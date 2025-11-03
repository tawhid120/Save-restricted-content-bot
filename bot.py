"""
Telegram Content Saver Bot
===========================
A professional webhook-based bot that saves content from Telegram messages.

Features:
- Supports public and private channels
- Handles topic/forum messages
- Multiple media types support
- Robust error handling
- Webhook deployment ready
- --- NEW: Batch/Range post saving ---

Author: Your Name
Version: 2.3.0 (Fixed formatting loss & added /batch_download command)
License: MIT
"""

import logging
import os
import re
import asyncio  # --- NEW ---: Added for batch processing delay
from typing import Optional, Tuple, Dict, Any
from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram.enums import ParseMode  # --- UPDATED: Added for formatting fix ---

# ==================== CONFIGURATION ====================

class Config:
    """
    Bot configuration loaded from environment variables.
    
    Required:
        API_ID: Telegram API ID from my.telegram.org
        API_HASH: Telegram API Hash from my.telegram.org
        BOT_TOKEN: Bot token from @BotFather
    
    Optional:
        OWNER_ID: Telegram user ID for admin commands (can be None)
    """
    
    # Load environment variables
    API_ID: Optional[int] = None
    API_HASH: Optional[str] = None
    BOT_TOKEN: Optional[str] = None
    OWNER_ID: Optional[int] = None
    
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
            
            # Optional variables
            owner_id_str = os.environ.get("OWNER_ID")
            if owner_id_str:
                try:
                    cls.OWNER_ID = int(owner_id_str)
                except (ValueError, TypeError):
                    logging.warning("OWNER_ID not set or invalid. Admin commands will be disabled.")
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


# ==================== HELPER FUNCTIONS ====================

def is_owner(user_id: int) -> bool:
    """
    Check if a user is the bot owner.
    
    Args:
        user_id: Telegram user ID to check
        
    Returns:
        bool: True if user is owner, False otherwise
    """
    return Config.OWNER_ID is not None and user_id == Config.OWNER_ID


