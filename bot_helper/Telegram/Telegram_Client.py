"""
╔══════════════════════════════════════════════════════════════════════╗
║           bot_helper/Telegram/Telegram_Client.py                     ║
║           Encoder1 Bot — v3.1                                        ║
╠══════════════════════════════════════════════════════════════════════╣
║  CHANGELOG dari versi lama:                                          ║
║  [FIX HIGH]  USE_SESSION_STRING comparison string→bool               ║
║  [FIX HIGH]  Lambda closure bug di loop — pakai functools.partial    ║
║  [FIX HIGH]  Bare except → except AttributeError                    ║
║  [FIX]       get_data() di-cache di awal loop, bukan tiap akses     ║
║  [FIX]       PYROGRAM_CLIENT kondisional (jika USE_PYROGRAM=False)  ║
║  [FIX]       msg.copy() crash jika Telethon client — pakai helper   ║
║  [FIX]       uploaded_file None check sebelum send_file             ║
║  [FIX]       thumbnail exists() check                               ║
║  [FIX]       Tambah retry logic untuk upload (max 3x)               ║
║  [IMPROVE]   @staticmethod decorator untuk semua class method        ║
║  [IMPROVE]   DocumentAttributeVideo ambil w/h dari metadata         ║
║  [IMPROVE]   Cancel check terintegrasi di progress callback         ║
╚══════════════════════════════════════════════════════════════════════╝
"""

# ── Standard Library ──────────────────────────────────────────────────
import asyncio
import functools
from os import makedirs
from os.path import exists, getsize, isdir
from time import time

# ── Telethon ──────────────────────────────────────────────────────────
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.custom import Button
from telethon.tl.types import DocumentAttributeVideo

# ── Pyrogram (opsional) ───────────────────────────────────────────────
try:
    from pyrogram import Client as PyrogramClient
    from pyrogram.errors import UserIsBlocked, PeerIdInvalid
    PYROGRAM_AVAILABLE = True
except ImportError:
    PYROGRAM_AVAILABLE = False
    UserIsBlocked = Exception
    PeerIdInvalid = Exception

# ── Internal ──────────────────────────────────────────────────────────
from config.config import Config
from bot_helper.Others.Helper_Functions import (
    get_video_duration,
    get_human_size,
    get_readable_time,
    verify_rclone_account,
)
from bot_helper.Telegram.Fast_Telethon import upload_file, download_file
from bot_helper.Database.User_Data import get_data
from bot_helper.Process.Running_Process import check_running_process
from bot_helper.Others.Names import Names
from bot_helper.FFMPEG.FFMPEG_Processes import split_video_file
from bot_helper.Rclone.Rclone_Upload import upload_single_drive

LOGGER = Config.LOGGER

# ── Konstanta ─────────────────────────────────────────────────────────
DEFAULT_THUMB    = "./thumb.jpg"
MAX_TG_SIZE_FREE = 2_097_151_000   # 2GB
MAX_TG_SIZE_PREM = 4_194_304_000   # 4GB
MAX_UPLOAD_RETRY = 3               # Retry maksimum untuk upload


# ═══════════════════════════════════════════════════════════════════════
#  HELPER FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════

def create_direc(direc: str) -> None:
    """Buat direktori jika belum ada."""
    if not isdir(direc):
        makedirs(direc, exist_ok=True)


def _get_thumbnail(thumbnail_path: str | None) -> str | None:
    """
    [FIX] Validasi thumbnail — kembalikan None jika file tidak ada.
    Sebelumnya: langsung pakai path tanpa cek exists(), bisa crash.
    """
    if thumbnail_path and exists(thumbnail_path):
        return thumbnail_path
    if exists(DEFAULT_THUMB):
        return DEFAULT_THUMB
    LOGGER.warning("⚠️  Thumbnail tidak ditemukan — upload tanpa thumbnail")
    return None


