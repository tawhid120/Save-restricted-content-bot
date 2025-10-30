import logging
from pyrogram import Client, filters
from pyrogram.types import Message
import asyncio
import re

# Configuration (এগুলো আমরা Render-এ সেট করবো)
API_ID = 20193909
API_HASH = "82cd035fc1eb439bda68b2bfc75a57cb"
BOT_TOKEN = "8373638513:AAH24ImOHsgnug64Y1KxOaGm8mgIq-WfxRI"
OWNER_ID = 7214443852

# Setup logging
logging.basicConfig(level=logging.INFO)

# --- পরিবর্তন এখানে ---
# Create bot client with in_memory=True
app = Client(
    "content_saver_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    in_memory=True  # এই লাইনটি যোগ করা হয়েছে
)

def is_owner(user_id: int) -> bool:
    """Check if user is the owner"""
    return user_id == OWNER_ID

def parse_telegram_link(link):
    """Enhanced URL parsing with better error handling for topic messages"""
    link = link.strip()

    patterns = [
        (r"https?://t\.me/c/(\d+)/(\d+)/(\d+)$", "private_topic"),
        (r"https?://t\.me/c/(\d+)/(\d+)$", "private"),
        (r"https?://t\.me/([^/]+)/(\d+)/(\d+)$", "public_topic"),
        (r"https?://t\.me/([^/]+)/(\d+)$", "public")
    ]

    for pattern, link_type in patterns:
        match = re.match(pattern, link)
        if match:
            if link_type == "public_topic":
                return {
                    "type": "public_topic",
                    "channel": match.group(1),
                    "topic_id": int(match.group(2)),
                    "message_id": int(match.group(3))
                }
            elif link_type == "private_topic":
                return {
                    "type": "private_topic",
                    "chat_id": int(f"-100{match.group(1)}"),
                    "topic_id": int(match.group(2)),
                    "message_id": int(match.group(3))
                }
            elif link_type == "private":
                return {
                    "type": "private",
                    "chat_id": int(f"-100{match.group(1)}"),
                    "message_id": int(match.group(2)),
                    "topic_id": None
                }
            elif link_type == "public":
                return {
                    "type": "public",
                    "channel": match.group(1),
                    "message_id": int(match.group(2)),
                    "topic_id": None
                }

    return None

async def send_message_copy(client, original_msg, to_chat_id):
    """Send message by copying content manually"""
    try:
        if original_msg.text:
            await client.send_message(
                chat_id=to_chat_id,
                text=original_msg.text
            )
        elif original_msg.photo:
            await client.send_photo(
                chat_id=to_chat_id,
                photo=original_msg.photo.file_id,
                caption=original_msg.caption if original_msg.caption else ""
            )
        elif original_msg.video:
            await client.send_video(
                chat_id=to_chat_id,
                video=original_msg.video.file_id,
                caption=original_msg.caption if original_msg.caption else ""
            )
        elif original_msg.document:
            await client.send_document(
                chat_id=to_chat_id,
                document=original_msg.document.file_id,
                caption=original_msg.caption if original_msg.caption else ""
            )
        elif original_msg.audio:
            await client.send_audio(
                chat_id=to_chat_id,
                audio=original_msg.audio.file_id,
                caption=original_msg.caption if original_msg.caption else ""
            )
        elif original_msg.voice:
            await client.send_voice(
                chat_id=to_chat_id,
                voice=original_msg.voice.file_id,
                caption=original_msg.caption if original_msg.caption else ""
            )
        elif original_msg.sticker:
            await client.send_sticker(
                chat_id=to_chat_id,
                sticker=original_msg.sticker.file_id
            )
        elif original_msg.animation:
            await client.send_animation(
                chat_id=to_chat_id,
                animation=original_msg.animation.file_id,
                caption=original_msg.caption if original_msg.caption else ""
            )
        else:
            return None, "Unsupported message type"

        return True, None

    except Exception as e:
        return None, str(e)

async def copy_message_with_media(client, from_chat_id, message_id, to_chat_id, message_thread_id=None):
    """Copy message with proper media handling"""
    try:
        # Get the original message first
        original_msg = await client.get_messages(from_chat_id, message_id)

        if not original_msg:
            return None, "Message not found"

        # Check if message is empty
        if not original_msg.text and not original_msg.caption and not original_msg.media:
            return None, "Message is empty"

        # Try manual copy first
        success, error = await send_message_copy(client, original_msg, to_chat_id)
        if success:
            return success, None

        # If manual copy fails, try regular copy_message (without thread_id for topic messages)
        try:
            copied_msg = await client.copy_message(
                chat_id=to_chat_id,
                from_chat_id=from_chat_id,
                message_id=message_id
            )
            return copied_msg, None
        except Exception as copy_error:
            # If copy_message fails, try to forward the message
            try:
                forwarded_msg = await client.forward_messages(
                    chat_id=to_chat_id,
                    from_chat_id=from_chat_id,
                    message_ids=message_id
                )
                return forwarded_msg, None
            except Exception as forward_error:
                return None, str(copy_error)

    except Exception as e:
        return None, str(e)

