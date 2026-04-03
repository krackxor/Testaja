"""
╔══════════════════════════════════════════════════════════════════════╗
║                    config/config.py                                  ║
║                    Encoder1 Bot — v3.1                               ║
╠══════════════════════════════════════════════════════════════════════╣
║  CHANGELOG dari versi lama:                                          ║
║  [SECURITY] Hapus semua eval() — ganti json.loads() & bool parse     ║
║  [SECURITY] Ganti os.system(wget) → requests.get() (no inject risk)  ║
║  [FIX]      Semua int() sekarang punya default value & try/except    ║
║  [FIX]      SUDO_USERS parsing tidak crash jika kosong               ║
║  [FIX]      MongoDB connection pakai timeout                         ║
║  [FIX]      get_mongo_data() return dict, bukan string               ║
║  [FIX]      aria.sh error tidak langsung crash bot                   ║
║  [FIX]      rmtree pakai ignore_errors=True                          ║
║  [IMPROVE]  Log file lebih hemat disk (10MB x5 bukan 50MB x10)       ║
║  [IMPROVE]  Semua env var punya default value yang masuk akal        ║
╚══════════════════════════════════════════════════════════════════════╝
"""

# ── Standard Library ──────────────────────────────────────────────────
import json
from os import environ, getcwd, makedirs
from os.path import exists
from shutil import rmtree
from subprocess import run as subprocess_run, TimeoutExpired, PIPE
from sys import exit
from logging import StreamHandler, getLogger, basicConfig, ERROR, INFO
from logging.handlers import RotatingFileHandler

# ── Third Party ───────────────────────────────────────────────────────
import requests
from pymongo import MongoClient
from pymongo.errors import ServerSelectionTimeoutError, ConnectionFailure
from dotenv import load_dotenv, dotenv_values


# ═══════════════════════════════════════════════════════════════════════
#  LOGGING SETUP
#  [FIX] maxBytes 50MB→10MB, backupCount 10→5 (hemat disk VPS)
# ═══════════════════════════════════════════════════════════════════════

basicConfig(
    level=INFO,
    format="%(asctime)s - %(levelname)s - %(message)s [%(filename)s:%(lineno)d]",
    datefmt="%d-%b-%y %H:%M:%S",
    handlers=[
        RotatingFileHandler(
            "Logging.txt",
            maxBytes=10_000_000,   # 10MB per file (was: 50MB)
            backupCount=5,         # 5 file backup (was: 10) = max 50MB total
            encoding="utf-8",
        ),
        StreamHandler(),
    ],
)

# Suppress verbose logs dari library third-party
getLogger("telethon").setLevel(ERROR)
getLogger("pyrogram").setLevel(ERROR)
getLogger("motor").setLevel(ERROR)
getLogger("pymongo").setLevel(ERROR)

LOGGER = getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
#  ARIA2 STARTUP
#  [FIX] Tambah timeout + error handling — bot tidak crash jika aria gagal
#  [FIX] Aria error sekarang hanya WARNING, bukan exit()
# ═══════════════════════════════════════════════════════════════════════

def _start_aria2() -> bool:
    """
    Jalankan aria.sh untuk start Aria2 daemon.
    Return True jika berhasil, False jika gagal (bot tetap jalan).
    """
    if not exists("aria.sh"):
        LOGGER.warning("⚠️  aria.sh tidak ditemukan — Aria2 tidak akan berjalan")
        return False
    try:
        subprocess_run(["chmod", "+x", "aria.sh"], check=True, timeout=10)
        result = subprocess_run(
            "./aria.sh",
            shell=True,
            timeout=30,
            stdout=PIPE,
            stderr=PIPE,
        )
        if result.returncode == 0:
            LOGGER.info("✅ Aria2 berhasil dijalankan")
            return True
        else:
            LOGGER.warning(
                f"⚠️  Aria2 gagal start (code {result.returncode}): "
                f"{result.stderr.decode(errors='ignore')[:200]}"
            )
            return False
    except TimeoutExpired:
        LOGGER.warning("⚠️  aria.sh timeout — Aria2 mungkin tidak berjalan")
        return False
    except Exception as e:
        LOGGER.warning(f"⚠️  Aria2 error: {e}")
        return False

