# bot.py
import logging
import asyncio
import os
from datetime import datetime, timedelta
from pyrogram import Client, filters
from pyrogram.types import Message, ChatPrivileges, ChatMemberUpdated
from pyrogram.errors import RPCError, FloodWait
from config import API_ID, API_HASH, BOT_TOKEN, ADMIN_ID, TARGET_BOT_ID
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

# In-memory cache for invite links and pending promotions
invite_cache = {}  # {chat_id: {user_id: {"link": str, "expires": datetime, "task": asyncio.Task}}}

# Helper function to validate chat accessibility
async def is_chat_valid(client: Client, chat_id: int) -> bool:
    try:
        await client.get_chat(chat_id)
        logger.info(f"Chat {chat_id} is valid and accessible")
        return True
    except RPCError as e:
        logger.error(f"Chat {chat_id} is invalid or inaccessible: {str(e)}")
        return False

# Helper function to check if bot is admin with real-world promotion test
async def is_bot_admin(client: Client, chat_id: int, max_retries: int = 3, retry_delay: float = 1.0) -> dict:
    bot = await client.get_me()
    for attempt in range(max_retries):
        try:
            # Primary check using get_chat_member
            bot_member = await client.get_chat_member(chat_id, bot.id)
            status = bot_member.status.value
            logger.info(f"Primary admin check attempt {attempt + 1}/{max_retries} for chat {chat_id}: status={status}")
            if status in ["administrator", "creator"]:
                privileges = {
                    "can_manage_chat": bot_member.privileges.can_manage_chat or False,
                    "can_delete_messages": bot_member.privileges.can_delete_messages or False,
                    "can_manage_video_chats": bot_member.privileges.can_manage_video_chats or False,
                    "can_restrict_members": bot_member.privileges.can_restrict_members or False,
                    "can_promote_members": bot_member.privileges.can_promote_members or False,
                    "can_change_info": bot_member.privileges.can_change_info or False,
                    "can_invite_users": bot_member.privileges.can_invite_users or False,
                    "can_pin_messages": bot_member.privileges.can_pin_messages or False,
                }
                logger.info(f"Bot is admin in chat {chat_id}: privileges={privileges}")
                # Verify required permissions
                if not privileges["can_promote_members"]:
                    logger.warning(f"Bot lacks 'can_promote_members' permission in chat {chat_id}")
                    return {}
                
                # Test actual promotion capability with ADMIN_ID
                chat = await client.get_chat(chat_id)
                if chat.type in ["supergroup", "channel"]:
                    try:
                        test_privileges = ChatPrivileges(can_manage_chat=True)
                        await client.promote_chat_member(
                            chat_id=chat_id,
                            user_id=ADMIN_ID,
                            privileges=test_privileges
                        )
                        await client.promote_chat_member(
                            chat_id=chat_id,
                            user_id=ADMIN_ID,
                            privileges=ChatPrivileges()
                        )
                        logger.info(f"Test promotion succeeded in chat {chat_id}")
                    except RPCError as e:
                        error_msg = str(e)
                        logger.warning(f"Test promotion failed in chat {chat_id}: {error_msg}")
                        if "CHAT_ADMIN_INVITE_REQUIRED" in error_msg:
                            logger.warning(f"Missing required permission in chat {chat_id}")
                            return {}
                        if "USER_NOT_PARTICIPANT" in error_msg:
                            logger.warning(f"ADMIN_ID not in chat {chat_id}, skipping test")
                        else:
                            logger.error(f"Test promotion error in chat {chat_id}: {error_msg}")
                            return {}
                    except Exception as e:
                        logger.error(f"Unexpected error in test promotion for chat {chat_id}: {str(e)}")
                        return {}
                return privileges
            
            # Fallback check using get_chat_members with admin filter
            logger.info(f"Fallback admin check attempt {attempt + 1}/{max_retries} for chat {chat_id}")
            admins = await client.get_chat_members(chat_id, filter="administrators")
            for admin in admins:
                if admin.user.id == bot.id:
                    privileges = {
                        "can_manage_chat": admin.privileges.can_manage_chat or False,
                        "can_delete_messages": admin.privileges.can_delete_messages or False,
                        "can_manage_video_chats": admin.privileges.can_manage_video_chats or False,
                        "can_restrict_members": admin.privileges.can_restrict_members or False,
                        "can_promote_members": admin.privileges.can_promote_members or False,
                        "can_change_info": admin.privileges.can_change_info or False,
                        "can_invite_users": admin.privileges.can_invite_users or False,
                        "can_pin_messages": admin.privileges.can_pin_messages or False,
                    }
                    logger.info(f"Bot found in admins list for chat {chat_id}: privileges={privileges}")
                    if not privileges["can_promote_members"]:
                        logger.warning(f"Bot lacks 'can_promote_members' permission in chat {chat_id}")
                        return {}
                    if chat.type in ["supergroup", "channel"]:
                        try:
                            await client.promote_chat_member(
                                chat_id=chat_id,
                                user_id=ADMIN_ID,
                                privileges=ChatPrivileges(can_manage_chat=True)
                            )
                            await client.promote_chat_member(
                                chat_id=chat_id,
                                user_id=ADMIN_ID,
                                privileges=ChatPrivileges()
                            )
                            logger.info(f"Test promotion succeeded in chat {chat_id}")
                        except RPCError as e:
                            error_msg = str(e)
                            logger.warning(f"Test promotion failed in chat {chat_id}: {error_msg}")
                            if "CHAT_ADMIN_INVITE_REQUIRED" in error_msg:
                                logger.warning(f"Missing required permission in chat {chat_id}")
                                return {}
                            if "USER_NOT_PARTICIPANT" in error_msg:
                                logger.warning(f"ADMIN_ID not in chat {chat_id}, skipping test")
                            else:
                                logger.error(f"Test promotion error in chat {chat_id}: {error_msg}")
                                return {}
                        except Exception as e:
                            logger.error(f"Unexpected error in test promotion for chat {chat_id}: {str(e)}")
                            return {}
                    return privileges
            logger.warning(f"Bot not found in admins list for chat {chat_id}")
            return {}
        
        except FloodWait as e:
            logger.warning(f"Flood wait {e.x}s during admin check for chat {chat_id}, attempt {attempt + 1}/{max_retries}")
            await asyncio.sleep(e.x)
        except RPCError as e:
            logger.error(f"RPC error during admin check for chat {chat_id}, attempt {attempt + 1}/{max_retries}: {str(e)}")
            if "RANDOM_ID_DUPLICATE" in str(e):
                logger.warning("Detected RANDOM_ID_DUPLICATE, resetting session")
                await reset_session(client)
            if attempt < max_retries - 1:
                await asyncio.sleep(retry_delay * (2 ** attempt))  # Exponential backoff
        except Exception as e:
            logger.error(f"Unexpected error during admin check for chat {chat_id}: {str(e)}")
            return {}
    logger.error(f"Failed to verify bot admin status in chat {chat_id} after {max_retries} attempts")
    return {}

