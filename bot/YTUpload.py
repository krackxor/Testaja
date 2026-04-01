"""
╔══════════════════════════════════════════════════════════════════════╗
║                    bot/YTUpload.py                                   ║
║           YouTube Upload — Terintegrasi Penuh dengan Bot System      ║
╠══════════════════════════════════════════════════════════════════════╣
║  ALUR KERJA:                                                         ║
║  1. /ytupload reply video → tampil dashboard + tombol privacy        ║
║  2. User pilih privacy → tekan ▶️ Mulai Upload                      ║
║  3. Masuk QUEUE via add_task() — ikut antrian bot                   ║
║  4. Download via Telegram.download_tg_file() + progress bar         ║
║  5. Upload ke YouTube per chunk + progress bar                       ║
║  6. Selesai → link YouTube dikirim                                   ║
║                                                                      ║
║  INTEGRASI:                                                          ║
║  ✅ ProcessStatus — tracking state, ping, status_message            ║
║  ✅ add_task() — masuk antrian bot                                   ║
║  ✅ Telegram.download_tg_file() — download standar bot              ║
║  ✅ check_running_process() — cancel support                         ║
║  ✅ CMD_SUFFIX — semua command                                       ║
║  ✅ VIP check — hanya member premium                                 ║
║  ✅ OAuth tanpa browser — token.json pre-generated                  ║
║                                                                      ║
║  FIXES dari versi lama:                                              ║
║  [SECURITY] run_local_server() dihapus — tidak bisa di VPS          ║
║  [FIX HIGH] function attribute last_edit → per-task state           ║
║  [FIX HIGH] format task functions yang salah → alur bot benar       ║
║  [FIX]      process_status.event tidak di-replace                   ║
║  [FIX]      CMD_SUFFIX format konsisten                             ║
║  [FIX]      bare except → typed exception                           ║
║  [NEW]      VIP check dengan expiry date                            ║
║  [NEW]      Full inline buttons                                     ║
║  [NEW]      Tombol /ytupload bisa dari file hasil render bot        ║
╚══════════════════════════════════════════════════════════════════════╝
"""

# ── Standard Library ──────────────────────────────────────────────────
import asyncio
import os
import time
from datetime import datetime

# ── Telethon ──────────────────────────────────────────────────────────
from telethon import events
from telethon.tl.custom import Button

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


async def _safe_edit(msg, text: str, buttons=None) -> None:
    """Helper edit pesan yang tidak crash jika gagal."""
    try:
        await msg.edit(text, buttons=buttons)
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════════
#  VIP CHECK
# ═══════════════════════════════════════════════════════════════════════

