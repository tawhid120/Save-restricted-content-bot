"""
Telegram Content Saver Bot
===========================
A professional webhook-based bot that saves content from Telegram messages.

Features:
- Supports PUBLIC channels/groups only (v3.0)
- Handles Polls and Quizzes (v3.0.5 - Fallback, Cleaned)
- Batch/Range post saving (v3.0 - Limit 100)
- Batch cancellation feature (v3.0 - /cancel)
- Robust error handling
- Webhook deployment ready

=== NEW IN v3.1.0 (Admin Update) ===
- Google Firestore database integration for user tracking.
- Admin panel (/admin) with user stats and list.
- User ban/unban system (/ban, /unban).
- Admin-only commands restricted to OWNER_ID.

Author: Your Name
Version: 3.1.1 (SyntaxError Fix)
License: MIT
"""

import logging
import os
import re
import asyncio
import json
import io # NEW: For sending user list as a file
from typing import Optional, Tuple, Dict, Any
from datetime import datetime, timezone

# --- NEW: Firebase Admin SDK ---
import firebase_admin
from firebase_admin import credentials, firestore

from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.enums import ParseMode, PollType
from pyrogram.errors import MessageNotModified

# ==================== CONFIGURATION ====================

class Config:
    """
    Bot configuration loaded from environment variables.
    
    Required:
        API_ID: Telegram API ID from my.telegram.org
        API_HASH: Telegram API Hash from my.telegram.org
        BOT_TOKEN: Bot token from @BotFather
        OWNER_ID: Your Telegram User ID for admin commands
        FIREBASE_SERVICE_ACCOUNT_JSON: JSON content of your Google Firebase service account key
    """
    
    # Load environment variables
    API_ID: Optional[int] = None
    API_HASH: Optional[str] = None
    BOT_TOKEN: Optional[str] = None
    OWNER_ID: Optional[int] = None # --- NEW: Now required for admin features ---
    FIREBASE_SERVICE_ACCOUNT_JSON: Optional[str] = None # --- NEW: For Firebase ---
    
    @classmethod
    def load(cls) -> bool:
        """
        Load and validate configuration from environment variables.
        
        Returns:
            bool: True if configuration is valid, False otherwise
        """
        try:
            # Required variables
            cls.API_ID = int(os.environ.get("API_ID", 0))
            cls.API_HASH = os.environ.get("API_HASH")
            cls.BOT_TOKEN = os.environ.get("BOT_TOKEN")
            cls.OWNER_ID = int(os.environ.get("OWNER_ID", 0)) # --- NEW ---
            cls.FIREBASE_SERVICE_ACCOUNT_JSON = os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON") # --- NEW ---
            
            # Validate required variables
            if not all([cls.API_ID, cls.API_HASH, cls.BOT_TOKEN]):
                logging.critical("Missing required env vars (API_ID, API_HASH, BOT_TOKEN)")
                return False
            
            # --- NEW: Validate admin and firebase config ---
            if not cls.OWNER_ID:
                logging.critical("Missing required env var: OWNER_ID")
                return False
            if not cls.FIREBASE_SERVICE_ACCOUNT_JSON:
                logging.critical("Missing required env var: FIREBASE_SERVICE_ACCOUNT_JSON")
                return False
            
            return True
            
        except ValueError as e:
            logging.critical(f"Configuration error: {e}")
            return False


# ==================== LOGGING SETUP ====================

def setup_logging():
    """Configure logging with appropriate format and level."""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler()
        ]
    )

setup_logging()
logger = logging.getLogger(__name__)

# ==================== NEW: FIREBASE DATABASE SETUP ====================

db = None # Firestore client global variable

def init_firebase():
    """Initialize the Firebase Admin SDK and Firestore client."""
    global db
    try:
        # Parse the service account JSON from the environment variable
        service_account_info = json.loads(Config.FIREBASE_SERVICE_ACCOUNT_JSON)
        cred = credentials.Certificate(service_account_info)
        
        # Initialize only if no app is already initialized
        if not firebase_admin._apps:
            firebase_admin.initialize_app(cred)
            
        db = firestore.client()
        logger.info("Firebase Firestore client initialized successfully.")
    except Exception as e:
        logger.critical(f"Failed to initialize Firebase: {e}", exc_info=True)
        db = None

