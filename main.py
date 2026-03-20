# main.py
import os
import json
import logging
import sqlite3
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
import config
import qrcode
from io import BytesIO

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

# Database functions
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
                  duration_days INTEGER,
                  created_at TEXT,
                  expires_at TEXT,
                  is_used INTEGER DEFAULT 0,
                  used_by INTEGER,
                  used_at TEXT,
                  added_by INTEGER)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS transactions
                 (txn_id TEXT PRIMARY KEY,
                  user_id INTEGER,
                  amount INTEGER,
                  duration_days INTEGER,
                  status TEXT,
                  created_at TEXT,
                  order_id TEXT,
                  payment_screenshot TEXT)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS bot_settings
                 (setting_key TEXT PRIMARY KEY,
                  setting_value TEXT)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS apks
                 (apk_id INTEGER PRIMARY KEY AUTOINCREMENT,
                  name TEXT,
                  version TEXT,
                  download_link TEXT,
                  created_at TEXT,
                  is_active INTEGER DEFAULT 1)''')
    
    # Insert default settings
    default_settings = [
        ('bot_name', 'ONLINE KEY BOT'),
        ('welcome_message', 'Welcome to License Key Bot'),
        ('upi_id', config.DEFAULT_UPI_ID),
        ('upi_name', config.DEFAULT_UPI_NAME),
        ('qr_code', config.DEFAULT_QR_PATH),
        ('support_username', config.SUPPORT_USERNAME),
        ('channel_link', ''),
        ('group_link', ''),
        ('admin_ids', '[]'),
        ('owner_id', config.DEFAULT_OWNER_ID),
        ('payment_note', '⚠️ *Important:* Send exact amount and share screenshot after payment')
    ]
    
    for key, value in default_settings:
        c.execute("INSERT OR IGNORE INTO bot_settings (setting_key, setting_value) VALUES (?, ?)", (key, value))
    
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

def add_key(key_text, duration_days, added_by):
    conn = sqlite3.connect('bot_database.db')
    c = conn.cursor()
    expires_at = datetime.now() + timedelta(days=duration_days)
    c.execute("INSERT INTO keys (key_text, duration_days, created_at, expires_at, added_by) VALUES (?, ?, ?, ?, ?)",
              (key_text, duration_days, datetime.now().isoformat(), expires_at.isoformat(), added_by))
    conn.commit()
    conn.close()

def verify_key(key_text):
    conn = sqlite3.connect('bot_database.db')
    c = conn.cursor()
    c.execute("SELECT key_text, duration_days, expires_at, is_used FROM keys WHERE key_text = ?", (key_text,))
    key_data = c.fetchone()
    conn.close()
    
    if not key_data:
        return False, "❌ Invalid key! Please check and try again."
    
    key_text, duration_days, expires_at, is_used = key_data
    
    if is_used:
        return False, "❌ This key has already been used!"
    
    expires_at_date = datetime.fromisoformat(expires_at)
    if expires_at_date < datetime.now():
        return False, "❌ This key has expired!"
    
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

def add_apk(name, version, download_link):
    conn = sqlite3.connect('bot_database.db')
    c = conn.cursor()
    c.execute("INSERT INTO apks (name, version, download_link, created_at) VALUES (?, ?, ?, ?)",
              (name, version, download_link, datetime.now().isoformat()))
    conn.commit()
    conn.close()

def get_apks():
    conn = sqlite3.connect('bot_database.db')
    c = conn.cursor()
    c.execute("SELECT apk_id, name, version, download_link, created_at FROM apks WHERE is_active = 1 ORDER BY created_at DESC")
    apks = c.fetchall()
    conn.close()
    return apks

def delete_apk(apk_id):
    conn = sqlite3.connect('bot_database.db')
    c = conn.cursor()
    c.execute("UPDATE apks SET is_active = 0 WHERE apk_id = ?", (apk_id,))
    conn.commit()
    conn.close()

def get_all_keys():
    conn = sqlite3.connect('bot_database.db')
    c = conn.cursor()
    c.execute("SELECT key_text, duration_days, created_at, expires_at, is_used, used_by FROM keys ORDER BY created_at DESC")
    keys = c.fetchall()
    conn.close()
    return keys

def delete_key_from_db(key_text):
    conn = sqlite3.connect('bot_database.db')
    c = conn.cursor()
    c.execute("DELETE FROM keys WHERE key_text = ?", (key_text,))
    affected = c.rowcount
    conn.commit()
    conn.close()
    return affected

# Generate QR Code
def generate_qr_code(upi_id, amount, name):
    # UPI QR format: upi://pay?pa=upi_id&pn=name&am=amount&cu=INR
    upi_url = f"upi://pay?pa={upi_id}&pn={name}&am={amount}&cu=INR"
    
    qr = qrcode.QRCode(version=1, box_size=10, border=5)
    qr.add_data(upi_url)
    qr.make(fit=True)
    
    img = qr.make_image(fill_color="black", back_color="white")
    
    # Save to bytes
    img_bytes = BytesIO()
    img.save(img_bytes, format='PNG')
    img_bytes.seek(0)
    
    return img_bytes

# Main Menu Keyboard
def get_main_menu_keyboard(user_id):
    keyboard = [
        [InlineKeyboardButton("🛒 BUY LICENSE", callback_data="buy_license")],
        [InlineKeyboardButton("🔑 ACTIVATE KEY", callback_data="activate_key")],
        [InlineKeyboardButton("📱 DOWNLOAD APK", callback_data="download_apk")],
        [InlineKeyboardButton("ℹ️ ABOUT", callback_data="about")],
        [InlineKeyboardButton("📞 SUPPORT", callback_data="support")]
    ]
    
    if is_admin(user_id):
        keyboard.append([InlineKeyboardButton("⚙️ ADMIN PANEL", callback_data="admin_panel")])
    
    return InlineKeyboardMarkup(keyboard)

# Buy License Keyboard
def get_buy_menu_keyboard():
    keyboard = [
        [InlineKeyboardButton("📦 1 DAY - ₹120", callback_data="buy_1_day")],
        [InlineKeyboardButton("📦 3 DAYS - ₹199", callback_data="buy_3_days")],
        [InlineKeyboardButton("📦 7 DAYS - ₹349", callback_data="buy_7_days")],
        [InlineKeyboardButton("📦 30 DAYS - ₹850", callback_data="buy_30_days")],
        [InlineKeyboardButton("🌟 SEASON (90 DAYS) - ₹1150", callback_data="buy_season")],
        [InlineKeyboardButton("🔙 BACK TO MENU", callback_data="back_to_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)

# Admin Panel Keyboard
def get_admin_panel_keyboard(is_owner_flag):
    keyboard = [
        [InlineKeyboardButton("👥 USER MANAGEMENT", callback_data="admin_users")],
        [InlineKeyboardButton("🔑 KEY MANAGEMENT", callback_data="admin_keys")],
        [InlineKeyboardButton("💰 TRANSACTIONS", callback_data="admin_transactions")],
        [InlineKeyboardButton("📱 APK MANAGEMENT", callback_data="admin_apks")],
        [InlineKeyboardButton("⚙️ BOT SETTINGS", callback_data="admin_settings")],
        [InlineKeyboardButton("📊 STATISTICS", callback_data="admin_stats")]
    ]
    
    if is_owner_flag:
        keyboard.append([InlineKeyboardButton("👑 OWNER CONTROLS", callback_data="owner_controls")])
    
    keyboard.append([InlineKeyboardButton("🔙 BACK TO MENU", callback_data="back_to_menu")])
    return InlineKeyboardMarkup(keyboard)

# Bot command handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    add_user(user.id, user.username, user.first_name)
    
    welcome_msg = get_bot_setting('welcome_message')
    bot_name = get_bot_setting('bot_name')
    
    welcome_text = f"""
🌟 *{bot_name}* 🌟

{welcome_msg}

📌 *Features:*
• Buy license keys instantly
• Activate your keys
• Download latest APK
• 24/7 support

👤 *Your ID:* `{user.id}`

Select an option below 👇
"""
    
    await update.message.reply_text(
        welcome_text,
        reply_markup=get_main_menu_keyboard(user.id),
        parse_mode='Markdown'
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = update.effective_user
    
    if query.data == "back_to_menu":
        await query.edit_message_text(
            "🌟 *Main Menu*\n\nSelect an option:",
            reply_markup=get_main_menu_keyboard(user.id),
            parse_mode='Markdown'
        )
    
    elif query.data == "buy_license":
        await query.edit_message_text(
            "🛒 *Select License Duration*\n\n"
            "💰 *Prices:*\n"
            "• 1 Day - ₹120\n"
            "• 3 Days - ₹199\n"
            "• 7 Days - ₹349\n"
            "• 30 Days - ₹850\n"
            "• Season (90 Days) - ₹1150\n\n"
            "Select your plan:",
            reply_markup=get_buy_menu_keyboard(),
            parse_mode='Markdown'
        )
    
    elif query.data.startswith("buy_"):
        duration_key = query.data.replace("buy_", "")
        duration_days = DURATIONS[duration_key]
        amount = PRICES[duration_key]
        
        # Store payment info in context
        context.user_data['payment_info'] = {
            'duration_days': duration_days,
            'amount': amount,
            'duration_key': duration_key
        }
        
        upi_id = get_bot_setting('upi_id')
        upi_name = get_bot_setting('upi_name')
        payment_note = get_bot_setting('payment_note')
        
        # Generate QR code
        qr_image = generate_qr_code(upi_id, amount, upi_name)
        
        payment_text = f"""
💳 *Payment Details*

💰 *Amount:* ₹{amount}
📅 *Duration:* {duration_days} days
🏦 *UPI ID:* `{upi_id}`
👤 *Account Name:* {upi_name}

{payment_note}

*Steps to Pay:*
1️⃣ Scan the QR code below
2️⃣ Pay exactly ₹{amount}
3️⃣ Take screenshot of payment
4️⃣ Click "I HAVE PAID" button
5️⃣ Send screenshot for verification
"""
        
        keyboard = [
            [InlineKeyboardButton("✅ I HAVE PAID", callback_data="payment_done")],
            [InlineKeyboardButton("🔙 CANCEL", callback_data="buy_license")]
        ]
        
        # Send QR code with payment info
        await query.edit_message_text(
            payment_text,
            parse_mode='Markdown'
        )
        
        # Send QR code as photo
        await context.bot.send_photo(
            chat_id=user.id,
            photo=qr_image,
            caption="📱 *Scan this QR code to pay*",
            parse_mode='Markdown'
        )
        
        # Send buttons after QR code
        await context.bot.send_message(
            chat_id=user.id,
            text="After payment, click the button below:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    elif query.data == "payment_done":
        if 'payment_info' not in context.user_data:
            await query.edit_message_text("❌ Session expired. Please start over.", reply_markup=get_main_menu_keyboard(user.id))
            return
        
        context.user_data['waiting_for_screenshot'] = True
        await query.edit_message_text(
            "📸 *Payment Confirmation*\n\n"
            "Please send the payment screenshot now.\n\n"
            "Make sure the screenshot shows:\n"
            "✅ Transaction ID\n"
            "✅ Amount: ₹" + str(context.user_data['payment_info']['amount']) + "\n"
            "✅ UPI ID: " + get_bot_setting('upi_id') + "\n\n"
            "Send the screenshot as a photo.",
            parse_mode='Markdown'
        )
    
    elif query.data == "activate_key":
        context.user_data['activating_key'] = True
        await query.edit_message_text(
            "🔑 *Activate License Key*\n\n"
            "Please enter your license key in this format:\n"
            "`XXXX-XXXX-XXXX-XXXX`\n\n"
            "Example: `ABCD-1234-EFGH-5678`",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 BACK", callback_data="back_to_menu")]]),
            parse_mode='Markdown'
        )
    
    elif query.data == "download_apk":
        apks = get_apks()
        
        if not apks:
            await query.edit_message_text(
                "📱 *APK Downloads*\n\nNo APKs available at the moment.\n\nPlease check back later!",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 BACK", callback_data="back_to_menu")]]),
                parse_mode='Markdown'
            )
            return
        
        keyboard = []
        for apk in apks:
            apk_id, name, version, link, _ = apk
            keyboard.append([InlineKeyboardButton(f"📱 {name} v{version}", url=link)])
        
        keyboard.append([InlineKeyboardButton("🔙 BACK", callback_data="back_to_menu")])
        
        await query.edit_message_text(
            "📱 *Available APK Downloads*\n\nClick on any version to download:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
    
    elif query.data == "about":
        bot_name = get_bot_setting('bot_name')
        await query.edit_message_text(
            f"🤖 *About {bot_name}*\n\n"
            f"**Version:** 2.0\n"
            f"**Bot ID:** `{BOT_ID}`\n\n"
            f"*Features:*\n"
            f"✓ Buy license keys\n"
            f"✓ Activate keys instantly\n"
            f"✓ Download APK files\n"
            f"✓ 24/7 automated support\n\n"
            f"*Developer:* @{config.DEVELOPER_USERNAME}\n\n"
            f"© 2024 All Rights Reserved",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 BACK", callback_data="back_to_menu")]]),
            parse_mode='Markdown'
        )
    
    elif query.data == "support":
        support_user = get_bot_setting('support_username')
        channel = get_bot_setting('channel_link')
        group = get_bot_setting('group_link')
        
        support_text = f"📞 *Support Information*\n\n"
        
        if support_user:
            support_text += f"👤 *Support:* @{support_user}\n"
        if channel:
            support_text += f"📢 *Channel:* {channel}\n"
        if group:
            support_text += f"💬 *Group:* {group}\n"
        
        support_text += f"\n⚡ *Response Time:* Usually within 24 hours"
        
        keyboard = []
        if support_user:
            keyboard.append([InlineKeyboardButton("📨 CONTACT SUPPORT", url=f"https://t.me/{support_user}")])
        if channel:
            keyboard.append([InlineKeyboardButton("📢 JOIN CHANNEL", url=channel)])
        if group:
            keyboard.append([InlineKeyboardButton("💬 JOIN GROUP", url=group)])
        
        keyboard.append([InlineKeyboardButton("🔙 BACK", callback_data="back_to_menu")])
        
        await query.edit_message_text(
            support_text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
    
    # Admin Panel Handlers
    elif query.data == "admin_panel":
        if not is_admin(user.id):
            await query.edit_message_text("❌ Access Denied! You are not an admin.", reply_markup=get_main_menu_keyboard(user.id))
            return
        
        await query.edit_message_text(
            "⚙️ *Admin Panel*\n\nSelect an option:",
            reply_markup=get_admin_panel_keyboard(is_owner(user.id)),
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
        c.execute("SELECT COUNT(*) FROM users WHERE is_owner = 1")
        total_owners = c.fetchone()[0]
        conn.close()
        
        keyboard = [
            [InlineKeyboardButton("📊 VIEW ALL USERS", callback_data="view_all_users")],
            [InlineKeyboardButton("➕ ADD ADMIN", callback_data="add_admin")],
            [InlineKeyboardButton("➖ REMOVE ADMIN", callback_data="remove_admin")],
            [InlineKeyboardButton("🔙 BACK", callback_data="admin_panel")]
        ]
        
        await query.edit_message_text(
            f"👥 *User Management*\n\n"
            f"📊 *Statistics:*\n"
            f"• Total Users: {total_users}\n"
            f"• Admins: {total_admins}\n"
            f"• Owners: {total_owners}\n\n"
            f"Select an action:",
            reply_markup=InlineKeyboardMarkup(keyboard),
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
        c.execute("SELECT COUNT(*) FROM keys WHERE is_used = 0 AND datetime(expires_at) > datetime('now')")
        active_keys = c.fetchone()[0]
        conn.close()
        
        keyboard = [
            [InlineKeyboardButton("➕ ADD NEW KEY", callback_data="add_key_menu")],
            [InlineKeyboardButton("📊 VIEW ALL KEYS", callback_data="view_keys")],
            [InlineKeyboardButton("🗑️ DELETE KEY", callback_data="delete_key")],
            [InlineKeyboardButton("🔙 BACK", callback_data="admin_panel")]
        ]
        
        await query.edit_message_text(
            f"🔑 *Key Management*\n\n"
            f"📊 *Statistics:*\n"
            f"• Total Keys: {total_keys}\n"
            f"• Used Keys: {used_keys}\n"
            f"• Active Keys: {active_keys}\n\n"
            f"Select an action:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
    
    elif query.data == "add_key_menu":
        if not is_admin(user.id):
            return
        
        keyboard = [
            [InlineKeyboardButton("📦 1 DAY", callback_data="addkey_1")],
            [InlineKeyboardButton("📦 3 DAYS", callback_data="addkey_3")],
            [InlineKeyboardButton("📦 7 DAYS", callback_data="addkey_7")],
            [InlineKeyboardButton("📦 30 DAYS", callback_data="addkey_30")],
            [InlineKeyboardButton("🌟 SEASON (90 DAYS)", callback_data="addkey_90")],
            [InlineKeyboardButton("🔙 BACK", callback_data="admin_keys")]
        ]
        
        await query.edit_message_text(
            "🔑 *Add License Key*\n\nSelect duration for the key:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
    
    elif query.data.startswith("addkey_"):
        if not is_admin(user.id):
            return
        
        days = int(query.data.replace("addkey_", ""))
        context.user_data['adding_key'] = {
            'duration': days,
            'waiting_for_key': True
        }
        
        await query.edit_message_text(
            f"🔑 *Add License Key*\n\n"
            f"📅 *Duration:* {days} days\n\n"
            f"Please enter the license key to add.\n\n"
            f"Format: `XXXX-XXXX-XXXX-XXXX`\n\n"
            f"Example: `ABCD-1234-EFGH-5678`\n\n"
            f"Or enter multiple keys (one per line):\n"
            f"`ABCD-1234-EFGH-5678`\n"
            f"`WXYZ-5678-ABCD-1234`",
            parse_mode='Markdown'
        )
    
    elif query.data == "view_keys":
        if not is_admin(user.id):
            return
        
        keys = get_all_keys()
        
        if not keys:
            await query.edit_message_text("No keys found.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 BACK", callback_data="admin_keys")]]))
            return
        
        key_list = "🔑 *All Keys:*\n\n"
        for key in keys[:20]:  # Show last 20 keys
            key_text, duration, created, expires, is_used, used_by = key
            status = "✅ Used" if is_used else "🆕 Available"
            key_list += f"🔑 `{key_text}`\n📅 {duration} days\n📊 {status}\n🕐 Added: {created[:10]}\n\n"
        
        if len(keys) > 20:
            key_list += f"\n*Showing 20 of {len(keys)} keys*"
        
        await query.edit_message_text(
            key_list,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 BACK", callback_data="admin_keys")]]),
            parse_mode='Markdown'
        )
    
    elif query.data == "delete_key":
        if not is_admin(user.id):
            return
        
        context.user_data['deleting_key'] = True
        await query.edit_message_text(
            "🗑️ *Delete License Key*\n\n"
            "Please send the license key you want to delete.\n\n"
            "Format: `XXXX-XXXX-XXXX-XXXX`",
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
        
        keyboard = [
            [InlineKeyboardButton("📊 PENDING TRANSACTIONS", callback_data="pending_txns")],
            [InlineKeyboardButton("📊 ALL TRANSACTIONS", callback_data="all_txns")],
            [InlineKeyboardButton("🔙 BACK", callback_data="admin_panel")]
        ]
        
        await query.edit_message_text(
            f"💰 *Transaction Management*\n\n"
            f"📊 *Statistics:*\n"
            f"• Pending: {pending}\n"
            f"• Completed: {completed}\n"
            f"• Total Revenue: ₹{total_revenue}\n\n"
            f"Select an option:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
    
    elif query.data == "admin_apks":
        if not is_admin(user.id):
            return
        
        keyboard = [
            [InlineKeyboardButton("➕ ADD NEW APK", callback_data="add_apk")],
            [InlineKeyboardButton("📱 VIEW APKS", callback_data="view_apks")],
            [InlineKeyboardButton("🗑️ DELETE APK", callback_data="delete_apk_menu")],
            [InlineKeyboardButton("🔙 BACK", callback_data="admin_panel")]
        ]
        
        await query.edit_message_text(
            "📱 *APK Management*\n\n"
            "Manage your APK files:\n\n"
            "• Add new APK with download link\n"
            "• View all available APKs\n"
            "• Remove outdated APKs",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
    
    elif query.data == "add_apk":
        if not is_admin(user.id):
            return
        
        context.user_data['adding_apk'] = True
        await query.edit_message_text(
            "📱 *Add New APK*\n\n"
            "Please send the APK details in this format:\n\n"
            "`Name | Version | Download Link`\n\n"
            "Example:\n"
            "`MyApp | 1.0.0 | https://example.com/app.apk`\n\n"
            "Send the details now:",
            parse_mode='Markdown'
        )
    
    elif query.data == "view_apks":
        if not is_admin(user.id):
            return
        
        apks = get_apks()
        
        if not apks:
            await query.edit_message_text("No APKs found.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 BACK", callback_data="admin_apks")]]))
            return
        
        apk_list = "📱 *Available APKs:*\n\n"
        for apk in apks:
            apk_id, name, version, link, created = apk
            apk_list += f"*ID:* {apk_id}\n*Name:* {name}\n*Version:* {version}\n*Link:* [Download]({link})\n*Added:* {created[:10]}\n\n"
        
        await query.edit_message_text(
            apk_list,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 BACK", callback_data="admin_apks")]]),
            parse_mode='Markdown',
            disable_web_page_preview=True
        )
    
    elif query.data == "delete_apk_menu":
        if not is_admin(user.id):
            return
        
        apks = get_apks()
        
        if not apks:
            await query.edit_message_text("No APKs to delete.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 BACK", callback_data="admin_apks")]]))
            return
        
        keyboard = []
        for apk in apks:
            apk_id, name, version, _, _ = apk
            keyboard.append([InlineKeyboardButton(f"🗑️ {name} v{version}", callback_data=f"del_apk_{apk_id}")])
        
        keyboard.append([InlineKeyboardButton("🔙 BACK", callback_data="admin_apks")])
        
        await query.edit_message_text(
            "Select APK to delete:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    elif query.data.startswith("del_apk_"):
        if not is_admin(user.id):
            return
        
        apk_id = query.data.replace("del_apk_", "")
        delete_apk(apk_id)
        
        await query.edit_message_text(
            "✅ APK deleted successfully!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 BACK", callback_data="admin_apks")]])
        )
    
    elif query.data == "admin_settings":
        if not is_admin(user.id):
            return
        
        keyboard = [
            [InlineKeyboardButton("🏷️ CHANGE BOT NAME", callback_data="set_bot_name")],
            [InlineKeyboardButton("💬 CHANGE WELCOME MSG", callback_data="set_welcome")],
            [InlineKeyboardButton("💰 CHANGE UPI ID", callback_data="set_upi")],
            [InlineKeyboardButton("👤 CHANGE UPI NAME", callback_data="set_upi_name")],
            [InlineKeyboardButton("📞 CHANGE SUPPORT USERNAME", callback_data="set_support")],
            [InlineKeyboardButton("📢 CHANGE CHANNEL LINK", callback_data="set_channel")],
            [InlineKeyboardButton("💬 CHANGE GROUP LINK", callback_data="set_group")],
            [InlineKeyboardButton("📝 CHANGE PAYMENT NOTE", callback_data="set_payment_note")],
            [InlineKeyboardButton("🔙 BACK", callback_data="admin_panel")]
        ]
        
        await query.edit_message_text(
            "⚙️ *Bot Settings*\n\nSelect setting to modify:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
    
    elif query.data == "admin_stats":
        if not is_admin(user.id):
            return
        
        conn = sqlite3.connect('bot_database.db')
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM users")
        total_users = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM keys")
        total_keys = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM keys WHERE is_used = 1")
        used_keys = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM transactions")
        total_txns = c.fetchone()[0]
        c.execute("SELECT SUM(amount) FROM transactions WHERE status = 'completed'")
        revenue = c.fetchone()[0] or 0
        c.execute("SELECT COUNT(*) FROM transactions WHERE status = 'pending'")
        pending = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM apks WHERE is_active = 1")
        total_apks = c.fetchone()[0]
        conn.close()
        
        await query.edit_message_text(
            f"📊 *Bot Statistics*\n\n"
            f"👥 *Users:* {total_users}\n"
            f"🔑 *Keys Added:* {total_keys}\n"
            f"✓ *Keys Used:* {used_keys}\n"
            f"💰 *Total Revenue:* ₹{revenue}\n"
            f"⏳ *Pending Payments:* {pending}\n"
            f"📊 *Total Transactions:* {total_txns}\n"
            f"📱 *APKs Available:* {total_apks}\n\n"
            f"📅 *Last Updated:* {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 BACK", callback_data="admin_panel")]]),
            parse_mode='Markdown'
        )
    
    elif query.data == "owner_controls":
        if not is_owner(user.id):
            return
        
        keyboard = [
            [InlineKeyboardButton("👑 SET NEW OWNER", callback_data="set_owner")],
            [InlineKeyboardButton("➕ ADD ADMIN", callback_data="add_admin")],
            [InlineKeyboardButton("➖ REMOVE ADMIN", callback_data="remove_admin")],
            [InlineKeyboardButton("🔄 RESET BOT SETTINGS", callback_data="reset_settings")],
            [InlineKeyboardButton("📊 FULL DATABASE BACKUP", callback_data="backup_db")],
            [InlineKeyboardButton("🔙 BACK", callback_data="admin_panel")]
        ]
        
        await query.edit_message_text(
            "👑 *Owner Controls*\n\n"
            "Advanced administrative controls:\n\n"
            "• Set new bot owner\n"
            "• Manage admin privileges\n"
            "• Reset bot to default settings\n"
            "• Backup database\n\n"
            "Select an option:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
    
    elif query.data in ["add_admin", "remove_admin", "set_owner"]:
        if not (is_owner(user.id) or (query.data == "add_admin" and is_admin(user.id))):
            return
        
        action = query.data.replace("_", " ")
        context.user_data['admin_action'] = query.data
        await query.edit_message_text(
            f"🔧 *{action.upper()}*\n\n"
            f"Please send the user ID of the user.\n\n"
            f"User ID format: `123456789`\n\n"
            f"You can get user ID from /users command or by asking the user to send /start",
            parse_mode='Markdown'
        )
    
    elif query.data.startswith("set_"):
        setting = query.data.replace("set_", "")
        context.user_data['setting_to_change'] = setting
        
        prompts = {
            'bot_name': "📝 Enter new bot name:",
            'welcome': "💬 Enter new welcome message:",
            'upi': "💰 Enter new UPI ID:",
            'upi_name': "👤 Enter new UPI account name:",
            'support': "📞 Enter support username (without @):",
            'channel': "📢 Enter channel link:",
            'group': "💬 Enter group link:",
            'payment_note': "📝 Enter new payment note:"
        }
        
        await query.edit_message_text(
            prompts.get(setting, "Enter new value:"),
            parse_mode='Markdown'
        )
    
    elif query.data == "view_all_users":
        if not is_admin(user.id):
            return
        
        conn = sqlite3.connect('bot_database.db')
        c = conn.cursor()
        c.execute("SELECT user_id, username, first_name, join_date FROM users ORDER BY join_date DESC LIMIT 20")
        users = c.fetchall()
        conn.close()
        
        if not users:
            await query.edit_message_text("No users found.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 BACK", callback_data="admin_users")]]))
            return
        
        user_list = "👥 *Recent Users:*\n\n"
        for u in users:
            user_id, username, name, join_date = u
            user_list += f"🆔 ID: `{user_id}`\n👤 Name: {name}\n📱 @{username or 'N/A'}\n📅 Joined: {join_date[:10]}\n\n"
        
        await query.edit_message_text(
            user_list,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 BACK", callback_data="admin_users")]]),
            parse_mode='Markdown'
        )
    
    elif query.data == "pending_txns":
        if not is_admin(user.id):
            return
        
        conn = sqlite3.connect('bot_database.db')
        c = conn.cursor()
        c.execute("SELECT txn_id, user_id, amount, duration_days, created_at FROM transactions WHERE status = 'pending' ORDER BY created_at DESC")
        txns = c.fetchall()
        conn.close()
        
        if not txns:
            await query.edit_message_text("No pending transactions.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 BACK", callback_data="admin_transactions")]]))
            return
        
        keyboard = []
        for txn in txns:
            txn_id, user_id, amount, duration, created = txn
            keyboard.append([InlineKeyboardButton(f"💰 ₹{amount} - User {user_id}", callback_data=f"view_txn_{txn_id}")])
        
        keyboard.append([InlineKeyboardButton("🔙 BACK", callback_data="admin_transactions")])
        
        await query.edit_message_text(
            "⏳ *Pending Transactions*\n\nClick on any transaction to verify:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
    
    elif query.data.startswith("view_txn_"):
        if not is_admin(user.id):
            return
        
        txn_id = query.data.replace("view_txn_", "")
        conn = sqlite3.connect('bot_database.db')
        c = conn.cursor()
        c.execute("SELECT user_id, amount, duration_days, created_at, order_id FROM transactions WHERE txn_id = ?", (txn_id,))
        txn = c.fetchone()
        conn.close()
        
        if txn:
            user_id, amount, duration, created, order_id = txn
            
            keyboard = [
                [InlineKeyboardButton("✅ VERIFY", callback_data=f"verify_{txn_id}")],
                [InlineKeyboardButton("❌ REJECT", callback_data=f"reject_{txn_id}")],
                [InlineKeyboardButton("🔙 BACK", callback_data="pending_txns")]
            ]
            
            await query.edit_message_text(
                f"💰 *Transaction Details*\n\n"
                f"🆔 TXN ID: `{txn_id}`\n"
                f"👤 User ID: `{user_id}`\n"
                f"💰 Amount: ₹{amount}\n"
                f"📅 Duration: {duration} days\n"
                f"🕐 Time: {created}\n"
                f"📝 Order ID: `{order_id}`\n\n"
                f"⚠️ Verify after checking payment screenshot",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
    
    elif query.data.startswith("verify_"):
        if not is_admin(user.id):
            return
        
        txn_id = query.data.replace("verify_", "")
        conn = sqlite3.connect('bot_database.db')
        c = conn.cursor()
        c.execute("SELECT user_id, amount, duration_days FROM transactions WHERE txn_id = ?", (txn_id,))
        txn = c.fetchone()
        
        if txn:
            user_id, amount, duration_days = txn
            
            # Check if we have any keys available for this duration
            conn2 = sqlite3.connect('bot_database.db')
            c2 = conn2.cursor()
            c2.execute("SELECT key_text FROM keys WHERE duration_days = ? AND is_used = 0 AND datetime(expires_at) > datetime('now') LIMIT 1", (duration_days,))
            available_key = c2.fetchone()
            
            if available_key:
                key = available_key[0]
                c2.execute("UPDATE keys SET is_used = 1, used_by = ?, used_at = ? WHERE key_text = ?",
                          (user_id, datetime.now().isoformat(), key))
                conn2.commit()
                conn2.close()
                
                c.execute("UPDATE transactions SET status = 'completed' WHERE txn_id = ?", (txn_id,))
                conn.commit()
                conn.close()
                
                # Send key to user
                await context.bot.send_message(
                    user_id,
                    f"✅ *Payment Verified!*\n\n"
                    f"🔑 *Your License Key:* `{key}`\n"
                    f"📅 *Valid for:* {duration_days} days\n\n"
                    f"Use this key with the *ACTIVATE KEY* option.\n\n"
                    f"Thank you for your purchase! 🎉",
                    parse_mode='Markdown',
                    reply_markup=get_main_menu_keyboard(user_id)
                )
                
                await query.edit_message_text(f"✅ Payment verified! Key sent to user.")
            else:
                conn2.close()
                await query.edit_message_text(f"❌ No keys available for {duration_days} days! Please add keys first.")
        
        conn.close()
    
    elif query.data.startswith("reject_"):
        if not is_admin(user.id):
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
            conn.close()
            
            await context.bot.send_message(
                user_id,
                f"❌ *Payment Rejected!*\n\n"
                f"Your payment could not be verified.\n\n"
                f"Please contact support for assistance.\n"
                f"Support: @{get_bot_setting('support_username')}",
                parse_mode='Markdown'
            )
            
            await query.edit_message_text(f"❌ Payment rejected.")
    
    elif query.data == "all_txns":
        if not is_admin(user.id):
            return
        
        conn = sqlite3.connect('bot_database.db')
        c = conn.cursor()
        c.execute("SELECT txn_id, user_id, amount, status, created_at FROM transactions ORDER BY created_at DESC LIMIT 20")
        txns = c.fetchall()
        conn.close()
        
        if not txns:
            await query.edit_message_text("No transactions found.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 BACK", callback_data="admin_transactions")]]))
            return
        
        txn_list = "💰 *Recent Transactions:*\n\n"
        for txn in txns:
            txn_id, user_id, amount, status, created = txn
            status_emoji = "✅" if status == "completed" else "⏳" if status == "pending" else "❌"
            txn_list += f"{status_emoji} `{txn_id[:15]}`\n👤 User: `{user_id}`\n💰 ₹{amount}\n🕐 {created[:10]}\n\n"
        
        await query.edit_message_text(
            txn_list,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 BACK", callback_data="admin_transactions")]]),
            parse_mode='Markdown'
        )
    
    elif query.data == "reset_settings":
        if not is_owner(user.id):
            return
        
        # Reset to default settings
        default_settings = {
            'bot_name': 'ONLINE KEY BOT',
            'welcome_message': 'Welcome to License Key Bot',
            'upi_id': config.DEFAULT_UPI_ID,
            'upi_name': config.DEFAULT_UPI_NAME,
            'support_username': config.SUPPORT_USERNAME,
            'channel_link': '',
            'group_link': '',
            'payment_note': '⚠️ *Important:* Send exact amount and share screenshot after payment'
        }
        
        for key, value in default_settings.items():
            update_bot_setting(key, value)
        
        await query.edit_message_text(
            "✅ Bot settings have been reset to default!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 BACK", callback_data="owner_controls")]])
        )
    
    elif query.data == "backup_db":
        if not is_owner(user.id):
            return
        
        # Send database file to owner
        try:
            with open('bot_database.db', 'rb') as f:
                await context.bot.send_document(
                    user.id,
                    f,
                    filename=f'backup_{datetime.now().strftime("%Y%m%d_%H%M%S")}.db',
                    caption="📊 Database Backup"
                )
            await query.edit_message_text("✅ Database backup sent!")
        except Exception as e:
            await query.edit_message_text(f"❌ Backup failed: {str(e)}")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    message_text = update.message.text
    
    # Handle key activation
    if context.user_data.get('activating_key'):
        if '-' in message_text and len(message_text) >= 19:  # XXXX-XXXX-XXXX-XXXX format
            success, result = verify_key(message_text)
            
            if success:
                use_key(result, user.id)
                await update.message.reply_text(
                    f"✅ *Key Activated Successfully!*\n\n"
                    f"Your license is now active. Enjoy the premium features! 🎉\n\n"
                    f"🔑 Key: `{result}`",
                    parse_mode='Markdown',
                    reply_markup=get_main_menu_keyboard(user.id)
                )
            else:
                await update.message.reply_text(
                    f"{result}\n\n"
                    f"Please check the key and try again.",
                    parse_mode='Markdown'
                )
        else:
            await update.message.reply_text(
                "❌ *Invalid Format!*\n\n"
                "Please use this format:\n"
                "`XXXX-XXXX-XXXX-XXXX`\n\n"
                "Example: `ABCD-1234-EFGH-5678`",
                parse_mode='Markdown'
            )
        
        context.user_data['activating_key'] = False
    
    # Handle adding multiple keys
    elif context.user_data.get('adding_key', {}).get('waiting_for_key'):
        duration = context.user_data['adding_key']['duration']
        keys = message_text.strip().split('\n')
        added_count = 0
        
        for key_text in keys:
            key_text = key_text.strip().upper()
            if '-' in key_text and len(key_text) >= 19:
                try:
                    add_key(key_text, duration, user.id)
                    added_count += 1
                except sqlite3.IntegrityError:
                    await update.message.reply_text(f"❌ Key `{key_text}` already exists!", parse_mode='Markdown')
            else:
                await update.message.reply_text(f"❌ Invalid key format: `{key_text}`\nUse format: XXXX-XXXX-XXXX-XXXX", parse_mode='Markdown')
        
        if added_count > 0:
            await update.message.reply_text(
                f"✅ *Added {added_count} key(s) successfully!*\n\n"
                f"📅 Duration: {duration} days\n"
                f"🔑 Keys added: {added_count}",
                parse_mode='Markdown'
            )
        
        context.user_data['adding_key'] = None
    
    # Handle APK addition
    elif context.user_data.get('adding_apk'):
        try:
            parts = message_text.split('|')
            if len(parts) >= 3:
                name = parts[0].strip()
                version = parts[1].strip()
                link = parts[2].strip()
                
                add_apk(name, version, link)
                await update.message.reply_text(
                    f"✅ *APK Added Successfully!*\n\n"
                    f"📱 Name: {name}\n"
                    f"📌 Version: {version}\n"
                    f"🔗 Link: {link}",
                    parse_mode='Markdown'
                )
            else:
                await update.message.reply_text(
                    "❌ *Invalid Format!*\n\n"
                    "Please use this format:\n"
                    "`Name | Version | Download Link`\n\n"
                    "Example:\n"
                    "`MyApp | 1.0.0 | https://example.com/app.apk`",
                    parse_mode='Markdown'
                )
        except Exception as e:
            await update.message.reply_text(f"❌ Error: {str(e)}")
        
        context.user_data['adding_apk'] = False
    
    # Handle admin actions (add/remove admin, set owner)
    elif context.user_data.get('admin_action'):
        action = context.user_data['admin_action']
        
        try:
            user_id = message_text.strip()
            
            if action == "add_admin":
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
            
            elif action == "remove_admin":
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
            
            elif action == "set_owner":
                update_bot_setting('owner_id', user_id)
                
                conn = sqlite3.connect('bot_database.db')
                c = conn.cursor()
                c.execute("UPDATE users SET is_owner = 1 WHERE user_id = ?", (user_id,))
                c.execute("UPDATE users SET is_owner = 0 WHERE user_id != ?", (user_id,))
                conn.commit()
                conn.close()
                
                await update.message.reply_text(f"✅ New owner set: `{user_id}`", parse_mode='Markdown')
        
        except Exception as e:
            await update.message.reply_text(f"❌ Error: {str(e)}")
        
        context.user_data['admin_action'] = None
    
    # Handle settings changes
    elif context.user_data.get('setting_to_change'):
        setting = context.user_data['setting_to_change']
        
        update_bot_setting(setting, message_text)
        
        setting_names = {
            'bot_name': 'Bot Name',
            'welcome': 'Welcome Message',
            'upi': 'UPI ID',
            'upi_name': 'UPI Account Name',
            'support': 'Support Username',
            'channel': 'Channel Link',
            'group': 'Group Link',
            'payment_note': 'Payment Note'
        }
        
        await update.message.reply_text(
            f"✅ {setting_names.get(setting, 'Setting')} updated successfully!\n\n"
            f"New Value: {message_text}",
            parse_mode='Markdown'
        )
        
        context.user_data['setting_to_change'] = None
    
    # Handle key deletion
    elif context.user_data.get('deleting_key'):
        affected = delete_key_from_db(message_text)
        
        if affected > 0:
            await update.message.reply_text(f"✅ Key `{message_text}` has been deleted.", parse_mode='Markdown')
        else:
            await update.message.reply_text(f"❌ Key `{message_text}` not found.", parse_mode='Markdown')
        
        context.user_data['deleting_key'] = False
    
    # Handle payment screenshot
    elif context.user_data.get('waiting_for_screenshot'):
        if update.message.photo:
            payment_info = context.user_data.get('payment_info', {})
            
            # Get the photo file
            photo_file = await update.message.photo[-1].get_file()
            
            # Save transaction
            txn_id = f"TXN_{user.id}_{int(datetime.now().timestamp())}"
            order_id = f"ORD_{user.id}_{int(datetime.now().timestamp())}"
            
            save_transaction(
                txn_id, 
                user.id, 
                payment_info.get('amount', 0), 
                payment_info.get('duration_days', 0), 
                'pending', 
                order_id
            )
            
            # Notify all admins
            admin_ids = json.loads(get_bot_setting('admin_ids') or '[]')
            owner_id = get_bot_setting('owner_id')
            all_admins = admin_ids + [owner_id]
            
            for admin_id in all_admins:
                try:
                    # Send screenshot
                    await context.bot.send_photo(
                        int(admin_id),
                        photo_file.file_id,
                        caption=f"💰 *New Payment Request!*\n\n"
                               f"👤 User: {user.first_name} (@{user.username})\n"
                               f"🆔 User ID: `{user.id}`\n"
                               f"💰 Amount: ₹{payment_info.get('amount', 0)}\n"
                               f"📅 Duration: {payment_info.get('duration_days', 0)} days\n"
                               f"🆔 TXN ID: `{txn_id}`\n"
                               f"🆔 Order ID: `{order_id}`\n\n"
                               f"Use admin panel to verify this payment.",
                        parse_mode='Markdown',
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("✅ VERIFY", callback_data=f"verify_{txn_id}")],
                            [InlineKeyboardButton("❌ REJECT", callback_data=f"reject_{txn_id}")]
                        ])
                    )
                except Exception as e:
                    logger.error(f"Failed to notify admin {admin_id}: {e}")
            
            await update.message.reply_text(
                f"✅ *Payment Screenshot Received!*\n\n"
                f"Your transaction ID: `{txn_id}`\n\n"
                f"⏳ Please wait for admin verification.\n"
                f"You will receive your license key shortly.\n\n"
                f"Thank you for your purchase! 🎉",
                parse_mode='Markdown',
                reply_markup=get_main_menu_keyboard(user.id)
            )
        else:
            await update.message.reply_text(
                "❌ *Please send a photo/screenshot*\n\n"
                "Take a screenshot of your payment and send it as a photo.",
                parse_mode='Markdown'
            )
        
        context.user_data['waiting_for_screenshot'] = False
        context.user_data['payment_info'] = None
    
    else:
        await update.message.reply_text(
            "❓ *Unknown Command*\n\n"
            "Please use the buttons below to navigate:",
            reply_markup=get_main_menu_keyboard(user.id),
            parse_mode='Markdown'
        )

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Update {update} caused error {context.error}")

def main():
    # Initialize database
    init_database()
    
    # Create application
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(MessageHandler(filters.PHOTO, handle_message))
    application.add_error_handler(error_handler)
    
    logger.info(f"Bot @{BOT_ID} started successfully!")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()