"""
UI Dashboard Template for STUDIO KHOIRUL (Aiogram 3.x)
Versi: PREMIUM AESTHETIC v3.3 (Super Bridge & Categories)
Fix: Seamless Backend Integration, No ImportError Crashes.
"""

import asyncio
from aiogram import Router, F
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, Message
from aiogram.exceptions import TelegramBadRequest
from config.config import Config

# Inisialisasi Router untuk UI
ui_router = Router(name="ui_dashboard")

# ==========================================
# 1. CONSTANTS & VISUAL THEMES
# ==========================================

BORDER_PREMIUM = "━━━━━━━━━━━━━━━━━━━"
BORDER_SUBTLE = "─────────────────────"
DIVIDER = "┃"
TOP_LEFT, TOP_RIGHT = "╭", "╮"
BOTTOM_LEFT, BOTTOM_RIGHT = "╰", "╯"
H_LINE, V_LINE = "─", "│"

def get_status_bar(current: int, max_val: int, width: int = 12) -> str:
    filled = int((current / max_val) * width)
    empty = width - filled
    return f"[{'▓' * filled}{'░' * empty}]"

# ==========================================
# 2. DASHBOARD TEXTS
# ==========================================

MAIN_DASHBOARD_TEXT = """
<b>╭─ STUDIO KHOIRUL ─╮</b>

<b>👋 Welcome back, {name}</b> <code>VIP PRO</code>

<b>✨ System Status</b>
  🟢 Core Engine: <code>Optimal</code>
  ⚡ GPU Pipeline: <code>Ready</code>  
  💾 Storage: {storage_bar} <code>{storage}%</code>
  🚀 Queue: <code>0 / 3 Tasks</code>

<b>╰─────────────────╯</b>

<i>Pilih workspace Anda di bawah 👇</i>
"""

WELCOME_FIRST_TIME = """
<b>╔═══════════════════╗</b>
<b>║  STUDIO KHOIRUL   ║</b>
<b>╚═══════════════════╝</b>

🎬 <b>Platform otomasi produksi video gaming</b>

<b>👉 Mari kita mulai!</b>
"""

def create_category_header(icon: str, title: str, desc: str, emoji_accent: str = "✨") -> str:
    return f"""
<b>{TOP_LEFT}{H_LINE*18}{TOP_RIGHT}</b>
<b>{DIVIDER} {icon} {title}</b>
<b>{BOTTOM_LEFT}{H_LINE*18}{BOTTOM_RIGHT}</b>

{desc}

<b>{BORDER_SUBTLE}</b>
<i>{emoji_accent} Pilih fitur yang ingin digunakan:</i>
"""

# ==========================================
# 3. HELPER FUNCTIONS
# ==========================================

async def safe_edit_message(message: Message, text: str, reply_markup: InlineKeyboardMarkup = None) -> bool:
    try:
        await message.edit_text(text=text, reply_markup=reply_markup, parse_mode="HTML")
        return True
    except TelegramBadRequest:
        return False

def check_is_admin(user_id: int) -> bool:
    return user_id in Config.SUDO_USERS

def get_back_cancel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="↩️ Kembali", callback_data="menu_main"),
         InlineKeyboardButton(text="✕ Tutup", callback_data="action_cancel")]
    ])

def get_storage_status() -> tuple:
    usage = 45
    return get_status_bar(usage, 100, 10), usage

def is_user_in_waiter(chat_id: int, user_id: int) -> bool:
    """Fungsi pintar untuk mengecek apakah user sedang dalam antrean Waiter."""
    try:
        from bot.shared import USER_WAITERS
        if user_id in USER_WAITERS: return True
    except ImportError: pass
    
    try:
        from bot.shared import _waiters
        if (chat_id, user_id) in _waiters: return True
    except ImportError: pass
        
    return False

# ==========================================
# 4. KEYBOARD BUILDERS
# ==========================================

