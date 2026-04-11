"""
╔══════════════════════════════════════════════════════════════════════╗
║                    bot/YTUpload.py — v5.1                            ║
║        YouTube Upload — Terintegrasi dengan Unified_Engine           ║
╠══════════════════════════════════════════════════════════════════════╣
║  CHANGELOG v5.1:                                                     ║
║  [NEW] INTEGRASI SISTEM POIN! Memotong saldo sebelum upload jalan.   ║
║  [INTEGRATION] Migrasi total ke bot_helper.Process.Unified_Engine    ║
║  [CLEANUP] Menghapus sistem antrean manual (Task/Process_Status lama)║
║  [UX PREMIUM] Progress Bar tersentralisasi & real-time ETA.          ║
╚══════════════════════════════════════════════════════════════════════╝
"""

# ── Standard Library ──────────────────────────────────────────────────
import asyncio
import os
import time
from datetime import datetime

# ── Aiogram ───────────────────────────────────────────────────────────
from aiogram import Router, F
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
)
from aiogram.filters import Command, CommandObject
from aiogram.exceptions import TelegramBadRequest

# ── Internal ──────────────────────────────────────────────────────────
from bot_helper.Database.User_Data import get_data, ensure_user_data_structure
from bot_helper.Others.Helper_Functions import get_human_size
from bot_helper.Process.Unified_Engine import execute_unified_task
from bot_helper.Telegram.Telegram_Client import Telegram
from config.config import Config

# [NEW v5.1] Import Mesin Kasir Poin
from bot_helper.Process.point_manager import process_payment

# Memanggil fitur "Inline Waiter" jika dibutuhkan
from bot.shared import wait_for_message

# ── YouTube API ───────────────────────────────────────────────────────
try:
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    import googleapiclient.discovery
    from googleapiclient.http import MediaFileUpload
    YOUTUBE_ENABLED = True
except ImportError:
    YOUTUBE_ENABLED = False

LOGGER     = Config.LOGGER
CMD_SUFFIX = Config.CMD_SUFFIX
router     = Router()

# ── Konstanta ─────────────────────────────────────────────────────────
YT_SCOPES      = ["https://www.googleapis.com/auth/youtube.upload"]
YT_CHUNK_SIZE  = 5 * 1024 * 1024    # 5 MB per chunk (harus kelipatan 256KB)
YT_CATEGORY_ID = "20"               # Gaming
YT_TAGS        = ["StudioKhoirul", "Gaming", "Upload"]
TEMP_DIR       = "./temp/ytupload/"
TOKEN_FILE     = "./token.json"
SECRET_FILE    = "./client_secret.json"

os.makedirs(TEMP_DIR, exist_ok=True)

# State sementara per user untuk menyimpan pilihan sebelum konfirmasi
_yt_state: dict = {}

# ═══════════════════════════════════════════════════════════════════════
#  UI & CLEANUP HELPERS
# ═══════════════════════════════════════════════════════════════════════

async def _clean_msgs(*msgs):
    """Menghapus pesan untuk menjaga chat tetap rapi."""
    for m in msgs:
        if m:
            try: await m.delete()
            except Exception: pass

def _make_reply_kb(options: list, row_width: int = 2) -> ReplyKeyboardMarkup:
    """Membuat Reply Keyboard dengan mudah dan warna otomatis (Native Telegram)."""
    kb, row = [], []
    for opt in options:
        if "Batal" in opt or "❌" in opt: btn_style = "danger"
        elif "Ya" in opt or "✅" in opt: btn_style = "success"
        else: btn_style = "primary"
        row.append(KeyboardButton(text=opt, style=btn_style))
        if len(row) == row_width:
            kb.append(row); row = []
    if row: kb.append(row)
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True, one_time_keyboard=True)

async def _safe_edit(msg: Message, text: str, buttons=None) -> None:
    """Helper edit pesan yang tidak crash jika gagal."""
    try:
        if buttons: await msg.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
        else: await msg.edit_text(text)
    except TelegramBadRequest: pass
    except Exception: pass


