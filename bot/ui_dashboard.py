"""
UI Dashboard Template for STUDIO KHOIRUL (Aiogram 3.x)
Versi: PROFESSIONAL v5.5 - Custom Media Prompt & 120s Timeout Fix
Update: Integrasi Menu AI, Subtitle Editor, Global Waiter
"""

import asyncio
import shutil
from aiogram import Router, F
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, Message
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from config.config import Config

# Inisialisasi Router untuk UI
ui_router = Router(name="ui_dashboard")

# ==========================================
# 1. VISUAL CONSTANTS
# ==========================================

BORDER_TOP = "━━━━━━━━━━━━━━━━━━━━"
BORDER_LIGHT = "────────────────────"
DIVIDER = "│"

def get_progress_bar(current: int, max_val: int, width: int = 10) -> str:
    filled = int((current / max_val) * width)
    empty = width - filled
    return f"[{'▓' * filled}{'░' * empty}]"

# ==========================================
# 2. DASHBOARD TEXTS
# ==========================================

WELCOME_TEXT = """
<b>💠 STUDIO KHOIRUL</b>
━━━━━━━━━━━━━━━━━━━━
<b>Platform Automasi & Video Editor</b>

Solusi instan untuk <i>encoding</i>, <i>editing</i>, dan manajemen aset media langsung dari genggaman Anda.

<i>Pilih aksi di bawah untuk memulai 👇</i>
"""

MAIN_DASHBOARD = """
<b>💠 STUDIO KHOIRUL</b>
━━━━━━━━━━━━━━━━━━━━

<b>Halo, {name}</b> {vip_badge}

<b>Status Sistem:</b>
  🟢 Engine: <code>Online</code>
  💾 Storage: {storage_bar} <code>{storage}%</code>
  🖥 CPU: {cpu_bar} <code>{cpu}%</code>
  🧠 RAM: {ram_bar} <code>{ram}%</code>
  📊 Antrean: <code>{queue_count} / 3</code>

<b>{BORDER_LIGHT}</b>
<i>Pilih workspace di bawah 👇</i>
"""

def create_section_header(icon: str, title: str, desc: str) -> str:
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
    try:
        await message.edit_text(text=text, reply_markup=reply_markup, parse_mode="HTML")
        return True
    except TelegramBadRequest:
        return False

def is_admin(user_id: int) -> bool:
    return user_id in Config.SUDO_USERS

def get_system_stats() -> dict:
    stats = {'storage': 0, 'cpu': 0, 'ram': 0}
    try:
        total, used, free = shutil.disk_usage("/")
        stats['storage'] = int((used / total) * 100)
    except Exception:
        pass
    try:
        import psutil
        stats['cpu'] = int(psutil.cpu_percent(interval=0.1))
        stats['ram'] = int(psutil.virtual_memory().percent)
    except ImportError:
        pass
    stats['storage_bar'] = get_progress_bar(stats['storage'], 100, 10)
    stats['cpu_bar'] = get_progress_bar(stats['cpu'], 100, 10)
    stats['ram_bar'] = get_progress_bar(stats['ram'], 100, 10)
    return stats

def get_vip_badge(user_id: int) -> str:
    return "<code>👑 VIP</code>"

def get_queue_count() -> int:
    try:
        from bot_helper.Process.Running_Tasks import queued_task, working_task
        return len(queued_task) + len(working_task)
    except Exception:
        return 0

def get_back_cancel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="↩️ Kembali", callback_data="menu_main", style="danger"),
         InlineKeyboardButton(text="❌ Tutup", callback_data="action_close", style="danger")]
    ])

# ==========================================
# 4. KEYBOARD LAYOUTS
# ==========================================

def kb_start_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="👤 Owner", url="https://t.me/Krackxhor", style="primary"),
            InlineKeyboardButton(text="📢 Channel", url="https://t.me/TelMovIDCariFilm", style="primary")
        ],
        [
            InlineKeyboardButton(text="🚀 Masuk Dashboard", callback_data="menu_main", style="success")
        ]
    ])