def get_main_menu_kb(is_admin: bool = False) -> InlineKeyboardMarkup:
    kb = [
        [InlineKeyboardButton(text="🎬 Studio Produksi", callback_data="menu_studio"),
         InlineKeyboardButton(text="✂️ Video Editing", callback_data="menu_vid_edit")],
        [InlineKeyboardButton(text="🎮 Asset Manager", callback_data="menu_assets"),
         InlineKeyboardButton(text="📥 Cloud & Download", callback_data="menu_downloader")],
        [InlineKeyboardButton(text="⚙️ Pengaturan", callback_data="settings"), 
         InlineKeyboardButton(text="👑 VIP Membership", callback_data="menu_vip")],
    ]
    if is_admin:
        kb.append([InlineKeyboardButton(text="🔧 Admin Control", callback_data="menu_admin")])
    kb.append([InlineKeyboardButton(text="❌ Tutup Dashboard", callback_data="action_cancel")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

def get_studio_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎬 Film Recap", callback_data="cmd_recap"), InlineKeyboardButton(text="🎥 Auto Clip", callback_data="cmd_clip")],
        [InlineKeyboardButton(text="🏆 Top Tier", callback_data="cmd_toptier"), InlineKeyboardButton(text="📊 Verdict", callback_data="cmd_verdict")],
        [InlineKeyboardButton(text="📖 Lore Analysis", callback_data="cmd_lore"), InlineKeyboardButton(text="🎯 Radar", callback_data="cmd_radar")],
        [InlineKeyboardButton(text="⚡ Patch Notes", callback_data="cmd_patch"), InlineKeyboardButton(text="📚 Archives", callback_data="cmd_archives")],
        [InlineKeyboardButton(text="▶️ YouTube Upload", callback_data="cmd_ytupload")],
        [InlineKeyboardButton(text="↩️ Kembali", callback_data="menu_main")]
    ])

def get_editor_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        # 🌟 ENGINE UTAMA (Paling Power Full)
        [InlineKeyboardButton(text="🚀 Encode Video", callback_data="cmd_encode")],
        
        # 📦 FORMAT & UKURAN (Dasar)
        [InlineKeyboardButton(text="🗜️ Compress", callback_data="cmd_compress"), 
         InlineKeyboardButton(text="🔄 Convert", callback_data="cmd_convert"), 
         InlineKeyboardButton(text="🔗 Merge", callback_data="cmd_merge")],
         
        # ✂️ PEMOTONGAN DURASI (Waktu)
        [InlineKeyboardButton(text="🎞️ Trim", callback_data="cmd_trim"), 
         InlineKeyboardButton(text="🔪 Cut", callback_data="cmd_cut"), 
         InlineKeyboardButton(text="✂️ Split", callback_data="cmd_split")],
         
        # 📐 MANIPULASI FRAME (Visual Geometri)
        [InlineKeyboardButton(text="📐 Crop", callback_data="cmd_crop"), 
         InlineKeyboardButton(text="🎬 Autocrop", callback_data="cmd_autocrop"), 
         InlineKeyboardButton(text="🔃 Rotate", callback_data="cmd_rotate")],
         
        # 📝 SUBTITLE & MUXING (Penggabungan Teks)
        [InlineKeyboardButton(text="📌 Hardmux", callback_data="cmd_hardmux"), 
         InlineKeyboardButton(text="📝 Softmux", callback_data="cmd_softmux"), 
         InlineKeyboardButton(text="♻️ Remux", callback_data="cmd_softremux")],
         
        # 🎛️ MANIPULASI TRACK & DATA (Sistem Dalam)
        [InlineKeyboardButton(text="📁 Extension", callback_data="cmd_extension"),
         InlineKeyboardButton(text="🎵 Extract Audio", callback_data="cmd_extract")],
        [InlineKeyboardButton(text="🔀 Change Index", callback_data="cmd_changeindex"),
         InlineKeyboardButton(text="🏷️ Metadata", callback_data="cmd_changemetadata")],
         
        # 📸 ASET & PREVIEW VISUAL (Tambahan)
        [InlineKeyboardButton(text="©️ Watermark", callback_data="cmd_watermark"), 
         InlineKeyboardButton(text="📸 Screenshot", callback_data="cmd_genss"), 
         InlineKeyboardButton(text="🎞️ Sample", callback_data="cmd_gensample")],
         
        # ℹ️ INFORMASI & NAVIGASI
        [InlineKeyboardButton(text="ℹ️ MediaInfo", callback_data="cmd_mediainfo"),
         InlineKeyboardButton(text="↩️ Kembali", callback_data="menu_main")]
    ])

def get_assets_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Add Gameplay", callback_data="cmd_addgameplay"), InlineKeyboardButton(text="📋 List Gameplay", callback_data="cmd_listgameplay")],
        [InlineKeyboardButton(text="🗑️ Delete Gameplay", callback_data="cmd_deletegameplay"), InlineKeyboardButton(text="🔊 Add SFX", callback_data="cmd_addsfx")],
        [InlineKeyboardButton(text="↩️ Kembali", callback_data="menu_main")]
    ])

