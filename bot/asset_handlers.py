"""
╔══════════════════════════════════════════════════════════════════════╗
║    bot/asset_handlers.py — v2.3 (PERSONAL ASSET VAULT)               ║
║    Mengelola Aset Video & Audio (SFX/BGM) untuk Studio               ║
╠══════════════════════════════════════════════════════════════════════╣
║  Fitur Baru: Setiap pengguna (user) kini memiliki folder atau        ║
║  "Brankas Aset" mereka sendiri berdasarkan User ID. User A tidak     ║
║  akan bisa mengakses atau melihat aset milik User B.                 ║
╚══════════════════════════════════════════════════════════════════════╝
"""

import os
import re
import time
import asyncio
from aiogram import Router, F
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.filters import Command, CommandObject
from moviepy import VideoFileClip

from bot_helper.Telegram.Telegram_Client import Telegram
from bot_helper.Others.Helper_Functions import get_human_size
from config.config import Config
from bot.shared import CMD_SUFFIX

router = Router()

# Base directory (Absolute)
BASE_DIR = os.path.abspath(os.getcwd())
ASET_VIDEO_BASE = os.path.join(BASE_DIR, "aset_video")
AUDIO_BASE = os.path.join(BASE_DIR, "audio")

# Pastikan direktori dasar ada
os.makedirs(ASET_VIDEO_BASE, exist_ok=True)
os.makedirs(AUDIO_BASE, exist_ok=True)

# ─── HELPERS ───

def get_user_dir(user_id: int, base_folder: str) -> str:
    """Mengembalikan jalur absolut khusus untuk user tersebut, misal: /app/aset_video/123456789"""
    # Jika user adalah admin, bisa juga memberikan opsi untuk save di root/global (opsional), 
    # tapi demi kerapian, kita buatkan folder berdasarkan ID-nya juga.
    user_dir = os.path.join(base_folder, str(user_id))
    os.makedirs(user_dir, exist_ok=True)
    return user_dir

def safe_filename(name: str, ext: str = ".mp4") -> str:
    clean = re.sub(r'[^\w\-_. ]', '_', name).strip()
    return clean if clean.lower().endswith(ext) else clean + ext

async def download_with_progress(message: Message, reply_msg: Message, dest: str, label: str, status_msg: Message) -> bool:
    target_media = reply_msg.video or reply_msg.document or reply_msg.audio or reply_msg.voice
    if not target_media: return False
    
    last_edit = 0.0
    async def _progress(current: int, total: int):
        nonlocal last_edit
        now = time.time()
        if now - last_edit >= 2.0 and status_msg:
            pct = current / total if total else 0
            bar = "█" * int(pct * 10) + "░" * (10 - int(pct * 10))
            try: 
                await status_msg.edit_text(f"⏳ 🔽 **Mengunduh {label}...**\n\n`[{bar}]` **{pct*100:.1f}%**\n📥 `{get_human_size(current)} / {get_human_size(total)}`")
            except: pass
            last_edit = now

    try:
        pyro_msg = await Telegram.PYROGRAM_CLIENT.get_messages(reply_msg.chat.id, reply_msg.message_id)
        await Telegram.PYROGRAM_CLIENT.download_media(message=pyro_msg, file_name=dest, progress=_progress)
        return os.path.exists(dest)
    except:
        try:
            await Telegram.AIOGRAM_BOT.download(target_media, destination=dest)
            return os.path.exists(dest)
        except: return False

def get_asset_info(folder_path: str, extensions: tuple) -> tuple:
    """Mengambil daftar aset dan menghitung ukuran totalnya."""
    assets = []
    total_size = 0
    if not os.path.exists(folder_path):
        return assets, total_size
        
    for f in os.listdir(folder_path):
        if f.lower().endswith(extensions):
            full_path = os.path.join(folder_path, f)
            size = os.path.getsize(full_path)
            total_size += size
            assets.append((f, size, full_path))
    assets.sort(key=lambda x: x[0])
    return assets, total_size


# ═══════════════════════════════════════════════════════════════════════
#  MANAJEMEN ASET VIDEO (PERSONAL)
# ═══════════════════════════════════════════════════════════════════════