# Helper function to check if a user/bot is in the chat and their status
async def get_user_status(client: Client, chat_id: int, user_id: int) -> str:
    try:
        member = await client.get_chat_member(chat_id, user_id)
        status = member.status.value
        logger.info(f"User {user_id} is in chat {chat_id} with status: {status}")
        return status
    except RPCError as e:
        logger.warning(f"User {user_id} not in chat {chat_id}: {str(e)}")
        return None

# Helper function to unban a user/bot from the chat
async def unban_user(client: Client, chat_id: int, user_id: int, max_retries: int = 2) -> bool:
    for attempt in range(max_retries):
        try:
            await client.unban_chat_member(chat_id, user_id)
            logger.info(f"Successfully unbanned user {user_id} from chat {chat_id}")
            return True
        except RPCError as e:
            logger.error(f"Failed to unban user {user_id} from chat {chat_id}, attempt {attempt + 1}/{max_retries}: {str(e)}")
            if attempt < max_retries - 1:
                await asyncio.sleep(2)
        except Exception as e:
            logger.error(f"Unexpected error unbanning user {user_id} from chat {chat_id}: {str(e)}")
            return False
    return False

# Helper function to invite a user/bot to the chat
async def invite_user(client: Client, chat_id: int, user_id: int) -> bool:
    try:
        chat = await client.get_chat(chat_id)
        if chat.type in ["supergroup", "channel"]:
            try:
                # Try direct invite
                await client.add_chat_members(chat_id, [user_id])
                logger.info(f"Successfully invited user {user_id} to chat {chat_id} via direct invite")
                return True
            except RPCError as e:
                error_msg = str(e)
                if "BOT_METHOD_INVALID" in error_msg or "USER_ALREADY_PARTICIPANT" in error_msg:
                    logger.warning(f"Direct invite failed for user {user_id} in chat {chat_id}: {error_msg}")
                else:
                    raise
        else:
            await client.add_chat_members(chat_id, [user_id])
            logger.info(f"Successfully invited user {user_id} to chat {chat_id} via direct invite")
            return True
    except RPCError as e:
        error_msg = str(e)
        logger.warning(f"Direct invite attempt failed for user {user_id} in chat {chat_id}: {error_msg}")
        if "BOT_METHOD_INVALID" in error_msg or "CHAT_WRITE_FORBIDDEN" in error_msg:
            # Fallback to invite link
            for attempt in range(2):
                try:
                    # Create temporary invite link (expires in 1 minute, 1 user)
                    expire_date = datetime.utcnow() + timedelta(minutes=1)
                    invite_link = await client.create_chat_invite_link(
                        chat_id,
                        expire_date=expire_date,
                        member_limit=1
                    )
                    invite_link = invite_link.invite_link
                    # Store in cache for join detection
                    if chat_id not in invite_cache:
                        invite_cache[chat_id] = {}
                    invite_cache[chat_id][user_id] = {
                        "link": invite_link,
                        "expires": expire_date,
                        "task": None
                    }
                    # Send invite link to target bot
                    try:
                        await client.send_message(
                            user_id,
                            f"You've been invited to join chat {chat_id}. Please join within 1 minute using this link: {invite_link}"
                        )
                        logger.info(f"Sent invite link to user {user_id} for chat {chat_id}: {invite_link}")
                    except RPCError as msg_e:
                        logger.warning(f"Failed to send invite link to user {user_id}: {str(msg_e)}")
                        # Fallback to ADMIN_ID
                        await client.send_message(
                            ADMIN_ID,
                            f"Couldn't send invite link to @{user_id} for chat {chat_id}. "
                            f"Please have @{user_id} join using this link within 1 minute: {invite_link}"
                        )
                        logger.info(f"Sent invite link to ADMIN_ID for user {user_id} to join chat {chat_id}: {invite_link}")
                    return False  # Indicate invite was not completed, but link was sent
                except RPCError as link_e:
                    logger.error(f"Failed to generate invite link for chat {chat_id}, attempt {attempt + 1}/2: {str(link_e)}")
                    if attempt < 1:
                        await asyncio.sleep(2)
                    else:
                        return False
        else:
            logger.error(f"Failed to invite user {user_id} to chat {chat_id}: {error_msg}")
            return False
    except Exception as e:
        logger.error(f"Unexpected error inviting user {user_id} to chat {chat_id}: {str(e)}")
        return False

