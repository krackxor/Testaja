"""
UI Dashboard Template for STUDIO KHOIRUL (Aiogram 3.x)
Versi: PROFESSIONAL v4.0 - Clean UX & Optimized Navigation
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
# 1. VISUAL CONSTANTS
# ==========================================

BORDER_TOP = "━━━━━━━━━━━━━━━━━━━━"
BORDER_LIGHT = "────────────────────"
DIVIDER = "│"
TOP_LEFT, TOP_RIGHT = "╭", "╮"
BOTTOM_LEFT, BOTTOM_RIGHT = "╰", "╯"
H_LINE, V_LINE = "─", "│"

def get_progress_bar(current: int, max_val: int, width: int = 10) -> str:
    """Generate clean progress bar"""
    filled = int((current / max_val) * width)
    empty = width - filled
    return f"[{'▓' * filled}{'░' * empty}]"

# ==========================================
# 2. DASHBOARD TEXTS
# ==========================================

MAIN_DASHBOARD = """
<b>╔═══════════════════════╗</b>
<b>║   STUDIO KHOIRUL      ║</b>
<b>╚═══════════════════════╝</b>

<b>Halo, {name}</b> {vip_badge}

<b>Status Sistem:</b>
  🟢 Engine: <code>Online</code>
  💾 Storage: {storage_bar} <code>{storage}%</code>
  📊 Antrean: <code>0 / 3</code>

{BORDER_LIGHT}
<i>Pilih workspace di bawah 👇</i>
"""

WELCOME_TEXT = """
<b>╔═══════════════════════╗</b>
<b>║   STUDIO KHOIRUL      ║</b>
<b>╚═══════════════════════╝</b>

🎬 <b>Platform Produksi Video Otomatis</b>

Sistem produksi dan editing video
dengan automasi AI dan tools profesional.

<i>Tekan tombol di bawah untuk memulai 👇</i>
"""

def create_section_header(icon: str, title: str, desc: str) -> str:
    """Create clean section header"""
    return f"""
<b>╭─ {icon} {title.upper()} ─╮</b>

{desc}

<b>{BORDER_LIGHT}</b>
<i>Pilih fitur yang Anda butuhkan:</i>
"""

# ==========================================
# 3. HELPER FUNCTIONS
# ==========================================

async def safe_edit(message: Message, text: str, reply_markup: InlineKeyboardMarkup = None) -> bool:
    """Safely edit message with error handling"""
    try:
        await message.edit_text(text=text, reply_markup=reply_markup, parse_mode="HTML")
        return True
    except TelegramBadRequest:
        return False

def is_admin(user_id: int) -> bool:
    """Check if user is admin"""
    return user_id in Config.SUDO_USERS

def get_storage_info() -> tuple:
    """Get storage usage info"""
    import shutil
    try:
        total, used, free = shutil.disk_usage("/")
        usage = int((used / total) * 100)
    except:
        usage = 45 # Fallback
    return get_progress_bar(usage, 100, 10), usage

def get_vip_badge(user_id: int) -> str:
    """Get VIP badge if user is VIP"""
    # Placeholder: Ganti dengan cek DB VIP yang sebenarnya
    return "<code>👑 VIP</code>"

def is_user_in_waiter(chat_id: int, user_id: int) -> bool:
    """Check if user is in waiter queue"""
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
# 4. KEYBOARD LAYOUTS
# ==========================================

def kb_main_menu(is_admin_user: bool = False) -> InlineKeyboardMarkup:
    """Main dashboard menu"""
    buttons = [
        # Core Production & Encoding
        [
            InlineKeyboardButton(text="🎬 Studio", callback_data="menu_studio"),
            InlineKeyboardButton(text="🎞️ Encode", callback_data="menu_encode")
        ],
        # Editing & Assets
        [
            InlineKeyboardButton(text="✂️ Editor", callback_data="menu_editor"),
            InlineKeyboardButton(text="🎮 Aset", callback_data="menu_assets")
        ],
        # Download & Settings
        [
            InlineKeyboardButton(text="📥 Download", callback_data="menu_download"),
            InlineKeyboardButton(text="⚙️ Pengaturan", callback_data="settings")
        ],
        # VIP
        [
            InlineKeyboardButton(text="👑 VIP", callback_data="menu_vip")
        ]
    ]
    
    # Admin button if admin
    if is_admin_user:
        buttons.append([
            InlineKeyboardButton(text="🔧 Admin", callback_data="menu_admin")
        ])
    
    # Close button
    buttons.append([
        InlineKeyboardButton(text="❌ Tutup", callback_data="action_close")
    ])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def kb_studio() -> InlineKeyboardMarkup:
    """Studio production menu"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🎬 Recap", callback_data="cmd_recap"),
            InlineKeyboardButton(text="🎥 Clip", callback_data="cmd_clip")
        ],
        [
            InlineKeyboardButton(text="🏆 Top Tier", callback_data="cmd_toptier"),
            InlineKeyboardButton(text="📊 Verdict", callback_data="cmd_verdict")
        ],
        [
            InlineKeyboardButton(text="📖 Analisis", callback_data="cmd_lore"),
            InlineKeyboardButton(text="🎯 Radar", callback_data="cmd_radar")
        ],
        [
            InlineKeyboardButton(text="⚡ Patch", callback_data="cmd_patch"),
            InlineKeyboardButton(text="📚 Arsip", callback_data="cmd_archives")
        ],
        [
            InlineKeyboardButton(text="▶️ Upload YT", callback_data="cmd_ytupload")
        ],
        [
            InlineKeyboardButton(text="↩️ Kembali", callback_data="menu_main")
        ]
    ])

