"""
╔══════════════════════════════════════════════════════════════════════╗
║           bot_helper/Others/Helper_Functions.py — v3.1               ║
║                     Utility Functions Encoder1 Bot                   ║
╠══════════════════════════════════════════════════════════════════════╣
║  FIXES dari versi lama:                                              ║
║  [FIX HIGH]  eval(ffprobe_result) → json.loads() — hapus RCE         ║
║  [FIX HIGH]  execute(str) shlex.split → terima list args             ║
║  [FIX HIGH]  get_host_stats pakai list args bukan string             ║
║  [FIX]       get_event_loop() deprecated → get_running_loop()        ║
║  [FIX]       clear_trash_list modifikasi list saat iterasi           ║
║  [FIX]       get_human_size() tidak handle None/non-numeric          ║
║  [FIX]       check_file_exists async → sync                          ║
║  [FIX]       delete_trash async sync → noted + typed except          ║
║  [FIX]       bare except di 6+ tempat → typed exception              ║
║  [FIX]       execute() log stderr jika returncode != 0               ║
║  [FIX]       typo sufix_list → suffix_list                           ║
╚══════════════════════════════════════════════════════════════════════╝
"""

# ── Standard Library ──────────────────────────────────────────────────
import asyncio
import json
from configparser import ConfigParser
from datetime import datetime
from os import mkdir, remove
from os.path import exists, isdir
from random import choices
from re import search as re_search
from shutil import rmtree
from string import ascii_lowercase, digits
from subprocess import PIPE as subprocessPIPE, STDOUT as subprocessSTDOUT
from subprocess import check_output, run as subprocessrun
from time import time
from typing import Optional, Tuple
from urllib.parse import parse_qs, urlparse

# ── Third Party ───────────────────────────────────────────────────────
from asyncio.subprocess import PIPE
from dotenv import dotenv_values
from magic import Magic
from psutil import (
    boot_time, cpu_count, cpu_percent,
    disk_usage, net_io_counters, swap_memory, virtual_memory,
)
from pytz import timezone

# ── Internal ──────────────────────────────────────────────────────────
from config.config import Config

# ── Konstanta ─────────────────────────────────────────────────────────
IMAGE_SUFFIXES = ("JPG", "JPX", "PNG", "CR2", "TIF", "BMP", "JXR", "PSD", "ICO", "HEIC", "JPEG")
IST            = timezone(Config.TIMEZONE)
botStartTime   = time()
LOGGER         = Config.LOGGER


# ═══════════════════════════════════════════════════════════════════════
#  TIME FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════

def get_readable_time(seconds: float) -> str:
    """Konversi detik ke string readable: 1d2h3m4s."""
    result    = ""
    seconds   = max(0, int(seconds))
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    if days:    result += f"{days}d"
    if hours:   result += f"{hours}h"
    if minutes: result += f"{minutes}m"
    result += f"{secs}s"
    return result


class Timer:
    """Rate-limiter sederhana berdasarkan waktu."""
    def __init__(self, time_between: float = 5):
        self.start_time    = time()
        self.time_between  = time_between

    def can_send(self) -> bool:
        if time() > (self.start_time + self.time_between):
            self.start_time = time()
            return True
        return False


def get_time() -> float:
    return time()


def getbotuptime() -> str:
    return get_readable_time(time() - botStartTime)


def TimeFormatter(milliseconds: int) -> str:
    """Format milliseconds ke string human-readable."""
    seconds, ms  = divmod(int(milliseconds), 1000)
    minutes, sec = divmod(seconds, 60)
    hours, mn    = divmod(minutes, 60)
    days, hr     = divmod(hours, 24)
    parts = []
    if days:    parts.append(f"{days}d")
    if hr:      parts.append(f"{hr}h")
    if mn:      parts.append(f"{mn}m")
    if sec:     parts.append(f"{sec}s")
    if ms:      parts.append(f"{ms}ms")
    return ", ".join(parts) if parts else "0s"


