from config import BOT_TOKEN, API_ID, API_HASH, ADMINS, DB_URI, DB_NAME
import os
print(f"BOT_TOKEN (repr): {repr(BOT_TOKEN)}")
print(f"API_ID (type): {type(API_ID)}")
print(f"API_ID (val): {API_ID}")
print(f"API_HASH (repr): {repr(API_HASH)}")
print(f"ADMINS: {ADMINS}")
print(f"DB_URI (repr): {repr(DB_URI)}")
print(f"DB_NAME (repr): {repr(DB_NAME)}")

from motor.motor_asyncio import AsyncIOMotorClient
try:
    print(f"Attempting motor.motor_asyncio.AsyncIOMotorClient({repr(DB_URI)})...")
    c = AsyncIOMotorClient(DB_URI)
    print("Motor client created successfully!")
except Exception as e:
    print(f"Motor Client Error: {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()
