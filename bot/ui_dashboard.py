"""
UI Dashboard Template for STUDIO KHOIRUL (Aiogram 3.x)
Versi: PREMIUM AESTHETIC v3.2 (Super Bridge & Smart Auto-Detect)
Fix: Seamless Backend Integration, No ImportError Crashes, Auto-Detect Bypass.
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
        [InlineKeyboardButton(text="🗜️ Compress", callback_data="cmd_compress"), InlineKeyboardButton(text="🔄 Convert", callback_data="cmd_convert"), InlineKeyboardButton(text="🔗 Merge", callback_data="cmd_merge")],
        [InlineKeyboardButton(text="🎞️ Trim", callback_data="cmd_trim"), InlineKeyboardButton(text="✂️ Split", callback_data="cmd_split"), InlineKeyboardButton(text="🔪 Cut", callback_data="cmd_cut")],
        [InlineKeyboardButton(text="📐 Crop", callback_data="cmd_crop"), InlineKeyboardButton(text="🎬 Autocrop", callback_data="cmd_autocrop"), InlineKeyboardButton(text="🔃 Rotate", callback_data="cmd_rotate")],
        [InlineKeyboardButton(text="📌 Hardmux", callback_data="cmd_hardmux"), InlineKeyboardButton(text="📝 Softmux", callback_data="cmd_softmux"), InlineKeyboardButton(text="♻️ Remux", callback_data="cmd_softremux")],
        [InlineKeyboardButton(text="🎵 Extract Audio", callback_data="cmd_extract"), InlineKeyboardButton(text="🏷️ Metadata", callback_data="cmd_changemetadata"), InlineKeyboardButton(text="ℹ️ MediaInfo", callback_data="cmd_mediainfo")],
        [InlineKeyboardButton(text="©️ Watermark", callback_data="cmd_watermark"), InlineKeyboardButton(text="📸 Screenshot", callback_data="cmd_genss"), InlineKeyboardButton(text="🎞️ Sample", callback_data="cmd_gensample")],
        [InlineKeyboardButton(text="↩️ Kembali", callback_data="menu_main")]
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
        [InlineKeyboardButton(text="📊 Status Tasks", callback_data="cmd_status"), InlineKeyboardButton(text="🚀 Speedtest", callback_data="cmd_speedtest")],
        [InlineKeyboardButton(text="⏱️ Uptime", callback_data="cmd_time"), InlineKeyboardButton(text="📈 Server Stats", callback_data="cmd_stats")],
        [InlineKeyboardButton(text="📜 View Logs", callback_data="cmd_log"), InlineKeyboardButton(text="📁 Download Logs", callback_data="cmd_logs")],
        [InlineKeyboardButton(text="🧹 Clean Server", callback_data="cmd_renew"), InlineKeyboardButton(text="💥 Reset Database", callback_data="cmd_resetdb")],
        [InlineKeyboardButton(text="👮 Check Sudoers", callback_data="cmd_checksudo"), InlineKeyboardButton(text="🔄 Restart Bot", callback_data="cmd_restart")],
        [InlineKeyboardButton(text="©️ Set Watermark Default", callback_data="cmd_savewatermark"), InlineKeyboardButton(text="🖼️ Set Thumb Default", callback_data="cmd_savethumb")],
        [InlineKeyboardButton(text="↩️ Back to Menu", callback_data="menu_main")]
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
    
    # Proteksi Akses Admin
    admin_cmds = ["speedtest", "restart", "renew", "log", "logs", "resetdb", "checksudo", "time", "stats", "savewatermark", "savethumb"]
    if command_name in admin_cmds and not check_is_admin(user_id):
        return await callback.answer("⛔ Admin command only!", show_alert=True)
            
    await callback.answer(f"🚀 Memanggil Modul {command_name}...", show_alert=False)
    
    # Membuat "Pesan Tiruan" yang mewarisi context dari pesan Dashboard/Auto-Detect
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
            "savethumb": getattr(adm, "_savethumb", None),
            
            "compress": getattr(med, "_compress_video", None), "convert": getattr(med, "_convert_video", None),
            "watermark": getattr(med, "_add_watermark_interactive", None), "merge": getattr(med, "_merge_videos", None),
            "softmux": getattr(med, "_softmux", None), "hardmux": getattr(med, "_hardmux", None),
            "softremux": getattr(med, "_softremux", None), "leech": getattr(med, "_leech_file", None),
            "mirror": getattr(med, "_mirror_file", None), "status": getattr(med, "_status", None),
            
            "trim": getattr(adv, "_trim_video", None), "split": getattr(adv, "_split_video", None),
            "cut": getattr(adv, "_cut_video", None), "rotate": getattr(adv, "_rotate_video", None),
            "crop": getattr(adv, "_crop_video", None), "autocrop": getattr(adv, "_autocrop_video", None),
            "extract": getattr(adv, "_extract_streams", None),
            
            "changemetadata": getattr(med, "_change_metadata", None) or getattr(adv, "_change_metadata", None),
            "mediainfo": getattr(med, "_media_info", None) or getattr(adv, "_media_info", None),
            
            "verify": getattr(vip, "_verify_payment", None), "myvip": getattr(vip, "_my_vip_status", None)
        }
        
        target_handler = handlers.get(command_name)
        
        # Eksekusi langsung jika fitur ditemukan di Backend!
        if target_handler:
            # (Kita sengaja tidak menghapus callback.message di sini agar backend bisa nge-reply)
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

# ==========================================
# 9. AUTO-DETECT MEDIA (APP MODE)
# ==========================================
@ui_router.message(F.video | F.document | F.audio | F.photo)
async def auto_detect_media(message: Message):
    # 🚨 PENCEGAH BENTROK: Jika User sedang ditanya oleh Backend (misal disuruh milih resolusi / kirim video), abaikan!
    if is_user_in_waiter(message.chat.id, message.from_user.id):
        return 
    
    mime = ""
    if message.video: mime = "video"
    elif message.audio: mime = "audio"
    elif message.photo: mime = "photo"
    elif message.document:
        mime_type = str(message.document.mime_type).lower()
        if mime_type.startswith("video/"): mime = "video"
        elif mime_type.startswith("audio/"): mime = "audio"
        elif mime_type.startswith("image/"): mime = "photo"
        else: mime = "doc"

    if mime == "video":
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🗜️ Compress", callback_data="cmd_compress"),
             InlineKeyboardButton(text="🔄 Convert", callback_data="cmd_convert")],
            [InlineKeyboardButton(text="🎞️ Trim", callback_data="cmd_trim"),
             InlineKeyboardButton(text="©️ Watermark", callback_data="cmd_watermark")],
            [InlineKeyboardButton(text="🎵 Extract Audio", callback_data="cmd_extract"),
             InlineKeyboardButton(text="📸 Screenshot", callback_data="cmd_genss")],
            [InlineKeyboardButton(text="➕ Add to Assets", callback_data="cmd_addgameplay"),
             InlineKeyboardButton(text="❌ Abaikan", callback_data="action_cancel")]
        ])
        
        size_mb = 0
        if message.video: size_mb = message.video.file_size / 1048576
        elif message.document: size_mb = message.document.file_size / 1048576
        
        text = (
            "<b>🎬 Video Terdeteksi!</b>\n"
            f"<code>Ukuran: {round(size_mb, 2)} MB</code>\n\n"
            "<i>Pilih aksi di bawah, sistem akan langsung mengeksekusi file ini!</i> 👇"
        )
        await message.reply(text, reply_markup=kb, parse_mode="HTML")

    elif mime == "audio":
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔊 Tambah ke SFX Assets", callback_data="cmd_addsfx")],
            [InlineKeyboardButton(text="❌ Abaikan", callback_data="action_cancel")]
        ])
        await message.reply("<b>🎵 File Audio Terdeteksi!</b>\n\n<i>Pilih aksi di bawah:</i>", reply_markup=kb, parse_mode="HTML")
        
    elif mime == "photo":
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="©️ Set sbg Watermark", callback_data="cmd_savewatermark"),
             InlineKeyboardButton(text="🖼️ Set sbg Thumbnail", callback_data="cmd_savethumb")],
            [InlineKeyboardButton(text="❌ Abaikan", callback_data="action_cancel")]
        ])
        await message.reply("<b>🖼️ Gambar Terdeteksi!</b>\n\n<i>Jadikan gambar ini sebagai default?</i>", reply_markup=kb, parse_mode="HTML")

__all__ = ["ui_router"]
