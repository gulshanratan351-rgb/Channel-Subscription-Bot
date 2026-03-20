import os, telebot, re
from pymongo import MongoClient
from flask import Flask
from threading import Thread
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

# --- Render Port Binding ---
app = Flask('')
@app.route('/')
def home(): return "Bot is Running!"
def run(): app.run(host='0.0.0.0', port=8080)
def keep_alive(): Thread(target=run).start()

# --- Config ---
TOKEN = os.getenv("BOT_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

bot = telebot.TeleBot(TOKEN)

# MongoDB Connection with Timeout
try:
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    db = client['subscription_bot']
    client.server_info() # Check connection
except Exception as e:
    print(f"MongoDB Error: {e}")

# --- Commands ---

@bot.message_handler(commands=['start', 'help'])
def start_help(message):
    if message.from_user.id == ADMIN_ID:
        bot.reply_to(message, "✅ **Admin Panel**\n\n/add - Setup Channel\n/channels - List All\n/help - Instructions")
    else:
        bot.reply_to(message, "Welcome! Payment karke **Screenshot** bhejiye.")

@bot.message_handler(commands=['add'])
def add_cmd(message):
    if message.from_user.id != ADMIN_ID: return
    msg = bot.reply_to(message, "Apne channel se koi bhi message **FORWARD** karke yahan bhejein.")
    bot.register_next_step_handler(msg, process_channel)

def process_channel(message):
    if message.forward_from_chat:
        cid, cname = message.forward_from_chat.id, message.forward_from_chat.title
        msg = bot.reply_to(message, f"Channel: {cname}\n\nPlans likhein (Example: `1440:30, 43200:199`)")
        bot.register_next_step_handler(msg, save_plans, cid, cname)
    else:
        bot.reply_to(message, "❌ Error: Forward nahi kiya. Phir se `/add` karein.")

def save_plans(message, cid, cname):
    plans = {m[0]: m[1] for m in re.findall(r'(\d+)\s*[:]\s*(\d+)', message.text)}
    if plans:
        db.channels.update_one({'cid': cid}, {'$set': {'name': cname, 'plans': plans}}, upsert=True)
        bot_user = bot.get_me().username
        link = f"https://t.me/{bot_user}?start=sub_{abs(cid)}"
        bot.send_message(message.chat.id, f"✅ **Setup Success!**\n\nShare this link:\n`{link}`", parse_mode="Markdown")
    else:
        bot.reply_to(message, "❌ Plans ka format galat hai.")

@bot.message_handler(commands=['channels'])
def list_ch(message):
    if message.from_user.id != ADMIN_ID: return
    try:
        chs = list(db.channels.find())
        if not chs:
            bot.reply_to(message, "Abhi koi channel add nahi hai.")
            return
        res = "📁 **Your Channels:**\n\n"
        for c in chs:
            res += f"🔹 {c.get('name')} (ID: `{c.get('cid')}`)\n"
        bot.send_message(message.chat.id, res, parse_mode="Markdown")
    except Exception as e:
        bot.reply_to(message, f"❌ DB Error: {e}")

# --- Screenshot Handling ---
@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    if message.from_user.id == ADMIN_ID: return
    
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("✅ Approve", callback_data=f"ap_{message.from_user.id}"),
               InlineKeyboardButton("❌ Reject", callback_data=f"rj_{message.from_user.id}"))
    
    bot.send_photo(ADMIN_ID, message.photo[-1].file_id, 
                   caption=f"📩 Payment from: {message.from_user.first_name}\nID: `{message.from_user.id}`", 
                   reply_markup=markup)
    bot.reply_to(message, "⏳ Screenshot Admin ko bhej diya gaya hai.")

@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    action, uid = call.data.split("_")
    uid = int(uid)
    
    if action == "ap":
        bot.send_message(uid, "✅ **Payment Approved!**\nWelcome to the VIP channel.")
        bot.answer_callback_query(call.id, "Approved!")
    else:
        bot.send_message(uid, "❌ **Payment Rejected!**")
        bot.answer_callback_query(call.id, "Rejected!")

if __name__ == "__main__":
    keep_alive()
    bot.infinity_polling(timeout=20, long_polling_timeout=5)
    
