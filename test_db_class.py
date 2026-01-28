from database.db import Database
from config import DB_URI, DB_NAME
print(f"Testing with URI: '{DB_URI}'")
print(f"Testing with Name: '{DB_NAME}'")
try:
    db_instance = Database(DB_URI, DB_NAME)
    print("Database instance created successfully!")
except Exception as e:
    import traceback
    traceback.print_exc()