# ═══════════════════════════════════════════════════════════════════════
#  OAUTH — HEADLESS VPS
# ═══════════════════════════════════════════════════════════════════════

def _get_youtube_client():
    if not YOUTUBE_ENABLED:
        raise RuntimeError("Library Google API tidak terinstall.")

    creds = None
    if os.path.exists(TOKEN_FILE):
        try: creds = Credentials.from_authorized_user_file(TOKEN_FILE, YT_SCOPES)
        except Exception as e: LOGGER.warning(f"⚠️  Gagal load token.json: {e}")

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            with open(TOKEN_FILE, "w") as f: f.write(creds.to_json())
            LOGGER.info("✅ YouTube token di-refresh")
        except Exception as e:
            raise RuntimeError(f"Token YouTube expired dan gagal di-refresh: {e}")

    if not creds or not creds.valid:
        raise RuntimeError("❌ Token YouTube tidak ditemukan atau tidak valid!")

    return googleapiclient.discovery.build("youtube", "v3", credentials=creds)


# ═══════════════════════════════════════════════════════════════════════
#  CORE UPLOAD LOGIC (UNIFIED ENGINE COMPATIBLE)
# ═══════════════════════════════════════════════════════════════════════

async def _core_ytupload_logic(message: Message, ui, reply_msg: Message, yt_title: str, yt_desc: str, yt_privacy: str, fname: str) -> None:
    """Fungsi inti Upload YouTube yang telah terintegrasi dengan ProgressUI"""
    final_path = os.path.join(TEMP_DIR, f"yt_{message.message_id}_{int(time.time())}.mp4")

    try:
        # ── STEP 1: Download dari Telegram ──────────────────────────
        target_media = reply_msg.video or reply_msg.document
        total_size = target_media.file_size
        
        await ui.update("📥 Mengunduh Video...", details="Menyimpan file dari Telegram...")
        
        last_dl_edit = 0.0
        async def _dl_progress(current: int, total: int):
            nonlocal last_dl_edit
            now = time.time()
            if now - last_dl_edit >= 2.0:
                asyncio.create_task(ui.update(
                    status="📥 Mengunduh Video...",
                    current=current,
                    total=total,
                    details=f"File: {fname}"
                ))
                last_dl_edit = now

        # Hybrid Download (Pyrogram prioritas, Aiogram fallback)
        pyro_client = Telegram.PYROGRAM_CLIENT
        downloaded = False
        
        if pyro_client:
            try:
                pyro_msg = await pyro_client.get_messages(reply_msg.chat.id, reply_msg.message_id)
                dl_file = await pyro_client.download_media(message=pyro_msg, file_name=final_path, progress=_dl_progress)
                if dl_file and os.path.exists(dl_file): downloaded = True
            except Exception as e:
                LOGGER.error(f"Pyrogram DL error: {e}")
                
        if not downloaded:
            await Telegram.AIOGRAM_BOT.download(target_media, destination=final_path)
            if os.path.exists(final_path): downloaded = True

        if not downloaded or not os.path.exists(final_path):
            raise RuntimeError("Download dari Telegram gagal.")

        file_size = os.path.getsize(final_path)

        # ── STEP 2: Upload ke YouTube ───────────────────────────────
        youtube = _get_youtube_client()
        media = MediaFileUpload(final_path, chunksize=YT_CHUNK_SIZE, resumable=True)

        request = youtube.videos().insert(
            part="snippet,status",
            body={
                "snippet": {
                    "categoryId": YT_CATEGORY_ID,
                    "description": yt_desc,
                    "title": yt_title,
                    "tags": YT_TAGS,
                },
                "status": {"privacyStatus": yt_privacy},
            },
            media_body=media,
        )

        await ui.update("🌐 Menginisiasi API YouTube...", details="Mengamankan koneksi ke Google Server...")

        response = None
        last_up_edit = 0.0

        while response is None:
            chunk_status, response = await asyncio.to_thread(request.next_chunk)
            
            if chunk_status:
                current = chunk_status.resumable_progress
                now = time.time()
                if now - last_up_edit >= 2.0:
                    await ui.update(
                        status="🚀 Mengunggah ke YouTube...",
                        current=current,
                        total=file_size,
                        details=f"Judul: {yt_title[:30]}\nPrivasi: {yt_privacy.capitalize()}"
                    )
                    last_up_edit = now

        video_id = response.get("id", "")
        if not video_id:
            raise RuntimeError("YouTube tidak mengembalikan ID Video.")

        yt_link = f"https://youtu.be/{video_id}"

        # ── STEP 3: Selesai ─────────────────────────────────────────
        success_text = (
            f"✅ **Upload YouTube Berhasil!**\n\n"
            f"📺 **Judul:** `{yt_title}`\n"
            f"🔒 **Privasi:** `{yt_privacy.capitalize()}`\n"
            f"💽 **Ukuran:** `{get_human_size(file_size)}`\n"
            f"🔗 **Link:** {yt_link}"
        )
        
        # Kirim pesan khusus dengan tombol URL
        await Telegram.AIOGRAM_BOT.send_message(
            chat_id=message.chat.id,
            text=success_text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📺 Buka di YouTube", url=yt_link, style="success")]]),
            reply_to_message_id=reply_msg.message_id
        )
        
        await ui.finish(f"✅ <b>Upload Selesai!</b>\nVideo Anda sudah ter-publish.")

    finally:
        if os.path.exists(final_path):
            try: os.remove(final_path); LOGGER.info(f"✅ Temp file dihapus: {final_path}")
            except OSError as e: LOGGER.warning(f"⚠️  Gagal hapus temp file: {e}")