async def _forward_to_log(
    msg,
    log_channel_id: int,
    upload_method: str,
) -> None:
    """
    [FIX] Forward pesan ke log channel.
    Sebelumnya: msg_in_pm.copy() selalu dipanggil — crash jika Telethon message
    karena Telethon message tidak punya method .copy() seperti Pyrogram.
    Sekarang: handle kedua client secara terpisah.
    """
    if not log_channel_id or not msg:
        return
    try:
        if upload_method == "Telethon":
            # Telethon: pakai forward_messages
            await Telegram.TELETHON_CLIENT.forward_messages(
                entity=log_channel_id,
                messages=msg.id,
                from_peer=msg.peer_id,
            )
        else:
            # Pyrogram: pakai copy_message
            await msg.copy(chat_id=log_channel_id)
    except Exception as e:
        LOGGER.warning(f"⚠️  Gagal forward ke log channel: {e}")


def _make_progress_callback(
    process_status,
    label: str,
    filename: str,
    start_time: float,
    status: str,
    upload_method: str,
    process_id: str,
) -> callable:
    """
    [FIX] Buat progress callback yang aman — tidak ada closure bug.
    
    Sebelumnya: lambda di dalam loop — variabel di-capture by reference,
    saat callback dipanggil nilai variabel sudah berubah ke iterasi terakhir.
    
    Sekarang: functools.partial atau default args untuk capture by value.
    
    Bonus: cancel check terintegrasi di sini.
    """
    def _callback(
        current: int,
        total: int,
        _label: str = label,
        _filename: str = filename,
        _start: float = start_time,
        _status: str = status,
        _method: str = upload_method,
        _pid: str = process_id,
    ):
        # Cancel check terintegrasi — tidak perlu cek setelah upload selesai
        if not check_running_process(_pid):
            raise asyncio.CancelledError("Tugas dibatalkan oleh pengguna")

        process_status.telegram_update_status(
            current, total, _label, _filename, _start, _status, _method
        )

    return _callback


async def check_size_limit() -> int:
    """
    Cek batas ukuran upload berdasarkan status Premium user.
    Return bytes maksimum yang bisa diupload.
    """
    if Telegram.TELETHON_USER_CLIENT:
        try:
            user = await Telegram.TELETHON_USER_CLIENT.get_me()
            if user and user.premium:
                return MAX_TG_SIZE_PREM
        except Exception as e:
            LOGGER.warning(f"⚠️  Gagal cek premium status: {e}")
    return MAX_TG_SIZE_FREE


async def get_split_size(user_id: int) -> int | bool:
    """
    Ambil ukuran split berdasarkan setting user.
    Return bytes jika upload ke TG, False jika tidak.
    """
    user_data = get_data().get(user_id, {})
    if not user_data.get("upload_tg"):
        return False
    if user_data.get("split") == "2GB":
        return MAX_TG_SIZE_FREE
    return await check_size_limit()


# ═══════════════════════════════════════════════════════════════════════
#  TELEGRAM CLASS
# ═══════════════════════════════════════════════════════════════════════