# --- MODIFIED: Updated parse_telegram_link to support ranges ---
def parse_telegram_link(link: str) -> Optional[Dict[str, Any]]:
    """
    Parse Telegram message links and extract relevant information.
    
    Supports single links and batch/range links (e.g., /100-110).
    
    Args:
        link: Telegram message link
        
    Returns:
        Dict with parsed information or None if link is invalid
    """
    link = link.strip().replace(" ", "") # Remove spaces
    
    # Define regex patterns for different link types
    # Batch/range patterns MUST come before single patterns
    patterns = [
        # --- NEW BATCH/RANGE PATTERNS ---
        # Private topic batch: https://t.me/c/1234567890/123/456-460
        (r"https?://t\.me/c/(\d+)/(\d+)/(\d+)-(\d+)$", "private_topic_batch"),
        
        # Public topic batch: https://t.me/channel/123/456-460
        (r"https?://t\.me/([^/]+)/(\d+)/(\d+)-(\d+)$", "public_topic_batch"),
        
        # Private channel batch: https://t.me/c/1234567890/123-130
        (r"https?://t\.me/c/(\d+)/(\d+)-(\d+)$", "private_batch"),
        
        # Public channel batch: https://t.me/channel/123-130
        (r"https?://t\.me/([^/]+)/(\d+)-(\d+)$", "public_batch"),
        
        # --- ORIGINAL SINGLE POST PATTERNS ---
        # Private topic: https://t.me/c/1234567890/123/456
        (r"https?://t\.me/c/(\d+)/(\d+)/(\d+)$", "private_topic"),
        
        # Private channel: https://t.me/c/1234567890/123
        (r"https?://t\.me/c/(\d+)/(\d+)$", "private"),
        
        # Public topic: https://t.me/channel/123/456
        (r"https://t\.me/([^/]+)/(\d+)/(\d+)$", "public_topic"),
        
        # Public channel: https://t.me/channel/123
        (r"https://t\.me/([^/]+)/(\d+)$", "public")
    ]
    
    for pattern, link_type in patterns:
        match = re.match(pattern, link)
        if match:
            # --- HANDLE BATCH TYPES ---
            if link_type == "public_topic_batch":
                return {
                    "type": "public_topic",
                    "channel": match.group(1),
                    "topic_id": int(match.group(2)),
                    "message_id_start": int(match.group(3)),
                    "message_id_end": int(match.group(4))
                }
            elif link_type == "private_topic_batch":
                return {
                    "type": "private_topic",
                    "chat_id": int(f"-100{match.group(1)}"),
                    "topic_id": int(match.group(2)),
                    "message_id_start": int(match.group(3)),
                    "message_id_end": int(match.group(4))
                }
            elif link_type == "private_batch":
                return {
                    "type": "private",
                    "chat_id": int(f"-100{match.group(1)}"),
                    "topic_id": None,
                    "message_id_start": int(match.group(2)),
                    "message_id_end": int(match.group(3))
                }
            elif link_type == "public_batch":
                return {
                    "type": "public",
                    "channel": match.group(1),
                    "topic_id": None,
                    "message_id_start": int(match.group(2)),
                    "message_id_end": int(match.group(3))
                }
                
            # --- HANDLE ORIGINAL SINGLE TYPES (Modified for consistency) ---
            elif link_type == "public_topic":
                msg_id = int(match.group(3))
                return {
                    "type": "public_topic",
                    "channel": match.group(1),
                    "topic_id": int(match.group(2)),
                    "message_id_start": msg_id,
                    "message_id_end": msg_id  # Start and end are the same
                }
            elif link_type == "private_topic":
                msg_id = int(match.group(3))
                return {
                    "type": "private_topic",
                    "chat_id": int(f"-100{match.group(1)}"),
                    "topic_id": int(match.group(2)),
                    "message_id_start": msg_id,
                    "message_id_end": msg_id
                }
            elif link_type == "private":
                msg_id = int(match.group(2))
                return {
                    "type": "private",
                    "chat_id": int(f"-100{match.group(1)}"),
                    "topic_id": None,
                    "message_id_start": msg_id,
                    "message_id_end": msg_id
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


# --- UPDATED: Function modified to preserve formatting ---
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
    message_thread_id: Optional[int] = None # This parameter is kept as requested
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
        message_thread_id: Topic ID for forum messages (optional)
        
    Returns:
        Tuple of (copied_message: Optional[Message], error: Optional[str])
    """
    try:
        # Fetch the original message
        original_msg = await client.get_messages(from_chat_id, message_id)
        
        if not original_msg:
            return None, "Message not found"
        
        # Check if message has any content
        if not original_msg.text and not original_msg.caption and not original_msg.media:
            return None, "Message is empty"
        
        # Method 1: Try manual copy by type (now preserves formatting)
        success, error = await send_message_by_type(client, original_msg, to_chat_id)
        if success:
            logger.info(f"Successfully copied message {message_id} using manual method")
            return original_msg, None
        
        # Method 2: Try Pyrogram's copy_message
        try:
            copied_msg = await client.copy_message(
                chat_id=to_chat_id,
                from_chat_id=from_chat_id,
                message_id=message_id
            )
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


async def handle_copy_error(status_msg: Message, error: Exception) -> None:
    """
    Handle and display user-friendly error messages.
    
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
        "CHAT_ADMIN_REQUIRED": "❌ Bot needs admin rights in the source channel.",
        "USER_NOT_PARTICIPANT": "❌ Bot is not a member of the source channel.",
        "MESSAGE_ID_INVALID": "❌ Message not found or invalid message ID.",
        "CHANNEL_PRIVATE": "❌ Cannot access private channel. Bot needs to be added to the channel.",
        "PEER_ID_INVALID": "❌ Invalid channel/chat ID. Make sure the link is correct.",
        "FLOOD_WAIT": "❌ Rate limited by Telegram. Please try again later.",
        "Message is empty": "❌ The message appears to be empty or has no content to copy.",
    }
    
    # Check for known error types
    for error_type, response in error_responses.items():
        if error_type in error_msg:
            await status_msg.edit(response)
            return
    
    # Generic error for unknown types
    await status_msg.edit(f"❌ Error: {error_msg}")


