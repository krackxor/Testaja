"""
╔══════════════════════════════════════════════════════════════════════╗
║    bot/CloudUploads.py — v2.1 (ULTIMATE MIRROR + PRIVATE API)        ║
║    Terintegrasi dengan Unified Engine & Pay-As-You-Go System         ║
╠══════════════════════════════════════════════════════════════════════╣
║  FITUR PROVIDER:                                                     ║
║  - /gofile       : Mendukung API Key Pribadi / Anonymous             ║
║  - /pixeldrain   : Mendukung API Key Pribadi / Anonymous             ║
║  - /buzzheavier  : Upload Anonymous API                              ║
║  - /terabox      : (Kunci Global di config.env)                      ║
║  - /vimeo        : (Kunci Global di config.env)                      ║
║  - /rclone       : Mirror ke Cloud Storage via rclone.conf user      ║
╚══════════════════════════════════════════════════════════════════════╝
"""

import asyncio
import os
import time
import subprocess
import aiohttp
from aiogram import Router, F
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command

from bot_helper.Process.Unified_Engine import execute_unified_task
from bot_helper.Process.point_manager import process_payment
from bot_helper.Telegram.Telegram_Client import Telegram
from bot_helper.Database.User_Data import get_data
from config.config import Config

LOGGER     = Config.LOGGER
CMD_SUFFIX = Config.CMD_SUFFIX
router     = Router()

TEMP_DIR = "./temp/cloud_uploads/"
os.makedirs(TEMP_DIR, exist_ok=True)

# ==========================================
#  API CLOUD PROVIDERS (UPLOAD LOGIC)
# ==========================================

async def upload_to_gofile(file_path: str, api_token: str = "") -> str:
    """Upload ke GoFile. Mendukung API Token jika diberikan."""
    async with aiohttp.ClientSession() as session:
        async with session.get("https://api.gofile.io/servers") as resp:
            data = await resp.json()
            if data["status"] != "ok": raise Exception("GoFile API Error")
            server = data["data"]["servers"][0]["name"]
        
        with open(file_path, 'rb') as f:
            form_data = aiohttp.FormData()
            form_data.add_field('file', f, filename=os.path.basename(file_path))
            if api_token:
                form_data.add_field('token', api_token) # Gunakan token user jika ada
                
            async with session.post(f"https://{server}.gofile.io/contents/uploadfile", data=form_data) as upload_resp:
                res = await upload_resp.json()
                if res["status"] != "ok": raise Exception("Gagal mengunggah ke GoFile")
                return res["data"]["downloadPage"]

async def upload_to_pixeldrain(file_path: str, api_key: str = "") -> str:
    """Upload ke Pixeldrain. Mendukung Basic Auth (API Key) jika diberikan."""
    # Pixeldrain menggunakan HTTP Basic Auth untuk API Key. Username kosong, password = API Key.
    auth = aiohttp.BasicAuth("", api_key) if api_key else None
    
    async with aiohttp.ClientSession() as session:
        with open(file_path, 'rb') as f:
            async with session.put("https://pixeldrain.com/api/file", data=f, auth=auth) as resp:
                res = await resp.json()
                if not res.get("success"): raise Exception("Gagal mengunggah ke Pixeldrain")
                return f"https://pixeldrain.com/u/{res['id']}"

async def upload_to_buzzheavier(file_path: str) -> str:
    """Upload ke Buzzheavier."""
    async with aiohttp.ClientSession() as session:
        with open(file_path, 'rb') as f:
            form_data = aiohttp.FormData()
            form_data.add_field('file', f, filename=os.path.basename(file_path))
            async with session.post("https://buzzheavier.com/api/upload", data=form_data) as resp:
                if resp.status != 200: raise Exception(f"HTTP Error {resp.status} dari Buzzheavier")
                try:
                    res = await resp.json()
                    return res.get("url", "https://buzzheavier.com/ (Cek Dashboard)")
                except:
                    return "https://buzzheavier.com/ (Upload selesai, cek dashboard Anda)"

