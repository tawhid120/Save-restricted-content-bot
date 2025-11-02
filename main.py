import logging
import os
import asyncio
import aiohttp
from fastapi import FastAPI, Request, Response
from pyrogram import types  # এটি থাকা খুবই গুরুত্বপূর্ণ

# Import app and BOT_TOKEN from your new bot.py file
try:
    from bot import app, BOT_TOKEN
except ImportError:
    print("CRITICAL: Could not import 'app' or 'BOT_TOKEN' from bot.py.")
    print("Ensure bot.py exists and is not failing on import.")
    app = None
    BOT_TOKEN = None

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
log = logging.getLogger(__name__)

# --- Environment Variables ---
WEBHOOK_URL = os.environ.get("RENDER_EXTERNAL_URL")
if not BOT_TOKEN:
    log.critical("BOT_TOKEN not loaded from bot.py. Bot cannot start.")
if not WEBHOOK_URL:
    log.warning("RENDER_EXTERNAL_URL not set. Webhook setup will fail unless run locally.")
    
# Define a secure webhook path
WEBHOOK_PATH = f"/webhook/{BOT_TOKEN}" if BOT_TOKEN else "/webhook"
FULL_WEBHOOK_URL = f"{WEBHOOK_URL}{WEBHOOK_PATH}" if WEBHOOK_URL and BOT_TOKEN else None

# --- Lazy App Startup ---
app_is_running = False

# Initialize the FastAPI server
server = FastAPI(docs_url=None, redoc_url=None)

@server.on_event("shutdown")
async def on_shutdown():
    """On server shutdown: stop the Pyrogram client if it was started."""
    global app_is_running
    if app and app_is_running and app.is_connected:
        log.info("Server is shutting down, stopping Pyrogram client...")
        await app.stop()
        log.info("Pyrogram client stopped.")
        app_is_running = False

# === সমাধান ১: UptimeRobot (TypeError এবং 405 Method Not Allowed) ===
# .get() এর বদলে .api_route() ব্যবহার করা হয়েছে, যা GET এবং HEAD উভয়ই সাপোর্ট করে।
@server.api_route("/", methods=["GET", "HEAD"])
async def health_check():
    """
    A simple health check endpoint that Render/UptimeRobot can ping.
    Handles both GET and HEAD requests.
    """
    # === সমাধান ৩: NameError (app_is_running is not defined) ===
    # ফাংশনকে বলে দেওয়া হলো যে 'app_is_running' একটি গ্লোবাল ভেরিয়েবল।
    global app_is_running
    
    log.info("Health check ping received.")
    return {"status": "ok", "app_running": app_is_running}

@server.post(WEBHOOK_PATH)
async def webhook_listener(request: Request):
    """This endpoint receives the webhook updates from Telegram."""
    global app_is_running
    
    if not app or not BOT_TOKEN:
        log.error("Webhook received but bot is not initialized. Check bot.py for errors.")
        return Response(status_code=500)
        
    try:
        # --- LAZY STARTUP ---
        if not app_is_running:
            log.info("First request received, starting Pyrogram client...")
            await app.start()
            app_is_running = True
            log.info("Pyrogram client started.")

        # Get the update data from the request body
        json_data = await request.json()
        
        # === সমাধান ২: মেসেজ প্রসেসিং (AttributeError) ===
        # raw dictionary (json_data) থেকে Pyrogram Update অবজেক্ট তৈরির সঠিক উপায়।
        update = types.Update.from_dict(json_data)
        
        # Process the Update object in a background task
        asyncio.create_task(app.process_update(update))
        
        # --- ALWAYS RETURN 200 OK ---
        return Response(status_code=200)
        
    except Exception as e:
        log.error(f"Error in webhook_listener: {e}")
        return Response(status_code=200)

@server.get(f"/setup/{BOT_TOKEN}")
async def setup_webhook():
    """
    A one-time endpoint to set the webhook.
    Visit this URL in your browser once after deploying:
    https://your-app-name.onrender.com/setup/YOUR_BOT_TOKEN
    """
    if not FULL_WEBHOOK_URL:
        return {"ok": False, "error": "RENDER_EXTERNAL_URL is not set or BOT_TOKEN is missing. Cannot set webhook."}

    global app_is_running
    try:
        if not app_is_running:
            log.info("Setting up webhook, starting client...")
            await app.start()
            app_is_running = True

        log.info(f"Setting webhook to {FULL_WEBHOOK_URL}...")
        api_url = f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook?url={FULL_WEBHOOK_URL}"
        
        async with aiohttp.ClientSession() as session:
            async with session.get(api_url) as resp:
                response_json = await resp.json()
                if resp.status == 200 and response_json.get("ok"):
                    log.info("Webhook set successfully.")
                    return {"ok": True, "message": "Webhook set successfully!"}
                else:
                    log.error(f"Failed to set webhook: {response_json.get('description', 'Unknown error')}")
                    return {"ok": False, "error": response_json.get('description', 'Unknown error')}
    except Exception as e:
        log.error(f"Error setting webhook: {e}")
        return {"ok": False, "error": str(e)}