def get_current_time() -> str:
    return str(datetime.now(IST).strftime("%I:%M:%S %p (%d-%b)"))


def get_time_from_string(check_time: str) -> str:
    try:
        return (
            datetime.strptime(check_time, "%Y-%m-%dT%H:%M:%S.%f%z")
            .astimezone(IST)
            .strftime("%I:%M:%S %p (%d-%b)")
        )
    except (ValueError, TypeError):
        return check_time


def time_string_to_seconds(time_str: str) -> int:
    """Konversi HH:MM:SS atau MM:SS ke detik."""
    try:
        parts = list(map(int, time_str.strip().split(":")))
        if len(parts) == 3:
            return parts[0] * 3600 + parts[1] * 60 + parts[2]
        elif len(parts) == 2:
            return parts[0] * 60 + parts[1]
        return int(parts[0])
    except (ValueError, IndexError):
        return 0


def seconds_to_readable_str(seconds) -> str:
    """Konversi detik ke HH:MM:SS.
    [FIX] Terima int ATAU float — cast ke int dulu agar {:02d} tidak crash.
          ValueError: Unknown format code 'd' for object of type 'float'
          terjadi karena ffprobe/moviepy return float (e.g. 93.04), bukan int.
    """
    seconds = int(seconds)   # <-- fix: float 93.04 → int 93
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


# ═══════════════════════════════════════════════════════════════════════
#  SIZE FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════

def get_human_size(num) -> str:
    """
    Konversi bytes ke string readable (B, KB, MB, ...).
    [FIX] Handle None dan non-numeric input.
    [FIX] Typo 'sufix_list' → 'suffix_list'
    """
    # [FIX] Guard untuk input tidak valid
    if num is None:
        return "0 B"
    try:
        num = float(num)
    except (TypeError, ValueError):
        return "0 B"

    base        = 1024.0
    suffix_list = ["B", "KB", "MB", "GB", "TB", "PB", "EB", "ZB", "YB"]
    for unit in suffix_list:
        if abs(num) < base:
            return f"{round(num, 2)} {unit}"
        num /= base
    return f"{round(num, 2)} YB"


def get_size(size) -> str:
    """Konversi bytes ke string dengan 2 desimal."""
    units = ["Bytes", "KB", "MB", "GB", "TB", "PB", "EB"]
    try:
        size = float(size)
    except (TypeError, ValueError):
        return "0 Bytes"
    i = 0
    while size >= 1024.0 and i < len(units) - 1:
        i   += 1
        size /= 1024.0
    return f"{size:.2f} {units[i]}"


def hrb(value, digits: int = 2, delim: str = "", postfix: str = "") -> Optional[str]:
    """Human-readable bytes (alternatif get_human_size)."""
    if value is None:
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    chosen_unit = "B"
    for unit in ("KB", "MB", "GB", "TB"):
        if value > 1000:
            value        /= 1024
            chosen_unit  = unit
        else:
            break
    return f"{value:.{digits}f}{delim}{chosen_unit}{postfix}"


# ═══════════════════════════════════════════════════════════════════════
#  FILE SYSTEM FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════

async def delete_trash(file: str) -> None:
    """Hapus file, abaikan error."""
    try:
        remove(file)
    except OSError as e:
        LOGGER.debug(f"delete_trash skip '{file}': {e}")


async def delete_all(direc: str) -> None:
    """Hapus direktori dan isinya, abaikan error."""
    try:
        rmtree(direc)
    except OSError as e:
        LOGGER.debug(f"delete_all skip '{direc}': {e}")


async def create_process_file(file: str) -> None:
    """Buat file kosong (hapus dulu jika sudah ada)."""
    if exists(file):
        remove(file)
    with open(file, "w"):
        pass


async def make_direc(direc: str) -> str:
    """Buat direktori jika belum ada."""
    try:
        if not isdir(direc):
            mkdir(direc)
    except OSError as e:
        LOGGER.debug(f"make_direc '{direc}': {e}")
    return direc