# Helper function to reset Pyrogram session
async def reset_session(client: Client):
    try:
        session_file = "admin_promoter_bot.session"
        if os.path.exists(session_file):
            os.remove(session_file)
            logger.info("Deleted session file to reset session")
        await client.stop()
        await client.start()
        logger.info("Session reset successfully")
    except Exception as e:
        logger.error("Failed to reset session: {str(e)}")

# Handler for when the bot's chat member status is updated
@app.on_chat_member_updated()
async def on_chat_member_updated(client: Client, update: ChatMemberUpdated):
    chat = update.chat
    new_member = update.new_chat_member
    logger.info(f"Chat member update: chat_id={chat.id}, user_id={new_member.user.id if new_member else None}, status={new_member.status.value if new_member else None}")
    
    bot = await client.get_me()
    chat_id = chat.id
    chat_title = chat.title or str(chat_id)
    chat_type = chat.type.value
    
    # Handle bot's own status update
    if new_member and new_member.user.id == bot.id and new_member.status.value in ["member", "administrator", "creator"]:
        if chat_type in ["group", "supergroup", "channel"]:
            privileges = await is_bot_admin(client, chat_id)
            if privileges:
                if mongo_db.save_chat(chat_id, chat_type, chat_title):
                    try:
                        await client.send_message(
                            ADMIN_ID,
                            f"Bot promoted to admin in {chat_type} {chat_title} (ID: {chat_id}) and saved to database"
                        )
                        logger.info(f"Saved chat {chat_id} ({chat_title}, type: {chat_type}) to database")
                    except Exception as e:
                        logger.error(f"Failed to notify ADMIN_ID for chat {chat_id}: {str(e)}")
                else:
                    try:
                        await client.send_message(
                            ADMIN_ID,
                            f"Failed to save {chat_type} {chat_title} (ID: {chat_id}) to database"
                        )
                    except Exception as e:
                        logger.error(f"Failed to notify ADMIN_ID for chat {chat_id}: {str(e)}")
            else:
                try:
                    await client.send_message(
                        ADMIN_ID,
                        f"Bot added to {chat_type} {chat_title} (ID: {chat_id}) but lacks required permissions. "
                        "Please grant 'Invite Users via Link', 'Ban Members', and 'Add New Admins' permissions in chat settings."
                    )
                    logger.info(f"Bot not an admin in {chat_id}, requested permissions")
                except Exception as e:
                    logger.error(f"Failed to notify ADMIN_ID for chat {chat_id}: {str(e)}")
        else:
            logger.info(f"Ignored chat {chat_id}: type {chat_type} is not group/supergroup/channel")
    
    # Handle target bot joining via invite link
    if new_member and chat_id in invite_cache and new_member.user.id == TARGET_BOT_ID:
        user_id = new_member.user.id
        if new_member.status.value in ["member", "administrator"]:
            logger.info(f"Detected user {user_id} joined chat {chat_id} via invite link")
            # Cancel any timeout task
            cache_entry = invite_cache[chat_id].get(user_id)
            if cache_entry and cache_entry["task"]:
                cache_entry["task"].cancel()
            
            # Attempt promotion
            try:
                privileges = await is_bot_admin(client, chat_id)
                if not privileges:
                    logger.warning(f"Cannot promote user {user_id} in chat {chat_id}: Bot lacks admin permissions")
                    await client.send_message(
                        ADMIN_ID,
                        f"Cannot promote @{user_id} in {chat_type} {chat_title} (ID: {chat_id}): I lack admin permissions."
                    )
                    return
                
                await client.promote_chat_member(
                    chat_id=chat_id,
                    user_id=user_id,
                    privileges=ChatPrivileges(**privileges)
                )
                await client.send_message(
                    ADMIN_ID,
                    f"Successfully promoted @{user_id} to admin in {chat_type} {chat_title} (ID: {chat_id}) after joining via invite link"
                )
                logger.info(f"Promoted user {user_id} in chat {chat_id} after joining")
            except Exception as e:
                logger.error(f"Failed to promote user {user_id} in chat {chat_id} after joining: {str(e)}")
                await client.send_message(
                    ADMIN_ID,
                    f"Failed to promote @{user_id} in {chat_type} {chat_title} (ID: {chat_id}) after joining: {str(e)}"
                )
            finally:
                # Clean up cache
                if chat_id in invite_cache and user_id in invite_cache[chat_id]:
                    del invite_cache[chat_id][user_id]
                    if not invite_cache[chat_id]:
                        del invite_cache[chat_id]

