"""
╔══════════════════════════════════════════════════════════════════════╗
║            bot_helper/Process/Process_Status.py                      ║
║            Encoder1 Bot — v4.5 (Pure Markdown Final Edition)         ║
╠══════════════════════════════════════════════════════════════════════╣
║  CHANGELOG v4.5:                                                     ║
║  [FIX CRITICAL] Mengubah seluruh format menjadi Markdown murni       ║
║                 (**tebal**, _miring_, `kode`) agar sesuai dengan     ║
║                 permintaan dan tidak ada tag HTML yang bocor.        ║
║  [UX] Mempertahankan Layout UI Profesional untuk tampilan layar HP.  ║
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

_CANCEL_CHECK_EVERY = 10

# ═══════════════════════════════════════════════════════════════════════
#  HELPER FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════

def create_direc(direc: str) -> None:
    if not isdir(direc):
        makedirs(direc, exist_ok=True)

def get_progress_bar_from_percentage(percentage: str) -> str:
    try:
        p = int(float(percentage.strip().strip("%")))
    except:
        p = 0
    p     = min(max(p, 0), 100)
    cFull = p // 8
    p_str = FINISHED_PROGRESS_STR * cFull + UNFINISHED_PROGRESS_STR * (12 - cFull)
    return f"[{p_str}]"

def get_progress_bar_string(current: float, total: float) -> str:
    if total <= 0: total = 1
    p     = min(max(round(current * 100 / total), 0), 100)
    cFull = p // 8
    p_str = FINISHED_PROGRESS_STR * cFull + UNFINISHED_PROGRESS_STR * (12 - cFull)
    return f"[{p_str}]"

def ffmpeg_status_foot(status, user_id: int, start_time: float, time_in_us: float) -> str:
    user_data   = get_data().get(user_id, {})
    status_foot = ""
    if user_data.get("ffmpeg_ptime", True):
        status_foot += f"\n⏱ **Durasi:** `{get_readable_time(time() - start_time)}`"
    if user_data.get("ffmpeg_size", True):
        sep = " | " if "⏱" in status_foot else "\n"
        try:
            est_size = get_human_size((status.output_size() / max(time_in_us, 1)) * status.duration * 1024 * 1024)
            status_foot += f"{sep}💾 **Est:** `{est_size}`"
        except:
            status_foot += f"{sep}💾 **Est:** `N/A`"
    return status_foot

def generate_ffmpeg_status_head(user_id: int, pmode: str, input_size: int) -> str:
    user_data          = get_data().get(user_id, {})
    video_settings     = user_data.get("video", {})
    
    if pmode in [Names.compress, Names.convert, Names.hardmux, Names.watermark, Names.encode]:
        res_val = video_settings.get('resolution', 'Auto')
        enc_val = video_settings.get('encoder', 'libx264')
        text = (
            f"**⚙️ Konfigurasi Engine:**\n"
            f"`{res_val} | {enc_val} | CRF:{video_settings.get('crf')}`\n"
            f"📥 **Input:** `{get_human_size(input_size)}`"
        )
        return text
    return ""

# ═══════════════════════════════════════════════════════════════════════
#  RCLONE & UTILITIES
# ═══════════════════════════════════════════════════════════════════════

async def get_ffmpeg_process_line(proc) -> bytes | bool:
    data = False
    try: data = await wait_for(proc.stderr.readline(), 5)
    except: pass
    return data

async def get_rclone_process_line(proc) -> bytes | bool:
    data = False
    try: data = await wait_for(proc.stdout.readline(), 5)
    except: pass
    return data

async def getdrivelink(search_command: list, event) -> str | bool:
    process = await create_subprocess_exec(*search_command, stdout=asyncioPIPE)
    stdout, _ = await process.communicate()
    try:
        decoded = stdout.decode().strip()
        data    = loads(decoded)
        return data[0]["ID"]
    except:
        return False

async def check_file_drive_link(
    search_command: list, event, fileloc: str, r_config: str, drive_name: str, name: str, caption: str,
) -> None:
    file_link = await rclone_get_link(drive_name, name, r_config)
    try: fisize = get_human_size(getsize(fileloc))
    except: fisize = "Unknown"

    if file_link:
        file_text = (
            f"✅ **Upload Selesai!**\n"
            f"📁 **File:** `{name}`\n"
            f"☁️ **Drive:** `{drive_name}`\n"
            f"💽 **Ukuran:** `{fisize}`\n\n"
            f"🔗 **Tautan Unduh:**\n{file_link}"
        )
    else:
        file_text = (
            f"✅ **Upload Selesai!**\n"
            f"📁 **File:** `{name}`\n"
            f"☁️ **Drive:** `{drive_name}`\n"
            f"💽 **Ukuran:** `{fisize}`\n\n"
            f"❗ _Gagal mengekstrak tautan otomatis._"
        )

    if caption: file_text += f"\n\n{str(caption).strip()}"
    await event.reply(file_text)

async def rclone_get_link(remote: str, name: str, conf: str) -> str | bool:
    cmd = ["rclone", "link", f"--config={conf}", f"{remote}:{name}"]
    process = await create_subprocess_exec(*cmd, stdout=asyncioPIPE, stderr=asyncioPIPE)
    out, _  = await process.communicate()
    if process.returncode == 0: return out.decode().strip()
    return False

# ═══════════════════════════════════════════════════════════════════════
#  PROCESS STATUS CLASS
# ═══════════════════════════════════════════════════════════════════════

class ProcessStatus:
    def __init__(self, user_id, chat_id, user_name, user_first_name, event, process_type, **kwargs):
        self.user_id = user_id
        self.chat_id = chat_id
        self.user_name = user_name
        self.user_first_name = user_first_name
        self.event = event
        self.process_type = process_type
        self.process_id = gen_random_string(10)
        self.dir = f"{download_dir}/{user_id}/{gen_random_string(5)}"
        self.send_files = []
        self.dw_files = []
        self.status_message = "🔁 **Menginisialisasi...**"
        self.ping = time()
        self.start_time = time()
        
        # [FIX] Konversi link ke Markdown Telethon
        if self.user_name:
            self.added_by = f"[{user_first_name}](https://t.me/{user_name})"
        else:
            self.added_by = f"**{user_first_name}**"

    def get_task_details(self) -> str:
        # [FIX] Menggunakan Markdown murni
        return f"👤 **Aktor:** {self.added_by} | **ID:** `{self.user_id}`\n"

    async def update_status(self, status) -> None:
        ffmpeg_head = ""
        if status.type() == Names.ffmpeg:
            ffmpeg_head = generate_ffmpeg_status_head(self.user_id, self.process_type, status.input_size())

        iter_count = 0 
        while True:
            self.ping = time()
            iter_count += 1

            if status.type() == Names.ffmpeg:
                if iter_count % _CANCEL_CHECK_EVERY == 0 and not check_running_process(self.process_id): break
                if status.returncode is not None: break

                time_in_us, progress, speed = 1, "error", 1.0
                if exists(status.log_file):
                    try:
                        async with aio_open(status.log_file, "r", encoding="utf-8", errors="replace") as f:
                            ffmpeg_text = await f.read()
                        time_in_us = get_value(refindall(r"out_time_ms=(.+)", ffmpeg_text), int, 1)
                        progress = get_value(refindall(r"progress=(\w+)", ffmpeg_text), str, "error")
                        speed = get_value(refindall(r"speed=(\d+\.?\d*)", ffmpeg_text), float, 1)
                    except: pass
                
                if progress == "end": break
                elapsed_time = time_in_us / 1_000_000
                duration = max(status.duration, 0.001)
                pct = f"{elapsed_time * 100 / duration:.1f}%"
                
                # [FIX CRITICAL] Menggunakan format Markdown murni
                text = (
                    f"**{Names.STATUS.get(self.process_type, self.process_type)}**\n"
                    f"📁 `{status.name[:30]}...`\n"
                    f"{get_progress_bar_string(elapsed_time, duration)} **{pct}**\n"
                    f"{DIVIDER}\n"
                    f"{self.get_task_details()}"
                    f"🚀 **Engine:** `FFmpeg Core`\n"
                    f"{ffmpeg_head}\n"
                    f"{DIVIDER}\n"
                    f"⏳ **Progress:** `{get_readable_time(elapsed_time)} / {get_readable_time(duration)}`\n"
                    f"⚡ **Speed:** `{speed}x`"
                    f"{ffmpeg_status_foot(status, self.user_id, self.start_time, time_in_us)}\n"
                    f"{DIVIDER}\n"
                    f"_Batal? /cancel{CMD_SUFFIX} process {self.process_id}_"
                )
                self.status_message = text
                await asynciosleep(0.5)
                
            elif status.type() == Names.aria:
                if status.process_status == 0:
                    text = (
                        f"**{status.status()}** `[{self.dw_index}]`\n"
                        f"📁 `{status.name()}`\n"
                        f"{get_progress_bar_from_percentage(status.progress())} **{status.progress()}**\n"
                        f"{DIVIDER}\n"
                        f"{self.get_task_details()}"
                        f"🚀 **Engine:** `Aria2c`\n"
                        f"📦 **Size:** `{get_human_size(int(status.processed_bytes()))} / {get_human_size(int(status.size_raw()))}`\n"
                        f"⚡ **Speed:** `{status.speed()}` | ⏱ **ETA:** `{status.eta()}`\n"
                        f"{DIVIDER}\n"
                        f"_Batal? /cancel{CMD_SUFFIX} aria {status.gid()}_"
                    )
                    self.status_message = text
                    await asynciosleep(0.5)
                else:
                    break

    def telegram_update_status(
        self, current: int, total: int, mode: str, name: str,
        start_time: float, status: str, engine: str, client=False,
    ) -> None:
        self.ping = time()
        if client and not check_running_process(self.process_id):
            client.stop_transmission()

        elapsed = max(1, round(time() - start_time))
        speed   = current / elapsed
        eta = get_readable_time((total - current) / speed) if (speed > 0 and total > current) else "N/A"
        pct  = f"{current * 100 / max(total, 1):.1f}%"
        
        # [FIX] Telegram Status ke Markdown murni
        text = (
            f"**{status}**\n"
            f"📁 `{name}`\n"
            f"{get_progress_bar_string(current, total)} **{pct}**\n"
            f"{DIVIDER}\n"
            f"{self.get_task_details()}"
            f"🚀 **Engine:** `{engine}`\n"
            f"📦 **{mode}:** `{get_human_size(current)} / {get_human_size(total)}`\n"
            f"⚡ **Speed:** `{get_human_size(int(speed))}ps` | ⏱ **ETA:** `{eta}`\n"
            f"{DIVIDER}\n"
            f"_Batal? /cancel{CMD_SUFFIX} process {self.process_id}_"
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
                                
                                # [FIX] Rclone Status ke Markdown murni
                                text = (
                                    f"**{status}**\n"
                                    f"📁 `{name}`\n"
                                    f"{get_progress_bar_from_percentage(percentage)} **{percentage}%**\n"
                                    f"{DIVIDER}\n"
                                    f"{self.get_task_details()}"
                                    f"🚀 **Engine:** `{Names.rclone}`\n"
                                    f"📦 **Diunggah:** `{dwdata[0].strip()} / {dwdata[1].strip()}`\n"
                                    f"⚡ **Speed:** `{progress[2]}` | ⏱ **ETA:** `{eta}`\n"
                                    f"{DIVIDER}\n"
                                    f"_Batal? /cancel{CMD_SUFFIX} process {self.process_id}_"
                                )
                                self.status_message = text
                                await asynciosleep(0.5)
                        except: pass
                except ValueError: pass
        except: pass

        if not cancelled:
            await rclone_process.wait()
            if rclone_process.returncode == 0:
                await check_file_drive_link(search_command, self.event, fileloc, r_config, drive_name, name, self.caption)
            else:
                if exists(log_path):
                    await self.event.client.send_file(self.chat_id, file=log_path, allow_cache=False, reply_to=self.event.message, caption=f"❌ Error saat mengunggah {name} ke Drive")
                else:
                    await self.event.reply("❗ Berkas log rclone tidak ditemukan")
        else:
            try: rclone_process.kill()
            except: pass
            if exists(log_path): remove(log_path)
            return False

        if exists(log_path): remove(log_path)
        return True

    # Helper functions bawaan class yang tidak perlu dimodifikasi
    def replace_send_list(self, files): self.send_files = files
    def update_process_message(self, text): self.status_message = text