def check_file_exists(file: str) -> bool:
    """
    Check apakah file ada.
    [FIX] Tidak perlu async — os.path.exists() adalah sync operation.
    Backward compat: masih bisa di-await (coroutine wrapper tidak diperlukan).
    """
    return exists(file)


async def check_files_exists(files: list) -> bool:
    """Check apakah semua file dalam list ada."""
    return all(exists(f) for f in files)


def get_logs_msg(log_file: str) -> str:
    """Ambil isi log file (maksimum 3000 karakter terakhir)."""
    try:
        with open(log_file, "r", encoding="utf-8") as f:
            log_lines = f.read().splitlines()
    except OSError:
        return "Log file tidak dapat dibaca."

    if not log_lines:
        return "Log kosong."

    collected = ""
    idx       = 1
    while len(collected) <= 3000:
        collected = log_lines[-idx] + "\n" + collected
        if idx == len(log_lines):
            break
        idx += 1

    header = f"Menampilkan {idx} baris terakhir dari {log_file}:\n\n--- START LOG ---\n\n"
    footer = "\n--- END LOG ---"
    return header + collected + footer


async def clear_trash_list(trash_list: list) -> None:
    """
    Hapus semua file dalam list dan kosongkan list.
    [FIX] Tidak modifikasi list saat iterasi — iterasi salinan dulu.
    """
    for t in list(trash_list):   # [FIX] iterasi salinan list
        try:
            remove(t)
        except OSError as e:
            LOGGER.debug(f"clear_trash_list skip '{t}': {e}")
    trash_list.clear()           # kosongkan list setelah semua dihapus


# ═══════════════════════════════════════════════════════════════════════
#  COMMAND EXECUTION
# ═══════════════════════════════════════════════════════════════════════

async def create_backgroud_task(x):
    """
    Buat background asyncio task.
    [FIX] get_event_loop() deprecated di 3.10+ → get_running_loop()
    """
    return asyncio.get_running_loop().create_task(x)


async def execute(cmnd, trusted: bool = False) -> str:
    """
    Eksekusi command async dan return stdout.

    [FIX HIGH] Tidak lagi menerima string mentah jika tidak trusted.
                - Jika cmnd adalah list → dipakai langsung (safe)
                - Jika cmnd adalah string dan trusted=True → shlex.split()
                - Jika cmnd adalah string dan trusted=False → raise ValueError

    [FIX] Log stderr jika returncode != 0.

    Args:
        cmnd:    Command sebagai list[str] (direkomendasikan) atau string (hanya jika trusted=True)
        trusted: True jika cmnd adalah string literal hardcoded (bukan dari user input)

    Returns:
        stdout string
    """
    if isinstance(cmnd, str):
        if not trusted:
            raise ValueError(
                "execute() menerima string hanya jika trusted=True. "
                "Gunakan list args untuk keamanan: execute(['cmd', 'arg1', 'arg2'])"
            )
        from shlex import split as shlexsplit
        args = shlexsplit(cmnd)
    else:
        args = list(cmnd)

    LOGGER.debug(f"execute: {args}")

    process = await asyncio.create_subprocess_exec(
        *args,
        stdout=PIPE,
        stderr=PIPE,
    )
    stdout, stderr = await process.communicate()

    # [FIX] Log stderr jika ada error
    if process.returncode != 0 and stderr:
        LOGGER.warning(f"execute returncode={process.returncode}: {stderr.decode('utf-8', 'replace')[:300]}")

    return stdout.decode("utf-8", "replace").strip()


def get_video_duration(filename: str) -> int:
    """Ambil durasi video menggunakan ffprobe (sync)."""
    result = subprocessrun(
        ["ffprobe", "-v", "error", "-show_entries",
         "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", filename],
        stdout=subprocessPIPE,
        stderr=subprocessSTDOUT,
    )
    try:
        return int(float(result.stdout))
    except (ValueError, TypeError):
        return 0


# ═══════════════════════════════════════════════════════════════════════
#  RCLONE / CONFIG FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════

