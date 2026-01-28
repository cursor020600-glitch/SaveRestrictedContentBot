# Coursesbuying
# Don't Remove Credit
# Telegram Channel @Coursesbuying

from pyrogram import Client, filters
from pyrogram.types import Message
from database.db import db
from config import ERROR_MESSAGE


@Client.on_message(filters.command("set_caption") & filters.private)
async def set_caption(client: Client, message: Message):
    if len(message.command) < 2:
        return await message.reply_text("**__Give me a caption to set.__**\n\nExample: `/set_caption File from @Coursesbuying`")
    
    caption = message.text.split(" ", 1)[1]
    await db.set_caption(message.from_user.id, caption)
    await message.reply_text(f"**__Caption Set Successfully ✅__**\n\n**Caption:** `{caption}`")
# Coursesbuying
# Don't Remove Credit
# Telegram Channel @Coursesbuying

@Client.on_message(filters.command("see_caption") & filters.private)
async def see_caption(client: Client, message: Message):
    caption = await db.get_caption(message.from_user.id)
    if caption:
        await message.reply_text(f"**__Your Custom Caption:__**\n\n`{caption}`")
    else:
        await message.reply_text("**__You haven't set any custom caption.__**")

@Client.on_message(filters.command("del_caption") & filters.private)
async def del_caption(client: Client, message: Message):
    caption = await db.get_caption(message.from_user.id)
    if not caption:
        return await message.reply_text("**__You don't have a custom caption to delete.__**")
    
    await db.del_caption(message.from_user.id)
    await message.reply_text("**__Custom Caption Deleted Successfully 🗑__**")

# Coursesbuying
# Don't Remove Credit
# Telegram Channel @Coursesbuying