def get_downloader_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📥 Leech", callback_data="cmd_leech"), InlineKeyboardButton(text="☁️ Mirror Upload", callback_data="cmd_mirror")],
        [InlineKeyboardButton(text="↩️ Kembali", callback_data="menu_main")]
    ])

def get_vip_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👑 Check VIP Status", callback_data="cmd_myvip")],
        [InlineKeyboardButton(text="💳 Verify Trakteer", callback_data="cmd_verify")],
        [InlineKeyboardButton(text="ℹ️ About VIP", callback_data="cmd_vip_info")],
        [InlineKeyboardButton(text="↩️ Kembali", callback_data="menu_main")]
    ])

def get_admin_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        # 🖥️ SERVER & SYSTEM
        [InlineKeyboardButton(text="📊 Status Tasks", callback_data="cmd_status"), 
         InlineKeyboardButton(text="🚀 Speedtest", callback_data="cmd_speedtest")],
        [InlineKeyboardButton(text="⏱️ Uptime", callback_data="cmd_time"), 
         InlineKeyboardButton(text="📈 Server Stats", callback_data="cmd_stats")],
        [InlineKeyboardButton(text="📜 View Logs", callback_data="cmd_log"), 
         InlineKeyboardButton(text="📁 Download Logs", callback_data="cmd_logs")],
        
        # 🛠️ DATABASE & CONFIG
        [InlineKeyboardButton(text="🧹 Clean Server", callback_data="cmd_renew"), 
         InlineKeyboardButton(text="💥 Reset DB", callback_data="cmd_resetdb")],
        [InlineKeyboardButton(text="🔄 Change Config", callback_data="cmd_changeconfig"),
         InlineKeyboardButton(text="🗑️ Clear Configs", callback_data="cmd_clearconfigs")],
         
        # 👮 SUDO MANAGEMENT
        [InlineKeyboardButton(text="👮 Check Sudoers", callback_data="cmd_checksudo")],
        [InlineKeyboardButton(text="➕ Add Sudo", callback_data="cmd_addsudo"),
         InlineKeyboardButton(text="➖ Del Sudo", callback_data="cmd_delsudo")],
         
        # 👑 VIP MANAGEMENT
        [InlineKeyboardButton(text="👑 View VIP List", callback_data="cmd_view_vip")],
        [InlineKeyboardButton(text="➕ Add VIP", callback_data="cmd_add_vip"),
         InlineKeyboardButton(text="➖ Delete VIP", callback_data="cmd_delete_vip")],

        # 🛑 SYSTEM CONTROL
        [InlineKeyboardButton(text="🔄 Restart Bot", callback_data="cmd_restart")],
        [InlineKeyboardButton(text="↩️ Kembali ke Menu", callback_data="menu_main")]
    ])

# ==========================================
# 5. NAVIGATION HANDLERS
# ==========================================

@ui_router.callback_query(F.data == "menu_main")
async def nav_main(callback: CallbackQuery):
    is_admin = check_is_admin(callback.from_user.id)
    bar, pct = get_storage_status()
    await safe_edit_message(callback.message, MAIN_DASHBOARD_TEXT.format(name=callback.from_user.first_name, storage_bar=bar, storage=pct), get_main_menu_kb(is_admin))
    await callback.answer()

@ui_router.callback_query(F.data == "menu_studio")
async def nav_studio(callback: CallbackQuery):
    await safe_edit_message(callback.message, create_category_header("🎬", "STUDIO PRODUKSI", "Produksi video otomatis dengan AI & Script", "📺"), get_studio_kb())
    await callback.answer()

@ui_router.callback_query(F.data == "menu_vid_edit")
async def nav_video_edit(callback: CallbackQuery):
    await safe_edit_message(callback.message, create_category_header("✂️", "VIDEO EDITING", "Suite editing profesional dengan berbagai tools", "⚙️"), get_editor_kb())
    await callback.answer()

@ui_router.callback_query(F.data == "menu_assets")
async def nav_assets(callback: CallbackQuery):
    await safe_edit_message(callback.message, create_category_header("🎮", "ASSET MANAGER", "Kelola video gameplay & efek suara custom", "🎯"), get_assets_kb())
    await callback.answer()

