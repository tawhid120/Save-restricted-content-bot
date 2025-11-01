import logging
import os
import asyncio
import aiohttp
from fastapi import FastAPI, Request, Response
from pyrogram import types
from bot import app, BOT_TOKEN  # Import app and BOT_TOKEN from bot.py

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
log = logging.getLogger(__name__)

# --- Environment Variables ---
# RENDER_EXTERNAL_URL is automatically set by Render
WEBHOOK_URL = os.environ.get("RENDER_EXTERNAL_URL")
# BOT_TOKEN is imported from bot.py, which gets it from os.environ

# Basic validation
if not WEBHOOK_URL:
    log.error("RENDER_EXTERNAL_URL environment variable not set. Assuming local test.")
    # For local testing, you might use a tool like ngrok and set this manually
    # WEBHOOK_URL = "https://your-ngrok-url.ngrok.io" 

if not BOT_TOKEN:
    log.critical("BOT_TOKEN environment variable not set. Bot cannot start.")

# Define a secure webhook path
WEBHOOK_PATH = f"/webhook/{BOT_TOKEN}"
# The full URL for Telegram
FULL_WEBHOOK_URL = f"{WEBHOOK_URL}{WEBHOOK_PATH}"

# Initialize the FastAPI server
server = FastAPI(docs_url=None, redoc_url=None)

@server.on_event("startup")
async def on_startup():
    """
    On server startup:
    1. Start the Pyrogram client.
    2. Manually set the Telegram webhook using an HTTP request.
    """
    if not BOT_TOKEN or not WEBHOOK_URL:
        log.error("Missing BOT_TOKEN or RENDER_EXTERNAL_URL. Cannot set webhook.")
        return
        
    log.info("Starting Pyrogram client...")
    await app.start()
    log.info("Pyrogram client started.")
    
    # --- THIS IS THE FIX ---
    # Manually set the webhook using aiohttp
    log.info(f"Setting webhook to {FULL_WEBHOOK_URL}...")
    try:
        async with aiohttp.ClientSession() as session:
            api_url = f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook?url={FULL_WEBHOOK_URL}"
            async with session.get(api_url) as resp:
                response_json = await resp.json()
                if resp.status == 200 and response_json.get("ok"):
                    log.info("Webhook set successfully.")
                else:
                    log.error(f"Failed to set webhook: {response_json.get('description', 'Unknown error')}")
    except Exception as e:
        log.error(f"Error setting webhook: {e}")
    # --- END OF FIX ---

@server.on_event("shutdown")
async def on_shutdown():
    """
    On server shutdown:
    1. Stop the Pyrogram client.
    """
    log.info("Server is shutting down...")
    if app.is_connected:
        await app.stop()
    log.info("Pyrogram client stopped.")

@server.get("/")
async def health_check():
    """
    A simple health check endpoint that Render can ping.
    """
    return {"status": "ok"}

@server.post(WEBHOOK_PATH)
async def webhook_listener(request: Request):
    """
    This endpoint receives the webhook updates from Telegram.
    This logic is for Pyrogram v2+ and is correct.
    """
    try:
        # Get the update data from the request body
        json_data = await request.json()
        
        # 1. Convert the raw JSON dict into a Pyrogram Update object
        update = await app.read_update(json_data)
        
        # 2. Process the Update object
        # We run this in a background task to immediately send a 200 OK
        # This prevents Telegram from resending the update.
        asyncio.create_task(app.process_update(update))
        
        # Return a 200 OK response to Telegram
        return Response(status_code=200)
        
    except Exception as e:
        log.error(f"Error processing update: {e}")
        return Response(status_code=500)


