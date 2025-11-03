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

Author: Your Name
Version: 3.0.5 (Public Only, Quiz/Poll Fallback, No Admin Commands)
License: MIT
"""

import logging
import os
import re
import asyncio
from typing import Optional, Tuple, Dict, Any
from datetime import datetime, timezone
from pyrogram import Client, filters
from pyrogram.types import Message
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
    
    Optional:
        OWNER_ID: (No longer used in v3.0.5)
    """
    
    # Load environment variables
    API_ID: Optional[int] = None
    API_HASH: Optional[str] = None
    BOT_TOKEN: Optional[str] = None
    OWNER_ID: Optional[int] = None # This variable can remain but is unused
    
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
            
            # Optional: Load OWNER_ID for compatibility, though it's not used
            owner_id_str = os.environ.get("OWNER_ID")
            if owner_id_str:
                try:
                    cls.OWNER_ID = int(owner_id_str)
                except (ValueError, TypeError):
                    cls.OWNER_ID = None
            
            # Validate required variables
            if not all([cls.API_ID, cls.API_HASH, cls.BOT_TOKEN]):
                logging.critical("Missing required environment variables (API_ID, API_HASH, BOT_TOKEN)")
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


# ==================== BOT INITIALIZATION ====================

# Load configuration
config_valid = Config.load()

# Initialize Pyrogram client only if configuration is valid
if config_valid:
    app = Client(
        name="content_saver_bot",
        api_id=Config.API_ID,
        api_hash=Config.API_HASH,
        bot_token=Config.BOT_TOKEN,
        in_memory=True,  # Use in-memory session storage (ideal for serverless/webhook deployments)
    )
    logger.info("Bot client initialized successfully")
else:
    logger.error("Bot client not initialized due to invalid configuration")
    app = None

# --- NEW: State tracking for /cancel command ---
ACTIVE_BATCHES: Dict[int, bool] = {}


# ==================== HELPER FUNCTIONS ====================

# --- REMOVED: is_owner function is no longer needed ---

# --- MODIFIED: Restricted to PUBLIC links ONLY. No private, no topics. ---
def parse_telegram_link(link: str) -> Optional[Dict[str, Any]]:
    """
    Parse Telegram message links and extract relevant information.
    
    Supports ONLY public channels/groups (single and batch).
    Blocks all private links (t.me/c/...) and all topic links.
    
    Args:
        link: Telegram message link
        
    Returns:
        Dict with parsed information or None if link is invalid/restricted
    """
    link = link.strip().replace(" ", "") # Remove spaces
    
    # Define regex patterns
    # Batch/range patterns MUST come before single patterns
    patterns = [
        # Public channel batch: https://t.me/channel/123-130
        (r"https?://t\.me/([^/]+)/(\d+)-(\d+)$", "public_batch"),
        
        # Public channel: https://t.me/channel/123
        (r"https?://t\.me/([^/]+)/(\d+)$", "public")
        
        # --- All other types (private, topics) are intentionally removed ---
    ]
    
    for pattern, link_type in patterns:
        match = re.match(pattern, link)
        if match:
            # --- Handle BATCH type ---
            if link_type == "public_batch":
                return {
                    "type": "public",
                    "channel": match.group(1),
                    "topic_id": None, # Topics are not supported
                    "message_id_start": int(match.group(2)),
                    "message_id_end": int(match.group(3))
                }
            
            # --- Handle SINGLE type ---
            elif link_type == "public":
                msg_id = int(match.group(2))
                return {
                    "type": "public",
                    "channel": match.group(1),
                    "topic_id": None, # Topics are not supported
                    "message_id_start": msg_id,
                    "message_id_end": msg_id  # Start and end are the same
                }
    
    # If no pattern matches (e.g., private link, topic link, or invalid)
    return None


