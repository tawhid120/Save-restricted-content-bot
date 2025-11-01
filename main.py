import logging
import os
import asyncio
from fastapi import FastAPI, Request, Response
from pyrogram import types
from bot import app  # Import the configured app from bot.py

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
log = logging.getLogger(__name__)

# Get environment variables from Render
# RENDER_EXTERNAL_URL is automatically set by Render
WEBHOOK_URL = os.environ.get("RENDER_EXTERNAL_URL")
BOT_TOKEN = os.environ.get("BOT_TOKEN")

# Basic validation
if not WEBHOOK_URL:
    log.error("RENDER_EXTERNAL_URL environment variable not set. Please ensure this is running on Render.")
    # We don't exit here, as Render might set it during startup
if not BOT_TOKEN:
    log.error("BOT_TOKEN environment variable not set.")
    # We don't exit here, to allow for Render's startup process

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
    2. Set the Telegram webhook to our server's URL.
    """
    log.info("Server is starting up...")
    if not WEBHOOK_URL or not BOT_TOKEN:
        log.error("Missing RENDER_EXTERNAL_URL or BOT_TOKEN. Webhook will not be set.")
        return
        
    await app.start()
    log.info("Pyrogram client started.")
    try:
        await app.set_webhook(FULL_WEBHOOK_URL)
        log.info(f"Webhook set successfully to {FULL_WEBHOOK_URL}")
    except Exception as e:
        log.error(f"Failed to set webhook: {e}")

@server.on_event("shutdown")
async def on_shutdown():
    """
    On server shutdown:
    1. Stop the Pyrogram client.
    """
    log.info("Server is shutting down...")
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
    """
    try:
        # Get the update data from the request body
        json_data = await request.json()
        
        # Manually construct the Update object
        # 'app.read_update' is the correct way to do this
        update = await app.read_update(json_data)
        
        # Process the update in a background task
        # This is crucial: it sends an immediate 200 OK response to Telegram
        # and prevents timeout issues, as Render's free plan can be slow.
        asyncio.create_task(app.process_update(update))
        
        # Return a 200 OK response to Telegram
        return Response(status_code=200)
        
    except Exception as e:
        log.error(f"Error processing update: {e}")
        # Return an error status, but still 200 to avoid Telegram resending
        return Response(status_code=200)

