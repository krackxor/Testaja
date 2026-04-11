"""
╔══════════════════════════════════════════════════════════════════════╗
║            bot_helper/Process/Process_Status.py                      ║
║            Encoder1 Bot — v4.1 (UI/UX Refined Edition)               ║
╠══════════════════════════════════════════════════════════════════════╣
║  CHANGELOG v4.1:                                                     ║
║  [UX] Desain pelaporan progress dirombak total agar sangat rapi di   ║
║       layar HP (menggunakan hierarki visual, pemisah, & monospace).  ║
║  [NEW] Dukungan metadata resolusi untuk Fast Encode Tracker.         ║
║  [IMPROVE] Penanganan error Aiofiles yang lebih kuat (Anti-Crash).   ║
╚══════════════════════════════════════════════════════════════════════╝
"""

# ── Standard Library ──────────────────────────────────────────────────
from asyncio import sleep as asynciosleep, wait_for, create_subprocess_exec
from asyncio.subprocess import PIPE as asyncioPIPE
from json import loads
from math import floor
from os import makedirs, remove, rename
from os.path import exists, getsize, isdir
from re import findall as refindall
from shutil import move as shutil_move
from time import time

# ── Third Party ───────────────────────────────────────────────────────
from aiofiles import open as aio_open

# ── Internal ──────────────────────────────────────────────────────────
from bot_helper.Database.User_Data import get_data
from bot_helper.Others.Helper_Functions import (
    gen_random_string, get_account_type, get_human_size,
    get_readable_time, get_value,
)
from bot_helper.Others.Names import Names
from bot_helper.Process.Running_Process import check_running_process
from config.config import Config

LOGGER                  = Config.LOGGER
FINISHED_PROGRESS_STR   = Config.FINISHED_PROGRESS_STR
UNFINISHED_PROGRESS_STR = Config.UNFINISHED_PROGRESS_STR
CMD_SUFFIX              = Config.CMD_SUFFIX
download_dir            = Config.DOWNLOAD_DIR

# Konstanta UI
DIVIDER = "━━━━━━━━━━━━━━━━━━━━"

# Peta nama posisi watermark
ws_name = {
    "5:5":                                  "Kiri Atas",
    "main_w-overlay_w-5:5":                 "Kanan Atas",
    "5:main_h-overlay_h":                   "Kiri Bawah",
    "main_w-overlay_w-5:main_h-overlay_h-5": "Kanan Bawah",
}

# Throttle cancel check — cek setiap N iterasi bukan setiap 0.5 detik
_CANCEL_CHECK_EVERY = 10


# ═══════════════════════════════════════════════════════════════════════
#  HELPER FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════

def create_direc(direc: str) -> None:
    if not isdir(direc):
        makedirs(direc, exist_ok=True)


def get_progress_bar_from_percentage(percentage: str) -> str:
    """Progress bar dari string persentase seperti '45.3%'."""
    try:
        p = int(float(percentage.strip().strip("%")))
    except (ValueError, TypeError, AttributeError):
        p = 0
    p     = min(max(p, 0), 100)
    cFull = p // 8
    p_str = FINISHED_PROGRESS_STR * cFull + UNFINISHED_PROGRESS_STR * (12 - cFull)
    return f"[{p_str}]"


def get_progress_bar_string(current: float, total: float) -> str:
    """Progress bar dari nilai current/total."""
    if total <= 0:
        total = 1
    p     = min(max(round(current * 100 / total), 0), 100)
    cFull = p // 8
    p_str = FINISHED_PROGRESS_STR * cFull + UNFINISHED_PROGRESS_STR * (12 - cFull)
    return f"[{p_str}]"


def ffmpeg_status_foot(status, user_id: int, start_time: float, time_in_us: float) -> str:
    """Generate footer status FFmpeg."""
    user_data   = get_data().get(user_id, {})
    status_foot = ""

    if user_data.get("ffmpeg_ptime", True):
        status_foot += f"\n⏱ <b>W. Proses:</b> <code>{get_readable_time(time() - start_time)}</code>"

    if user_data.get("ffmpeg_size", True):
        sep = " | " if status_foot else "\n"
        try:
            est_size = get_human_size(
                (status.output_size() / max(time_in_us, 1)) * status.duration * 1024 * 1024
            )
            status_foot += f"{sep}💽 <b>Est. Ukuran:</b> <code>{est_size}</code>"
        except (ZeroDivisionError, TypeError):
            status_foot += f"{sep}💽 <b>Est. Ukuran:</b> <code>N/A</code>"

    return status_foot