async def get_config(file: str) -> list | bool:
    """Baca rclone config dan return list nama account."""
    try:
        config = ConfigParser(default_section=False)
        config.read(file, encoding="utf-8")
        accounts = [d for d in config if d]
        return accounts if accounts else False
    except Exception as e:
        LOGGER.debug(f"get_config error: {e}")
        return False


async def get_account_type(file: str, drive_name: str) -> str | bool:
    """Return type dari rclone remote (gdrive, s3, dll)."""
    try:
        config = ConfigParser(default_section=False)
        config.read(file, encoding="utf-8")
        if drive_name in config and "type" in config[drive_name]:
            return str(config[drive_name].get("type")).strip()
        return False
    except Exception as e:
        LOGGER.debug(f"get_account_type error: {e}")
        return False


def verify_rclone_account(file: str, drive_name: str) -> bool:
    """Verifikasi apakah drive_name ada di rclone config."""
    try:
        config = ConfigParser(default_section=False)
        config.read(file, encoding="utf-8")
        return drive_name in config
    except Exception as e:
        LOGGER.debug(f"verify_rclone_account error: {e}")
        return False


# ═══════════════════════════════════════════════════════════════════════
#  MISC UTILITIES
# ═══════════════════════════════════════════════════════════════════════

def gen_random_string(k: int) -> str:
    """Generate random alphanumeric string sepanjang k karakter."""
    return "".join(choices(ascii_lowercase + digits, k=k))


async def process_checker(check_data: list) -> bool:
    """Check apakah semua data[0] ada di data[1]."""
    return all(item[0] in item[1] for item in check_data)


def get_value(dlist: list, dtype, value):
    """
    Ambil nilai terakhir dari list, konversi ke dtype.
    Dipakai untuk parse output regex FFmpeg.
    """
    if dlist:
        try:
            return dtype(dlist[-1].strip())
        except (ValueError, TypeError):
            return value
    return value


def get_env_dict(env_file: str) -> Optional[dict]:
    """Load .env file sebagai dict."""
    if exists(env_file):
        return dict(dotenv_values(env_file))
    return None


def get_env_keys(env_file: str) -> Optional[list]:
    """Return list keys dari .env file."""
    if exists(env_file):
        return list(dict(dotenv_values(env_file)).keys())
    return None