@router.message(Command(f"addaset{CMD_SUFFIX}"))
async def addaset_handler(message: Message, command: CommandObject) -> None:
    # [FIX] Sekarang SEMUA user bisa menambahkan aset, tapi masuk ke folder pribadi mereka.
    user_id = message.from_user.id
    if not message.reply_to_message or not (message.reply_to_message.video or message.reply_to_message.document):
        return await message.reply("❌ **Cara Pakai:**\nBalas sebuah Video lalu ketik `/addaset{CMD_SUFFIX} Nama Video`")
    
    custom_name = (command.args or "").strip()
    if custom_name: file_name = safe_filename(custom_name)
    else:
        doc = message.reply_to_message.document or message.reply_to_message.video
        file_name = re.sub(r'[^\w\-_. ]','_', doc.file_name) if getattr(doc, 'file_name', None) else f"video_{message.message_id}.mp4"
        
    # Ambil direktori khusus user ini
    user_dir = get_user_dir(user_id, ASET_VIDEO_BASE)
    final_path = os.path.join(user_dir, file_name)
    
    status_msg = await message.reply(f"⏳ Menyimpan ke Brankas Pribadi: `{file_name}`...")
    
    if await download_with_progress(message, message.reply_to_message, final_path, f"{file_name}", status_msg): 
        try:
            clip = VideoFileClip(final_path)
            w, h, d = clip.w, clip.h, clip.duration
            clip.close()
            f_size = get_human_size(os.path.getsize(final_path))
            
            teks_sukses = (
                f"✅ **ASET VIDEO TERSIMPAN! (Private)**\n"
                f"`━━━━━━━━━━━━━━━━━━━━━━━━━━`\n"
                f"📁 **File:** `{file_name}`\n"
                f"📍 **Path FFmpeg:** `{final_path}`\n"
                f"📐 **Resolusi:** `{w}×{h}`\n"
                f"⏱ **Durasi:** `{d:.1f} detik`\n"
                f"💾 **Ukuran:** `{f_size}`\n"
                f"`━━━━━━━━━━━━━━━━━━━━━━━━━━`\n"
            )
            await status_msg.edit_text(teks_sukses)
        except:
            await status_msg.edit_text(f"✅ **Tersimpan di Brankas:** `{file_name}`\n📍 Path FFmpeg: `{final_path}`")
    else:
        await status_msg.edit_text("❌ Gagal mengunduh video.")

@router.message(Command(f"viewaset{CMD_SUFFIX}"))
async def viewaset_handler(message: Message) -> None:
    user_id = message.from_user.id
    user_dir = get_user_dir(user_id, ASET_VIDEO_BASE)
    
    assets, total_size = get_asset_info(user_dir, ('.mp4', '.mkv', '.avi', '.mov'))
    if not assets: return await message.answer(f"❌ Brankas video Anda masih kosong.\nSilakan balas video dengan `/addaset{CMD_SUFFIX}`")
    
    lines = [
        "🗂 **BRANKAS VIDEO PRIBADI ANDA**",
        f"👤 User ID: `{user_id}`",
        f"`━━━━━━━━━━━━━━━━━━━━━━━━━━━━━`"
    ]
    
    for i, (name, size, full_path) in enumerate(assets, 1):
        size_str = get_human_size(size)
        lines.append(f"**{i}.** `{name}` _({size_str})_")
        lines.append(f"   └ 📍 `{full_path}`")
        
    lines.append(f"`━━━━━━━━━━━━━━━━━━━━━━━━━━━━━`")
    lines.append(f"📊 **Kapasitas Terpakai:** `{get_human_size(total_size)}`")
    
    btn = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🗑️ Cara Hapus Aset", callback_data="help_delaset", style="danger")]])
    await message.answer("\n".join(lines), reply_markup=btn)

@router.message(Command(f"delaset{CMD_SUFFIX}"))
async def delaset_handler(message: Message, command: CommandObject) -> None:
    user_id = message.from_user.id
    name = (command.args or "").strip()
    if not name: return await message.reply("❌ Format: `/delaset{CMD_SUFFIX} nama_file.mp4`")
    
    user_dir = get_user_dir(user_id, ASET_VIDEO_BASE)
    path = os.path.join(user_dir, name)
    
    if os.path.exists(path):
        os.remove(path)
        await message.reply(f"✅ **Video berhasil dihapus dari Brankas:**\n🗑 `{name}`")
    else:
        await message.reply(f"❌ File `{name}` tidak ditemukan di Brankas Anda.")