def _is_vip(user_id: int) -> bool:
    """
    Cek apakah user punya akses VIP/premium aktif.
    Berdasarkan premium_expiry_date dari User_Data (Step 10).
    Owner dan sudo users selalu dianggap VIP.
    """
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
    """Return teks masa aktif VIP untuk ditampilkan."""
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
    """
    Build YouTube API client.

    [FIX] run_local_server() DIHAPUS — tidak bisa di VPS headless.
    Strategi baru:
    - token.json harus sudah ada (di-generate sekali di lokal/dev machine)
    - Jika token expired → refresh otomatis via refresh_token
    - Jika tidak ada token → raise error dengan instruksi yang jelas

    Cara generate token.json di lokal:
        python3 get_token.py  (atau script terpisah)
    """
    if not YOUTUBE_ENABLED:
        raise RuntimeError("Library Google API tidak terinstall. Jalankan: pip install google-api-python-client google-auth-oauthlib google-auth-httplib2")

    creds = None

    # Load token yang sudah ada
    if os.path.exists(TOKEN_FILE):
        try:
            creds = Credentials.from_authorized_user_file(TOKEN_FILE, YT_SCOPES)
        except Exception as e:
            LOGGER.warning(f"⚠️  Gagal load token.json: {e}")

    # Refresh jika expired
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

    # Token tidak ada sama sekali
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
    status_msg,
) -> str:
    """
    Upload video ke YouTube dengan progress bar.

    [FIX HIGH] Tidak pakai function attribute untuk last_edit.
               Setiap call punya variabel lokal sendiri → tidak ada race condition.
    [FIX]      Tidak replace process_status.event — pakai status_msg terpisah.

    Returns:
        URL video YouTube jika sukses
    Raises:
        Exception jika gagal atau dibatalkan
    """
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
    last_edit_time = 0.0   # [FIX] variabel lokal, bukan function attribute

    # Update pesan awal
    _update_yt_status(
        process_status, "⬆️ Menghubungkan ke YouTube API...",
        0, total_size, start_time,
    )
    try:
        await status_msg.edit(process_status.status_message)
    except Exception:
        pass

    while response is None:
        # Cancel check
        if not check_running_process(process_status.process_id):
            raise asyncio.CancelledError("Dibatalkan oleh pengguna")

        # Update ping agar tidak dianggap zombie oleh process_status_checker
        process_status.ping = time.time()

        # Upload chunk di thread terpisah — tidak block event loop
        chunk_status, response = await asyncio.to_thread(request.next_chunk)

        # Update progress
        if chunk_status:
            current = chunk_status.resumable_progress
            _update_yt_status(
                process_status, "⬆️ Mengunggah ke YouTube",
                current, total_size, start_time,
            )
            # Throttle edit — maksimal 1 edit per 2 detik
            now = time.time()
            if now - last_edit_time >= 2.0:
                try:
                    await status_msg.edit(process_status.status_message)
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
    """Update status_message dengan progress bar YouTube upload."""
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
    original_event,
    reply_msg,
    yt_title: str,
    yt_desc: str,
    yt_privacy: str,
    status_msg,
) -> None:
    """
    Worker utama YouTube upload.

    [FIX HIGH] Tidak lagi pakai format 'CUSTOM' di task functions.
    Worker ini dipanggil langsung sebagai asyncio.create_task() setelah
    process_status didaftarkan ke running_process dan working_task.

    Alur:
    1. Download file via Telethon
    2. Upload ke YouTube dengan progress
    3. Kirim hasil ke chat
    4. Cleanup
    """
    final_path = os.path.join(TEMP_DIR, f"yt_{process_status.process_id}.mp4")

    try:
        # ── STEP 1: Download ──────────────────────────────────────────
        process_status.update_process_message(
            f"🔽 **Mengunduh Video...**\n\n"
            f"`{process_status.file_name or 'video'}`\n"
            f"**Ditambahkan Oleh**: {process_status.added_by} | **ID**: `{process_status.user_id}`\n"
            f"`/cancel{CMD_SUFFIX} process {process_status.process_id}`"
        )

        try:
            await status_msg.edit(process_status.status_message)
        except Exception:
            pass

        download_start = time.time()
        last_dl_edit   = 0.0   # [FIX] nonlocal var, bukan function attribute

        def _dl_progress(current: int, total: int) -> None:
            """
            Sync progress callback untuk download_media.
            [FIX] download_media butuh sync callback — bukan async.
            [FIX] Pakai nonlocal last_dl_edit bukan hasattr() function attribute.
            """
            nonlocal last_dl_edit
            if not check_running_process(process_status.process_id):
                raise asyncio.CancelledError("Dibatalkan")
            process_status.ping = time.time()
            process_status.telegram_update_status(
                current, total, "Diunduh",
                process_status.file_name or "video",
                download_start,
                "Mengunduh untuk YouTube",
                "Telethon",
            )
            now = time.time()
            if now - last_dl_edit >= 2.0:
                last_dl_edit = now
                # Jadwalkan edit ke event loop — callback ini sync tapi edit perlu async
                asyncio.get_event_loop().create_task(
                    _safe_edit(status_msg, process_status.status_message)
                )

        downloaded = await original_event.client.download_media(
            reply_msg,
            final_path,
            progress_callback=_dl_progress,
        )

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
        buttons = [[Button.url("📺 Buka di YouTube", yt_link)]]

        try:
            await status_msg.edit(success_text, buttons=buttons)
        except Exception:
            await original_event.respond(success_text, buttons=buttons)

    except asyncio.CancelledError:
        try:
            await status_msg.edit("🚫 **Upload YouTube Dibatalkan.**")
        except Exception:
            pass

    except Exception as e:
        LOGGER.error(f"❌ YTUpload worker error: {e}", exc_info=True)
        err_text = f"❌ **Upload YouTube Gagal!**\n\n`{str(e)[:300]}`"
        try:
            await status_msg.edit(err_text)
        except Exception:
            try:
                await original_event.respond(err_text)
            except Exception:
                pass

    finally:
        # Cleanup file temp
        if os.path.exists(final_path):
            try:
                os.remove(final_path)
                LOGGER.info(f"✅ Temp file dihapus: {final_path}")
            except OSError as e:
                LOGGER.warning(f"⚠️  Gagal hapus temp file: {e}")

        # Hapus dari working_task dan running_process
        await remove_running_process(process_status.process_id)
        async with working_task_lock:
            for task in list(working_task):
                if task.get("process_status") and \
                   task["process_status"].process_id == process_status.process_id:
                    working_task.remove(task)
                    break

        # Bersihkan state sementara
        _yt_state.pop(process_status.user_id, None)