@ui_router.callback_query(F.data == "menu_downloader")
async def nav_downloader(callback: CallbackQuery):
    await safe_edit_message(callback.message, create_category_header("📥", "CLOUD & DOWNLOAD", "Download file ke Telegram atau Cloud Storage", "💾"), get_downloader_kb())
    await callback.answer()

@ui_router.callback_query(F.data == "menu_vip")
async def nav_vip(callback: CallbackQuery):
    await safe_edit_message(callback.message, create_category_header("👑", "VIP MEMBERSHIP", "Akses fitur premium dan priority queue", "✨"), get_vip_kb())
    await callback.answer()

@ui_router.callback_query(F.data == "menu_admin")
async def nav_admin(callback: CallbackQuery):
    if not check_is_admin(callback.from_user.id): return await callback.answer("⛔ Access Denied!", show_alert=True)
    await safe_edit_message(callback.message, create_category_header("🔧", "ADMIN CONTROL", "Kelola server, antrean, dan database", "⚙️"), get_admin_kb())
    await callback.answer()

# ==========================================
# 6. UNIVERSAL BACKEND COMMAND CATCHER
# ==========================================

@ui_router.callback_query(F.data.startswith("cmd_"))
async def catch_all_commands(callback: CallbackQuery):
    command_name = callback.data.split("_", 1)[1]
    user_id = callback.from_user.id
    
    # Proteksi Akses Admin (Fitur Personal tidak masuk sini)
    admin_cmds = [
        "speedtest", "restart", "renew", "log", "logs", "resetdb", 
        "checksudo", "time", "stats", "add_vip", "delete_vip", 
        "view_vip", "addsudo", "delsudo", "changeconfig", "clearconfigs"
    ]
    if command_name in admin_cmds and not check_is_admin(user_id):
        return await callback.answer("⛔ Admin command only!", show_alert=True)
            
    await callback.answer(f"🚀 Memanggil Modul {command_name}...", show_alert=False)
    
    # Membuat "Pesan Tiruan" yang mewarisi context dari pesan Dashboard
    fake_msg = callback.message.model_copy(update={
        "from_user": callback.from_user,
        "chat": callback.message.chat,
        "text": f"/{command_name}"
    })
    
    try:
        # Mengimpor modul backend secara dinamis agar aman dari ImportError
        import bot.admin_handlers as adm
        import bot.media_handlers as med
        import bot.advanced_media_handlers as adv
        import bot.vip_handlers as vip
        
        # Mapping fungsi menggunakan getattr agar kebal terhadap perubahan nama
        handlers = {
            "speedtest": getattr(adm, "_speed_test", None), "time": getattr(adm, "_timecmd", None),
            "stats": getattr(adm, "_stats_msg", None), "restart": getattr(adm, "_restart", None),
            "renew": getattr(adm, "_renew", None), "log": getattr(adm, "_log", None),
            "logs": getattr(adm, "_logs", None), "checksudo": getattr(adm, "_checksudo", None),
            "resetdb": getattr(adm, "_resetdb", None), "savewatermark": getattr(adm, "_savewatermark", None),
            "savethumb": getattr(adm, "_savethumb", None), "saveconfig": getattr(adm, "_saverclone", None),
            
            "addsudo": getattr(adm, "_addsudo", None), "delsudo": getattr(adm, "_delsudo", None),
            "changeconfig": getattr(adm, "_changeconfig", None), "clearconfigs": getattr(adm, "_clearconfig", None),
            
            "compress": getattr(med, "_compress_video", None), "convert": getattr(med, "_convert_video", None),
            "watermark": getattr(med, "_add_watermark_interactive", None), "merge": getattr(med, "_merge_videos", None),
            "softmux": getattr(med, "_softmux", None), "hardmux": getattr(med, "_hardmux", None),
            "softremux": getattr(med, "_softremux", None), "leech": getattr(med, "_leech_file", None),
            "mirror": getattr(med, "_mirror_file", None), "status": getattr(med, "_status", None),
            
            "encode": getattr(med, "_encode_video", None),
            "changeindex": getattr(med, "_change_index", None) or getattr(adv, "_change_index", None),
            
            "trim": getattr(adv, "_trim_video", None), "split": getattr(adv, "_split_video", None),
            "cut": getattr(adv, "_cut_video", None), "rotate": getattr(adv, "_rotate_video", None),
            "crop": getattr(adv, "_crop_video", None), "autocrop": getattr(adv, "_autocrop_video", None),
            "extract": getattr(adv, "_extract_streams", None),
            "extension": getattr(med, "_extension_changer", None) or getattr(adv, "_extension_changer", None),
            
            "changemetadata": getattr(med, "_change_metadata", None) or getattr(adv, "_change_metadata", None),
            "mediainfo": getattr(med, "_media_info", None) or getattr(adv, "_media_info", None),
            "genss": getattr(adv, "_gen_screenshots", None) or getattr(med, "_gen_screenshots", None),
            "gensample": getattr(adv, "_gen_video_sample", None) or getattr(med, "_gen_video_sample", None),
            
            "verify": getattr(vip, "_verify_payment", None), "myvip": getattr(vip, "_my_vip_status", None),
            "add_vip": getattr(vip, "_add_vip_manual", None), "delete_vip": getattr(vip, "_delete_vip_manual", None),
            "view_vip": getattr(vip, "_view_vip_list", None)
        }
        
        target_handler = handlers.get(command_name)
        
        # Eksekusi langsung jika fitur ditemukan di Backend!
        if target_handler:
            return await target_handler(fake_msg)
            
    except Exception as e:
        print(f"[UI ERROR] Kesalahan sistem backend: {e}")

    # ==========================================
    # 7. FALLBACK
    # ==========================================
    custom_instructions = {
        "addgameplay": "🎮 Kirimkan <b>Video Gameplay</b> atau <b>Link</b> ke obrolan ini.",
        "deletegameplay": "🗑️ Cek <b>List Gameplay</b>, lalu kirimkan <b>ID Gameplay</b> yang ingin dihapus.",
        "addsfx": "🔊 Kirimkan file <b>Audio/SFX</b>.",
        "listgameplay": "📋 <i>Mengarahkan...</i>\nJika gagal, ketik <code>/listgameplay</code> di obrolan.",
        "recap": "🎬 Ketik perintah <code>/recap</code> untuk memulai Film Recap otomatis.",
        "clip": "🎥 Ketik perintah <code>/clip</code> untuk memulai Auto Clip otomatis.",
        "add_vip": "👑 Ketik ID User yang ingin dijadikan VIP, atau balas pesannya.\nContoh: <code>/add_vip 123456789 30d</code>",
        "delete_vip": "👑 Ketik ID User yang ingin dicabut VIP-nya.\nContoh: <code>/delete_vip 123456789</code>",
        "addsudo": "👮 Ketik ID User yang ingin dijadikan Admin/Sudo.\nContoh: <code>/addsudo 123456789</code>",
        "delsudo": "👮 Ketik ID User yang ingin dihapus dari Admin/Sudo.\nContoh: <code>/delsudo 123456789</code>",
        "saveconfig": "💾 Kirimkan file <b>rclone.conf</b> Anda ke sini.",
        "savewatermark": "©️ Kirimkan gambar untuk dijadikan <b>Watermark Default</b>.",
        "savethumb": "🖼️ Kirimkan gambar untuk dijadikan <b>Thumbnail Default</b>.",
    }
    
    instruction_msg = custom_instructions.get(
        command_name, 
        "Modul ini memerlukan input atau file.\n<i>Silakan kirimkan file, media, atau link ke obrolan ini</i>"
    )

    instruction_text = f"<b>╭─ ACTIVE MODULE ─╮</b>\n<code>/{command_name}</code>\n\n{instruction_msg}\n\n<b>╰───────────────╯</b>"
    await safe_edit_message(callback.message, instruction_text, get_back_cancel_kb())


# ==========================================
# 8. GLOBAL HANDLERS
# ==========================================

@ui_router.callback_query(F.data == "action_cancel")
async def handler_action_cancel(callback: CallbackQuery):
    try: await callback.message.delete()
    except: pass

@ui_router.message(F.text == "/start")
async def cmd_start_first_time(message: Message):
    is_admin = check_is_admin(message.from_user.id)
    await message.answer(text=WELCOME_FIRST_TIME, reply_markup=get_main_menu_kb(is_admin), parse_mode="HTML")

@ui_router.message(F.text.in_(["/dashboard", "/menu"]))
async def cmd_dashboard(message: Message):
    is_admin = check_is_admin(message.from_user.id)
    bar, pct = get_storage_status()
    await message.answer(text=MAIN_DASHBOARD_TEXT.format(name=message.from_user.first_name, storage_bar=bar, storage=pct), reply_markup=get_main_menu_kb(is_admin), parse_mode="HTML")

__all__ = ["ui_router"]