# ═══════════════════════════════════════════════════════════════════════
#  MANAJEMEN ASET AUDIO (PERSONAL)
# ═══════════════════════════════════════════════════════════════════════

@router.message(Command(f"addsfx{CMD_SUFFIX}", f"adsfx{CMD_SUFFIX}"))
async def addsfx_handler(message: Message, command: CommandObject) -> None:
    user_id = message.from_user.id
    if not message.reply_to_message or not (message.reply_to_message.audio or message.reply_to_message.voice or message.reply_to_message.document):
        return await message.reply("❌ **Cara Pakai:**\nBalas file MP3/Audio lalu ketik `/addsfx{CMD_SUFFIX} nama_sfx`")

    raw_text = (command.args or "").strip()
    if not raw_text: return await message.reply("❌ Berikan nama file! Contoh: `/addsfx sfx_impact`")
    
    file_name = safe_filename(raw_text, ext=".mp3")
    user_dir = get_user_dir(user_id, AUDIO_BASE)
    final_path = os.path.join(user_dir, file_name)
    
    status_msg = await message.reply(f"⏳ Mengunduh SFX ke Brankas Pribadi: `{file_name}`...")
    
    if await download_with_progress(message, message.reply_to_message, final_path, "SFX", status_msg):
        f_size = get_human_size(os.path.getsize(final_path))
        await status_msg.edit_text(f"✅ **AUDIO TERSIMPAN! (Private)**\n🎵 `{file_name}` _({f_size})_\n📍 **Path:** `{final_path}`")
    else:
        await status_msg.edit_text("❌ Gagal mengunduh audio.")

@router.message(Command(f"viewsfx{CMD_SUFFIX}"))
async def viewsfx_handler(message: Message) -> None:
    user_id = message.from_user.id
    user_dir = get_user_dir(user_id, AUDIO_BASE)
    
    assets, total_size = get_asset_info(user_dir, ('.mp3', '.wav', '.ogg', '.m4a'))
    if not assets: return await message.answer(f"❌ Brankas audio Anda masih kosong.\nSilakan balas audio dengan `/addsfx{CMD_SUFFIX}`")
    
    lines = [
        "🎵 **BRANKAS AUDIO PRIBADI ANDA**",
        f"👤 User ID: `{user_id}`",
        f"`━━━━━━━━━━━━━━━━━━━━━━━━━━━━━`"
    ]
    
    for i, (name, size, full_path) in enumerate(assets, 1):
        size_str = get_human_size(size)
        lines.append(f"**{i}.** `{name}` _({size_str})_")
        lines.append(f"   └ 📍 `{full_path}`")
        
    lines.append(f"`━━━━━━━━━━━━━━━━━━━━━━━━━━━━━`")
    lines.append(f"📊 **Kapasitas Terpakai:** `{get_human_size(total_size)}`")
    
    btn = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🗑️ Cara Hapus Audio", callback_data="help_delsfx", style="danger")]])
    await message.answer("\n".join(lines), reply_markup=btn)

@router.message(Command(f"delsfx{CMD_SUFFIX}"))
async def delsfx_handler(message: Message, command: CommandObject) -> None:
    user_id = message.from_user.id
    name = (command.args or "").strip()
    if not name: return await message.reply("❌ Format: `/delsfx{CMD_SUFFIX} nama_file.mp3`")
    
    if not name.endswith(".mp3"): name += ".mp3"
    user_dir = get_user_dir(user_id, AUDIO_BASE)
    path = os.path.join(user_dir, name)
    
    if os.path.exists(path):
        os.remove(path)
        await message.reply(f"✅ **Audio berhasil dihapus dari Brankas:**\n🗑 `{name}`")
    else:
        await message.reply(f"❌ File `{name}` tidak ditemukan di Brankas Anda.")

# ─── CALLBACK BANTUAN HAPUS ───
@router.callback_query(F.data == "help_delaset")
async def help_delaset_cb(call: CallbackQuery) -> None: 
    await call.answer()
    await call.message.answer(f"Hapus video? Ketik perintah:\n`/delaset{CMD_SUFFIX} nama_file.mp4`")

@router.callback_query(F.data == "help_delsfx")
async def help_delsfx_cb(call: CallbackQuery) -> None: 
    await call.answer()
    await call.message.answer(f"Hapus audio? Ketik perintah:\n`/delsfx{CMD_SUFFIX} nama_file.mp3`")
