"""
╔══════════════════════════════════════════════════════════════════════╗
║              bot_helper/Upload/Rclone_Upload.py — v3.1              ║
║                    Rclone Upload Engine                              ║
╠══════════════════════════════════════════════════════════════════════╣
║  FIXES dari versi lama:                                              ║
║  [FIX HIGH]  get_data()[user_id]['drive_name'] → .get() double      ║
║  [FIX HIGH]  r_config tidak divalidasi exists() → cek dulu         ║
║  [FIX HIGH]  event.reply() tanpa try/except → bungkus safe_reply   ║
║  [FIX]       for i in range(total_files) → for filepath in files    ║
║  [FIX]       variable q dead code → dihapus                        ║
║  [FIX]       re.escape() bukan untuk rclone glob → dihapus         ║
║  [FIX]       Tidak ada rclone binary check → shutil.which()        ║
║  [IMPROVE]   Indentasi 24+ spaces → 4 spaces standard              ║
║  [NEW]       upload_drive() return detail hasil per file            ║
╚══════════════════════════════════════════════════════════════════════╝
"""

# ── Standard Library ──────────────────────────────────────────────────
import os
import shutil
from asyncio import create_subprocess_exec
from asyncio.subprocess import PIPE as asyncioPIPE
from typing import Optional

# ── Internal ──────────────────────────────────────────────────────────
from bot_helper.Database.User_Data import get_data
from bot_helper.Others.Names import Names
from config.config import Config

LOGGER = Config.LOGGER

# [FIX] Cek rclone binary saat import — error lebih informatif
_RCLONE_BIN = shutil.which("rclone")
if not _RCLONE_BIN:
    LOGGER.warning("⚠️  rclone binary tidak ditemukan di PATH. Fitur upload ke Drive tidak akan berfungsi.")


def _get_rclone_config(user_id: int) -> str:
    """Return path rclone config file untuk user."""
    return f"./userdata/{user_id}_rclone.conf"


async def _safe_reply(process_status, text: str) -> None:
    """
    Kirim reply dengan error handling.
    [FIX HIGH] event.reply() bisa crash jika event expired — bungkus try/except.
    """
    try:
        await process_status.event.reply(text)
    except Exception as e:
        LOGGER.warning(f"⚠️  Gagal reply ke user {process_status.user_id}: {e}")


def _build_rclone_commands(
    filepath: str,
    filename: str,
    r_config: str,
    drive_name: str,
) -> tuple[list, list]:
    """
    Build rclone copy command dan lsjson search command.

    [FIX] Hapus re.escape() — rclone pakai glob pattern, bukan regex.
          re.escape() mengubah titik jadi \\. yang tidak valid di rclone filter.

    Returns:
        (copy_command, search_command)
    """
    copy_command = [
        "rclone", "copy",
        f"--config={r_config}",
        str(filepath),
        f"{drive_name}:/",
        "-f", "- *.!qB",         # Exclude file incomplete qBittorrent
        "--buffer-size=1M",
        "-P",                      # Progress output ke stdout
    ]

    # [FIX] Tidak pakai re.escape() untuk rclone glob filter
    # Rclone filter sudah handle nama file literal dengan benar
    search_command = [
        "rclone", "lsjson",
        f"--config={r_config}",
        f"{drive_name}:/",
        "--files-only",
        "-f", f"+ {filename}",   # Filter: hanya file dengan nama ini
        "-f", "- *",              # Exclude semua yang lain
    ]

    return copy_command, search_command


async def _run_upload(
    process_status,
    filepath: str,
    filename: str,
    r_config: str,
    drive_name: str,
    status_label: str,
) -> bool:
    """
    Jalankan satu upload rclone dan pantau progress.

    Returns:
        True jika sukses, False jika dibatalkan atau error.
    """
    copy_command, search_command = _build_rclone_commands(
        filepath, filename, r_config, drive_name
    )

    rclone_process = await create_subprocess_exec(
        *copy_command,
        stdout=asyncioPIPE,
        stderr=asyncioPIPE,
    )

    try:
        result = await process_status.rclone__update_status(
            rclone_process,
            filename,
            search_command,
            filepath,
            r_config,
            drive_name,
            status_label,
        )
        return bool(result)
    except Exception as e:
        LOGGER.error(f"❌ Upload {filename} ke Drive gagal: {e}", exc_info=True)
        await _safe_reply(
            process_status,
            f"❌ Error saat mengunggah `{filename}` ke Drive\n\n`{str(e)[:300]}`",
        )
        return False


# ═══════════════════════════════════════════════════════════════════════
#  PUBLIC API
# ═══════════════════════════════════════════════════════════════════════

