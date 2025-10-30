import os
import logging
import uvicorn
import aiohttp
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response, PlainTextResponse
from starlette.routing import Route

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

async def startup():
    """সার্ভার চালু হওয়ার সময় এটি চলবে"""
    logging.info("Starting Pyrogram client...")
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
        logging.info("Bot is ready.")
        
    except Exception as e:
        logging.error(f"Webhook setup failed during startup: {e}")

async def shutdown():
    """সার্ভার বন্ধ হওয়ার সময় এটি চলবে"""
    logging.info("Stopping Pyrogram client...")
    await app.stop()

async def webhook_handler(request: Request):
    """
    টেলিগ্রাম থেকে আসা সব আপডেট এখানে আসবে
    (সঠিক মেথড 'process_update' ব্যবহার করে)
    """
    try:
        data = await request.json()
        await app.process_update(data)

    except AttributeError as e:
        # যদি কোনো কারণে Pyrogram v2 ইন্সটল না হয়, তবে এই এররটি লগ হবে
        logging.error("="*50)
        logging.error(f"CRITICAL: {e}")
        logging.error("Pyrogram version is still old! Check requirements.txt")
        logging.error("="*50)
    except Exception as e:
        logging.error(f"Webhook handler error: {e}")
    
    return Response(status_code=200)

async def health_check(request: Request):
    """Render-কে জানানোর জন্য যে সার্ভার চালু আছে"""
    return PlainTextResponse("Bot is running (Webhook Mode - Final Fix)!")

# রুট বা URL গুলো ডিফাইন করুন
routes = [
    Route("/", endpoint=health_check, methods=["GET"]),
    Route(f"/{BOT_TOKEN}", endpoint=webhook_handler, methods=["POST"])
]

# Starlette ASGI অ্যাপ্লিকেশন তৈরি করুন
server = Starlette(
    routes=routes,
    on_startup=[startup],
    on_shutdown=[shutdown]
)