# ═══════════════════════════════════════════════════════════════════════
#  TOMBOL DASHBOARD
# ═══════════════════════════════════════════════════════════════════════

def _build_dashboard(user_id: int, yt_title: str, privacy: str) -> tuple[str, list]:
    from bot_helper.Database.User_Data import get_user_balance
    balance = get_user_balance(user_id)
    if user_id in Config.SUDO_USERS:
        vip_text = "♾️ Unlimited (Owner/Sudo)"
    else:
        vip_text = f"💎 Saldo: {balance:,} Poin"
        
    priv_icons = {"private": "🔒", "unlisted": "🔗", "public": "🌍"}
    priv_icon  = priv_icons.get(privacy, "🔒")
    
    clean_title = yt_title.replace("`", "").replace("*", "")

    dash_text = (
        f"**📺 KONFIRMASI UPLOAD YOUTUBE**\n\n"
        f"📝 **Judul:** `{clean_title[:40]}{'...' if len(clean_title) > 40 else ''}`\n"
        f"{priv_icon} **Privasi Target:** `{privacy.capitalize()}`\n"
        f"💳 **Dompet:** {vip_text}\n\n"
        f"Lanjutkan?"
    )

    def _prv_btn(label: str, val: str):
        icon  = "✅ " if val == privacy else ""
        return InlineKeyboardButton(text=f"{icon}{label}", callback_data=f"yt_prv_{user_id}_{val}", style="success" if val == privacy else "primary")

    buttons = [
        [_prv_btn("🔒 Private", "private"), _prv_btn("🔗 Unlisted", "unlisted"), _prv_btn("🌍 Public", "public")],
        [InlineKeyboardButton(text="✅ Upload", callback_data=f"yt_go_{user_id}", style="success"),
         InlineKeyboardButton(text="❌ Batal", callback_data=f"yt_cancel_{user_id}", style="danger")],
    ]

    return dash_text, buttons


# ═══════════════════════════════════════════════════════════════════════
#  HANDLER: /ytupload
# ═══════════════════════════════════════════════════════════════════════