def kb_main_menu(is_admin_user: bool = False) -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(text="🎬 Studio", callback_data="menu_studio", style="primary"),
            InlineKeyboardButton(text="🎞️ Encode", callback_data="menu_encode", style="primary")
        ],
        [
            InlineKeyboardButton(text="✂️ Editor Video", callback_data="menu_editor", style="primary"),
            InlineKeyboardButton(text="🤖 AI & Subtitle", callback_data="menu_ai", style="primary")
        ],
        [
            InlineKeyboardButton(text="🎮 Aset", callback_data="menu_assets", style="primary"),
            InlineKeyboardButton(text="📥 Download", callback_data="menu_download", style="primary")
        ],
        [
            InlineKeyboardButton(text="⚙️ Pengaturan", callback_data="settings", style="primary"),
            InlineKeyboardButton(text="👑 VIP", callback_data="menu_vip", style="success")
        ]
    ]
    if is_admin_user:
        buttons.append([
            InlineKeyboardButton(text="🔧 Admin Control Panel", callback_data="menu_admin", style="primary")
        ])
    buttons.append([
        InlineKeyboardButton(text="❌ Tutup", callback_data="action_close", style="danger")
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def kb_ai() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🧠 Auto Subtitle (AI)", callback_data="cmd_autosub", style="primary")
        ],
        [
            InlineKeyboardButton(text="🌐 Auto Translate", callback_data="cmd_autotranslate", style="primary"),
            InlineKeyboardButton(text="📝 Editor Subtitle", callback_data="cmd_subedit", style="primary")
        ],
        [
            InlineKeyboardButton(text="↩️ Kembali", callback_data="menu_main", style="danger")
        ]
    ])

def kb_studio() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🎬 Recap", callback_data="cmd_recap", style="primary"),
            InlineKeyboardButton(text="🎥 Clip", callback_data="cmd_clip", style="primary")
        ],
        [
            InlineKeyboardButton(text="🏆 Top Tier", callback_data="cmd_toptier", style="primary"),
            InlineKeyboardButton(text="📊 Verdict", callback_data="cmd_verdict", style="primary")
        ],
        [
            InlineKeyboardButton(text="📖 Analisis", callback_data="cmd_lore", style="primary"),
            InlineKeyboardButton(text="🎯 Radar", callback_data="cmd_radar", style="primary")
        ],
        [
            InlineKeyboardButton(text="⚡ Patch", callback_data="cmd_patch", style="primary"),
            InlineKeyboardButton(text="📚 Arsip", callback_data="cmd_archives", style="primary")
        ],
        [
            InlineKeyboardButton(text="▶️ Upload YT", callback_data="cmd_ytupload", style="success")
        ],
        [
            InlineKeyboardButton(text="↩️ Kembali", callback_data="menu_main", style="danger")
        ]
    ])

def kb_encode() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🚀 Encode Cepat", callback_data="cmd_encode", style="success")
        ],
        [
            InlineKeyboardButton(text="🎛️ Encode Custom", callback_data="cmd_customencode", style="primary")
        ],
        [
            InlineKeyboardButton(text="ℹ️ Info Encode", callback_data="info_encode", style="primary"),
            InlineKeyboardButton(text="↩️ Kembali", callback_data="menu_main", style="danger")
        ]
    ])