class Telegram:

    # ── Telethon Bot Client ────────────────────────────────────────────
    TELETHON_CLIENT = TelegramClient(
        Config.NAME,
        Config.API_ID,
        Config.API_HASH,
    )

    # ── Pyrogram Client (opsional) ─────────────────────────────────────
    # [FIX] Tidak lagi dibuat jika USE_PYROGRAM=False
    # Sebelumnya: selalu dibuat — buat session file & koneksi tidak perlu
    if Config.USE_PYROGRAM and PYROGRAM_AVAILABLE:
        PYROGRAM_CLIENT = PyrogramClient(
            f"Pyrogram_{Config.NAME}",
            api_id=Config.API_ID,
            api_hash=Config.API_HASH,
            bot_token=Config.TOKEN,
        )
    else:
        PYROGRAM_CLIENT = None
        if Config.USE_PYROGRAM and not PYROGRAM_AVAILABLE:
            LOGGER.warning("⚠️  USE_PYROGRAM=True tapi pyrogram tidak terinstall")

    # ── Telethon User Client (opsional, untuk file >2GB) ──────────────
    # [FIX] Sebelumnya: if Config.USE_SESSION_STRING=="True" — string comparison
    # Config.USE_SESSION_STRING sekarang bool (dari Step 2), jadi langsung cek
    if Config.USE_SESSION_STRING and Config.SESSION_STRING:
        TELETHON_USER_CLIENT = TelegramClient(
            StringSession(Config.SESSION_STRING),
            Config.API_ID,
            Config.API_HASH,
        )
    else:
        TELETHON_USER_CLIENT = None

    # ── Upload ke Telegram ────────────────────────────────────────────

    @staticmethod
    async def upload_videos_on_telegram(process_status) -> None:
        """
        Upload satu atau lebih file video ke Telegram.
        
        [FIX] @staticmethod decorator ditambahkan
        [FIX] get_data() di-cache di awal, bukan dipanggil tiap akses
        [FIX] Lambda closure bug diperbaiki dengan _make_progress_callback()
        [FIX] Retry logic ditambahkan (max 3x)
        [FIX] _forward_to_log() untuk handle Telethon vs Pyrogram forward
        [FIX] uploaded_file None check sebelum send_file
        [FIX] thumbnail exists() check
        """
        total_files   = len(process_status.send_files)
        files         = process_status.send_files
        user_id       = process_status.user_id
        user_pm_id    = process_status.user_id
        original_chat_id = process_status.chat_id
        caption       = process_status.caption
        event         = process_status.event
        process_id    = process_status.process_id
        log_channel_id = Config.LOG_CHANNEL_ID

        # [FIX] Ambil thumbnail dengan validasi exists()
        thumbnail = _get_thumbnail(
            process_status.thumbnail if hasattr(process_status, "thumbnail") else None
        )

        # [FIX] Cache user_data sekali di awal — tidak panggil get_data() tiap iterasi
        user_data = get_data().get(user_id, {})
        upload_method = user_data.get("tgupload", "Telethon")

        files_sent_successfully     = True
        is_user_blocked_or_not_started = False

        for i, file_path in enumerate(files):
            start_time = time()
            filename   = file_path.split("/")[-1]
            status     = f"{Names.STATUS_UPLOADING} [{i + 1}/{total_files}]"
            file_size  = getsize(file_path)
            size_limit = await check_size_limit()

            # Build caption
            file_caption = (
                f"**Nama Berkas**: `{filename}`\n{str(caption).strip()}"
                if caption
                else f"**Nama Berkas**: `{filename}`"
            )

            # [FIX] Progress callback dengan closure bug fix + cancel terintegrasi
            progress_cb = _make_progress_callback(
                process_status=process_status,
                label="Diunggah",
                filename=filename,
                start_time=start_time,
                status=status,
                upload_method=upload_method,
                process_id=process_id,
            )

            try:
                # ── CASE 1: File terlalu besar untuk Telegram ──────────
                if file_size > size_limit:
                    r_config   = f"./userdata/{user_id}_rclone.conf"
                    drive_name = user_data.get("drive_name", "")
                    if (
                        user_data.get("auto_drive")
                        and exists(r_config)
                        and verify_rclone_account(r_config, drive_name)
                    ):
                        await upload_single_drive(
                            process_status, file_path, status,
                            r_config, drive_name, filename,
                        )
                    else:
                        await event.reply(
                            f"❌ Ukuran berkas `{filename}` ({get_human_size(file_size)}) "
                            f"melebihi batas upload Telegram ({get_human_size(size_limit)}).\n"
                            f"Aktifkan **Auto Drive** untuk upload otomatis ke cloud."
                        )
                        files_sent_successfully = False

                # ── CASE 2: File ≤ 2GB — upload via bot client ─────────
                elif file_size <= MAX_TG_SIZE_FREE:
                    msg_in_pm = None

                    if upload_method == "Telethon":
                        # Telethon upload dengan retry
                        uploaded_file = await _upload_with_retry(
                            client=Telegram.TELETHON_CLIENT,
                            file_path=file_path,
                            filename=filename,
                            process_id=process_id,
                            progress_cb=progress_cb,
                        )
                        # [FIX] Cek None sebelum send_file
                        if uploaded_file is None:
                            LOGGER.error(f"❌ Upload {filename} gagal setelah {MAX_UPLOAD_RETRY}x retry")
                            files_sent_successfully = False
                            continue

                        # Ambil dimensi video untuk attribute yang benar
                        duration, width, height = _get_video_meta(file_path)
                        msg_in_pm = await Telegram.TELETHON_CLIENT.send_file(
                            user_pm_id,
                            file=uploaded_file,
                            thumb=thumbnail,
                            allow_cache=False,
                            supports_streaming=True,
                            caption=file_caption,
                            attributes=(DocumentAttributeVideo(duration, width, height),),
                        )

                    elif upload_method == "Pyrogram" and Telegram.PYROGRAM_CLIENT:
                        duration, width, height = _get_video_meta(file_path)
                        msg_in_pm = await Telegram.PYROGRAM_CLIENT.send_video(
                            chat_id=user_pm_id,
                            file_name=filename,
                            video=file_path,
                            caption=file_caption,
                            supports_streaming=True,
                            duration=duration,
                            width=width,
                            height=height,
                            thumb=thumbnail,
                            progress=process_status.telegram_update_status,
                            progress_args=(
                                "Diunggah", filename, start_time,
                                status, upload_method, Telegram.PYROGRAM_CLIENT,
                            ),
                        )
                    else:
                        await event.reply("❌ Metode upload tidak valid atau Pyrogram tidak aktif.")
                        files_sent_successfully = False
                        continue

                    # [FIX] Forward ke log channel dengan helper yang handle kedua client
                    if log_channel_id and msg_in_pm:
                        await _forward_to_log(msg_in_pm, log_channel_id, upload_method)

                # ── CASE 3: File > 2GB — upload via user client ────────
                else:
                    if Telegram.TELETHON_USER_CLIENT:
                        uploaded_file = await _upload_with_retry(
                            client=Telegram.TELETHON_USER_CLIENT,
                            file_path=file_path,
                            filename=filename,
                            process_id=process_id,
                            progress_cb=progress_cb,
                        )
                        if uploaded_file is None:
                            LOGGER.error(f"❌ Upload {filename} via user client gagal")
                            files_sent_successfully = False
                            continue

                        duration, width, height = _get_video_meta(file_path)
                        msg_in_pm = await Telegram.TELETHON_USER_CLIENT.send_file(
                            user_pm_id,
                            file=uploaded_file,
                            thumb=thumbnail,
                            allow_cache=False,
                            supports_streaming=True,
                            caption=file_caption,
                            attributes=(DocumentAttributeVideo(duration, width, height),),
                        )
                        if log_channel_id and msg_in_pm:
                            await _forward_to_log(msg_in_pm, log_channel_id, "Telethon")
                    else:
                        await event.reply(
                            f"❌ File `{filename}` ({get_human_size(file_size)}) melebihi 2GB.\n"
                            f"Tambahkan SESSION_STRING untuk upload file besar."
                        )
                        files_sent_successfully = False

            except asyncio.CancelledError:
                await event.reply("🔒 Tugas dibatalkan oleh pengguna.")
                files_sent_successfully = False
                break

            except UserIsBlocked:
                is_user_blocked_or_not_started = True
                files_sent_successfully = False
                await event.reply(
                    "‼️ **Anda telah memblokir saya.**\n\n"
                    "Silakan buka blokir di chat pribadi agar saya bisa mengirimkan berkas."
                )
                LOGGER.warning(f"User {user_pm_id} memblokir bot")
                break

            except PeerIdInvalid:
                is_user_blocked_or_not_started = True
                files_sent_successfully = False
                start_button = [Button.url("Mulai Bot", f"https://t.me/{Config.BOT_USERNAME}?start=start")]
                await event.reply(
                    "‼️ **Anda belum memulai bot.**\n\n"
                    "Klik tombol di bawah dan tekan `START` di chat pribadi, lalu coba lagi.",
                    buttons=start_button,
                )
                LOGGER.info(f"User {user_pm_id} belum mulai bot")
                break

            except Exception as e:
                files_sent_successfully = False
                LOGGER.error(f"❌ Upload error untuk {filename}: {e}", exc_info=True)
                await event.reply(f"❗ Terjadi kesalahan saat mengunggah `{filename}`:\n`{e}`")
                break

        # ── Notifikasi di group jika semua file berhasil ───────────────
        if (
            files_sent_successfully
            and hasattr(event, "is_group")
            and (event.is_group or event.is_channel)
        ):
            try:
                total_size    = sum(getsize(f) for f in process_status.send_files)
                time_taken    = get_readable_time(time() - process_status.start_time)
                output_filename = getattr(process_status, "file_name", None) or f"{total_files} Berkas"

                notif_message = (
                    f"✅ **Proses Selesai**: `{output_filename}`\n\n"
                    f"├─ 📦 **Ukuran:** `{get_human_size(total_size)}`\n"
                    f"├─ ⏱️ **Waktu:** `{time_taken}`\n"
                    f"├─ 📥 **Mode Input:** #{getattr(process_status, 'input_mode', '-')}\n"
                    f"├─ 📤 **Mode Output:** #{getattr(process_status, 'process_type', '-')}\n"
                    f"└─ 👤 **Oleh:** {getattr(process_status, 'added_by', '-')}\n\n"
                    f"👇 Hasil dikirim ke PM Anda."
                )
                pm_button = [Button.url("Buka PM", f"https://t.me/{Config.BOT_USERNAME}")]
                await Telegram.TELETHON_CLIENT.send_message(
                    original_chat_id,
                    notif_message,
                    buttons=pm_button,
                    reply_to=event.message.id,
                )
            except Exception as e:
                LOGGER.info(f"ℹ️  Gagal kirim notifikasi ke group: {e}")

    # ── Download dari Telegram ─────────────────────────────────────────

    @staticmethod
    async def download_tg_file(process_status, variables, dw_index) -> bool:
        """
        Download file dari Telegram.
        
        [FIX] Bare except → except AttributeError
        [FIX] get_data() di-cache
        """
        start_time = time()
        status     = f"{Names.STATUS_DOWNLOADING} [{dw_index}]"
        new_event  = variables[0]

        # [FIX] Bare except → except AttributeError
        # Sebelumnya: semua exception ditangkap termasuk KeyboardInterrupt
        try:
            file_name     = new_event.message.file.name
            file_location = new_event.message.document
            file_id       = new_event.message.id
        except AttributeError:
            try:
                file_name     = new_event.file.name
                file_location = new_event.document
                file_id       = new_event.id
            except AttributeError as e:
                LOGGER.error(f"❌ Tidak bisa baca file dari event: {e}")
                await new_event.reply("❗ Tidak bisa membaca informasi file dari pesan ini.")
                return False

        # Fallback nama file jika None
        if not file_name:
            file_name = f"download_{int(time())}.mp4"

        create_direc(process_status.dir)
        download_location = f"{process_status.dir}/{file_name}"
        process_status.append_dw_files(file_name)

        # [FIX] Cache user_data
        user_data        = get_data().get(process_status.user_id, {})
        download_method  = user_data.get("tgdownload", "Telethon")

        # Progress callback untuk download
        progress_cb = _make_progress_callback(
            process_status=process_status,
            label="Diunduh",
            filename=file_name,
            start_time=start_time,
            status=status,
            upload_method=download_method,
            process_id=process_status.process_id,
        )

        if download_method == "Telethon":
            try:
                with open(download_location, "wb") as f:
                    await download_file(
                        client=Telegram.TELETHON_CLIENT,
                        location=file_location,
                        out=f,
                        check_data=process_status.process_id,
                        progress_callback=progress_cb,
                    )
            except asyncio.CancelledError:
                await new_event.reply("🔒 Tugas dibatalkan oleh pengguna")
                return False
            except Exception as e:
                if str(e) == "Cancelled":
                    await new_event.reply("🔒 Tugas dibatalkan oleh pengguna")
                else:
                    await new_event.reply(f"❗ Error unduhan Telethon: `{e}`")
                    LOGGER.error(f"Telethon download error: {e}", exc_info=True)
                return False

        else:  # Pyrogram
            if not Telegram.PYROGRAM_CLIENT:
                await new_event.reply("❌ Pyrogram client tidak aktif. Set USE_PYROGRAM=True di config.")
                return False
            try:
                chat_id = (
                    Config.AUTH_GROUP_ID
                    if (process_status.event.is_group and Config.AUTH_GROUP_ID)
                    else process_status.chat_id
                )
                await Telegram.PYROGRAM_CLIENT.download_media(
                    message=(await Telegram.PYROGRAM_CLIENT.get_messages(chat_id, file_id)),
                    file_name=download_location,
                    progress=process_status.telegram_update_status,
                    progress_args=(
                        "Diunduh", file_name, start_time,
                        status, download_method, Telegram.PYROGRAM_CLIENT,
                    ),
                )
                if not check_running_process(process_status.process_id):
                    await new_event.reply("🔒 Tugas dibatalkan oleh pengguna")
                    return False
            except Exception as e:
                await new_event.reply(f"❗ Error unduhan Pyrogram: `{e}`")
                LOGGER.error(f"Pyrogram download error: {e}", exc_info=True)
                return False

        process_status.move_dw_file(file_name)
        return True

    # ── Upload dengan split otomatis ───────────────────────────────────

    @staticmethod
    async def upload_videos(process_status) -> None:
        """
        Upload video dengan auto-split jika diperlukan.
        """
        user_data = get_data().get(process_status.user_id, {})

        if user_data.get("split_video"):
            split_size = await get_split_size(process_status.user_id)
            if split_size:
                send_files = process_status.send_files.copy()
                for output_file in list(process_status.send_files):
                    if getsize(output_file) > split_size:
                        send_files.remove(output_file)
                        file_name = output_file.split("/")[-1]
                        process_status.update_process_message(
                            f"✂️ Membagi Video\n`{file_name}`\n{process_status.get_task_details()}"
                        )
                        splitted_files = await split_video_file(
                            output_file, split_size,
                            process_status.dir, process_status.event,
                        )
                        if splitted_files:
                            send_files += splitted_files
                process_status.replace_send_list(send_files)
                LOGGER.info(f"File list setelah split: {send_files}")

        await Telegram.upload_videos_on_telegram(process_status)


