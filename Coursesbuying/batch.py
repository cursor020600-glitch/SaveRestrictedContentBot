import re
import asyncio
import time
import os
import json
from pyrogram import Client, filters, enums
from pyrogram.types import Message
from pyrogram.errors import FloodWait, AuthKeyUnregistered, UserDeactivated, UserDeactivatedBan
from config import API_ID, API_HASH
from database.db import db
from logger import LOGGER

logger = LOGGER(__name__)

# User state storage
BATCH_STATE = {}

# Active users tracking for cancel functionality
ACTIVE_USERS = {}
ACTIVE_USERS_FILE = "active_users.json"

# Progress tracking
P = {}

def sanitize(filename):
    """Sanitize filename to remove invalid characters"""
    return re.sub(r'[<>:"/\\|?*\']', '_', filename).strip(" .")[:255]

def load_active_users():
    """Load active users from file"""
    try:
        if os.path.exists(ACTIVE_USERS_FILE):
            with open(ACTIVE_USERS_FILE, 'r') as f:
                return json.load(f)
        return {}
    except Exception:
        return {}

async def save_active_users_to_file():
    """Save active users to file"""
    try:
        with open(ACTIVE_USERS_FILE, 'w') as f:
            json.dump(ACTIVE_USERS, f)
    except Exception as e:
        logger.error(f"Error saving active users: {e}")

async def add_active_batch(user_id: int, batch_info: dict):
    """Add user to active batch list"""
    ACTIVE_USERS[str(user_id)] = batch_info
    await save_active_users_to_file()

def is_user_active(user_id: int) -> bool:
    """Check if user has active batch"""
    return str(user_id) in ACTIVE_USERS

async def update_batch_progress(user_id: int, current: int, success: int):
    """Update batch progress"""
    if str(user_id) in ACTIVE_USERS:
        ACTIVE_USERS[str(user_id)]["current"] = current
        ACTIVE_USERS[str(user_id)]["success"] = success
        await save_active_users_to_file()

async def request_batch_cancel(user_id: int):
    """Request batch cancellation"""
    if str(user_id) in ACTIVE_USERS:
        ACTIVE_USERS[str(user_id)]["cancel_requested"] = True
        await save_active_users_to_file()
        return True
    return False

def should_cancel(user_id: int) -> bool:
    """Check if cancellation requested"""
    user_str = str(user_id)
    return user_str in ACTIVE_USERS and ACTIVE_USERS[user_str].get("cancel_requested", False)

async def remove_active_batch(user_id: int):
    """Remove user from active batch list"""
    if str(user_id) in ACTIVE_USERS:
        del ACTIVE_USERS[str(user_id)]
        await save_active_users_to_file()

def get_batch_info(user_id: int) -> dict:
    """Get batch info for user"""
    return ACTIVE_USERS.get(str(user_id))

# Load active users on startup
ACTIVE_USERS = load_active_users()

def parse_msg_link(link):
    """Parses a telegram message link to extract chat_id and message_id."""
    # Private: https://t.me/c/123456789/123
    if "t.me/c/" in link:
        match = re.match(r"https://t\.me/c/(\d+)/(\d+)", link)
        if match:
            chat_id = int("-100" + match.group(1))
            return chat_id, int(match.group(2))
    else:
        # Public: https://t.me/channel/123
        match = re.match(r"https://t\.me/([^/]+)/(\d+)", link)
        if match:
            return match.group(1), int(match.group(2))
    return None, None

def get_forward_chat_id(message: Message):
    """Get chat ID from forwarded message"""
    if message.forward_from_chat:
        return message.forward_from_chat.id
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

