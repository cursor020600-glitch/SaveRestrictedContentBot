# Coursesbuying
# Don't Remove Credit
# Telegram Channel @Coursesbuying

# Coursesbuying
# Don't Remove Credit 
# Telegram Channel @Coursesbuying
import os
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), '.env'), override=True)

BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
API_ID = int(os.environ.get("API_ID", "").strip() or 0)
API_HASH = os.environ.get("API_HASH", "").strip()
ADMINS = [int(id.strip()) for id in os.environ.get("ADMINS", "").split(",") if id.strip()]
DB_URI = os.environ.get("DB_URI", "").strip()
DB_NAME = os.environ.get("DB_NAME", "").strip()
LOG_CHANNEL = os.environ.get("LOG_CHANNEL", "-1003656791142")
ERROR_MESSAGE = bool(os.environ.get('ERROR_MESSAGE', True))
KEEP_ALIVE_URL = os.environ.get("KEEP_ALIVE_URL", "")
# Coursesbuying
# Don't Remove Credit
# Telegram Channel @Coursesbuying


# Coursesbuying
# Don't Remove Credit 
# Telegram Channel @Coursesbuying

# Coursesbuying
# Don't Remove Credit
# Telegram Channel @Coursesbuying