def kb_editor() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🗜️ Kompres", callback_data="cmd_compress", style="primary"),
            InlineKeyboardButton(text="🔄 Konversi", callback_data="cmd_convert", style="primary")
        ],
        [
            InlineKeyboardButton(text="🔗 Gabung", callback_data="cmd_merge", style="primary")
        ],
        [
            InlineKeyboardButton(text="✂️ Trim", callback_data="cmd_trim", style="primary"),
            InlineKeyboardButton(text="🔪 Potong", callback_data="cmd_cut", style="primary"),
            InlineKeyboardButton(text="📐 Split", callback_data="cmd_split", style="primary")
        ],
        [
            InlineKeyboardButton(text="⚡ Kecepatan", callback_data="cmd_speed", style="primary"),
            InlineKeyboardButton(text="📁 Ekstensi", callback_data="cmd_extension", style="primary")
        ],
        [
            InlineKeyboardButton(text="📐 Crop", callback_data="cmd_crop", style="primary"),
            InlineKeyboardButton(text="🎬 Auto Crop", callback_data="cmd_autocrop", style="primary"),
            InlineKeyboardButton(text="🔃 Rotasi", callback_data="cmd_rotate", style="primary")
        ],
        [
            InlineKeyboardButton(text="©️ Watermark", callback_data="cmd_watermark", style="primary")
        ],
        [
            InlineKeyboardButton(text="🔇 Mute Audio", callback_data="cmd_mute", style="primary"),
            InlineKeyboardButton(text="🎙️ Dubbing", callback_data="cmd_dubbing", style="primary")
        ],
        [
            InlineKeyboardButton(text="📌 Hardmux", callback_data="cmd_hardmux", style="primary"),
            InlineKeyboardButton(text="📝 Softmux", callback_data="cmd_softmux", style="primary"),
            InlineKeyboardButton(text="♻️ Remux", callback_data="cmd_softremux", style="primary")
        ],
        [
            InlineKeyboardButton(text="🏷️ Metadata", callback_data="cmd_changemetadata", style="primary"),
            InlineKeyboardButton(text="🔀 Ubah Index", callback_data="cmd_changeindex", style="primary")
        ],
        [
            InlineKeyboardButton(text="📥 Ekstrak", callback_data="cmd_extract", style="primary")
        ],
        [
            InlineKeyboardButton(text="📸 Screenshot", callback_data="cmd_genss", style="primary"),
            InlineKeyboardButton(text="🎞️ Sample", callback_data="cmd_gensample", style="primary")
        ],
        [
            InlineKeyboardButton(text="ℹ️ Info Media", callback_data="cmd_mediainfo", style="primary"),
            InlineKeyboardButton(text="↩️ Kembali", callback_data="menu_main", style="danger")
        ]
    ])

def kb_assets() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="➕ Tambah Footage", callback_data="cmd_addgameplay", style="success")
        ],
        [
            InlineKeyboardButton(text="📋 List Footage", callback_data="cmd_listgameplay", style="primary"),
            InlineKeyboardButton(text="🔊 Tambah SFX", callback_data="cmd_addsfx", style="primary")
        ],
        [
            InlineKeyboardButton(text="🗑️ Hapus", callback_data="cmd_deletegameplay", style="danger"),
            InlineKeyboardButton(text="↩️ Kembali", callback_data="menu_main", style="danger")
        ]
    ])

def kb_download() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📥 Leech URL", callback_data="cmd_leech", style="primary"),
            InlineKeyboardButton(text="☁️ Mirror Cloud", callback_data="cmd_mirror", style="primary")
        ],
        [
            InlineKeyboardButton(text="↩️ Kembali", callback_data="menu_main", style="danger")
        ]
    ])

