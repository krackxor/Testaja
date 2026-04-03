"""
╔══════════════════════════════════════════════════════════════════════╗
║                    bot/YTUpload.py — v3.1                            ║
║       YouTube Upload — Terintegrasi Penuh dengan Bot System          ║
╠══════════════════════════════════════════════════════════════════════╣
║  CHANGELOG dari versi lama:                                          ║
║  [NEW] Migrasi total ke Aiogram Router & CallbackQuery               ║
║  [NEW] Hybrid Downloader (Pyrogram dengan Progress Bar -> Aiogram)   ║
║  [FIX] TelegramBadRequest untuk edit_text handling                   ║
║  [FIX] InlineKeyboardButton & InlineKeyboardMarkup Aiogram syntax    ║
╚══════════════════════════════════════════════════════════════════════╝
"""

# ── Standard Library ──────────────────────────────────────────────────
import asyncio
import os
import time
from datetime import datetime

# ── Aiogram ───────────────────────────────────────────────────────────
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command, CommandObject
from aiogram.exceptions import TelegramBadRequest

# ── Internal ──────────────────────────────────────────────────────────
from bot_helper.Database.User_Data import get_data, ensure_user_data_structure, get_task_limit
from bot_helper.Others.Helper_Functions import get_human_size, get_readable_time
from bot_helper.Others.Names import Names
from bot_helper.Process.Process_Status import ProcessStatus
from bot_helper.Process.Running_Process import (
    append_running_process, check_running_process, remove_running_process,
)
from bot_helper.Process.Running_Tasks import (
    add_task, working_task, working_task_lock, queued_task, queued_task_lock,
)
from bot_helper.Telegram.Telegram_Client import Telegram
from config.config import Config

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
YT_QUEUE_TIMEOUT = 3600  # Max 1 jam tunggu antrian

os.makedirs(TEMP_DIR, exist_ok=True)

# State sementara per user untuk menyimpan pilihan sebelum konfirmasi
_yt_state: dict = {}


async def _safe_edit(msg: Message, text: str, buttons=None) -> None:
    """Helper edit pesan yang tidak crash jika gagal."""
    try:
        if buttons:
            await msg.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
        else:
            await msg.edit_text(text)
    except TelegramBadRequest:
        pass
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════════
#  VIP CHECK
# ═══════════════════════════════════════════════════════════════════════

def _is_vip(user_id: int) -> bool:
    if user_id == Config.OWNER_ID or user_id in Config.SUDO_USERS:
        return True
    user_data   = get_data().get(user_id, {})
    expiry_str  = user_data.get("premium_expiry_date")
    if not expiry_str:
        return False
    try:
        expiry = datetime.fromisoformat(str(expiry_str))
        return datetime.now(expiry.tzinfo) < expiry
    except (ValueError, TypeError):
        return False


def _vip_expiry_text(user_id: int) -> str:
    if user_id == Config.OWNER_ID or user_id in Config.SUDO_USERS:
        return "♾️ Unlimited (Owner/Sudo)"
    user_data  = get_data().get(user_id, {})
    expiry_str = user_data.get("premium_expiry_date")
    if not expiry_str:
        return "❌ Tidak aktif"
    try:
        expiry = datetime.fromisoformat(str(expiry_str))
        now    = datetime.now(expiry.tzinfo)
        if now >= expiry:
            return "❌ Sudah kadaluarsa"
        sisa = expiry - now
        days = sisa.days
        return f"✅ Aktif — sisa {days} hari"
    except Exception:
        return "❓ Tidak diketahui"


# ═══════════════════════════════════════════════════════════════════════
#  OAUTH — HEADLESS VPS
# ═══════════════════════════════════════════════════════════════════════

