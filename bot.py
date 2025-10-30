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

# Render আপনাকে একটি URL দেবে, এটি Environment Variable-এ সেট করতে হবে
RENDER_URL = os.environ.get("RENDER_URL")
if not RENDER_URL:
    logging.warning("RENDER_URL environment variable not set. Webhook setup will likely fail.")

# ওয়েববুক URL সেট করুন
WEBHOOK_URL = f"{RENDER_URL}/{BOT_TOKEN}"

# --- মূল অংশ: বট চালু করা এবং ওয়েববুক সেট করা ---
async def main_startup():
    """অ্যাসিনক্রোনাসভাবে বট চালু করে এবং ওয়েববুক সেট করে"""
    try:
        logging.info("Starting Pyrogram client...")
        await app.start()
        logging.info(f"Setting webhook to {WEBHOOK_URL}...")
        await app.set_webhook(WEBHOOK_URL)
        logging.info("Webhook set successfully.")
    except Exception as e:
        logging.critical(f"Bot startup failed: {e}")

# Render যখন এই ফাইলটি লোড করবে, তখন এটি স্বয়ংক্রিয়ভাবে চালু হবে
# এটি Gunicorn-এর সাথে কাজ করার জন্য সঠিক উপায়
asyncio.run(main_startup())
# --------------------------------------------------

@server.route(f"/{BOT_TOKEN}", methods=["POST"])
def webhook_handler():
    """টেলিগ্রাম থেকে আসা সব আপডেট এখানে আসবে"""
    try:
        # Pyrogram-কে gelen update-টি দিন
        # Pyrogram v2+ এর জন্য, feed_update একটি async ফাংশন
        asyncio.run(app.feed_update(request.get_json(force=True)))
    except Exception as e:
        logging.error(f"Webhook error: {e}")
    return Response(status=200) # টেলিগ্রামকে জানাতে হবে যে আপডেট পেয়েছি

@server.route("/")
def index():
    """সার্ভারটি যে চালু আছে তা পরীক্ষা করার জন্য (Health Check)"""
    return "Bot is running!"