# --- UPDATED: Added Poll/Quiz support ---
async def send_message_by_type(client: Client, original_msg: Message, to_chat_id: int) -> Tuple[bool, Optional[str]]:
    """
    Send a message by determining its type and using the appropriate method.
    
    This function handles all common Telegram message types
    and preserves rich text formatting (bold, italic, links).
    
    Args:
        client: Pyrogram client instance
        original_msg: Original message to copy
        to_chat_id: Destination chat ID
        
    Returns:
        Tuple of (success: bool, error: Optional[str])
    """
    try:
        # --- MODIFIED v3.0.4: Skip Polls ---
        # A Bot account cannot get correct_option_id from a channel poll.
        # This will always fail. We must use copy_message as fallback.
        if original_msg.poll:
            return False, "Polls cannot be manually recreated by bots (API limitation)"
        # --- END MODIFIED BLOCK ---
        
        # Text message
        if original_msg.text:
            await client.send_message(
                chat_id=to_chat_id,
                text=original_msg.text.html,
                parse_mode=ParseMode.HTML
            )
        
        # Photo
        elif original_msg.photo:
            await client.send_photo(
                chat_id=to_chat_id,
                photo=original_msg.photo.file_id,
                caption=original_msg.caption.html if original_msg.caption else None,
                parse_mode=ParseMode.HTML
            )
        
        # Video
        elif original_msg.video:
            await client.send_video(
                chat_id=to_chat_id,
                video=original_msg.video.file_id,
                caption=original_msg.caption.html if original_msg.caption else None,
                parse_mode=ParseMode.HTML
            )
        
        # Document
        elif original_msg.document:
            await client.send_document(
                chat_id=to_chat_id,
                document=original_msg.document.file_id,
                caption=original_msg.caption.html if original_msg.caption else None,
                parse_mode=ParseMode.HTML
            )
        
        # Audio
        elif original_msg.audio:
            await client.send_audio(
                chat_id=to_chat_id,
                audio=original_msg.audio.file_id,
                caption=original_msg.caption.html if original_msg.caption else None,
                parse_mode=ParseMode.HTML
            )
        
        # Voice message
        elif original_msg.voice:
            await client.send_voice(
                chat_id=to_chat_id,
                voice=original_msg.voice.file_id,
                caption=original_msg.caption.html if original_msg.caption else None,
                parse_mode=ParseMode.HTML
            )
        
        # Sticker
        elif original_msg.sticker:
            await client.send_sticker(
                chat_id=to_chat_id,
                sticker=original_msg.sticker.file_id
            )
        
        # Animation/GIF
        elif original_msg.animation:
            await client.send_animation(
                chat_id=to_chat_id,
                animation=original_msg.animation.file_id,
                caption=original_msg.caption.html if original_msg.caption else None,
                parse_mode=ParseMode.HTML
            )
        
        # Unsupported type
        else:
            return False, "Unsupported message type"
        
        return True, None
    
    except Exception as e:
        logger.error(f"Error sending message by type: {e}")
        return False, str(e)


async def copy_message_with_fallback(
    client: Client,
    from_chat_id: int,
    message_id: int,
    to_chat_id: int,
    message_thread_id: Optional[int] = None # This parameter is kept
) -> Tuple[Optional[Message], Optional[str]]:
    """
    Copy a message with multiple fallback methods.
    
    This function attempts to copy a message using three methods in order:
    1. Manual copy by message type (most reliable, preserves formatting)
    2. Pyrogram's copy_message method
    3. Forward message as last resort
    
    Args:
        client: Pyrogram client instance
        from_chat_id: Source chat/channel ID
        message_id: Message ID to copy
        to_chat_id: Destination chat ID
        message_thread_id: Topic ID (not used in v3.0 but kept for compatibility)
        
    Returns:
        Tuple of (copied_message: Optional[Message], error: Optional[str])
    """
    try:
        # Fetch the original message
        original_msg = await client.get_messages(from_chat_id, message_id)
        
        if not original_msg:
            return None, "Message not found"
        
        # Check if message has any content
        if not original_msg.text and not original_msg.caption and not original_msg.media and not original_msg.poll:
            return None, "Message is empty"
        
        # --- MODIFIED v3.0.4: Skip manual copy for polls ---
        # We know send_message_by_type will fail for polls due to API limits,
        # so we skip it to go directly to copy_message.
        if not original_msg.poll:
            # Method 1: Try manual copy by type (for non-poll messages)
            success, error = await send_message_by_type(client, original_msg, to_chat_id)
            if success:
                logger.info(f"Successfully copied message {message_id} using manual method")
                return original_msg, None
            
            if error:
                 logger.warning(f"Manual copy failed for {message_id}. Falling back. Error: {error}")

        # Method 2: Try Pyrogram's copy_message (This will be the main method for polls)
        try:
            copied_msg = await client.copy_message(
                chat_id=to_chat_id,
                from_chat_id=from_chat_id,
                message_id=message_id
            )
            if original_msg.poll:
                logger.info(f"Successfully copied poll {message_id} using copy_message (API fallback)")
            else:
                 logger.info(f"Successfully copied message {message_id} using copy_message")
            return copied_msg, None
        except Exception as copy_error:
            logger.warning(f"copy_message failed: {copy_error}")
        
        # Method 3: Try forwarding as last resort
        try:
            forwarded_msg = await client.forward_messages(
                chat_id=to_chat_id,
                from_chat_id=from_chat_id,
                message_ids=message_id
            )
            logger.info(f"Successfully forwarded message {message_id}")
            return forwarded_msg, None
        except Exception as forward_error:
            logger.error(f"All methods failed. Last error: {forward_error}")
            return None, str(forward_error)
    
    except Exception as e:
        logger.error(f"Unexpected error in copy_message_with_fallback: {e}")
        return None, str(e)


