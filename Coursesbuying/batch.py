import re
import asyncio
import os
import time
import tempfile
import shutil
from pyrogram import Client, filters, enums
from pyrogram.types import Message
from pyrogram.errors import FloodWait
from config import API_ID, API_HASH
from database.db import db
from logger import LOGGER

logger = LOGGER(__name__)

BATCH_STATE = {}

# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def parse_msg_link(link):
    if "t.me/c/" in link:
        match = re.match(r"https://t\.me/c/(\d+)/(\d+)", link)
        if match:
            return int("-100" + match.group(1)), int(match.group(2))
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


# ─────────────────────────────────────────────
# /batch command
# ─────────────────────────────────────────────

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
    return message.from_user and message.from_user.id in BATCH_STATE

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
        return await message.reply_text(
            "<b>✅ First message saved!\n\n"
            "Now forward the batch LAST message from your batch channel (with forward tag)\n"
            "OR\n"
            "Send me the batch LAST message link from your batch channel.</b>",
            parse_mode=enums.ParseMode.HTML
        )

    elif state["step"] == "WAITLAST":
        if chat_id != state["chat_id"]:
            return await message.reply_text(
                "<b>❌ The last message must be from the same chat as the first.</b>"
            )

        start_id = state["start_id"]
        end_id = msg_id

        # ── State turant delete karo — double trigger se bachne ke liye
        del BATCH_STATE[user_id]

        if start_id > end_id:
            start_id, end_id = end_id, start_id

        total_msgs = end_id - start_id + 1
        sts = await message.reply_text(
            f"<b>🚀 Batch Processing Started...</b>\n"
            f"<b>📊 Total Messages: {total_msgs}</b>",
            parse_mode=enums.ParseMode.HTML
        )

        user_sess = await db.get_session(user_id)
        if not user_sess:
            return await sts.edit_text(
                "<b>❌ You must /login first to use batch mode.</b>",
                parse_mode=enums.ParseMode.HTML
            )

        # ── FIX: in_memory=True causes "Cannot operate on a closed database"
        #    Use a real temp workdir + no_updates=True to avoid SQLite conflicts
        workdir = tempfile.mkdtemp(prefix=f"btch_{user_id}_")

        acc = Client(
            name="usersession",
            session_string=user_sess,
            api_hash=API_HASH,
            api_id=API_ID,
            workdir=workdir,
            no_updates=True   # Batch client ko live updates nahi chahiye
        )

        sent_count = 0
        failed_count = 0
        processed_count = 0
        start_time = time.time()
        last_edit_time = 0

        async def update_progress(force=False):
            nonlocal last_edit_time
            now = time.time()
            if not force and (now - last_edit_time < 4):
                return
            last_edit_time = now
            elapsed = now - start_time
            speed = sent_count / elapsed if elapsed > 0 else 0
            remaining = total_msgs - processed_count
            eta = remaining / speed if speed > 0 else 0
            pbar = make_progress_bar(processed_count, total_msgs)
            pct = int(processed_count * 100 / total_msgs) if total_msgs > 0 else 0
            try:
                await sts.edit_text(
                    f"<b>⚙️ Processing Batch...</b>\n\n"
                    f"<b>[{pbar}] {pct}%</b>\n\n"
                    f"✅ <b>Sent:</b> {sent_count}/{total_msgs}\n"
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
            logger.info(f"[Batch] acc connected | user={user_id}")

            # Chat resolve karo
            try:
                chat = await acc.get_chat(chat_id)
                chat_id = chat.id
                logger.info(f"[Batch] chat resolved → {chat_id}")
            except Exception as e:
                logger.error(f"[Batch] chat resolve failed: {e}")

            message_ids = list(range(start_id, end_id + 1))

            for i in range(0, len(message_ids), 20):
                chunk = message_ids[i:i + 20]

                # ── Fetch chunk
                msgs = []
                for attempt in range(5):
                    try:
                        result = await acc.get_messages(chat_id, chunk)
                        msgs = result if isinstance(result, list) else [result]
                        logger.info(f"[Batch] chunk {i}: fetched {len(msgs)} msgs")
                        break
                    except FloodWait as fw:
                        logger.warning(f"[Batch] FloodWait fetch: {fw.value}s")
                        await asyncio.sleep(fw.value + 3)
                    except Exception as e:
                        logger.error(f"[Batch] fetch error attempt {attempt+1}: {e}")
                        await asyncio.sleep(2)

                for msg in msgs:
                    if not msg or msg.empty:
                        processed_count += 1
                        await update_progress()
                        continue

                    if not (msg.media or msg.text):
                        processed_count += 1
                        await update_progress()
                        continue

                    logger.info(f"[Batch] processing msg {msg.id}")

                    # ── Step 1: Direct Forward
                    forward_ok = False
                    for _ in range(10):  # Sirf FloodWait retry
                        try:
                            await acc.forward_messages(
                                chat_id=user_id,
                                from_chat_id=chat_id,
                                message_ids=msg.id
                            )
                            forward_ok = True
                            logger.info(f"[Batch] ✅ forwarded msg {msg.id}")
                            break
                        except FloodWait as fw:
                            logger.warning(f"[Batch] FloodWait forward {msg.id}: {fw.value}s")
                            await asyncio.sleep(fw.value + 3)
                        except Exception as e:
                            logger.warning(f"[Batch] forward failed {msg.id}: {e} → fallback")
                            break  # Non-FloodWait = fallback, no retry

                    if forward_ok:
                        sent_count += 1
                        processed_count += 1
                        await update_progress()
                        await asyncio.sleep(0.5)
                        continue

                    # ── Step 2: Download → Upload fallback
                    fallback_ok = False
                    file_path = None
                    thumb_path = None

                    for _ in range(10):  # Sirf FloodWait retry
                        try:
                            caption = msg.caption or ""

                            # Pure text message
                            if msg.text and not msg.media:
                                await client.send_message(user_id, msg.text, entities=msg.entities)
                                fallback_ok = True
                                logger.info(f"[Batch] ✅ sent text {msg.id} via fallback")
                                break

                            # Download media
                            file_path = await acc.download_media(msg)
                            if not file_path:
                                logger.error(f"[Batch] download returned None for msg {msg.id}")
                                break

                            logger.info(f"[Batch] downloaded {msg.id} → {file_path}")

                            async def try_thumb(media_obj):
                                nonlocal thumb_path
                                try:
                                    if media_obj and getattr(media_obj, "thumbs", None):
                                        thumb_path = await acc.download_media(media_obj.thumbs[0].file_id)
                                except Exception:
                                    thumb_path = None

                            if msg.photo:
                                await client.send_photo(user_id, file_path, caption=caption)
                            elif msg.video:
                                await try_thumb(msg.video)
                                await client.send_video(
                                    user_id, file_path, caption=caption,
                                    supports_streaming=True, thumb=thumb_path
                                )
                            elif msg.audio:
                                await try_thumb(msg.audio)
                                await client.send_audio(user_id, file_path, caption=caption, thumb=thumb_path)
                            elif msg.voice:
                                await client.send_voice(user_id, file_path, caption=caption)
                            elif msg.document:
                                await try_thumb(msg.document)
                                await client.send_document(user_id, file_path, caption=caption, thumb=thumb_path)
                            elif msg.sticker:
                                await client.send_sticker(user_id, file_path)
                            elif msg.animation:
                                await client.send_animation(user_id, file_path, caption=caption)
                            else:
                                await client.send_document(user_id, file_path, caption=caption)

                            fallback_ok = True
                            logger.info(f"[Batch] ✅ sent {msg.id} via download-upload")
                            break

                        except FloodWait as fw:
                            logger.warning(f"[Batch] FloodWait fallback {msg.id}: {fw.value}s")
                            await asyncio.sleep(fw.value + 3)
                        except Exception as e:
                            logger.error(f"[Batch] fallback FAILED {msg.id}: {e}")
                            break  # Retry nahi, skip karo

                    # Cleanup
                    for path in [file_path, thumb_path]:
                        if path and os.path.exists(path):
                            try:
                                os.remove(path)
                            except Exception:
                                pass

                    if fallback_ok:
                        sent_count += 1
                    else:
                        failed_count += 1
                        logger.error(f"[Batch] ❌ msg {msg.id} completely failed")

                    processed_count += 1
                    await update_progress()
                    await asyncio.sleep(0.5)

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
            logger.error(f"[Batch] top-level error user={user_id}: {e}", exc_info=True)
            try:
                await sts.edit_text(f"<b>❌ Error: {e}</b>", parse_mode=enums.ParseMode.HTML)
            except Exception:
                pass

        finally:
            try:
                await acc.disconnect()
                logger.info(f"[Batch] acc disconnected | user={user_id}")
            except Exception:
                pass
            try:
                shutil.rmtree(workdir, ignore_errors=True)
            except Exception:
                pass


# ─────────────────────────────────────────────
# /cancel command
# ─────────────────────────────────────────────

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
