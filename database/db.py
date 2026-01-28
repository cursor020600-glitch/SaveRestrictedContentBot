# Coursesbuying
# Don't Remove Credit
# Telegram Channel @Coursesbuying



import motor.motor_asyncio
from config import DB_NAME, DB_URI
from logger import LOGGER

logger = LOGGER(__name__)

class Database:
    
    def __init__(self, uri, database_name):
        self._client = motor.motor_asyncio.AsyncIOMotorClient(uri)
        self.db = self._client[database_name]
        self.col = self.db.users

    def new_user(self, id, name):
        return dict(
            id = id,
            name = name,
            session = None,
        )
    
    async def add_user(self, id, name):
        user = self.new_user(id, name)
        await self.col.insert_one(user)
        logger.info(f"New user added to DB: {id} - {name}")
    
    async def is_user_exist(self, id):
        user = await self.col.find_one({'id':int(id)})
        return bool(user)
    
    async def total_users_count(self):
        count = await self.col.count_documents({})
        return count

    async def get_all_users(self):
        return self.col.find({})

    async def delete_user(self, user_id):
        await self.col.delete_many({'id': int(user_id)})
        logger.info(f"User deleted from DB: {user_id}")

    async def set_session(self, id, session):
        await self.col.update_one({'id': int(id)}, {'$set': {'session': session}})

    async def get_session(self, id):
        user = await self.col.find_one({'id': int(id)})
        return user.get('session')

    # Caption Support
    async def set_caption(self, id, caption):
        await self.col.update_one({'id': int(id)}, {'$set': {'caption': caption}})

    async def get_caption(self, id):
        user = await self.col.find_one({'id': int(id)})
        return user.get('caption', None)

    async def del_caption(self, id):
        await self.col.update_one({'id': int(id)}, {'$unset': {'caption': ""}})

    # Thumbnail Support
    async def set_thumbnail(self, id, thumbnail):
        await self.col.update_one({'id': int(id)}, {'$set': {'thumbnail': thumbnail}})

    async def get_thumbnail(self, id):
        user = await self.col.find_one({'id': int(id)})
        return user.get('thumbnail', None)

    async def del_thumbnail(self, id):
        await self.col.update_one({'id': int(id)}, {'$unset': {'thumbnail': ""}})
# Coursesbuying
# Don't Remove Credit
# Telegram Channel @Coursesbuying

    # Premium Support
    async def add_premium(self, id, expiry_date):
        await self.col.update_one({'id': int(id)}, {'$set': {'is_premium': True, 'premium_expiry': expiry_date}})
        logger.info(f"User {id} granted premium until {expiry_date}")

    async def remove_premium(self, id):
        await self.col.update_one({'id': int(id)}, {'$set': {'is_premium': False, 'premium_expiry': None}})
        logger.info(f"User {id} removed from premium")

    async def check_premium(self, id):
        user = await self.col.find_one({'id': int(id)})
        if user and user.get('is_premium'):
            return user.get('premium_expiry')
        return None

    async def get_premium_users(self):
        return self.col.find({'is_premium': True})

    # Ban Support
    async def ban_user(self, id):
        await self.col.update_one({'id': int(id)}, {'$set': {'is_banned': True}})
        logger.warning(f"User banned: {id}")

    async def unban_user(self, id):
        await self.col.update_one({'id': int(id)}, {'$set': {'is_banned': False}})
        logger.info(f"User unbanned: {id}")

    async def is_banned(self, id):
        user = await self.col.find_one({'id': int(id)})
        return user.get('is_banned', False)

    # Dump Chat Support
    async def set_dump_chat(self, id, chat_id):
        await self.col.update_one({'id': int(id)}, {'$set': {'dump_chat': int(chat_id)}})

    async def get_dump_chat(self, id):
        user = await self.col.find_one({'id': int(id)})
        return user.get('dump_chat', None)

    # Delete/Replace Words Support
    async def set_delete_words(self, id, words):
        # words should be a list
        await self.col.update_one({'id': int(id)}, {'$addToSet': {'delete_words': {'$each': words}}})

    async def get_delete_words(self, id):
        user = await self.col.find_one({'id': int(id)})
        return user.get('delete_words', [])

    async def remove_delete_words(self, id, words):
        await self.col.update_one({'id': int(id)}, {'$pull': {'delete_words': {'$in': words}}})

    async def set_replace_words(self, id, repl_dict):
        # repl_dict should be a dictionary {word: replacement}
        # We might need to store it as a list of objects or handle it carefully. 
        # For simplicity, let's assume we store updating the whole map or adding to it.
        # MongoDB dot notation for maps is tricky for user inputs.
        # Let's verify existing map first.
        user = await self.col.find_one({'id': int(id)})
        current_repl = user.get('replace_words', {})
        current_repl.update(repl_dict)
        await self.col.update_one({'id': int(id)}, {'$set': {'replace_words': current_repl}})

    async def get_replace_words(self, id):
        user = await self.col.find_one({'id': int(id)})
        return user.get('replace_words', {})

    async def remove_replace_words(self, id, words):
        user = await self.col.find_one({'id': int(id)})
        current_repl = user.get('replace_words', {})
        for w in words:
            current_repl.pop(w, None)
        await self.col.update_one({'id': int(id)}, {'$set': {'replace_words': current_repl}})

db = Database(DB_URI, DB_NAME)


# Coursesbuying
# Don't Remove Credit 🥺
# Telegram Channel @Coursesbuying

# Coursesbuying
# Don't Remove Credit
# Telegram Channel @Coursesbuying
