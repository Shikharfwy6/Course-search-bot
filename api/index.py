import os
from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
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

# FastAPI App initialization without complex lifespan
app = FastAPI()

# Dynamic Database Connection Helper (Lazy Initialization)
def get_collection():
    # Har request par connection pool check karega, closed ya state-issue nahi aayega
    client = AsyncIOMotorClient(MONGO_URL)
    db = client["telegram_search_bot"]
    return db["posts"]


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

    posts_collection = get_collection()
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

    posts_collection = get_collection()
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

    posts_collection = get_collection()
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
        except Exception as e:
            print(f"Failed to forward: {e}")

    await bot.send_message(user_id, "✅ Saari posts upar bhej di gayi hain!")


# --- NATIVE ASYNCHRONOUS WEBHOOK ROUTE ---
@app.post("/webhook")
async def telegram_webhook(request: Request):
    try:
        update_data = await request.json()
        update = Update.model_validate(update_data, context={"bot": bot})
        await dp.feed_update(bot, update)
        return {"status": "ok"}
    except Exception as e:
        # Agar koi internal issue aaye toh exact error trace response me mil sake
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"error": str(e)})


@app.get("/")
async def index():
    return {"message": "Bot is running stably on Vercel!"}


# Webhook auto-setup helper route
@app.get("/set_webhook")
async def setup_webhook():
    if VERCEL_URL:
        webhook_url = f"https://{VERCEL_URL}/webhook"
        await bot.set_webhook(url=webhook_url)
        return {"message": f"Webhook successfully set to: {webhook_url}"}
    return {"error": "VERCEL_URL environment variable is missing!"}
