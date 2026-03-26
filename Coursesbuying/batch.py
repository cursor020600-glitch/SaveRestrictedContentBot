import re
import asyncio
import os
import time
from pyrogram import Client, filters, enums
from pyrogram.types import Message
from pyrogram.errors import FloodWait, AuthKeyUnregistered, UserDeactivated, UserDeactivatedBan
from config import API_ID, API_HASH
from database.db import db
from logger import LOGGER

logger = LOGGER(__name__)

# User state storage
BATCH_STATE = {}


def parse_msg_link(link):
    """Parses a telegram message link to extract chat_id and message_id."""
    if "t.me/c/" in link:
        match = re.match(r"https://t\.me/c/(\d+)/(\d+)", link)
        if match:
            chat_id = int("-100" + match.group(1))
            return chat_id, int(match.group(2))
    else:
        match = re.match(r"https://t\.me/([^/]+)/(\d+)", link)
        if match:
            return match.group(1), int(match.group(2))
    return None, None


def get_forward_chat_id(message: Message):
    if message.forward_from_chat:
        return message.forward_from_chat.id
    if getattr(message, "forward_origin", None) and getattr(message.forward_origin, "chat", None):
        return message.forward_origin.chat.id
    return None


def get_msg_info(message: Message):
    fwd_chat_id = get_forward_chat_id(message)
    if fwd_chat_id:
        return fwd_chat_id, message.forward_from_message_id
    elif message.text and "t.me/" in message.text:
        return parse_msg_link(message.text)
    return None, None


def format_time(seconds):
    if seconds < 60:
        return f"{int(seconds)}s"
    elif seconds < 3600:
        return f"{int(seconds // 60)}m {int(seconds % 60)}s"
    else:
        return f"{int(seconds // 3600)}h {int((seconds % 3600) // 60)}m"


def make_progress_bar(current, total, length=10):
    if total == 0:
        return "▓" * length
    filled = int(length * current / total)
    return "▓" * filled + "░" * (length - filled)


@Client.on_message(filters.command("batch") & filters.private)
async def batch_cmd(client: Client, message: Message):
    user_id = message.from_user.id
    BATCH_STATE[user_id] = {"step": "WAITFIRST"}
    await message.reply_text(
        "<b>Forward the batch FIRST message from your batch channel (with forward tag)\n"
        "OR\n"
        "Send me the batch FIRST message link from your batch channel.</b>",
        parse_mode=enums.ParseMode.HTML
    )


async def is_batch_waiting(_, __, message):
    return message.from_user.id in BATCH_STATE

batch_filter = filters.create(is_batch_waiting)