def generate_ffmpeg_status_head(user_id: int, pmode: str, input_size: int) -> str:
    """Generate header status FFmpeg sesuai mode proses."""
    user_data          = get_data().get(user_id, {})
    video_settings     = user_data.get("video", {})
    watermark_settings = user_data.get("watermark", {})
    merge_settings     = user_data.get("merge", {})
    mux_settings       = user_data.get("mux", {})

    if pmode in [Names.compress, Names.convert, Names.hardmux, Names.watermark, Names.encode]:
        qsize_text = (
            f"<code>{video_settings.get('queue_size', '-')}</code>"
            if video_settings.get("use_queue_size")
            else "<code>Normal</code>"
        )
        res_val = video_settings.get('resolution', 'Auto')
        text = (
            f"<b>⚙️ Konfigurasi Engine:</b>\n"
            f"├ <b>Res:</b> <code>{res_val}</code> | <b>Preset:</b> <code>{video_settings.get('preset')}</code>\n"
            f"├ <b>CRF:</b> <code>{video_settings.get('crf')}</code> | <b>Sub:</b> <code>{video_settings.get('copy_sub')}</code>\n"
            f"├ <b>Buf:</b> {qsize_text} | <b>Peta:</b> <code>{video_settings.get('map')}</code>\n"
            f"└ <b>Enc:</b> <code>{video_settings.get('encoder')}</code> | <b>IN:</b> <code>{get_human_size(input_size)}</code>"
        )
        if pmode == Names.watermark:
            text += (
                f"\n├ <b>WM Skala:</b> <code>{watermark_settings.get('size', '-')}</code>%\n"
                f"└ <b>WM Posisi:</b> <code>{ws_name.get(watermark_settings.get('position', ''), 'N/A')}</code>"
            )
        return text

    elif pmode == Names.merge:
        return f"<b>⚙️ Info Gabung:</b> Peta <code>{merge_settings.get('map')}</code> | Fix Blank <code>{merge_settings.get('fix_blank')}</code>"

    elif pmode in [Names.softmux, Names.softremux]:
        return f"<b>⚙️ Info Mux:</b> Codec <code>{mux_settings.get('sub_codec')}</code> | IN <code>{get_human_size(input_size)}</code>"

    return ""


# ═══════════════════════════════════════════════════════════════════════
#  RCLONE UTILITIES
# ═══════════════════════════════════════════════════════════════════════

async def get_ffmpeg_process_line(proc) -> bytes | bool:
    data = False
    try:
        data = await wait_for(proc.stderr.readline(), 5)
    except Exception:
        pass
    return data


async def get_rclone_process_line(proc) -> bytes | bool:
    data = False
    try:
        data = await wait_for(proc.stdout.readline(), 5)
    except Exception as e:
        LOGGER.warning(f"⚠️  Error baca log rclone: {e}")
    return data


async def getdrivelink(search_command: list, event) -> str | bool:
    process = await create_subprocess_exec(*search_command, stdout=asyncioPIPE)
    stdout, _ = await process.communicate()
    try:
        decoded = stdout.decode().strip()
        data    = loads(decoded)
        file_id = data[0]["ID"]
        return file_id
    except Exception as e:
        await event.reply(f"❌ Error saat mendapatkan ID berkas: `{e}`")
        LOGGER.error(f"❌ getdrivelink error: {e}", exc_info=True)
        return False


async def check_file_drive_link(
    search_command: list, event, fileloc: str,
    r_config: str, drive_name: str, name: str, caption: str,
) -> None:
    file_link = await rclone_get_link(drive_name, name, r_config)

    try:
        fisize = get_human_size(getsize(fileloc))
    except (OSError, FileNotFoundError):
        fisize = "Unknown"

    if file_link:
        file_text = (
            f"✅ <b>Upload Selesai!</b>\n"
            f"📁 <b>File:</b> <code>{name}</code>\n"
            f"☁️ <b>Drive:</b> <code>{drive_name}</code>\n"
            f"💽 <b>Ukuran:</b> <code>{fisize}</code>\n\n"
            f"🔗 <b>Tautan Unduh:</b>\n{file_link}"
        )
    else:
        file_text = (
            f"✅ <b>Upload Selesai!</b>\n"
            f"📁 <b>File:</b> <code>{name}</code>\n"
            f"☁️ <b>Drive:</b> <code>{drive_name}</code>\n"
            f"💽 <b>Ukuran:</b> <code>{fisize}</code>\n\n"
            f"❗ <i>Gagal mengekstrak tautan otomatis.</i>"
        )

    if caption:
        file_text += f"\n\n{str(caption).strip()}"

    await event.reply(file_text, parse_mode="HTML")


