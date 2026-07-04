# ==========================================
# SECTION 1: IMPORTS & MODULES
# ==========================================
import os
import logging
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommandScopeChat
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from pymongo import MongoClient
from bson.objectid import ObjectId

# ==========================================
# SECTION 2: LOGGING CONFIGURATION
# ==========================================
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', 
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ==========================================
# SECTION 3: ENVIRONMENT VARIABLES
# ==========================================
BOT_TOKEN = os.getenv("BOT_TOKEN")
MONGO_URL = os.getenv("MONGO_URL")
CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME")
ADMIN_ID = int(os.getenv("ADMIN_ID", 0))

# ==========================================
# SECTION 4: DATABASE INITIALIZATION
# ==========================================
client = MongoClient(MONGO_URL)
db = client['tg_material_bot']
users_col = db['users']
material_col = db['materials']

# ==========================================
# SECTION 5: HELPER FUNCTIONS
# ==========================================
async def is_subbed(bot, user_id):
    """चेक करता है कि यूजर ने चैनल ज्वाइन किया है या नहीं"""
    try:
        member = await bot.get_chat_member(chat_id=CHANNEL_USERNAME, user_id=user_id)
        return member.status in ['member', 'administrator', 'creator']
    except Exception as e:
        logger.error(f"Subscription check error: {e}")
        return False

async def show_main_menu(message_obj, name, is_edit=False):
    """मुख्य डैशबोर्ड और कैटगरीज़ दिखाता है"""
    keyboard = [
        [InlineKeyboardButton("💼 Banking", callback_data="acat_Banking")],
        [InlineKeyboardButton("📚 SSC", callback_data="acat_SSC")],
        [InlineKeyboardButton("🎓 UPSC", callback_data="acat_UPSC")],
        [InlineKeyboardButton("🏠 Main Menu", callback_data="amenu_main")]
    ]
    text = f"🎯 Niche di gayi categories me se chunein:"
    if is_edit:
        await message_obj.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await message_obj.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