def kb_settings() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="💾 Set Rclone", callback_data="cmd_saveconfig", style="success"),
            InlineKeyboardButton(text="🖼️ Set Thumb", callback_data="cmd_savethumb", style="success")
        ],
        [
            InlineKeyboardButton(text="📥 Upload Watermark", callback_data="cmd_savewatermark", style="success"),
            InlineKeyboardButton(text="©️ Setting Watermark", callback_data="watermark_settings", style="primary")
        ],
        [
            InlineKeyboardButton(text="🎥 Video Prefs", callback_data="video_settings", style="primary"),
            InlineKeyboardButton(text="🎵 Audio Prefs", callback_data="audio_settings", style="primary")
        ],
        [
            InlineKeyboardButton(text="🔗 Merge Rule", callback_data="merge_settings", style="primary"),
            InlineKeyboardButton(text="📝 Muxing Rule", callback_data="mux_settings", style="primary")
        ],
        [
            InlineKeyboardButton(text="🚜 Target Konversi", callback_data="convert_settings", style="primary"),
            InlineKeyboardButton(text="🏷️ Metadata", callback_data="metadata_settings", style="primary")
        ],
        [
            InlineKeyboardButton(text="🤖 Setting Umum (Bot)", callback_data="settings_bot", style="primary")
        ],
        [
            InlineKeyboardButton(text="↩️ Kembali", callback_data="menu_main", style="danger")
        ]
    ])

def kb_vip() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="👑 Status VIP", callback_data="cmd_myvip", style="primary"),
            InlineKeyboardButton(text="ℹ️ Info VIP", callback_data="cmd_vip_info", style="primary")
        ],
        [
            InlineKeyboardButton(text="💳 Verifikasi", callback_data="cmd_verify", style="success")
        ],
        [
            InlineKeyboardButton(text="↩️ Kembali", callback_data="menu_main", style="danger")
        ]
    ])

def kb_admin() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📊 Status", callback_data="cmd_status", style="primary"),
            InlineKeyboardButton(text="⏱️ Uptime", callback_data="cmd_time", style="primary"),
            InlineKeyboardButton(text="⚡ Speedtest", callback_data="cmd_speedtest", style="primary")
        ],
        [
            InlineKeyboardButton(text="📈 Stats", callback_data="cmd_stats", style="primary"),
            InlineKeyboardButton(text="📜 Log", callback_data="cmd_log", style="primary"),
            InlineKeyboardButton(text="📁 Unduh", callback_data="cmd_logs", style="primary")
        ],
        [
            InlineKeyboardButton(text="🔄 Cek Config", callback_data="cmd_changeconfig", style="primary"),
            InlineKeyboardButton(text="🗑️ Hapus Config", callback_data="cmd_clearconfigs", style="danger")
        ],
        [
            InlineKeyboardButton(text="🧹 Bersihkan", callback_data="cmd_renew", style="primary"),
            InlineKeyboardButton(text="💥 Reset DB", callback_data="cmd_resetdb", style="danger")
        ],
        [
            InlineKeyboardButton(text="👮 List Sudo", callback_data="cmd_checksudo", style="primary"),
            InlineKeyboardButton(text="👑 List VIP", callback_data="cmd_view_vip", style="primary")
        ],
        [
            InlineKeyboardButton(text="➕ Sudo", callback_data="cmd_addsudo", style="success"),
            InlineKeyboardButton(text="➖ Sudo", callback_data="cmd_delsudo", style="danger")
        ],
        [
            InlineKeyboardButton(text="➕ VIP", callback_data="cmd_add_vip", style="success"),
            InlineKeyboardButton(text="➖ VIP", callback_data="cmd_delete_vip", style="danger")
        ],
        [
            InlineKeyboardButton(text="🔄 Restart", callback_data="cmd_restart", style="primary"),
            InlineKeyboardButton(text="↩️ Kembali", callback_data="menu_main", style="danger")
        ]
    ])

# ==========================================
# 5. NAVIGATION HANDLERS
# ==========================================

@ui_router.callback_query(F.data == "menu_main")
async def nav_main(callback: CallbackQuery):
    admin_status = is_admin(callback.from_user.id)
    stats = get_system_stats()
    vip_badge = get_vip_badge(callback.from_user.id)
    queue_count = get_queue_count()
    
    text = MAIN_DASHBOARD.format(
        name=callback.from_user.first_name,
        vip_badge=vip_badge,
        storage_bar=stats['storage_bar'],
        storage=stats['storage'],
        cpu_bar=stats['cpu_bar'],
        cpu=stats['cpu'],
        ram_bar=stats['ram_bar'],
        ram=stats['ram'],
        queue_count=queue_count,
        BORDER_LIGHT=BORDER_LIGHT
    )
    await safe_edit(callback.message, text, kb_main_menu(admin_status))
    await callback.answer()

