"""
UI Dashboard Template for STUDIO KHOIRUL (Aiogram 3.x)
Versi: PROFESSIONAL v7.0 - Final Layout & Asset Integration
Update: Re-layout menu utama, sinkronisasi dengan bot.asset_handlers, 
        perbaikan mapping fungsi untuk fitur aset video/audio.
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
    return user_id in Config.SUDO_USERS or user_id == Config.OWNER_ID

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
    if is_admin(user_id):
        return "<code>👑 Admin (∞)</code>"
    else:
        try:
            from bot_helper.Database.User_Data import get_user_balance
            pts = get_user_balance(user_id)
            return f"<code>💎 {pts:,} Pts</code>"
        except Exception:
            return "<code>💎 0 Pts</code>"

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
# 4. KEYBOARD LAYOUTS (FINAL EDITION)
# ==========================================

def kb_start_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="👤 Owner", url="https://t.me/Krackxhor", style="primary"),
            InlineKeyboardButton(text="📢 Channel", url="https://t.me/TelMovIDCariFilm", style="primary")
        ],
        [
            InlineKeyboardButton(text="🚀 Dashboard", callback_data="menu_main", style="success")
        ]
    ])

def kb_main_menu(is_admin_user: bool = False) -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(text="🎞️ Encode", callback_data="menu_encode", style="primary"),
            InlineKeyboardButton(text="✂️ Editor", callback_data="menu_editor", style="primary")
        ],
        [
            InlineKeyboardButton(text="🎬 Creator", callback_data="menu_studio", style="primary"),
            InlineKeyboardButton(text="🤖 AI & Sub", callback_data="menu_ai", style="primary")
        ],
        [
            InlineKeyboardButton(text="📥 Download", callback_data="menu_download", style="primary"),
            InlineKeyboardButton(text="☁️ Cloud", callback_data="menu_cloud", style="primary")
        ],
        [
            InlineKeyboardButton(text="🎮 Aset", callback_data="menu_assets", style="primary"),
            InlineKeyboardButton(text="⚙️ Setting", callback_data="settings", style="primary"),
        ],
        [
            InlineKeyboardButton(text="💎 Top Up", callback_data="menu_vip", style="success")
        ]
    ]
    if is_admin_user:
        buttons.append([
            InlineKeyboardButton(text="🔧 Admin Panel", callback_data="menu_admin", style="primary")
        ])
    buttons.append([
        InlineKeyboardButton(text="❌ Tutup", callback_data="action_close", style="danger")
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def kb_cloud_mirror() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📁 GoFile", callback_data="cmd_gofile", style="primary"),
            InlineKeyboardButton(text="🔗 Pixeldrain", callback_data="cmd_pixeldrain", style="primary")
        ],
        [
            InlineKeyboardButton(text="🐝 Buzzheavier", callback_data="cmd_buzzheavier", style="primary"),
            InlineKeyboardButton(text="📦 Terabox", callback_data="cmd_terabox", style="primary")
        ],
        [
            InlineKeyboardButton(text="📺 YouTube", callback_data="cmd_youtube", style="primary"),
            InlineKeyboardButton(text="🎬 Vimeo", callback_data="cmd_vimeo", style="primary")
        ],
        [InlineKeyboardButton(text="🚀 Rclone Mirror", callback_data="cmd_rclone", style="success")],
        [InlineKeyboardButton(text="↩️ Kembali", callback_data="menu_main", style="danger")]
    ])

def kb_ai() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🧠 Auto Sub", callback_data="cmd_autosub", style="primary")],
        [
            InlineKeyboardButton(text="🌐 Auto Trans", callback_data="cmd_autotranslate", style="primary"),
            InlineKeyboardButton(text="📝 Sub Editor", callback_data="open_sub_workspace", style="primary")
        ],
        [InlineKeyboardButton(text="↩️ Kembali", callback_data="menu_main", style="danger")]
    ])

def kb_studio() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🎬 Recap", callback_data="cmd_recap", style="primary"),
            InlineKeyboardButton(text="🎥 Clip", callback_data="cmd_clip", style="primary")
        ],
        [
            InlineKeyboardButton(text="🏆 Top Tier", callback_data="info_studio_toptier", style="primary"),
            InlineKeyboardButton(text="📊 Verdict", callback_data="info_studio_verdict", style="primary")
        ],
        [
            InlineKeyboardButton(text="📖 Analisis", callback_data="info_studio_lore", style="primary"),
            InlineKeyboardButton(text="🎯 Radar", callback_data="info_studio_radar", style="primary")
        ],
        [
            InlineKeyboardButton(text="⚡ Patch", callback_data="info_studio_patch", style="primary"),
            InlineKeyboardButton(text="📚 Arsip", callback_data="info_studio_archives", style="primary")
        ],
        [InlineKeyboardButton(text="▶️ Upload YT", callback_data="cmd_ytupload", style="success")],
        [InlineKeyboardButton(text="↩️ Kembali", callback_data="menu_main", style="danger")]
    ])

def kb_encode_main() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🚀 Fast Encode", callback_data="menu_fast_encode", style="success"), 
            InlineKeyboardButton(text="🎛️ Custom", callback_data="cmd_customencode", style="primary")
        ],
        [
            InlineKeyboardButton(text="ℹ️ Info Engine", callback_data="info_encode", style="primary")
        ],
        [InlineKeyboardButton(text="↩️ Kembali", callback_data="menu_main", style="danger")]
    ])

def kb_fast_encode_submenu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🎥 Set Video", callback_data="video_settings", style="primary"),
            InlineKeyboardButton(text="🎵 Set Audio", callback_data="audio_settings", style="primary")
        ],
        [
            InlineKeyboardButton(text="🚜 Resolusi", callback_data="convert_settings", style="primary"), 
            InlineKeyboardButton(text="©️ Watermark", callback_data="watermark_settings", style="primary")
        ],
        [
            InlineKeyboardButton(text="🏷️ Metadata", callback_data="metadata_settings", style="primary")
        ],
        [InlineKeyboardButton(text="▶️ MULAI FAST ENCODE", callback_data="cmd_encode", style="success")], 
        [InlineKeyboardButton(text="↩️ Kembali ke Menu Encode", callback_data="menu_encode", style="danger")]
    ])

def kb_editor() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🗜️ Kompres", callback_data="cmd_compress", style="primary"),
            InlineKeyboardButton(text="🔄 Konversi", callback_data="cmd_convert", style="primary")
        ],
        [InlineKeyboardButton(text="🔗 Gabung", callback_data="cmd_merge", style="primary")],
        [
            InlineKeyboardButton(text="✂️ Trim", callback_data="cmd_trim", style="primary"),
            InlineKeyboardButton(text="🔪 Cut", callback_data="cmd_cut", style="primary"),
            InlineKeyboardButton(text="📐 Split", callback_data="cmd_split", style="primary")
        ],
        [
            InlineKeyboardButton(text="⚡ Speed", callback_data="cmd_speed", style="primary"),
            InlineKeyboardButton(text="📁 Ekstensi", callback_data="cmd_extension", style="primary")
        ],
        [
            InlineKeyboardButton(text="📐 Crop", callback_data="cmd_crop", style="primary"),
            InlineKeyboardButton(text="🎬 Auto Crop", callback_data="cmd_autocrop", style="primary"),
            InlineKeyboardButton(text="🔃 Rotasi", callback_data="cmd_rotate", style="primary")
        ],
        [InlineKeyboardButton(text="©️ Watermark", callback_data="cmd_watermark", style="primary")],
        [
            InlineKeyboardButton(text="🔇 Mute", callback_data="cmd_mute", style="primary"),
            InlineKeyboardButton(text="🎙️ Dubbing", callback_data="cmd_dubbing", style="primary")
        ],
        [
            InlineKeyboardButton(text="📌 Hardmux", callback_data="cmd_hardmux", style="primary"),
            InlineKeyboardButton(text="📝 Softmux", callback_data="cmd_softmux", style="primary"),
            InlineKeyboardButton(text="♻️ Remux", callback_data="cmd_softremux", style="primary")
        ],
        [
            InlineKeyboardButton(text="🏷️ Metadata", callback_data="cmd_changemetadata", style="primary"),
            InlineKeyboardButton(text="🔀 Index", callback_data="cmd_changeindex", style="primary")
        ],
        [InlineKeyboardButton(text="📥 Ekstrak", callback_data="cmd_extract", style="primary")],
        [
            InlineKeyboardButton(text="📸 SS", callback_data="cmd_genss", style="primary"),
            InlineKeyboardButton(text="🎞️ Sample", callback_data="cmd_gensample", style="primary")
        ],
        [
            InlineKeyboardButton(text="ℹ️ Info", callback_data="cmd_mediainfo", style="primary"),
            InlineKeyboardButton(text="↩️ Kembali", callback_data="menu_main", style="danger")
        ]
    ])

def kb_assets() -> InlineKeyboardMarkup:
    """[FIX v7.0] Menyesuaikan tombol dengan command asset_handlers.py"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="➕ Add Video", callback_data="cmd_addaset", style="success"),
            InlineKeyboardButton(text="🔊 Add Audio", callback_data="cmd_addsfx", style="success")
        ],
        [
            InlineKeyboardButton(text="📋 List Video", callback_data="cmd_viewaset", style="primary"),
            InlineKeyboardButton(text="🎵 List Audio", callback_data="cmd_viewsfx", style="primary")
        ],
        [
            InlineKeyboardButton(text="🗑️ Del Video", callback_data="cmd_delaset", style="danger"),
            InlineKeyboardButton(text="🗑️ Del Audio", callback_data="cmd_delsfx", style="danger")
        ],
        [InlineKeyboardButton(text="↩️ Kembali", callback_data="menu_main", style="danger")]
    ])

