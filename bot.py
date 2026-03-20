import os, telebot, re
from pymongo import MongoClient
from flask import Flask
from threading 
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
        