# Periodic task to check admin status in all chats
async def check_all_chats_admin_status(client: Client):
    while True:
        try:
            async for dialog in client.get_dialogs():
                chat = dialog.chat
                chat_id = chat.id
                chat_type = chat.type.value
                chat_title = chat.title or str(chat_id)
                if chat_type in ["group", "supergroup", "channel"]:
                    privileges = await is_bot_admin(client, chat_id)
                    if privileges:
                        if mongo_db.save_chat(chat_id, chat_type, chat_title):
                            logger.info(f"Periodic check: Saved chat {chat_id} ({chat_title}, type: {chat_type}) to database")
                        else:
                            logger.error(f"Periodic check: Failed to save chat {chat_id} to database")
            await asyncio.sleep(3600)  # Run every hour
        except Exception as e:
            logger.error(f"Error in periodic admin status check: {str(e)}")
            await asyncio.sleep(300)  # Retry after 5 minutes if error

# Command to manually add the current chat to the database
@app.on_message(filters.command("addchat") & filters.user(ADMIN_ID) & (filters.group | filters.channel))
async def add_chat(client: Client, message: Message):
    logger.info(f"Received /addchat command from {message.from_user.id} in chat {message.chat.id}")
    chat = message.chat
    chat_id = chat.id
    chat_type = chat.type.value
    chat_title = chat.title or str(chat_id)
    
    try:
        if not await is_chat_valid(client, chat_id):
            await message.reply(f"Chat {chat_id} is invalid or inaccessible. Please verify the chat exists and I'm a member.")
            logger.warning(f"Invalid chat {chat_id} for /addchat")
            return
        
        privileges = await is_bot_admin(client, chat_id)
        if not privileges:
            await message.reply(
                "I must be an admin with 'Invite Users via Link', 'Ban Members', and 'Add New Admins' permissions to add this chat. "
                "Please check chat settings > Administrators."
            )
            logger.warning(f"Bot is not an admin or lacks required permissions in chat {chat_id}")
            return
        
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

# Command to clean invalid chats from the database
@app.on_message(filters.command("cleandb") & filters.user(ADMIN_ID))
async def clean_db(client: Client, message: Message):
    logger.info(f"Received /cleandb command from {message.from_user.id}")
    try:
        chats = mongo_db.get_all_chats()
        if not chats:
            await message.reply("No chats found in the database.")
            return
        
        deleted_count = 0
        for chat in chats:
            chat_id = chat["chat_id"]
            if not await is_chat_valid(client, chat_id):
                if mongo_db.delete_chat(chat_id):
                    deleted_count += 1
                    logger.info(f"Removed invalid chat {chat_id} from database")
        
        await message.reply(f"Database cleanup complete. Removed {deleted_count} invalid chats.")
        logger.info(f"Cleaned up {deleted_count} invalid chats from MongoDB")
        
    except Exception as e:
        await message.reply("An unexpected error occurred. Check logs for details.")
        logger.error(f"Unexpected error in /cleandb: {str(e)}")