@Client.on_message(filters.private & batch_filter & ~filters.command(["batch", "start", "cancel"]))
async def handle_batch_responses(client: Client, message: Message):
    user_id = message.from_user.id
    state = BATCH_STATE[user_id]

    chat_id, msg_id = get_msg_info(message)

    if chat_id is None or msg_id is None:
        return await message.reply_text("<b>❌ Please provide a valid forwarded message or Telegram link.</b>")

    if state["step"] == "WAITFIRST":
        state["step"] = "WAITLAST"
        state["chat_id"] = chat_id
        state["start_id"] = msg_id
        await message.reply_text(
            "<b>Forward the batch LAST message from your batch channel (with forward tag)\n"
            "OR\n"
            "Send me the batch LAST message link from your batch channel.</b>",
            parse_mode=enums.ParseMode.HTML
        )

    elif state["step"] == "WAITLAST":
        if chat_id != state["chat_id"]:
            return await message.reply_text("<b>❌ The last message must be from the same chat as the first.</b>")

        start_id = state["start_id"]
        end_id = msg_id
        del BATCH_STATE[user_id]  # State clear karo

        if start_id > end_id:
            start_id, end_id = end_id, start_id

        total_msgs = end_id - start_id + 1
        sts = await message.reply_text(
            f"<b>🚀 Batch Processing Started...\n📊 Total Messages: {total_msgs}</b>",
            parse_mode=enums.ParseMode.HTML
        )

        user_sess = await db.get_session(user_id)
        if not user_sess:
            return await sts.edit_text("<b>❌ You must /login first to use batch mode for restricted content.</b>")

        acc = Client(
            f"batch_{user_id}_{int(time.time())}",
            session_string=user_sess,
            api_hash=API_HASH,
            api_id=API_ID,
            in_memory=True
        )

        videos_count = 0
        failed_count = 0
        processed_count = 0
        start_time = time.time()
        last_edit_time = 0

        async def update_progress():
            nonlocal last_edit_time
            now = time.time()
            if now - last_edit_time < 4:
                return
            last_edit_time = now
            elapsed = now - start_time
            speed = videos_count / elapsed if elapsed > 0 else 0
            remaining = total_msgs - processed_count
            eta = remaining / speed if speed > 0 else 0
            pbar = make_progress_bar(processed_count, total_msgs)
            pct = int(processed_count * 100 / total_msgs) if total_msgs > 0 else 0
            try:
                await sts.edit_text(
                    f"<b>⚙️ Processing Batch...</b>\n\n"
                    f"<b>[{pbar}] {pct}%</b>\n\n"
                    f"✅ <b>Sent:</b> {videos_count}/{total_msgs}\n"
                    f"❌ <b>Failed:</b> {failed_count}\n"
                    f"⚡ <b>Speed:</b> {speed:.2f} msg/s\n"
                    f"⏱ <b>Elapsed:</b> {format_time(elapsed)}\n"
                    f"🕐 <b>ETA:</b> {format_time(eta)}",
                    parse_mode=enums.ParseMode.HTML
                )
            except Exception:
                pass

        try:
            await acc.connect()

            try:
                chat = await acc.get_chat(chat_id)
                chat_id = chat.id
            except Exception as e:
                logger.error(f"Failed to resolve chat {chat_id}: {e}")

            message_ids = list(range(start_id, end_id + 1))

            for i in range(0, len(message_ids), 20):
                chunk = message_ids[i:i + 20]
                try:
                    msgs = []
                    while True:
                        try:
                            msgs = await acc.get_messages(chat_id, chunk)
                            break
                        except FloodWait as fw:
                            await asyncio.sleep(fw.value + 5)
                            continue
                        except Exception as e:
                            logger.error(f"Error fetching chunk: {e}")
                            break

                    if not isinstance(msgs, list):
                        msgs = [msgs]

                    for msg in msgs:
                        if not msg or msg.empty:
                            processed_count += 1
                            await update_progress()
                            continue

                        if not (msg.media or msg.text):
                            processed_count += 1
                            await update_progress()
                            continue

                        # ── FIX 1: retry_count kabhi reset nahi hoga
                        # ── FIX 2: forward aur fallback ke liye alag loops
                        
                        sent = False  # Track karo ki yeh message gaya ya nahi

                        # ── STEP 1: Direct Forward try karo ──
                        retry_count = 0
                        while retry_count < 3:
                            try:
                                await acc.forward_messages(user_id, chat_id, [msg.id])
                                sent = True
                                break
                            except FloodWait as fw:
                                # FIX 1: retry_count reset NAHI karo — sirf wait karo
                                await asyncio.sleep(fw.value + 5)
                                continue  # Retry forward, count mat badhao
                            except Exception as e:
                                error_str = str(e)
                                logger.warning(f"Forward failed msg {msg.id}: {e}")
                                # Forward restriction ya koi aur error = fallback pe jao
                                break

                        # ── STEP 2: Agar forward nahi hua toh Download → Upload ──
                        if not sent:
                            file_path = None
                            thumb_path = None
                            try:
                                caption = msg.caption or ""

                                # Text message
                                if msg.text:
                                    await client.send_message(
                                        user_id, msg.text,
                                        entities=msg.entities,
                                        parse_mode=enums.ParseMode.HTML
                                    )
                                    sent = True

                                else:
                                    # Media download
                                    file_path = await acc.download_media(msg)

                                    if msg.photo:
                                        await client.send_photo(user_id, file_path, caption=caption)

                                    elif msg.video:
                                        try:
                                            if msg.video.thumbs:
                                                thumb_path = await acc.download_media(msg.video.thumbs[0].file_id)
                                        except Exception:
                                            pass
                                        await client.send_video(
                                            user_id, file_path, caption=caption,
                                            supports_streaming=True, thumb=thumb_path
                                        )

                                    elif msg.audio:
                                        try:
                                            if msg.audio.thumbs:
                                                thumb_path = await acc.download_media(msg.audio.thumbs[0].file_id)
                                        except Exception:
                                            pass
                                        await client.send_audio(
                                            user_id, file_path, caption=caption, thumb=thumb_path
                                        )

                                    elif msg.voice:
                                        await client.send_voice(user_id, file_path, caption=caption)

                                    elif msg.document:
                                        try:
                                            if msg.document.thumbs:
                                                thumb_path = await acc.download_media(msg.document.thumbs[0].file_id)
                                        except Exception:
                                            pass
                                        await client.send_document(
                                            user_id, file_path, caption=caption, thumb=thumb_path
                                        )

                                    elif msg.sticker:
                                        await client.send_sticker(user_id, file_path)

                                    elif msg.animation:
                                        await client.send_animation(user_id, file_path, caption=caption)

                                    else:
                                        await client.send_document(user_id, file_path, caption=caption)

                                    sent = True

                            except FloodWait as fw:
                                # FIX 2: Fallback mein FloodWait aaye toh wait karo
                                # Bahar NAHI jaana — yahan hi wait karke retry karo
                                await asyncio.sleep(fw.value + 5)
                                try:
                                    # Ek aur try — agar fir bhi fail toh failed count
                                    if file_path:
                                        # Re-upload try
                                        if msg.photo:
                                            await client.send_photo(user_id, file_path, caption=caption)
                                        elif msg.video:
                                            await client.send_video(user_id, file_path, caption=caption, supports_streaming=True)
                                        elif msg.audio:
                                            await client.send_audio(user_id, file_path, caption=caption)
                                        elif msg.voice:
                                            await client.send_voice(user_id, file_path, caption=caption)
                                        elif msg.document:
                                            await client.send_document(user_id, file_path, caption=caption)
                                        else:
                                            await client.send_document(user_id, file_path, caption=caption)
                                        sent = True
                                except Exception:
                                    pass

                            except Exception as dl_e:
                                logger.error(f"Download/upload fallback failed msg {msg.id}: {dl_e}")

                            finally:
                                # FIX 3: os import upar hai, cleanup hamesha hoga
                                if file_path and os.path.exists(file_path):
                                    try:
                                        os.remove(file_path)
                                    except Exception:
                                        pass
                                if thumb_path and os.path.exists(thumb_path):
                                    try:
                                        os.remove(thumb_path)
                                    except Exception:
                                        pass

                        if sent:
                            videos_count += 1
                        else:
                            failed_count += 1

                        processed_count += 1
                        await update_progress()
                        await asyncio.sleep(0.5)

                except Exception as e:
                    logger.error(f"Error in batch loop: {e}")

            # Final status
            elapsed = time.time() - start_time
            await sts.edit_text(
                f"<b>✅ Batch Complete!</b>\n\n"
                f"✅ <b>Sent:</b> {videos_count}\n"
                f"❌ <b>Failed:</b> {failed_count}\n"
                f"📊 <b>Total:</b> {total_msgs}\n"
                f"⏱ <b>Time Taken:</b> {format_time(elapsed)}",
                parse_mode=enums.ParseMode.HTML
            )

        except Exception as e:
            await sts.edit_text(f"<b>❌ Error: {e}</b>")
        finally:
            try:
                await acc.disconnect()
            except Exception:
                pass


@Client.on_message(filters.command(["cancel", "cancell"]) & filters.private)
async def cancel_batch_cmd(client: Client, message: Message):
    user_id = message.from_user.id
    if user_id in BATCH_STATE:
        del BATCH_STATE[user_id]
        await message.reply_text(
            "<b>❌ Batch Process Cancelled Successfully.</b>",
            parse_mode=enums.ParseMode.HTML
        )
    else:
        await message.reply_text(
            "<b>❌ No Active Batch Process To Cancel.</b>",
            parse_mode=enums.ParseMode.HTML
        )