async def upload_to_vimeo(file_path: str) -> str:
    """Upload ke Vimeo (Menggunakan Kunci Global dari config.env)."""
    token = getattr(Config, "VIMEO_TOKEN", None)
    if not token:
        raise Exception("VIMEO_TOKEN tidak ditemukan di sistem. Fitur ini dimatikan.")
    
    import vimeo # pip install PyVimeo
    client = vimeo.VimeoClient(token=token, key="dummy", secret="dummy")
    file_name = os.path.basename(file_path)
    try:
        def _sync_upload():
            uri = client.upload(file_path, data={'name': file_name, 'privacy': {'view': 'unlisted'}})
            video_data = client.get(uri + '?fields=link').json()
            return video_data.get('link')
        return await asyncio.to_thread(_sync_upload)
    except Exception as e:
        raise Exception(f"Gagal mengunggah ke Vimeo: {e}")

async def upload_to_terabox(file_path: str) -> str:
    """Upload ke Terabox (Menggunakan Cookie Global)."""
    raise Exception("Integrasi Terabox sedang dalam perbaikan akibat proteksi anti-bot tingkat tinggi.")

async def upload_via_rclone(file_path: str, user_id: int) -> str:
    """Upload file ke Cloud Storage pengguna menggunakan konfigurasi Rclone."""
    r_config = f"./userdata/{user_id}_rclone.conf"
    if not os.path.exists(r_config):
        raise Exception("Konfigurasi Rclone tidak ditemukan. Gunakan `/saveconfig` terlebih dahulu.")
        
    drive_name = get_data().get(user_id, {}).get("drive_name", "")
    if not drive_name:
        raise Exception("Drive Rclone belum dipilih. Atur di menu Settings.")

    file_name = os.path.basename(file_path)
    dest_path = f"{drive_name}:/StudioKhoirul_Uploads/"
    
    cmd = [
        "rclone", "copy", file_path, dest_path,
        "--config", r_config,
        "--progress", "--ignore-existing"
    ]
    
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
        
        if proc.returncode != 0:
            raise Exception(f"Rclone Error: {stderr.decode('utf-8')}")
            
        return f"Berhasil diunggah ke Drive: `{drive_name}`\nFolder: `StudioKhoirul_Uploads/`"
    except Exception as e:
        raise Exception(f"Proses Rclone gagal: {e}")


# ═══════════════════════════════════════════════════════════════════════
#  CORE LOGIC (UNIFIED ENGINE)
# ═══════════════════════════════════════════════════════════════════════

async def _core_cloud_upload_logic(message: Message, ui, reply_msg: Message, provider: str, fname: str) -> None:
    file_path = os.path.join(TEMP_DIR, f"dl_{message.message_id}_{fname}")
    user_id = message.from_user.id
    
    try:
        # Ambil API Key pengguna (jika ada)
        user_keys = get_data().get(user_id, {}).get("cloud_keys", {})
        
        # ── STEP 1: Download dari Telegram ──────────────────────────
        target_media = reply_msg.video or reply_msg.document or reply_msg.audio
        if not target_media: raise RuntimeError("Pesan tidak mengandung file yang valid.")
        
        await ui.update("📥 Mengunduh File...", details="Menyimpan file dari Telegram ke server sementara...")
        await Telegram.AIOGRAM_BOT.download(target_media, destination=file_path)
        
        if not os.path.exists(file_path):
            raise RuntimeError("Gagal mengunduh file dari Telegram.")
            
        file_size = os.path.getsize(file_path)
        from bot_helper.Others.Helper_Functions import get_human_size
        size_str = get_human_size(file_size)

        # ── STEP 2: Upload ke Provider Cloud ────────────────────────
        key_status = "(Akun Pribadi)" if user_keys.get(provider) else "(Anonim)"
        await ui.update(f"🚀 Mengunggah ke {provider.capitalize()}...", details=f"Mode: {key_status}\nMentransfer {size_str} ke server Cloud...")
        
        link = None
        if provider == "gofile":
            link = await upload_to_gofile(file_path, user_keys.get("gofile", ""))
        elif provider == "pixeldrain":
            link = await upload_to_pixeldrain(file_path, user_keys.get("pixeldrain", ""))
        elif provider == "buzzheavier":
            link = await upload_to_buzzheavier(file_path)
        elif provider == "vimeo":
            link = await upload_to_vimeo(file_path)
        elif provider == "terabox":
            link = await upload_to_terabox(file_path)
        elif provider == "rclone":
            link = await upload_via_rclone(file_path, user_id)
        else:
            raise RuntimeError("Provider Cloud tidak dikenal.")

        if not link:
            raise RuntimeError("Gagal mendapatkan link atau respons dari provider.")

        # ── STEP 3: Selesai & Kirim Hasil ───────────────────────────
        success_text = (
            f"✅ **Mirror / Upload Berhasil!**\n\n"
            f"📁 **File:** `{fname}`\n"
            f"💽 **Ukuran:** `{size_str}`\n"
            f"☁️ **Provider:** `{provider.capitalize()} {key_status}`\n\n"
            f"🔗 **Link / Status:**\n{link}"
        )
        
        btn = None
        if link.startswith("http"):
            btn = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=f"🌐 Buka Link", url=link, style="success")]])
            
        await Telegram.AIOGRAM_BOT.send_message(chat_id=message.chat.id, text=success_text, reply_markup=btn, reply_to_message_id=reply_msg.message_id)
        
        await ui.finish(f"✅ <b>Upload Selesai!</b>\nFile Anda telah diamankan di {provider.capitalize()}.")

    except Exception as e:
        LOGGER.error(f"Cloud Upload Error ({provider}): {e}", exc_info=True)
        await ui.finish(f"❌ <b>Upload Gagal!</b>\nError: {e}")
        
    finally:
        if os.path.exists(file_path):
            try: os.remove(file_path)
            except: pass