# --- NEW: Database Helper Functions ---

async def add_or_update_user(user, is_start=False):
    """Add or update user info in Firestore."""
    if not db:
        return None
    
    try:
        user_ref = db.collection('users').document(str(user.id))
        user_doc = user_ref.get()

        user_data = {
            'first_name': user.first_name,
            'username': user.username or '',
            'last_seen': firestore.SERVER_TIMESTAMP
        }

        if not user_doc.exists:
            # New user
            user_data['is_banned'] = False
            user_data['joined_date'] = firestore.SERVER_TIMESTAMP
            user_ref.set(user_data)
            logger.info(f"New user {user.id} ({user.first_name}) added to Firestore.")
            return user_data
        else:
            # Existing user
            user_data_existing = user_doc.to_dict()
            if 'is_banned' not in user_data_existing:
                user_data['is_banned'] = False # Backfill missing field
            
            user_ref.update(user_data)
            # Log only on start, not every message
            if is_start:
                logger.info(f"User {user.id} ({user.first_name}) updated (re-started).")
            return user_doc.to_dict() # Return existing data

    except Exception as e:
        logger.error(f"Failed to add/update user {user.id}: {e}")
        return None

async def get_user_data(user_id):
    """Get user data (including ban status) from Firestore."""
    if not db:
        return None
    try:
        user_ref = db.collection('users').document(str(user_id))
        user_doc = user_ref.get()
        if user_doc.exists:
            return user_doc.to_dict()
        return None # User not found
    except Exception as e:
        logger.error(f"Failed to get user data {user_id}: {e}")
        return None

async def set_ban_status(user_id: int, status: bool):
    """Set the ban status for a user."""
    if not db:
        return False, "Database not connected"
    try:
        user_ref = db.collection('users').document(str(user_id))
        user_ref.update({'is_banned': status})
        logger.info(f"User {user_id} ban status set to {status}")
        return True, "Success"
    except Exception as e:
        logger.error(f"Failed to set ban status for {user_id}: {e}")
        return False, str(e)

async def get_user_count():
    """Get total user count from Firestore."""
    if not db:
        return 0
    try:
        # This gets the count efficiently
        count_query = db.collection('users').count()
        count_result = count_query.get()
        return count_result[0][0].value
    except Exception as e:
        logger.error(f"Failed to get user count: {e}")
        return 0

async def get_all_users_from_db():
    """Get all users from Firestore."""
    if not db:
        return []
    try:
        users_stream = db.collection('users').stream()
        users_list = []
        # Add user_id to the dict as it's the document ID
        for doc in users_stream:
            user_data = doc.to_dict()
            user_data['user_id'] = doc.id
            users_list.append(user_data)
        return users_list
    except Exception as e:
        logger.error(f"Failed to get all users: {e}")
        return []

# ==================== BOT INITIALIZATION ====================

# Load configuration
config_valid = Config.load()

# --- NEW: Initialize Firebase ---
if config_valid:
    init_firebase()
else:
    logger.critical("Firebase not initialized due to invalid config.")

# Initialize Pyrogram client only if configuration is valid
if config_valid and db: # --- NEW: Check for DB connection ---
    app = Client(
        name="content_saver_bot",
        api_id=Config.API_ID,
        api_hash=Config.API_HASH,
        bot_token=Config.BOT_TOKEN,
        in_memory=True,
    )
    logger.info("Bot client initialized successfully")
else:
    logger.error("Bot client not initialized due to invalid configuration or DB failure")
    app = None

# --- State tracking for /cancel command ---
ACTIVE_BATCHES: Dict[int, bool] = {}


# ==================== HELPER FUNCTIONS ====================

# --- NEW: Admin check function ---
def is_owner(user_id: int) -> bool:
    """Check if the user ID matches the OWNER_ID."""
    return user_id == Config.OWNER_ID