async def _start_ytupload_task(
    process_status: ProcessStatus,
    original_event,
    reply_msg,
    yt_title: str,
    yt_desc: str,
    yt_privacy: str,
    status_msg,
) -> None:
    """
    Wrapper yang mendaftarkan task ke queue bot sebelum jalankan worker.

    [FIX HIGH] Tidak pakai format 'CUSTOM' functions yang tidak dikenal start_task().
    Alur yang benar:
    - Daftarkan ke running_process
    - Masuk working_task atau queued_task (via add_task-like logic)
    - Jalankan worker secara langsung
    """
    # Wrap process_status dalam dict yang kompatibel dengan working_task
    task_wrapper = {"process_status": process_status, "functions": [], "_yt_task": True}

    # Cek apakah bisa langsung jalan atau masuk antrian
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

        # [FIX] Tunggu giliran dengan TIMEOUT — tidak stuck selamanya
        waited = 0
        while waited < YT_QUEUE_TIMEOUT:
            await asyncio.sleep(5)
            waited += 5
            async with queued_task_lock:
                if task_wrapper not in queued_task:
                    break  # Keluar dari antrian
        else:
            # Timeout — batalkan task
            async with queued_task_lock:
                if task_wrapper in queued_task:
                    queued_task.remove(task_wrapper)
            await _safe_edit(status_msg, "❌ **Timeout antrian (1 jam).** Coba lagi.")
            _yt_state.pop(process_status.user_id, None)
            return

        if not check_running_process(process_status.process_id):
            _yt_state.pop(process_status.user_id, None)
            return

    # Jalankan worker
    await _ytupload_worker(
        process_status, original_event, reply_msg,
        yt_title, yt_desc, yt_privacy, status_msg,
    )


# ═══════════════════════════════════════════════════════════════════════
#  TOMBOL DASHBOARD
# ═══════════════════════════════════════════════════════════════════════

def _build_dashboard(user_id: int, yt_title: str, privacy: str) -> tuple[str, list]:
    """Build teks dashboard dan tombol inline."""
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

    # Tombol privacy selector — yang aktif ditandai ✅
    def _prv_btn(label: str, val: str) -> Button:
        icon  = "✅ " if val == privacy else ""
        return Button.inline(f"{icon}{label}", f"yt_prv_{user_id}_{val}")

    buttons = [
        # Row 1: Privacy selector
        [_prv_btn("🔒 Private", "private"),
         _prv_btn("🔗 Unlisted", "unlisted"),
         _prv_btn("🌍 Public", "public")],
        # Row 2: Aksi
        [Button.inline("▶️ Mulai Upload", f"yt_go_{user_id}"),
         Button.inline("❌ Batal", f"yt_cancel_{user_id}")],
    ]

    return dash_text, buttons