@app.on_message(filters.command("start"))
async def start_command(client, message: Message):
    """Handle /start command"""
    if not is_owner(message.from_user.id):
        await message.reply("❌ Access Denied! This bot is private.")
        return

    await message.reply(
        "🤖 **Content Saver Bot (Webhook)**\n\n"
        "📋 **How to use:**\n"
        "• Send any Telegram message link\n"
        "• Bot will try to fetch and forward the content\n"
        "• Now supports topic messages!\n\n"
        "✅ **Ready to save content!**"
    )

@app.on_message(filters.text & ~filters.command("start"))
async def handle_message(client, message: Message):
    """Handle incoming messages with topic support"""
    if not is_owner(message.from_user.id):
        await message.reply("❌ Access Denied!")
        return

    text = message.text

    # Check if message contains a Telegram link
    if not any(domain in text for domain in ['t.me/', 'telegram.me/']):
        await message.reply("📎 Please send a valid Telegram message link.")
        return

    # Extract link from text
    link_pattern = r'https?://(?:t\.me|telegram\.me)/\S+'
    link_match = re.search(link_pattern, text)

    if not link_match:
        await message.reply("❌ No valid Telegram link found.")
        return

    telegram_link = link_match.group()

    # Send processing message
    status_msg = await message.reply("🔄 Processing...")

    try:
        # Parse the link using the enhanced function
        parsed_link = parse_telegram_link(telegram_link)

        if not parsed_link:
            await status_msg.edit("❌ Invalid Telegram link format.")
            return

        # Handle different link types
        if parsed_link["type"] == "public_topic":
            # Public channel with topic
            channel = parsed_link["channel"]
            topic_id = parsed_link["topic_id"]
            msg_id = parsed_link["message_id"]

            copied_msg, error = await copy_message_with_media(
                client, 
                from_chat_id=channel,
                message_id=msg_id,
                to_chat_id=message.chat.id,
                message_thread_id=topic_id
            )

            if error:
                await handle_copy_error(status_msg, Exception(error))
            else:
                await status_msg.edit(f"✅ Content saved from topic {topic_id}!")

        elif parsed_link["type"] == "private_topic":
            # Private channel with topic
            chat_id = parsed_link["chat_id"]
            topic_id = parsed_link["topic_id"]
            msg_id = parsed_link["message_id"]

            copied_msg, error = await copy_message_with_media(
                client,
                from_chat_id=chat_id,
                message_id=msg_id,
                to_chat_id=message.chat.id,
                message_thread_id=topic_id
            )

            if error:
                await handle_copy_error(status_msg, Exception(error))
            else:
                await status_msg.edit(f"✅ Content saved from private topic {topic_id}!")

        elif parsed_link["type"] == "public":
            # Regular public channel
            channel = parsed_link["channel"]
            msg_id = parsed_link["message_id"]

            copied_msg, error = await copy_message_with_media(
                client,
                from_chat_id=channel,
                message_id=msg_id,
                to_chat_id=message.chat.id
            )

            if error:
                await handle_copy_error(status_msg, Exception(error))
            else:
                await status_msg.edit("✅ Content saved successfully!")

        elif parsed_link["type"] == "private":
            # Regular private channel
            chat_id = parsed_link["chat_id"]
            msg_id = parsed_link["message_id"]

            copied_msg, error = await copy_message_with_media(
                client,
                from_chat_id=chat_id,
                message_id=msg_id,
                to_chat_id=message.chat.id
            )

            if error:
                await handle_copy_error(status_msg, Exception(error))
            else:
                await status_msg.edit("✅ Content saved successfully!")

    except Exception as e:
        await status_msg.edit(f"❌ Unexpected error: {str(e)}")