_start_aria2()


# ═══════════════════════════════════════════════════════════════════════
#  CONFIG FILE IMPORT
#  [SECURITY] Ganti os.system(wget) → requests.get()
#             os.system() rentan command injection jika URL dimanipulasi
#  [FIX]      Tambah SSL verify + timeout
# ═══════════════════════════════════════════════════════════════════════

def _download_config(url: str, dest: str = "config.env") -> bool:
    """
    Download config file dari URL menggunakan requests (bukan os.system + wget).
    Lebih aman: tidak ada command injection risk, ada SSL verification.
    """
    try:
        LOGGER.info(f"🔶 Downloading config dari: {url}")
        response = requests.get(
            url,
            timeout=30,
            verify=True,        # Verifikasi SSL certificate
            allow_redirects=True,
        )
        response.raise_for_status()
        with open(dest, "wb") as f:
            f.write(response.content)
        LOGGER.info(f"✅ Config berhasil didownload ke {dest}")
        return True
    except requests.exceptions.SSLError:
        LOGGER.error("❌ SSL certificate error saat download config — tolak koneksi tidak aman")
        return False
    except requests.exceptions.Timeout:
        LOGGER.error("❌ Timeout saat download config")
        return False
    except requests.exceptions.RequestException as e:
        LOGGER.error(f"❌ Gagal download config: {e}")
        return False


def _load_config() -> None:
    """Load config dari file yang sesuai (userdata, download URL, atau local)."""
    if exists("./userdata/botconfig.env"):
        LOGGER.info("🔶 Importing Bot Config File dari userdata/")
        env_dict = dict(dotenv_values("./userdata/botconfig.env"))
        for key, value in env_dict.items():
            environ[key] = str(value)
        return

    # Coba download dari URL jika ada
    config_url = environ.get("CONFIG_FILE_URL", "")
    if config_url and config_url.startswith(("http://", "https://")):
        if _download_config(config_url):
            pass  # lanjut ke load config.env di bawah
        else:
            LOGGER.warning("⚠️  Gagal download config dari URL, coba config.env lokal")

    # Load dari config.env lokal
    if exists("config.env"):
        LOGGER.info("🔶 Importing Config dari config.env")
        load_dotenv("config.env", override=True)
    else:
        LOGGER.info("🔶 Menggunakan environment variables langsung")

_load_config()


# ═══════════════════════════════════════════════════════════════════════
#  MONGODB — GET DATA
#  [SECURITY] Hapus eval() pada data MongoDB → pakai json.loads()
#             eval() pada data DB = remote code execution jika DB dicompromise
#  [FIX]      Tambah connection timeout — tidak hang selamanya
#  [FIX]      Return dict kosong {}, bukan string "{}"
#  [FIX]      Tutup koneksi setelah selesai (resource leak)
# ═══════════════════════════════════════════════════════════════════════

