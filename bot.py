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
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
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
co_admins_col = db['co_admins']  # New collection to persist multi-user upload permissions
dynamic_buttons_col = db['dynamic_buttons']  # Super Admin custom channels/bots buttons
requests_col = db['user_requests']  # New collection to track user file requests

# State Memory for Actions & Conversations
admin_states = {}
user_states = {}  # Tracks conversational flow like waiting for material request name

# ==========================================
# SECTION 5: HELPER FUNCTIONS & MIDDLEWARES
# ==========================================
async def is_subscribed(bot, user_id):
    """Checks if the user is a member of the mandatory update channel."""
    try:
        member = await bot.get_chat_member(chat_id=CHANNEL_USERNAME, user_id=user_id)
        return member.status in ['member', 'administrator', 'creator']
    except Exception as e:
        logger.error(f"Error checking subscription: {e}")
        return False

def is_admin_or_co_admin(user_id):
    """Checks if the user is either the main owner or an approved contributor."""
    if user_id == ADMIN_ID:
        return True
    return co_admins_col.find_one({"user_id": user_id}) is not None

async def send_material_file(bot, chat_id, file_data):
    """Dispatches saved media or documents securely to users and tracks analytics."""
    try:
        if file_data["file_type"] == "document":
            await bot.send_document(chat_id=chat_id, document=file_data["file_id"], caption=file_data["file_name"])
        elif file_data["file_type"] == "photo":
            await bot.send_photo(chat_id=chat_id, photo=file_data["file_id"], caption=file_data["file_name"])
        elif file_data["file_type"] == "video":
            await bot.send_video(chat_id=chat_id, video=file_data["file_id"], caption=file_data["file_name"])
        
        # Track history: Add file to user's downloaded files history if not already present
        users_col.update_one(
            {"user_id": chat_id},
            {"$addToSet": {"downloaded_files": {"file_id": str(file_data["_id"]), "file_name": file_data["file_name"]}}}
        )
    except Exception as e:
        logger.error(f"Error sending file: {e}")

async def setup_menus(application: Application):
    """Sets role-specific bot command menus dynamically via scopes on startup."""
    bot = application.bot
    try:
        user_commands = [
            ("start", "🚀 Start Bot / Dashboard"),
            ("categories", "🗂️ View Categories"),
            ("home", "🏠 Main Menu"),
            ("request", "📥 Request Extra Material")
        ]
        await bot.set_my_commands(user_commands)
        
        if ADMIN_ID != 0:
            admin_commands = [
                ("start", "🚀 Start Bot"),
                ("categories", "🗂️ View Categories"),
                ("home", "🏠 Main Dashboard"),
                ("request", "📥 Request Material"),
                ("admin", "👑 Admin Panel"),
                ("broadcast", "📢 Broadcast Message"),
                ("coadmins", "👥 Manage Co-Admins")
            ]
            await bot.set_my_commands(admin_commands, scope=BotCommandScopeChat(chat_id=ADMIN_ID))
        logger.info("Bot commands menu registered successfully.")
    except Exception as e:
        logger.error(f"Error setting menus: {e}")