# --- UPDATED: All messages translated to English ---
async def handle_copy_error(status_msg: Message, error: Exception) -> None:
    """
    Handle and display user-friendly error messages (in English).
    
    Args:
        status_msg: Status message to edit with error
        error: Exception that occurred
    """
    error_msg = str(error)
    
    # --- FIX: Ignore MESSAGE_NOT_MODIFIED errors ---
    if "MESSAGE_NOT_MODIFIED" in error_msg:
        logger.warning("Ignoring 'MESSAGE_NOT_MODIFIED' error (likely a duplicate webhook).")
        return
        
    # Map of error types to user-friendly messages
    error_responses = {
        "CHAT_ADMIN_REQUIRED": "❌ **Error:** Bot needs admin rights in the source channel.",
        "USER_NOT_PARTICIPANT": "❌ **Error:** Bot is not a member of the source channel. Please add it.",
        "MESSAGE_ID_INVALID": "❌ **Error:** Message not found or invalid message ID.",
        "CHANNEL_PRIVATE": "❌ **Error:** Cannot access private channel. This bot only supports public channels.",
        "PEER_ID_INVALID": "❌ **Error:** Invalid channel/chat ID. Make sure the link is correct.",
        "FLOOD_WAIT": "❌ **Error:** Rate limited by Telegram. Please try again later.",
        "Message is empty": "❌ **Error:** The message appears to be empty or has no content to copy.",
    }
    
    # Check for known error types
    for error_type, response in error_responses.items():
        if error_type in error_msg:
            try:
                await status_msg.edit(response)
            except MessageNotModified:
                pass # Ignore if message is already showing the error
            return
    
    # Generic error for unknown types
    try:
        await status_msg.edit(f"❌ **An unexpected error occurred:**\n`{error_msg}`")
    except MessageNotModified:
        pass


# ==================== BOT COMMAND HANDLERS ====================
# --- FIX: Added filters.private & ~filters.me to prevent spam loops ---