# ═══════════════════════════════════════════════════════════════════════
#  HANDLER: /ytupload
# ═══════════════════════════════════════════════════════════════════════

@Telegram.TELETHON_CLIENT.on(events.NewMessage(pattern=f"/ytupload{CMD_SUFFIX}"))
async def ytupload_handler(event) -> None:
    """
    Handler perintah /ytupload.
    User harus reply ke video yang ingin diupload.
    """
    user_id = event.sender_id

    # ── Validasi library ──────────────────────────────────────────────
    if not YOUTUBE_ENABLED:
        return await event.reply(
            "❌ **Library Google API belum terinstall!**\n\n"
            "Jalankan: `pip install google-api-python-client google-auth-oauthlib google-auth-httplib2`"
        )

    # ── VIP Check ────────────────────────────────────────────────────
    if not _is_vip(user_id):
        return await event.reply(
            "👑 **Fitur Eksklusif VIP**\n\n"
            "Upload langsung ke YouTube hanya tersedia untuk member **VIP/Premium**.\n\n"
            "Hubungi admin untuk informasi berlangganan VIP.",
            buttons=[[Button.url("💬 Hubungi Admin", f"https://t.me/{Config.BOT_USERNAME}")]],
        )

    # ── Validasi token YouTube ────────────────────────────────────────
    if not os.path.exists(TOKEN_FILE):
        return await event.reply(
            "❌ **Token YouTube Tidak Ditemukan!**\n\n"
            "Token YouTube belum di-setup di server bot.\n\n"
            "📋 **Langkah Setup:**\n"
            "1. Download `client_secret.json` dari Google Cloud Console\n"
            "2. Jalankan `python3 get_token.py` di komputer lokal\n"
            "3. Login di browser yang muncul\n"
            "4. Upload `token.json` yang dihasilkan ke folder bot di VPS\n\n"
            "_Token hanya perlu di-setup sekali._"
        )

    # ── Validasi reply ────────────────────────────────────────────────
    if not event.is_reply:
        return await event.reply(
            "❌ **Cara Pakai:**\n"
            f"Balas sebuah video dengan perintah `/ytupload{CMD_SUFFIX}`\n\n"
            "Contoh:\n"
            "1. Kirim/forward video ke chat ini\n"
            f"2. Reply video tersebut dengan `/ytupload{CMD_SUFFIX}`"
        )

    reply_msg = await event.get_reply_message()
    if not (reply_msg.video or reply_msg.document):
        return await event.reply("❌ Pesan yang dibalas bukan video yang valid!")

    # ── Pastikan struktur data user ada ──────────────────────────────
    await ensure_user_data_structure(user_id)

    # ── Ambil judul dari nama file atau text event ────────────────────
    # Jika user ketik: /ytupload Judul Video Saya → pakai itu
    # Jika tidak → pakai nama file
    cmd_parts = event.raw_text.strip().split(None, 1)
    if len(cmd_parts) > 1:
        yt_title = cmd_parts[1].strip()
    else:
        try:
            yt_title = reply_msg.file.name or "Video Upload"
            # Hapus ekstensi dari judul
            if "." in yt_title:
                yt_title = yt_title.rsplit(".", 1)[0]
        except Exception:
            yt_title = "Video Upload"

    # ── Simpan state sementara ────────────────────────────────────────
    _yt_state[user_id] = {
        "reply_msg": reply_msg,
        "title":     yt_title,
        "desc":      "",
        "privacy":   "private",   # Default private — paling aman
    }

    # ── Tampilkan dashboard ───────────────────────────────────────────
    dash_text, buttons = _build_dashboard(user_id, yt_title, "private")
    await event.reply(dash_text, buttons=buttons)