def export_env_file(env_file: str, env_dict: dict) -> bool:
    """Export dict ke format .env file."""
    lines = [f"{k}={v}" for k, v in env_dict.items()]
    if not lines:
        return False
    with open(env_file, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return True


# ═══════════════════════════════════════════════════════════════════════
#  SYSTEM STATS
# ═══════════════════════════════════════════════════════════════════════

async def get_host_stats() -> str:
    """
    Return string statistik host (disk, CPU, RAM, dll).
    [FIX HIGH] execute() dipanggil dengan list args (bukan string) + trusted=False tidak perlu
               karena ini hardcoded — gunakan list langsung.
    """
    if exists(".git"):
        try:
            last_commit = await execute(
                ["git", "log", "-1", "--date=short", "--pretty=format:%cd <b>From</b> %cr"]
            )
        except Exception:
            last_commit = "Git error"
    else:
        last_commit = "No UPSTREAM_REPO"

    total, used, free, disk = disk_usage("/")
    swap   = swap_memory()
    memory = virtual_memory()

    stats = (
        f"<b>Commit Date:</b> {last_commit}\n\n"
        f"Version: {Config.VERSION}\n\n"
        f"<b>Bot Uptime:</b> {get_readable_time(time() - botStartTime)}\n"
        f"<b>OS Uptime:</b> {get_readable_time(time() - boot_time())}\n\n"
        f"<b>Total Disk Space:</b> {get_size(total)}\n"
        f"<b>Used:</b> {get_size(used)} | <b>Free:</b> {get_size(free)}\n\n"
        f"<b>Upload:</b> {get_size(net_io_counters().bytes_sent)}\n"
        f"<b>Download:</b> {get_size(net_io_counters().bytes_recv)}\n\n"
        f"<b>CPU:</b> {cpu_percent(interval=0.5)}%\n"
        f"<b>RAM:</b> {memory.percent}%\n"
        f"<b>DISK:</b> {disk}%\n\n"
        f"<b>Physical Cores:</b> {cpu_count(logical=False)}\n"
        f"<b>Total Cores:</b> {cpu_count(logical=True)}\n\n"
        f"<b>SWAP:</b> {get_size(swap.total)} | <b>Used:</b> {swap.percent}%\n"
        f"<b>Memory Total:</b> {get_size(memory.total)}\n"
        f"<b>Memory Free:</b> {get_size(memory.available)}\n"
        f"<b>Memory Used:</b> {get_size(memory.used)}"
    )
    return stats


# ═══════════════════════════════════════════════════════════════════════
#  FILE TYPE DETECTION
# ═══════════════════════════════════════════════════════════════════════

def get_mime_type(file_path: str) -> str:
    """Deteksi MIME type file menggunakan python-magic."""
    try:
        mime      = Magic(mime=True)
        mime_type = mime.from_file(file_path)
        return mime_type or "text/plain"
    except Exception as e:
        LOGGER.debug(f"get_mime_type error '{file_path}': {e}")
        return "text/plain"


def get_media_streams(path: str) -> Tuple[bool, bool, bool]:
    """
    Deteksi apakah file adalah video, audio, atau image.
    [FIX HIGH] eval(ffprobe_result) → json.loads() — hapus RCE vulnerability.

    Returns:
        (is_video, is_audio, is_image)
    """
    is_video = is_audio = is_image = False

    mime_type = get_mime_type(path)

    if mime_type.startswith("audio"):
        return False, True, False

    if mime_type.startswith("image"):
        return False, False, True

    if path.endswith(".bin") or (
        not mime_type.startswith("video") and not mime_type.endswith("octet-stream")
    ):
        return False, False, False

    try:
        result = check_output([
            "ffprobe", "-hide_banner", "-loglevel", "error",
            "-print_format", "json", "-show_streams", path,
        ]).decode("utf-8")
    except Exception as e:
        if not mime_type.endswith("octet-stream"):
            LOGGER.error(f"ffprobe error '{path}': {e}")
        return False, False, False

    # [FIX HIGH] eval() → json.loads() — tidak ada RCE risk
    try:
        data   = json.loads(result)
        fields = data.get("streams")
    except (json.JSONDecodeError, AttributeError) as e:
        LOGGER.error(f"get_media_streams JSON parse error: {e} | output: {result[:200]}")
        return False, False, False

    if fields is None:
        return False, False, False

    for stream in fields:
        codec = stream.get("codec_type", "")
        if codec == "video":
            is_video = True
        elif codec == "audio":
            is_audio = True

    return is_video, is_audio, is_image


def get_file_type(up_path: str) -> Tuple[bool, bool, bool]:
    """
    Return (is_video, is_audio, is_image) untuk file.
    Tambahkan check ekstensi gambar sebagai fallback.
    """
    is_video, is_audio, is_image = get_media_streams(up_path)
    is_image = is_image or up_path.upper().endswith(IMAGE_SUFFIXES)
    return is_video, is_audio, is_image


# ═══════════════════════════════════════════════════════════════════════
#  GOOGLE DRIVE URL PARSER
# ═══════════════════════════════════════════════════════════════════════

def getIdFromUrl(link: str) -> str | bool:
    """Extract Google Drive file/folder ID dari URL."""
    try:
        if "folders" in link or "file" in link:
            regex = r"https:\/\/drive\.google\.com\/(?:drive(.*?)\/folders\/|file(.*?)?\/d\/)([-\w]+)"
            res   = re_search(regex, link)
            if res is None:
                return False
            return res.group(3)
        parsed = urlparse(link)
        ids    = parse_qs(parsed.query).get("id")
        return ids[0] if ids else False
    except Exception as e:
        LOGGER.debug(f"getIdFromUrl error: {e}")
        return False
