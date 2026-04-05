"""
UI Dashboard Template for STUDIO KHOIRUL (Aiogram 3.x)
Versi: PREMIUM AESTHETIC v3.0 (Fully Backend-Integrated + Full Instructions)
Fix: Direct Handler Routing, No FSM Conflicts, One-Click Application Mode
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

# Separator & Border Styles
BORDER_PREMIUM = "━━━━━━━━━━━━━━━━━━━"
BORDER_SUBTLE = "─────────────────────"
DIVIDER = "┃"
TOP_LEFT = "╭"
TOP_RIGHT = "╮"
BOTTOM_LEFT = "╰"
BOTTOM_RIGHT = "╯"
H_LINE = "─"
V_LINE = "│"

# Status Indicators (Unicode Progress Bar)
def get_status_bar(current: int, max_val: int, width: int = 12) -> str:
    """Generate a visual progress bar"""
    filled = int((current / max_val) * width)
    empty = width - filled
    return f"[{'▓' * filled}{'░' * empty}]"

# ==========================================
# 2. DASHBOARD TEXTS (Enhanced)
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

<i>Fitur Utama:</i>
  • 🎞️ Auto Clip Generation
  • 🎬 Film Recap Editor  
  • 🎮 Gameplay Asset Manager
  • 📥 Download & Cloud Integration
  • ✂️ Pro Video Editing Suite

<b>👉 Mari kita mulai!</b>
"""

# Category Headers dengan styling
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
    except TelegramBadRequest as e:
        if "message is not modified" in str(e).lower():
            return False
        raise e

def check_is_admin(user_id: int) -> bool:
    return user_id in Config.SUDO_USERS

def get_back_cancel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="↩️ Kembali", callback_data="menu_main"),
         InlineKeyboardButton(text="✕ Tutup", callback_data="action_cancel")]
    ])

def get_storage_status() -> tuple:
    """Simulasi storage usage - ganti dengan real data"""
    usage = 45
    return get_status_bar(usage, 100, 10), usage

# ==========================================
# 4. KEYBOARD BUILDERS (ENHANCED)
# ==========================================

def get_main_menu_kb(is_admin: bool = False) -> InlineKeyboardMarkup:
    kb = [
        # Production Suite
        [InlineKeyboardButton(text="🎬 Studio Produksi", callback_data="menu_studio"),
         InlineKeyboardButton(text="✂️ Video Editing", callback_data="menu_vid_edit")],
        
        # Asset Management  
        [InlineKeyboardButton(text="🎮 Asset Manager", callback_data="menu_assets"),
         InlineKeyboardButton(text="📥 Cloud & Download", callback_data="menu_downloader")],
        
        # Settings & VIP
        [InlineKeyboardButton(text="⚙️ Pengaturan", callback_data="settings"), # Diarahkan langsung ke sistem callbacks.py
         InlineKeyboardButton(text="👑 VIP Membership", callback_data="menu_vip")],
    ]
    
    if is_admin:
        kb.append([InlineKeyboardButton(text="🔧 Admin Control", callback_data="menu_admin")])
    
    kb.append([InlineKeyboardButton(text="❌ Tutup Dashboard", callback_data="action_cancel")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

def get_studio_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        # Content Production
        [InlineKeyboardButton(text="🎬 Film Recap", callback_data="cmd_recap"),
         InlineKeyboardButton(text="🎥 Auto Clip", callback_data="cmd_clip")],
        
        # Video Analysis & Ranking
        [InlineKeyboardButton(text="🏆 Top Tier", callback_data="cmd_toptier"),
         InlineKeyboardButton(text="📊 Verdict", callback_data="cmd_verdict")],
        
        # Gaming Content
        [InlineKeyboardButton(text="📖 Lore Analysis", callback_data="cmd_lore"),
         InlineKeyboardButton(text="🎯 Radar", callback_data="cmd_radar")],
        
        # Misc
        [InlineKeyboardButton(text="⚡ Patch Notes", callback_data="cmd_patch"),
         InlineKeyboardButton(text="📚 Archives", callback_data="cmd_archives")],
        
        # Upload
        [InlineKeyboardButton(text="▶️ YouTube Upload", callback_data="cmd_ytupload")],
        
        # Navigation
        [InlineKeyboardButton(text="↩️ Kembali", callback_data="menu_main")]
    ])