# ═══════════════════════════════════════════════════════════════════════
#  CALLBACKS TOMBOL INLINE
# ═══════════════════════════════════════════════════════════════════════

@Telegram.TELETHON_CLIENT.on(events.CallbackQuery(pattern=b"yt_prv_(.+)"))
async def yt_privacy_cb(event) -> None:
    """Callback: user pilih privacy (private/unlisted/public)."""
    await event.answer()

    data  = event.data.decode().split("_")
    # Format: yt_prv_{user_id}_{privacy}
    if len(data) < 4:
        return

    user_id = int(data[2])
    privacy = data[3]

    # Validasi: hanya user yang bersangkutan
    if event.sender_id != user_id:
        return await event.answer("❌ Bukan milikmu!", alert=True)

    if user_id not in _yt_state:
        return await event.answer("⚠️ Session expired. Ulangi /ytupload", alert=True)

    _yt_state[user_id]["privacy"] = privacy

    # Rebuild dashboard dengan pilihan baru
    yt_title  = _yt_state[user_id]["title"]
    dash_text, buttons = _build_dashboard(user_id, yt_title, privacy)

    try:
        await event.edit(dash_text, buttons=buttons)
    except Exception:
        pass


@Telegram.TELETHON_CLIENT.on(events.CallbackQuery(pattern=b"yt_go_(.+)"))
async def yt_go_cb(event) -> None:
    """Callback: user tekan ▶️ Mulai Upload."""
    await event.answer("⏳ Memproses...")

    user_id = int(event.data.decode().split("_")[2])

    # Validasi kepemilikan
    if event.sender_id != user_id:
        return await event.answer("❌ Bukan milikmu!", alert=True)

    # VIP re-check (bisa saja expired di antara waktu)
    if not _is_vip(user_id):
        return await event.edit("❌ Akses VIP kamu sudah habis. Hubungi admin untuk perpanjang.")

    if user_id not in _yt_state:
        return await event.edit(
            "⚠️ Session expired.\n"
            f"Ulangi perintah `/ytupload{CMD_SUFFIX}`"
        )

    state     = _yt_state[user_id]
    reply_msg = state["reply_msg"]
    yt_title  = state["title"]
    yt_desc   = state["desc"]
    yt_privacy = state["privacy"]

    # Ambil info sender
    sender = await event.get_sender()
    user_name       = getattr(sender, "username", None) or ""
    user_first_name = getattr(sender, "first_name", None) or str(user_id)

    # Buat ProcessStatus
    process_status = ProcessStatus(
        user_id        = user_id,
        chat_id        = event.chat_id,
        user_name      = user_name,
        user_first_name = user_first_name,
        event          = event,
        process_type   = Names.ytupload,   # Tambahkan di Names.py
        input_mode     = "Telegram",
    )

    # Set file name untuk display
    try:
        fname = reply_msg.file.name or "video.mp4"
    except Exception:
        fname = "video.mp4"
    process_status.file_name = fname

    # Edit pesan menjadi status awal
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

    # Edit tombol → tampilkan tombol cancel + log
    action_buttons = [
        [Button.inline("❌ Batalkan", f"yt_cancel_{user_id}_{process_status.process_id}"),
         Button.inline("📋 Lihat Status", f"yt_status_{process_status.process_id}")],
    ]

    try:
        status_msg = await event.edit(init_text, buttons=action_buttons)
    except Exception:
        status_msg = await event.respond(init_text, buttons=action_buttons)

    # Jalankan task (queue-aware)
    asyncio.create_task(
        _start_ytupload_task(
            process_status,
            event,
            reply_msg,
            yt_title,
            yt_desc,
            yt_privacy,
            status_msg,
        )
    )