def kb_encode() -> InlineKeyboardMarkup:
    """Encoding menu - separated from editor"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🚀 Encode Cepat", callback_data="cmd_encode")
        ],
        [
            InlineKeyboardButton(text="🎛️ Encode Custom", callback_data="cmd_customencode")
        ],
        [
            InlineKeyboardButton(text="ℹ️ Info Encode", callback_data="info_encode")
        ],
        [
            InlineKeyboardButton(text="↩️ Kembali", callback_data="menu_main")
        ]
    ])

def kb_editor() -> InlineKeyboardMarkup:
    """Video editor menu - reorganized and cleaned"""
    return InlineKeyboardMarkup(inline_keyboard=[
        # === FORMAT & KOMPRESI ===
        [
            InlineKeyboardButton(text="🗜️ Kompres", callback_data="cmd_compress"),
            InlineKeyboardButton(text="🔄 Konversi", callback_data="cmd_convert")
        ],
        
        # === POTONG & GABUNG ===
        [
            InlineKeyboardButton(text="✂️ Trim", callback_data="cmd_trim"),
            InlineKeyboardButton(text="🔪 Potong", callback_data="cmd_cut"),
            InlineKeyboardButton(text="📐 Split", callback_data="cmd_split")
        ],
        [
            InlineKeyboardButton(text="🔗 Gabung", callback_data="cmd_merge")
        ],
        
        # === VISUAL & EFEK ===
        [
            InlineKeyboardButton(text="📐 Crop", callback_data="cmd_crop"),
            InlineKeyboardButton(text="🎬 Auto Crop", callback_data="cmd_autocrop"),
            InlineKeyboardButton(text="🔃 Rotasi", callback_data="cmd_rotate")
        ],
        [
            InlineKeyboardButton(text="⚡ Kecepatan", callback_data="cmd_speed"),
            InlineKeyboardButton(text="©️ Watermark", callback_data="cmd_watermark")
        ],
        
        # === AUDIO ===
        [
            InlineKeyboardButton(text="🔇 Mute", callback_data="cmd_mute"),
            InlineKeyboardButton(text="🎙️ Dubbing", callback_data="cmd_dubbing")
        ],
        
        # === SUBTITLE & TRACK ===
        [
            InlineKeyboardButton(text="📌 Hardmux", callback_data="cmd_hardmux"),
            InlineKeyboardButton(text="📝 Softmux", callback_data="cmd_softmux")
        ],
        [
            InlineKeyboardButton(text="♻️ Remux", callback_data="cmd_softremux"),
            InlineKeyboardButton(text="🔀 Index", callback_data="cmd_changeindex")
        ],
        
        # === DATA & INFO ===
        [
            InlineKeyboardButton(text="📁 Ekstensi", callback_data="cmd_extension"),
            InlineKeyboardButton(text="🏷️ Metadata", callback_data="cmd_changemetadata")
        ],
        [
            InlineKeyboardButton(text="📥 Ekstrak", callback_data="cmd_extract"),
            InlineKeyboardButton(text="ℹ️ Info Media", callback_data="cmd_mediainfo")
        ],
        
        # === PREVIEW & SAMPLE ===
        [
            InlineKeyboardButton(text="📸 Screenshot", callback_data="cmd_genss"),
            InlineKeyboardButton(text="🎞️ Sample", callback_data="cmd_gensample")
        ],
        
        # === NAVIGATION ===
        [
            InlineKeyboardButton(text="↩️ Kembali", callback_data="menu_main")
        ]
    ])

def kb_assets() -> InlineKeyboardMarkup:
    """Asset manager menu"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="➕ Tambah", callback_data="cmd_addgameplay"),
            InlineKeyboardButton(text="📋 Daftar", callback_data="cmd_listgameplay")
        ],
        [
            InlineKeyboardButton(text="🗑️ Hapus", callback_data="cmd_deletegameplay"),
            InlineKeyboardButton(text="🔊 SFX", callback_data="cmd_addsfx")
        ],
        [
            InlineKeyboardButton(text="↩️ Kembali", callback_data="menu_main")
        ]
    ])