# ==========================================
# SECTION 6: USER CORE COMMAND HANDLERS
# ==========================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Triggered on /start or /home command."""
    user = update.effective_user
    user_id = user.id
    
    if not users_col.find_one({"user_id": user_id}):
        users_col.insert_one({"user_id": user_id, "username": user.username, "name": user.first_name, "downloaded_files": []})

    if not await is_subscribed(context.bot, user_id):
        keyboard = [
            [InlineKeyboardButton("📢 Join Channel", url=f"https://t.me/{CHANNEL_USERNAME.replace('@','')}")],
            [InlineKeyboardButton("🔄 Verify Me", callback_data="verify")]
        ]
        await update.message.reply_text("Pehle upar diye channel ko join karein!", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    await show_main_menu(update.message, user.first_name, is_edit=False)

async def show_main_menu(message_obj, name, is_edit=True):
    """Renders the top level highly polished dashboard."""
    keyboard = [
        [InlineKeyboardButton("🗂️ View Categories", callback_data="view_cats")],
        [InlineKeyboardButton("👤 My Profile", callback_data="my_profile"), InlineKeyboardButton("📊 Bot Stats", callback_data="bot_stats")],
        [InlineKeyboardButton("📥 Request Files", callback_data="user_req_menu")],
        [InlineKeyboardButton("✨ More Buttons ✨", callback_data="more_combined")]
    ]
    
    text = (
        f"📚 **Welcome {name} to the Ultimate Study Dashboard!** ✨\n\n"
        f"Yahan aapko aapki padhai ke liye sabhi important **PDFs, Hand-written Notes, Question Banks aur Videos** bilkul free milenge! 🚀\n\n"
        f"💡 **Kaise search karein?**\n"
        f"• Aap seedhe chat me kisi bhi subject ya chapter ka naam (e.g., *Physics Notes*) likh kar bhej sakte hain, bot use automatically dhoodh lega!\n"
        f"• Ya fir niche diye gaye **View Categories** option ka use karke systematic tariqe se padh sakte hain.\n\n"
        f"📥 **Kuch alag se chahiye?**\n"
        f"Agar koi material na mile, toh niche diye gaye **Request Files** button ka use karke direct humse maang sakte hain!\n\n"
        f"🎯 *Padhte rahiye, badhte rahiye!*"
    )
    
    if is_edit:
        await message_obj.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    else:
        await message_obj.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def cmd_categories(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_subscribed(context.bot, update.effective_user.id): return
    await show_categories_menu(update.message, is_edit=False)

async def show_categories_menu(message_obj, is_edit=True):
    """Renders all categories dynamically."""
    categories = material_col.distinct("category", {"status": "live"})
    if not categories:
        keyboard = [[InlineKeyboardButton("🏠 Main Menu", callback_data="go_home")]]
        msg = "🗂️ Abhi tak koi category nahi banayi gayi hai."
        if is_edit: await message_obj.edit_text(msg, reply_markup=InlineKeyboardMarkup(keyboard))
        else: await message_obj.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard))
        return
    
    keyboard = [[InlineKeyboardButton(f"📂 {cat}", callback_data=f"vcat_{cat}")] for cat in categories]
    keyboard.append([InlineKeyboardButton("🏠 Main Menu", callback_data="go_home")])
    if is_edit: await message_obj.edit_text("📂 Niche di gayi categories me se chunein:", reply_markup=InlineKeyboardMarkup(keyboard))
    else: await message_obj.reply_text("📂 Niche di gayi categories me se chunein:", reply_markup=InlineKeyboardMarkup(keyboard))

# ==========================================
# SECTION 7: USER CONVERSATIONAL REQUEST SYSTEM
# ==========================================
async def request_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Initiates conversation flow or handles direct arguments for admin forwarding."""
    user_id = update.effective_user.id
    if not await is_subscribed(context.bot, user_id): return

    if len(context.args) < 1:
        user_states[user_id] = "waiting_for_request"
        await update.message.reply_text(
            "📝 **Aapko kaunse extra notes ya study material chahiye?**\n\n"
            "Kripya us book, subject ya notes ka naam niche type karke send karein. Aapki request seedhe Admin panel tak pahunchayi jayegi!",
            parse_mode='Markdown'
        )
        return
    
    file_request_name = " ".join(context.args)
    await process_and_send_request(update, context, user_id, file_request_name)

async def process_and_send_request(update, context, user_id, file_request_name):
    """Core request processing and dispatching engine to primary admin."""
    user = update.effective_user
    user_info = f"{user.first_name} (ID: `{user_id}` | Username: @{user.username or 'None'})"
    
    try:
        # Save request to database history
        requests_col.insert_one({
            "user_id": user_id,
            "file_name": file_request_name,
            "status": "pending"
        })

        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=f"🔔 **[NEW REQUEST RECEIVED]**\n\n👤 **From User:** {user_info}\n📂 **Requested Material:** {file_request_name}\n\n"
                 f"ℹ️ *Aap unhe directly provide kar sakte hain ya database me upload kar sakte hain.*",
            parse_mode='Markdown'
        )
        
        success_text = (
            "✅ **Aapki request safaltapoorvak Admin tak pahunch gayi hai!**\n\n"
            "Jaise hi yeh material humare paas available hoga, ise upload kar diya jayega. Tab tak aap baaki dashboard materials se padhai jari rakh sakte hain! 👍"
        )
        
        keyboard = [[InlineKeyboardButton("🔙 Back to Request Menu", callback_data="user_req_menu")]]
        
        if update.callback_query:
            await update.callback_query.message.reply_text(success_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
        else:
            await update.message.reply_text(success_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
        user_states.pop(user_id, None)
    except Exception as e:
        logger.error(f"Error in dispatching request to admin: {e}")
        if update.callback_query:
            await update.callback_query.message.reply_text("❌ Upsee! Request bhejte samay kuch dikkat aayi. Kripya baad me try karein.")
        else:
            await update.message.reply_text("❌ Upsee! Request bhejte samay kuch dikkat aayi. Kripya baad me try karein.")

# ==========================================
# SECTION 8: ADMINISTRATIVE MANAGEMENT (MULTI-USER SUPPORT)
# ==========================================
async def add_co_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Enables primary admin to authorize multiple contributors."""
    if update.effective_user.id != ADMIN_ID: return
    if not context.args:
        await update.message.reply_text("❌ Please provide a Telegram User ID.\nExample: `/addcoadmin 123456789`", parse_mode="Markdown")
        return
    try:
        co_id = int(context.args[0])
        if co_admins_col.find_one({"user_id": co_id}):
            await update.message.reply_text("⚠️ Yeh user pehle se hi Co-Admin list me shamil hai.")
            return
        co_admins_col.insert_one({"user_id": co_id})
        await update.message.reply_text(f"✅ User ID `{co_id}` ko safely **Co-Admin** bana diya gaya hai! Ab yeh bhi files upload kar sakte hain.", parse_mode="Markdown")
    except ValueError:
        await update.message.reply_text("❌ Invalid User ID. Kripya sirf digits ka istemal karein.")

