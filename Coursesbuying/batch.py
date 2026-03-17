import re
import asyncio
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
    # Public: https://t.me/channel/123 or https://t.me/c/123456789/123
    if "t.me/c/" in link:
        # Private
        match = re.match(r"https://t\.me/c/(\d+)/(\d+)", link)
        if match:
            chat_id = int("-100" + match.group(1))
            return chat_id, int(match.group(2))
    else:
        # Public
        match = re.match(r"https://t\.me/([^/]+)/(\d+)", link)
        if match:
            return match.group(1), int(match.group(2))
    return None, None


# Helper to get Chat ID from forward safely
def get_forward_chat_id(message: Message):
    if message.forward_from_chat:
        return message.forward_from_chat.id
    # Pyrogram 2.x deprecation fallback
    if getattr(message, "forward_origin", None) and getattr(message.forward_origin, "chat", None):
        return message.forward_origin.chat.id
    return None

def get_msg_info(message: Message):
    """Extracts chat_id and msg_id from forward or link."""
    # Check forward
    fwd_chat_id = get_forward_chat_id(message)
    if fwd_chat_id:
        return fwd_chat_id, message.forward_from_message_id
    elif message.text and "t.me/" in message.text:
        return parse_msg_link(message.text)
    return None, None

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
        del BATCH_STATE[user_id] # Clear state
        
        # Ensure range is correct
        if start_id > end_id:
            start_id, end_id = end_id, start_id

        sts = await message.reply_text("<b>🚀 Batch Processing Started...</b>")
        
        # Get User Session for restricted content
        user_sess = await db.get_session(user_id)
        if not user_sess:
            return await sts.edit_text("<b>❌ You must /login first to use batch mode for restricted content.</b>")

        # Use a unique session name to avoid conflicts
        import time
        acc = Client(f"batch_{user_id}_{int(time.time())}", session_string=user_sess, api_hash=API_HASH, api_id=API_ID, in_memory=True)
        
        videos_count = 0
        try:
            await acc.connect()
            
            # Resolve peer
            try:
                chat = await acc.get_chat(chat_id)
                chat_id = chat.id
            except Exception as e:
                logger.error(f"Failed to resolve chat {chat_id}: {e}")
            
            message_ids = list(range(start_id, end_id + 1))
            
            # Process one by one to handle mix of restricted/unrestricted cleanly and allow fallback
            # (Fetching in chunks is good, but processing one by one allows falling back for specific failures)
            
            # Process one by one with retry mechanism for FloodWait
            for i in range(0, len(message_ids), 20):
                chunk = message_ids[i:i+20]
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
                            continue
                        
                        # Check for any media or text
                        is_target = False
                        if msg.media or msg.text:
                            is_target = True
                        
                        if is_target:
                            retry_count = 0
                            while retry_count < 3:
                                try:
                                    # 1. Try Direct Forward (Fastest)
                                    await acc.forward_messages(user_id, chat_id, [msg.id])
                                    videos_count += 1
                                    await asyncio.sleep(0.5)
                                    break
                                except FloodWait as fw:
                                    await asyncio.sleep(fw.value + 5)
                                    retry_count = 0 # Reset retry on flood wait to keep trying
                                    continue
                                except Exception as e:
                                    # 2. Fallback to Download -> Upload
                                    error_str = str(e)
                                    if "CHAT_FORWARDS_RESTRICTED" in error_str or "400" in error_str:
                                        try:
                                            # Status update
                                            # await sts.edit_text(f"<b>⚠️ Restricted Content Detected. Downloading... ({videos_count} done)</b>")
                                            # (Commented out to reduce flood wait on edits)

                                            # Handle Text
                                            if msg.text:
                                                await client.send_message(user_id, msg.text, entities=msg.entities, parse_mode=enums.ParseMode.HTML)
                                                videos_count += 1
                                                break

                                            # Download media
                                            file_path = await acc.download_media(msg)
                                            
                                            # Upload to user based on type
                                            caption = msg.caption or ""
                                            
                                            if msg.photo:
                                                await client.send_photo(user_id, file_path, caption=caption)
                                            elif msg.video:
                                                thumb_path = None
                                                try:
                                                    if msg.video.thumbs:
                                                        thumb_path = await acc.download_media(msg.video.thumbs[0].file_id)
                                                except:
                                                    pass
                                                await client.send_video(user_id, file_path, caption=caption, supports_streaming=True, thumb=thumb_path)
                                                if thumb_path and os.path.exists(thumb_path):
                                                    os.remove(thumb_path)
                                            elif msg.audio:
                                                thumb_path = None
                                                try:
                                                    if msg.audio.thumbs:
                                                        thumb_path = await acc.download_media(msg.audio.thumbs[0].file_id)
                                                except:
                                                    pass
                                                await client.send_audio(user_id, file_path, caption=caption, thumb=thumb_path)
                                                if thumb_path and os.path.exists(thumb_path):
                                                    os.remove(thumb_path)
                                            elif msg.voice:
                                                await client.send_voice(user_id, file_path, caption=caption)
                                            elif msg.document:
                                                thumb_path = None
                                                try:
                                                    if msg.document.thumbs:
                                                        thumb_path = await acc.download_media(msg.document.thumbs[0].file_id)
                                                except:
                                                    pass
                                                await client.send_document(user_id, file_path, caption=caption, thumb=thumb_path)
                                                if thumb_path and os.path.exists(thumb_path):
                                                    os.remove(thumb_path)
                                            elif msg.sticker:
                                                await client.send_sticker(user_id, file_path)
                                            elif msg.animation:
                                                await client.send_animation(user_id, file_path, caption=caption) 
                                            else:
                                                await client.send_document(user_id, file_path, caption=caption)
                                            
                                            # Cleanup
                                            import os
                                            if os.path.exists(file_path):
                                                os.remove(file_path)
                                                
                                            videos_count += 1
                                            break
                                        except FloodWait as fw:
                                            await asyncio.sleep(fw.value + 5)
                                            continue
                                        except Exception as dl_e:
                                            logger.error(f"Download fallback failed: {dl_e}")
                                            retry_count += 1
                                    else:
                                        logger.error(f"Forward failed: {e}")
                                        retry_count += 1
                        
                except Exception as e:
                    logger.error(f"Error in batch loop: {e}")
            
            await sts.edit_text(f"<b>✅ Batch Complete! Sent `{videos_count}` messages.</b>")
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
