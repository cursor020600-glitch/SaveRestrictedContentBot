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

BATCH_STATE = {}

def parse_msg_link(link):
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


# ─── Progress Callback ────────────────────────────────────────────────────────

def make_progress_callback(sts: Message, action: str, file_name: str = ""):
    """
    Returns a progress callback for download/upload.
    action: "📥 Downloading" or "📤 Uploading"
    """
    last_edit = {"time": 0}

    async def progress(current, total):
        now = time.time()
        # Edit max once every 5 seconds to avoid FloodWait
        if now - last_edit["time"] < 5:
            return
        last_edit["time"] = now

        if total == 0:
            return

        percent = current * 100 / total
        done = current / (1024 * 1024)      # MB done
        total_mb = total / (1024 * 1024)    # MB total

        elapsed = now - last_edit.get("start", now)
        speed = (current / elapsed / 1024) if elapsed > 0 else 0  # KB/s
        speed_mb = speed / 1024  # MB/s

        eta_sec = ((total - current) / (speed * 1024)) if speed > 0 else 0
        eta_str = f"{int(eta_sec)}s" if eta_sec < 60 else f"{int(eta_sec//60)}m {int(eta_sec%60)}s"

        # Progress bar
        filled = int(percent / 10)
        bar = "█" * filled + "░" * (10 - filled)

        text = (
            f"<b>{action}</b>\n"
            f"{'📄 ' + file_name if file_name else ''}\n\n"
            f"<code>[{bar}] {percent:.1f}%</code>\n\n"
            f"✅ Done: <b>{done:.2f} MB</b> / <b>{total_mb:.2f} MB</b>\n"
            f"⚡ Speed: <b>{speed_mb:.2f} MB/s</b>\n"
            f"⏳ ETA: <b>{eta_str}</b>"
        )
        try:
            await sts.edit_text(text, parse_mode=enums.ParseMode.HTML)
        except Exception:
            pass

    # Store start time on first call
    last_edit["start"] = time.time()
    return progress


