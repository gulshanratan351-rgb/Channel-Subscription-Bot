import os
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from pymongo import MongoClient
import datetime

# --- CONFIGURATION ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
UPI_ID = os.getenv("UPI_ID", "your-upi@id")
CONTACT_USERNAME = os.getenv("CONTACT_USERNAME", "admin_username")

bot = telebot.TeleBot(BOT_TOKEN)
client = MongoClient(MONGO_URI)
db = client['subscription_bot']
channels_col = db['channels']
users_col = db['users']

# --- ADMIN COMMANDS ---
@bot.message_count_handler(commands=['start'])
def start(message):
    bot.reply_to(message, "✅ Admin Panel Active!\n\n/add - Add/Edit Channel & Prices\n/channels - Manage Existing Channels")

@bot.message_handler(commands=['add'])
def add_channel(message):
    if message.from_user.id != ADMIN_ID:
        return
    msg = bot.send_message(message.chat.id, "Please ensure the bot is an Admin in your channel, then **FORWARD** any message from that channel here.")
    bot.register_next_step_handler(msg, get_channel_info)

def get_channel_info(message):
    if not message.forward_from_chat:
        bot.reply_to(message, "❌ Please FORWARD a message from the channel.")
        return
    
    ch_id = message.forward_from_chat.id
    ch_name = message.forward_from_chat.title
    
    msg = bot.send_message(message.chat.id, f"Channel Detected: **{ch_name}**\n\nEnter plans in format (Minutes:Price):\nExample: `1440:99, 43200:199` (1 Day and 30 Days)")
    bot.register_next_step_handler(msg, save_plans, ch_id, ch_name)

def save_plans(message, ch_id, ch_name):
    try:
        plans_raw = message.text.split(',')
        plans = {}
        for p in plans_raw:
            mins, price = p.strip().split(':')
            plans[mins] = price
        
        channels_col.update_one(
            {"channel_id": ch_id},
            {"$set": {"name": ch_name, "plans": plans}},
            upsert=True
        )
        bot.reply_to(message, f"✅ Setup Successful for **{ch_name}**!")
    except Exception as e:
        bot.reply_to(message, "❌ Invalid Format. Use `Min:Price, Min:Price`.")

# --- USER SIDE (PAYMENT FLOW) ---
@bot.callback_query_handler(func=lambda call: call.data.startswith('select_'))
def user_pays(call):
    try:
        _, ch_id, mins = call.data.split('_')
        ch_data = channels_col.find_one({"channel_id": int(ch_id)})
        price = ch_data['plans'][mins]
        
        qr_url = f"https://api.qrserver.com/v1/create-qr-code/?size=300x300&data=upi://pay?pa={UPI_ID}%26am={price}%26cu=INR"
        
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("✅ I Have Paid", callback_data=f"paid_{ch_id}_{mins}"))
        markup.add(InlineKeyboardButton("📞 Contact Admin", url=f"https://t.me/{CONTACT_USERNAME}"))
        
        bot.send_photo(
            call.message.chat.id, 
            qr_url,
            caption=f"Plan: {mins} Minutes\nPrice: ₹{price}\n\nUPI ID: `{UPI_ID}`\n\nPlease complete the payment and click 'I Have Paid'.",
            reply_markup=markup,
            parse_mode="Markdown"
        )
    except Exception as e:
        bot.answer_callback_query(call.id, "Error processing payment.")

# --- POLLING ---
if __name__ == "__main__":
    print("Bot is running...")
    bot.infinity_polling(timeout=10, long_polling_timeout=5)
    
        