@ui_router.callback_query(F.data == "menu_studio")
async def nav_studio(callback: CallbackQuery):
    text = create_section_header("🎬", "Studio", "Produksi video otomatis dengan AI, script, dan rendering")
    await safe_edit(callback.message, text, kb_studio())
    await callback.answer()

@ui_router.callback_query(F.data == "menu_ai")
async def nav_ai(callback: CallbackQuery):
    text = create_section_header("🤖", "AI & Subtitle", "Generate subtitle otomatis (Speech-to-Text), terjemahkan file subtitle menggunakan AI Whisper, atau edit subtitle secara manual.")
    await safe_edit(callback.message, text, kb_ai())
    await callback.answer()

@ui_router.callback_query(F.data == "menu_encode")
async def nav_encode(callback: CallbackQuery):
    text = create_section_header("🎞️", "Encode", "Encoding video dengan preset optimized atau custom parameters")
    await safe_edit(callback.message, text, kb_encode())
    await callback.answer()

@ui_router.callback_query(F.data == "menu_editor")
async def nav_editor(callback: CallbackQuery):
    text = f"""
<b>╭─ ✂️ EDITOR VIDEO ─╮</b>

Pusat modifikasi dan manipulasi video.

<b>Kategori Alat:</b>
📦 <b>Format:</b> Kompres, Konversi, Gabung
⏱ <b>Timeline:</b> Trim, Cut, Split, Kecepatan
📐 <b>Visual:</b> Crop, Rotasi, Watermark
🎵 <b>Audio/Teks:</b> Mute, Dubbing, Muxing
⚙️ <b>Utilitas:</b> Ekstrak, Sample, Metadata, Index

<b>{BORDER_LIGHT}</b>
<i>Pilih fitur di bawah 👇</i>
"""
    await safe_edit(callback.message, text, kb_editor())
    await callback.answer()

@ui_router.callback_query(F.data == "menu_assets")
async def nav_assets(callback: CallbackQuery):
    text = create_section_header("🎮", "Aset", "Kelola footage video mentahan, sound effects, dan media")
    await safe_edit(callback.message, text, kb_assets())
    await callback.answer()

@ui_router.callback_query(F.data == "menu_download")
async def nav_download(callback: CallbackQuery):
    text = create_section_header("📥", "Download", "Download file dari URL atau mirror ke cloud storage")
    await safe_edit(callback.message, text, kb_download())
    await callback.answer()

@ui_router.callback_query(F.data == "settings")
async def nav_settings(callback: CallbackQuery):
    text = create_section_header("⚙️", "Pengaturan", "Konfigurasi engine, media, dan metadata Studio Khoirul.\n<i>(Menu terhubung langsung ke sistem inti bot)</i>")
    await safe_edit(callback.message, text, kb_settings())
    await callback.answer()

@ui_router.callback_query(F.data == "menu_vip")
async def nav_vip(callback: CallbackQuery):
    text = create_section_header("👑", "VIP", "Status membership, verifikasi pembayaran, dan benefit VIP")
    await safe_edit(callback.message, text, kb_vip())
    await callback.answer()

