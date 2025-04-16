# database.py
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure
from config import MONGO_URI, MONGO_DB_NAME
import logging

# Set up logging
logger = logging.getLogger(__name__)

class MongoDB:
    def __init__(self):
        try:
            self.client = MongoClient(MONGO_URI)
            self.db = self.client[MONGO_DB_NAME]
            # Test connection
            self.client.admin.command("ping")
            logger.info("Connected to MongoDB successfully")
        except ConnectionFailure as e:
            logger.error(f"Failed to connect to MongoDB: {str(e)}")
            raise

    def save_chat(self, chat_id: int, chat_type: str, chat_title: str):
        """Save a chat to the database."""
        try:
            collection = self.db.chats
            collection.update_one(
                {"chat_id": chat_id},
                {"$set": {"chat_type": chat_type, "chat_title": chat_title}},
                upsert=True
            )
            logger.info(f"Saved chat {chat_id} ({chat_title}, type: {chat_type}) to MongoDB")
            return True
        except Exception as e:
            logger.error(f"Failed to save chat {chat_id}: {str(e)}")
            return False

    def get_all_chats(self):
        """Retrieve all stored chats."""
        try:
            collection = self.db.chats
            chats = list(collection.find())
            logger.info(f"Retrieved {len(chats)} chats from MongoDB")
            return chats
        except Exception as e:
            logger.error(f"Failed to retrieve chats: {str(e)}")
            return []