def kb_download() -> InlineKeyboardMarkup:
    """Download & cloud menu"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📥 Leech", callback_data="cmd_leech"),
            InlineKeyboardButton(text="☁️ Mirror", callback_data="cmd_mirror")
        ],
        [
            InlineKeyboardButton(text="↩️ Kembali", callback_data="menu_main")
        ]
    ])

def kb_vip() -> InlineKeyboardMarkup:
    """VIP membership menu"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="👑 Status VIP", callback_data="cmd_myvip")
        ],
        [
            InlineKeyboardButton(text="💳 Verifikasi", callback_data="cmd_verify")
        ],
        [
            InlineKeyboardButton(text="ℹ️ Info VIP", callback_data="cmd_vip_info")
        ],
        [
            InlineKeyboardButton(text="↩️ Kembali", callback_data="menu_main")
        ]
    ])

def kb_admin() -> InlineKeyboardMarkup:
    """Admin control panel"""
    return InlineKeyboardMarkup(inline_keyboard=[
        # === MONITORING ===
        [
            InlineKeyboardButton(text="📊 Status", callback_data="cmd_status"),
            InlineKeyboardButton(text="⏱️ Uptime", callback_data="cmd_time")
        ],
        [
            InlineKeyboardButton(text="🚀 Speed", callback_data="cmd_speedtest"),
            InlineKeyboardButton(text="📈 Stats", callback_data="cmd_stats")
        ],
        
        # === LOGS ===
        [
            InlineKeyboardButton(text="📜 Log", callback_data="cmd_log"),
            InlineKeyboardButton(text="📁 Download", callback_data="cmd_logs")
        ],
        
        # === DATABASE ===
        [
            InlineKeyboardButton(text="🧹 Bersihkan", callback_data="cmd_renew"),
            InlineKeyboardButton(text="💥 Reset DB", callback_data="cmd_resetdb")
        ],
        
        # === CONFIG ===
        [
            InlineKeyboardButton(text="🔄 Config", callback_data="cmd_changeconfig"),
            InlineKeyboardButton(text="🗑️ Hapus Config", callback_data="cmd_clearconfigs")
        ],
        
        # === SUDO USERS ===
        [
            InlineKeyboardButton(text="👮 Daftar Sudo", callback_data="cmd_checksudo")
        ],
        [
            InlineKeyboardButton(text="➕ Tambah", callback_data="cmd_addsudo"),
            InlineKeyboardButton(text="➖ Hapus", callback_data="cmd_delsudo")
        ],
        
        # === VIP MANAGEMENT ===
        [
            InlineKeyboardButton(text="👑 Daftar VIP", callback_data="cmd_view_vip")
        ],
        [
            InlineKeyboardButton(text="➕ Tambah", callback_data="cmd_add_vip"),
            InlineKeyboardButton(text="➖ Hapus", callback_data="cmd_delete_vip")
        ],
        
        # === SYSTEM CONTROL ===
        [
            InlineKeyboardButton(text="🔄 Restart", callback_data="cmd_restart")
        ],
        [
            InlineKeyboardButton(text="↩️ Kembali", callback_data="menu_main")
        ]
    ])