def get_editor_kb() -> InlineKeyboardMarkup:
    """Video Editing Tools - Organized by category"""
    return InlineKeyboardMarkup(inline_keyboard=[
        # Compression & Format
        [InlineKeyboardButton(text="🗜️ Compress", callback_data="cmd_compress"),
         InlineKeyboardButton(text="🔄 Convert", callback_data="cmd_convert"),
         InlineKeyboardButton(text="🔗 Merge", callback_data="cmd_merge")],
        
        # Trimming & Cutting
        [InlineKeyboardButton(text="🎞️ Trim", callback_data="cmd_trim"),
         InlineKeyboardButton(text="✂️ Split", callback_data="cmd_split"),
         InlineKeyboardButton(text="🔪 Cut", callback_data="cmd_cut")],
        
        # Cropping & Rotation
        [InlineKeyboardButton(text="📐 Crop", callback_data="cmd_crop"),
         InlineKeyboardButton(text="🎬 Autocrop", callback_data="cmd_autocrop"),
         InlineKeyboardButton(text="🔃 Rotate", callback_data="cmd_rotate")],
        
        # Muxing Options
        [InlineKeyboardButton(text="📌 Hardmux", callback_data="cmd_hardmux"),
         InlineKeyboardButton(text="📝 Softmux", callback_data="cmd_softmux"),
         InlineKeyboardButton(text="♻️ Remux", callback_data="cmd_softremux")],
        
        # Audio & Metadata
        [InlineKeyboardButton(text="🎵 Extract Audio", callback_data="cmd_extract"),
         InlineKeyboardButton(text="🏷️ Metadata", callback_data="cmd_changemetadata"),
         InlineKeyboardButton(text="ℹ️ MediaInfo", callback_data="cmd_mediainfo")],
        
        # Advanced Tools
        [InlineKeyboardButton(text="©️ Watermark", callback_data="cmd_watermark"),
         InlineKeyboardButton(text="📸 Screenshot", callback_data="cmd_genss"),
         InlineKeyboardButton(text="🎞️ Sample", callback_data="cmd_gensample")],
        
        # Navigation
        [InlineKeyboardButton(text="↩️ Kembali", callback_data="menu_main")]
    ])

def get_assets_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Add Gameplay", callback_data="cmd_addgameplay"),
         InlineKeyboardButton(text="📋 List Gameplay", callback_data="cmd_listgameplay")],
        [InlineKeyboardButton(text="🗑️ Delete Gameplay", callback_data="cmd_deletegameplay"),
         InlineKeyboardButton(text="🔊 Add SFX", callback_data="cmd_addsfx")],
        [InlineKeyboardButton(text="↩️ Kembali", callback_data="menu_main")]
    ])

def get_downloader_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📥 Leech", callback_data="cmd_leech"),
         InlineKeyboardButton(text="☁️ Mirror Upload", callback_data="cmd_mirror")],
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
        # Monitoring
        [InlineKeyboardButton(text="📊 Status Tasks", callback_data="cmd_status"),
         InlineKeyboardButton(text="🚀 Speedtest", callback_data="cmd_speedtest")],
        
        [InlineKeyboardButton(text="⏱️ Uptime", callback_data="cmd_time"),
         InlineKeyboardButton(text="📈 Server Stats", callback_data="cmd_stats")],
        
        # Logging
        [InlineKeyboardButton(text="📜 View Logs", callback_data="cmd_log"),
         InlineKeyboardButton(text="📁 Download Logs", callback_data="cmd_logs")],
        
        # Maintenance
        [InlineKeyboardButton(text="🧹 Clean Server", callback_data="cmd_renew"),
         InlineKeyboardButton(text="💥 Reset Database", callback_data="cmd_resetdb")],
        
        # System Control
        [InlineKeyboardButton(text="👮 Check Sudoers", callback_data="cmd_checksudo"),
         InlineKeyboardButton(text="🔄 Restart Bot", callback_data="cmd_restart")],
         
        # Settings Quick Links
        [InlineKeyboardButton(text="©️ Set Watermark Default", callback_data="cmd_savewatermark"),
         InlineKeyboardButton(text="🖼️ Set Thumb Default", callback_data="cmd_savethumb")],
        
        # Navigation
        [InlineKeyboardButton(text="↩️ Back to Menu", callback_data="menu_main")]
    ])

