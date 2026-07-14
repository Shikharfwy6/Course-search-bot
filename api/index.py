import os
import asyncio
from flask import Flask, request, jsonify
from aiogram import Bot, Dispatcher, types, F
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Update
from motor.motor_asyncio import AsyncIOMotorClient

# Environment Variables
BOT_TOKEN = os.getenv("BOT_TOKEN")
MONGO_URL = os.getenv("MONGO_URL")
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "-1004436698454"))
VERCEL_URL = os.getenv("VERCEL_URL")  # e.g., course-search-bot.vercel.app

# Initialize Bot and Dispatcher
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# MongoDB Connection
db_client = AsyncIOMotorClient(MONGO_URL)
db = db_client["telegram_search_bot"]
posts_collection = db["posts"]

# Flask App Initialize
flask_app = Flask(__name__)


# --- 1. CHANNEL MONITORING (Save Posts) ---
@dp.channel_post()
async def handle_channel_post(message: types.Message):
    if message.chat.id != CHANNEL_ID:
        return

    caption = message.text or message.caption or ""
    if not caption:
        return

    post_data = {
        "message_id": message.message_id,
        "caption": caption,
        "chat_id": message.chat.id
    }

    await posts_collection.update_one(
        {"message_id": message.message_id},
        {"$set": post_data},
        upsert=True
    )


# --- 2. USER SEARCH (Keyword/Sentence) ---
@dp.message(F.chat.type == "private")
async def handle_user_search(message: types.Message):
    query = message.text
    if not query:
        return

    cursor = posts_collection.find({"caption": {"$regex": query, "$options": "i"}})
    results = await cursor.to_list(length=100)
    
    total_found = len(results)

    if total_found == 0:
        await message.reply("❌ Koi bhi post nahi mili. Kuch aur search karein.")
        return

    response_text = f"Total **({total_found})** found"
    callback_data = f"get_{query[:30]}"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📥 Get All Posts", callback_data=callback_data)]
    ])

    await message.reply(response_text, reply_markup=keyboard)


# --- 3. GET ALL POSTS BUTTON HANDLER ---
@dp.callback_query(F.data.startswith("get_"))
async def send_all_posts(callback_query: types.CallbackQuery):
    search_query = callback_query.data.split("_", 1)[1]
    user_id = callback_query.from_user.id

    await callback_query.answer("Sending posts... Please wait.")

    cursor = posts_collection.find({"caption": {"$regex": search_query, "$options": "i"}})
    results = await cursor.to_list(length=100)

    if not results:
        await bot.send_message(user_id, "❌ Error: Posts not found anymore.")
        return

    for post in results:
        try:
            await bot.forward_message(
                chat_id=user_id,
                from_chat_id=post["chat_id"],
                message_id=post["message_id"]
            )
            await asyncio.sleep(0.3)
        except Exception as e:
            print(f"Failed to forward: {e}")

    await bot.send_message(user_id, "✅ Saari posts upar bhej di gayi hain!")


# --- FLASK WEBHOOK ROUTING ---
@flask_app.route("/webhook", methods=["POST"])
def telegram_webhook():
    if request.headers.get("content-type") == "application/json":
        json_string = request.get_data().decode("utf-8")
        update = Update.model_validate_json(json_string, context={"bot": bot})
        
        # Async functions ko Flask ke sync route me run karne ke liye asyncio loop ka use karein
        asyncio.run(dp.feed_update(bot, update))
        return jsonify({"status": "ok"}), 200
    else:
        return jsonify({"error": "Unsupported Media Type"}), 415


@flask_app.route("/")
def index():
    return "Bot is running on Vercel with Flask!", 200


# Webhook check/setup helper (Aap ise browser me manually call kar sakte hain webhook set karne ke liye)
@flask_app.route("/set_webhook")
def setup_webhook():
    if VERCEL_URL:
        webhook_url = f"https://{VERCEL_URL}/webhook"
        asyncio.run(bot.set_webhook(url=webhook_url))
        return f"Webhook successfully set to: {webhook_url}", 200
    return "VERCEL_URL environment variable is missing!", 400
