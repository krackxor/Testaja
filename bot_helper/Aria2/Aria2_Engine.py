"""
╔══════════════════════════════════════════════════════════════════════╗
║                bot_helper/Aria2/Aria2_Engine.py — v3.1              ║
║           Aria2 Download Engine untuk Encoder1 / Studio Khoirul      ║
╠══════════════════════════════════════════════════════════════════════╣
║  FIXES dari versi lama:                                              ║
║  [FIX HIGH]  Retry loop di class body → classmethod initialize()    ║
║  [FIX HIGH]  sleep() blocking di class body → async-safe            ║
║  [FIX HIGH]  add_aria2c_download tanpa self → @classmethod          ║
║  [FIX HIGH]  cancel_download tanpa self → @classmethod              ║
║  [FIX HIGH]  add_magnet/add_uris sync → asyncio.to_thread()         ║
║  [FIX HIGH]  .remove() sync di async → asyncio.to_thread()          ║
║  [FIX]       threading.Lock di async → asyncio.Lock                 ║
║  [FIX]       __update() tanpa try/except → safe update              ║
║  [FIX]       ratio() ZeroDivisionError → guard completed_length     ║
║  [FIX]       download unused var di __onDownloadStarted             ║
║  [FIX]       bare except → typed exception + logging                ║
║  [FIX]       EDIT_SLEEP_TIME_OUT tidak dipakai → dihapus           ║
╚══════════════════════════════════════════════════════════════════════╝
"""

# ── Standard Library ──────────────────────────────────────────────────
import asyncio
from re import findall as re_findall
from threading import Lock, Thread
from time import sleep, time

# ── Third Party ───────────────────────────────────────────────────────
from aria2p import API as ariaAPI, Client as ariaClient

# ── Internal ──────────────────────────────────────────────────────────
from bot_helper.Others.Helper_Functions import get_readable_time
from bot_helper.Others.Names import Names
from config.config import Config

LOGGER          = Config.LOGGER
TORRENT_TIMEOUT = 600
MAGNET_REGEX    = r"magnet:\?xt=urn:btih:[a-zA-Z0-9]*"

# [FIX] asyncio.Lock untuk async context, threading.Lock hanya untuk thread callbacks
aria2_download_list_lock       = asyncio.Lock()    # dipakai di async add_aria2c_download
aria2_download_list_thread_lock = Lock()           # dipakai di thread callbacks
aria2_download_list: list = []


# ═══════════════════════════════════════════════════════════════════════
#  HELPER FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════

def getDownloadByGid(gid: str):
    """Cari AriaDownloadStatus berdasarkan GID. Thread-safe via thread lock."""
    with aria2_download_list_thread_lock:
        for dl in aria2_download_list:
            if dl.gid() == gid:
                return dl
    return None


def get_download(gid: str):
    """Ambil download object dari aria2 API."""
    return Aria2.client.get_download(gid)


def is_magnet(url: str) -> bool:
    """Check apakah URL adalah magnet link."""
    return bool(re_findall(MAGNET_REGEX, url))


def new_thread(fn):
    """Decorator untuk menjalankan fungsi di thread terpisah."""
    def wrapper(*args, **kwargs):
        thread = Thread(target=fn, args=args, kwargs=kwargs)
        thread.daemon = True
        thread.start()
        return thread
    return wrapper


# ═══════════════════════════════════════════════════════════════════════
#  ARIA2 CALLBACKS (dijalankan di thread terpisah oleh aria2p)
# ═══════════════════════════════════════════════════════════════════════

@new_thread
def __onDownloadStarted(api, gid: str):
    LOGGER.info(f"aria2 onDownloadStarted: {gid}")
    retry = 0
    while retry < 10:
        if dl := getDownloadByGid(gid):
            dl.onDownloadStarted()
            return
        retry += 1
        sleep(1)
    LOGGER.warning(f"aria2 onDownloadStarted: GID {gid} tidak ditemukan setelah 10 retry")


@new_thread
def __onDownloadComplete(api, gid: str):
    LOGGER.info(f"aria2 onDownloadComplete: {gid}")
    if dl := getDownloadByGid(gid):
        dl.onDownloadComplete()