async def prog(current, total, client, chat_id, message_id, start_time):
    """Progress callback with better UI"""
    global P
    percentage = current / total * 100
    
    # Adaptive interval based on file size
    if total >= 100 * 1024 * 1024:
        interval = 10
    elif total >= 50 * 1024 * 1024:
        interval = 20
    elif total >= 10 * 1024 * 1024:
        interval = 30
    else:
        interval = 50
    
    step = int(percentage // interval) * interval
    
    if message_id not in P or P[message_id] != step or percentage >= 100:
        P[message_id] = step
        current_mb = current / (1024 * 1024)
        total_mb = total / (1024 * 1024)
        
        # Progress bar
        bar = '🟢' * int(percentage / 10) + '🔴' * (10 - int(percentage / 10))
        
        # Speed calculation
        elapsed_time = time.time() - start_time
        speed = current / elapsed_time / (1024 * 1024) if elapsed_time > 0 else 0
        
        # ETA calculation
        if speed > 0:
            eta_seconds = (total - current) / (speed * 1024 * 1024)
            eta = time.strftime('%M:%S', time.gmtime(eta_seconds))
        else:
            eta = '00:00'
        
        try:
            await client.edit_message_text(
                chat_id, message_id,
                f"__**Processing...**__\n\n{bar}\n\n"
                f"⚡**Completed**: {current_mb:.2f} MB / {total_mb:.2f} MB\n"
                f"📊 **Done**: {percentage:.2f}%\n"
                f"🚀 **Speed**: {speed:.2f} MB/s\n"
                f"⏳ **ETA**: {eta}"
            )
        except:
            pass
        
        if percentage >= 100:
            P.pop(message_id, None)

@Client.on_message(filters.command("batch") & filters.private)
async def batch_cmd(client: Client, message: Message):
    user_id = message.from_user.id
    
    # Check if user already has active batch
    if is_user_active(user_id):
        await message.reply_text(
            "<b>⚠️ You already have an active batch process.\n"
            "Use /cancel to stop it first.</b>",
            parse_mode=enums.ParseMode.HTML
        )
        return
    
    BATCH_STATE[user_id] = {"step": "WAITFIRST"}
    await message.reply_text(
        "<b>📤 Forward the batch FIRST message from your batch channel (with forward tag)\n"
        "OR\n"
        "📎 Send me the batch FIRST message link from your batch channel.</b>",
        parse_mode=enums.ParseMode.HTML
    )

async def is_batch_waiting(_, __, message):
    return message.from_user.id in BATCH_STATE

batch_filter = filters.create(is_batch_waiting)

@Client.on_message(filters.private & batch_filter & ~filters.command(["batch", "start", "cancel", "stop"]))
async def handle_batch_responses(client: Client, message: Message):
    user_id = message.from_user.id
    state = BATCH_STATE[user_id]
    
    chat_id, msg_id = get_msg_info(message)
    
    if chat_id is None or msg_id is None:
        return await message.reply_text(
            "<b>❌ Please provide a valid forwarded message or Telegram link.</b>",
            parse_mode=enums.ParseMode.HTML
        )

    if state["step"] == "WAITFIRST":
        state["step"] = "WAITLAST"
        state["chat_id"] = chat_id
        state["start_id"] = msg_id
        await message.reply_text(
            "<b>📤 Forward the batch LAST message from your batch channel (with forward tag)\n"
            "OR\n"
            "📎 Send me the batch LAST message link from your batch channel.</b>",
            parse_mode=enums.ParseMode.HTML
        )
    
    elif state["step"] == "WAITLAST":
        if chat_id != state["chat_id"]:
            return await message.reply_text(
                "<b>❌ The last message must be from the same chat as the first.</b>",
                parse_mode=enums.ParseMode.HTML
            )
        
        start_id = state["start_id"]
        end_id = msg_id
        del BATCH_STATE[user_id]  # Clear state
        
        # Ensure range is correct
        if start_id > end_id:
            start_id, end_id = end_id, start_id
        
        total_messages = end_id - start_id + 1
        
        sts = await message.reply_text(
            f"<b>🚀 Batch Processing Started...\n"
            f"📊 Total Messages: {total_messages}</b>",
            parse_mode=enums.ParseMode.HTML
        )
        
        # Get User Session
        user_sess = await db.get_session(user_id)
        if not user_sess:
            return await sts.edit_text(
                "<b>❌ You must /login first to use batch mode for restricted content.</b>",
                parse_mode=enums.ParseMode.HTML
            )

        # Create user client with proper settings - NO DATABASE
        acc = Client(
            name=f"batch_{user_id}_{int(time.time())}", 
            session_string=user_sess, 
            api_hash=API_HASH, 
            api_id=API_ID,
            in_memory=True,  # Use in-memory storage
            no_updates=True,  # Don't receive updates
            workdir="/tmp"  # Use temp directory
        )
        
        success_count = 0
        failed_count = 0
        
        try:
            await acc.start()
            logger.info(f"User client started for {user_id}")
            
            # Add to active users
            await add_active_batch(user_id, {
                "total": total_messages,
                "current": 0,
                "success": 0,
                "cancel_requested": False,
                "progress_message_id": sts.id
            })
            
            # Resolve peer
            resolved_chat_id = chat_id
            try:
                chat = await acc.get_chat(chat_id)
                resolved_chat_id = chat.id
                logger.info(f"Resolved chat: {resolved_chat_id}")
            except Exception as e:
                logger.error(f"Failed to resolve chat {chat_id}: {e}")
            
            message_ids = list(range(start_id, end_id + 1))
            processed_count = 0
            
            # Process in chunks
            for i in range(0, len(message_ids), 20):
                # Check for cancellation
                if should_cancel(user_id):
                    await sts.edit_text(
                        f"<b>⚠️ Batch Cancelled!\n\n"
                        f"✅ Success: {success_count}\n"
                        f"❌ Failed: {failed_count}\n"
                        f"📊 Total: {processed_count}/{total_messages}</b>",
                        parse_mode=enums.ParseMode.HTML
                    )
                    break
                
                chunk = message_ids[i:i+20]
                
                try:
                    # Fetch messages with retry
                    msgs = None
                    retry_count = 0
                    while retry_count < 3:
                        try:
                            msgs = await acc.get_messages(resolved_chat_id, chunk)
                            break
                        except FloodWait as fw:
                            logger.warning(f"FloodWait: {fw.value} seconds")
                            await asyncio.sleep(fw.value + 5)
                            continue
                        except Exception as e:
                            logger.error(f"Error fetching chunk: {e}")
                            retry_count += 1
                            if retry_count >= 3:
                                break
                            await asyncio.sleep(5)

                    if not msgs:
                        failed_count += len(chunk)
                        processed_count += len(chunk)
                        continue

                    if not isinstance(msgs, list):
                        msgs = [msgs]
                    
                    # Process each message
                    for msg in msgs:
                        if not msg or msg.empty:
                            failed_count += 1
                            processed_count += 1
                            continue
                        
                        # Update progress
                        await update_batch_progress(user_id, processed_count, success_count)
                        
                        # Update status every 5 messages
                        if processed_count % 5 == 0:
                            try:
                                await sts.edit_text(
                                    f"<b>⚡ Processing...\n\n"
                                    f"📊 Progress: {processed_count}/{total_messages}\n"
                                    f"✅ Success: {success_count}\n"
                                    f"❌ Failed: {failed_count}</b>",
                                    parse_mode=enums.ParseMode.HTML
                                )
                            except:
                                pass
                        
                        # Check if message has media or text
                        if not (msg.media or msg.text):
                            failed_count += 1
                            processed_count += 1
                            continue
                        
                        retry_count = 0
                        message_sent = False
                        
                        while retry_count < 3 and not message_sent:
                            try:
                                # Try direct forward first
                                await acc.forward_messages(
                                    chat_id=user_id,
                                    from_chat_id=resolved_chat_id,
                                    message_ids=msg.id
                                )
                                success_count += 1
                                message_sent = True
                                logger.info(f"Forwarded message {msg.id} to user {user_id}")
                                await asyncio.sleep(1)  # Small delay between forwards
                                break
                                
                            except FloodWait as fw:
                                logger.warning(f"FloodWait on forward: {fw.value} seconds")
                                await asyncio.sleep(fw.value + 5)
                                continue
                                
                            except Exception as e:
                                error_str = str(e)
                                logger.error(f"Forward error: {error_str}")
                                
                                # Fallback to download-upload for restricted content
                                if "CHAT_FORWARDS_RESTRICTED" in error_str or "CHAT_SEND_MEDIA_FORBIDDEN" in error_str or "MESSAGE_ID_INVALID" in error_str:
                                    try:
                                        # Handle text messages
                                        if msg.text and not msg.media:
                                            await client.send_message(
                                                user_id, 
                                                msg.text, 
                                                entities=msg.entities
                                            )
                                            success_count += 1
                                            message_sent = True
                                            logger.info(f"Sent text message to user {user_id}")
                                            break

                                        # Download media
                                        download_msg = await client.send_message(
                                            user_id, 
                                            "⬇️ Downloading restricted content..."
                                        )
                                        
                                        start_time = time.time()
                                        
                                        # Create temp filename
                                        temp_file = f"/tmp/batch_{user_id}_{msg.id}_{int(time.time())}"
                                        
                                        file_path = await acc.download_media(
                                            msg,
                                            file_name=temp_file,
                                            progress=prog,
                                            progress_args=(
                                                client, 
                                                user_id, 
                                                download_msg.id, 
                                                start_time
                                            )
                                        )
                                        
                                        if not file_path:
                                            await download_msg.delete()
                                            failed_count += 1
                                            break
                                        
                                        await download_msg.edit_text("⬆️ Uploading...")
                                        
                                        caption = msg.caption or ""
                                        thumb_path = None
                                        
                                        # Upload based on media type
                                        try:
                                            if msg.photo:
                                                await client.send_photo(
                                                    user_id, file_path, caption=caption
                                                )
                                            elif msg.video:
                                                try:
                                                    if msg.video.thumbs:
                                                        thumb_path = await acc.download_media(
                                                            msg.video.thumbs[0].file_id,
                                                            file_name=f"/tmp/thumb_{user_id}_{msg.id}.jpg"
                                                        )
                                                except:
                                                    pass
                                                await client.send_video(
                                                    user_id, file_path, 
                                                    caption=caption,
                                                    supports_streaming=True, 
                                                    thumb=thumb_path
                                                )
                                            elif msg.audio:
                                                try:
                                                    if msg.audio.thumbs:
                                                        thumb_path = await acc.download_media(
                                                            msg.audio.thumbs[0].file_id,
                                                            file_name=f"/tmp/thumb_{user_id}_{msg.id}.jpg"
                                                        )
                                                except:
                                                    pass
                                                await client.send_audio(
                                                    user_id, file_path, 
                                                    caption=caption, 
                                                    thumb=thumb_path
                                                )
                                            elif msg.voice:
                                                await client.send_voice(
                                                    user_id, file_path, caption=caption
                                                )
                                            elif msg.document:
                                                try:
                                                    if msg.document.thumbs:
                                                        thumb_path = await acc.download_media(
                                                            msg.document.thumbs[0].file_id,
                                                            file_name=f"/tmp/thumb_{user_id}_{msg.id}.jpg"
                                                        )
                                                except:
                                                    pass
                                                await client.send_document(
                                                    user_id, file_path, 
                                                    caption=caption, 
                                                    thumb=thumb_path
                                                )
                                            elif msg.sticker:
                                                await client.send_sticker(user_id, file_path)
                                            elif msg.animation:
                                                await client.send_animation(
                                                    user_id, file_path, caption=caption
                                                )
                                            else:
                                                await client.send_document(
                                                    user_id, file_path, caption=caption
                                                )
                                            
                                            success_count += 1
                                            message_sent = True
                                            logger.info(f"Uploaded media to user {user_id}")
                                        except Exception as upload_err:
                                            logger.error(f"Upload failed: {upload_err}")
                                            failed_count += 1
                                        
                                        # Cleanup
                                        try:
                                            if file_path and os.path.exists(file_path):
                                                os.remove(file_path)
                                            if thumb_path and os.path.exists(thumb_path):
                                                os.remove(thumb_path)
                                        except:
                                            pass
                                        
                                        try:
                                            await download_msg.delete()
                                        except:
                                            pass
                                        
                                        break
                                        
                                    except FloodWait as fw:
                                        logger.warning(f"FloodWait on download: {fw.value}")
                                        await asyncio.sleep(fw.value + 5)
                                        continue
                                        
                                    except Exception as dl_e:
                                        logger.error(f"Download fallback failed: {dl_e}")
                                        failed_count += 1
                                        retry_count += 1
                                else:
                                    logger.error(f"Forward failed: {e}")
                                    failed_count += 1
                                    retry_count += 1
                        
                        if not message_sent:
                            failed_count += 1
                        
                        processed_count += 1
                        
                except Exception as e:
                    logger.error(f"Error in batch loop: {e}")
                    failed_count += len(chunk)
                    processed_count += len(chunk)
            
            # Final update
            await sts.edit_text(
                f"<b>✅ Batch Complete!\n\n"
                f"📊 Total Messages: {total_messages}\n"
                f"✅ Success: {success_count}\n"
                f"❌ Failed: {failed_count}</b>",
                parse_mode=enums.ParseMode.HTML
            )
            
        except Exception as e:
            logger.error(f"Batch error: {e}")
            await sts.edit_text(
                f"<b>❌ Error: {str(e)[:100]}\n\n"
                f"✅ Success: {success_count}\n"
                f"❌ Failed: {failed_count}</b>",
                parse_mode=enums.ParseMode.HTML
            )
        finally:
            await remove_active_batch(user_id)
            try:
                await acc.stop()
                logger.info(f"User client stopped for {user_id}")
            except Exception as e:
                logger.error(f"Error stopping client: {e}")

@Client.on_message(filters.command(["cancel", "stop"]) & filters.private)
async def cancel_batch_cmd(client: Client, message: Message):
    user_id = message.from_user.id
    
    if is_user_active(user_id):
        if await request_batch_cancel(user_id):
            await message.reply_text(
                "<b>⚠️ Cancellation Requested!\n\n"
                "The batch will stop after the current message completes.</b>",
                parse_mode=enums.ParseMode.HTML
            )
        else:
            await message.reply_text(
                "<b>❌ Failed to request cancellation. Please try again.</b>",
                parse_mode=enums.ParseMode.HTML
            )
    elif user_id in BATCH_STATE:
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