def get_mongo_data(mongodb_uri: str, bot_username: str, doc_id: str, collection: str) -> dict:
    """
    Ambil data dari MongoDB saat startup.
    
    [SECURITY] Tidak lagi menggunakan eval() — pakai json.loads()
    [FIX] Ada timeout agar tidak hang jika MongoDB tidak bisa diakses
    [FIX] Return dict langsung, bukan string
    [FIX] Koneksi ditutup setelah selesai
    
    Returns:
        dict: Data dari database, atau {} jika tidak ditemukan / error
    """
    mongo_client = None
    try:
        LOGGER.info(
            f"🔶 Connecting to MongoDB — DB: {bot_username}, "
            f"Collection: {collection}, ID: {doc_id}"
        )
        mongo_client = MongoClient(
            mongodb_uri,
            serverSelectionTimeoutMS=5_000,   # [FIX] 5 detik timeout (was: infinite)
            connectTimeoutMS=5_000,
            socketTimeoutMS=10_000,
        )
        # Test koneksi sebelum query
        mongo_client.admin.command("ping")

        col = mongo_client[bot_username][collection]
        item = col.find_one({"id": doc_id})

        if item and "data" in item:
            raw_data = item["data"]
            LOGGER.info("✅ Data ditemukan di MongoDB")

            # [SECURITY] json.loads() bukan eval()
            # eval() berbahaya karena bisa execute arbitrary Python code
            if isinstance(raw_data, str):
                try:
                    return json.loads(raw_data)
                except json.JSONDecodeError as e:
                    LOGGER.error(f"❌ Data dari MongoDB bukan JSON valid: {e}")
                    return {}
            elif isinstance(raw_data, dict):
                return raw_data
            else:
                LOGGER.warning(f"⚠️  Format data tidak dikenal: {type(raw_data)}")
                return {}
        else:
            LOGGER.info("🟡 Data tidak ditemukan di MongoDB, pakai default {}")
            return {}

    except ServerSelectionTimeoutError:
        LOGGER.error(
            "❌ Tidak bisa connect ke MongoDB (timeout 5 detik). "
            "Cek MONGODB_URI dan pastikan MongoDB bisa diakses dari VPS."
        )
        return {}
    except ConnectionFailure as e:
        LOGGER.error(f"❌ MongoDB connection failure: {e}")
        return {}
    except Exception as e:
        LOGGER.error(f"❌ MongoDB error tidak terduga: {e}")
        return {}
    finally:
        # [FIX] Selalu tutup koneksi — cegah resource leak
        if mongo_client is not None:
            try:
                mongo_client.close()
            except Exception:
                pass


# ═══════════════════════════════════════════════════════════════════════
#  HELPER — SAFE ENV PARSER
#  Fungsi helper agar tidak ada int('') crash di mana-mana
# ═══════════════════════════════════════════════════════════════════════

def _env_int(key: str, default: int, label: str = "") -> int:
    """
    Baca env var sebagai integer dengan default value.
    Tidak crash jika env var kosong atau bukan angka.
    """
    raw = environ.get(key, "").strip()
    if not raw:
        if label:
            LOGGER.warning(f"⚠️  {label} ({key}) tidak ditemukan, pakai default: {default}")
        return default
    try:
        return int(raw)
    except ValueError:
        LOGGER.error(f"❌ {key}='{raw}' bukan angka valid, pakai default: {default}")
        return default


def _env_bool(key: str, default: bool = False) -> bool:
    """
    [SECURITY] Ganti eval() untuk boolean env var.
    eval('True') works tapi eval(user_input) berbahaya.
    """
    return environ.get(key, str(default)).strip().lower() in ("true", "1", "yes", "on")


def _env_list_int(key: str, default: list | None = None) -> list:
    """
    Parse env var berisi list integer dipisah spasi.
    [FIX] Tidak crash jika kosong atau ada spasi ganda.
    """
    if default is None:
        default = []
    raw = environ.get(key, "").strip()
    if not raw:
        return default
    result = []
    for item in raw.split():   # split() otomatis handle spasi ganda
        item = item.strip()
        if item:
            try:
                result.append(int(item))
            except ValueError:
                LOGGER.warning(f"⚠️  Item '{item}' di {key} bukan integer valid, dilewati")
    return result if result else default


# ═══════════════════════════════════════════════════════════════════════
#  CONFIG CLASS
# ═══════════════════════════════════════════════════════════════════════