@ui_router.callback_query(F.data == "menu_admin")
async def nav_admin(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return await callback.answer("⛔ Akses ditolak", show_alert=True)
    text = create_section_header("🔧", "Admin", "Monitoring sistem, database, users, dan kontrol server")
    await safe_edit(callback.message, text, kb_admin())
    await callback.answer()

# ==========================================
# 6. INFO HANDLERS
# ==========================================

@ui_router.callback_query(F.data == "info_encode")
async def info_encode(callback: CallbackQuery):
    info_text = f"""
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

<b>{BORDER_LIGHT}</b>
"""
    await safe_edit(callback.message, info_text, get_back_cancel_kb())
    await callback.answer()

# ==========================================
# 7. COMMAND ROUTER (NEW CLICK & SEND LOGIC)
# ==========================================

@ui_router.callback_query(F.data.startswith("cmd_"))
async def route_commands(callback: CallbackQuery):
    cmd = callback.data.split("_", 1)[1]
    user_id = callback.from_user.id

  # --- TAMBAHKAN BARIS INI ---
        "recap": getattr(recap, "recap_handler", None),
        "clip": getattr(clip, "autoclip_handler", None),
        "addgameplay": getattr(gp, "add_gameplay_handler", None),
        "addsfx": getattr(gp, "addsfx_handler", None),
        "listgameplay": getattr(gp, "list_gameplay_handler", None),
        "deletegameplay": getattr(gp, "delete_gameplay_handler", None),
        "ytupload": getattr(yt, "ytupload_handler", None),
            
  # Handler untuk menu Studio (Verdict, Lore, dll)
        "verdict": getattr(gp, "master_studio_handler", None),
        "toptier": getattr(gp, "master_studio_handler", None),
        "archives": getattr(gp, "master_studio_handler", None),
        "lore": getattr(gp, "master_studio_handler", None),
        "radar": getattr(gp, "master_studio_handler", None),
        "patch": getattr(gp, "master_studio_handler", None),
        }
    
    # Perintah yang langsung dieksekusi tanpa butuh input file
    admin_cmds = {
        "speedtest", "restart", "renew", "log", "logs", "resetdb",
        "checksudo", "time", "stats", "add_vip", "delete_vip",
        "view_vip", "addsudo", "delsudo", "changeconfig", "clearconfigs",
        "saveconfig", "savewatermark", "savethumb", "status", "verify", "myvip",
        "listgameplay"
    }
    
    # Perintah yang butuh user mengirimkan file (Video/Srt/Audio)
    media_cmds = {
        "encode", "customencode", "compress", "convert", "merge", "speed",
        "mute", "dubbing", "softmux", "hardmux", "softremux", "watermark",
        "extract", "extension", "changeindex", "changemetadata", "mediainfo",
        "trim", "split", "cut", "rotate", "crop", "autocrop", "genss",
        "gensample", "ext_thumb", "ext_frames", "autosub", "autotranslate", "subedit",
        "leech", "mirror", "addgameplay", "addsfx", "deletegameplay", "recap", "clip",
        "ytupload"
    }
    
    if cmd in admin_cmds and not is_admin(user_id) and cmd not in ["status", "verify", "myvip"]:
        return await callback.answer("⛔ Akses admin only", show_alert=True)
    
    try:
        import bot.admin_handlers as adm
        import bot.media_handlers as med
        import bot.advanced_media_handlers as adv
        import bot.vip_handlers as vip
        import bot.subtitle_handlers as sub
        import bot.subtitle_editor as subed
        import bot.MovieRecap as recap
        import bot.Gameplay as gp
        import bot.AutoClip as autoclip
        import bot.YTUpload as yt
        
        handlers = {
            "speedtest": getattr(adm, "_speed_test", None), "time": getattr(adm, "_timecmd", None),
            "stats": getattr(adm, "_stats_msg", None), "restart": getattr(adm, "_restart", None),
            "renew": getattr(adm, "_renew", None), "log": getattr(adm, "_log", None),
            "logs": getattr(adm, "_logs", None), "checksudo": getattr(adm, "_checksudo", None),
            "resetdb": getattr(adm, "_resetdb", None), "addsudo": getattr(adm, "_addsudo", None),
            "delsudo": getattr(adm, "_delsudo", None), "changeconfig": getattr(adm, "_changeconfig", None),
            "clearconfigs": getattr(adm, "_clearconfig", None),

            "saveconfig": getattr(adm, "_saverclone", None), 
            "savewatermark": getattr(adm, "_savewatermark", None),
            "savethumb": getattr(adm, "_savethumb", None),

            "listgameplay": getattr(gp, "list_gameplay_handler", None), "deletegameplay": getattr(gp, "delete_gameplay_handler", None),
            "recap": getattr(recap, "recap_handler", None), "clip": getattr(autoclip, "autoclip_handler", None), "ytupload": getattr(yt, "ytupload_handler", None),
            "addgameplay": getattr(gp, "add_gameplay_handler", None), "addsfx": getattr(gp, "addsfx_handler", None),
            "verdict": getattr(gp, "master_studio_handler", None), "toptier": getattr(gp, "master_studio_handler", None),
            "archives": getattr(gp, "master_studio_handler", None), "lore": getattr(gp, "master_studio_handler", None),
            "radar": getattr(gp, "master_studio_handler", None), "patch": getattr(gp, "master_studio_handler", None),

            "encode": getattr(med, "_encode_video", None), "customencode": getattr(med, "_custom_encode_video", None),
            "compress": getattr(med, "_compress_video", None), "convert": getattr(med, "_convert_video", None),
            "merge": getattr(med, "_merge_videos", None), "speed": getattr(med, "_speed_video", None),
            "mute": getattr(med, "_mute_video", None), "dubbing": getattr(med, "_dubbing_video", None),
            "softmux": getattr(med, "_softmux", None), "hardmux": getattr(med, "_hardmux", None),
            "softremux": getattr(med, "_softremux", None),

            "watermark": getattr(med, "_add_watermark_interactive", None),
            "extract": getattr(med, "_extract_streams", None) or getattr(adv, "_extract_streams", None),
            "extension": getattr(med, "_extension_changer", None) or getattr(adv, "_extension_changer", None),
            "changeindex": getattr(med, "_change_index", None) or getattr(adv, "_change_index", None),
            "changemetadata": getattr(med, "_change_metadata", None) or getattr(adv, "_change_metadata", None),
            "mediainfo": getattr(med, "_media_info", None) or getattr(adv, "_media_info", None),

            "trim": getattr(adv, "_trim_video", None), "split": getattr(adv, "_split_video", None),
            "cut": getattr(adv, "_cut_video", None), "rotate": getattr(adv, "_rotate_video", None),
            "crop": getattr(adv, "_crop_video", None), "autocrop": getattr(adv, "_autocrop_video", None),
            "genss": getattr(adv, "_gen_screenshots", None) or getattr(med, "_gen_screenshots", None),
            "gensample": getattr(adv, "_gen_video_sample", None) or getattr(med, "_gen_video_sample", None),
            "ext_thumb": getattr(med, "_extract_thumbnail", None) or getattr(adv, "_extract_thumbnail", None),
            "ext_frames": getattr(med, "_extract_frames_zip", None) or getattr(adv, "_extract_frames_zip", None),

            "leech": getattr(med, "_leech_file", None), "mirror": getattr(med, "_mirror_file", None),
            "status": getattr(med, "_status", None),

            "verify": getattr(vip, "_verify_payment", None), "myvip": getattr(vip, "_my_vip_status", None),
            "add_vip": getattr(vip, "_add_vip_manual", None), "delete_vip": getattr(vip, "_delete_vip_manual", None),
            "view_vip": getattr(vip, "_view_vip_list", None),

            "autosub": getattr(sub, "autosub_handler", None),
            "autotranslate": getattr(sub, "autotranslate_handler", None),
            "subedit": getattr(subed, "subedit_start", None)
        }
        
        handler = handlers.get(cmd)
        if not handler:
            return await callback.answer(f"Module {cmd} belum tersedia.", show_alert=True)

        # ─── JIKA MENU MEMBUTUHKAN INPUT FILE ───
        if cmd in media_cmds:
            # [FIX HIGH] Cegah TelegramBadRequest Timeout 
            await callback.answer() 
            
            # --- CUSTOM PROMPT MESSAGE BERDASARKAN KATEGORI ---
            if cmd == "autosub":
                media_type = "Video atau Audio"
            elif cmd in ["autotranslate", "subedit"]:
                media_type = "File Subtitle (.srt / .ass)"
            elif cmd in ["savethumb", "savewatermark"]:
                media_type = "Gambar / Foto"
            else:
                media_type = "Media (Video/Audio/Srt/Gambar)"

            prompt = await callback.message.answer(
                f"📥 <b>MODE {cmd.upper()} AKTIF</b>\n"
                f"────────────────────\n"
                f"Silakan kirim <b>{media_type}</b> Anda ke chat ini sekarang...\n\n"
                f"<i>(Waktu tunggu 120 detik)</i>",
                parse_mode="HTML"
            )
            
            from bot.shared import wait_for_message
            try:
                # Waktu tunggu diset ke 120 detik
                response_msg = await wait_for_message(callback.message.chat.id, user_id, timeout=120)
            except asyncio.TimeoutError:
                response_msg = None
            
            if not response_msg:
                return await prompt.edit_text(
                    "❌ <b>Dibatalkan:</b> Waktu habis (120 detik) atau input tidak valid.\n"
                    "Silakan buka menu kembali.", 
                    parse_mode="HTML"
                )
            
            await prompt.delete() # Hapus pesan prompt
            
            # MEMBUAT FAKE MESSAGE
            # Seolah-olah user mereply file tersebut dengan perintah /cmd
            fake_msg = response_msg.model_copy(update={
                "text": f"/{cmd}",
                "reply_to_message": response_msg 
            })
            
            return await handler(fake_msg)

        # ─── JIKA MENU INSTAN (TIDAK BUTUH FILE) ───
        else:
            await callback.answer(f"⚡ Memuat {cmd}...")
            fake_msg = callback.message.model_copy(update={
                "from_user": callback.from_user,
                "chat": callback.message.chat,
                "text": f"/{cmd}"
            })
            return await handler(fake_msg)
            
    except Exception as e:
        print(f"[UI ROUTER ERROR] {e}")
        try:
            await callback.answer("Terjadi kesalahan sistem UI.", show_alert=True)
        except TelegramBadRequest:
            pass # Abaikan error jika callback sudah expired