# ==========================================
# SECTION 6: USER COMMAND HANDLERS
# ==========================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/start और /home कमांड को हैंडल करता है"""
    user_id = update.effective_user.id
    users_col.update_one(
        {'id': user_id}, 
        {'$set': {'username': update.effective_user.username, 'name': update.effective_user.first_name}}, 
        upsert=True
    )
    
    if not await is_subbed(context.bot, user_id):
        keyboard = [[InlineKeyboardButton("📢 Join Channel", url=f"https://t.me/{CHANNEL_USERNAME.replace('@','')}")]]
        await update.message.reply_text(
            "⚠️ Pehle upar diye gaye channel ko join karein tabhi bot chalega!", 
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return
    await show_main_menu(update.message, update.effective_user.first_name)

async def cmd_categories(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/categories कमांड को हैंडल करता है"""
    await show_main_menu(update.message, update.effective_user.first_name)

# ==========================================
# SECTION 7: FILE REQUEST SYSTEM (FIXED BUG)
# ==========================================
async def request_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """यूजर की फाइल रिक्वेस्ट सीधे एडमिन तक पहुँचाता है"""
    if len(context.args) < 1:
        await update.message.reply_text(
            "❌ Please provide the file name.\n\n**Example:**\n`/request Class 12 Physics Notes`",
            parse_mode='Markdown'
        )
        return
    
    file_request_name = " ".join(context.args)
    user_info = f"{update.effective_user.first_name} \nID: {update.effective_user.id}"
    
    try:
        # यहाँ 'app.send_message' की जगह 'context.bot.send_message' का उपयोग किया गया है ताकि क्रैश न हो
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=f"📥 **New Request Received!**\n\n👤 **Requested By:** {user_info}\n📂 **Requested File:** {file_request_name}",
            parse_mode='Markdown'
        )
        await update.message.reply_text(
            "✅ Your request has been sent to the Admin!\nAs soon as the material is available, it will be uploaded to the bot.",
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"Error in request_file: {e}")
        await update.message.reply_text("❌ Something went wrong. Please try again later.")

# ==========================================
# SECTION 8: INLINE BUTTON & SEARCH HANDLING
# ==========================================
async def button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """इनलाइन कीबोर्ड बटन्स के क्लिक्स को मैनेज करता है"""
    query = update.callback_query
    await query.answer()
    # यहाँ आप अपनी कैटेगरी लोडिंग की लॉजिक को बढ़ा सकते हैं

async def handle_user_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """यूजर द्वारा भेजे गए टेक्स्ट के आधार पर डेटाबेस में फाइल ढूंढता है"""
    user_id = update.effective_user.id
    if not await is_subbed(context.bot, user_id):
        return
        
    search_query = update.message.text
    results = list(material_col.find({"file_name": {"$regex": search_query, "$options": "i"}}))
    
    if not results:
        await update.message.reply_text("❌ Iske liye koi live material nahi mila.")
    else:
        text = f"📊 **Results Found (Count: {len(results)}):**\n\n"
        for mat in results:
            text += f"📄 {mat['file_name']}\n🔗 Link: /file_{mat['_id']}\n\n"
        await update.message.reply_text(text, parse_mode='Markdown')

async def handle_file_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """सर्च रिजल्ट के /file_ वाले लिंक पर क्लिक करने पर फाइल भेजता है"""
    user_id = update.effective_user.id
    if not await is_subbed(context.bot, user_id):
        return
        
    msg_text = update.message.text
    file_id_str = msg_text.split("_")[1]
    
    try:
        mat = material_col.find_one({"_id": ObjectId(file_id_str)})
        if mat:
            if mat['file_type'] == "document":
                await context.bot.send_document(chat_id=user_id, document=mat['file_id'], caption=mat['file_name'])
            elif mat['file_type'] == "photo":
                await context.bot.send_photo(chat_id=user_id, photo=mat['file_id'], caption=mat['file_name'])
            elif mat['file_type'] == "video":
                await context.bot.send_video(chat_id=user_id, video=mat['file_id'], caption=mat['file_name'])
        else:
            await update.message.reply_text("❌ File status expired or invalid ID.")
    except Exception as e:
        logger.error(f"Error sending file link: {e}")
        await update.message.reply_text("❌ Invalid File Link.")

# ==========================================
# SECTION 9: ADMIN CONTROL PANEL
# ==========================================
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    await update.message.reply_text("⚙️ Welcome to Admin Control Panel.")

async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    await update.message.reply_text("📢 Broadcast feature initiated...")

async def handle_admin_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """एडमिन द्वारा भेजी गई फाइल्स को सीधे डेटाबेस में सेव करता है"""
    message = update.message
    if message.from_user.id != ADMIN_ID:
        return
        
    file_data = {"file_id": None, "file_name": "Unnamed", "file_type": None}
    
    if message.document:
        file_data["file_id"] = message.document.file_id
        file_data["file_name"] = message.document.file_name
        file_data["file_type"] = "document"
    elif message.photo:
        file_data["file_id"] = message.photo[-1].file_id
        file_data["file_type"] = "photo"
    elif message.video:
        file_data["file_id"] = message.video.file_id
        file_data["file_name"] = message.video.file_name or "Video File"
        file_data["file_type"] = "video"
        
    if file_data["file_id"]:
        res = material_col.insert_one(file_data)
        await message.reply_text(f"✅ **Material Uploaded Successfully!**\n\n🔗 **User Link:** /file_{res.inserted_id}")

# ==========================================
# SECTION 10: MENUS & ERROR RUNNER
# ==========================================
async def setup_menus(application: Application):
    """बोट के अंदर मेनू बटन को सेट करता है"""
    user_commands = [
        ("start", "🚀 Start the Bot"),
        ("categories", "📂 View Categories"),
        ("home", "🏠 Main Dashboard"),
        ("request", "📥 Request Study Material")
    ]
    await application.bot.set_my_commands(user_commands)

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Logs: Exception while handling an update: {context.error}")

# ==========================================
# SECTION 11: MAIN APPLICATION RUNNER
# ==========================================
def main():
    """एप्लीकेशन को शुरू और हैंडलर्स को मैप करता है"""
    app = Application.builder().token(BOT_TOKEN).post_init(setup_menus).build()
    
    # कमांड्स मैपिंग
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("home", start))
    app.add_handler(CommandHandler("categories", cmd_categories))
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(CommandHandler("broadcast", broadcast_command))
    app.add_handler(CommandHandler("request", request_file))
    
    # इनलाइन क्लिक्स
    app.add_handler(CallbackQueryHandler(button_click))
    
    # मेसेजेस और मीडिया फ़िल्टर्स
    app.add_handler(MessageHandler(filters.Regex(r'^/file_[a-fA-F0-9]{24}$'), handle_file_link))
    app.add_handler(filters.Document.ALL | filters.PHOTO | filters.VIDEO, MessageHandler(handle_admin_upload))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_user_search))
    
    # एरर हैंडलर
    app.add_error_handler(error_handler)
    
    # बोट पोलिंग स्टार्ट करें
    app.run_polling()

if __name__ == '__main__':
    main()