# ═══════════════════════════════════════════════════════════════════════
#  PRIVATE HELPERS
# ═══════════════════════════════════════════════════════════════════════

async def _upload_with_retry(
    client,
    file_path: str,
    filename: str,
    process_id: str,
    progress_cb: callable,
    max_retry: int = MAX_UPLOAD_RETRY,
) -> object | None:
    """
    [NEW] Upload file dengan retry logic (exponential backoff).
    Return uploaded_file jika berhasil, None jika semua retry gagal.
    """
    for attempt in range(1, max_retry + 1):
        try:
            with open(file_path, "rb") as f:
                uploaded_file = await upload_file(
                    client=client,
                    file=f,
                    name=filename,
                    check_data=process_id,
                    progress_callback=progress_cb,
                )
            if uploaded_file:
                return uploaded_file
            LOGGER.warning(f"⚠️  Upload {filename} attempt {attempt} return None")
        except asyncio.CancelledError:
            raise   # Jangan retry jika user cancel
        except Exception as e:
            LOGGER.warning(f"⚠️  Upload {filename} attempt {attempt}/{max_retry} gagal: {e}")
            if attempt < max_retry:
                wait_sec = 2 ** attempt   # Exponential backoff: 2s, 4s, 8s
                LOGGER.info(f"🔄 Retry dalam {wait_sec} detik...")
                await asyncio.sleep(wait_sec)
            else:
                LOGGER.error(f"❌ Upload {filename} gagal setelah {max_retry}x retry")
    return None