def kb_back_close() -> InlineKeyboardMarkup:
    """Standard back/close buttons"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="↩️ Kembali", callback_data="menu_main"),
            InlineKeyboardButton(text="❌ Tutup", callback_data="action_close")
        ]
    ])

# ==========================================
# 5. NAVIGATION HANDLERS
# ==========================================

@ui_router.callback_query(F.data == "menu_main")
async def nav_main(callback: CallbackQuery):
    """Navigate to main menu"""
    admin_status = is_admin(callback.from_user.id)
    bar, pct = get_storage_info()
    vip_badge = get_vip_badge(callback.from_user.id)
    
    text = MAIN_DASHBOARD.format(
        name=callback.from_user.first_name,
        vip_badge=vip_badge,
        storage_bar=bar,
        storage=pct,
        BORDER_LIGHT=BORDER_LIGHT
    )
    
    await safe_edit(callback.message, text, kb_main_menu(admin_status))
    await callback.answer()

@ui_router.callback_query(F.data == "menu_studio")
async def nav_studio(callback: CallbackQuery):
    """Navigate to studio production"""
    text = create_section_header(
        "🎬", 
        "Studio",
        "Produksi video otomatis dengan AI, script, dan rendering"
    )
    await safe_edit(callback.message, text, kb_studio())
    await callback.answer()

@ui_router.callback_query(F.data == "menu_encode")
async def nav_encode(callback: CallbackQuery):
    """Navigate to encoding menu"""
    text = create_section_header(
        "🎞️",
        "Encode",
        "Encoding video dengan preset optimized atau custom parameters"
    )
    await safe_edit(callback.message, text, kb_encode())
    await callback.answer()

@ui_router.callback_query(F.data == "menu_editor")
async def nav_editor(callback: CallbackQuery):
    """Navigate to video editor"""
    text = create_section_header(
        "✂️",
        "Editor",
        "Tools editing video profesional - potong, gabung, efek, dan lainnya"
    )
    await safe_edit(callback.message, text, kb_editor())
    await callback.answer()

@ui_router.callback_query(F.data == "menu_assets")
async def nav_assets(callback: CallbackQuery):
    """Navigate to asset manager"""
    text = create_section_header(
        "🎮",
        "Aset",
        "Kelola gameplay footage, sound effects, dan media library"
    )
    await safe_edit(callback.message, text, kb_assets())
    await callback.answer()

@ui_router.callback_query(F.data == "menu_download")
async def nav_download(callback: CallbackQuery):
    """Navigate to download menu"""
    text = create_section_header(
        "📥",
        "Download",
        "Download file dari URL atau mirror ke cloud storage"
    )
    await safe_edit(callback.message, text, kb_download())
    await callback.answer()

@ui_router.callback_query(F.data == "settings")
async def nav_settings(callback: CallbackQuery):
    """Navigate to settings"""
    text = create_section_header(
        "⚙️",
        "Pengaturan",
        "Konfigurasi bot, watermark, thumbnail, dan preferensi"
    )
    await safe_edit(callback.message, text, kb_back_close())
    await callback.answer("⚙️ Gunakan perintah /settings untuk saat ini")

@ui_router.callback_query(F.data == "menu_vip")
async def nav_vip(callback: CallbackQuery):
    """Navigate to VIP menu"""
    text = create_section_header(
        "👑",
        "VIP",
        "Status membership, verifikasi pembayaran, dan benefit VIP"
    )
    await safe_edit(callback.message, text, kb_vip())
    await callback.answer()

@ui_router.callback_query(F.data == "menu_admin")
async def nav_admin(callback: CallbackQuery):
    """Navigate to admin panel"""
    if not is_admin(callback.from_user.id):
        return await callback.answer("⛔ Akses ditolak", show_alert=True)
    
    text = create_section_header(
        "🔧",
        "Admin",
        "Monitoring sistem, database, users, dan kontrol server"
    )
    await safe_edit(callback.message, text, kb_admin())
    await callback.answer()

# ==========================================
# 6. INFO HANDLERS
# ==========================================

@ui_router.callback_query(F.data == "info_encode")
async def info_encode(callback: CallbackQuery):
    """Show encoding info"""
    info_text = """