if app:
    
    # --- UPDATED: Translated to English ---
    @app.on_message(filters.command("start") & filters.private & ~filters.me)
    async def start_command(client: Client, message: Message):
        """
        Handle /start command - Display welcome message and usage instructions.
        
        This command is accessible to all users.
        """
        welcome_text = (
            "🤖 **Content Saver Bot** (v3.0.5)\n\n" # <-- Version updated
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
        logger.info(f"User {message.from_user.id} started the bot")
    
    
    # --- UPDATED: Translated to English ---
    @app.on_message(filters.command("batch_download") & filters.private & ~filters.me)
    async def batch_command(client: Client, message: Message):
        """
        Handle /batch_download command - Explain how to use the batch feature.
        
        This command is accessible to all users.
        """
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
    
    
    # --- NEW: /cancel command handler ---
    @app.on_message(filters.command("cancel") & filters.private & ~filters.me)
    async def cancel_command(client: Client, message: Message):
        """
        Handle /cancel command - Stops an active batch process for the user.
        
        This command is accessible to all users.
        """
        user_id = message.from_user.id
        if ACTIVE_BATCHES.get(user_id) is False:
            # The flag is False, meaning a batch is running but not yet cancelled
            ACTIVE_BATCHES[user_id] = True # Set flag to True
            await message.reply("Requesting cancellation... The batch will stop shortly.")
            logger.info(f"User {user_id} requested batch cancellation")
        elif ACTIVE_BATCHES.get(user_id) is True:
            # Flag is already True, cancellation is in progress
            await message.reply("Cancellation is already in progress...")
        else:
            # User is not in the dict, no batch is running
            await message.reply("You have no active batch operation to cancel.")
            logger.warning(f"User {user_id} tried to cancel with no active batch")
    
    
    # --- MODIFIED: Handles new restrictions, limit, and cancellation ---
    # --- REMOVED: "status", "test", "debug" from the filter ---
    @app.on_message(filters.text & ~filters.command(["start", "batch_download", "cancel"]) & filters.private & ~filters.me)
    async def handle_message_link(client: Client, message: Message):
        """
        Handle incoming Telegram message links (single or batch).
        
        This is the main functionality of the bot. It:
        1. Validates the message contains a Telegram link
        2. Parses the link (blocks private/topics)
        3. Loops through the range and copies messages
        4. Provides a final report
        5. Listens for /cancel
        """
        text = message.text
        user_id = message.from_user.id
        
        # Check if message contains a Telegram link
        if not any(domain in text for domain in ['t.me/', 'telegram.me/']):
            await message.reply("📎 Please send a valid Telegram message link.")
            return
        
        # Extract link using regex
        link_pattern = r'https?://(?:t\.me|telegram\.me)/\S+'
        link_match = re.search(link_pattern, text)
        
        if not link_match:
            await message.reply("❌ No valid Telegram link found in your message.")
            return
        
        telegram_link = link_match.group()
        logger.info(f"Processing link from user {user_id}: {telegram_link}")
        
        # Send processing status
        status_msg = await message.reply("🔄 Processing your request...")
        
        try:
            # Parse the Telegram link
            parsed_link = parse_telegram_link(telegram_link)
            
            # --- UPDATED: New error message for restricted links ---
            if not parsed_link:
                await status_msg.edit(
                    "❌ **Invalid Link Format**\n\n"
                    "I can only process links from **public** channels or groups.\n\n"
                    "**Private links** (`t.me/c/...`) and **Topic links** are **not** supported."
                )
                return
            
            msg_start = parsed_link["message_id_start"]
            msg_end = parsed_link["message_id_end"]
            
            # --- BATCH/RANGE CHECKS ---
            BATCH_LIMIT = 100  # --- UPDATED: Limit set to 100 ---
            
            if msg_start > msg_end:
                await status_msg.edit("❌ **Error:** 'From' ID must be smaller than 'To' ID.")
                return
            
            num_messages = (msg_end - msg_start) + 1
            if num_messages > BATCH_LIMIT:
                await status_msg.edit(f"❌ **Error:** Range too large. Max **{BATCH_LIMIT}** posts at a time. You requested {num_messages}.")
                return
            
            # Determine chat ID (will always be public username)
            chat_id = parsed_link["channel"]
            topic_id = None # Topics are not supported
            
            # --- PROCESS THE BATCH (even if it's just 1) ---
            success_count = 0
            fail_count = 0
            last_error = None
            
            # --- NEW: Setup for /cancel ---
            ACTIVE_BATCHES[user_id] = False # Set flag to False (running)
            
            if num_messages > 1:
                await status_msg.edit(f"🔄 Processing {num_messages} messages... (Send /cancel to stop)")

            for msg_id in range(msg_start, msg_end + 1):
                
                # --- NEW: Check for cancellation flag ---
                if ACTIVE_BATCHES.get(user_id, False):
                    logger.info(f"Batch cancelled by user {user_id} at msg {msg_id}")
                    await status_msg.edit("🛑 **Batch operation cancelled by user.**")
                    fail_count = (msg_end + 1) - msg_id # Count remaining as "failed"
                    break # Exit the loop
                
                copied_msg, error = await copy_message_with_fallback(
                    client=client,
                    from_chat_id=chat_id,
                    message_id=msg_id,
                    to_chat_id=message.chat.id,
                    message_thread_id=topic_id # Passing None
                )
                
                if error:
                    fail_count += 1
                    last_error = error
                    logger.warning(f"Failed to copy message {msg_id}: {error}")
                else:
                    success_count += 1
                    logger.info(f"Successfully copied message {msg_id} for user {user_id}")
                
                # Add a small delay to prevent flood waits
                if num_messages > 1:
                    await asyncio.sleep(0.5) 
            
            # --- FINAL REPORT (Translated) ---
            if num_messages == 1 and not ACTIVE_BATCHES.get(user_id, False):
                if success_count == 1:
                    success_msg = "✅ Content saved successfully!"
                    await status_msg.edit(success_msg)
                else:
                    # Show the specific error for the single failed message
                    await handle_copy_error(status_msg, Exception(last_error))
            elif not ACTIVE_BATCHES.get(user_id, False):
                # Batch summary
                await status_msg.edit(
                    f"✅ **Batch Complete**\n\n"
                    f"• Successfully saved: {success_count}\n"
                    f"• Failed to save: {fail_count}"
                )
        
        except Exception as e:
            await handle_copy_error(status_msg, e) # Use our handler
            logger.error(f"Unexpected error processing link: {e}", exc_info=True)
        
        finally:
            # --- NEW: Clean up user from active batches dict ---
            ACTIVE_BATCHES.pop(user_id, None)

    # --- REMOVED: status_command, test_link_parsing, and debug_message ---


# ==================== MODULE EXPORTS ====================

# Export the app instance and BOT_TOKEN for use in main.py
__all__ = ['app', 'BOT_TOKEN']
BOT_TOKEN = Config.BOT_TOKEN

logger.info("Bot module v3.0.5 (No Admin) loaded successfully")
