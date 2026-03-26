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

# User state storage: {user_id: {"step": "WAITFIRST", "chat_id": None, "start_id": None}}
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
    """Extracts chat_id and msg_id from forward or link."""
    fwd_chat_id = get_forward_chat_id(message)
    if fwd_chat_id:
        return fwd_chat_id, message.forward_from_message_id
    elif message.text and "t.me/" in message.text:
        return parse_msg_link(message.text)
    return None, None

def format_time(seconds):
    """Seconds ko human readable format mein convert karo."""
    if seconds < 60:
        return f"{int(seconds)}s"
    elif seconds < 3600:
        return f"{int(seconds // 60)}m {int(seconds % 60)}s"
    else:
        return f"{int(seconds // 3600)}h {int((seconds % 3600) // 60)}m"

def make_progress_bar(current, total, length=10):
    """Simple text progress bar banao."""
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

@Client.on_message(filters.private & batch_filter & ~filters.command(["batch", "start", "cancel", "cancell"]))
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
        del BATCH_STATE[user_id]  # Clear state immediately

        if start_id > end_id:
            start_id, end_id = end_id, start_id

        total_msgs = end_id - start_id + 1
        sts = await message.reply_text(
            f"<b>🚀 Batch Processing Started...\n"
            f"📊 Total Messages: {total_msgs}</b>",
            parse_mode=enums.ParseMode.HTML
        )

        # Get User Session
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

        sent_count = 0
        failed_count = 0
        processed_count = 0  # Kitne messages try kiye (sent + skipped + failed)
        start_time = time.time()
        last_edit_time = 0  # Status message ko baar baar edit hone se rokne ke liye

        async def update_status():
            """Progress status update karo, but sirf har 3 second mein."""
            nonlocal last_edit_time
            now = time.time()
            if now - last_edit_time < 3:  # Har 3 second mein ek baar edit karo
                return
            last_edit_time = now

            elapsed = now - start_time
            speed = sent_count / elapsed if elapsed > 0 else 0  # msgs per second

            remaining = total_msgs - processed_count
            eta = remaining / speed if speed > 0 else 0

            progress_bar = make_progress_bar(processed_count, total_msgs)

            percent = int(processed_count * 100 / total_msgs) if total_msgs > 0 else 0

            status_text = (
                f"<b>⚙️ Batch Processing...</b>\n\n"
                f"<b>[{progress_bar}] {percent}%</b>\n\n"
                f"✅ <b>Sent:</b> {sent_count}/{total_msgs}\n"
                f"❌ <b>Failed:</b> {failed_count}\n"
                f"⚡ <b>Speed:</b> {speed:.2f} msg/s\n"
                f"⏱ <b>Elapsed:</b> {format_time(elapsed)}\n"
                f"🕐 <b>ETA:</b> {format_time(eta)}"
            )
            try:
                await sts.edit_text(status_text, parse_mode=enums.ParseMode.HTML)
            except Exception:
                pass  # Edit fail ho toh ignore karo

        try:
            await acc.connect()

            # Chat resolve karo
            try:
                chat = await acc.get_chat(chat_id)
                chat_id = chat.id
            except Exception as e:
                logger.error(f"Failed to resolve chat {chat_id}: {e}")

            message_ids = list(range(start_id, end_id + 1))

            for i in range(0, len(message_ids), 20):
                chunk = message_ids[i:i + 20]

                # Chunk fetch karo with FloodWait handling
                msgs = []
                flood_retries = 0
                while flood_retries < 5:
                    try:
                        msgs = await acc.get_messages(chat_id, chunk)
                        break
                    except FloodWait as fw:
                        logger.warning(f"FloodWait while fetching: {fw.value}s")
                        await asyncio.sleep(fw.value + 5)
                        flood_retries += 1
                    except Exception as e:
                        logger.error(f"Error fetching chunk: {e}")
                        break

                if not isinstance(msgs, list):
                    msgs = [msgs]

                for msg in msgs:
                    if not msg or msg.empty:
                        processed_count += 1
                        await update_status()
                        continue

                    if not (msg.media or msg.text):
                        processed_count += 1
                        await update_status()
                        continue

                    # ===== FIX: Ek message ke liye sirf ek baar try karo =====
                    # Pehle direct forward try karo
                    forward_success = False
                    flood_wait_retries = 0

                    while flood_wait_retries < 10:  # Sirf FloodWait ke liye retry
                        try:
                            await acc.forward_messages(user_id, chat_id, [msg.id])
                            sent_count += 1
                            forward_success = True
                            break
                        except FloodWait as fw:
                            # FloodWait aaye toh wait karo aur SAME message retry karo
                            logger.warning(f"FloodWait on forward: {fw.value}s")
                            await asyncio.sleep(fw.value + 5)
                            flood_wait_retries += 1
                            continue
                        except Exception as e:
                            # Forward fail, fallback try karenge
                            break

                    # Agar forward fail hua toh download->upload fallback
                    if not forward_success:
                        fallback_success = False
                        flood_wait_retries = 0

                        while flood_wait_retries < 10:  # Sirf FloodWait ke liye retry
                            try:
                                # Text message
                                if msg.text:
                                    await client.send_message(
                                        user_id, msg.text,
                                        entities=msg.entities,
                                        parse_mode=enums.ParseMode.HTML
                                    )
                                    sent_count += 1
                                    fallback_success = True
                                    break

                                # Media download karo
                                file_path = await acc.download_media(msg)
                                caption = msg.caption or ""
                                thumb_path = None

                                # Thumbnail download helper
                                async def get_thumb(media_obj):
                                    nonlocal thumb_path
                                    try:
                                        if media_obj and media_obj.thumbs:
                                            thumb_path = await acc.download_media(media_obj.thumbs[0].file_id)
                                    except Exception:
                                        thumb_path = None

                                # Type ke hisab se send karo
                                if msg.photo:
                                    await client.send_photo(user_id, file_path, caption=caption)
                                elif msg.video:
                                    await get_thumb(msg.video)
                                    await client.send_video(
                                        user_id, file_path, caption=caption,
                                        supports_streaming=True, thumb=thumb_path
                                    )
                                elif msg.audio:
                                    await get_thumb(msg.audio)
                                    await client.send_audio(user_id, file_path, caption=caption, thumb=thumb_path)
                                elif msg.voice:
                                    await client.send_voice(user_id, file_path, caption=caption)
                                elif msg.document:
                                    await get_thumb(msg.document)
                                    await client.send_document(user_id, file_path, caption=caption, thumb=thumb_path)
                                elif msg.sticker:
                                    await client.send_sticker(user_id, file_path)
                                elif msg.animation:
                                    await client.send_animation(user_id, file_path, caption=caption)
                                else:
                                    await client.send_document(user_id, file_path, caption=caption)

                                sent_count += 1
                                fallback_success = True

                                # File cleanup
                                if file_path and os.path.exists(file_path):
                                    os.remove(file_path)
                                if thumb_path and os.path.exists(thumb_path):
                                    os.remove(thumb_path)

                                break  # Success, loop se bahar

                            except FloodWait as fw:
                                logger.warning(f"FloodWait on fallback: {fw.value}s")
                                await asyncio.sleep(fw.value + 5)
                                flood_wait_retries += 1
                                continue
                            except Exception as dl_e:
                                logger.error(f"Fallback failed for msg {msg.id}: {dl_e}")
                                # Cleanup attempt
                                try:
                                    if 'file_path' in locals() and file_path and os.path.exists(file_path):
                                        os.remove(file_path)
                                    if thumb_path and os.path.exists(thumb_path):
                                        os.remove(thumb_path)
                                except Exception:
                                    pass
                                break  # Ye message skip karo, agle pe jao

                        if not fallback_success:
                            failed_count += 1

                    processed_count += 1
                    await update_status()
                    await asyncio.sleep(0.5)  # Rate limit se bachne ke liye

            # Final status
            elapsed = time.time() - start_time
            await sts.edit_text(
                f"<b>✅ Batch Complete!</b>\n\n"
                f"✅ <b>Sent:</b> {sent_count}\n"
                f"❌ <b>Failed:</b> {failed_count}\n"
                f"📊 <b>Total:</b> {total_msgs}\n"
                f"⏱ <b>Time Taken:</b> {format_time(elapsed)}",
                parse_mode=enums.ParseMode.HTML
            )

        except Exception as e:
            await sts.edit_text(f"<b>❌ Error: {e}</b>", parse_mode=enums.ParseMode.HTML)
            logger.error(f"Batch error for user {user_id}: {e}")
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
