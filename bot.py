import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ForceReply
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
import sqlite3
from datetime import datetime
import os

# Token dari BotFather
TOKEN = "8209398360:AAFu4ycsJNsmfuxLZkuWJRj9H5QHg9KkwdU"  # Ganti dengan token kau

DB_NAME = "monorich.db"

# Commission
SPONSOR_BONUS = 2.00
SPILLOVER_LEVEL_1_5 = 1.00
SPILLOVER_LEVEL_6_10 = 0.50
SPILLOVER_CAP = 10
REENTRY_REQUIRED_DEPTH = 10
REENTRY_COST = 10.00

# Admin Telegram ID (kau kena tahu ID Telegram kau – guna @userinfobot)
ADMIN_TELEGRAM_ID = Malsyam  # Ganti dengan ID Telegram kau

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

def get_db_connection():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER UNIQUE,
            username TEXT,
            referral_code TEXT UNIQUE,
            referrer_id INTEGER,
            position INTEGER UNIQUE,
            balance REAL DEFAULT 0.0,
            join_date TEXT
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            type TEXT,
            amount REAL,
            description TEXT,
            timestamp TEXT
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS withdraw_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            amount REAL,
            bank_name TEXT,
            account_name TEXT,
            account_number TEXT,
            status TEXT DEFAULT 'pending',
            request_date TEXT
        )
    ''')
    conn.commit()
    conn.close()

def get_next_position():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT MAX(position) FROM users")
    row = c.fetchone()
    max_pos = row[0] if row[0] else 0
    conn.close()
    return max_pos + 1

def generate_referral_code(username):
    return f"{username.upper()}{hash(username) % 10000:04d}"

def get_user_by_telegram_id(telegram_id):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,))
    user = c.fetchone()
    conn.close()
    return user

def process_bonus(new_user_id, referrer_id, new_position):
    conn = get_db_connection()
    c = conn.cursor()

    if referrer_id:
        c.execute("UPDATE users SET balance = balance + ? WHERE id = ?", (SPONSOR_BONUS, referrer_id))
        c.execute('''
            INSERT INTO transactions (user_id, type, amount, description, timestamp)
            VALUES (?, 'sponsor', ?, 'Sponsor Bonus', ?)
        ''', (referrer_id, SPONSOR_BONUS, datetime.now().isoformat()))

    # Spillover logic (simple version for bot)
    c.execute("SELECT id FROM users WHERE position < ? ORDER BY position DESC LIMIT ?", (new_position, SPILLOVER_CAP))
    uplines = c.fetchall()
    for level, row in enumerate(uplines, 1):
        bonus = SPILLOVER_LEVEL_1_5 if level <= 5 else SPILLOVER_LEVEL_6_10 if level <= 10 else 0.0
        if bonus > 0:
            c.execute("UPDATE users SET balance = balance + ? WHERE id = ?", (bonus, row['id']))
            c.execute('''
                INSERT INTO transactions (user_id, type, amount, description, timestamp)
                VALUES (?, 'spillover', ?, ?, ?)
            ''', (row['id'], bonus, f"Spillover Level {level}", datetime.now().isoformat()))

    conn.commit()
    conn.close()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db_user = get_user_by_telegram_id(user.id)
    
    if not db_user:
        # Register new user
        conn = get_db_connection()
        c = conn.cursor()
        referrer_id = None
        # Simple first user as admin
        position = get_next_position()
        ref_code = generate_referral_code(user.username or "user")
        c.execute('''
            INSERT INTO users (telegram_id, username, referral_code, referrer_id, position, join_date)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (user.id, user.username or "user", ref_code, referrer_id, position, datetime.now().isoformat()))
        conn.commit()
        conn.close()
        
        await update.message.reply_html(
            f"Selamat datang <b>{user.first_name}</b>!\n"
            "Akaun kau berjaya didaftar di MonoRich Bot 🔥\n\n"
            "/dashboard - Tengok balance & downline\n"
            "/reentry - Re-entry kalau cukup condition\n"
            "/withdraw - Withdraw balance\n"
            "/referral - Link referral kau\n"
            "/leg - Lihat single leg\n"
            "/history - Transaction history"
        )
    else:
        keyboard = [
            [InlineKeyboardButton("📊 Dashboard", callback_data="dashboard")],
            [InlineKeyboardButton("🚀 Re-entry", callback_data="reentry"), InlineKeyboardButton("💰 Withdraw", callback_data="withdraw")],
            [InlineKeyboardButton("🔗 Referral", callback_data="referral"), InlineKeyboardButton("📜 Leg", callback_data="leg")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(f"Welcome back <b>{user.first_name}</b>! 🔥", reply_markup=reply_markup, parse_mode='HTML')

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "dashboard":
        user = get_user_by_telegram_id(query.from_user.id)
        if user:
            conn = get_db_connection()
            c = conn.cursor()
            c.execute("SELECT MAX(position) FROM users")
            max_pos = c.fetchone()[0] or 0
            depth = max_pos - user['position']
            c.execute("SELECT COUNT(*) FROM users WHERE referrer_id = ?", (user['id'],))
            direct = c.fetchone()[0]
            conn.close()
            
            text = f"📊 <b>Dashboard Kau</b>\n\n"
            text += f"Position: #{user['position']}\n"
            text += f"Balance: RM{user['balance']:.2f}\n"
            text += f"Downline: {depth} / 10\n"
            text += f"Direct Sponsor: {direct}\n\n"
            if depth >= 10 and user['balance'] >= 10:
                text += "✅ Kau layak Re-entry!\nKlik /reentry"
            await query.edit_message_text(text, parse_mode='HTML')

    # Tambah handler lain untuk reentry, withdraw, dll (aku bagi full nanti kalau kau confirm)

async def main():
    init_db()
    application = Application.builder().token(TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button))
    
    await application.run_polling()

if __name__ == '__main__':
    import asyncio

    asyncio.run(main())

