# bot.py
import logging
import json
import os
from pyrogram import Client, filters
from pyrogram.types import Message, ChatPrivileges
from pyrogram.errors import RPCError
from config import API_ID, API_HASH, BOT_TOKEN, ADMIN_ID

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler("bot.log"), logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# Initialize Pyrogram client
app = Client(
    "admin_promoter_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)

# File to store chat IDs
CHAT_FILE = "chats.json"

# Helper function to load chat IDs from JSON
def load_chats():
    if os.path.exists(CHAT_FILE):
        try:
            with open(CHAT_FILE, "r") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load chats.json: {str(e)}")
            return []
    return []

# Helper function to save chat IDs to JSON
def save_chats(chats):
    try:
        with open(CHAT_FILE, "w") as f:
            json.dump(chats, f, indent=4)
        logger.info(f"Saved chats to {CHAT_FILE}: {chats}")
    except Exception as e:
        logger.error(f"Failed to save chats.json: {str(e)}")

# Helper function to get the bot's own admin privileges in a chat
async def get_bot_privileges(client: Client, chat_id: int) -> dict:
    try:
        bot_member = await client.get_chat_member(chat_id, "me")
        if bot_member.status == "administrator":
            privileges = {
                "can_manage_chat": bot_member.privileges.can_manage_chat,
                "can_delete_messages": bot_member.privileges.can_delete_messages,
                "can_manage_video_chats": bot_member.privileges.can_manage_video_chats,
                "can_restrict_members": bot_member.privileges.can_restrict_members,
                "can_promote_members": bot_member.privileges.can_promote_members,
                "can_change_info": bot_member.privileges.can_change_info,
                "can_invite_users": bot_member.privileges.can_invite_users,
                "can_pin_messages": bot_member.privileges.can_pin_messages,
            }
            logger.info(f"Bot privileges in {chat_id}: {privileges}")
            return privileges
        else:
            logger.warning(f"Bot is not an admin in chat {chat_id}")
            return {}
    except RPCError as e:
        logger.error(f"Failed to get bot privileges in {chat_id}: {str(e)}")
        return {}

# Command to add the current chat (run in group/channel)
@app.on_message(filters.command("addchat") & filters.user(ADMIN_ID) & (filters.group | filters.channel))
async def add_chat(client: Client, message: Message):
    logger.info(f"Received /addchat command from {message.from_user.id} in chat {message.chat.id}")
    chat_id = message.chat.id
    chats = load_chats()
    
    try:
        if chat_id not in chats:
            privileges = await get_bot_privileges(client, chat_id)
            if privileges.get("can_promote_members", False):
                chats.append(chat_id)
                save_chats(chats)
                await message.reply(f"Added chat {chat_id} to the list.")
                logger.info(f"Added chat {chat_id}")
            else:
                await message.reply("I am not an admin with 'Add New Admins' permission in this chat.")
                logger.warning(f"Bot lacks promote permission in chat {chat_id}")
        else:
            await message.reply(f"Chat {chat_id} is already in the list.")
    except RPCError as e:
        await message.reply(f"Error: {str(e)}")
        logger.error(f"Failed to add chat {chat_id}: {str(e)}")
    except Exception as e:
        await message.reply("An unexpected error occurred. Check logs for details.")
        logger.error(f"Unexpected error in /addchat: {str(e)}")

# Command to refresh the chat list
@app.on_message(filters.command("refresh") & filters.user(ADMIN_ID))
async def refresh_chats(client: Client, message: Message):
    logger.info(f"Received /refresh command from {message.from_user.id}")
    chats = load_chats()
    valid_chats = []
    removed_count = 0
    
    try:
        for chat_id in chats:
            try:
                privileges = await get_bot_privileges(client, chat_id)
                if privileges.get("can_promote_members", False):
                    valid_chats.append(chat_id)
                else:
                    removed_count += 1
                    logger.info(f"Removed chat {chat_id} during refresh (no promote permission)")
            except RPCError as e:
                removed_count += 1
                logger.error(f"Failed to check chat {chat_id} during refresh: {str(e)}")
        
        save_chats(valid_chats)
        await message.reply(f"Refresh complete! {len(valid_chats)} chats valid, {removed_count} removed. Use /checkchats to view.")
        logger.info(f"Refresh completed: {len(valid_chats)} chats valid, {removed_count} removed")
    
    except Exception as e:
        await message.reply("An unexpected error occurred. Check logs for details.")
        logger.error(f"Unexpected error in /refresh: {str(e)}")

# Command to check registered chats
@app.on_message(filters.command("checkchats") & filters.user(ADMIN_ID))
async def check_chats(client: Client, message: Message):
    logger.info(f"Received /checkchats command from {message.from_user.id}")
    chats = load_chats()
    if chats:
        chat_list = "\n".join([f"- {chat_id}" for chat_id in chats])
        await message.reply(f"Registered chats:\n{chat_list}")
    else:
        await message.reply("No chats registered. Use /addchat in groups/channels where I'm an admin with 'Add New Admins' permission.")
    logger.info(f"Checked chats: {chats}")

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
    chat_id = args[2]
    
    try:
        # Check if the bot is a member of the chat
        bot_member = await client.get_users(bot_username)
        chat = await client.get_chat(chat_id)
        
        # Get the current bot's privileges
        privileges = await get_bot_privileges(client, chat.id)
        if not privileges:
            await message.reply("I am not an admin or lack permissions in this chat.")
            return
        
        # Promote the bot to admin with the same privileges
        await client.promote_chat_member(
            chat_id=chat.id,
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
        chats = load_chats()
        if not chats:
            await message.reply("No chats registered. Use /addchat in groups/channels where I'm an admin with 'Add New Admins' permission.")
            logger.warning("No chats registered for /promoteall")
            return
        
        for chat_id in chats:
            try:
                chat = await client.get_chat(chat_id)
                # Get the current bot's privileges in this chat
                privileges = await get_bot_privileges(client, chat.id)
                if not privileges:
                    failure_count += 1
                    logger.warning(f"Skipping {chat.id}: Bot is not an admin or lacks permissions")
                    continue
                
                # Promote the bot with the same privileges
                await client.promote_chat_member(
                    chat_id=chat.id,
                    user_id=bot_member.id,
                    privileges=ChatPrivileges(**privileges)
                )
                success_count += 1
                logger.info(f"Promoted {bot_username} in chat {chat.id} with same permissions")
            except RPCError as e:
                failure_count += 1
                logger.error(f"Failed to promote {bot_username} in {chat.id}: {str(e)}")
        
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
                       "/addchat - Add the current group/channel (run in chat)\n"
                       "/refresh - Refresh the chat list\n"
                       "/promote <bot_username> <chat_id> - Promote a bot in a specific chat\n"
                       "/promoteall <bot_username> - Promote a bot in all registered chats\n"
                       "/checkchats - View registered chats")
    logger.info(f"Start command received from {message.from_user.id}")

# Run the bot
if __name__ == "__main__":
    logger.info("Starting Admin Promoter Bot")
    app.run()
