# ========================================================
# Coursesbuying
# Don't Remove Credit
# Telegram Channel @Coursesbuying
#
# Maintained & Updated by: Coursesbuying
# GitHub: https://github.com/Coursesbuying
# ========================================================

import asyncio
import datetime
import sys
from datetime import timezone, timedelta

# ❌ BUGGED IMPORT (self-ping keep alive causes issues on Render)
# import aiohttp   # BUG: Not needed with port-binding keep alive

from motor.motor_asyncio import AsyncIOMotorClient
from pyrogram import Client, filters, __version__ as pyrogram_version
from pyrogram.types import Message

from config import API_ID, API_HASH, BOT_TOKEN, LOG_CHANNEL, DB_URI, DB_NAME
from logger import LOGGER

# ✅ NEW: Proper keep-alive SERVER (port binding)
from keep_alive import keep_alive

logger = LOGGER(__name__)

# ✅ Indian Standard Time
IST = timezone(timedelta(hours=5, minutes=30))

from database.db import db as bot_db

class Bot(Client):
    def __init__(self):
        super().__init__(
            "Coursesbuying Login",
            api_id=API_ID,
            api_hash=API_HASH,
            bot_token=BOT_TOKEN,
            plugins=dict(root="Coursesbuying"),
            workers=50,
            sleep_threshold=10
        )

    async def start(self):
        await super().start()
        me = await self.get_me()

        # ✅ START KEEP-ALIVE SERVER (FIXED)
        # Opens HTTP port required by Render
        keep_alive()

        # 🔍 Debug MongoDB connection
        logger.info(f"Connected to MongoDB")
        count = await bot_db.total_users_count()
        logger.info(f"Current Stored Users: {count}")

        # Cache Log Channel Peer
        try:
            await self.get_chat(LOG_CHANNEL)
        except Exception as e:
            logger.warning(f"Failed to cache Log Channel: {e}")

        # Bot startup log
        now = datetime.datetime.now(IST)
        py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"

        text = (
            f"**__🤖 Bot Deployed / Restarted ♻️__**\n"
            f"**__- @{me.username}__**\n\n"
            f"**__📅 Date:** {now.strftime('%d-%b-%Y')}__\n"
            f"**__🕒 Time:** {now.strftime('%I:%M %p')}__\n"
            f"**🐍 Python:** `{py_ver}`\n"
            f"**🔥 Pyrogram:** `{pyrogram_version}`\n\n"
            f"**__@Coursesbuying__**"
        )

        try:
            await self.send_message(LOG_CHANNEL, text)
        except Exception as e:
            logger.error(f"Log send failed: {e}")

        logger.info(f"Bot Powered By @{me.username}")
        logger.info(f"Python Version: {py_ver}")
        logger.info(f"Pyrogram Version: {pyrogram_version}")

    async def stop(self, *args):
        me = await self.get_me()

        # ℹ️ No keep-alive shutdown needed
        # Flask runs in daemon thread and exits safely

        try:
            await self.send_message(LOG_CHANNEL, f"❌ Bot @{me.username} Stopped")
        except Exception as e:
            logger.error(f"Stop log failed: {e}")

        await super().stop()
        logger.info("Bot Stopped - Bye")


BotInstance = Bot()


# ========================================================
# ✅ User Logging Handler (Persistent MongoDB)
# ========================================================
@BotInstance.on_message(filters.private & filters.incoming, group=-1)
async def new_user_log(bot: Client, message: Message):
    # This is a placeholder for the logging logic
    # The original logic used a collection that we removed for simplicity
    pass


try:
    BotInstance.run()
except Exception:
    import traceback
    traceback.print_exc()


# ========================================================
# Coursesbuying
# Don't Remove Credit
# Telegram Channel @Coursesbuying
#
# Updated & Managed by:
# Coursesbuying | https://github.com/Coursesbuying
# ========================================================
