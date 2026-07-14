import os
import re
from flask import Flask, request, jsonify
import requests
from pymongo import MongoClient

app = Flask(__name__)

# Environment Variables (Vercel Dashboard me add karein)
BOT_TOKEN = os.environ.get("BOT_TOKEN")
MONGO_URI = os.environ.get("MONGO_URI")
CHANNEL_ID = int(os.environ.get("CHANNEL_ID")) # E.g., -1004436698454

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

# MongoDB Setup
client = MongoClient(MONGO_URI)
db = client['telegram_bot_db']
posts_collection = db['posts']

@app.route('/', methods=['GET'])
def home():
    return "Bot is running 24/7 on Vercel!"

@app.route('/webhook', methods=['POST'])
def webhook():
    update = request.get_json()
    
    if not update:
        return jsonify({"status": "error", "message": "No payload"}), 400

    # 1. Channel ki nayi post ko save karna
    if "channel_post" in update:
        post = update["channel_post"]
        chat_id = post["chat"]["id"]
        
        # Check agar post usi target channel se hai
        if chat_id == CHANNEL_ID:
            message_id = post["message_id"]
            caption = post.get("caption") or post.get("text") or ""
            
            # Telegram Private Channel Link Format: https://telegram.me/c/CHANNEL_ID_WITHOUT_100/MESSAGE_ID
            clean_channel_id = str(CHANNEL_ID).replace("-100", "")
            post_link = f"https://telegram.me/c/{clean_channel_id}/{message_id}"
            
            # MongoDB me insert ya update karein
            posts_collection.update_one(
                {"message_id": message_id},
                {"$set": {"caption": caption, "link": post_link}},
                upsert=True
            )
            return jsonify({"status": "success", "message": "Post saved"}), 200

    # 2. User ka Bot par message handle karna (Search Functionality)
    elif "message" in update:
        message = update["message"]
        chat_id = message["chat"]["id"]
        user_text = message.get("text", "").strip()
        
        # Agar user inline button par click karta hai (Callback Query)
        # Note: Callback queries niche alag se handled hain, ye normal text search ke liye hai.
        if user_text:
            if user_text.startswith('/start'):
                send_message(chat_id, "Welcome! Kuch bhi keyword bhejein post search karne ke liye.")
                return jsonify({"status": "ok"}), 200
            
            # MongoDB me case-insensitive regex search
            query = {"caption": {"$regex": re.escape(user_text), "$options": "i"}}
            results_count = posts_collection.count_documents(query)
            
            if results_count > 0:
                # Reply message text aur inline button
                reply_text = f"Total {results_count} found"
                reply_markup = {
                    "inline_keyboard": [[
                        {"text": "🎁 Get All Post", "callback_data": f"get_all:{user_text}"}
                    ]]
                }
                send_message(chat_id, reply_text, reply_markup)
            else:
                send_message(chat_id, "Sorry, koi post nahi mili!")

    # 3. Inline Button (Callback Query) Handle karna
    elif "callback_query" in update:
        callback = update["callback_query"]
        chat_id = callback["message"]["chat"]["id"]
        callback_data = callback["data"]
        
        if callback_data.startswith("get_all:"):
            search_keyword = callback_data.split(":", 1)[1]
            
            query = {"caption": {"$regex": re.escape(search_keyword), "$options": "i"}}
            posts = posts_collection.find(query)
            
            # Saari posts ke links user ko bhejna
            response_text = f"📚 Here are the posts for '{search_keyword}':\n\n"
            for index, post in enumerate(posts, 1):
                caption_snippet = post['caption'][:30] + "..." if len(post['caption']) > 30 else post['caption']
                response_text += f"{index}. {caption_snippet}\n🔗 {post['link']}\n\n"
                
                # Agar text bada ho jaye to break karke bhej sakte hain (Telegram limit 4096 chars)
                if len(response_text) > 3500:
                    send_message(chat_id, response_text)
                    response_text = ""
            
            if response_text:
                send_message(chat_id, response_text)
                
            # Telegram ko acknowledge karna ki callback process ho gaya
            requests.post(f"{TELEGRAM_API}/answerCallbackQuery", json={"callback_query_id": callback["id"]})

    return jsonify({"status": "ok"}), 200

def send_message(chat_id, text, reply_markup=None):
    url = f"{TELEGRAM_API}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    requests.post(url, json=payload)

# Vercel requirements ke liye app export
app = app