# ==========================================
# 5. NAVIGATION HANDLERS
# ==========================================

@ui_router.callback_query(F.data == "menu_main")
async def nav_main(callback: CallbackQuery):
    is_admin = check_is_admin(callback.from_user.id)
    storage_bar, storage_pct = get_storage_status()
    text = MAIN_DASHBOARD_TEXT.format(
        name=callback.from_user.first_name,
        storage_bar=storage_bar,
        storage=storage_pct
    )
    await safe_edit_message(callback.message, text, get_main_menu_kb(is_admin))
    await callback.answer()

@ui_router.callback_query(F.data == "menu_studio")
async def nav_studio(callback: CallbackQuery):
    text = create_category_header(
        "🎬", "STUDIO PRODUKSI & AI",
        "Produksi video otomatis dengan AI & Script\n💡 Buat konten gaming berkualitas tinggi",
        "📺"
    )
    await safe_edit_message(callback.message, text, get_studio_kb())
    await callback.answer()

@ui_router.callback_query(F.data == "menu_vid_edit")
async def nav_video_edit(callback: CallbackQuery):
    text = create_category_header(
        "✂️", "VIDEO EDITING SUITE",
        "Suite editing profesional dengan berbagai tools\n🎬 Compress, Crop, Trim, Merge, Watermark & More",
        "⚙️"
    )
    await safe_edit_message(callback.message, text, get_editor_kb())
    await callback.answer()

@ui_router.callback_query(F.data == "menu_assets")
async def nav_assets(callback: CallbackQuery):
    text = create_category_header(
        "🎮", "ASSET MANAGER",
        "Kelola video gameplay & efek suara custom\n📚 Build library asset untuk produksi Anda",
        "🎯"
    )
    await safe_edit_message(callback.message, text, get_assets_kb())
    await callback.answer()

@ui_router.callback_query(F.data == "menu_downloader")
async def nav_downloader(callback: CallbackQuery):
    text = create_category_header(
        "📥", "CLOUD & DOWNLOAD",
        "Download file ke Telegram atau Cloud Storage\n☁️ Integrasi dengan Google Drive & Media penyimpanan lainnya",
        "💾"
    )
    await safe_edit_message(callback.message, text, get_downloader_kb())
    await callback.answer()

@ui_router.callback_query(F.data == "menu_vip")
async def nav_vip(callback: CallbackQuery):
    text = create_category_header(
        "👑", "VIP MEMBERSHIP",
        "Akses fitur premium dan priority queue\n💎 Unlock unlimited render & faster processing",
        "✨"
    )
    await safe_edit_message(callback.message, text, get_vip_kb())
    await callback.answer()

@ui_router.callback_query(F.data == "menu_admin")
async def nav_admin(callback: CallbackQuery):
    if not check_is_admin(callback.from_user.id):
        return await callback.answer("⛔ Access Denied - Admin Only!", show_alert=True)
    
    text = create_category_header(
        "🔧", "ADMIN CONTROL PANEL",
        "Kelola server, antrean, dan database\n⚡ Full system control & monitoring",
        "⚙️"
    )
    await safe_edit_message(callback.message, text, get_admin_kb())
    await callback.answer()

# ==========================================
# 6. UNIVERSAL BACKEND COMMAND CATCHER
# ==========================================