# --- All existing helper functions (parse_telegram_link, send_message_by_type, etc.)
# --- are kept exactly as they were. ---

def parse_telegram_link(link: str) -> Optional[Dict[str, Any]]:
    link = link.strip().replace(" ", "") # Remove spaces
    patterns = [
        (r"https?://t\.me/([^/]+)/(\d+)-(\d+)$", "public_batch"),
        (r"https?://t\.me/([^/]+)/(\d+)$", "public")
    ]
    for pattern, link_type in patterns:
        match = re.match(pattern, link)
        if match:
            if link_type == "public_batch":
                return {
                    "type": "public",
                    "channel": match.group(1),
                    "topic_id": None,
                    "message_id_start": int(match.group(2)),
                    "message_id_end": int(match.group(3))
                }
            elif link_type == "public":
                msg_id = int(match.group(2))
                return {
                    "type": "public",
                    "channel": match.group(1),
                    "topic_id": None,
                    "message_id_start": msg_id,
                    "message_id_end": msg_id
                }
    return None

async def send_message_by_type(client: Client, original_msg: Message, to_chat_id: int) -> Tuple[bool, Optional[str]]:
    try:
        if original_msg.poll:
            return False, "Polls cannot be manually recreated by bots (API limitation)"
        if original_msg.text:
            await client.send_message(
                chat_id=to_chat_id, text=original_msg.text.html, parse_mode=ParseMode.HTML
            )
        elif original_msg.photo:
            await client.send_photo(
                chat_id=to_chat_id, photo=original_msg.photo.file_id,
                caption=original_msg.caption.html if original_msg.caption else None, parse_mode=ParseMode.HTML
            )
        elif original_msg.video:
            await client.send_video(
                chat_id=to_chat_id, video=original_msg.video.file_id,
                caption=original_msg.caption.html if original_msg.caption else None, parse_mode=ParseMode.HTML
            )
        elif original_msg.document:
            await client.send_document(
                chat_id=to_chat_id, document=original_msg.document.file_id,
                caption=original_msg.caption.html if original_msg.caption else None, parse_mode=ParseMode.HTML
            )
        elif original_msg.audio:
            await client.send_audio(
                chat_id=to_chat_id, audio=original_msg.audio.file_id,
                caption=original_msg.caption.html if original_msg.caption else None, parse_mode=ParseMode.HTML
            )
        elif original_msg.voice:
            await client.send_voice(
                chat_id=to_chat_id, voice=original_msg.voice.file_id,
                caption=original_msg.caption.html if original_msg.caption else None, parse_mode=ParseMode.HTML
            )
        elif original_msg.sticker:
            await client.send_sticker(chat_id=to_chat_id, sticker=original_msg.sticker.file_id)
        elif original_msg.animation:
            await client.send_animation(
                chat_id=to_chat_id, animation=original_msg.animation.file_id,
                caption=original_msg.caption.html if original_msg.caption else None, parse_mode=ParseMode.HTML
            )
        else:
            return False, "Unsupported message type"
        return True, None
    except Exception as e:
        logger.error(f"Error sending message by type: {e}")
        return False, str(e)

async def copy_message_with_fallback(
    client: Client, from_chat_id: int, message_id: int, to_chat_id: int,
    message_thread_id: Optional[int] = None
) -> Tuple[Optional[Message], Optional[str]]:
    try:
        original_msg = await client.get_messages(from_chat_id, message_id)
        if not original_msg:
            return None, "Message not found"
        if not original_msg.text and not original_msg.caption and not original_msg.media and not original_msg.poll:
            return None, "Message is empty"
        
        if not original_msg.poll:
            success, error = await send_message_by_type(client, original_msg, to_chat_id)
            if success:
                logger.info(f"Successfully copied message {message_id} using manual method")
                return original_msg, None
            if error:
                 logger.warning(f"Manual copy failed for {message_id}. Falling back. Error: {error}")

        try:
            copied_msg = await client.copy_message(
                chat_id=to_chat_id, from_chat_id=from_chat_id, message_id=message_id
            )
            if original_msg.poll:
                logger.info(f"Successfully copied poll {message_id} using copy_message (API fallback)")
            else:
                 logger.info(f"Successfully copied message {message_id} using copy_message")
            return copied_msg, None
        except Exception as copy_error:
            logger.warning(f"copy_message failed: {copy_error}")
        
        try:
            forwarded_msg = await client.forward_messages(
                chat_id=to_chat_id, from_chat_id=from_chat_id, message_ids=message_id
            )
            logger.info(f"Successfully forwarded message {message_id}")
            return forwarded_msg, None
        except Exception as forward_error:
            logger.error(f"All methods failed. Last error: {forward_error}")
            return None, str(forward_error)
    
    except Exception as e:
        logger.error(f"Unexpected error in copy_message_with_fallback: {e}")
        return None, str(e)