# Command to promote a bot to admin in a specific chat with same permissions
async def promote_with_timeout(client: Client, chat_id: int, user_id: int, bot_username: str, timeout: int = 60):
    """Wait for user to join and promote, with timeout."""
    start_time = datetime.utcnow()
    while datetime.utcnow() - start_time < timedelta(seconds=timeout):
        status = await get_user_status(client, chat_id, user_id)
        if status in ["member", "administrator"]:
            try:
                privileges = await is_bot_admin(client, chat_id)
                if not privileges:
                    logger.warning(f"Cannot promote user {user_id} in chat {chat_id}: Bot lacks admin permissions")
                    await client.send_message(
                        ADMIN_ID,
                        f"Cannot promote @{bot_username} in chat {chat_id}: I lack admin permissions."
                    )
                    return False
                await client.promote_chat_member(
                    chat_id=chat_id,
                    user_id=user_id,
                    privileges=ChatPrivileges(**privileges)
                )
                logger.info(f"Promoted @{bot_username} in chat {chat_id} after joining")
                await client.send_message(
                    ADMIN_ID,
                    f"Successfully promoted @{bot_username} to admin in chat {chat_id} after joining"
                )
                return True
            except Exception as e:
                logger.error(f"Failed to promote user {user_id} in chat {chat_id}: {str(e)}")
                await client.send_message(
                    ADMIN_ID,
                    f"Failed to promote @{bot_username} in chat {chat_id}: {str(e)}"
                )
                return False
        await asyncio.sleep(5)  # Check every 5 seconds
    logger.warning(f"Timeout waiting for user {user_id} to join chat {chat_id}")
    await client.send_message(
        ADMIN_ID,
        f"Timeout: @{bot_username} did not join chat {chat_id} within 1 minute. Please add them manually or retry."
    )
    return False