# ==========================================
# 8. GLOBAL ACTIONS
# ==========================================

@ui_router.callback_query(F.data == "action_close")
async def action_close(callback: CallbackQuery):
    try: await callback.message.delete()
    except: pass
    await callback.answer("Dashboard ditutup")

@ui_router.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer(
        text=WELCOME_TEXT,
        reply_markup=kb_start_menu(),
        parse_mode="HTML"
    )

@ui_router.message(F.text.in_(["/dashboard", "/menu"]))
async def cmd_dashboard(message: Message):
    admin_status = is_admin(message.from_user.id)
    stats = get_system_stats()
    vip_badge = get_vip_badge(message.from_user.id)
    queue_count = get_queue_count()
    
    text = MAIN_DASHBOARD.format(
        name=message.from_user.first_name,
        vip_badge=vip_badge,
        storage_bar=stats['storage_bar'],
        storage=stats['storage'],
        cpu_bar=stats['cpu_bar'],
        cpu=stats['cpu'],
        ram_bar=stats['ram_bar'],
        ram=stats['ram'],
        queue_count=queue_count,
        BORDER_LIGHT=BORDER_LIGHT
    )
    await message.answer(
        text=text,
        reply_markup=kb_main_menu(admin_status),
        parse_mode="HTML"
    )

__all__ = ["ui_router"]