@router.message(Command(f"ytupload{CMD_SUFFIX}"))
async def ytupload_handler(message: Message, command: CommandObject) -> None:
    user_id = message.from_user.id

    if not YOUTUBE_ENABLED:
        return await message.reply("❌ **Library Google API belum terinstall!**")

    if not os.path.exists(TOKEN_FILE):
        return await message.reply("❌ **Token YouTube Tidak Ditemukan!**\nAdmin harus mensetup `token.json` terlebih dahulu.")

    if not message.reply_to_message:
        return await message.reply("❌ **Cara Pakai:**\nBalas sebuah video dengan perintah `/ytupload Judul Video`")

    reply_msg = message.reply_to_message
    if not (reply_msg.video or reply_msg.document):
        return await message.reply("❌ Pesan yang dibalas bukan video yang valid!")

    await ensure_user_data_structure(user_id)

    cmd_parts = (message.text or "").strip().split(None, 1)
    if len(cmd_parts) > 1:
        yt_title = cmd_parts[1].strip()
    else:
        try:
            target_media = reply_msg.video or reply_msg.document
            yt_title = target_media.file_name or "Video Upload"
            if "." in yt_title: yt_title = yt_title.rsplit(".", 1)[0]
        except Exception:
            yt_title = "Video Upload"

    _yt_state[user_id] = {
        "reply_msg": reply_msg,
        "title":     yt_title,
        "desc":      "",
        "privacy":   "private", 
    }

    dash_text, buttons = _build_dashboard(user_id, yt_title, "private")
    await message.reply(dash_text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))


# ═══════════════════════════════════════════════════════════════════════
#  CALLBACKS TOMBOL INLINE
# ═══════════════════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("yt_prv_"))
async def yt_privacy_cb(call: CallbackQuery) -> None:
    try: await call.answer()
    except: pass
    
    data = call.data.split("_")
    if len(data) < 4: return
    user_id, privacy = int(data[2]), data[3]

    if call.from_user.id != user_id:
        return await call.answer("❌ Menu ini bukan milik Anda!", show_alert=True)
    if user_id not in _yt_state:
        return await call.answer("❌ Sesi berakhir. Silakan ulangi.", show_alert=True)

    _yt_state[user_id]["privacy"] = privacy
    yt_title = _yt_state[user_id]["title"]
    dash_text, buttons = _build_dashboard(user_id, yt_title, privacy)
    await _safe_edit(call.message, dash_text, buttons=buttons)


@router.callback_query(F.data.startswith("yt_go_"))
async def yt_go_cb(call: CallbackQuery) -> None:
    try: await call.answer("✅ Mengantrekan...", show_alert=False)
    except: pass
    
    user_id = int(call.data.split("_")[2])

    if call.from_user.id != user_id:
        return await call.answer("❌ Menu ini bukan milik Anda!", show_alert=True)
    if user_id not in _yt_state:
        return await call.message.edit_text("❌ Sesi berakhir.\nSilakan ulangi perintah `/ytupload`")

    state      = _yt_state[user_id]
    reply_msg  = state["reply_msg"]
    yt_title   = state["title"]
    yt_desc    = state["desc"]
    yt_privacy = state["privacy"]

    try:
        target_media = reply_msg.video or reply_msg.document
        fname = target_media.file_name or "video.mp4"
    except Exception:
        fname = "video.mp4"

    # [NEW v5.1] MESIN KASIR: POTONG SALDO POIN
    payment = await process_payment(user_id=user_id, command="ytupload")
    if not payment["success"]:
        _yt_state.pop(user_id, None)
        return await call.message.edit_text(payment["message"])

    # Hapus pesan konfirmasi inline (digantikan oleh Unified_Engine nantinya)
    await _clean_msgs(call.message)
    _yt_state.pop(user_id, None)
    
    # Beri tahu user bahwa poin terpotong (sementara sebelum Unified UI muncul)
    temp_msg = await reply_msg.reply(payment["message"])

    # 🚀 JALANKAN VIA UNIFIED ENGINE (Ini menyelesaikan segalanya!)
    # Membuat fake_msg agar notifikasi progress mereply ke pesan video aslinya
    fake_msg = call.message.model_copy(update={
        "from_user": call.from_user,
        "chat": call.message.chat,
        "reply_to_message": reply_msg
    })
    
    await execute_unified_task(fake_msg, "YOUTUBE UPLOAD", _core_ytupload_logic, reply_msg, yt_title, yt_desc, yt_privacy, fname)
    
    # Hapus pesan poin setelah task masuk antrean
    await asyncio.sleep(2)
    await _clean_msgs(temp_msg)