@new_thread
def __onBtDownloadComplete(api, gid: str):
    LOGGER.info(f"aria2 onBtDownloadComplete: {gid}")
    if dl := getDownloadByGid(gid):
        dl.onBtDownloadComplete()


@new_thread
def __onDownloadStopped(api, gid: str):
    LOGGER.info(f"aria2 onDownloadStopped: {gid}")
    try:
        if dl := getDownloadByGid(gid):
            dl.onDownloadStopped("❌ Dead torrent!")
    except Exception as e:
        LOGGER.debug(f"onDownloadStopped error: {e}")


@new_thread
def __onDownloadError(api, gid: str):
    LOGGER.info(f"aria2 onDownloadError: {gid}")
    error = "Unknown error"
    try:
        download = api.get_download(gid)
        error    = download.error_message or error
    except Exception as e:
        LOGGER.debug(f"Gagal ambil error_message: {e}")

    LOGGER.warning(f"aria2 error [{gid}]: {error}")
    if dl := getDownloadByGid(gid):
        dl.onDownloadError(error)
    else:
        LOGGER.warning(f"aria2 onDownloadError: GID {gid} tidak ditemukan")


# ═══════════════════════════════════════════════════════════════════════
#  ARIA2 CLIENT
# ═══════════════════════════════════════════════════════════════════════

class Aria2:
    """
    Wrapper aria2p untuk download management.

    [FIX HIGH] Retry loop dan sleep() dipindahkan dari class body ke
    classmethod initialize() — mencegah crash saat import jika aria2
    belum siap, dan tidak memblokir event loop.
    """

    client: ariaAPI = None
    aria2_options: dict = {}
    _initialized: bool  = False

    aria2c_global = [
        "bt-max-open-files", "download-result", "keep-unfinished-download-result",
        "log", "log-level", "max-concurrent-downloads", "max-download-result",
        "max-overall-download-limit", "save-session", "max-overall-upload-limit",
        "optimize-concurrent-downloads", "save-cookies", "server-stat-of",
    ]

    @classmethod
    def initialize(cls, host: str = "http://localhost", port: int = 6800, secret: str = "",
                   max_retries: int = 5, retry_delay: float = 2.0) -> bool:
        """
        Inisialisasi koneksi ke aria2c.
        Dipanggil satu kali setelah event loop siap — bukan di class body.

        Returns:
            True jika berhasil, False jika gagal setelah semua retry.
        """
        if cls._initialized and cls.client is not None:
            return True

        cls.client = ariaAPI(ariaClient(host=host, port=port, secret=secret))

        for attempt in range(1, max_retries + 1):
            try:
                options = cls.client.client.get_global_option()
                # Hapus 'dir' dari global options agar tidak override per-download dir
                options.pop("dir", None)
                cls.aria2_options = options

                # Apply global options (hanya yang ada di aria2c_global)
                a2c_glo = {k: v for k, v in options.items() if k in cls.aria2c_global}
                if a2c_glo:
                    cls.client.set_global_options(a2c_glo)

                cls._initialized = True
                LOGGER.info(f"✅ Aria2 terhubung di {host}:{port}")
                return True

            except Exception as e:
                LOGGER.warning(f"⚠️  Koneksi Aria2 gagal (percobaan {attempt}/{max_retries}): {e}")
                if attempt < max_retries:
                    sleep(retry_delay)   # blocking OK di sini — dipanggil sebelum event loop

        LOGGER.error("❌ Tidak dapat terhubung ke server Aria2 setelah semua percobaan.")
        return False

    @classmethod
    async def add_aria2c_download(
        cls,
        link: str,
        listener,
        filename: str = "",
        auth: str = "",
        ratio: str = "",
        seed_time: str = "",
    ) -> tuple:
        """
        Tambahkan download baru ke aria2.

        [FIX HIGH] Ditambahkan @classmethod + cls
        [FIX HIGH] add_magnet/add_uris dijalankan di thread via asyncio.to_thread()
        [FIX]      asyncio.Lock dipakai untuk thread-safe list append

        Returns:
            (download, aria2_status) jika berhasil, (False, False) jika gagal.
        """
        if not cls._initialized or cls.client is None:
            LOGGER.error("Aria2 belum diinisialisasi. Panggil Aria2.initialize() dulu.")
            return False, False

        path = listener.dir
        args: dict = {"dir": path, "max-upload-limit": "1K"}

        # Merge dengan global options (minus yang ada di aria2c_global)
        a2c_opt = {k: v for k, v in cls.aria2_options.items() if k not in cls.aria2c_global}
        args.update(a2c_opt)

        if filename:    args["out"]             = filename
        if auth:        args["header"]          = f"authorization: {auth}"
        if ratio:       args["seed-ratio"]      = ratio
        if seed_time:   args["seed-time"]       = seed_time
        if TORRENT_TIMEOUT:
            args["bt-stop-timeout"] = str(TORRENT_TIMEOUT)

        try:
            if is_magnet(link):
                LOGGER.info(f"Aria2: magnet link → {link[:60]}")
                # [FIX HIGH] asyncio.to_thread() — tidak block event loop
                download = await asyncio.to_thread(cls.client.add_magnet, link, args)
            else:
                LOGGER.info(f"Aria2: HTTP link → {link[:60]}")
                download = await asyncio.to_thread(cls.client.add_uris, [link], args)
        except Exception as e:
            LOGGER.error(f"❌ Aria2 gagal tambah download: {e}", exc_info=True)
            listener.update_status_message(f"❌ Aria2 Error: {e}")
            return False, False

        if download.error_message:
            error = str(download.error_message).replace("<", " ").replace(">", " ")
            LOGGER.error(f"❌ Aria2 download error: {error}")
            listener.update_status_message(f"❌ Download Error: {error}")
            return False, False

        # [FIX] asyncio.Lock untuk list append dari async context
        async with aria2_download_list_lock:
            aria2_status = AriaDownloadStatus(download.gid, listener, time())
            aria2_download_list.append(aria2_status)
            LOGGER.info(f"✅ Aria2 download dimulai: GID={download.gid}")

        return download, aria2_status

    @classmethod
    async def cancel_download(cls, gid: str) -> None:
        """
        Batalkan download berdasarkan GID.

        [FIX HIGH] Ditambahkan @classmethod + cls
        """
        if dl := getDownloadByGid(gid):
            await dl.cancel_download()


