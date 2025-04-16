# companion_bot.py
import logging
from pyrogram import Client, filters
from config import API_ID, API_HASH, ADMIN_ID

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler("companion_bot.log"), logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# Initialize Pyrogram client for @Akash52131_bot
app = Client(
    "target_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token="your_akash52131_bot_token_here"  # Replace with @Akash52131_bot's token
)

# Handler for receiving invite links
@app.on_message(filters.user(ADMIN_ID) & filters.text & filters.private)
async def handle_invite_link(client: Client, message: Message):
    text = message.text
    if "t.me/+" in text:
        try:
            # Extract invite link
            invite_link = next((word for word in text.split() if "t.me/+" in word), None)
            if invite_link:
                # Join the chat
                await client.join_chat(invite_link)
                logger.info(f"Joined chat via invite link: {invite_link}")
                await message.reply("Joined the chat successfully!")
        except Exception as e:
            logger.error(f"Failed to join chat via invite link {invite_link}: {str(e)}")
            await message.reply(f"Failed to join chat: {str(e)}")

# Start command
@app.on_message(filters.command("start") & filters.user(ADMIN_ID))
async def start(client: Client, message: Message):
    await message.reply("I'm ready to receive invite links and join chats!")
    logger.info("Companion bot started")

# Run the bot
if __name__ == "__main__":
    logger.info("Starting Companion Bot")
    app.run()