def kb_download() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📥 Leech URL", callback_data="cmd_leech", style="primary"),
            InlineKeyboardButton(text="☁️ Mirror URL", callback_data="cmd_mirror", style="primary")
        ],
        [InlineKeyboardButton(text="↩️ Kembali", callback_data="menu_main", style="danger")]
    ])

def kb_settings() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="💾 Rclone", callback_data="cmd_saveconfig", style="success"),
            InlineKeyboardButton(text="🖼️ Thumb", callback_data="cmd_savethumb", style="success")
        ],
        [
            InlineKeyboardButton(text="📥 Add WM", callback_data="cmd_savewatermark", style="success"),
            InlineKeyboardButton(text="🤖 Set Bot", callback_data="settings_bot", style="primary")
        ],
        [
            InlineKeyboardButton(text="🔗 Rule Merge", callback_data="merge_settings", style="primary"),
            InlineKeyboardButton(text="📝 Rule Mux", callback_data="mux_settings", style="primary")
        ],
        [InlineKeyboardButton(text="↩️ Kembali", callback_data="menu_main", style="danger")]
    ])

def kb_vip() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="💳 Dompet", callback_data="cmd_myvip", style="primary"),
            InlineKeyboardButton(text="📜 Mutasi", callback_data="cmd_history", style="primary") 
        ],
        [InlineKeyboardButton(text="💎 Top-Up (Verify)", callback_data="cmd_verify", style="success")],
        [InlineKeyboardButton(text="↩️ Kembali", callback_data="menu_main", style="danger")]
    ])