# ==================== BOT COMMAND HANDLERS ====================
# --- FIX: Added filters.private & ~filters.me to prevent spam loops ---

if app:
    
    @app.on_message(filters.command("start") & filters.private & ~filters.me)
    async def start_command(client: Client, message: Message):
        """
        Handle /start command - Display welcome message and usage instructions.
        
        This command is accessible to all users.
        """
        welcome_text = (
            "🤖 **Content Saver Bot**\n\n"
            "📋 **How to use:**\n"
            "• Send any Telegram message link\n"
            "• Bot will fetch and forward the content to you\n"
            "• Supports regular channels and topic/forum messages\n\n"
            "**--- NEW: Batch Saving ---**\n"
            "Send links in `from-to` format:\n"
            "`https://t.me/channel/100-110`\n"
            "(Maximum 25 posts at a time)\n\n"
            "For more details, send /batch_download\n\n"
            "✅ **Ready to save content!**"
        )
        await message.reply(welcome_text)
        logger.info(f"User {message.from_user.id} started the bot")
    
    
    # --- NEW: Added /batch_download command handler ---
    @app.on_message(filters.command("batch_download") & filters.private & ~filters.me)
    async def batch_command(client: Client, message: Message):
        """
        Handle /batch_download command - Explain how to use the batch feature.
        
        This command is accessible to all users.
        """
        batch_help_text = (
            "📤 **ব্যাচ সেভ (Batch Save) নির্দেশিকা**\n\n"
            "একাধিক পোস্ট একসাথে সেভ করতে, লিঙ্কটি `from-to` ফরম্যাটে পাঠান।\n\n"
            "**পাবলিক চ্যানেল/গ্রুপ:**\n"
            "`https://t.me/channel_username/1001-1010`\n\n"
            "**প্রাইভেট চ্যানেল/গ্রুপ:**\n"
            "`https://t.me/c/1234567890/101-120`\n\n"
            "**টপিক সহ (পাবলিক):**\n"
            "`https://t.me/channel_username/topic_id/50-60`\n\n"
            "**টপিক সহ (প্রাইভেট):**\n"
            "`https://t.me/c/123456789/topic_id/200-205`\n\n"
            "ℹ️ **দ্রষ্টব্য:** রেঞ্জের মধ্যে স্পেস থাকলেও (`101 - 120`) এটি কাজ করবে। নিরাপত্তার জন্য সর্বোচ্চ **২৫টি** পোস্ট একসাথে প্রসেস করা যাবে।"
        )
        await message.reply(batch_help_text)
        logger.info(f"User {message.from_user.id} requested batch help")
    
    
    # --- MODIFIED: Rewritten to handle single and batch links ---
    @app.on_message(filters.text & ~filters.command(["start", "batch_download", "status", "test", "debug"]) & filters.private & ~filters.me)
    async def handle_message_link(client: Client, message: Message):
        """
        Handle incoming Telegram message links (single or batch).
        
        This is the main functionality of the bot. It:
        1. Validates the message contains a Telegram link
        2. Parses the link (e.g., /100 or /100-110)
        3. Loops through the range and copies messages
        4. Provides a final report
        """
        text = message.text
        
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
        logger.info(f"Processing link from user {message.from_user.id}: {telegram_link}")
        
        # Send processing status
        status_msg = await message.reply("🔄 Processing your request...")
        
        try:
            # Parse the Telegram link
            parsed_link = parse_telegram_link(telegram_link)
            
            if not parsed_link:
                await status_msg.edit("❌ Invalid Telegram link format. Please check the link and try again.")
                return
            
            link_type = parsed_link["type"]
            msg_start = parsed_link["message_id_start"]
            msg_end = parsed_link["message_id_end"]
            
            # --- BATCH/RANGE CHECKS ---
            BATCH_LIMIT = 25  # Set a reasonable limit
            
            if msg_start > msg_end:
                await status_msg.edit("❌ Error: 'From' ID must be smaller than 'To' ID.")
                return
            
            num_messages = (msg_end - msg_start) + 1
            if num_messages > BATCH_LIMIT:
                await status_msg.edit(f"❌ Error: Range too large. Max **{BATCH_LIMIT}** posts at a time. You requested {num_messages}.")
                return
            
            # Determine chat ID based on link type
            if link_type in ["public_topic", "public"]:
                chat_id = parsed_link["channel"]
            else:
                chat_id = parsed_link["chat_id"]
            
            # Extract topic ID if present
            topic_id = parsed_link.get("topic_id")
            
            # --- PROCESS THE BATCH (even if it's just 1) ---
            success_count = 0
            fail_count = 0
            last_error = None
            
            if num_messages > 1:
                await status_msg.edit(f"🔄 Processing {num_messages} messages...")

            for msg_id in range(msg_start, msg_end + 1):
                copied_msg, error = await copy_message_with_fallback(
                    client=client,
                    from_chat_id=chat_id,
                    message_id=msg_id,
                    to_chat_id=message.chat.id,
                    message_thread_id=topic_id # Passing this parameter as requested
                )
                
                if error:
                    fail_count += 1
                    last_error = error
                    logger.warning(f"Failed to copy message {msg_id}: {error}")
                else:
                    success_count += 1
                    logger.info(f"Successfully copied message {msg_id} for user {message.from_user.id}")
                
                # Add a small delay to prevent flood waits
                if num_messages > 1:
                    await asyncio.sleep(0.5) 
            
            # --- FINAL REPORT ---
            if num_messages == 1:
                if success_count == 1:
                    success_msg = "✅ Content saved successfully!"
                    if topic_id:
                        success_msg += f" (from topic {topic_id})"
                    await status_msg.edit(success_msg)
                else:
                    # Show the specific error for the single failed message
                    await handle_copy_error(status_msg, Exception(last_error))
            else:
                # Batch summary
                await status_msg.edit(
                    f"✅ **Batch Complete**\n\n"
                    f"• Successfully saved: {success_count}\n"
                    f"• Failed to save: {fail_count}"
                )
        
        except Exception as e:
            await handle_copy_error(status_msg, e) # Use our handler to check for non-critical errors
            logger.error(f"Unexpected error processing link: {e}", exc_info=True)
    
    
    @app.on_message(filters.command("status") & filters.private & ~filters.me)
    async def status_command(client: Client, message: Message):
        """
        Check bot status and display information.
        
        This command is restricted to the bot owner.
        """
        # Check if user is owner
        if not is_owner(message.from_user.id):
            await message.reply("❌ This command is for the bot owner only.")
            logger.warning(f"Unauthorized status command from user {message.from_user.id}")
            return
        
        # Get bot information
        me = await client.get_me()
        
        status_text = (
            "🟢 **Bot Status: Online (Webhook Mode)**\n\n"
            f"🆔 **Bot ID:** `{me.id}`\n"
            f"👤 **Username:** @{me.username}\n"
            f"📝 **First Name:** {me.first_name}\n"
            f"🔧 **Pyrogram Version:** {client.pyro_version}\n"
            f"👑 **Owner ID:** `{Config.OWNER_ID}`"
        )
        
        await message.reply(status_text)
        logger.info(f"Status command executed by owner {message.from_user.id}")
    
    
    @app.on_message(filters.command("test") & filters.private & ~filters.me)
    async def test_link_parsing(client: Client, message: Message):
        """
        Test the link parsing functionality with sample links.
        
        This command is restricted to the bot owner.
        """
        if not is_owner(message.from_user.id):
            await message.reply("❌ This command is for the bot owner only.")
            return
        
        # Sample test links
        test_links = [
            # --- NEW BATCH LINKS ---
            "https://t.me/freecoursebioc1/2/203-205",   # Public topic batch
            "https://t.me/c/1234567890/123/456-457",    # Private topic batch
            "https://t.me/mychannel/123-125",           # Public channel batch
            "https://t.me/c/1234567890/123-124",         # Private channel batch
            
            # --- ORIGINAL SINGLE LINKS ---
            "https://t.me/mychannel/123",           # Public channel
            "https://t.me/c/1234567890/123",         # Private channel
            "https://t.me/freecoursebioc1/2/203",   # Public topic
        ]
        
        result = "🧪 **Link Parsing Test Results:**\n\n"
        
        for link in test_links:
            parsed = parse_telegram_link(link)
            if parsed:
                result += f"✅ Link parsed successfully\n"
                result += f"   `{link}`\n"
                result += f"   **Type:** {parsed['type']}\n"
                if 'topic_id' in parsed and parsed['topic_id']:
                    result += f"   **Topic ID:** {parsed['topic_id']}\n"
                result += f"   **Msg Start:** {parsed['message_id_start']}\n"
                result += f"   **Msg End:** {parsed['message_id_end']}\n\n"
            else:
                result += f"❌ Failed to parse\n   `{link}`\n\n"
        
        await message.reply(result)
        logger.info(f"Test command executed by owner {message.from_user.id}")
    
    
    @app.on_message(filters.command("debug") & filters.private & ~filters.me)
    async def debug_message(client: Client, message: Message):
        """
        Debug a Telegram message link and show detailed information.
        
        Usage: /debug <telegram_link>
        
        This command is restricted to the bot owner.
        """
        if not is_owner(message.from_user.id):
            await message.reply("❌ This command is for the bot owner only.")
            return
        
        # Extract link from command
        text = message.text.replace("/debug", "").strip()
        
        if not text:
            await message.reply(
                "**Usage:** `/debug <telegram_link>`\n\n"
                "**Example:** `/debug https://t.me/channel/123`\n"
                "**Or:** `/debug https://t.me/channel/123-125`"
            )
            return
        
        # Parse the link
        parsed = parse_telegram_link(text)
        
        if not parsed:
            await message.reply("❌ Invalid link format")
            return
            
        # --- MODIFIED: Use msg_start for debug ---
        msg_id_to_debug = parsed["message_id_start"] # Just debug the first message in a range
            
        try:
            # Determine chat ID
            if parsed["type"] in ["public_topic", "public"]:
                chat_id = parsed["channel"]
            else:
                chat_id = parsed["chat_id"]
            
            # Fetch message details
            original_msg = await client.get_messages(chat_id, msg_id_to_debug)
            
            if not original_msg:
                await message.reply("❌ Message not found or bot doesn't have access")
                return
            
            # Build debug information
            debug_info = (
                "🔍 **Link Debug Information**\n\n"
                f"**Link Type:** {parsed['type']}\n"
                f"**Chat ID:** `{chat_id}`\n"
                f"**Msg Start:** `{parsed['message_id_start']}`\n"
                f"**Msg End:** `{parsed['message_id_end']}`\n"
            )
            
            if 'topic_id' in parsed and parsed['topic_id']:
                debug_info += f"**Topic ID:** `{parsed['topic_id']}`\n"
            
            debug_info += f"\n**Content Analysis (for Msg ID: {msg_id_to_debug}):**\n"
            debug_info += f"• Has Text: {'✅' if original_msg.text else '❌'}\n"
            debug_info += f"• Has Caption: {'✅' if original_msg.caption else '❌'}\n"
            debug_info += f"• Has Media: {'✅' if original_msg.media else '❌'}\n"
            
            if original_msg.media:
                debug_info += f"• Media Type: {original_msg.media.value}\n"
            
            await message.reply(debug_info)
            logger.info(f"Debug command executed for link: {text}")
        
        except Exception as e:
            await message.reply(f"❌ Debug error: {str(e)}")
            logger.error(f"Debug command error: {e}", exc_info=True)


# ==================== MODULE EXPORTS ====================

# Export the app instance and BOT_TOKEN for use in main.py
__all__ = ['app', 'BOT_TOKEN']
BOT_TOKEN = Config.BOT_TOKEN

logger.info("Bot module loaded successfully")
