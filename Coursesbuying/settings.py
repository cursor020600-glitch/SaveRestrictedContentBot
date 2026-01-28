# Coursesbuying
# Don't Remove Credit
# Telegram Channel @Coursesbuying

from pyrogram import Client, filters, enums
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from database.db import db
from Coursesbuying.strings import COMMANDS_TXT

@Client.on_message(filters.command("settings") & filters.private)
async def settings(client: Client, message: Message):
    settings_buttons = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📜 Commands List", callback_data="cmd_list_btn"),
        ],
        [
            InlineKeyboardButton("❌ Close", callback_data="close_btn")
        ]
    ])
    await message.reply_text(
        "**⚙️ Settings Menu**\n\nChoose an option below:",
        reply_markup=settings_buttons
    )

@Client.on_message(filters.command("commands") & filters.private)
async def commands_list(client: Client, message: Message):
    # Reuse the callback logic for consistency, or send fresh
    settings_buttons = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("❌ Close", callback_data="close_btn")
        ]
    ])
    await message.reply_text(
        COMMANDS_TXT,
        reply_markup=settings_buttons,
        parse_mode=enums.ParseMode.HTML,
        disable_web_page_preview=True
    )

@Client.on_message(filters.command("setchat") & filters.private)
async def setchat(client: Client, message: Message):
    if len(message.command) < 2:
        return await message.reply_text("**Usage:** `/setchat chat_id`\n\nSet the chat ID where you want your dumps to go.")
# Coursesbuying
# Don't Remove Credit
# Telegram Channel @Coursesbuying
    
    try:
        chat_id = int(message.command[1])
        await db.set_dump_chat(message.from_user.id, chat_id)
        await message.reply_text(f"**Dump Chat Set Successfully ✅**\n\n**Chat ID:** `{chat_id}`")
    except ValueError:
        await message.reply_text("**Invalid Chat ID.**")
    except Exception as e:
        await message.reply_text(f"Error: {e}")

@Client.on_callback_query(filters.regex("cmd_list_btn"))
async def cmd_list_callback(client: Client, callback_query):
    settings_buttons = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔙 Back", callback_data="settings_back_btn"),
            InlineKeyboardButton("❌ Close", callback_data="close_btn")
        ]
    ])
    await callback_query.edit_message_text(
        COMMANDS_TXT,
        reply_markup=settings_buttons,
        parse_mode=enums.ParseMode.HTML,
        disable_web_page_preview=True
    )

@Client.on_callback_query(filters.regex("settings_back_btn"))
async def settings_back_callback(client: Client, callback_query):
    settings_buttons = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📜 Commands List", callback_data="cmd_list_btn"),
        ],
        [
            InlineKeyboardButton("❌ Close", callback_data="close_btn")
        ]
    ])
    await callback_query.edit_message_text(
        "**⚙️ Settings Menu**\n\nChoose an option below:",
        reply_markup=settings_buttons
    )

# Coursesbuying
# Don't Remove Credit
# Telegram Channel @Coursesbuying