async def rclone_get_link(remote: str, name: str, conf: str) -> str | bool:
    cmd = ["rclone", "link", f"--config={conf}", f"{remote}:{name}"]
    process = await create_subprocess_exec(*cmd, stdout=asyncioPIPE, stderr=asyncioPIPE)
    out, _  = await process.communicate()
    url     = out.decode().strip()
    if process.returncode == 0:
        return url
    return False


# ═══════════════════════════════════════════════════════════════════════
#  PROCESS STATUS CLASS
# ═══════════════════════════════════════════════════════════════════════

class ProcessStatus:
    """Tracking state untuk satu proses bot."""

    def __init__(
        self, user_id: int, chat_id: int, user_name: str, user_first_name: str,
        event, process_type: str, file_name=False, thumbnail=False,
        start_time=False, custom_metadata=False, custom_index=False,
        input_mode: str = "Telegram",
    ):
        self.user_id        = user_id
        self.chat_id        = chat_id
        self.amap_options   = "0:a"
        self.user_name      = user_name
        self.user_first_name = user_first_name
        self.event          = event
        self.garbage_messages = []
        self.dir            = f"{download_dir}/{user_id}/{gen_random_string(5)}"
        self.send_files     = []
        self.dw_files       = []
        self.subtitles      = []
        self.dw_index       = "-/-"
        self.file_name      = file_name
        self.status_message_id = gen_random_string(5)
        self.process_id     = gen_random_string(10)
        self.status_message = f"🔁 <b>Menginisialisasi...</b>\n<i>Tunggu sebentar...</i>"
        self.message        = "Tidak Ditemukan"
        self.caption        = False
        self.process_type   = process_type
        self.start_time     = start_time
        self.convert_quality = 480
        self.convert_index  = "-/-"
        self.ping           = time()
        self.trash_objects  = False
        self.multi_tasks    = []
        self.multi_task_no  = 0
        self.custom_metadata = custom_metadata
        self.custom_index   = custom_index
        self.input_mode     = input_mode

        # Fitur-fitur proses bawaan
        self.trim_start    = None
        self.trim_end      = None
        self.split_mode    = None
        self.split_value   = None
        self.cut_ranges    = []
        self.rotate_option = None
        self.new_extension = None
        self.file_type     = "video"
        self.crop_params   = None
        self.extract_maps  = []

        self.custom_watermark  = {}
        self.custom_dub_audio  = None
        self.video_filters     = None
        self.audio_filters     = None
        self.custom_ffmpeg_cmd = [] 
        self.extra_inputs      = [] 

        if not thumbnail and exists(f"./userdata/{user_id}_Thumbnail.jpg"):
            self.thumbnail = f"./userdata/{user_id}_Thumbnail.jpg"
        else:
            self.thumbnail = thumbnail

        if self.user_name:
            self.added_by = f"<a href='https://t.me/{self.user_name}'>{self.user_first_name}</a>"
        else:
            self.added_by = f"<b>{self.user_first_name}</b>"

    # ── Multi-task Methods ───────────────────────────────────────────
    def append_multi_tasks(self, task) -> None: self.multi_tasks.append(task)
    def change_multi_tasks_no(self, no: int) -> None: self.multi_task_no = no
    def get_multi_task_no(self) -> str:
        if self.multi_task_no:
            done = self.multi_task_no - len(self.multi_tasks)
            return f"({done}/{self.multi_task_no})"
        return ""
    def replace_multi_tasks(self, multi_tasks: list) -> None: self.multi_tasks = multi_tasks

    # ── Status Message Methods ───────────────────────────────────────
    def update_status_message(self, message: str) -> None: self.message = message
    def update_convert_quality(self, convert_quality) -> None: self.convert_quality = convert_quality
    def update_convert_index(self, convert_index: str) -> None: self.convert_index = convert_index
    def update_process_message(self, text: str) -> None: self.status_message = text
    def update_start_time(self, start_time: float) -> None: self.start_time = start_time

    # ── File Methods ─────────────────────────────────────────────────
    def set_custom_thumbnail(self, thumbnail: str) -> None: self.thumbnail = thumbnail

    def move_custom_thumbnail(self, thumbnail: str | None) -> None:
        if not thumbnail: return
        if exists(thumbnail):
            name     = thumbnail.split("/")[-1]
            move_dir = f"{self.dir}/thumbnail"
            if exists(f"{move_dir}/{name}"):
                move_dir = f"{self.dir}/{gen_random_string(5)}"
            create_direc(move_dir)
            shutil_move(thumbnail, f"{move_dir}/{name}")
            self.thumbnail = f"{move_dir}/{name}"
        else:
            self.thumbnail = "./thumb.jpg" if exists("./thumb.jpg") else None

    def set_send_files(self, name: str) -> None: self.send_files = [f"{self.dir}/{name}"]
    def replace_send_files(self, file_name: str) -> None: self.send_files = [file_name]
    def replace_send_list(self, send_files: list) -> None: self.send_files = send_files
    def append_send_files(self, name: str) -> None:
        path = f"{self.dir}/{name}"
        if path not in self.send_files: self.send_files.append(path)
    def append_send_files_loc(self, fileloc: str) -> None:
        if fileloc not in self.send_files: self.send_files.append(fileloc)
    def append_dw_files_loc(self, fileloc: str) -> None:
        if fileloc not in self.dw_files: self.dw_files.append(fileloc)
    def append_dw_files(self, name: str) -> None:
        path = f"{self.dir}/{name}"
        if path not in self.dw_files: self.dw_files.append(path)
    def set_file_name(self, file_name: str) -> None:
        if not self.file_name: self.file_name = file_name
    def set_file_name_from_send_list(self) -> None:
        if not self.file_name:
            try:
                if self.send_files: self.file_name = self.send_files[-1].split("/")[-1]
            except Exception: pass

    def set_caption(self, caption: str) -> None: self.caption = caption
    def set_amap_options(self, options: str) -> None: self.amap_options = options
    def set_dw_index(self, dw_index: str) -> None: self.dw_index = dw_index

    def move_dw_file(self, name: str) -> None:
        src = f"{self.dir}/{name}"
        if not exists(src) or src not in self.dw_files: return
        self.dw_files.remove(src)
        move_dir = f"{self.dir}/work_files"
        create_direc(move_dir)
        dest = f"{move_dir}/{name}"
        if exists(dest): rename(dest, f"{move_dir}/{gen_random_string(5)}_{name}")
        shutil_move(src, dest)
        self.send_files.append(dest)

    def move_send_files(self, send_files: list) -> None:
        for file in send_files:
            if not exists(file): continue
            name     = file.split("/")[-1]
            move_dir = f"{self.dir}/work_files"
            if exists(f"{move_dir}/{name}"): move_dir = f"{self.dir}/{gen_random_string(5)}"
            create_direc(move_dir)
            shutil_move(file, f"{move_dir}/{name}")
            self.send_files.append(f"{move_dir}/{name}")

    def append_subtitles(self, sub_loc: str) -> None:
        if not exists(sub_loc): return
        if sub_loc not in self.subtitles: self.subtitles.append(sub_loc)

    def get_task_details(self) -> str:
        return f"👤 <b>Aktor:</b> {self.added_by} | <b>ID:</b> <code>{self.user_id}</code>"

    # ── Status Update Methods ────────────────────────────────────────

    async def update_status(self, status) -> None:
        if status.type() == Names.ffmpeg:
            input_size  = status.input_size()
            ffmpeg_head = generate_ffmpeg_status_head(self.user_id, self.process_type, input_size)

        total_files   = len(self.send_files)
        error_no      = 0
        multi_task_no = self.get_multi_task_no()
        iter_count    = 0 

        while True:
            self.ping = time()
            iter_count += 1

            # ── ARIA STATUS ──────────────────────────────────────────
            if status.type() == Names.aria:
                if status.process_status == 0:
                    text = (
                        f"<b>{status.status()}</b> <code>[{self.dw_index}]</code>\n"
                        f"📁 <code>{status.name()}</code>\n"
                        f"{get_progress_bar_from_percentage(status.progress())} <b>{status.progress()}</b>\n"
                        f"{DIVIDER}\n"
                        f"{self.get_task_details()}\n"
                        f"🚀 <b>Engine:</b> <code>Aria2c</code>\n"
                        f"📦 <b>Size:</b> <code>{get_human_size(int(status.processed_bytes()))} / {get_human_size(int(status.size_raw()))}</code>\n"
                        f"⚡ <b>Speed:</b> <code>{status.speed()}</code> | ⏱ <b>ETA:</b> <code>{status.eta()}</code>\n"
                        f"{DIVIDER}\n"
                        f"<i>Berhenti? /cancel{CMD_SUFFIX} aria {status.gid()}</i>"
                    )
                    self.status_message = text
                    await asynciosleep(0.5)
                else:
                    break

            # ── FFMPEG STATUS ────────────────────────────────────────
            elif status.type() == Names.ffmpeg:
                if iter_count % _CANCEL_CHECK_EVERY == 0:
                    if not check_running_process(self.process_id):
                        await self.event.reply("🔒 <b>Tugas dibatalkan oleh pengguna.</b>", parse_mode="HTML")
                        break

                if status.returncode is not None: break

                if exists(status.log_file):
                    try:
                        async with aio_open(status.log_file, "r", encoding="utf-8", errors="replace") as f:
                            ffmpeg_text = await f.read()
                        time_in_us = get_value(refindall(r"out_time_ms=(.+)", ffmpeg_text), int, 1)
                        progress   = get_value(refindall(r"progress=(\w+)", ffmpeg_text), str, "error")
                        speed      = get_value(refindall(r"speed=(\d+\.?\d*)", ffmpeg_text), float, 1)
                    except (OSError, IOError) as e:
                        time_in_us, progress, speed = 1, "error", 1.0
                else:
                    time_in_us, progress, speed = 1, "error", 1.0

                if progress == "end": break

                if progress == "error":
                    if error_no == 30:
                        await self.event.reply("❗ Terjadi beberapa error pada proses FFmpeg.")
                    if error_no == 100: break
                    error_no += 1

                elapsed_time = time_in_us / 1_000_000

                if self.process_type == Names.convert:
                    process_state = f"{Names.STATUS[self.process_type]} Ke {self.convert_quality}P [{self.convert_index}]"
                    name          = status.name
                elif self.process_type != Names.merge:
                    process_state = Names.STATUS.get(self.process_type, self.process_type)
                    name          = status.name
                else:
                    process_state = f"{Names.STATUS[self.process_type]} [{total_files} Berkas]"
                    name          = str(self.file_name)

                user_data        = get_data().get(self.user_id, {})
                show_detailed    = user_data.get("detailed_messages", True)

                duration         = max(status.duration, 0.001)
                progress_percent = f"{elapsed_time * 100 / duration:.1f}%"
                progress_bar     = get_progress_bar_string(elapsed_time, duration)
                eta_str          = (
                    get_readable_time(floor((duration - elapsed_time) / speed))
                    if speed > 0 else "N/A"
                )

                text = (
                    f"<b>{process_state}</b> <code>{multi_task_no}</code>\n"
                    f"📁 <code>{name}</code>\n"
                    f"{progress_bar} <b>{progress_percent}</b>\n"
                    f"{DIVIDER}\n"
                    f"{self.get_task_details()}\n"
                    f"🚀 <b>Engine:</b> <code>FFmpeg Core</code>\n"
                    f"{ffmpeg_head if show_detailed else ''}\n"
                    f"{DIVIDER}\n"
                    f"⏳ <b>Progress:</b> <code>{get_readable_time(elapsed_time)} / {get_readable_time(duration)}</code>\n"
                    f"⚡ <b>Speed:</b> <code>{speed}x</code> | ⏱ <b>ETA:</b> <code>{eta_str}</code>"
                    f"{ffmpeg_status_foot(status, self.user_id, self.start_time, time_in_us)}\n"
                    f"{DIVIDER}\n"
                    f"<i>Cek Log: /ffmpeg{CMD_SUFFIX} log {self.process_id}</i>\n"
                    f"<i>Berhenti? /cancel{CMD_SUFFIX} process {self.process_id}</i>"
                )
                self.status_message = text
                await asynciosleep(0.5)

        if status.type() == Names.aria and status.name():
            path = f"{self.dir}/{status.name()}"
            if path not in self.dw_files:
                self.dw_files.append(path)

    def telegram_update_status(
        self, current: int, total: int, mode: str, name: str,
        start_time: float, status: str, engine: str, client=False,
    ) -> None:
        self.ping = time()

        if client:
            if not check_running_process(self.process_id):
                client.stop_transmission()

        elapsed = max(1, round(time() - start_time))
        speed   = current / elapsed

        if speed > 0 and total > current:
            eta = get_readable_time((total - current) / speed)
        else:
            eta = "N/A"

        pct  = f"{current * 100 / max(total, 1):.1f}%"
        text = (
            f"<b>{status}</b>\n"
            f"📁 <code>{name}</code>\n"
            f"{get_progress_bar_string(current, total)} <b>{pct}</b>\n"
            f"{DIVIDER}\n"
            f"{self.get_task_details()}\n"
            f"🚀 <b>Engine:</b> <code>{engine}</code>\n"
            f"📦 <b>{mode}:</b> <code>{get_human_size(current)} / {get_human_size(total)}</code>\n"
            f"⚡ <b>Speed:</b> <code>{get_human_size(int(speed))}ps</code> | ⏱ <b>ETA:</b> <code>{eta}</code>\n"
            f"{DIVIDER}\n"
            f"<i>Berhenti? /cancel{CMD_SUFFIX} process {self.process_id}</i>"
        )
        self.status_message = text

    async def rclone__update_status(
        self, rclone_process, name: str, search_command: list, fileloc: str,
        r_config: str, drive_name: str, status: str,
    ) -> bool:
        cancelled = False
        log_path  = f"{self.dir}/upload_log_{name}.txt"

        try:
            async with aio_open(log_path, "a+", encoding="utf-8") as log_f:
                try:
                    async for raw_line in rclone_process.stdout:
                        if not check_running_process(self.process_id):
                            cancelled = True
                            break

                        line = raw_line.decode("utf-8", errors="replace").strip()
                        await log_f.write(f"{line}\n")

                        try:
                            datam = refindall(r"Transferred:.*ETA.*", line)
                            if datam:
                                progress   = datam[0].replace("Transferred:", "").strip().split(",")
                                percentage = progress[1].strip("% ")
                                dwdata     = progress[0].strip().split("/")
                                eta        = progress[3].strip().replace("ETA", "").strip()
                                text = (
                                    f"<b>{status}</b>\n"
                                    f"📁 <code>{name}</code>\n"
                                    f"{get_progress_bar_from_percentage(percentage)} <b>{percentage}%</b>\n"
                                    f"{DIVIDER}\n"
                                    f"{self.get_task_details()}\n"
                                    f"🚀 <b>Engine:</b> <code>{Names.rclone}</code>\n"
                                    f"📦 <b>Diunggah:</b> <code>{dwdata[0].strip()} / {dwdata[1].strip()}</code>\n"
                                    f"⚡ <b>Speed:</b> <code>{progress[2]}</code> | ⏱ <b>ETA:</b> <code>{eta}</code>\n"
                                    f"{DIVIDER}\n"
                                    f"<i>Berhenti? /cancel{CMD_SUFFIX} process {self.process_id}</i>"
                                )
                                self.status_message = text
                                await asynciosleep(0.5)
                        except (IndexError, Exception):
                            pass

                except ValueError:
                    pass

        except (OSError, PermissionError) as e:
            LOGGER.error(f"❌ Gagal buka/tulis rclone log {log_path}: {e}")

        if not cancelled:
            await rclone_process.wait()
            if rclone_process.returncode == 0:
                await check_file_drive_link(
                    search_command, self.event, fileloc,
                    r_config, drive_name, name, self.caption,
                )
            else:
                if exists(log_path):
                    await self.event.client.send_file(
                        self.chat_id, file=log_path, allow_cache=False,
                        reply_to=self.event.message, caption=f"❌ Error saat mengunggah {name} ke Drive",
                    )
                else:
                    await self.event.reply("❗ Berkas log rclone tidak ditemukan")
        else:
            try: rclone_process.kill()
            except Exception: pass
            if exists(log_path): remove(log_path)
            return False

        if exists(log_path): remove(log_path)
        return True
