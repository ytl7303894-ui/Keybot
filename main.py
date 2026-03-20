# main.py
import os
import json
import logging
import sqlite3
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
import config

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Bot Configuration
BOT_TOKEN = config.BOT_TOKEN
BOT_ID = config.BOT_ID

# Price configuration
PRICES = {
    '1_day': 120,
    '3_days': 199,
    '7_days': 349,
    '30_days': 850,
    'season': 1150
}

DURATIONS = {
    '1_day': 1,
    '3_days': 3,
    '7_days': 7,
    '30_days': 30,
    'season': 90
}

# Database setup
def init_database():
    conn = sqlite3.connect('bot_database.db')
    c = conn.cursor()
    
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (user_id INTEGER PRIMARY KEY,
                  username TEXT,
                  first_name TEXT,
                  join_date TEXT,
                  is_admin INTEGER DEFAULT 0,
                  is_owner INTEGER DEFAULT 0)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS keys
                 (key_text TEXT PRIMARY KEY,
                  user_id INTEGER,
                  duration_days INTEGER,
                  created_at TEXT,
                  expires_at TEXT,
                  is_used INTEGER DEFAULT 0,
                  used_by INTEGER,
                  used_at TEXT)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS transactions
                 (txn_id TEXT PRIMARY KEY,
                  user_id INTEGER,
                  amount INTEGER,
                  duration_days INTEGER,
                  status TEXT,
                  created_at TEXT,
                  order_id TEXT)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS bot_settings
                 (setting_key TEXT PRIMARY KEY,
                  setting_value TEXT)''')
    
    # Insert default settings
    c.execute("INSERT OR IGNORE INTO bot_settings (setting_key, setting_value) VALUES (?, ?)",
              ('bot_name', 'ONLINE KEY BOT'))
    c.execute("INSERT OR IGNORE INTO bot_settings (setting_key, setting_value) VALUES (?, ?)",
              ('welcome_message', 'Welcome to License Key Bot'))
    c.execute("INSERT OR IGNORE INTO bot_settings (setting_key, setting_value) VALUES (?, ?)",
              ('payment_details', 'UPI: example@upi\nScan QR code and send screenshot'))
    c.execute("INSERT OR IGNORE INTO bot_settings (setting_key, setting_value) VALUES (?, ?)",
              ('admin_ids', '[]'))
    c.execute("INSERT OR IGNORE INTO bot_settings (setting_key, setting_value) VALUES (?, ?)",
              ('owner_id', config.DEFAULT_OWNER_ID))
    
    conn.commit()
    conn.close()

def get_bot_setting(setting_key):
    conn = sqlite3.connect('bot_database.db')
    c = conn.cursor()
    c.execute("SELECT setting_value FROM bot_settings WHERE setting_key = ?", (setting_key,))
    result = c.fetchone()
    conn.close()
    return result[0] if result else None

def update_bot_setting(setting_key, setting_value):
    conn = sqlite3.connect('bot_database.db')
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO bot_settings (setting_key, setting_value) VALUES (?, ?)",
              (setting_key, setting_value))
    conn.commit()
    conn.close()

def is_admin(user_id):
    admin_ids = json.loads(get_bot_setting('admin_ids') or '[]')
    owner_id = get_bot_setting('owner_id')
    return str(user_id) in admin_ids or str(user_id) == owner_id

def is_owner(user_id):
    owner_id = get_bot_setting('owner_id')
    return str(user_id) == owner_id

def add_user(user_id, username, first_name):
    conn = sqlite3.connect('bot_database.db')
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO users (user_id, username, first_name, join_date) VALUES (?, ?, ?, ?)",
              (user_id, username, first_name, datetime.now().isoformat()))
    conn.commit()
    conn.close()

def generate_key(duration_days):
    import uuid
    import hashlib
    key = hashlib.md5(f"{uuid.uuid4()}{datetime.now()}".encode()).hexdigest()[:16].upper()
    return f"{key[:4]}-{key[4:8]}-{key[8:12]}-{key[12:]}"

def save_key(key, duration_days, created_by):
    conn = sqlite3.connect('bot_database.db')
    c = conn.cursor()
    expires_at = datetime.now() + timedelta(days=duration_days)
    c.execute("INSERT INTO keys (key_text, user_id, duration_days, created_at, expires_at) VALUES (?, ?, ?, ?, ?)",
              (key, created_by, duration_days, datetime.now().isoformat(), expires_at.isoformat()))
    conn.commit()
    conn.close()
    return key

def verify_key(key_text):
    conn = sqlite3.connect('bot_database.db')
    c = conn.cursor()
    c.execute("SELECT key_text, duration_days, expires_at, is_used FROM keys WHERE key_text = ?", (key_text,))
    key_data = c.fetchone()
    conn.close()
    
    if not key_data:
        return False, "Invalid key"
    
    key_text, duration_days, expires_at, is_used = key_data
    
    if is_used:
        return False, "Key already used"
    
    expires_at_date = datetime.fromisoformat(expires_at)
    if expires_at_date < datetime.now():
        return False, "Key expired"
    
    return True, key_text

def use_key(key_text, user_id):
    conn = sqlite3.connect('bot_database.db')
    c = conn.cursor()
    c.execute("UPDATE keys SET is_used = 1, used_by = ?, used_at = ? WHERE key_text = ?",
              (user_id, datetime.now().isoformat(), key_text))
    conn.commit()
    conn.close()

def save_transaction(txn_id, user_id, amount, duration_days, status, order_id):
    conn = sqlite3.connect('bot_database.db')
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO transactions (txn_id, user_id, amount, duration_days, status, created_at, order_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
              (txn_id, user_id, amount, duration_days, status, datetime.now().isoformat(), order_id))
    conn.commit()
    conn.close()

# Bot command handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    add_user(user.id, user.username, user.first_name)
    
    welcome_msg = get_bot_setting('welcome_message')
    bot_name = get_bot_setting('bot_name')
    
    keyboard = [
        [InlineKeyboardButton("💰 Generate Key (Paid)", callback_data="generate_key")],
        [InlineKeyboardButton("🔑 Reset Key", callback_data="reset_key")],
        [InlineKeyboardButton("ℹ️ About", callback_data="about")]
    ]
    
    if is_admin(user.id):
        keyboard.append([InlineKeyboardButton("⚙️ Admin Panel", callback_data="admin_panel")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"🌟 *{bot_name}* 🌟\n\n{welcome_msg}\n\nSelect an option:",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user = update.effective_user
    
    if query.data == "about":
        keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="back_to_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            f"🤖 *Bot Information*\n\n"
            f"Bot ID: `{BOT_ID}`\n"
            f"Version: 2.0\n"
            f"Developer: @{config.DEVELOPER_USERNAME}\n\n"
            f"*Features:*\n"
            f"• Generate license keys\n"
            f"• Reset/activate keys\n"
            f"• 24/7 support\n"
            f"• Secure transactions",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    
    elif query.data == "generate_key":
        keyboard = [
            [InlineKeyboardButton("1 Day - ₹120", callback_data="buy_1_day")],
            [InlineKeyboardButton("3 Days - ₹199", callback_data="buy_3_days")],
            [InlineKeyboardButton("7 Days - ₹349", callback_data="buy_7_days")],
            [InlineKeyboardButton("30 Days - ₹850", callback_data="buy_30_days")],
            [InlineKeyboardButton("Season - ₹1150", callback_data="buy_season")],
            [InlineKeyboardButton("🔙 Back", callback_data="back_to_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            "📦 *Select key duration:*\n\n💰 *Prices:*\n• 1 Day - ₹120\n• 3 Days - ₹199\n• 7 Days - ₹349\n• 30 Days - ₹850\n• Season - ₹1150",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    
    elif query.data.startswith("buy_"):
        duration_key = query.data.replace("buy_", "")
        duration_days = DURATIONS[duration_key]
        amount = PRICES[duration_key]
        
        order_id = f"ORD_{user.id}_{int(datetime.now().timestamp())}"
        
        context.user_data['pending_payment'] = {
            'duration_days': duration_days,
            'amount': amount,
            'order_id': order_id
        }
        
        payment_details = get_bot_setting('payment_details')
        bot_name = get_bot_setting('bot_name')
        
        keyboard = [
            [InlineKeyboardButton("✅ PAID after payment", callback_data=f"paid_{order_id}")],
            [InlineKeyboardButton("🔙 Cancel", callback_data="back_to_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            f"💳 *{bot_name}*\n\n{payment_details}\n\n"
            f"💰 *Amount:* ₹{amount}\n"
            f"📅 *Duration:* {duration_days} days\n"
            f"🆔 *Order ID:* `{order_id}`\n\n"
            f"⚠️ *Click PAID after completing payment*",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    
    elif query.data.startswith("paid_"):
        order_id = query.data.replace("paid_", "")
        pending = context.user_data.get('pending_payment')
        
        if not pending or pending.get('order_id') != order_id:
            await query.edit_message_text("❌ Payment session expired. Please try again.")
            return
        
        txn_id = f"TXN_{user.id}_{int(datetime.now().timestamp())}"
        save_transaction(txn_id, user.id, pending['amount'], pending['duration_days'], 'pending', order_id)
        
        keyboard = [[InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            f"✅ *Payment Recorded!*\n\n"
            f"🆔 Transaction ID: `{txn_id}`\n"
            f"💰 Amount: ₹{pending['amount']}\n"
            f"📅 Duration: {pending['duration_days']} days\n\n"
            f"⏳ *Waiting for admin verification...*\n"
            f"You will receive your key shortly.",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        
        # Notify admins
        admin_ids = json.loads(get_bot_setting('admin_ids') or '[]')
        for admin_id in admin_ids:
            try:
                admin_keyboard = [
                    [InlineKeyboardButton("✅ Verify Payment", callback_data=f"verify_{txn_id}")],
                    [InlineKeyboardButton("❌ Reject Payment", callback_data=f"reject_{txn_id}")]
                ]
                admin_markup = InlineKeyboardMarkup(admin_keyboard)
                
                await context.bot.send_message(
                    int(admin_id),
                    f"💰 *New Payment Request!*\n\n"
                    f"👤 User: {user.first_name} (@{user.username})\n"
                    f"🆔 User ID: `{user.id}`\n"
                    f"💰 Amount: ₹{pending['amount']}\n"
                    f"📅 Duration: {pending['duration_days']} days\n"
                    f"🆔 Order ID: `{order_id}`\n"
                    f"🆔 TXN ID: `{txn_id}`",
                    reply_markup=admin_markup,
                    parse_mode='Markdown'
                )
            except Exception as e:
                logger.error(f"Failed to notify admin {admin_id}: {e}")
    
    elif query.data.startswith("verify_"):
        if not is_admin(user.id):
            await query.edit_message_text("❌ You don't have permission to do this.")
            return
        
        txn_id = query.data.replace("verify_", "")
        conn = sqlite3.connect('bot_database.db')
        c = conn.cursor()
        c.execute("SELECT user_id, amount, duration_days FROM transactions WHERE txn_id = ?", (txn_id,))
        txn = c.fetchone()
        
        if txn:
            user_id, amount, duration_days = txn
            
            key = generate_key(duration_days)
            save_key(key, duration_days, user_id)
            
            c.execute("UPDATE transactions SET status = 'completed' WHERE txn_id = ?", (txn_id,))
            conn.commit()
            
            await context.bot.send_message(
                user_id,
                f"✅ *Payment Verified!*\n\n"
                f"🔑 *Your License Key:* `{key}`\n"
                f"📅 *Valid for:* {duration_days} days\n\n"
                f"Use this key with the *Reset Key* option",
                parse_mode='Markdown'
            )
            
            await query.edit_message_text(f"✅ Payment verified! Key sent to user.")
        
        conn.close()
    
    elif query.data.startswith("reject_"):
        if not is_admin(user.id):
            await query.edit_message_text("❌ You don't have permission to do this.")
            return
        
        txn_id = query.data.replace("reject_", "")
        conn = sqlite3.connect('bot_database.db')
        c = conn.cursor()
        c.execute("SELECT user_id FROM transactions WHERE txn_id = ?", (txn_id,))
        txn = c.fetchone()
        
        if txn:
            user_id = txn[0]
            c.execute("UPDATE transactions SET status = 'rejected' WHERE txn_id = ?", (txn_id,))
            conn.commit()
            
            await context.bot.send_message(
                user_id,
                f"❌ *Payment Rejected!*\n\n"
                f"Please contact support for assistance.\n"
                f"Support: @{config.SUPPORT_USERNAME}",
                parse_mode='Markdown'
            )
            
            await query.edit_message_text(f"❌ Payment rejected.")
        
        conn.close()
    
    elif query.data == "reset_key":
        context.user_data['resetting_key'] = True
        await query.edit_message_text(
            "🔑 *Please enter your license key to reset:*\n\n"
            "Format: `XXXX-XXXX-XXXX-XXXX`",
            parse_mode='Markdown'
        )
    
    elif query.data == "admin_panel":
        if not is_admin(user.id):
            await query.edit_message_text("❌ You don't have permission to access admin panel.")
            return
        
        keyboard = [
            [InlineKeyboardButton("👥 View Users", callback_data="admin_users")],
            [InlineKeyboardButton("🔑 Manage Keys", callback_data="admin_keys")],
            [InlineKeyboardButton("💰 Transactions", callback_data="admin_transactions")],
            [InlineKeyboardButton("⚙️ Bot Settings", callback_data="admin_settings")],
            [InlineKeyboardButton("➕ Add Admin", callback_data="admin_add_admin")],
            [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_menu")]
        ]
        
        if is_owner(user.id):
            keyboard.insert(3, [InlineKeyboardButton("👑 Owner Settings", callback_data="owner_settings")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            "⚙️ *Admin Panel*\n\nSelect an option:",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    
    elif query.data == "admin_users":
        if not is_admin(user.id):
            return
        
        conn = sqlite3.connect('bot_database.db')
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM users")
        total_users = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM users WHERE is_admin = 1")
        total_admins = c.fetchone()[0]
        conn.close()
        
        keyboard = [[InlineKeyboardButton("🔙 Back to Admin", callback_data="admin_panel")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            f"👥 *User Statistics*\n\n"
            f"Total Users: {total_users}\n"
            f"Total Admins: {total_admins}\n\n"
            f"Use `/users` command to list all users",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    
    elif query.data == "admin_keys":
        if not is_admin(user.id):
            return
        
        conn = sqlite3.connect('bot_database.db')
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM keys")
        total_keys = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM keys WHERE is_used = 1")
        used_keys = c.fetchone()[0]
        conn.close()
        
        keyboard = [
            [InlineKeyboardButton("➕ Generate New Key", callback_data="admin_generate_key")],
            [InlineKeyboardButton("🔙 Back to Admin", callback_data="admin_panel")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            f"🔑 *Key Statistics*\n\n"
            f"Total Keys: {total_keys}\n"
            f"Used Keys: {used_keys}\n"
            f"Available Keys: {total_keys - used_keys}",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    
    elif query.data == "admin_generate_key":
        if not is_admin(user.id):
            return
        
        keyboard = [
            [InlineKeyboardButton("1 Day", callback_data="gen_1")],
            [InlineKeyboardButton("3 Days", callback_data="gen_3")],
            [InlineKeyboardButton("7 Days", callback_data="gen_7")],
            [InlineKeyboardButton("30 Days", callback_data="gen_30")],
            [InlineKeyboardButton("Season (90 Days)", callback_data="gen_90")],
            [InlineKeyboardButton("🔙 Back", callback_data="admin_keys")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            "🔑 *Generate New Key*\n\nSelect duration:",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    
    elif query.data.startswith("gen_"):
        if not is_admin(user.id):
            return
        
        days = int(query.data.replace("gen_", ""))
        key = generate_key(days)
        save_key(key, days, user.id)
        
        keyboard = [[InlineKeyboardButton("🔙 Back to Keys", callback_data="admin_keys")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            f"✅ *Key Generated Successfully!*\n\n"
            f"🔑 Key: `{key}`\n"
            f"📅 Duration: {days} days\n"
            f"👤 Generated by: {user.first_name}",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    
    elif query.data == "admin_transactions":
        if not is_admin(user.id):
            return
        
        conn = sqlite3.connect('bot_database.db')
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM transactions WHERE status = 'pending'")
        pending = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM transactions WHERE status = 'completed'")
        completed = c.fetchone()[0]
        c.execute("SELECT SUM(amount) FROM transactions WHERE status = 'completed'")
        total_revenue = c.fetchone()[0] or 0
        conn.close()
        
        keyboard = [[InlineKeyboardButton("🔙 Back to Admin", callback_data="admin_panel")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            f"💰 *Transaction Statistics*\n\n"
            f"Pending: {pending}\n"
            f"Completed: {completed}\n"
            f"Total Revenue: ₹{total_revenue}\n\n"
            f"Use `/transactions` to view all transactions",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    
    elif query.data == "admin_settings":
        if not is_admin(user.id):
            return
        
        keyboard = [
            [InlineKeyboardButton("📝 Change Bot Name", callback_data="settings_bot_name")],
            [InlineKeyboardButton("💬 Change Welcome Message", callback_data="settings_welcome")],
            [InlineKeyboardButton("💳 Change Payment Details", callback_data="settings_payment")],
            [InlineKeyboardButton("🔙 Back to Admin", callback_data="admin_panel")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            "⚙️ *Bot Settings*\n\nSelect setting to modify:",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    
    elif query.data == "owner_settings":
        if not is_owner(user.id):
            await query.edit_message_text("❌ Only the owner can access this.")
            return
        
        keyboard = [
            [InlineKeyboardButton("👑 Set New Owner", callback_data="owner_set_owner")],
            [InlineKeyboardButton("🔄 Rebrand Bot", callback_data="owner_rebrand")],
            [InlineKeyboardButton("📊 Full Statistics", callback_data="owner_stats")],
            [InlineKeyboardButton("🔙 Back to Admin", callback_data="admin_panel")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            "👑 *Owner Settings*\n\nSelect an option:",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    
    elif query.data == "owner_rebrand":
        if not is_owner(user.id):
            return
        
        keyboard = [
            [InlineKeyboardButton("🏷️ Change Bot Name", callback_data="rebrand_name")],
            [InlineKeyboardButton("💬 Change Welcome Message", callback_data="rebrand_welcome")],
            [InlineKeyboardButton("💳 Change Payment Details", callback_data="rebrand_payment")],
            [InlineKeyboardButton("🎨 Reset to Default", callback_data="rebrand_reset")],
            [InlineKeyboardButton("🔙 Back", callback_data="owner_settings")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            "🔄 *Rebrand Bot*\n\nCustomize your bot's appearance:",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    
    elif query.data == "back_to_menu":
        keyboard = [
            [InlineKeyboardButton("💰 Generate Key (Paid)", callback_data="generate_key")],
            [InlineKeyboardButton("🔑 Reset Key", callback_data="reset_key")],
            [InlineKeyboardButton("ℹ️ About", callback_data="about")]
        ]
        
        if is_admin(user.id):
            keyboard.append([InlineKeyboardButton("⚙️ Admin Panel", callback_data="admin_panel")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            "🌟 *Main Menu*\n\nSelect an option:",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    
    elif query.data.startswith("settings_") or query.data.startswith("rebrand_"):
        setting_type = query.data.split("_", 1)[1]
        context.user_data['editing_setting'] = setting_type
        
        prompts = {
            'bot_name': "Enter new bot name:",
            'welcome': "Enter new welcome message:",
            'payment': "Enter new payment details (UPI ID, QR instructions, etc):",
            'name': "Enter new bot name:"
        }
        
        await query.edit_message_text(prompts.get(setting_type, "Enter new value:"))

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    message_text = update.message.text
    
    if context.user_data.get('resetting_key'):
        success, result = verify_key(message_text)
        
        if success:
            use_key(result, user.id)
            await update.message.reply_text(
                f"✅ *Key activated successfully!*\n\n"
                f"Your license is now active. Enjoy!",
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text(
                f"❌ *{result}*\n\nPlease try again with a valid key.",
                parse_mode='Markdown'
            )
        
        context.user_data['resetting_key'] = False
    
    elif context.user_data.get('editing_setting'):
        setting = context.user_data['editing_setting']
        
        if setting in ['bot_name', 'name']:
            update_bot_setting('bot_name', message_text)
            await update.message.reply_text(f"✅ Bot name updated to: {message_text}")
        elif setting == 'welcome':
            update_bot_setting('welcome_message', message_text)
            await update.message.reply_text(f"✅ Welcome message updated!")
        elif setting == 'payment':
            update_bot_setting('payment_details', message_text)
            await update.message.reply_text(f"✅ Payment details updated!")
        
        context.user_data['editing_setting'] = None

async def list_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ You don't have permission.")
        return
    
    conn = sqlite3.connect('bot_database.db')
    c = conn.cursor()
    c.execute("SELECT user_id, username, first_name, join_date FROM users LIMIT 50")
    users = c.fetchall()
    conn.close()
    
    if not users:
        await update.message.reply_text("No users found.")
        return
    
    user_list = "👥 *Recent Users:*\n\n"
    for user in users:
        user_list += f"🆔 ID: `{user[0]}`\n👤 Name: {user[2]}\n📱 @{user[1]}\n📅 Joined: {user[3][:10]}\n\n"
    
    await update.message.reply_text(user_list, parse_mode='Markdown')

async def list_transactions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ You don't have permission.")
        return
    
    conn = sqlite3.connect('bot_database.db')
    c = conn.cursor()
    c.execute("SELECT txn_id, user_id, amount, status, created_at FROM transactions ORDER BY created_at DESC LIMIT 20")
    transactions = c.fetchall()
    conn.close()
    
    if not transactions:
        await update.message.reply_text("No transactions found.")
        return
    
    txn_list = "💰 *Recent Transactions:*\n\n"
    for txn in transactions:
        txn_list += f"🆔 TXN: `{txn[0][:15]}`\n👤 User: `{txn[1]}`\n💰 Amount: ₹{txn[2]}\n📊 Status: {txn[3]}\n⏰ Time: {txn[4][:16]}\n\n"
    
    await update.message.reply_text(txn_list, parse_mode='Markdown')

async def add_admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id):
        await update.message.reply_text("❌ Only the owner can add admins.")
        return
    
    try:
        user_id = context.args[0]
        admin_ids = json.loads(get_bot_setting('admin_ids') or '[]')
        
        if user_id not in admin_ids:
            admin_ids.append(user_id)
            update_bot_setting('admin_ids', json.dumps(admin_ids))
            
            conn = sqlite3.connect('bot_database.db')
            c = conn.cursor()
            c.execute("UPDATE users SET is_admin = 1 WHERE user_id = ?", (user_id,))
            conn.commit()
            conn.close()
            
            await update.message.reply_text(f"✅ User `{user_id}` is now an admin!", parse_mode='Markdown')
        else:
            await update.message.reply_text(f"User `{user_id}` is already an admin.", parse_mode='Markdown')
    except:
        await update.message.reply_text("Usage: `/addadmin <user_id>`", parse_mode='Markdown')

async def remove_admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id):
        await update.message.reply_text("❌ Only the owner can remove admins.")
        return
    
    try:
        user_id = context.args[0]
        admin_ids = json.loads(get_bot_setting('admin_ids') or '[]')
        
        if user_id in admin_ids:
            admin_ids.remove(user_id)
            update_bot_setting('admin_ids', json.dumps(admin_ids))
            
            conn = sqlite3.connect('bot_database.db')
            c = conn.cursor()
            c.execute("UPDATE users SET is_admin = 0 WHERE user_id = ?", (user_id,))
            conn.commit()
            conn.close()
            
            await update.message.reply_text(f"✅ User `{user_id}` is no longer an admin.", parse_mode='Markdown')
        else:
            await update.message.reply_text(f"User `{user_id}` is not an admin.", parse_mode='Markdown')
    except:
        await update.message.reply_text("Usage: `/removeadmin <user_id>`", parse_mode='Markdown')

async def set_owner_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id):
        await update.message.reply_text("❌ Only the current owner can set a new owner.")
        return
    
    try:
        user_id = context.args[0]
        update_bot_setting('owner_id', user_id)
        
        conn = sqlite3.connect('bot_database.db')
        c = conn.cursor()
        c.execute("UPDATE users SET is_owner = 1 WHERE user_id = ?", (user_id,))
        c.execute("UPDATE users SET is_owner = 0 WHERE user_id != ?", (user_id,))
        conn.commit()
        conn.close()
        
        await update.message.reply_text(f"✅ New owner set: `{user_id}`", parse_mode='Markdown')
    except:
        await update.message.reply_text("Usage: `/setowner <user_id>`", parse_mode='Markdown')

def main():
    init_database()
    
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("users", list_users))
    application.add_handler(CommandHandler("transactions", list_transactions))
    application.add_handler(CommandHandler("addadmin", add_admin_command))
    application.add_handler(CommandHandler("removeadmin", remove_admin_command))
    application.add_handler(CommandHandler("setowner", set_owner_command))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    logger.info(f"Bot @{BOT_ID} started successfully!")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()