class Config:
    VERSION = "3.1"

    # ── Telegram API ───────────────────────────────────────────────────
    # [FIX] Pakai _env_int() agar tidak crash jika kosong
    API_ID: int = _env_int("API_ID", 0, "Telegram API_ID")
    if not API_ID:
        LOGGER.critical("❌ API_ID tidak ditemukan atau 0 — Bot tidak bisa jalan!")
        exit(1)

    API_HASH: str = environ.get("API_HASH", "")
    if not API_HASH:
        LOGGER.critical("❌ API_HASH tidak ditemukan — Bot tidak bisa jalan!")
        exit(1)

    TOKEN: str = environ.get("TOKEN", "")
    if not TOKEN:
        LOGGER.critical("❌ Bot TOKEN tidak ditemukan — Bot tidak bisa jalan!")
        exit(1)

    BOT_USERNAME: str = environ.get("BOT_USERNAME", "MyEncoderBot")

    # ── Session ────────────────────────────────────────────────────────
    USE_SESSION_STRING: bool = _env_bool("USE_SESSION_STRING", False)
    SESSION_STRING: str = environ.get("SESSION_STRING", "")

    # ── Pyrogram (opsional) ────────────────────────────────────────────
    # [FIX] Tidak lagi hardcoded True — baca dari env
    USE_PYROGRAM: bool = _env_bool("USE_PYROGRAM", False)

    # Auth group untuk Pyrogram download/upload di group
    try:
        AUTH_GROUP_ID: int | bool = int(environ.get("AUTH_GROUP_ID", "").strip())
    except ValueError:
        AUTH_GROUP_ID = False
        LOGGER.info("🔶 AUTH_GROUP_ID tidak ditemukan — Pyrogram tidak akan kerja di group")

    # ── Task Limits ────────────────────────────────────────────────────
    # [FIX] Default value 3 jika tidak ada di env
    RUNNING_TASK_LIMIT: int = _env_int("RUNNING_TASK_LIMIT", 3, "Running Task Limit")

    # ── Bot Behavior ───────────────────────────────────────────────────
    # [SECURITY] Ganti eval() → _env_bool()
    AUTO_SET_BOT_CMDS: bool = _env_bool("AUTO_SET_BOT_CMDS", False)

    CMD_SUFFIX: str = environ.get("CMD_SUFFIX", "")

    # Progress bar characters
    FINISHED_PROGRESS_STR: str   = environ.get("FINISHED_PROGRESS_STR", "■")
    UNFINISHED_PROGRESS_STR: str = environ.get("UNFINISHED_PROGRESS_STR", "□")

    TIMEZONE: str = environ.get("TIMEZONE", "Asia/Jakarta")   # [FIX] Default Jakarta, bukan Kolkata

    # ── Heroku (tidak dipakai di VPS — dipertahankan untuk kompatibilitas) ──
    HEROKU_APP_NAME: str | bool = environ.get("HEROKU_APP_NAME") or False
    HEROKU_API_KEY: str | bool  = environ.get("HEROKU_API_KEY") or False

    # ── Bot Identity ───────────────────────────────────────────────────
    NAME: str = "Nik66Bots"

    # ── File System ────────────────────────────────────────────────────
    DOWNLOAD_DIR: str = f"{getcwd()}/downloads"

    # ── User Management ────────────────────────────────────────────────
    # [FIX] OWNER_ID pakai _env_int() dengan default 0, cek sesudahnya
    OWNER_ID: int = _env_int("OWNER_ID", 0, "Owner ID")
    if not OWNER_ID:
        LOGGER.critical("❌ OWNER_ID tidak ditemukan — Bot tidak bisa jalan!")
        exit(1)

    # [FIX] SUDO_USERS tidak crash jika kosong atau ada spasi ganda
    SUDO_USERS: list = _env_list_int("SUDO_USERS", [])
    if not SUDO_USERS:
        LOGGER.info("🔶 SUDO_USERS kosong — hanya OWNER yang punya akses sudo")

    # Daftar chat yang diizinkan (gabungan OWNER + SUDO)
    ALLOWED_CHATS: list = list(set([OWNER_ID] + SUDO_USERS))

    # ── MongoDB / Database ─────────────────────────────────────────────
    # [SECURITY] Ganti eval() → _env_bool()
    SAVE_TO_DATABASE: bool = _env_bool("SAVE_TO_DATABASE", False)

    if SAVE_TO_DATABASE:
        MONGODB_URI: str     = environ.get("MONGODB_URI", "")
        COLLECTION_NAME: str = "USER_DATA"
        SAVE_ID: str         = "Nik66"

        if not MONGODB_URI:
            LOGGER.error("❌ SAVE_TO_DATABASE=True tapi MONGODB_URI kosong!")
            DATA: dict = {}
        else:
            # [SECURITY] Tidak lagi pakai eval() — get_mongo_data() return dict langsung
            DATA: dict = get_mongo_data(
                MONGODB_URI, NAME, SAVE_ID, COLLECTION_NAME
            )
    else:
        LOGGER.info("🔶 MongoDB tidak dipakai (SAVE_TO_DATABASE=False)")
        MONGODB_URI: str = ""
        DATA: dict = {}

    # ── Notification ───────────────────────────────────────────────────
    RESTART_NOTIFY_ID: int | bool
    try:
        _rni = environ.get("RESTART_NOTIFY_ID", "").strip()
        RESTART_NOTIFY_ID = int(_rni) if _rni else False
        if RESTART_NOTIFY_ID:
            LOGGER.info("✅ Restart Notification ID ditemukan")
        else:
            LOGGER.info("🔶 Restart Notification ID tidak ditemukan")
    except ValueError:
        RESTART_NOTIFY_ID = False
        LOGGER.warning("⚠️  RESTART_NOTIFY_ID bukan angka valid")

    LOG_CHANNEL_ID: int | bool
    try:
        _lci = environ.get("LOG_CHANNEL_ID", "").strip()
        LOG_CHANNEL_ID = int(_lci) if _lci else False
        if LOG_CHANNEL_ID:
            LOGGER.info("✅ Log Channel ID ditemukan")
        else:
            LOGGER.info("🔶 Log Channel ID tidak ditemukan")
    except ValueError:
        LOG_CHANNEL_ID = False
        LOGGER.warning("⚠️  LOG_CHANNEL_ID bukan angka valid")

    # ── Third Party API Keys ───────────────────────────────────────────
    TRAKTEER_API_KEY: str = environ.get("TRAKTEER_API_KEY", "")

    # ── Logger reference ───────────────────────────────────────────────
    LOGGER = LOGGER


