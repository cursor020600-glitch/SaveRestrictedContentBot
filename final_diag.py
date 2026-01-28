import traceback
import sys
print("Starting final diagnostic...")
try:
    print("Importing bot.py...")
    import bot
    print("Bot imported successfully!")
except Exception as e:
    print("\n" + "="*50)
    print("CRITICAL ERROR DETECTED")
    print("="*50)
    traceback.print_exc(file=sys.stdout)
    print("="*50)