def kb_admin() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📊 Status", callback_data="cmd_status", style="primary"),
            InlineKeyboardButton(text="⏱️ Uptime", callback_data="cmd_time", style="primary"),
            InlineKeyboardButton(text="⚡ Speed", callback_data="cmd_speedtest", style="primary")
        ],
        [
            InlineKeyboardButton(text="📈 Stats", callback_data="cmd_stats", style="primary"),
            InlineKeyboardButton(text="📜 Log", callback_data="cmd_log", style="primary"),
            InlineKeyboardButton(text="📁 DL Logs", callback_data="cmd_logs", style="primary")
        ],
        [
            InlineKeyboardButton(text="🔄 Cek Cfg", callback_data="cmd_changeconfig", style="primary"),
            InlineKeyboardButton(text="🗑️ Del Cfg", callback_data="cmd_clearconfigs", style="danger")
        ],
        [
            InlineKeyboardButton(text="🧹 Clean", callback_data="cmd_renew", style="primary"),
            InlineKeyboardButton(text="💥 Reset DB", callback_data="cmd_resetdb", style="danger")
        ],
        [
            InlineKeyboardButton(text="👮 Sudo", callback_data="cmd_checksudo", style="primary"),
            InlineKeyboardButton(text="💎 Top Spender", callback_data="cmd_view_vip", style="primary") 
        ],
        [
            InlineKeyboardButton(text="➕ Sudo", callback_data="cmd_addsudo", style="success"),
            InlineKeyboardButton(text="➖ Sudo", callback_data="cmd_delsudo", style="danger")
        ],
        [
            InlineKeyboardButton(text="➕ Poin", callback_data="cmd_add_vip", style="success"),
            InlineKeyboardButton(text="➖ Poin", callback_data="cmd_delete_vip", style="danger")
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

@ui_router.callback_query(F.data == "menu_cloud")
async def nav_cloud(callback: CallbackQuery):
    text = create_section_header("☁️", "Cloud & Mirroring", "Unggah file Anda ke berbagai provider cloud secara instan tanpa memakan kuota lokal.")
    await safe_edit(callback.message, text, kb_cloud_mirror())
    await callback.answer()

@ui_router.callback_query(F.data == "menu_studio")
async def nav_studio(callback: CallbackQuery):
    text = create_section_header("🎬", "Creator", "Produksi video otomatis dengan AI, script, dan rendering")
    await safe_edit(callback.message, text, kb_studio())
    await callback.answer()

@ui_router.callback_query(F.data == "menu_ai")
async def nav_ai(callback: CallbackQuery):
    text = create_section_header("🤖", "AI & Subtitle", "Generate subtitle otomatis (Speech-to-Text), terjemahkan file subtitle menggunakan AI Whisper, atau edit subtitle secara manual.")
    await safe_edit(callback.message, text, kb_ai())
    await callback.answer()

@ui_router.callback_query(F.data == "menu_encode")
async def nav_encode(callback: CallbackQuery):
    text = create_section_header("🎞️", "Encode & Profil", "Pilih metode kompresi video Anda.")
    await safe_edit(callback.message, text, kb_encode_main())
    await callback.answer()

@ui_router.callback_query(F.data == "menu_fast_encode")
async def nav_fast_encode(callback: CallbackQuery):
    text = create_section_header("🚀", "Fast Encode Studio", "Sebelum memulai Fast Encode, pastikan preferensi Kualitas, Resolusi, dan Metadata Anda sudah benar.\n\nJika sudah siap, klik 'MULAI FAST ENCODE'.")
    await safe_edit(callback.message, text, kb_fast_encode_submenu())
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
    text = create_section_header("🎮", "Brankas Aset", "Kelola footage video mentahan, sound effects, dan media pribadi Anda.")
    await safe_edit(callback.message, text, kb_assets())
    await callback.answer()

@ui_router.callback_query(F.data == "menu_download")
async def nav_download(callback: CallbackQuery):
    text = create_section_header("📥", "Download", "Download file dari URL publik atau ubah menjadi Mirror Rclone")
    await safe_edit(callback.message, text, kb_download())
    await callback.answer()

@ui_router.callback_query(F.data == "settings")
async def nav_settings(callback: CallbackQuery):
    text = create_section_header("⚙️", "Pengaturan Global", "Konfigurasi engine bot, Rclone, file sistem, dan aturan Muxing/Merge.")
    await safe_edit(callback.message, text, kb_settings())
    await callback.answer()

@ui_router.callback_query(F.data == "menu_vip")
async def nav_vip(callback: CallbackQuery):
    text = create_section_header("💎", "Top Up & Dompet", "Kelola saldo poin, mutasi pemakaian, dan top-up (Verifikasi Trakteer)")
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

<b>🚀 Fast Encode</b>
Encode otomatis menggunakan profil yang tersimpan di 'Set Video', 'Set Audio', dan 'Resolusi'.
Pastikan Anda sudah mengaturnya sebelum klik tombol ini.

<b>🎛️ Custom Encode</b>
Anda akan diminta memasukkan teks perintah FFMpeg secara manual secara interaktif. 
Cocok untuk pengguna mahir.

<b>{BORDER_LIGHT}</b>
"""
    await safe_edit(callback.message, info_text, InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="↩️ Kembali", callback_data="menu_encode", style="danger")]]))
    await callback.answer()

@ui_router.callback_query(F.data.startswith("info_studio_"))
async def info_studio_modes(callback: CallbackQuery):
    mode = callback.data.split("_")[2]
    
    themes = {
        "toptier": "🏆 **TOP TIER (Emas)**\nCocok untuk video peringkat atau listicle (Contoh: Top 10 Game RPG). Menampilkan badge emas elegan.",
        "verdict": "📊 **THE VERDICT (Merah)**\nCocok untuk video ulasan akhir atau kesimpulan. Menampilkan kartu skor dan rating bintang.",
        "lore": "📖 **LORE & CONSPIRACIES (Netflix Red)**\nCocok untuk video cerita mendalam, teori konspirasi, atau penjelasan sejarah game.",
        "radar": "🎯 **ON THE RADAR (Cyber Cyan)**\nCocok untuk membahas game yang akan rilis, rumor, atau ekspektasi masa depan.",
        "patch": "⚡ **THE LATEST PATCH (News Red)**\nCocok untuk berita kilat, update game terbaru, atau patch notes.",
        "archives": "📚 **THE ARCHIVES (Retro Amber)**\nCocok untuk video nostalgia, membahas game lawas, atau sejarah developer."
    }
    
    desc = themes.get(mode, "Mode Produksi Creator")
    
    info_text = f"""
<b>╭─ ℹ️ CARA PAKAI: MODE CREATOR ─╮</b>

{desc}

<b>💡 CARA PENGGUNAAN (ONE-CLICK):</b>
Anda tidak perlu menekan tombol ini. Sistem kami sudah dibuat sangat pintar!

1. Siapkan naskah (Script) Anda dalam file berformat <code>.txt</code>.
2. Kirimkan file <code>.txt</code> tersebut langsung ke chat ini.
3. Bot akan otomatis mendeteksi file tersebut dan memunculkan Menu Creator secara instan!

<b>{BORDER_LIGHT}</b>
"""
    await safe_edit(callback.message, info_text, InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="↩️ Kembali ke Creator", callback_data="menu_studio", style="primary")]
    ]))
    await callback.answer()

# ==========================================
# 7. COMMAND ROUTER
# ==========================================

@ui_router.callback_query(F.data.startswith("cmd_"))
async def route_commands(callback: CallbackQuery):
    cmd = callback.data.split("_", 1)[1]
    user_id = callback.from_user.id

    try:
        import bot.admin_handlers as adm
        import bot.media_handlers as med
        import bot.advanced_media_handlers as adv
        import bot.vip_handlers as vip
        import bot.subtitle_handlers as sub
        import bot.MovieRecap as recap
        import bot.Gameplay as gp
        import bot.AutoClip as autoclip
        import bot.YTUpload as yt
        import bot.CloudUploads as cloud 
        import bot.asset_handlers as asset # [NEW v7.0] Asset Import
    except Exception as import_err:
        print(f"[UI ROUTER IMPORT ERROR] {import_err}")
        return await callback.answer("❌ Gagal memuat module handler.", show_alert=True)

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

        # [FIX v7.0] MAPPING ULANG KE ASSET HANDLER
        "addaset": getattr(asset, "addaset_handler", None),
        "viewaset": getattr(asset, "viewaset_handler", None),
        "delaset": getattr(asset, "delaset_handler", None),
        "addsfx": getattr(asset, "addsfx_handler", None),
        "viewsfx": getattr(asset, "viewsfx_handler", None),
        "delsfx": getattr(asset, "delsfx_handler", None),

        "recap": getattr(recap, "recap_handler", None),
        "clip": getattr(autoclip, "autoclip_handler", None),
        "ytupload": getattr(yt, "ytupload_handler", None),
        "youtube": getattr(cloud, "cmd_youtube_alias", None), 

        "encode": getattr(med, "_encode_video", None),
        "customencode": getattr(med, "_custom_encode_video", None),
        "compress": getattr(med, "_compress_video", None),
        "convert": getattr(med, "_convert_video", None),
        "merge": getattr(med, "_merge_videos", None),
        "speed": getattr(med, "_speed_video", None),
        "mute": getattr(med, "_mute_video", None),
        "dubbing": getattr(med, "_dubbing_video", None),
        "softmux": getattr(med, "_softmux", None),
        "hardmux": getattr(med, "_hardmux", None),
        "softremux": getattr(med, "_softremux", None),

        "watermark": getattr(med, "_add_watermark_interactive", None),
        "extract": getattr(med, "_extract_streams", None) or getattr(adv, "_extract_streams", None),
        "extension": getattr(med, "_extension_changer", None) or getattr(adv, "_extension_changer", None),
        "changeindex": getattr(med, "_change_index", None) or getattr(adv, "_change_index", None),
        "changemetadata": getattr(med, "_change_metadata", None) or getattr(adv, "_change_metadata", None),
        "mediainfo": getattr(med, "_media_info", None) or getattr(adv, "_media_info", None),

        "trim": getattr(adv, "_trim_video", None),
        "split": getattr(adv, "_split_video", None),
        "cut": getattr(adv, "_cut_video", None),
        "rotate": getattr(adv, "_rotate_video", None),
        "crop": getattr(adv, "_crop_video", None),
        "autocrop": getattr(adv, "_autocrop_video", None),
        "genss": getattr(adv, "_gen_screenshots", None) or getattr(med, "_gen_screenshots", None),
        "gensample": getattr(adv, "_gen_video_sample", None) or getattr(med, "_gen_video_sample", None),
        "ext_thumb": getattr(adv, "_extract_thumbnail", None),
        "ext_frames": getattr(adv, "_extract_frames_zip", None),

        "leech": getattr(med, "_leech_file", None),
        "mirror": getattr(med, "_mirror_file", None),
        "status": getattr(med, "_status", None),

        "verify": getattr(vip, "_verify_payment", None),
        "myvip": getattr(vip, "_my_vip_status", None),
        "history": getattr(vip, "_my_usage_history", None), 
        "add_vip": getattr(vip, "_add_vip_manual", None),
        "delete_vip": getattr(vip, "_delete_vip_manual", None),
        "view_vip": getattr(vip, "_view_vip_list", None),

        "autosub": getattr(sub, "autosub_handler", None),
        "autotranslate": getattr(sub, "autotranslate_handler", None),
        
        "gofile": getattr(cloud, "cmd_gofile", None),
        "pixeldrain": getattr(cloud, "cmd_pixeldrain", None),
        "buzzheavier": getattr(cloud, "cmd_buzzheavier", None),
        "terabox": getattr(cloud, "cmd_terabox", None),
        "vimeo": getattr(cloud, "cmd_vimeo", None),
        "rclone": getattr(cloud, "cmd_rclone", None),
    }

    admin_cmds = {
        "speedtest", "restart", "renew", "log", "logs", "resetdb",
        "checksudo", "time", "stats", "add_vip", "delete_vip",
        "view_vip", "addsudo", "delsudo", "changeconfig", "clearconfigs",
        "saveconfig", "savewatermark", "savethumb", "status", "verify", "myvip", "history",
    }

    media_cmds = {
        "encode", "customencode", "compress", "convert", "merge", "speed",
        "mute", "dubbing", "softmux", "hardmux", "softremux", "watermark",
        "extract", "extension", "changeindex", "changemetadata", "mediainfo",
        "trim", "split", "cut", "rotate", "crop", "autocrop", "genss",
        "gensample", "ext_thumb", "ext_frames", "autosub", "autotranslate", 
        "leech", "mirror", "addaset", "addsfx", "delaset", "delsfx", "recap", "clip", # Ditambah addaset, addsfx
        "ytupload", "gofile", "pixeldrain", "buzzheavier", "terabox", "vimeo", "rclone", "youtube"
    }

    if cmd in admin_cmds and not is_admin(user_id) and cmd not in ["status", "verify", "myvip", "history"]:
        return await callback.answer("⛔ Akses ditolak", show_alert=True)

    try:
        handler = handlers.get(cmd)
        if not handler:
            return await callback.answer(f"Module {cmd} belum tersedia.", show_alert=True)

        if cmd in media_cmds:
            await callback.answer()
            
            # [FIX v7.0] PROMPT CERDAS SESUAI FITUR ASET
            if cmd == "addaset":
                media_type = "File Video (MP4/MKV/DSB)"
            elif cmd == "addsfx":
                media_type = "File Audio/MP3"
            elif cmd == "autosub":
                media_type = "Video atau Audio"
            elif cmd == "autotranslate":
                media_type = "File Subtitle (.srt / .ass)"
            elif cmd in ["savethumb", "savewatermark"]:
                media_type = "Gambar / Foto"
            elif cmd in ["gofile", "pixeldrain", "buzzheavier", "terabox", "vimeo", "rclone", "youtube", "ytupload"]:
                media_type = "File / Video / Dokumen"
            elif cmd in ["recap", "clip"]:
                media_type = "File Naskah (.txt)"
            elif cmd in ["delaset", "delsfx"]:
                media_type = "Teks (Nama file yang ingin dihapus)"
            else:
                media_type = "Media (Video/Audio/Srt/Gambar)"

            prompt = await callback.message.answer(
                f"📥 <b>MODE {cmd.upper()} AKTIF</b>\n"
                f"────────────────────\n"
                f"Silakan kirim atau balas dengan <b>{media_type}</b> Anda ke chat ini sekarang...\n\n"
                f"<i>(Waktu tunggu 120 detik)</i>",
                parse_mode="HTML"
            )

            from bot.shared import wait_for_message
            try:
                response_msg = await wait_for_message(callback.message.chat.id, user_id, timeout=120)
            except asyncio.TimeoutError:
                response_msg = None

            if not response_msg:
                return await prompt.edit_text(
                    "❌ <b>Dibatalkan:</b> Waktu habis (120 detik) atau input tidak valid.\n"
                    "Silakan buka menu kembali.", 
                    parse_mode="HTML"
                )

            await prompt.delete()

            fake_msg = response_msg.model_copy(update={
                "text": f"/{cmd}",
                "reply_to_message": response_msg
            })
            return await handler(fake_msg)

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
            pass

# ==========================================
# 8. GLOBAL ACTIONS
# ==========================================

@ui_router.callback_query(F.data == "action_close")
async def action_close(callback: CallbackQuery):
    try:
        await callback.message.delete()
    except:
        pass
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
