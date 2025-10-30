import os
import logging
import asyncio
from flask import Flask, request, Response
import threading

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

# --- মূল পরিবর্তন: একটি স্থায়ী Event Loop তৈরি করা ---

# একটি নতুন ইভেন্ট লুপ তৈরি করুন যা ব্যাকগ্রাউন্ড থ্রেডে চলবে
bot_loop = asyncio.new_event_loop()

async def main_startup():
    """অ্যাসিনক্রোনাসভাবে বট চালু করে এবং ওয়েববুক সেট করে"""
    logging.info("Starting Pyrogram client...")
    # app.start() কল করলে এটি বর্তমান (অর্থাৎ bot_loop) লুপের সাথে বাইন্ড হবে
    await app.start()
    logging.info(f"Setting webhook to {WEBHOOK_URL}...")
    await app.set_webhook(WEBHOOK_URL)
    logging.info("Webhook set successfully. Bot is ready.")

def start_bot_loop():
    """বটের ইভেন্ট লুপটি একটি আলাদা থ্রেডে চালান"""
    logging.info("Starting bot event loop thread...")
    asyncio.set_event_loop(bot_loop)
    try:
        # স্টার্টআপ টাস্ক চালান
        bot_loop.run_until_complete(main_startup())
        # লুপটি *চালু রাখুন* যাতে এটি ভবিষ্যতে টাস্ক গ্রহণ করতে পারে
        bot_loop.run_forever()
    except Exception as e:
        logging.critical(f"Bot startup/loop failed in thread: {e}")
        # যদি লুপটি ক্র্যাশ করে, তবে এটি এখানে লগ হবে
    finally:
        logging.info("Bot loop stopped. Closing...")
        bot_loop.close()

# Gunicorn যখন এই ফাইলটি লোড করবে, তখন এই থ্রেডটি শুরু হবে
# daemon=True সেট করা নিশ্চিত করে যে মূল প্রোগ্রামটি বন্ধ হলে থ্রেডটিও বন্ধ হবে
bot_thread = threading.Thread(target=start_bot_loop, daemon=True)
bot_thread.start()
# --------------------------------------------------

@server.route(f"/{BOT_TOKEN}", methods=["POST"])
def webhook_handler():
    """টেলিগ্রাম থেকে আসা সব আপডেট এখানে আসবে"""
    try:
        # Gunicorn-এর সিঙ্ক থ্রেড থেকে অ্যাসিনক্রোনাস কোড চালান
        # feed_update-কে রানিং bot_loop-এ সাবমিট করুন
        future = asyncio.run_coroutine_threadsafe(
            app.feed_update(request.get_json(force=True)),
            bot_loop
        )
        # টাস্কটি শেষ হওয়ার জন্য অপেক্ষা করুন (টাইমআউট সহ)
        future.result(timeout=10) 
    except Exception as e:
        # যদি future.result() টাইমআউট হয় বা feed_update-এ কোনো এরর হয়
        logging.error(f"Webhook handler error: {e}")
    
    # টেলিগ্রামকে জানাতে হবে যে আপডেট পেয়েছি, নাহলে এটি বারবার পাঠাতে থাকবে
    return Response(status=200)

@server.route("/")
def index():
    """সার্ভারটি যে চালু আছে তা পরীক্ষা করার জন্য (Health Check)"""
    return "Bot is running!"

# মূল `asyncio.run(main_startup())` লাইনটি সম্পূর্ণ মুছে ফেলা হয়েছে
# কারণ এটি এখন `start_bot_loop` থ্রেডের মধ্যে চলছে।