# ═══════════════════════════════════════════════════════════════════════
#  DOWNLOAD DIRECTORY SETUP
#  [FIX] ignore_errors=True — tidak crash jika ada file sedang dipakai
#  [FIX] Buat ulang folder setelah dihapus
# ═══════════════════════════════════════════════════════════════════════

def _setup_download_dir() -> None:
    """Bersihkan dan buat ulang download directory saat startup."""
    dl_dir = Config.DOWNLOAD_DIR
    if exists(dl_dir):
        LOGGER.info(f"🔶 Membersihkan download directory: {dl_dir}")
        # [FIX] ignore_errors=True — tidak crash jika ada file yang sedang dipakai proses lain
        rmtree(dl_dir, ignore_errors=True)

    # Buat ulang folder (rmtree sudah hapus foldernya)
    try:
        makedirs(dl_dir, exist_ok=True)
        LOGGER.info(f"✅ Download directory siap: {dl_dir}")
    except OSError as e:
        LOGGER.error(f"❌ Gagal membuat download directory: {e}")

_setup_download_dir()


# ═══════════════════════════════════════════════════════════════════════
#  STARTUP VALIDATION SUMMARY
# ═══════════════════════════════════════════════════════════════════════

def _print_startup_info() -> None:
    """Print ringkasan konfigurasi saat startup untuk memudahkan debugging."""
    LOGGER.info("=" * 60)
    LOGGER.info(f"🤖 Bot Version      : {Config.VERSION}")
    LOGGER.info(f"👤 Owner ID         : {Config.OWNER_ID}")
    LOGGER.info(f"👥 Sudo Users       : {Config.SUDO_USERS}")
    LOGGER.info(f"📋 Task Limit       : {Config.RUNNING_TASK_LIMIT}")
    LOGGER.info(f"🗄️  Database         : {'MongoDB' if Config.SAVE_TO_DATABASE else 'Tidak dipakai'}")
    LOGGER.info(f"🌏 Timezone         : {Config.TIMEZONE}")
    LOGGER.info(f"📁 Download Dir     : {Config.DOWNLOAD_DIR}")
    LOGGER.info(f"🔑 Pyrogram         : {'Aktif' if Config.USE_PYROGRAM else 'Nonaktif'}")
    LOGGER.info(f"📺 Log Channel      : {Config.LOG_CHANNEL_ID or 'Tidak ada'}")
    LOGGER.info(f"🔔 Restart Notify   : {Config.RESTART_NOTIFY_ID or 'Tidak ada'}")
    LOGGER.info("=" * 60)

_print_startup_info()