@ui_router.callback_query(F.data.startswith("cmd_"))
async def catch_all_commands(callback: CallbackQuery):
    command_name = callback.data.split("_", 1)[1]
    user_id = callback.from_user.id
    
    # Proteksi Akses Admin
    admin_commands = ["speedtest", "restart", "renew", "log", "logs", "resetdb", "checksudo", "time", "stats", "savewatermark", "savethumb"]
    if command_name in admin_commands and not check_is_admin(user_id):
        return await callback.answer("⛔ Admin command only!", show_alert=True)
            
    await callback.answer(f"🚀 Memanggil Modul {command_name}...", show_alert=False)
    
    # 1. Membuat "Pesan Tiruan" (Fake Message)
    fake_msg = callback.message.model_copy(update={
        "from_user": callback.from_user,
        "chat": callback.message.chat,
        "text": f"/{command_name}"
    })
    
    try:
        # 2. Mengimpor fungsi-fungsi dari Backend Handlers
        from bot.admin_handlers import _speed_test, _timecmd, _stats_msg, _restart, _renew, _log, _logs, _checksudo, _resetdb, _savewatermark, _savethumb
        from bot.media_handlers import _compress_video, _convert_video, _add_watermark_interactive, _merge_videos, _softmux, _hardmux, _softremux, _leech_file, _mirror_file, _status
        from bot.advanced_media_handlers import _trim_video, _split_video, _cut_video, _rotate_video, _crop_video, _autocrop_video, _extract_streams, _change_metadata, _media_info
        from bot.vip_handlers import _verify_payment, _my_vip_status
        
        # 3. Pemetaan Perintah (Mapping)
        handlers = {
            # Admin Handlers
            "speedtest": _speed_test, "time": _timecmd, "stats": _stats_msg, "restart": _restart, "renew": _renew, 
            "log": _log, "logs": _logs, "checksudo": _checksudo, "resetdb": _resetdb, "savewatermark": _savewatermark, "savethumb": _savethumb,
            # Media Handlers
            "compress": _compress_video, "convert": _convert_video, "watermark": _add_watermark_interactive, "merge": _merge_videos, 
            "softmux": _softmux, "hardmux": _hardmux, "softremux": _softremux, "leech": _leech_file, "mirror": _mirror_file, "status": _status,
            # Advanced Media Handlers
            "trim": _trim_video, "split": _split_video, "cut": _cut_video, "rotate": _rotate_video, "crop": _crop_video, 
            "autocrop": _autocrop_video, "extract": _extract_streams, "changemetadata": _change_metadata, "mediainfo": _media_info,
            # VIP Handlers
            "verify": _verify_payment, "myvip": _my_vip_status
        }
        
        # 4. Jika fungsi terhubung di Backend, eksekusi langsung (Dashboard ditutup)
        if command_name in handlers:
            await callback.message.delete()
            return await handlers[command_name](fake_msg)
            
    except ImportError as e:
        print(f"[UI ERROR] Gagal mengimpor backend module: {e}")

    # ==========================================
    # 5. FALLBACK: DAFTAR INSTRUKSI KHUSUS LENGKAP
    # Jika suatu fitur belum di-import ke backend, 
    # tampilkan instruksinya yang estetik di dalam Dashboard.
    # ==========================================
    custom_instructions = {
        # Asset Manager
        "addgameplay": "🎮 Silakan kirimkan <b>Video Gameplay</b> atau <b>Link</b> ke obrolan ini.",
        "deletegameplay": "🗑️ Silakan cek <b>List Gameplay</b>, lalu kirimkan <b>ID Gameplay</b> yang ingin dihapus ke obrolan ini.",
        "addsfx": "🔊 Silakan kirimkan file <b>Audio/SFX</b> ke obrolan ini.",
        "listgameplay": "📋 <i>Mengarahkan ke daftar...</i>\n\nJika daftar tidak muncul otomatis, silakan ketik perintah <code>/listgameplay</code> di obrolan.",
        
        # VIP & Admin
        "verify": "🔑 Silakan kirimkan <b>Kode Verifikasi Trakteer</b> Anda ke obrolan ini.",
        "resetdb": "⚠️ <b>PERINGATAN RESET DATABASE</b> ⚠️\n\nApakah Anda yakin ingin mereset database?\n<i>Ketik <b>YA</b> untuk melanjutkan, atau klik tombol <b>Batal/Tutup</b> di bawah.</i>",
        "vip_info": "ℹ️ <b>INFO VIP MEMBER</b>\n\nUntuk mendapatkan akses VIP, silakan dukung pengembangan bot ini melalui Trakteer.",
        
        # Video Editing Suite
        "compress": "🗜️ Kirimkan <b>Video</b> yang ingin di-compress ukurannya.",
        "convert": "🔄 Kirimkan <b>Video</b> yang formatnya ingin diubah.",
        "merge": "🔗 Kirimkan beberapa <b>Video</b> yang ingin digabungkan.",
        "trim": "🎞️ Kirimkan <b>Video</b> beserta waktu potong (Trim).",
        "split": "✂️ Kirimkan <b>Video</b> yang ingin di-split (dibagi menjadi beberapa bagian).",
        "cut": "🔪 Kirimkan <b>Video</b> yang ingin di-cut bagian tengahnya.",
        "crop": "📐 Kirimkan <b>Video</b> yang ingin di-crop (potong frame layarnya).",
        "autocrop": "🎬 Kirimkan <b>Video</b> untuk proses Autocrop (hilangkan bar hitam otomatis).",
        "rotate": "🔃 Kirimkan <b>Video</b> yang ingin dirotasi derajatnya.",
        "hardmux": "📌 Kirimkan <b>Video</b> beserta file <b>Subtitle (.srt/.ass)</b> untuk di-Hardmux (nempel permanen).",
        "softmux": "📝 Kirimkan <b>Video</b> beserta file <b>Subtitle</b> untuk di-Softmux.",
        "softremux": "♻️ Kirimkan <b>Video</b> untuk di-Remux formatnya.",
        "extract": "🎵 Kirimkan <b>Video</b> yang ingin diekstrak (diambil) audionya.",
        "changemetadata": "🏷️ Kirimkan <b>Video atau File Media</b> untuk diubah metadatanya (judul, author, dll).",
        "mediainfo": "ℹ️ Kirimkan <b>File Media</b> untuk melihat detail informasi teknisnya (MediaInfo).",
        "watermark": "©️ Kirimkan <b>Video</b> yang ingin diberi Watermark.",
        "genss": "📸 Kirimkan <b>Video</b> untuk men-generate Screenshot layar.",
        "gensample": "🎞️ Kirimkan <b>Video</b> untuk dibuatkan klip Sample/Preview pendek.",
        
        # Downloader
        "leech": "📥 Kirimkan <b>Link</b> (Direct, Torrent, atau Magnet) yang ingin di-download ke Telegram.",
        "mirror": "☁️ Kirimkan <b>Link</b> atau <b>File</b> yang ingin di-upload ke Cloud Storage (Gdrive, dll).",
        
        # Settings
        "savewatermark": "©️ Kirimkan <b>Gambar (PNG transparan)</b> ke obrolan ini untuk disimpan sebagai Watermark default.",
        "savethumb": "🖼️ Kirimkan <b>Gambar</b> ke obrolan ini untuk disimpan sebagai Thumbnail default.",
        
        # Studio Produksi
        "recap": "🎬 Kirimkan <b>Video</b> beserta <b>Teks Script</b> untuk dibuatkan Film Recap.",
        "clip": "🎥 Kirimkan <b>Video Full</b> yang ingin dijadikan Clip pendek secara otomatis.",
        "ytupload": "▶️ Kirimkan <b>Video</b> yang sudah siap untuk di-upload ke YouTube.",
        "toptier": "🏆 Kirimkan materi untuk analisis Top Tier List.",
        "verdict": "📊 Kirimkan materi untuk diberikan rating/Verdict.",
        "lore": "📖 Kirimkan materi untuk analisis Lore/Cerita.",
        "radar": "🎯 Kirimkan input untuk masuk ke sistem Radar.",
        "patch": "⚡ Kirimkan teks atau link Patch Notes yang ingin dibahas.",
        "archives": "📚 Kirimkan link atau file untuk dimasukkan ke sistem Archives."
    }
    
    # Mengambil pesan dari kamus, atau berikan pesan dasar jika di luar daftar
    instruction_msg = custom_instructions.get(
        command_name, 
        "Modul ini memerlukan input atau file.\n<i>Silakan kirimkan file, media, atau link ke obrolan ini</i>"
    )

    instruction_text = f"""
<b>╭─ ACTIVE MODULE ─╮</b>
<code>/{command_name}</code>

{instruction_msg}

<b>╰───────────────╯</b>
"""
    await safe_edit_message(callback.message, instruction_text, get_back_cancel_kb())