async def upload_drive(process_status) -> dict:
    """
    Upload semua file di process_status.send_files ke Google Drive via rclone.

    [FIX HIGH] get_data() pakai .get() — tidak crash jika user_id atau drive_name tidak ada
    [FIX HIGH] Validasi r_config exists() sebelum jalankan rclone
    [FIX HIGH] event.reply() dibungkus _safe_reply()
    [FIX]      Iterasi for filepath in files — tidak pakai index
    [FIX]      Variable q dead code dihapus
    [FIX]      os.path.basename() menggantikan .split('/')[-1]

    Returns:
        dict dengan key 'success', 'failed', 'cancelled'
    """
    if not _RCLONE_BIN:
        await _safe_reply(process_status, "❌ rclone tidak terinstall di server.")
        return {"success": 0, "failed": 0, "cancelled": False}

    user_id    = process_status.user_id
    files      = process_status.send_files
    total      = len(files)
    r_config   = _get_rclone_config(user_id)

    # [FIX HIGH] .get() double — tidak crash jika key tidak ada
    user_data  = get_data().get(user_id, {})
    drive_name = user_data.get("drive_name")

    # Validasi drive_name
    if not drive_name:
        await _safe_reply(
            process_status,
            "❌ Drive belum dikonfigurasi.\n"
            "Gunakan `/settings` untuk mengatur drive tujuan.",
        )
        return {"success": 0, "failed": 0, "cancelled": False}

    # [FIX HIGH] Validasi rclone config exists
    if not os.path.exists(r_config):
        await _safe_reply(
            process_status,
            f"❌ File konfigurasi rclone tidak ditemukan.\n"
            f"Setup rclone untuk akun ini terlebih dahulu.",
        )
        return {"success": 0, "failed": 0, "cancelled": False}

    LOGGER.info(f"Rclone upload: {total} file → {drive_name}:/ (user={user_id})")

    success_count = 0
    failed_count  = 0

    # [FIX] Iterasi langsung — tidak pakai for i in range(total)
    for idx, filepath in enumerate(files, 1):
        # [FIX] os.path.basename() — handle semua OS path separator
        filename     = os.path.basename(filepath)
        status_label = f"{Names.STATUS_UPLOADING} [{idx}/{total}]"

        if not os.path.exists(filepath):
            LOGGER.warning(f"⚠️  File tidak ditemukan, skip: {filepath}")
            failed_count += 1
            continue

        LOGGER.info(f"Rclone upload [{idx}/{total}]: {filename}")
        ok = await _run_upload(process_status, filepath, filename, r_config, drive_name, status_label)

        if not ok:
            # Cek apakah dibatalkan atau error
            if not process_status.send_files:
                # send_files dikosongkan = di-cancel dari luar
                await _safe_reply(process_status, "🔒 Tugas Dibatalkan Oleh Pengguna")
                return {"success": success_count, "failed": failed_count, "cancelled": True}

            # rclone__update_status return False = user cancel
            failed_count += 1
            await _safe_reply(process_status, "🔒 Tugas Dibatalkan Oleh Pengguna")
            return {"success": success_count, "failed": failed_count, "cancelled": True}

        success_count += 1

    LOGGER.info(f"Rclone upload selesai: {success_count}/{total} berhasil, {failed_count} gagal")
    return {"success": success_count, "failed": failed_count, "cancelled": False}


async def upload_single_drive(
    process_status,
    file: str,
    status: str,
    r_config: str,
    drive_name: str,
    filename: Optional[str] = None,
) -> bool:
    """
    Upload satu file ke Drive via rclone.

    [FIX HIGH] event.reply() dibungkus _safe_reply()
    [FIX HIGH] Validasi r_config dan rclone binary
    [FIX]      filename default ke os.path.basename(file) jika tidak diberikan

    Args:
        process_status: ProcessStatus object
        file:           Path file yang akan diupload
        status:         Label status untuk ditampilkan
        r_config:       Path ke rclone config file
        drive_name:     Nama remote rclone (tanpa ':/') 
        filename:       Nama file di Drive (default: basename dari file)

    Returns:
        True jika sukses, False jika gagal/dibatalkan.
    """
    if not _RCLONE_BIN:
        await _safe_reply(process_status, "❌ rclone tidak terinstall di server.")
        return False

    # [FIX] Default filename dari path jika tidak diberikan
    if not filename:
        filename = os.path.basename(file)

    # [FIX HIGH] Validasi file dan config
    if not os.path.exists(file):
        LOGGER.warning(f"⚠️  File tidak ditemukan: {file}")
        await _safe_reply(process_status, f"❌ File `{filename}` tidak ditemukan.")
        return False

    if not os.path.exists(r_config):
        await _safe_reply(
            process_status,
            "❌ File konfigurasi rclone tidak ditemukan.\nSetup rclone terlebih dahulu.",
        )
        return False

    LOGGER.info(f"Rclone single upload: {filename} → {drive_name}:/")
    return await _run_upload(process_status, file, filename, r_config, drive_name, status)