async def handle_copy_error(status_msg: Message, error: Exception) -> None:
    error_msg = str(error)
    if "MESSAGE_NOT_MODIFIED" in error_msg:
        logger.warning("Ignoring 'MESSAGE_NOT_MODIFIED' error.")
        return
    error_responses = {
        "CHAT_ADMIN_REQUIRED": "❌ **Error:** Bot needs admin rights in the source channel.",
        "USER_NOT_PARTICIPANT": "❌ **Error:** Bot is not a member of the source channel. Please add it.",
        "MESSAGE_ID_INVALID": "❌ **Error:** Message not found or invalid message ID.",
        "CHANNEL_PRIVATE": "❌ **Error:** Cannot access private channel. This bot only supports public channels.",
        "PEER_ID_INVALID": "❌ **Error:** Invalid channel/chat ID. Make sure the link is correct.",
        "FLOOD_WAIT": "❌ **Error:** Rate limited by Telegram. Please try again later.",
        "Message is empty": "❌ **Error:** The message appears to be empty or has no content to copy.",
    }
    for error_type, response in error_responses.items():
        if error_type in error_msg:
            try:
                await status_msg.edit(response)
            except MessageNotModified:
                pass
            return
    try:
        await status_msg.edit(f"❌ **An unexpected error occurred:**\n`{error_msg}`")
    except MessageNotModified:
        pass


# ==================== BOT COMMAND HANDLERS ====================