async def remove_co_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Enables primary admin to revoke contributor access instantly."""
    if update.effective_user.id != ADMIN_ID: return
    if not context.args:
        await update.message.reply_text("❌ Please provide a Telegram User ID.\nExample: `/removecoadmin 123456789`", parse_mode="Markdown")
        return
    try:
        co_id = int(context.args[0])
        res = co_admins_col.delete_one({"user_id": co_id})
        if res.deleted_count > 0:
            await update.message.reply_text(f"✅ User ID `{co_id}` se Co-Admin permissions wapas le li gayi hain.")
        else:
            await update.message.reply_text("❌ Yeh User ID Co-Admin list me nahi mili.")
    except ValueError:
        await update.message.reply_text("❌ Invalid User ID format.")

async def list_co_admins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lists and provides inline control for authorized co-admins/contributors."""
    if update.effective_user.id != ADMIN_ID: return
    await show_co_admins_panel(update.message, is_edit=False)

async def show_co_admins_panel(message_obj, is_edit=True):
    co_list = list(co_admins_col.find({}))
    keyboard = []
    msg = "👑 **Co-Admin Management Panel:**\n\n"
    if not co_list:
        msg += "👥 Abhi tak koi Co-Admin nahi banaya gaya hai.\n👉 Naya co-admin jodne ke liye text field me unka User ID type karke send karein."
    else:
        msg += "Current Active Co-Admins (Click to remove):\n"
        for co in co_list:
            keyboard.append([InlineKeyboardButton(f"❌ Remove: {co['user_id']}", callback_data=f"remco_{co['user_id']}")])
    
    keyboard.append([InlineKeyboardButton("🏠 Admin Dashboard", callback_data="admin_home")])
    if is_edit:
        await message_obj.edit_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    else:
        await message_obj.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Renders administrative operations dashboard."""
    if not is_admin_or_co_admin(update.effective_user.id): return
    await show_admin_dashboard(update.message, update.effective_user.id, is_edit=False)

async def show_admin_dashboard(message_obj, user_id, is_edit=True):
    keyboard = []
    
    # Co-Admin Only Sees Content Management
    if user_id != ADMIN_ID:
        keyboard.append([InlineKeyboardButton("📂 Manage All Content", callback_data="manage_files")])
        keyboard.append([InlineKeyboardButton("📊 Bot Stats", callback_data="bot_stats")])
        text = "⚙️ *Contributor Control Panel:*"
    else:
        # Super Admin Controls Everything
        keyboard.append([InlineKeyboardButton("📂 Manage Content & Categories", callback_data="manage_files")])
        keyboard.append([InlineKeyboardButton("👥 Manage Co-Admins", callback_data="admin_coadmins")])
        keyboard.append([InlineKeyboardButton("🛠️ Manage Dynamic Buttons", callback_data="manage_dyn_buttons")])
        keyboard.append([InlineKeyboardButton("📊 Bot Stats", callback_data="bot_stats")])
        text = "👑 *Main Super Admin Panel:*"

    if is_edit:
        await message_obj.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    else:
        await message_obj.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def manage_files_list(query):
    """Lists files inside admin interface."""
    files = list(material_col.find({}))
    keyboard = []
    
    if query.from_user.id == ADMIN_ID:
        keyboard.append([InlineKeyboardButton("➕ Add New Category", callback_data="add_new_category")])
        
    if not files:
        keyboard.append([InlineKeyboardButton("🏠 Back to Admin", callback_data="admin_home")])
        await query.edit_message_text("🗂️ Database khali hai.", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    for f in files:
        status_icon = "🟢" if f.get("status", "live") == "live" else "🔴"
        keyboard.append([InlineKeyboardButton(f"{status_icon} [{f['category']}-{f.get('subject','General')}] {f['file_name']}", callback_data=f"editfile_{f['_id']}")])
    keyboard.append([InlineKeyboardButton("🏠 Back to Admin", callback_data="admin_home")])
    await query.edit_message_text("📂 *Manage Content (Click to edit):*", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def edit_file_options(query, file_id):
    """Interactive individual settings configuration panel for files."""
    file = material_col.find_one({"_id": ObjectId(file_id)})
    if not file: return
    current_status = file.get("status", "live")
    toggle_text = "🔴 Hide From Users" if current_status == "live" else "🟢 Make It Live"
    
    keyboard = [
        [InlineKeyboardButton(toggle_text, callback_data=f"toggle_{file_id}")]
    ]
    
    # Restrict Advanced actions to Super Admin Only
    if query.from_user.id == ADMIN_ID:
        keyboard.append([InlineKeyboardButton("📦 Transfer File", callback_data=f"move_{file_id}"), InlineKeyboardButton("👯 Copy File", callback_data=f"copy_{file_id}")])
        keyboard.append([InlineKeyboardButton("🗑️ Delete Permanently", callback_data=f"del_{file_id}")])
        
    keyboard.append([InlineKeyboardButton("🔙 Back to List", callback_data="manage_files")])
    await query.edit_message_text(f"📝 *Managing:* `{file['file_name']}`\n📂 Cat: `{file['category']}` | 📚 Sub: `{file.get('subject','General')}`\n⚡ Status: `{current_status.upper()}`", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

# ==========================================
# SECTION 9: INLINE CALLBACK ENGINE
# ==========================================
async def button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Central processing module for high-speed callback handling."""
    query = update.callback_query
    user_id = query.from_user.id
    
    await query.answer()

    try:
        if query.data == "verify":
            if await is_subscribed(context.bot, user_id):
                try:
                    await query.message.delete()
                except Exception: pass
                await show_main_menu(query.message, query.from_user.first_name, is_edit=False)

        elif query.data == "go_home":
            await show_main_menu(query.message, query.from_user.first_name, is_edit=True)

        # NEW SUB-MENU FOR USER REQUESTS
        elif query.data == "user_req_menu":
            keyboard = [
                [InlineKeyboardButton("🆕 Request New File", callback_data="user_req_file")],
                [InlineKeyboardButton("📂 View Requested Files", callback_data="view_my_requests")],
                [InlineKeyboardButton("🔙 Back to Dashboard", callback_data="go_home")]
            ]
            text = (
                "📥 **File Request Desk**\n\n"
                "Aapka swagat hai! Agar aapko dashboard me koi material nahi mila, toh aap direct request daal sakte hain:\n\n"
                "• **Request New File:** Kisi bhi naye study material ki mang karein.\n"
                "• **View Requested Files:** Apni abhi tak ki bheji gayi requests ka record check karein."
            )
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

        elif query.data == "user_req_file":
            user_states[user_id] = "waiting_for_request"
            await query.message.reply_text(
                "📝 **Aapko kaunse extra notes ya study material chahiye?**\n\n"
                "Kripya us book, subject ya notes ka naam niche type karke send karein. Aapki request seedhe Admin panel tak pahunchayi jayegi!",
                parse_mode='Markdown'
            )

        # NEW VIEW REQUEST HISTORY FEATURE
        elif query.data == "view_my_requests":
            user_reqs = list(requests_col.find({"user_id": user_id}))
            keyboard = [[InlineKeyboardButton("🔙 Back to Request Menu", callback_data="user_req_menu")]]
            
            if not user_reqs:
                text = "📂 **Aapne abhi tak koi extra file request nahi ki hai!**"
            else:
                text = "📋 **Aapki Requested Files ki list:**\n\n"
                for index, req in enumerate(user_reqs, 1):
                    status_emoji = "⏳ Pending" if req.get("status") == "pending" else "✅ Completed"
                    text += f"{index}. 📂 **{req['file_name']}**\n⚡ Status: `{status_emoji}`\n\n"
                    
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

        elif query.data == "more_combined":
            # Highly Custom dynamic button listing for links managed by Super Admin
            buttons = list(dynamic_buttons_col.find({}))
            keyboard = []
            for btn in buttons:
                keyboard.append([InlineKeyboardButton(f"{btn['emoji']} {btn['name']}", url=btn['url'])])
            keyboard.append([InlineKeyboardButton("🔙 Back to Menu", callback_data="go_home")])
            await query.edit_message_text(
                "✨ **Explore More Channels & Smart Bots:** ✨\n\n"
                "Niche diye gaye verified links ke through extra study content, automated groups aur extra tools explore karein! 👇",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown"
            )

        elif query.data == "admin_home" and is_admin_or_co_admin(user_id):
            admin_states.pop(user_id, None)
            await show_admin_dashboard(query.message, user_id, is_edit=True)

        elif query.data == "admin_coadmins" and user_id == ADMIN_ID:
            await show_co_admins_panel(query.message, is_edit=True)

        elif query.data.startswith("remco_") and user_id == ADMIN_ID:
            co_to_rem = int(query.data.replace("remco_", ""))
            co_admins_col.delete_one({"user_id": co_to_rem})
            await show_co_admins_panel(query.message, is_edit=True)

        elif query.data == "add_new_category" and user_id == ADMIN_ID:
            admin_states[user_id] = {"action": "waiting_for_cat_name"}
            await query.edit_message_text("📝 **Nayi category ka naam type karke bhejein:**", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data="manage_files")]]))

        elif query.data == "manage_dyn_buttons" and user_id == ADMIN_ID:
            buttons = list(dynamic_buttons_col.find({}))
            keyboard = [[InlineKeyboardButton("➕ Add New Button", callback_data="add_dyn_btn")]]
            for btn in buttons:
                keyboard.append([InlineKeyboardButton(f"🗑️ Delete: {btn['name']}", callback_data=f"deldbtn_{btn['_id']}")])
            keyboard.append([InlineKeyboardButton("🏠 Admin Dashboard", callback_data="admin_home")])
            await query.edit_message_text("🛠️ **Dynamic Buttons Configuration Panel:**", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

        elif query.data == "add_dyn_btn" and user_id == ADMIN_ID:
            admin_states[user_id] = {"action": "waiting_btn_name"}
            await query.edit_message_text("📛 **Naye button ka Text (Naam) enter karein:**", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data="manage_dyn_buttons")]]))

        elif query.data.startswith("deldbtn_") and user_id == ADMIN_ID:
            bid = query.data.replace("deldbtn_", "")
            dynamic_buttons_col.delete_one({"_id": ObjectId(bid)})
            # Re-render dynamic buttons panel
            buttons = list(dynamic_buttons_col.find({}))
            keyboard = [[InlineKeyboardButton("➕ Add New Button", callback_data="add_dyn_btn")]]
            for btn in buttons:
                keyboard.append([InlineKeyboardButton(f"🗑️ Delete: {btn['name']}", callback_data=f"deldbtn_{btn['_id']}")])
            keyboard.append([InlineKeyboardButton("🏠 Admin Dashboard", callback_data="admin_home")])
            await query.edit_message_text("🛠️ **Dynamic Buttons Configuration Panel:**", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

        elif query.data == "manage_files" and is_admin_or_co_admin(user_id):
            await manage_files_list(query)

        elif query.data.startswith("editfile_") and is_admin_or_co_admin(user_id):
            fid = query.data.replace("editfile_", "")
            await edit_file_options(query, fid)

        elif query.data.startswith("toggle_") and is_admin_or_co_admin(user_id):
            fid = query.data.replace("toggle_", "")
            f = material_col.find_one({"_id": ObjectId(fid)})
            if f:
                nst = "hidden" if f.get("status", "live") == "live" else "live"
                material_col.update_one({"_id": ObjectId(fid)}, {"$set": {"status": nst}})
                await edit_file_options(query, fid)

        elif query.data.startswith("del_") and user_id == ADMIN_ID:
            fid = query.data.replace("del_", "")
            material_col.delete_one({"_id": ObjectId(fid)})
            await manage_files_list(query)

        elif (query.data.startswith("move_") or query.data.startswith("copy_")) and user_id == ADMIN_ID:
            mode, fid = query.data.split("_", 1)
            admin_states[user_id] = {"action": mode, "fid": fid}
            
            # Fetch global categories to populate dynamically
            categories = material_col.distinct("category")
            if not categories: categories = ["SSC", "UPSC", "Banking", "NEET_JEE"]
            
            keyboard = []
            for i in range(0, len(categories), 2):
                row = [InlineKeyboardButton(f"📂 {categories[i]}", callback_data=f"tcat_{categories[i]}")]
                if i+1 < len(categories):
                    row.append(InlineKeyboardButton(f"📂 {categories[i+1]}", callback_data=f"tcat_{categories[i+1]}"))
                keyboard.append(row)
                
            await query.edit_message_text("Target **Main Category** select kijiye:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

        elif query.data.startswith("tcat_") and user_id == ADMIN_ID:
            tcat = query.data.replace("tcat_", "")
            if user_id in admin_states:
                admin_states[user_id]["target_cat"] = tcat
                keyboard = [
                    [InlineKeyboardButton("📐 Maths", callback_data="tsub_Maths"), InlineKeyboardButton("🌍 GK/GS", callback_data="tsub_GK")],
                    [InlineKeyboardButton("🧠 Reasoning", callback_data="tsub_Reasoning"), InlineKeyboardButton("🔤 English", callback_data="tsub_English")]
                ]
                await query.edit_message_text(f"Category *{tcat}* done. Target **Subject** chunein:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

        elif query.data.startswith("tsub_") and user_id == ADMIN_ID:
            tsub = query.data.replace("tsub_", "")
            state = admin_states.get(user_id)
            if state:
                orig_file = material_col.find_one({"_id": ObjectId(state["fid"])})
                if orig_file:
                    if state["action"] == "move":
                        material_col.update_one({"_id": ObjectId(state["fid"])}, {"$set": {"category": state["target_cat"], "subject": tsub}})
                    elif state["action"] == "copy":
                        new_doc = orig_file.copy()
                        del new_doc["_id"]
                        new_doc["category"] = state["target_cat"]
                        new_doc["subject"] = tsub
                        material_col.insert_one(new_doc)
                admin_states.pop(user_id, None)
            await manage_files_list(query)

        elif query.data == "bot_stats":
            total_users = users_col.count_documents({})
            total_files = material_col.count_documents({})
            back = "admin_home" if is_admin_or_co_admin(user_id) else "go_home"
            await query.edit_message_text(f"📊 *Bot Status:*\n\n👥 Users: {total_users}\n📂 Files: {total_files}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Main Menu", callback_data=back)]]), parse_mode="Markdown")

        # CLEAN PROFILE DASHBOARD (WITHOUT FLOODING STUFF)
        elif query.data == "my_profile":
            keyboard = [
                [InlineKeyboardButton("📥 View Downloaded Files", callback_data="view_my_downloads")],
                [InlineKeyboardButton("🏠 Main Menu", callback_data="go_home")]
            ]
            text = (
                f"👤 **Your Personal Profile Profile**\n\n"
                f"📝 **Name:** {query.from_user.first_name}\n"
                f"🆔 **Telegram ID:** `{user_id}`\n"
                f"🌐 **Username:** @{query.from_user.username or 'None'}\n\n"
                f"💡 *Apni sabhi purani download ki hui files dekhne ke liye niche diye gaye button par click karein!*"
            )
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

        # HIDDEN DOWNLOAD LIST POPUP (TRIGGERED VIA TAP)
        elif query.data == "view_my_downloads":
            u_doc = users_col.find_one({"user_id": user_id})
            downloaded = u_doc.get("downloaded_files", []) if u_doc else []
            
            keyboard = []
            if not downloaded:
                text = "📥 **Aapne abhi tak bot se koi bhi file download nahi ki hai!**\n\nDashboard se padhai suru karein aur material download karein."
            else:
                text = "📂 **Aapki abhi tak download ki gayi saari Files:**\n\n_Niche diye inline buttons par tap karke aap unhe fir se fetch kar sakte hain:_"
                for file_info in downloaded:
                    keyboard.append([InlineKeyboardButton(f"📄 {file_info['file_name']}", callback_data=f"sfile_{file_info['file_id']}")])
            
            keyboard.append([InlineKeyboardButton("🔙 Back to Profile", callback_data="my_profile")])
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

        elif query.data == "view_cats":
            await show_categories_menu(query.message, is_edit=True)

        elif query.data.startswith("vcat_"):
            cat_name = query.data.replace("vcat_", "")
            subjects = material_col.distinct("subject", {"category": cat_name, "status": "live"})
            if not subjects:
                await query.edit_message_text(f"❌ {cat_name} me koi live subjects nahi hain.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="view_cats")]]))
                return
            keyboard = [[InlineKeyboardButton(f"📚 {sub}", callback_data=f"vsub_{cat_name}__{sub}")] for sub in subjects]
            keyboard.append([InlineKeyboardButton("🔙 Back to Categories", callback_data="view_cats")])
            await query.edit_message_text(f"📂 *Category: {cat_name}*\nSubject chunein:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

        elif query.data.startswith("vsub_"):
            payload = query.data.replace("vsub_", "")
            cat_name, sub_name = payload.split("__")
            materials = list(material_col.find({"category": cat_name, "subject": sub_name, "status": "live"}))
            if not materials:
                await query.edit_message_text("❌ Khali hai.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data=f"vcat_{cat_name}")]]))
                return
            keyboard = [[InlineKeyboardButton(f"📥 {mat['file_name']}", callback_data=f"sfile_{mat['_id']}")] for mat in materials]
            keyboard.append([InlineKeyboardButton("🔙 Back to Subjects", callback_data=f"vcat_{cat_name}")])
            await query.edit_message_text(f"📚 *{cat_name} ➡️ {sub_name}*:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

        elif query.data.startswith("sfile_"):
            fid = query.data.replace("sfile_", "")
            file_data = material_col.find_one({"_id": ObjectId(fid)})
            if file_data and file_data.get("status", "live") == "live":
                await send_material_file(context.bot, user_id, file_data)

        elif query.data.startswith("acat_") and is_admin_or_co_admin(user_id):
            category = query.data.replace("acat_", "")
            if user_id in admin_states:
                admin_states[user_id]["category"] = category
                keyboard = [
                    [InlineKeyboardButton("📐 Maths", callback_data="asub_Maths"), InlineKeyboardButton("🌍 GK/GS", callback_data="asub_GK")],
                    [InlineKeyboardButton("🧠 Reasoning", callback_data="asub_Reasoning"), InlineKeyboardButton("🔤 English", callback_data="asub_English")]
                ]
                await query.edit_message_text(f"Category *{category}* done. Select **Subject**:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

        elif query.data.startswith("asub_") and is_admin_or_co_admin(user_id):
            subject = query.data.replace("asub_", "")
            file_data = admin_states.get(user_id)
            if file_data:
                file_data["subject"] = subject
                file_data["status"] = "live"
                material_col.insert_one(file_data)
                await query.edit_message_text("✅ *Successfully Saved!*", parse_mode="Markdown")
                admin_states.pop(user_id, None)
                
    except Exception as e:
        logger.error(f"Error handling button click callback: {e}", exc_info=True)

# ==========================================
# SECTION 10: COMMUNICATIONS & SYSTEM LOGIC
# ==========================================
async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sends a broadcast message to all users (Strictly Main Admin only)."""
    if update.effective_user.id != ADMIN_ID: return
    if not context.args: return
    broadcast_text = update.message.text.split(None, 1)[1]
    all_users = users_col.find({})
    for user in all_users:
        try:
            await context.bot.send_message(chat_id=user["user_id"], text=broadcast_text)
            await asyncio.sleep(0.05)
        except Exception: pass
    await update.message.reply_text("📢 Broadcast Done!")

async def handle_admin_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Intercepts media documents specifically for authorized admin/co-admin upload streams."""
    user_id = update.effective_user.id
    if not is_admin_or_co_admin(user_id): return
    
    message = update.message
    file_id, file_name, file_type = None, "Unnamed", None
    if message.document: 
        file_id, file_name, file_type = message.document.file_id, message.document.file_name, "document"
    elif message.photo: 
        file_id, file_name, file_type = message.photo[-1].file_id, message.caption or "Photo Note", "photo"
    elif message.video: 
        file_id, file_name, file_type = message.video.file_id, message.video.file_name or message.caption or "Video Note", "video"

    if file_id:
        admin_states[user_id] = {"file_id": file_id, "file_name": file_name, "file_type": file_type}
        
        # Pull global live categories dynamically
        categories = material_col.distinct("category")
        if not categories: categories = ["SSC", "UPSC", "Banking", "NEET_JEE"]
        
        keyboard = []
        for i in range(0, len(categories), 2):
            row = [InlineKeyboardButton(f"📂 {categories[i]}", callback_data=f"acat_{categories[i]}")]
            if i+1 < len(categories):
                row.append(InlineKeyboardButton(f"📂 {categories[i+1]}", callback_data=f"acat_{categories[i+1]}"))
            keyboard.append(row)
            
        await message.reply_text("📥 *Material mila!* Iski *Main Category* chunein:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def handle_user_incoming_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles incoming text queries; captures dynamic administrative text parameters safely."""
    user_id = update.effective_user.id
    incoming_text = update.message.text
    if incoming_text.startswith("/"): return 

    # Administrative Text Capture Routing
    if is_admin_or_co_admin(user_id) and user_id in admin_states:
        state = admin_states[user_id]
        
        if state.get("action") == "waiting_for_cat_name" and user_id == ADMIN_ID:
            # Seed the database with a dummy live content object to reserve this category instantly
            dummy_data = {
                "category": incoming_text,
                "subject": "General",
                "file_name": "Category Initialized",
                "file_id": "",
                "file_type": "document",
                "status": "hidden"
            }
            material_col.insert_one(dummy_data)
            admin_states.pop(user_id, None)
            await update.message.reply_text(f"📂 Nayi category **'{incoming_text}'** successfully initialize ho gayi hai!")
            return

        elif state.get("action") == "waiting_btn_name" and user_id == ADMIN_ID:
            state["name"] = incoming_text
            state["action"] = "waiting_btn_url"
            await update.message.reply_text(f"🔗 Button text registered as *{incoming_text}*.\n👉 Ab is space down me redirection target **URL (Link)** text paste karke send karein:")
            return

        elif state.get("action") == "waiting_btn_url" and user_id == ADMIN_ID:
            if not incoming_text.startswith("http://") and not incoming_text.startswith("https://"):
                await update.message.reply_text("❌ Please enter a valid URL scheme starting with http:// or https://")
                return
            state["url"] = incoming_text
            state["action"] = "waiting_btn_emoji"
            await update.message.reply_text("🎭 **Is button ke liye koi ek Single Emoji send karein:**\n(Example: 📢, 🤖, 🧪)")
            return

        elif state.get("action") == "waiting_btn_emoji" and user_id == ADMIN_ID:
            emoji = incoming_text.strip()
            new_btn = {
                "name": state["name"],
                "url": state["url"],
                "emoji": emoji
            }
            dynamic_buttons_col.insert_one(new_btn)
            admin_states.pop(user_id, None)
            await update.message.reply_text("✅ **Dynamic Multi-Channel Link Button successfully saved!**\nAb yeh user interface panel me automatically show hone lagega.")
            return

    # Treat as structural text addition to Co-Admin list if main admin uses dashboard scope
    if user_id == ADMIN_ID and incoming_text.isdigit():
        co_id = int(incoming_text)
        if not co_admins_col.find_one({"user_id": co_id}):
            co_admins_col.insert_one({"user_id": co_id})
            await update.message.reply_text(f"✅ User ID `{co_id}` saved as Co-Admin!")
            await show_co_admins_panel(update.message, is_edit=False)
        else:
            await update.message.reply_text("⚠️ Yeh ID pehle se hi Co-Admin list me active hai.")
        return

    # Standard Subscriber Handling Verification Barrier
    if not await is_subscribed(context.bot, user_id): return

    if user_states.get(user_id) == "waiting_for_request":
        await process_and_send_request(update, context, user_id, incoming_text)
        return

    # Standard Material Search Query Processing
    results = list(material_col.find({"file_name": {"$regex": incoming_text, "$options": "i"}, "status": "live"}))
    count = len(results)
    
    if count == 0:
        await update.message.reply_text(
            f"🔍 '{incoming_text}' ke liye abhi koi live material nahi mila.\n\n"
            f"💡 Agar aapko yeh material urgently chahiye, toh aap `/request {incoming_text}` likh kar direct humse maang sakte hain!"
        )
    else:
        text = f"🔍 *Search Results ({count}):*\n\n"
        for mat in results:
            text += f"🔹 /file_{mat['_id']} - {mat['file_name']} ({mat.get('subject','')})\n"
        await update.message.reply_text(text, parse_mode="Markdown")

async def handle_file_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles direct file links clicked from search results."""
    user_id = update.effective_user.id
    if not await is_subscribed(context.bot, user_id): return
    
    msg_text = update.message.text
    if msg_text.startswith("/file_"):
        file_id_str = msg_text.replace("/file_", "")
        try:
            file_data = material_col.find_one({"_id": ObjectId(file_id_str)})
            if file_data and file_data.get("status", "live") == "live":
                await send_material_file(context.bot, user_id, file_data)
            else:
                await update.message.reply_text("❌ Yeh file ab available nahi hai ya hide kar di gayi hai.")
        except Exception as e:
            logger.error(f"Error handling direct file link: {e}")
            await update.message.reply_text("❌ Invalid File ID.")

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Logs unexpected exceptions."""
    logger.error("Exception while handling an update:", exc_info=context.error)

# ==========================================
# SECTION 11: MAIN APPLICATION INITIALIZER
# ==========================================
def main():
    """Starts the bot application and registers handlers safely."""
    app = Application.builder().token(BOT_TOKEN).post_init(setup_menus).build()

    # User & Core Control Commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("home", start))
    app.add_handler(CommandHandler("categories", cmd_categories))
    app.add_handler(CommandHandler("request", request_file))
    
    # Administrative Exclusive Management Commands
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(CommandHandler("broadcast", broadcast_command))
    app.add_handler(CommandHandler("addcoadmin", add_co_admin))
    app.add_handler(CommandHandler("removecoadmin", remove_co_admin))
    app.add_handler(CommandHandler("coadmins", list_co_admins))
    
    # Callback Query Handler
    app.add_handler(CallbackQueryHandler(button_click))
    
    # Message Handlers mapped accurately via Regex/Filters
    app.add_handler(MessageHandler(filters.Regex(r'^/file_[a-fA-F0-9]{24}$'), handle_file_link))
    app.add_handler(MessageHandler(filters.Document.ALL | filters.PHOTO | filters.VIDEO, handle_admin_upload))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_user_incoming_messages))

    # Error Handler
    app.add_error_handler(error_handler)
    
    # Start Polling
    app.run_polling()

if __name__ == '__main__':
    main()