@app.on_message(filters.command("promote") & filters.user(ADMIN_ID))
async def promote_bot(client: Client, message: Message):
    logger.info(f"Received /promote command from {message.from_user.id}")
    args = message.text.split()
    
    if len(args) != 3:
        await message.reply("Usage: /promote <bot_username> <chat_id>")
        logger.warning("Invalid /promote command format")
        return
    
    bot_username = args[1].lstrip("@")
    try:
        chat_id = int(args[2])
    except ValueError:
        await message.reply("Invalid chat_id format. Use a numeric ID (e.g., -100123456789)")
        logger.error("Invalid chat_id format in /promote")
        return
    
    try:
        # Get target bot
        bot_member = await client.get_users(bot_username)
        if not await is_chat_valid(client, chat_id):
            await message.reply(f"Chat {chat_id} is invalid or inaccessible. Please verify the chat exists and I'm a member.")
            logger.warning(f"Invalid chat {chat_id} for /promote")
            return
        
        # Check target bot status
        status = await get_user_status(client, chat_id, bot_member.id)
        if status == "banned":
            # Try unbanning
            if await unban_user(client, chat_id, bot_member.id):
                logger.info(f"Unbanned @{bot_username} in chat {chat_id}")
                await asyncio.sleep(2)
            else:
                await message.reply(
                    f"@{bot_username} is banned from chat {chat_id}, and I couldn't unban them. "
                    "Please unban them manually in chat settings > Banned Users."
                )
                logger.error(f"Failed to unban @{bot_username} in chat {chat_id}")
                return
            # Try inviting after unban
            if await invite_user(client, chat_id, bot_member.id):
                await asyncio.sleep(2)
                logger.info(f"Invited @{bot_username} to chat {chat_id} after unban")
            else:
                # If invite failed, rely on cache and timeout
                if chat_id in invite_cache and bot_member.id in invite_cache[chat_id]:
                    task = asyncio.create_task(
                        promote_with_timeout(client, chat_id, bot_member.id, bot_username)
                    )
                    invite_cache[chat_id][bot_member.id]["task"] = task
                    await message.reply(
                        f"Sent invite link to @{bot_username} for chat {chat_id}. "
                        "Waiting for them to join within 1 minute to promote."
                    )
                    return
                await message.reply(
                    f"Failed to invite @{bot_username} to chat {chat_id} after unbanning. "
                    "Please add them manually or ensure I have 'Invite Users via Link' permission."
                )
                logger.error(f"Failed to invite @{bot_username} to chat {chat_id} after unban")
                return
        elif not status:
            # Try inviting the bot
            if await invite_user(client, chat_id, bot_member.id):
                await asyncio.sleep(2)
                logger.info(f"Invited @{bot_username} to chat {chat_id}")
            else:
                # If invite failed, rely on cache and timeout
                if chat_id in invite_cache and bot_member.id in invite_cache[chat_id]:
                    task = asyncio.create_task(
                        promote_with_timeout(client, chat_id, bot_member.id, bot_username)
                    )
                    invite_cache[chat_id][bot_member.id]["task"] = task
                    await message.reply(
                        f"Sent invite link to @{bot_username} for chat {chat_id}. "
                        "Waiting for them to join within 1 minute to promote."
                    )
                    return
                await message.reply(
                    f"Failed to invite @{bot_username} to chat {chat_id}. "
                    "Please add them manually or ensure I have 'Invite Users via Link' permission."
                )
                logger.error(f"Failed to invite @{bot_username} to chat {chat_id}")
                return
        
        # Check admin status with fresh data
        privileges = await is_bot_admin(client, chat_id)
        if not privileges:
            await message.reply(
                "I am not an admin or lack required permissions in this chat. "
                "Please ensure I have 'Invite Users via Link', 'Ban Members', and 'Add New Admins' permissions in chat settings > Administrators. "
                "If the issue persists, try granting full admin rights."
            )
            logger.warning(f"Bot is not an admin or lacks permissions in chat {chat_id} for /promote")
            return
        
        # Attempt promotion with retry
        for attempt in range(2):
            try:
                await client.promote_chat_member(
                    chat_id=chat_id,
                    user_id=bot_member.id,
                    privileges=ChatPrivileges(**privileges)
                )
                await message.reply(f"Successfully promoted @{bot_username} to admin in chat {chat_id} with same permissions")
                logger.info(f"Promoted @{bot_username} in chat {chat_id} with same permissions")
                return
            except RPCError as e:
                error_msg = str(e)
                if "CHAT_ADMIN_INVITE_REQUIRED" in error_msg and attempt == 0:
                    logger.warning(f"Promotion failed in {chat_id}: CHAT_ADMIN_INVITE_REQUIRED, retrying after refresh")
                    await asyncio.sleep(2)
                    privileges = await is_bot_admin(client, chat_id)
                    if not privileges:
                        break
                else:
                    raise
        await message.reply(
            "Failed to promote: I need the 'Invite Users via Link' permission. "
            "Please go to chat settings > Administrators > Edit my permissions and enable 'Invite Users via Link', 'Ban Members', and 'Add New Admins'. "
            "If this persists, grant full admin rights to the bot."
        )
        logger.error(f"Promotion failed in {chat_id}: Missing required permissions")
        
    except RPCError as e:
        error_msg = str(e)
        if "PEER_ID_INVALID" in error_msg:
            await message.reply(
                f"Chat {chat_id} is invalid or inaccessible. "
                "Please verify the chat exists, I'm a member, and the ID is correct (e.g., -100123456789)."
            )
            logger.error(f"Promotion failed: Invalid chat {chat_id}")
        elif "CHAT_ADMIN_INVITE_REQUIRED" in error_msg:
            await message.reply(
                "Failed to promote: I need the 'Invite Users via Link' permission. "
                "Please go to chat settings > Administrators > Edit my permissions and enable 'Invite Users via Link', 'Ban Members', and 'Add New Admins'. "
                "If this persists, grant full admin rights to the bot."
            )
            logger.error(f"Promotion failed in {chat_id}: Missing 'Invite Users' permission")
        elif "USER_NOT_PARTICIPANT" in error_msg:
            # Try inviting again
            if await invite_user(client, chat_id, bot_member.id):
                await message.reply(f"Invited @{bot_username} to chat {chat_id}. Please retry the promotion.")
                logger.info(f"Invited @{bot_username} to chat {chat_id} after USER_NOT_PARTICIPANT")
            else:
                # If invite failed, rely on cache and timeout
                if chat_id in invite_cache and bot_member.id in invite_cache[chat_id]:
                    task = asyncio.create_task(
                        promote_with_timeout(client, chat_id, bot_member.id, bot_username)
                    )
                    invite_cache[chat_id][bot_member.id]["task"] = task
                    await message.reply(
                        f"Sent invite link to @{bot_username} for chat {chat_id}. "
                        "Waiting for them to join within 1 minute to promote."
                    )
                    return
                await message.reply(
                    f"@{bot_username} is not a member of chat {chat_id}, and I couldn't invite them. "
                    "Please add them manually or check my permissions."
                )
                logger.error(f"Failed to invite @{bot_username} to chat {chat_id}")
        else:
            await message.reply(f"Error: {error_msg}")
            logger.error(f"Failed to promote @{bot_username} in {chat_id}: {error_msg}")
    except Exception as e:
        await message.reply("An unexpected error occurred. Check logs for details.")
        logger.error(f"Unexpected error in /promote: {str(e)}")