# ═══════════════════════════════════════════════════════════════════════
#  COMMAND HANDLERS
# ═══════════════════════════════════════════════════════════════════════

async def _handle_upload_command(message: Message, provider: str):
    user_id = message.from_user.id
    
    if not message.reply_to_message:
        return await message.reply(f"❌ **Cara Pakai:**\nBalas sebuah File/Video dengan perintah `/{provider}{CMD_SUFFIX}`")
        
    reply_msg = message.reply_to_message
    if not (reply_msg.video or reply_msg.document or reply_msg.audio):
        return await message.reply("❌ Pesan yang dibalas harus berupa file media (Video/Audio/Dokumen)!")

    # Cek Poin & Potong Saldo
    payment = await process_payment(user_id=user_id, command=provider)
    if not payment["success"]:
        return await message.reply(payment["message"])

    temp_msg = await message.reply(f"⏳ Menyiapkan tugas Cloud Upload...\n{payment['message']}")
    await asyncio.sleep(1.5)
    try: await temp_msg.delete()
    except: pass

    # Dapatkan nama file asli
    target_media = reply_msg.video or reply_msg.document or reply_msg.audio
    fname = getattr(target_media, "file_name", f"upload_{int(time.time())}.mp4")

    # Lempar ke Unified Engine
    await execute_unified_task(
        message, 
        f"MIRROR {provider.upper()}", 
        _core_cloud_upload_logic, 
        reply_msg, provider, fname
    )

@router.message(Command(f"gofile{CMD_SUFFIX}"))
async def cmd_gofile(message: Message): await _handle_upload_command(message, "gofile")

@router.message(Command(f"pixeldrain{CMD_SUFFIX}"))
async def cmd_pixeldrain(message: Message): await _handle_upload_command(message, "pixeldrain")

@router.message(Command(f"buzzheavier{CMD_SUFFIX}"))
async def cmd_buzzheavier(message: Message): await _handle_upload_command(message, "buzzheavier")

@router.message(Command(f"vimeo{CMD_SUFFIX}"))
async def cmd_vimeo(message: Message): await _handle_upload_command(message, "vimeo")

@router.message(Command(f"terabox{CMD_SUFFIX}"))
async def cmd_terabox(message: Message): await _handle_upload_command(message, "terabox")

@router.message(Command(f"rclone{CMD_SUFFIX}"))
async def cmd_rclone(message: Message): await _handle_upload_command(message, "rclone")
    
@router.message(Command(f"youtube{CMD_SUFFIX}"))
async def cmd_youtube_alias(message: Message):
    from bot.YTUpload import ytupload_handler
    class FakeCommand: args = ""
    await ytupload_handler(message, FakeCommand())