<b>╭─ ℹ️ INFO ENCODE ─╮</b>

<b>🚀 Encode Cepat</b>
Preset optimized untuk kualitas dan ukuran
• H.264 - kompatibilitas tinggi
• Kualitas 720p/1080p
• Bitrate auto-optimize

<b>🎛️ Encode Custom</b>
Kontrol penuh parameter encoding
• Pilih codec (H.264/H.265/VP9)
• Custom bitrate & CRF
• Audio/subtitle handling
• Resolution & framerate

{BORDER_LIGHT}
""".format(BORDER_LIGHT=BORDER_LIGHT)
    
    await safe_edit(callback.message, info_text, kb_back_close())
    await callback.answer()

# ==========================================
# 7. COMMAND ROUTER
# ==========================================

@ui_router.callback_query(F.data.startswith("cmd_"))
async def route_commands(callback: CallbackQuery):
    """Route commands to backend handlers"""
    cmd = callback.data.split("_", 1)[1]
    user_id = callback.from_user.id
    
    # Admin command protection
    admin_cmds = {
        "speedtest", "restart", "renew", "log", "logs", "resetdb",
        "checksudo", "time", "stats", "add_vip", "delete_vip",
        "view_vip", "addsudo", "delsudo", "changeconfig", "clearconfigs"
    }
    
    if cmd in admin_cmds and not is_admin(user_id):
        return await callback.answer("⛔ Akses admin only", show_alert=True)
    
    await callback.answer(f"⚡ Memuat {cmd}...")
    
    # Create fake message for backend
    fake_msg = callback.message.model_copy(update={
        "from_user": callback.from_user,
        "chat": callback.message.chat,
        "text": f"/{cmd}"
    })
    
    try:
        # Dynamic import for safety
        import bot.admin_handlers as adm
        import bot.media_handlers as med
        import bot.advanced_media_handlers as adv
        import bot.vip_handlers as vip
        
        # Handler mapping
        handlers = {
            # Admin
            "speedtest": getattr(adm, "_speed_test", None),
            "time": getattr(adm, "_timecmd", None),
            "stats": getattr(adm, "_stats_msg", None),
            "restart": getattr(adm, "_restart", None),
            "renew": getattr(adm, "_renew", None),
            "log": getattr(adm, "_log", None),
            "logs": getattr(adm, "_logs", None),
            "checksudo": getattr(adm, "_checksudo", None),
            "resetdb": getattr(adm, "_resetdb", None),
            "addsudo": getattr(adm, "_addsudo", None),
            "delsudo": getattr(adm, "_delsudo", None),
            "changeconfig": getattr(adm, "_changeconfig", None),
            "clearconfigs": getattr(adm, "_clearconfig", None),
            
            # Media - Core
            "encode": getattr(med, "_encode_video", None),
            "customencode": getattr(med, "_custom_encode_video", None),
            "compress": getattr(med, "_compress_video", None),
            "convert": getattr(med, "_convert_video", None),
            "merge": getattr(med, "_merge_videos", None),
            "speed": getattr(med, "_speed_video", None),
            "mute": getattr(med, "_mute_video", None),
            "dubbing": getattr(med, "_dubbing_video", None),
            
            # Media - Muxing
            "softmux": getattr(med, "_softmux", None),
            "hardmux": getattr(med, "_hardmux", None),
            "softremux": getattr(med, "_softremux", None),
            
            # Media - Utility
            "watermark": getattr(med, "_add_watermark_interactive", None),
            "extract": getattr(med, "_extract_streams", None) or getattr(adv, "_extract_streams", None),
            "extension": getattr(med, "_extension_changer", None) or getattr(adv, "_extension_changer", None),
            "changeindex": getattr(med, "_change_index", None) or getattr(adv, "_change_index", None),
            "changemetadata": getattr(med, "_change_metadata", None) or getattr(adv, "_change_metadata", None),
            "mediainfo": getattr(med, "_media_info", None) or getattr(adv, "_media_info", None),
            
            # Advanced
            "trim": getattr(adv, "_trim_video", None),
            "split": getattr(adv, "_split_video", None),
            "cut": getattr(adv, "_cut_video", None),
            "rotate": getattr(adv, "_rotate_video", None),
            "crop": getattr(adv, "_crop_video", None),
            "autocrop": getattr(adv, "_autocrop_video", None),
            "genss": getattr(adv, "_gen_screenshots", None) or getattr(med, "_gen_screenshots", None),
            "gensample": getattr(adv, "_gen_video_sample", None) or getattr(med, "_gen_video_sample", None),
            "ext_thumb": getattr(med, "_extract_thumbnail", None) or getattr(adv, "_extract_thumbnail", None),
            "ext_frames": getattr(med, "_extract_frames_zip", None) or getattr(adv, "_extract_frames_zip", None),
            
            # Download
            "leech": getattr(med, "_leech_file", None),
            "mirror": getattr(med, "_mirror_file", None),
            "status": getattr(med, "_status", None),
            
            # VIP
            "verify": getattr(vip, "_verify_payment", None),
            "myvip": getattr(vip, "_my_vip_status", None),
            "add_vip": getattr(vip, "_add_vip_manual", None),
            "delete_vip": getattr(vip, "_delete_vip_manual", None),
            "view_vip": getattr(vip, "_view_vip_list", None)
        }
        
        handler = handlers.get(cmd)
        
        if handler:
            return await handler(fake_msg)
            
    except Exception as e:
        print(f"[UI ROUTER ERROR] {e}")
    
    # ==========================================
    # FALLBACK INSTRUCTIONS
    # ==========================================
    instructions = {
        "addgameplay": "🎮 Kirim <b>video gameplay</b> atau <b>link</b> ke chat",
        "deletegameplay": "🗑️ Cek daftar gameplay, lalu kirim <b>ID</b> yang akan dihapus",
        "addsfx": "🔊 Kirim file <b>audio/SFX</b>",
        "listgameplay": "📋 Loading...\nJika gagal ketik <code>/listgameplay</code>",
        "recap": "🎬 Ketik <code>/recap</code> untuk memulai",
        "clip": "🎥 Ketik <code>/clip</code> untuk memulai",
        "add_vip": "👑 Format: <code>/add_vip [user_id] [durasi]</code>\nContoh: <code>/add_vip 123456789 30d</code>",
        "delete_vip": "👑 Format: <code>/delete_vip [user_id]</code>",
        "addsudo": "👮 Format: <code>/addsudo [user_id]</code>",
        "delsudo": "👮 Format: <code>/delsudo [user_id]</code>",
        "saveconfig": "💾 Kirim file <b>rclone.conf</b>",
        "savewatermark": "©️ Kirim gambar untuk <b>watermark default</b>",
        "savethumb": "🖼️ Kirim gambar untuk <b>thumbnail default</b>",
    }
    
    instruction = instructions.get(
        cmd,
        "Modul memerlukan input.\n<i>Kirim file/media/link ke chat ini</i>"
    )
    
    text = f"""