# Command to promote a bot to admin in all stored chats with same permissions
@app.on_message(filters.command("promoteall") & filters.user(ADMIN_ID))
async def promote_bot_all(client: Client, message: Message):
    logger.info(f"Received /promoteall command from {message.from_user.id}")
    args = message.text.split()
    
    if len(args) != 2:
        await message.reply("Usage: /promoteall <bot_username> (e.g., /promoteall @BotUsername)")
        logger.warning("Invalid /promoteall command format")
        return
    
    bot_username = args[1].lstrip("@")
    success_count = 0
    failure_count = 0
    errors = []
    
    try:
        bot_member = await client.get_users(bot_username)
        chats = mongo_db.get_all_chats()
        if not chats:
            await message.reply("No chats found in the database. Use /addchat in a group or channel to add chats.")
            logger.warning("No chats found in MongoDB")
            return
        
        for chat in chats:
            chat_id = chat["chat_id"]
            chat_title = chat.get("chat_title", str(chat_id))
            try:
                # Validate chat
                if not await is_chat_valid(client, chat_id):
                    failure_count += 1
                    errors.append(
                        f"{chat_title} (ID: {chat_id}): Chat is invalid or inaccessible. "
                        "Verify the chat exists and I'm a member, or use /cleandb to remove it."
                    )
                    logger.warning(f"Invalid chat {chat_id} for promotion")
                    continue
                
                # Check target bot status
                status = await get_user_status(client, chat_id, bot_member.id)
                if status == "banned":
                    # Try unbanning
                    if await unban_user(client, chat_id, bot_member.id):
                        logger.info(f"Unbanned @{bot_username} in chat {chat_id}")
                        await asyncio.sleep(2)
                    else:
                        failure_count += 1
                        errors.append(
                            f"{chat_title} (ID: {chat_id}): @{bot_username} is banned and couldn't be unbanned. "
                            "Please unban them manually in chat settings > Banned Users."
                        )
                        logger.error(f"Failed to unban @{bot_username} in chat {chat_id}")
                        continue
                    # Try inviting after unban
                    if await invite_user(client, chat_id, bot_member.id):
                        await asyncio.sleep(2)
                        logger.info(f"Invited @{bot_username} to chat {chat_id} after unban")
                    else:
                        # If invite failed, rely on cache and timeout
                        if chat_id in invite_cache and bot_member.id in invite_cache[chat_id]:
                            task = asyncio.create_task(
                                promote_with_timeout(client, chat_id, bot_member.id, bot_username)
                            )
                            invite_cache[chat_id][bot_member.id]["task"] = task
                            errors.append(
                                f"{chat_title} (ID: {chat_id}): Sent invite link to @{bot_username}. "
                                "Waiting for them to join within 1 minute to promote."
                            )
                            continue
                        failure_count += 1
                        errors.append(
                            f"{chat_title} (ID: {chat_id}): Failed to invite @{bot_username} after unbanning. "
                            "Please add them manually or ensure I have 'Invite Users via Link' permission."
                        )
                        logger.error(f"Failed to invite @{bot_username} to chat {chat_id} after unban")
                        continue
                elif not status:
                    # Try inviting the bot
                    if await invite_user(client, chat_id, bot_member.id):
                        await asyncio.sleep(2)
                        logger.info(f"Invited @{bot_username} to chat {chat_id}")
                    else:
                        # If invite failed, rely on cache and timeout
                        if chat_id in invite_cache and bot_member.id in invite_cache[chat_id]:
                            task = asyncio.create_task(
                                promote_with_timeout(client, chat_id, bot_member.id, bot_username)
                            )
                            invite_cache[chat_id][bot_member.id]["task"] = task
                            errors.append(
                                f"{chat_title} (ID: {chat_id}): Sent invite link to @{bot_username}. "
                                "Waiting for them to join within 1 minute to promote."
                            )
                            continue
                        failure_count += 1
                        errors.append(
                            f"{chat_title} (ID: {chat_id}): Failed to invite @{bot_username}. "
                            "Please add them manually or ensure I have 'Invite Users via Link' permission."
                        )
                        logger.error(f"Failed to invite @{bot_username} to chat {chat_id}")
                        continue
                
                # Check admin status with fresh data
                privileges = await is_bot_admin(client, chat_id)
                if not privileges:
                    failure_count += 1
                    errors.append(
                        f"{chat_title} (ID: {chat_id}): Missing 'Invite Users via Link', 'Ban Members', or 'Add New Admins' permissions. "
                        "Try granting full admin rights."
                    )
                    logger.warning(f"Bot lacks permissions in chat {chat_id}")
                    continue
                
                # Attempt promotion with retry
                for attempt in range(2):
                    try:
                        await client.promote_chat_member(
                            chat_id=chat_id,
                            user_id=bot_member.id,
                            privileges=ChatPrivileges(**privileges)
                        )
                        success_count += 1
                        logger.info(f"Promoted @{bot_username} in chat {chat_id} ({chat_title}) with same permissions")
                        break
                    except RPCError as e:
                        error_msg = str(e)
                        if "CHAT_ADMIN_INVITE_REQUIRED" in error_msg and attempt == 0:
                            logger.warning(f"Promotion failed in {chat_id}: CHAT_ADMIN_INVITE_REQUIRED, retrying after refresh")
                            await asyncio.sleep(2)
                            privileges = await is_bot_admin(client, chat_id)
                            if not privileges:
                                break
                        else:
                            raise
                else:
                    failure_count += 1
                    errors.append(
                        f"{chat_title} (ID: {chat_id}): Missing 'Invite Users via Link' permission. "
                        "Enable it in chat settings > Administrators or grant full admin rights."
                    )
                    logger.error(f"Promotion failed in {chat_id}: Missing required permissions")
            
            except RPCError as e:
                failure_count += 1
                error_msg = str(e)
                if "PEER_ID_INVALID" in error_msg:
                    errors.append(
                        f"{chat_title} (ID: {chat_id}): Chat is invalid or inaccessible. "
                        "Verify the chat exists and I'm a member, or use /cleandb to remove it."
                    )
                    logger.error(f"Promotion failed: Invalid chat {chat_id}")
                elif "CHAT_ADMIN_INVITE_REQUIRED" in error_msg:
                    errors.append(
                        f"{chat_title} (ID: {chat_id}): Missing 'Invite Users via Link' permission. "
                        "Enable it in chat settings > Administrators or grant full admin rights."
                    )
                    logger.error(f"Promotion failed in {chat_id}: Missing 'Invite Users' permission")
                elif "USER_NOT_PARTICIPANT" in error_msg:
                    # Try inviting again
                    if await invite_user(client, chat_id, bot_member.id):
                        errors.append(f"{chat_title} (ID: {chat_id}): Invited @{bot_username}, please retry.")
                        logger.info(f"Invited @{bot_username} to chat {chat_id} after USER_NOT_PARTICIPANT")
                    else:
                        # If invite failed, rely on cache and timeout
                        if chat_id in invite_cache and bot_member.id in invite_cache[chat_id]:
                            task = asyncio.create_task(
                                promote_with_timeout(client, chat_id, bot_member.id, bot_username)
                            )
                            invite_cache[chat_id][bot_member.id]["task"] = task
                            errors.append(
                                f"{chat_title} (ID: {chat_id}): Sent invite link to @{bot_username}. "
                                "Waiting for them to join within 1 minute to promote."
                            )
                            continue
                        errors.append(
                            f"{chat_title} (ID: {chat_id}): @{bot_username} not a member and couldn't be invited. "
                            "Please add them manually."
                        )
                        logger.error(f"Failed to invite @{bot_username} to chat {chat_id}")
                else:
                    errors.append(f"{chat_title} (ID: {chat_id}): {error_msg}")
                    logger.error(f"Failed to promote @{bot_username} in {chat_id}: {error_msg}")
            except Exception as e:
                failure_count += 1
                errors.append(f"{chat_title} (ID: {chat_id}): Unexpected error")
                logger.error(f"Unexpected error promoting @{bot_username} in {chat_id}: {str(e)}")
        
        reply = f"Promotion complete!\nSuccessfully promoted @{bot_username} in {success_count} chats.\nFailed in {failure_count} chats."
        if errors:
            reply += "\n\nErrors:\n" + "\n".join([f"- {e}" for e in errors[:5]])
            if len(errors) > 5:
                reply += f"\n...and {len(errors) - 5} more (check logs)."
        await message.reply(reply)
        
    except Exception as e:
        await message.reply("An unexpected error occurred. Check logs for details.")
        logger.error(f"Unexpected error in /promoteall: {str(e)}")

# Start command for basic greeting
@app.on_message(filters.command("start") & filters.user(ADMIN_ID))
async def start(client: Client, message: Message):
    await message.reply(
        "Hello! I'm a bot that can invite and promote other bots to admin.\n"
        "Commands:\n"
        "/addchat - Add the current chat to the database (use in group/channel)\n"
        "/promote <bot_username> <chat_id> - Invite and promote a bot in a specific chat\n"
        "/promoteall <bot_username> - Invite and promote a bot in all stored chats\n"
        "/cleandb - Remove invalid chats from the database\n"
        "/init - Start periodic admin status checks"
    )
    logger.info(f"Start command received from {message.from_user.id}")

# Initialize periodic task after startup
@app.on_message(filters.command("init") & filters.user(ADMIN_ID))
async def init(client: Client, message: Message):
    try:
        asyncio.create_task(check_all_chats_admin_status(client))
        await message.reply("Initialized periodic admin status check.")
        logger.info("Initialized periodic admin status check")
    except Exception as e:
        await message.reply(f"Failed to initialize: {str(e)}")
        logger.error(f"Failed to initialize periodic check: {str(e)}")

# Run the bot
if __name__ == "__main__":
    logger.info("Starting Admin Promoter Bot")
    app.run()