@router.callback_query(F.data.startswith("yt_cancel_"))
async def yt_cancel_cb(call: CallbackQuery) -> None:
    try: await call.answer("⏳ ❌ Membatalkan...", show_alert=False)
    except: pass
    
    parts   = call.data.split("_")
    user_id = int(parts[2])

    if call.from_user.id != user_id:
        return await call.answer("❌ Menu ini bukan milik Anda!", show_alert=True)

    _yt_state.pop(user_id, None)
    try: await call.message.edit_text("❌ **Sesi Upload YouTube dibatalkan.**")
    except Exception: pass


# ═══════════════════════════════════════════════════════════════════════
#  HANDLER: /yttoken — Setup token YouTube
# ═══════════════════════════════════════════════════════════════════════

@router.message(Command(f"yttoken{CMD_SUFFIX}"))
async def yttoken_handler(message: Message) -> None:
    user_id = message.from_user.id
    if user_id != Config.OWNER_ID and user_id not in Config.SUDO_USERS:
        return await message.reply("❌ Perintah ini hanya bisa digunakan oleh Admin Bot.")

    if not message.reply_to_message:
        token_status = "✅ Tersedia" if os.path.exists(TOKEN_FILE) else "❌ Tidak Ditemukan"
        secret_status = "✅ Tersedia" if os.path.exists(SECRET_FILE) else "❌ Tidak Ditemukan"

        kb = _make_reply_kb(["❌ Batal"], 1)
        ask_msg = await message.reply(
            f"🔑 **Status Kredensial YouTube**\n\n"
            f"  `token.json`: {token_status}\n"
            f"  `client_secret.json`: {secret_status}\n\n"
            f"📋 **Untuk Memperbarui Token:**\n"
            f"Kirimkan file `token.json` baru Anda di sini.",
            reply_markup=kb
        )
        
        resp = await wait_for_message(message.chat.id, user_id, 120)
        await _clean_msgs(ask_msg, resp)
        
        if not resp or "batal" in (resp.text or "").lower():
            return await message.answer("❌ Dibatalkan.", reply_markup=ReplyKeyboardRemove())
            
        if not resp.document:
            return await message.answer("❌ Silakan kirimkan file `token.json` yang sah.", reply_markup=ReplyKeyboardRemove())
            
        try:
            await Telegram.AIOGRAM_BOT.download(resp.document, destination=TOKEN_FILE)
            LOGGER.info(f"✅ token.json berhasil diperbarui oleh admin {user_id}")
            await message.answer("✅ **`token.json` berhasil diperbarui!**\n\nFitur Upload YouTube sekarang aktif dan siap digunakan.", reply_markup=ReplyKeyboardRemove())
        except Exception as e:
            LOGGER.error(f"❌ Gagal memperbarui token.json: {e}", exc_info=True)
            await message.answer(f"❌ Gagal menyimpan file token:\n`{e}`", reply_markup=ReplyKeyboardRemove())
        return

    reply_msg = message.reply_to_message
    if not reply_msg.document:
        return await message.reply("❌ Silakan balas (reply) file `token.json` yang sah.")

    try:
        await Telegram.AIOGRAM_BOT.download(reply_msg.document, destination=TOKEN_FILE)
        LOGGER.info(f"✅ token.json berhasil diperbarui oleh admin {user_id}")
        await message.reply("✅ **`token.json` berhasil diperbarui!**\n\nFitur Upload YouTube sekarang aktif dan siap digunakan.")
    except Exception as e:
        LOGGER.error(f"❌ Gagal memperbarui token.json: {e}", exc_info=True)
        await message.reply(f"❌ Gagal menyimpan file token:\n`{e}`")