# ─── Bot Commands ─────────────────────────────────────────────────────────────

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
        del BATCH_STATE[user_id]

        if start_id > end_id:
            start_id, end_id = end_id, start_id

        sts = await message.reply_text("<b>🚀 Batch Processing Started...</b>")

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
                        except Exception as e:
                            logger.error(f"Error fetching chunk: {e}")
                            break

                    if not isinstance(msgs, list):
                        msgs = [msgs]

                    for msg in msgs:
                        if not msg or msg.empty:
                            continue
                        if not (msg.media or msg.text):
                            continue

                        retry_count = 0
                        while retry_count < 3:
                            try:
                                await acc.forward_messages(user_id, chat_id, [msg.id])
                                videos_count += 1
                                await asyncio.sleep(0.5)
                                break
                            except FloodWait as fw:
                                await asyncio.sleep(fw.value + 5)
                                retry_count = 0
                            except Exception as e:
                                error_str = str(e)
                                if "CHAT_FORWARDS_RESTRICTED" in error_str or "400" in error_str:
                                    try:
                                        # ── Text ──
                                        if msg.text:
                                            await client.send_message(user_id, msg.text, entities=msg.entities)
                                            videos_count += 1
                                            break

                                        caption = msg.caption or ""

                                        # ── Get file name for display ──
                                        file_name = ""
                                        if msg.document and msg.document.file_name:
                                            file_name = msg.document.file_name
                                        elif msg.audio and msg.audio.file_name:
                                            file_name = msg.audio.file_name
                                        elif msg.video:
                                            file_name = "video"
                                        elif msg.photo:
                                            file_name = "photo"

                                        # ── Download with Progress ──
                                        dl_progress = make_progress_callback(sts, "📥 Downloading", file_name)
                                        file_path = await acc.download_media(msg, progress=dl_progress)

                                        # ── Upload with Progress ──
                                        up_progress = make_progress_callback(sts, "📤 Uploading", file_name)

                                        if msg.photo:
                                            await client.send_photo(user_id, file_path, caption=caption, progress=up_progress)

                                        elif msg.video:
                                            thumb_path = None
                                            try:
                                                if msg.video.thumbs:
                                                    thumb_path = await acc.download_media(msg.video.thumbs[0].file_id)
                                            except:
                                                pass
                                            await client.send_video(
                                                user_id, file_path, caption=caption,
                                                supports_streaming=True, thumb=thumb_path,
                                                progress=up_progress
                                            )
                                            if thumb_path and os.path.exists(thumb_path):
                                                os.remove(thumb_path)

                                        elif msg.audio:
                                            thumb_path = None
                                            try:
                                                if msg.audio.thumbs:
                                                    thumb_path = await acc.download_media(msg.audio.thumbs[0].file_id)
                                            except:
                                                pass
                                            await client.send_audio(
                                                user_id, file_path, caption=caption,
                                                thumb=thumb_path, progress=up_progress
                                            )
                                            if thumb_path and os.path.exists(thumb_path):
                                                os.remove(thumb_path)

                                        elif msg.voice:
                                            await client.send_voice(user_id, file_path, caption=caption, progress=up_progress)

                                        elif msg.document:
                                            thumb_path = None
                                            try:
                                                if msg.document.thumbs:
                                                    thumb_path = await acc.download_media(msg.document.thumbs[0].file_id)
                                            except:
                                                pass
                                            await client.send_document(
                                                user_id, file_path, caption=caption,
                                                thumb=thumb_path, progress=up_progress
                                            )
                                            if thumb_path and os.path.exists(thumb_path):
                                                os.remove(thumb_path)

                                        elif msg.sticker:
                                            await client.send_sticker(user_id, file_path)

                                        elif msg.animation:
                                            await client.send_animation(user_id, file_path, caption=caption, progress=up_progress)

                                        else:
                                            await client.send_document(user_id, file_path, caption=caption, progress=up_progress)

                                        if os.path.exists(file_path):
                                            os.remove(file_path)

                                        videos_count += 1
                                        break

                                    except FloodWait as fw:
                                        await asyncio.sleep(fw.value + 5)
                                    except Exception as dl_e:
                                        logger.error(f"Download fallback failed: {dl_e}")
                                        retry_count += 1
                                else:
                                    logger.error(f"Forward failed: {e}")
                                    retry_count += 1

                except Exception as e:
                    logger.error(f"Error in batch loop: {e}")

            await sts.edit_text(f"<b>✅ Batch Complete! Sent <code>{videos_count}</code> messages.</b>")

        except Exception as e:
            await sts.edit_text(f"<b>❌ Error: {e}</b>")
        finally:
            try:
                await acc.disconnect()
            except:
                pass


@Client.on_message(filters.command(["cancel", "cancell"]) & filters.private)
async def cancel_batch_cmd(client: Client, message: Message):
    user_id = message.from_user.id
    if user_id in BATCH_STATE:
        del BATCH_STATE[user_id]
        await message.reply_text("<b>❌ Batch Process Cancelled Successfully.</b>", parse_mode=enums.ParseMode.HTML)
    else:
        await message.reply_text("<b>❌ No Active Batch Process To Cancel.</b>", parse_mode=enums.ParseMode.HTML)
```

---

## Ab Progress aise dikhega:
```
# 📥 Downloading
# 📄 lecture_video.mp4

# [████████░░] 82.4%

# ✅ Done: 124.30 MB / 150.80 MB
# ⚡ Speed: 3.45 MB/s
# ⏳ ETA: 7s
# ```

# Aur upload ke time:
# ```
# 📤 Uploading
# 📄 lecture_video.mp4

# [██████░░░░] 60.1%

# ✅ Done: 90.15 MB / 150.80 MB
# ⚡ Speed: 2.10 MB/s
# ⏳ ETA: 28s