if app:
    
    # --- MODIFIED: /start command ---
    @app.on_message(filters.command("start") & filters.private & ~filters.me)
    async def start_command(client: Client, message: Message):
        """
        Handle /start command - Display welcome message and SAVE USER to DB.
        Checks for ban status.
        """
        user = message.from_user
        
        # --- NEW: Add user to DB and check ban status ---
        user_data = await add_or_update_user(user, is_start=True)
        
        if user_data and user_data.get('is_banned', False):
            await message.reply("❌ আপনি এই বটটি ব্যবহার করা থেকে নিষিদ্ধ (banned)।")
            logger.warning(f"Banned user {user.id} tried to /start")
            return
        
        # (Your existing welcome text)
        welcome_text = (
            "🤖 **Content Saver Bot** (v3.1.1)\n\n" # <-- Version updated
            "📋 **How to use:**\n"
            "• Send any **public** Telegram message link\n"
            "• Bot will fetch and forward the content to you\n\n"
            "⚠️ **Restrictions:**\n"
            "• **Private** channels/groups are **not** supported.\n"
            "• **Topic** links are **not** supported.\n\n"
            "**--- NEW: Batch Saving ---**\n"
            "Send links in `from-to` format:\n"
            "`https://t.me/channel/100-110`\n"
            "(Maximum **100** posts at a time)\n\n"
            "For more details, send /batch_download\n\n"
            "✅ **Ready to save content!**"
        )
        await message.reply(welcome_text)
        # Logger info is now inside add_or_update_user()
    
    
    # --- MODIFIED: /batch_download command ---
    @app.on_message(filters.command("batch_download") & filters.private & ~filters.me)
    async def batch_command(client: Client, message: Message):
        """
        Handle /batch_download command - Explain how to use the batch feature.
        Checks for ban status.
        """
        # --- NEW: Ban check ---
        user_data = await get_user_data(message.from_user.id)
        if user_data and user_data.get('is_banned', False):
            await message.reply("❌ আপনি এই বটটি ব্যবহার করা থেকে নিষিদ্ধ (banned)।")
            return
        
        # (Your existing batch help text)
        batch_help_text = (
            "📤 **Batch Saving Guide**\n\n"
            "To save multiple posts at once, send the link in a `from-to` format.\n\n"
            "**Example (Public Channel):**\n"
            "`https://t.me/channel_username/1001-1010`\n\n"
            "ℹ️ **Notes:**\n"
            "• Spaces in the range (`101 - 120`) will also work.\n"
            "• The maximum allowed range is **100** posts at a time.\n"
            "• Only public channels/groups are supported.\n\n"
            "To stop a batch process, send /cancel"
        )
        await message.reply(batch_help_text)
        logger.info(f"User {message.from_user.id} requested batch help")
    
    
    # --- MODIFIED: /cancel command handler ---
    @app.on_message(filters.command("cancel") & filters.private & ~filters.me)
    async def cancel_command(client: Client, message: Message):
        """
        Handle /cancel command - Stops an active batch process for the user.
        Checks for ban status.
        """
        user_id = message.from_user.id
        
        # --- NEW: Ban check ---
        user_data = await get_user_data(user_id)
        if user_data and user_data.get('is_banned', False):
            await message.reply("❌ আপনি এই বটটি ব্যবহার করা থেকে নিষিদ্ধ (banned)।")
            return
            
        # (Your existing cancel logic)
        if ACTIVE_BATCHES.get(user_id) is False:
            ACTIVE_BATCHES[user_id] = True 
            await message.reply("Requesting cancellation... The batch will stop shortly.")
            logger.info(f"User {user_id} requested batch cancellation")
        elif ACTIVE_BATCHES.get(user_id) is True:
            await message.reply("Cancellation is already in progress...")
        else:
            await message.reply("You have no active batch operation to cancel.")
            logger.warning(f"User {user_id} tried to cancel with no active batch")
    
    
    # ==================== NEW: ADMIN COMMANDS ====================
    
    @app.on_message(filters.command("admin") & filters.private & ~filters.me)
    async def admin_panel_command(client: Client, message: Message):
        """
        Display the admin panel with stats and user management buttons.
        Restricted to OWNER_ID.
        """
        if not is_owner(message.from_user.id):
            return # Ignore silently if not owner
        
        try:
            total_users = await get_user_count()
            
            text = f"👮‍♂️ **Admin Panel**\n\n"
            text += f"📊 **Total Users:** `{total_users}`"
            
            keyboard = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton("🔄 Refresh Stats", callback_data="admin_stats"),
                        InlineKeyboardButton("👥 View All Users", callback_data="view_all_users")
                    ],
                    [
                        InlineKeyboardButton("ℹ️ How to Ban/Unban?", callback_data="admin_help_ban")
                    ]
                ]
            )
            await message.reply(text, reply_markup=keyboard)
        except Exception as e:
            await message.reply(f"❌ Error fetching admin stats: {e}")
            logger.error(f"Error in /admin: {e}")

    @app.on_message(filters.command("ban") & filters.private & ~filters.me)
    async def ban_user_command(client: Client, message: Message):
        """
        Ban a user by their ID.
        Restricted to OWNER_ID.
        """
        if not is_owner(message.from_user.id):
            return
        
        try:
            parts = message.text.split()
            if len(parts) < 2:
                await message.reply("Usage: `/ban [USER_ID]`")
                return
            
            user_id_to_ban = int(parts[1])
            success, msg = await set_ban_status(user_id_to_ban, True)
            
            if success:
                await message.reply(f"✅ User `{user_id_to_ban}` has been **banned**.")
            else:
                await message.reply(f"❌ Failed to ban user `{user_id_to_ban}`: {msg}")
        except ValueError:
            await message.reply("❌ Invalid User ID. It must be a number.")
        except Exception as e:
            await message.reply(f"❌ Error during banning: {e}")

    @app.on_message(filters.command("unban") & filters.private & ~filters.me)
    async def unban_user_command(client: Client, message: Message):
        """
        Unban a user by their ID.
        Restricted to OWNER_ID.
        """
        if not is_owner(message.from_user.id):
            return

        try:
            parts = message.text.split()
            if len(parts) < 2:
                await message.reply("Usage: `/unban [USER_ID]`")
                return
            
            user_id_to_unban = int(parts[1])
            success, msg = await set_ban_status(user_id_to_unban, False)
            
            if success:
                await message.reply(f"✅ User `{user_id_to_unban}` has been **unbanned**.")
            else:
                await message.reply(f"❌ Failed to unban user `{user_id_to_unban}`: {msg}")
        except ValueError:
            await message.reply("❌ Invalid User ID. It must be a number.")
        except Exception as e:
            await message.reply(f"❌ Error during unbanning: {e}")

    # ==================== NEW: ADMIN CALLBACK HANDLER ====================

    @app.on_callback_query()
    async def admin_callback_handler(client: Client, callback_query):
        """Handle all callback queries from the admin panel."""
        if not is_owner(callback_query.from_user.id):
            await callback_query.answer("❌ This is for the admin only.", show_alert=True)
            return

        data = callback_query.data
        
        try:
            if data == "admin_stats":
                # Refresh stats
                total_users = await get_user_count()
                text = f"👮‍♂️ **Admin Panel**\n\n"
                text += f"📊 **Total Users:** `{total_users}`"
                
                await callback_query.message.edit_text(text, reply_markup=callback_query.message.reply_markup)
                await callback_query.answer("Stats refreshed!")
            
            elif data == "view_all_users":
                # Send a list of all users as a file
                await callback_query.answer("Please wait, fetching all users...")
                users_list = await get_all_users_from_db()
                
                if not users_list:
                    await callback_query.message.reply("No users found in the database.")
                    return

                # Create a text file in memory
                output = "USER_ID,FIRST_NAME,USERNAME,IS_BANNED\n"
                for user in users_list:
                    # Format data for CSV
                    user_id = user.get('user_id', 'N/A')
                    first_name = str(user.get('first_name', 'N/A')).replace(',', '') # Remove commas
                    username = str(user.get('username', 'N/A')).replace(',', '')
                    is_banned = user.get('is_banned', 'N/A')
                    output += f"{user_id},{first_name},{username},{is_banned}\n"
                
                # Send the file
                with io.BytesIO(output.encode('utf-8')) as f:
                    f.name = "all_users.csv"
                    await callback_query.message.reply_document(
                        document=f,
                        caption=f"Here is the list of all {len(users_list)} users."
                    )
            
            elif data == "admin_help_ban":
                await callback_query.answer() # Close the "loading"
                await callback_query.message.reply(
                    "**How to Ban/Unban:**\n\n"
                    "To ban a user, send:\n"
                    "`/ban 12345678`\n\n"
                    "To unban a user, send:\n"
                    "`/unban 12345678`\n\n"
                    "(Replace `12345678` with the user's Telegram ID)"
                )
                
        except MessageNotModified:
            await callback_query.answer() # Acknowledge
        except Exception as e:
            logger.error(f"Error in admin callback: {e}", exc_info=True)
            await callback_query.answer(f"Error: {e}", show_alert=True)
    
    
    # ==================== MAIN MESSAGE HANDLER ====================
    
    # --- MODIFIED: Handles new restrictions, limit, cancellation, and BAN CHECK ---
    @app.on_message(filters.text & ~filters.command(["start", "batch_download", "cancel", "admin", "ban", "unban"]) & filters.private & ~filters.me)
    async def handle_message_link(client: Client, message: Message):
        """
        Handle incoming Telegram message links (single or batch).
        This is the main functionality of the bot.
        """
        text = message.text
        user = message.from_user
        
        # --- NEW: Add/Update user and check ban status ---
        user_data = await add_or_update_user(user, is_start=False) # is_start=False
        if user_data and user_data.get('is_banned', False):
            # Do not reply, just log and ignore
            logger.warning(f"Banned user {user.id} tried to send a link. Ignoring.")
            return

        # (Your existing link processing logic)
        
        if not any(domain in text for domain in ['t.me/', 'telegram.me/']):
            await message.reply("📎 Please send a valid Telegram message link.")
            return
        
        link_pattern = r'https?://(?:t\.me|telegram\.me)/\S+'
        link_match = re.search(link_pattern, text)
        
        if not link_match:
            await message.reply("❌ No valid Telegram link found in your message.")
            return
        
        telegram_link = link_match.group()
        logger.info(f"Processing link from user {user.id}: {telegram_link}")
        
        status_msg = await message.reply("🔄 Processing your request...")
        
        try:
            parsed_link = parse_telegram_link(telegram_link)
            
            if not parsed_link:
                await status_msg.edit(
                    "❌ **Invalid Link Format**\n\n"
                    "I can only process links from **public** channels or groups.\n\n"
                    "**Private links** (`t.me/c/...`) and **Topic links** are **not** supported."
                )
                return
            
            msg_start = parsed_link["message_id_start"]
            msg_end = parsed_link["message_id_end"]
            
            BATCH_LIMIT = 100
            
            if msg_start > msg_end:
                await status_msg.edit("❌ **Error:** 'From' ID must be smaller than 'To' ID.")
                return
            
            num_messages = (msg_end - msg_start) + 1
            if num_messages > BATCH_LIMIT:
                await status_msg.edit(f"❌ **Error:** Range too large. Max **{BATCH_LIMIT}** posts at a time. You requested {num_messages}.")
                return
            
            chat_id = parsed_link["channel"]
            topic_id = None 
            
            success_count = 0
            fail_count = 0
            last_error = None
            
            ACTIVE_BATCHES[user.id] = False
            
            if num_messages > 1:
                await status_msg.edit(f"🔄 Processing {num_messages} messages... (Send /cancel to stop)")

            for msg_id in range(msg_start, msg_end + 1):
                
                if ACTIVE_BATCHES.get(user.id, False):
                    logger.info(f"Batch cancelled by user {user.id} at msg {msg_id}")
                    await status_msg.edit("🛑 **Batch operation cancelled by user.**")
                    fail_count = (msg_end + 1) - msg_id
                    break
                
                copied_msg, error = await copy_message_with_fallback(
                    client=client,
                    from_chat_id=chat_id,
                    message_id=msg_id,
                    to_chat_id=message.chat.id,
                    message_thread_id=topic_id
                )
                
                if error:
                    fail_count += 1
                    last_error = error
                    logger.warning(f"Failed to copy message {msg_id}: {error}")
                else:
                    success_count += 1
                    logger.info(f"Successfully copied message {msg_id} for user {user.id}")
                
                if num_messages > 1:
                    await asyncio.sleep(0.5) 
            
            if num_messages == 1 and not ACTIVE_BATCHES.get(user.id, False):
                if success_count == 1:
                    success_msg = "✅ Content saved successfully!"
                    await status_msg.edit(success_msg)
                else:
                    await handle_copy_error(status_msg, Exception(last_error))
            elif not ACTIVE_BATCHES.get(user.id, False):
                # Batch summary
                # --- THIS IS THE FIX ---
                await status_msg.edit(
                    f"✅ **Batch Complete**\n\n"
                    f"• Successfully saved: {success_count}\n"
                    f"• Failed to save: {fail_count}" # <-- FIX: Removed the typo 'f•' and made it a valid string
                )
        
        except Exception as e:
            await handle_copy_error(status_msg, e)
            logger.error(f"Unexpected error processing link: {e}", exc_info=True)
        
        finally:
            ACTIVE_BATCHES.pop(user.id, None)


# ==================== MODULE EXPORTS ====================

# Export the app instance and BOT_TOKEN for use in main.py
__all__ = ['app', 'BOT_TOKEN']
BOT_TOKEN = Config.BOT_TOKEN

logger.info("Bot module v3.1.1 (Admin+Firebase+Fix) loaded successfully")