def _get_video_meta(file_path: str) -> tuple[int, int, int]:
    """
    [FIX] Ambil duration, width, height dari video.
    Sebelumnya: DocumentAttributeVideo(duration, 0, 0) — width/height hardcoded 0
    yang membuat video tidak tampil sebagai preview di Telegram.
    
    Return: (duration_detik, width_px, height_px)
    """
    try:
        # get_video_duration mungkin return hanya duration
        # Coba panggil dengan extended=True jika didukung
        result = get_video_duration(file_path)
        if isinstance(result, (tuple, list)) and len(result) >= 3:
            return int(result[0]), int(result[1]), int(result[2])
        # Fallback: hanya duration, width/height dari ffprobe
        duration = int(result) if result else 0
        width, height = _get_dimensions_ffprobe(file_path)
        return duration, width, height
    except Exception as e:
        LOGGER.warning(f"⚠️  Gagal baca metadata video {file_path}: {e}")
        return 0, 0, 0


def _get_dimensions_ffprobe(file_path: str) -> tuple[int, int]:
    """Ambil resolusi video menggunakan ffprobe."""
    import subprocess
    import json
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "quiet", "-print_format", "json",
                "-show_streams", "-select_streams", "v:0", file_path,
            ],
            capture_output=True, text=True, timeout=10,
        )
        data = json.loads(result.stdout)
        stream = data.get("streams", [{}])[0]
        return int(stream.get("width", 0)), int(stream.get("height", 0))
    except Exception:
        return 0, 0