def _get_youtube_client():
    if not YOUTUBE_ENABLED:
        raise RuntimeError("Library Google API tidak terinstall. Jalankan: pip install google-api-python-client google-auth-oauthlib google-auth-httplib2")

    creds = None
    if os.path.exists(TOKEN_FILE):
        try:
            creds = Credentials.from_authorized_user_file(TOKEN_FILE, YT_SCOPES)
        except Exception as e:
            LOGGER.warning(f"⚠️  Gagal load token.json: {e}")

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            with open(TOKEN_FILE, "w") as f:
                f.write(creds.to_json())
            LOGGER.info("✅ YouTube token di-refresh")
        except Exception as e:
            raise RuntimeError(
                f"Token YouTube expired dan gagal di-refresh: {e}\n"
                "Jalankan 'python3 get_token.py' di lokal untuk generate token baru."
            )

    if not creds or not creds.valid:
        raise RuntimeError(
            "❌ Token YouTube tidak ditemukan atau tidak valid!\n\n"
            "📋 Langkah untuk generate token.json:\n"
            "1. Download client_secret.json dari Google Cloud Console\n"
            "2. Jalankan di komputer lokal: `python3 get_token.py`\n"
            "3. Login di browser yang muncul\n"
            "4. Copy token.json yang dihasilkan ke folder bot di VPS\n\n"
            "Token hanya perlu di-generate sekali. Setelah itu refresh otomatis."
        )

    return googleapiclient.discovery.build("youtube", "v3", credentials=creds)


# ═══════════════════════════════════════════════════════════════════════
#  CORE UPLOAD FUNCTION
# ═══════════════════════════════════════════════════════════════════════

async def upload_to_youtube(
    video_path: str,
    title: str,
    description: str,
    privacy: str,
    process_status: ProcessStatus,
    status_msg: Message,
) -> str:
    youtube    = _get_youtube_client()
    total_size = os.path.getsize(video_path)

    media = MediaFileUpload(
        video_path,
        chunksize=YT_CHUNK_SIZE,
        resumable=True,
    )

    request = youtube.videos().insert(
        part="snippet,status",
        body={
            "snippet": {
                "categoryId": YT_CATEGORY_ID,
                "description": description,
                "title": title,
                "tags": YT_TAGS,
            },
            "status": {"privacyStatus": privacy},
        },
        media_body=media,
    )

    response       = None
    start_time     = time.time()
    last_edit_time = 0.0

    _update_yt_status(
        process_status, "⬆️ Menghubungkan ke YouTube API...",
        0, total_size, start_time,
    )
    try:
        await status_msg.edit_text(process_status.status_message)
    except Exception:
        pass

    while response is None:
        if not check_running_process(process_status.process_id):
            raise asyncio.CancelledError("Dibatalkan oleh pengguna")

        process_status.ping = time.time()

        chunk_status, response = await asyncio.to_thread(request.next_chunk)

        if chunk_status:
            current = chunk_status.resumable_progress
            _update_yt_status(
                process_status, "⬆️ Mengunggah ke YouTube",
                current, total_size, start_time,
            )
            now = time.time()
            if now - last_edit_time >= 2.0:
                try:
                    await status_msg.edit_text(process_status.status_message)
                    last_edit_time = now
                except Exception:
                    pass

    video_id = response.get("id", "")
    if not video_id:
        raise RuntimeError("YouTube tidak mengembalikan video ID")

    return f"https://youtu.be/{video_id}"


def _update_yt_status(
    ps: ProcessStatus,
    header: str,
    current: int,
    total: int,
    start_time: float,
) -> None:
    from bot_helper.Process.Process_Status import get_progress_bar_string

    elapsed = max(1, time.time() - start_time)
    speed   = current / elapsed
    pct     = f"{current * 100 / max(total, 1):.1f}%"
    eta     = get_readable_time((total - current) / speed) if speed > 0 else "N/A"
    bar     = get_progress_bar_string(current, total)

    ps.status_message = (
        f"{header}\n\n"
        f"`{ps.file_name or 'video'}`\n"
        f"{bar} {pct}\n"
        f"**Ditambahkan Oleh**: {ps.added_by} | **ID**: `{ps.user_id}`\n"
        f"**Mesin**: YouTube API\n"
        f"**Diunggah**: {get_human_size(current)} dari {get_human_size(total)}\n"
        f"**Kecepatan**: {get_human_size(int(speed))}ps | **ETA**: {eta}\n"
        f"`/cancel{CMD_SUFFIX} process {ps.process_id}`"
    )


# ═══════════════════════════════════════════════════════════════════════
#  TASK WORKER — TERINTEGRASI DENGAN START_TASK
# ═══════════════════════════════════════════════════════════════════════

