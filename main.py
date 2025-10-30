import os
import logging
import asyncio
from flask import Flask, request, Response

# bot.py ফাইল থেকে app এবং BOT_TOKEN ইম্পোর্ট করুন
try:
    from bot import app, BOT_TOKEN
except ImportError:
    logging.critical("Could not import 'app' or 'BOT_TOKEN' from bot.py. Make sure bot.py exists.")
    exit(1)

logging.basicConfig(level=logging.INFO)

# Flask সার্ভার শুরু করুন
server = Flask(__name__)

# Render URL
RENDER_URL = os.environ.get("RENDER_URL")
if not RENDER_URL:
    logging.warning("RENDER_URL environment variable not set. Webhook setup will likely fail.")

WEBHOOK_URL = f"{RENDER_URL}/{BOT_TOKEN}"


@server.before_serving
async def startup():
    """
    এই ফাংশনটি সার্ভার চালু হওয়ার ঠিক আগে *একবার* চলবে।
    এটি Pyrogram ক্লায়েন্ট চালু করবে এবং ওয়েবহুক সেট করবে।
    """
    logging.info("Starting Pyrogram client...")
    await app.start()
    logging.info(f"Setting webhook to {WEBHOOK_URL}...")
    try:
        await app.set_webhook(WEBHOOK_URL)
        logging.info("Webhook set successfully. Bot is ready.")
    except Exception as e:
        logging.error(f"Failed to set webhook: {e}")


@server.route(f"/{BOT_TOKEN}", methods=["POST"])
async def webhook_handler():
    """
    টেলিগ্রাম থেকে আসা সব আপডেট এখানে আসবে।
    এটি এখন একটি async ফাংশন, তাই এটি সরাসরি await ব্যবহার করতে পারে।
    """
    try:
        # রিকোয়েস্ট থেকে JSON ডেটা নিন (এটি সিঙ্ক)
        update_data = request.get_json(force=True)
        # Pyrogram-কে আপডেট দিন (এটি অ্যাসিঙ্ক)
        await app.feed_update(update_data)
    except Exception as e:
        logging.error(f"Webhook handler error: {e}")
    
    # টেলিগ্রামকে জানাতে হবে যে আপডেট পেয়েছি
    return Response(status=200)


@server.route("/")
def index():
    """সার্ভারটি যে চালু আছে তা পরীক্ষা করার জন্য (Health Check)"""
    return "Bot is running (Async Mode)!"