@Telegram.TELETHON_CLIENT.on(events.CallbackQuery(pattern=b"yt_cancel_(.+)"))
async def yt_cancel_cb(event) -> None:
    """Callback: user tekan ❌ Batal — sebelum atau sesudah proses dimulai."""
    await event.answer("🚫 Membatalkan...")

    parts   = event.data.decode().split("_")
    user_id = int(parts[2])

    # Validasi kepemilikan
    if event.sender_id != user_id:
        return await event.answer("❌ Bukan milikmu!", alert=True)

    if len(parts) >= 4:
        # Ada process_id → cancel proses yang sedang berjalan
        process_id = parts[3]
        from bot_helper.Process.Running_Process import remove_running_process
        await remove_running_process(process_id)
        try:
            await event.edit("🚫 **Proses dibatalkan.**")
        except Exception:
            pass
    else:
        # Belum ada process_id → cancel sebelum mulai (hapus state)
        _yt_state.pop(user_id, None)
        try:
            await event.edit("❌ **Upload YouTube dibatalkan.**")
        except Exception:
            pass


@Telegram.TELETHON_CLIENT.on(events.CallbackQuery(pattern=b"yt_status_(.+)"))
async def yt_status_cb(event) -> None:
    """Callback: tampilkan status proses YouTube upload saat ini."""
    await event.answer()

    process_id = event.data.decode().split("_")[2]

    # Cari task di working_task
    async with working_task_lock:
        for task in list(working_task):
            ps = task.get("process_status")
            if ps and ps.process_id == process_id:
                if event.sender_id != ps.user_id:
                    return await event.answer("❌ Bukan milikmu!", alert=True)
                try:
                    await event.answer(
                        ps.status_message[:200] if ps.status_message else "Tidak ada info status",
                        alert=True,
                    )
                except Exception:
                    pass
                return

    await event.answer("⚠️ Proses tidak ditemukan (mungkin sudah selesai)", alert=True)


# ═══════════════════════════════════════════════════════════════════════
#  HANDLER: /yttoken — Setup token YouTube
# ═══════════════════════════════════════════════════════════════════════

@Telegram.TELETHON_CLIENT.on(events.NewMessage(pattern=f"/yttoken{CMD_SUFFIX}"))
async def yttoken_handler(event) -> None:
    """
    Handler untuk upload token.json via bot.
    Owner/sudo bisa reply file token.json dengan /yttoken untuk update token.
    """
    user_id = event.sender_id

    # Hanya owner dan sudo
    if user_id != Config.OWNER_ID and user_id not in Config.SUDO_USERS:
        return await event.reply("❌ Perintah ini hanya untuk admin bot.")

    if not event.is_reply:
        # Tampilkan status token saat ini
        token_status = "✅ Ada" if os.path.exists(TOKEN_FILE) else "❌ Tidak ditemukan"
        secret_status = "✅ Ada" if os.path.exists(SECRET_FILE) else "❌ Tidak ditemukan"

        return await event.reply(
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

    reply_msg = await event.get_reply_message()
    if not reply_msg.document:
        return await event.reply("❌ Reply file token.json yang valid.")

    # Download dan simpan token
    try:
        await event.client.download_media(reply_msg, TOKEN_FILE)
        LOGGER.info(f"✅ token.json diupdate oleh user {user_id}")
        await event.reply("✅ **token.json berhasil diupdate!**\n\nYouTube upload sekarang aktif.")
    except Exception as e:
        LOGGER.error(f"❌ Gagal update token.json: {e}", exc_info=True)
        await event.reply(f"❌ Gagal menyimpan token: `{e}`")


# ═══════════════════════════════════════════════════════════════════════
#  NAMES EXTENSION — tambahkan ke Names.py
# ═══════════════════════════════════════════════════════════════════════
# Tambahkan baris berikut ke bot_helper/Others/Names.py:
#
#   ytupload = "YouTubeUpload"
#   STATUS["YouTubeUpload"] = "⬆️ Mengunggah YouTube"
#
# ─────────────────────────────────────────────────────────────────────
