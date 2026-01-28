from config import DB_URI, DB_NAME
print(f"DB_URI: '{DB_URI}'")
print(f"Length: {len(DB_URI)}")
print("Chars (Hex):", [hex(ord(c)) for c in DB_URI])
print(f"DB_NAME: '{DB_NAME}'")
print("Chars (Hex):", [hex(ord(c)) for c in DB_NAME])
try:
    from motor.motor_asyncio import AsyncIOMotorClient
    client = AsyncIOMotorClient(DB_URI)
    print("Motor client initialized successfully (URI check only)")
except Exception as e:
    print(f"Motor Error: {e}")