async def handle_copy_error(status_msg, error):
    """Handle copy message errors"""
    error_msg = str(error)
    if "CHAT_ADMIN_REQUIRED" in error_msg:
        await status_msg.edit("❌ Bot needs admin rights in the source channel.")
    elif "USER_NOT_PARTICIPANT" in error_msg:
        await status_msg.edit("❌ Bot is not a member of the source channel.")
    elif "MESSAGE_ID_INVALID" in error_msg:
        await status_msg.edit("❌ Message not found or invalid message ID.")
    elif "CHANNEL_PRIVATE" in error_msg:
        await status_msg.edit("❌ Cannot access private channel. Bot needs to be added to the channel.")
    elif "PEER_ID_INVALID" in error_msg:
        await status_msg.edit("❌ Invalid channel/chat ID. Make sure the link is correct.")
    elif "FLOOD_WAIT" in error_msg:
        await status_msg.edit("❌ Rate limited. Please try again later.")
    elif "Message is empty" in error_msg:
        await status_msg.edit("❌ The message appears to be empty or has no content to copy.")
    elif "copy_message" in error_msg.lower():
        await status_msg.edit("❌ Cannot copy this message. It might be a service message or restricted content.")
    else:
        await status_msg.edit(f"❌ Error: {error_msg}")

@app.on_message(filters.command("status"))
async def status_command(client, message: Message):
    """Check bot status"""
    if not is_owner(message.from_user.id):
        await message.reply("❌ Access Denied!")
        return

    # বট ক্লায়েন্ট থেকে me (নিজের) তথ্য নিন
    me = await client.get_me()

    await message.reply(
        "🟢 **Bot Status: Online (Webhook)**\n\n"
        f"🆔 **Bot ID:** {me.id}\n"
        f"👤 **Bot Username:** @{me.username}\n"
        f"📱 **Pyrogram Version:** {Client.pyro_version}"
    )

@app.on_message(filters.command("test"))
async def test_command(client, message: Message):
    """Test link parsing"""
    if not is_owner(message.from_user.id):
        await message.reply("❌ Access Denied!")
        return

    test_links = [
        "https://t.me/freecoursebioc1/2/203",   # Public topic
        "https://t.me/c/1234567890/123/456",    # Private topic
        "https://t.me/channel/123",             # Public channel
        "https://t.me/c/1234567890/123"         # Private channel
    ]

    result = "🧪 **Link Parsing Test:**\n\n"
    for link in test_links:
        parsed = parse_telegram_link(link)
        if parsed:
            result += f"✅ `{link}`\n"
            result += f"   Type: {parsed['type']}\n"
            if 'topic_id' in parsed and parsed['topic_id']:
                result += f"   Topic ID: {parsed['topic_id']}\n"
            result += "\n"
        else:
            result += f"❌ `{link}` - Failed to parse\n\n"

    await message.reply(result)

@app.on_message(filters.command("debug"))
async def debug_command(client, message: Message):
    """Debug message details"""
    if not is_owner(message.from_user.id):
        await message.reply("❌ Access Denied!")
        return

    # Get the message text after the command
    text = message.text.replace("/debug", "").strip()

    if not text:
        await message.reply("Usage: /debug <telegram_link>")
        return

    parsed = parse_telegram_link(text)
    if not parsed:
        await message.reply("❌ Invalid link format")
        return

    try:
        # Get message details
        if parsed["type"] in ["public_topic", "public"]:
            chat_id = parsed["channel"]
        else:
            chat_id = parsed["chat_id"]

        msg_id = parsed["message_id"]
        original_msg = await client.get_messages(chat_id, msg_id)

        if not original_msg:
            await message.reply("❌ Message not found")
            return

        debug_info = f"🔍 **Message Debug Info:**\n\n"
        debug_info += f"**Type:** {parsed['type']}\n"
        debug_info += f"**Chat ID:** {chat_id}\n"
        debug_info += f"**Message ID:** {msg_id}\n"
        if 'topic_id' in parsed and parsed['topic_id']:
            debug_info += f"**Topic ID:** {parsed['topic_id']}\n"
        debug_info += f"**Has Text:** {'Yes' if original_msg.text else 'No'}\n"
        debug_info += f"**Has Caption:** {'Yes' if original_msg.caption else 'No'}\n"
        debug_info += f"**Has Media:** {'Yes' if original_msg.media else 'No'}\n"
        debug_info += f"**Media Type:** {original_msg.media if original_msg.media else 'None'}\n"

        await message.reply(debug_info)

    except Exception as e:
        await message.reply(f"❌ Debug error: {str(e)}")

# --- পরিবর্তন এখানে ---
# কোডের শেষ থেকে if __name__ == "__main__": এবং app.run() ব্লকটি
# সম্পূর্ণ মুছে ফেলা হয়েছে।