<b>╭─ MODULE AKTIF ─╮</b>
<code>/{cmd}</code>

{instruction}

<b>╰──────────────╯</b>
"""
    
    await safe_edit(callback.message, text, kb_back_close())

# ==========================================
# 8. GLOBAL ACTIONS
# ==========================================

@ui_router.callback_query(F.data == "action_close")
async def action_close(callback: CallbackQuery):
    """Close dashboard"""
    try:
        await callback.message.delete()
    except:
        pass
    await callback.answer("Dashboard ditutup")

@ui_router.message(F.text == "/start")
async def cmd_start(message: Message):
    """Start command - show welcome"""
    admin_status = is_admin(message.from_user.id)
    await message.answer(
        text=WELCOME_TEXT,
        reply_markup=kb_main_menu(admin_status),
        parse_mode="HTML"
    )

@ui_router.message(F.text.in_(["/dashboard", "/menu"]))
async def cmd_dashboard(message: Message):
    """Dashboard command - show main menu"""
    admin_status = is_admin(message.from_user.id)
    bar, pct = get_storage_info()
    vip_badge = get_vip_badge(message.from_user.id)
    
    text = MAIN_DASHBOARD.format(
        name=message.from_user.first_name,
        vip_badge=vip_badge,
        storage_bar=bar,
        storage=pct,
        BORDER_LIGHT=BORDER_LIGHT
    )
    
    await message.answer(
        text=text,
        reply_markup=kb_main_menu(admin_status),
        parse_mode="HTML"
    )

__all__ = ["ui_router"]