async def _ytupload_worker(
    process_status: ProcessStatus,
    original_message: Message,
    reply_msg: Message,
    yt_title: str,
    yt_desc: str,
    yt_privacy: str,
    status_msg: Message,
) -> None:
    final_path = os.path.join(TEMP_DIR, f"yt_{process_status.process_id}.mp4")

    try:
        # ── STEP 1: Download ──────────────────────────────────────────
        process_status.update_process_message(
            f"🔽 **Mengunduh Video...**\n\n"
            f"`{process_status.file_name or 'video'}`\n"
            f"**Ditambahkan Oleh**: {process_status.added_by} | **ID**: `{process_status.user_id}`\n"
            f"`/cancel{CMD_SUFFIX} process {process_status.process_id}`"
        )
        try: await status_msg.edit_text(process_status.status_message)
        except Exception: pass

        download_start = time.time()
        last_dl_edit   = 0.0

        async def _dl_progress(current: int, total: int):
            nonlocal last_dl_edit
            if not check_running_process(process_status.process_id):
                raise asyncio.CancelledError("Dibatalkan")
            process_status.ping = time.time()
            process_status.telegram_update_status(
                current, total, "Diunduh", process_status.file_name or "video",
                download_start, "Mengunduh untuk YouTube", "Pyrogram",
            )
            now = time.time()
            if now - last_dl_edit >= 2.0:
                last_dl_edit = now
                asyncio.create_task(_safe_edit(status_msg, process_status.status_message))

        # Menggunakan Hybrid Download (Pyrogram prioritas, lalu Aiogram)
        pyro_client = Telegram.PYROGRAM_CLIENT
        downloaded = False
        
        if pyro_client:
            try:
                pyro_msg = await pyro_client.get_messages(reply_msg.chat.id, reply_msg.message_id)
                dl_file = await pyro_client.download_media(message=pyro_msg, file_name=final_path, progress=_dl_progress)
                if dl_file and os.path.exists(dl_file): downloaded = True
            except Exception as e:
                LOGGER.error(f"Pyrogram DL error: {e}")
                
        # Aiogram Fallback
        if not downloaded:
            target_media = reply_msg.video or reply_msg.document
            await Telegram.AIOGRAM_BOT.download(target_media, destination=final_path)
            if os.path.exists(final_path): downloaded = True

        if not downloaded or not os.path.exists(final_path):
            raise RuntimeError("Download gagal — file tidak ditemukan setelah download")

        if not check_running_process(process_status.process_id):
            raise asyncio.CancelledError("Dibatalkan setelah download")

        # ── STEP 2: Upload ke YouTube ─────────────────────────────────
        yt_link = await upload_to_youtube(
            final_path, yt_title, yt_desc, yt_privacy,
            process_status, status_msg,
        )

        # ── STEP 3: Sukses ────────────────────────────────────────────
        file_size = os.path.getsize(final_path)
        elapsed   = get_readable_time(time.time() - download_start)

        success_text = (
            f"✅ **Upload YouTube Berhasil!**\n\n"
            f"📺 **Judul:** `{yt_title}`\n"
            f"🔒 **Privasi:** `{yt_privacy.capitalize()}`\n"
            f"💽 **Ukuran:** `{get_human_size(file_size)}`\n"
            f"⏱️ **Waktu:** `{elapsed}`\n"
            f"🔗 **Link:** {yt_link}"
        )
        buttons = [[InlineKeyboardButton(text="📺 Buka di YouTube", url=yt_link)]]

        try:
            await status_msg.edit_text(success_text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
        except Exception:
            await original_message.answer(success_text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

    except asyncio.CancelledError:
        try: await status_msg.edit_text("🚫 **Upload YouTube Dibatalkan.**")
        except Exception: pass

    except Exception as e:
        LOGGER.error(f"❌ YTUpload worker error: {e}", exc_info=True)
        err_text = f"❌ **Upload YouTube Gagal!**\n\n`{str(e)[:300]}`"
        try: await status_msg.edit_text(err_text)
        except Exception:
            try: await original_message.answer(err_text)
            except Exception: pass

    finally:
        if os.path.exists(final_path):
            try: os.remove(final_path); LOGGER.info(f"✅ Temp file dihapus: {final_path}")
            except OSError as e: LOGGER.warning(f"⚠️  Gagal hapus temp file: {e}")

        await remove_running_process(process_status.process_id)
        async with working_task_lock:
            for task in list(working_task):
                if task.get("process_status") and task["process_status"].process_id == process_status.process_id:
                    working_task.remove(task)
                    break

        _yt_state.pop(process_status.user_id, None)


async def _start_ytupload_task(
    process_status: ProcessStatus,
    original_message: Message,
    reply_msg: Message,
    yt_title: str,
    yt_desc: str,
    yt_privacy: str,
    status_msg: Message,
) -> None:
    task_wrapper = {"process_status": process_status, "functions": [], "_yt_task": True}
    queued = False

    async with working_task_lock:
        if len(working_task) < get_task_limit():
            working_task.append(task_wrapper)
            await append_running_process(process_status.process_id)
        else:
            queued = True

    if queued:
        async with queued_task_lock:
            pos = len(queued_task) + 1
            queued_task.append(task_wrapper)

        queue_text = (
            f"⏳ **Masuk Antrian YouTube Upload**\n\n"
            f"📋 **Posisi:** `{pos}`\n"
            f"📺 **Judul:** `{yt_title}`\n"
            f"🔒 **Privasi:** `{yt_privacy.capitalize()}`\n"
            f"**ID Proses:** `{process_status.process_id}`\n\n"
            f"`/cancel{CMD_SUFFIX} process {process_status.process_id}`"
        )
        await _safe_edit(status_msg, queue_text)

        waited = 0
        while waited < YT_QUEUE_TIMEOUT:
            await asyncio.sleep(5)
            waited += 5
            async with queued_task_lock:
                if task_wrapper not in queued_task:
                    break 
        else:
            async with queued_task_lock:
                if task_wrapper in queued_task:
                    queued_task.remove(task_wrapper)
            await _safe_edit(status_msg, "❌ **Timeout antrian (1 jam).** Coba lagi.")
            _yt_state.pop(process_status.user_id, None)
            return

        if not check_running_process(process_status.process_id):
            _yt_state.pop(process_status.user_id, None)
            return

    await _ytupload_worker(
        process_status, original_message, reply_msg,
        yt_title, yt_desc, yt_privacy, status_msg,
    )


# ═══════════════════════════════════════════════════════════════════════
#  TOMBOL DASHBOARD
# ═══════════════════════════════════════════════════════════════════════

def _build_dashboard(user_id: int, yt_title: str, privacy: str) -> tuple[str, list]:
    vip_text = _vip_expiry_text(user_id)
    priv_icons = {"private": "🔒", "unlisted": "🔗", "public": "🌍"}
    priv_icon  = priv_icons.get(privacy, "🔒")

    dash_text = (
        f"📺 **YouTube Upload — Konfirmasi**\n"
        f"{'─' * 32}\n"
        f"  📝 Judul      `{yt_title[:40]}{'...' if len(yt_title) > 40 else ''}`\n"
        f"  {priv_icon} Privasi    `{privacy.capitalize()}`\n"
        f"  👑 VIP        {vip_text}\n"
        f"{'─' * 32}\n"
        f"_Pilih privasi lalu tekan ▶️ Mulai Upload_"
    )

    def _prv_btn(label: str, val: str):
        icon  = "✅ " if val == privacy else ""
        return InlineKeyboardButton(text=f"{icon}{label}", callback_data=f"yt_prv_{user_id}_{val}")

    buttons = [
        [_prv_btn("🔒 Private", "private"), _prv_btn("🔗 Unlisted", "unlisted"), _prv_btn("🌍 Public", "public")],
        [InlineKeyboardButton(text="▶️ Mulai Upload", callback_data=f"yt_go_{user_id}"),
         InlineKeyboardButton(text="❌ Batal", callback_data=f"yt_cancel_{user_id}")],
    ]

    return dash_text, buttons


# ═══════════════════════════════════════════════════════════════════════
#  HANDLER: /ytupload
# ═══════════════════════════════════════════════════════════════════════

@router.message(Command("ytupload"))
async def ytupload_handler(message: Message, command: CommandObject) -> None:
    user_id = message.from_user.id

    if not YOUTUBE_ENABLED:
        return await message.reply(
            "❌ **Library Google API belum terinstall!**\n\n"
            "Jalankan: `pip install google-api-python-client google-auth-oauthlib google-auth-httplib2`"
        )

    if not _is_vip(user_id):
        return await message.reply(
            "👑 **Fitur Eksklusif VIP**\n\n"
            "Upload langsung ke YouTube hanya tersedia untuk member **VIP/Premium**.\n\n"
            "Hubungi admin untuk informasi berlangganan VIP.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="💬 Hubungi Admin", url=f"https://t.me/{Config.BOT_USERNAME}")]])
        )

    if not os.path.exists(TOKEN_FILE):
        return await message.reply(
            "❌ **Token YouTube Tidak Ditemukan!**\n\n"
            "Token YouTube belum di-setup di server bot.\n\n"
            "📋 **Langkah Setup:**\n"
            "1. Download `client_secret.json` dari Google Cloud Console\n"
            "2. Jalankan `python3 get_token.py` di komputer lokal\n"
            "3. Login di browser yang muncul\n"
            "4. Upload `token.json` yang dihasilkan ke folder bot di VPS\n\n"
            "_Token hanya perlu di-setup sekali._"
        )

    if not message.reply_to_message:
        return await message.reply(
            "❌ **Cara Pakai:**\n"
            f"Balas sebuah video dengan perintah `/ytupload{CMD_SUFFIX}`\n\n"
            "Contoh:\n"
            "1. Kirim/forward video ke chat ini\n"
            f"2. Reply video tersebut dengan `/ytupload{CMD_SUFFIX}`"
        )

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
            if "." in yt_title:
                yt_title = yt_title.rsplit(".", 1)[0]
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
    await call.answer()
    data = call.data.split("_")
    if len(data) < 4: return
    user_id, privacy = int(data[2]), data[3]

    if call.from_user.id != user_id:
        return await call.answer("❌ Bukan milikmu!", show_alert=True)
    if user_id not in _yt_state:
        return await call.answer("⚠️ Session expired. Ulangi /ytupload", show_alert=True)

    _yt_state[user_id]["privacy"] = privacy
    yt_title = _yt_state[user_id]["title"]
    dash_text, buttons = _build_dashboard(user_id, yt_title, privacy)
    await _safe_edit(call.message, dash_text, buttons=buttons)


@router.callback_query(F.data.startswith("yt_go_"))
async def yt_go_cb(call: CallbackQuery) -> None:
    await call.answer("⏳ Memproses...")
    user_id = int(call.data.split("_")[2])

    if call.from_user.id != user_id:
        return await call.answer("❌ Bukan milikmu!", show_alert=True)
    if not _is_vip(user_id):
        return await call.message.edit_text("❌ Akses VIP kamu sudah habis. Hubungi admin untuk perpanjang.")
    if user_id not in _yt_state:
        return await call.message.edit_text("⚠️ Session expired.\n" + f"Ulangi perintah `/ytupload{CMD_SUFFIX}`")

    state      = _yt_state[user_id]
    reply_msg  = state["reply_msg"]
    yt_title   = state["title"]
    yt_desc    = state["desc"]
    yt_privacy = state["privacy"]

    user_name       = call.from_user.username or ""
    user_first_name = call.from_user.first_name or str(user_id)

    process_status = ProcessStatus(
        user_id         = user_id,
        chat_id         = call.message.chat.id,
        user_name       = user_name,
        user_first_name = user_first_name,
        event           = call.message,
        process_type    = getattr(Names, "ytupload", "YouTubeUpload"),
        input_mode      = "Telegram",
    )

    try:
        target_media = reply_msg.video or reply_msg.document
        fname = target_media.file_name or "video.mp4"
    except Exception:
        fname = "video.mp4"
    process_status.file_name = fname

    priv_icons = {"private": "🔒", "unlisted": "🔗", "public": "🌍"}
    priv_icon  = priv_icons.get(yt_privacy, "🔒")

    init_text = (
        f"📺 **YouTube Upload Dimulai**\n"
        f"{'─' * 32}\n"
        f"  📝 Judul    `{yt_title[:40]}`\n"
        f"  {priv_icon} Privasi  `{yt_privacy.capitalize()}`\n"
        f"  💽 File     `{fname}`\n"
        f"{'─' * 32}\n"
        f"**ID Proses:** `{process_status.process_id}`\n"
        f"`/cancel{CMD_SUFFIX} process {process_status.process_id}`"
    )

    action_buttons = [
        [InlineKeyboardButton(text="❌ Batalkan", callback_data=f"yt_cancel_{user_id}_{process_status.process_id}"),
         InlineKeyboardButton(text="📋 Lihat Status", callback_data=f"yt_status_{process_status.process_id}")],
    ]

    try:
        status_msg = await call.message.edit_text(init_text, reply_markup=InlineKeyboardMarkup(inline_keyboard=action_buttons))
    except Exception:
        status_msg = await call.message.answer(init_text, reply_markup=InlineKeyboardMarkup(inline_keyboard=action_buttons))

    asyncio.create_task(
        _start_ytupload_task(
            process_status,
            call.message,
            reply_msg,
            yt_title,
            yt_desc,
            yt_privacy,
            status_msg,
        )
    )


@router.callback_query(F.data.startswith("yt_cancel_"))
async def yt_cancel_cb(call: CallbackQuery) -> None:
    await call.answer("🚫 Membatalkan...")
    parts   = call.data.split("_")
    user_id = int(parts[2])

    if call.from_user.id != user_id:
        return await call.answer("❌ Bukan milikmu!", show_alert=True)

    if len(parts) >= 4:
        process_id = parts[3]
        from bot_helper.Process.Running_Process import remove_running_process
        await remove_running_process(process_id)
        try: await call.message.edit_text("🚫 **Proses dibatalkan.**")
        except Exception: pass
    else:
        _yt_state.pop(user_id, None)
        try: await call.message.edit_text("❌ **Upload YouTube dibatalkan.**")
        except Exception: pass


@router.callback_query(F.data.startswith("yt_status_"))
async def yt_status_cb(call: CallbackQuery) -> None:
    await call.answer()
    process_id = call.data.split("_")[2]

    async with working_task_lock:
        for task in list(working_task):
            ps = task.get("process_status")
            if ps and ps.process_id == process_id:
                if call.from_user.id != ps.user_id:
                    return await call.answer("❌ Bukan milikmu!", show_alert=True)
                try:
                    await call.answer(
                        ps.status_message[:200] if ps.status_message else "Tidak ada info status",
                        show_alert=True,
                    )
                except Exception:
                    pass
                return

    await call.answer("⚠️ Proses tidak ditemukan (mungkin sudah selesai)", show_alert=True)


# ═══════════════════════════════════════════════════════════════════════
#  HANDLER: /yttoken — Setup token YouTube
# ═══════════════════════════════════════════════════════════════════════

@router.message(Command("yttoken"))
async def yttoken_handler(message: Message) -> None:
    user_id = message.from_user.id
    if user_id != Config.OWNER_ID and user_id not in Config.SUDO_USERS:
        return await message.reply("❌ Perintah ini hanya untuk admin bot.")

    if not message.reply_to_message:
        token_status = "✅ Ada" if os.path.exists(TOKEN_FILE) else "❌ Tidak ditemukan"
        secret_status = "✅ Ada" if os.path.exists(SECRET_FILE) else "❌ Tidak ditemukan"

        return await message.reply(
            f"🔑 **Status Token YouTube**\n\n"
            f"  token.json: {token_status}\n"
            f"  client_secret.json: {secret_status}\n\n"
            f"📋 **Untuk update token:**\n"
            f"Reply file `token.json` dengan `/yttoken{CMD_SUFFIX}`\n\n"
            f"📋 **Cara generate token.json:**\n"
            f"1. Jalankan `python3 get_token.py` di lokal\n"
            f"2. Login di browser\n"
            f"3. Upload `token.json` yang dihasilkan"
        )

    reply_msg = message.reply_to_message
    if not reply_msg.document:
        return await message.reply("❌ Reply file token.json yang valid.")

    try:
        await Telegram.AIOGRAM_BOT.download(reply_msg.document, destination=TOKEN_FILE)
        LOGGER.info(f"✅ token.json diupdate oleh user {user_id}")
        await message.reply("✅ **token.json berhasil diupdate!**\n\nYouTube upload sekarang aktif.")
    except Exception as e:
        LOGGER.error(f"❌ Gagal update token.json: {e}", exc_info=True)
        await message.reply(f"❌ Gagal menyimpan token: `{e}`")


# ═══════════════════════════════════════════════════════════════════════
#  NAMES EXTENSION — tambahkan ke Names.py
# ═══════════════════════════════════════════════════════════════════════
# Tambahkan baris berikut ke bot_helper/Others/Names.py:
#
#   ytupload = "YouTubeUpload"
#   STATUS["YouTubeUpload"] = "⬆️ Mengunggah YouTube"
#
# ─────────────────────────────────────────────────────────────────────