# ==========================================
# 7. GLOBAL HANDLERS
# ==========================================

@ui_router.callback_query(F.data == "action_cancel")
async def handler_action_cancel(callback: CallbackQuery):
    try: 
        await callback.message.delete()
    except: 
        pass
    await callback.answer("✕ Dashboard closed.")

@ui_router.message(F.text == "/start")
async def cmd_start_first_time(message: Message):
    """First time user greeting"""
    is_admin = check_is_admin(message.from_user.id)
    await message.answer(
        text=WELCOME_FIRST_TIME,
        reply_markup=get_main_menu_kb(is_admin),
        parse_mode="HTML"
    )

@ui_router.message(F.text.in_(["/dashboard", "/menu"]))
async def cmd_dashboard(message: Message):
    """Dashboard command"""
    is_admin = check_is_admin(message.from_user.id)
    storage_bar, storage_pct = get_storage_status()
    text = MAIN_DASHBOARD_TEXT.format(
        name=message.from_user.first_name,
        storage_bar=storage_bar,
        storage=storage_pct
    )
    await message.answer(
        text=text, 
        reply_markup=get_main_menu_kb(is_admin), 
        parse_mode="HTML"
    )

# ==========================================
# 9. AUTO-DETECT MEDIA (APP MODE)
# ==========================================
@ui_router.message(F.video | F.document | F.audio | F.photo)
async def auto_detect_media(message: Message):
    """
    Menangkap media yang dikirim pengguna saat sedang tidak menjalankan perintah apa pun.
    Memunculkan menu aksi langsung ke file tersebut layaknya Aplikasi.
    """
    is_admin = check_is_admin(message.from_user.id)
    
    # Deteksi jenis file
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

    # 1. Jika dikirim VIDEO
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
        
        # Hitung ukuran file (MB)
        size_mb = 0
        if message.video: size_mb = message.video.file_size / 1048576
        elif message.document: size_mb = message.document.file_size / 1048576
        
        text = (
            "<b>🎬 Video Terdeteksi!</b>\n"
            f"<code>Ukuran: {round(size_mb, 2)} MB</code>\n\n"
            "<i>Pilih aksi yang ingin dilakukan pada video ini 👇</i>\n\n"
            "⚠️ <b>Tips:</b> Klik tombol di bawah. Saat bot meminta video, cukup <b>Balas (Reply)</b> pesan video Anda ini."
        )
        await message.reply(text, reply_markup=kb, parse_mode="HTML")

    # 2. Jika dikirim AUDIO
    elif mime == "audio":
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔊 Tambah ke SFX Assets", callback_data="cmd_addsfx")],
            [InlineKeyboardButton(text="❌ Abaikan", callback_data="action_cancel")]
        ])
        await message.reply("<b>🎵 File Audio Terdeteksi!</b>\n\n<i>Pilih aksi di bawah:</i>", reply_markup=kb, parse_mode="HTML")
        
    # 3. Jika dikirim GAMBAR
    elif mime == "photo":
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="©️ Set sbg Watermark", callback_data="cmd_savewatermark"),
             InlineKeyboardButton(text="🖼️ Set sbg Thumbnail", callback_data="cmd_savethumb")],
            [InlineKeyboardButton(text="❌ Abaikan", callback_data="action_cancel")]
        ])
        await message.reply("<b>🖼️ Gambar Terdeteksi!</b>\n\n<i>Jadikan gambar ini sebagai default?</i>", reply_markup=kb, parse_mode="HTML")


# ==========================================
# 8. EXPORT
# ==========================================
__all__ = ["ui_router"]