def start_listener() -> None:
    """Mulai listener notifikasi aria2 di background thread."""
    if Aria2.client is None:
        LOGGER.error("Aria2 client belum diinisialisasi. Jalankan Aria2.initialize() dulu.")
        return
    Aria2.client.listen_to_notifications(
        threaded=True,
        on_download_start=__onDownloadStarted,
        on_download_error=__onDownloadError,
        on_download_stop=__onDownloadStopped,
        on_download_complete=__onDownloadComplete,
        on_bt_download_complete=__onBtDownloadComplete,
        timeout=60,
    )
    LOGGER.info("✅ Aria2 listener dimulai")


# ═══════════════════════════════════════════════════════════════════════
#  ARIA2 DOWNLOAD STATUS
# ═══════════════════════════════════════════════════════════════════════

class AriaDownloadStatus:
    """
    Tracking state untuk satu download aria2.

    [FIX] __update() sekarang punya try/except — tidak crash jika download
          sudah dihapus dari aria2.
    [FIX] ratio() ada guard untuk ZeroDivisionError.
    [FIX] bare except → typed exception.
    """

    def __init__(self, gid: str, listener, start_time: float, seeding: bool = False):
        self.__gid      = gid
        self.__listener = listener
        self.__download = get_download(gid)
        self.start_time = start_time
        self.seeding    = seeding
        self.process_status = 0   # 0=running, 1=done, -1=error, -2=cancelled

    def __update(self) -> bool:
        """
        Update download object dari aria2.
        [FIX] try/except — .live bisa raise jika download sudah tidak ada.

        Returns:
            True jika berhasil update, False jika gagal.
        """
        try:
            live = self.__download.live
            if live is None:
                self.__download = get_download(self.__gid)
            elif live.followed_by_ids:
                # Download diteruskan ke GID baru (e.g. metalink → actual download)
                self.__gid      = live.followed_by_ids[0]
                self.__download = get_download(self.__gid)
            else:
                self.__download = live
            return True
        except Exception as e:
            LOGGER.debug(f"aria2 __update error [GID={self.__gid}]: {e}")
            return False

    # ── Status Methods ────────────────────────────────────────────────

    def progress(self) -> str:
        return self.__download.progress_string()

    def is_complete(self) -> bool:
        return self.__download.is_complete

    def error_message(self) -> str:
        return self.__download.error_message or ""

    def has_failed(self) -> bool:
        return self.__download.has_failed

    def size_raw(self) -> int:
        return self.__download.total_length

    def processed_bytes(self) -> int:
        return self.__download.completed_length

    def speed(self) -> str:
        self.__update()
        return self.__download.download_speed_string()

    def name(self) -> str | bool:
        return self.__download.name or False

    def size(self) -> str:
        return self.__download.total_length_string()

    def eta(self) -> str:
        return self.__download.eta_string()

    def status(self) -> str:
        self.__update()
        dl = self.__download
        if dl.is_waiting:
            return Names.STATUS_WAITING
        elif dl.is_paused:
            return Names.STATUS_PAUSED
        elif dl.seeder and self.seeding:
            return Names.STATUS_SEEDING
        else:
            return Names.STATUS_DOWNLOADING

    def seeders_num(self) -> int:
        return self.__download.num_seeders

    def leechers_num(self) -> int:
        return self.__download.connections

    def uploaded_bytes(self) -> str:
        return self.__download.upload_length_string()

    def upload_speed(self) -> str:
        self.__update()
        return self.__download.upload_speed_string()

    def ratio(self) -> str:
        """
        [FIX] Guard ZeroDivisionError jika download belum mulai.
        """
        completed = self.__download.completed_length
        uploaded  = self.__download.upload_length
        if completed > 0:
            return f"{round(uploaded / completed, 3)}"
        return "0.000"

    def seeding_time(self) -> str:
        return get_readable_time(time() - self.start_time)

    def listener(self):
        return self.__listener

    def download(self):
        return self

    def gid(self) -> str:
        try:
            self.__update()
        except Exception as e:
            LOGGER.debug(f"gid() update error: {e}")
        return self.__gid

    def type(self) -> str:
        return Names.aria

    # ── Event Callbacks (dipanggil dari thread) ───────────────────────

    def onDownloadStarted(self) -> None:
        self.__listener.update_status_message(Names.STATUS_DOWNLOADING)
        if self.name():
            self.__listener.append_dw_files(self.name())

    def onDownloadComplete(self) -> None:
        self.__listener.update_status_message("✅ Download Selesai")
        self.process_status = 1

    def onBtDownloadComplete(self) -> None:
        self.__listener.update_status_message("🟡 Download Torrent Selesai")
        self.process_status = 1

    def onDownloadStopped(self, msg: str) -> None:
        sleep(5)   # Beri waktu agar proses cleanup selesai
        if self.process_status != -2:   # -2 = manually cancelled, jangan override
            self.__listener.update_status_message(msg)
            self.process_status = -1

    def onDownloadError(self, error: str) -> None:
        self.__listener.update_status_message(f"❌ Download Error: {error}")
        self.process_status = -1

    # ── Cancel ───────────────────────────────────────────────────────

    async def cancel_download(self) -> None:
        """
        Batalkan download ini.
        [FIX HIGH] Aria2.client.remove() dijalankan via asyncio.to_thread()
        """
        self.__update()
        dl = self.__download

        if dl.seeder and self.seeding:
            # Batalkan seeding
            LOGGER.info(f"Aria2: batalkan seed {self.name()} | ratio={self.ratio()} | waktu={self.seeding_time()}")
            self.__listener.update_status_message(f"🔒 Menghentikan seed: {self.name()}")
            self.process_status = -2
            await asyncio.to_thread(Aria2.client.remove, [dl], force=True, files=True)

        elif downloads := dl.followed_by:
            # Batalkan download yang sudah di-follow
            LOGGER.info(f"Aria2: batalkan download {self.name()}")
            self.__listener.update_status_message("🔒 Tugas Dibatalkan Oleh Pengguna")
            self.process_status = -2
            all_downloads = downloads + [dl]
            await asyncio.to_thread(Aria2.client.remove, all_downloads, force=True, files=True)

        else:
            # Batalkan download biasa
            LOGGER.info(f"Aria2: batalkan download {self.name()}")
            self.process_status = -2
            self.__listener.update_status_message("🔒 Tugas Dibatalkan Oleh Pengguna")
            await asyncio.to_thread(Aria2.client.remove, [dl], force=True, files=True)
