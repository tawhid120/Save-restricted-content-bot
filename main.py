import os
import logging
import asyncio
import threading
import aiohttp
from flask import Flask, request, Response

# bot.py ফাইল থেকে app এবং BOT_TOKEN ইম্পোর্ট করুন
try:
    from bot import app, BOT_TOKEN
except ImportError:
    logging.critical("Could not import 'app' or 'BOT_TOKEN' from bot.py.")
    exit(1)

logging.basicConfig(level=logging.INFO)

# Render URL
RENDER_URL = os.environ.get("RENDER_URL")
if not RENDER_URL:
    logging.warning("RENDER_URL environment variable not set.")

WEBHOOK_URL = f"{RENDER_URL}/{BOT_TOKEN}"

# --- Pyrogram-এর জন্য আলাদা থ্রেড এবং ইভেন্ট লুপ ---

# ১. Pyrogram-এর জন্য একটি নতুন ইভেন্ট লুপ তৈরি করুন
bot_loop = asyncio.new_event_loop()

async def main_startup():
    """বট চালু করে এবং ওয়েববুক সেট করে"""
    logging.info("Starting Pyrogram client in background thread...")
    await app.start()
    
    logging.info(f"Setting webhook to {WEBHOOK_URL}...")
    try:
        # ম্যানুয়ালি Webhook সেট করা
        async with aiohttp.ClientSession() as session:
            response = await session.get(
                f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook?url={WEBHOOK_URL}"
            )
            data = await response.json()
            if not data.get("ok"):
                logging.error(f"Failed to set webhook: {data}")
            else:
                logging.info("Webhook set successfully.")
        logging.info("Bot is ready (Threaded Mode).")
        
    except Exception as e:
        logging.error(f"Webhook setup failed during startup: {e}")

def start_bot_loop():
    """এই ফাংশনটি আলাদা থ্রেডে চলবে"""
    logging.info("Bot event loop thread started.")
    asyncio.set_event_loop(bot_loop)
    try:
        # বট চালু করুন এবং লুপটি চিরতরে চালান
        bot_loop.run_until_complete(main_startup())
        bot_loop.run_forever()
    except Exception as e:
        logging.critical(f"Bot loop crashed: {e}")
    finally:
        bot_loop.close()
        logging.info("Bot loop closed.")

# ২. থ্রেডটি চালু করুন
# daemon=True দিলে মূল প্রোগ্রাম বন্ধ হলে থ্রেডটিও বন্ধ হয়ে যাবে
bot_thread = threading.Thread(target=start_bot_loop, daemon=True)
bot_thread.start()

# --- Flask সার্ভার (এটি মূল থ্রেডে চলবে) ---

server = Flask(__name__)

@server.route(f"/{BOT_TOKEN}", methods=["POST"])
def webhook_handler():
    """
    টেলিগ্রাম থেকে আসা সব আপডেট এখানে আসবে (সিঙ্ক্রোনাস)
    """
    try:
        # ১. Flask থেকে JSON ডেটা নিন
        data = request.get_json(force=True)

        async def process_in_bot_loop():
            """
            এই coroutine-টি ব্যাকগ্রাউন্ড থ্রেডের লুপে চলবে
            """
            try:
                # ২. সঠিক মেথডটি কল করুন
                await app.dispatcher.feed_raw_update(data)
            except Exception as e:
                logging.error(f"Error feeding update to dispatcher: {e}")

        # ৩. টাস্কটিকে Flask (সিঙ্ক) থ্রেড থেকে Pyrogram (অ্যাসিঙ্ক) থ্রেডে পাঠান
        asyncio.run_coroutine_threadsafe(process_in_bot_loop(), bot_loop)

    except Exception as e:
        logging.error(f"Webhook handler (Flask) error: {e}")
    
    return Response(status_code=200)

@server.route("/")
def health_check():
    """Render-কে জানানোর জন্য যে সার্ভার চালু আছে"""
    return "Bot is running (Flask + Threading Model)"
