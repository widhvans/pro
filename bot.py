# bot.py
import logging
import asyncio
from pyrogram import Client, filters
from pyrogram.types import Message, ChatPrivileges, ChatMemberUpdated
from pyrogram.errors import RPCError, FloodWait
from config import API_ID, API_HASH, BOT_TOKEN, ADMIN_ID
from database import MongoDB

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler("bot.log"), logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# Initialize Pyrogram client and MongoDB
app = Client(
    "admin_promoter_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)
mongo_db = MongoDB()

# Helper function to check if bot is admin with retries
async def is_bot_admin(client: Client, chat_id: int, max_retries: int = 3, retry_delay: float = 1.0) -> dict:
    for attempt in range(max_retries):
        try:
            bot = await client.get_me()
            bot_member = await client.get_chat_member(chat_id, bot.id)
            logger.info(f"Admin check attempt {attempt + 1}/{max_retries} for chat {chat_id}: status={bot_member.status}")
            if bot_member.status in ["administrator", "creator"]:
                return {
                    "can_manage_chat": bot_member.privileges.can_manage_chat,
                    "can_delete_messages": bot_member.privileges.can_delete_messages,
                    "can_manage_video_chats": bot_member.privileges.can_manage_video_chats,
                    "can_restrict_members": bot_member.privileges.can_restrict_members,
                    "can_promote_members": bot_member.privileges.can_promote_members,
                    "can_change_info": bot_member.privileges.can_change_info,
                    "can_invite_users": bot_member.privileges.can_invite_users,
                    "can_pin_messages": bot_member.privileges.can_pin_messages,
                }
            else:
                logger.warning(f"Bot is not an admin in chat {chat_id}: status={bot_member.status}")
                return {}
        except FloodWait as e:
            logger.warning(f"Flood wait {e.x}s during admin check for chat {chat_id}, attempt {attempt + 1}/{max_retries}")
            await asyncio.sleep(e.x)
        except RPCError as e:
            logger.error(f"Failed to check admin status in chat {chat_id}, attempt {attempt + 1}/{max_retries}: {str(e)}")
            if attempt < max_retries - 1:
                await asyncio.sleep(retry_delay)
        except Exception as e:
            logger.error(f"Unexpected error checking admin status in chat {chat_id}: {str(e)}")
            return {}
    logger.error(f"Failed to verify bot admin status in chat {chat_id} after {max_retries} attempts")
    return {}

# Handler for when the bot's chat member status is updated
@app.on_chat_member_updated()
async def on_chat_member_updated(client: Client, update: ChatMemberUpdated):
    chat = update.chat
    new_member = update.new_chat_member
    logger.info(f"Chat member update: chat_id={chat.id}, user_id={new_member.user.id if new_member else None}, status={new_member.status if new_member else None}")
    
    bot = await client.get_me()
    if new_member and new_member.user.id == bot.id and new_member.status in ["member", "administrator", "creator"]:
        # Bot was added to a chat or status changed
        chat_type = chat.type.value  # Get string value (e.g., 'supergroup')
        chat_id = chat.id
        chat_title = chat.title or str(chat_id)
        
        if chat_type in ["group", "supergroup", "channel"]:
            # Verify admin status
            privileges = await is_bot_admin(client, chat_id)
            if privileges:
                if mongo_db.save_chat(chat_id, chat_type, chat_title):
                    await client.send_message(
                        ADMIN_ID,
                        f"Bot added or promoted to admin in {chat_type} {chat_title} (ID: {chat_id}) and saved to database"
                    )
                    logger.info(f"Bot saved chat {chat_id} ({chat_title}, type: {chat_type}) to database")
                else:
                    await client.send_message(
                        ADMIN_ID,
                        f"Failed to save {chat_type} {chat_title} (ID: {chat_id}) to database"
                    )
                    logger.error(f"Failed to save chat {chat_id} to database")
            else:
                logger.info(f"Bot not an admin in {chat_id}, skipping database save")
        else:
            logger.info(f"Ignored chat {chat_id}: type {chat_type} is not group/supergroup/channel")

# Command to manually add the current chat to the database
@app.on_message(filters.command("addchat") & filters.user(ADMIN_ID) & (filters.group | filters.channel))
async def add_chat(client: Client, message: Message):
    logger.info(f"Received /addchat command from {message.from_user.id} in chat {message.chat.id}")
    chat = message.chat
    chat_id = chat.id
    chat_type = chat.type.value  # Get string value (e.g., 'supergroup')
    chat_title = chat.title or str(chat_id)
    
    try:
        # Check if bot is an admin
        privileges = await is_bot_admin(client, chat_id)
        if not privileges:
            await message.reply("I must be an admin to add this chat.")
            logger.warning(f"Bot is not an admin in chat {chat_id}")
            return
        
        # Save chat to database
        if chat_type in ["group", "supergroup", "channel"]:
            if mongo_db.save_chat(chat_id, chat_type, chat_title):
                await message.reply(f"Successfully saved {chat_title} (ID: {chat_id}) to database")
                logger.info(f"Saved chat {chat_id} ({chat_title}, type: {chat_type}) to database")
            else:
                await message.reply(f"Failed to save {chat_title} (ID: {chat_id}) to database")
                logger.error(f"Failed to save chat {chat_id} to database")
        else:
            await message.reply("This command can only be used in groups, supergroups, or channels.")
            logger.warning(f"Invalid chat type {chat_type} for chat {chat_id}")
            
    except RPCError as e:
        await message.reply(f"Error: {str(e)}")
        logger.error(f"Failed to process /addchat in {chat_id}: {str(e)}")
    except Exception as e:
        await message.reply("An unexpected error occurred. Check logs for details.")
        logger.error(f"Unexpected error in /addchat: {str(e)}")

# Command to promote a bot to admin in a specific chat with same permissions
@app.on_message(filters.command("promote") & filters.user(ADMIN_ID))
async def promote_bot(client: Client, message: Message):
    logger.info(f"Received /promote command from {message.from_user.id}")
    args = message.text.split()
    
    if len(args) != 3:
        await message.reply("Usage: /promote <bot_username> <chat_id>")
        logger.warning("Invalid /promote command format")
        return
    
    bot_username = args[1]
    try:
        chat_id = int(args[2])
    except ValueError:
        await message.reply("Invalid chat_id format. Use a numeric ID (e.g., -100123456789)")
        logger.error("Invalid chat_id format in /promote")
        return
    
    try:
        # Check if the bot is a member of the chat
        bot_member = await client.get_users(bot_username)
        chat = await client.get_chat(chat_id)
        
        # Get the current bot's privileges
        privileges = await is_bot_admin(client, chat_id)
        if not privileges:
            await message.reply("I am not an admin or lack permissions in this chat.")
            logger.warning(f"Bot is not an admin in chat {chat_id} for /promote")
            return
        
        # Promote the bot to admin with the same privileges
        await client.promote_chat_member(
            chat_id=chat_id,
            user_id=bot_member.id,
            privileges=ChatPrivileges(**privileges)
        )
        await message.reply(f"Successfully promoted {bot_username} to admin in {chat.title or chat.id} with same permissions")
        logger.info(f"Promoted {bot_username} in chat {chat_id} with same permissions")
        
    except RPCError as e:
        await message.reply(f"Error: {str(e)}")
        logger.error(f"Failed to promote {bot_username} in {chat_id}: {str(e)}")
    except Exception as e:
        await message.reply("An unexpected error occurred. Check logs for details.")
        logger.error(f"Unexpected error in /promote: {str(e)}")

# Command to promote a bot to admin in all stored chats with same permissions
@app.on_message(filters.command("promoteall") & filters.user(ADMIN_ID))
async def promote_bot_all(client: Client, message: Message):
    logger.info(f"Received /promoteall command from {message.from_user.id}")
    args = message.text.split()
    
    if len(args) != 2:
        await message.reply("Usage: /promoteall <bot_username>")
        logger.warning("Invalid /promoteall command format")
        return
    
    bot_username = args[1]
    success_count = 0
    failure_count = 0
    
    try:
        bot_member = await client.get_users(bot_username)
        # Retrieve chats from MongoDB
        chats = mongo_db.get_all_chats()
        if not chats:
            await message.reply("No chats found in the database. Use /addchat in a group or channel to add chats.")
            logger.warning("No chats found in MongoDB")
            return
        
        for chat in chats:
            chat_id = chat["chat_id"]
            chat_title = chat.get("chat_title", str(chat_id))
            try:
                # Get the current bot's privileges
                privileges = await is_bot_admin(client, chat_id)
                if not privileges:
                    failure_count += 1
                    logger.warning(f"Skipping {chat_id}: Bot is not an admin or lacks permissions")
                    continue
                
                # Promote the bot with the same privileges
                await client.promote_chat_member(
                    chat_id=chat_id,
                    user_id=bot_member.id,
                    privileges=ChatPrivileges(**privileges)
                )
                success_count += 1
                logger.info(f"Promoted {bot_username} in chat {chat_id} ({chat_title}) with same permissions")
            except RPCError as e:
                failure_count += 1
                logger.error(f"Failed to promote {bot_username} in {chat_id}: {str(e)}")
        
        await message.reply(
            f"Promotion complete!\n"
            f"Successfully promoted {bot_username} in {success_count} chats with same permissions.\n"
            f"Failed in {failure_count} chats (check logs for details)."
        )
        
    except Exception as e:
        await message.reply("An unexpected error occurred. Check logs for details.")
        logger.error(f"Unexpected error in /promoteall: {str(e)}")

# Start command for basic greeting
@app.on_message(filters.command("start") & filters.user(ADMIN_ID))
async def start(client: Client, message: Message):
    await message.reply("Hello! I'm a bot that can promote other bots to admin with same permissions.\n"
                       "Commands:\n"
                       "/addchat - Add the current chat to the database (use in group/channel)\n"
                       "/promote <bot_username> <chat_id> - Promote a bot in a specific chat\n"
                       "/promoteall <bot_username> - Promote a bot in all stored chats")
    logger.info(f"Start command received from {message.from_user.id}")

# Run the bot
if __name__ == "__main__":
    logger.info("Starting Admin Promoter Bot")
    app.run()
