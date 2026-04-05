"""
╔══════════════════════════════════════════════════════════════════════╗
║            bot_helper/Process/Running_Tasks.py                       ║
║            Encoder1 Bot — v3.1 (Aiogram 3.x)                         ║
╠══════════════════════════════════════════════════════════════════════╣
║  CHANGELOG dari versi lama:                                          ║
║  [FIX HIGH]  pkill ffmpeg global → kill PID spesifik                 ║
║  [FIX HIGH]  get_data()[user_id] → .get() semua tempat               ║
║  [FIX HIGH]  analyze_ffmpeg_error tuple → dict (Step 8 API)          ║
║  [FIX HIGH]  refresh_tasks return di dalam while → logic benar       ║
║  [FIX]       Iterasi working_task tanpa lock → list() snapshot       ║
║  [FIX]       queued_task list → deque (O(1) popleft)                 ║
║  [FIX]       create_log_file sync → pathlib.touch()                  ║
║  [FIX]       handle_extract gather → Semaphore(3)                    ║
║  [FIX]       bare except rmtree → (OSError, FileNotFoundError)       ║
║  [FIX]       handle_autocrop stdout deadlock → DEVNULL               ║
║  [IMPROVE]   process_status_checker log → LOGGER.debug               ║
║  [IMPROVE]   upload_files cache user_data sekali                     ║
║  [FIX CRIT]  Menghapus sisa Telethon Button → Aiogram Markup         ║
║  [FIX HIGH]  Fallback send_message jika pesan asli (reply) dihapus   ║
║  [FIX BUG]   FFmpeg sukses tidak lanjut upload (process_completed)   ║
╚══════════════════════════════════════════════════════════════════════╝
"""

# ── Standard Library ──────────────────────────────────────────────────
import asyncio
import re
from asyncio import Lock, create_task, create_subprocess_exec, sleep
from asyncio.subprocess import PIPE as asyncioPIPE, DEVNULL as asyncioDEVNULL
from collections import deque
from json import loads as json_loads
from os import remove
from os.path import exists, join as path_join
from pathlib import Path
from shutil import rmtree
from time import time

# ── Aiogram ───────────────────────────────────────────────────────────
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

# ── Internal ──────────────────────────────────────────────────────────
from bot_helper.Database.User_Data import get_data, get_task_limit
from bot_helper.FFMPEG.FFMPEG_Commands import get_commands
from bot_helper.FFMPEG.FFMPEG_ErrorParser import analyze_ffmpeg_error
from bot_helper.FFMPEG.FFMPEG_Processes import (
    change_metadata, gen_sample_video, generate_ss,
    get_output_name, run_process_command, select_audio,
    split_by_duration, split_by_parts, split_by_size,
)
from bot_helper.FFMPEG.FFMPEG_Status import FfmpegStatus
from bot_helper.Others.Helper_Functions import make_direc, verify_rclone_account
from bot_helper.Others.Names import Names
from bot_helper.Process.Running_Process import (
    append_running_process, check_running_process, remove_running_process,
)
from bot_helper.Rclone.Rclone_Upload import upload_drive
from bot_helper.Telegram.Telegram_Client import Telegram
from config.config import Config

LOGGER = Config.LOGGER

# ── Task Queues ───────────────────────────────────────────────────────
working_task: list       = []
working_task_lock        = Lock()

# [FIX] deque untuk O(1) popleft() bukan list.pop(0) O(n)
queued_task: deque       = deque()
queued_task_lock         = Lock()

process_status_checker_value = [0]
process_status_checker_lock  = Lock()

# [FIX HIGH] Registry PID ffmpeg aktif — untuk kill spesifik, bukan pkill global
_active_ffmpeg_pids: dict[str, list[int]] = {}   # process_id → [pid1, pid2, ...]
_ffmpeg_pid_lock = Lock()


# ═══════════════════════════════════════════════════════════════════════
#  PID MANAGEMENT
# ═══════════════════════════════════════════════════════════════════════

async def _register_ffmpeg_pid(process_id: str, pid: int) -> None:
    """Daftarkan PID ffmpeg ke registry agar bisa di-kill spesifik."""
    async with _ffmpeg_pid_lock:
        if process_id not in _active_ffmpeg_pids:
            _active_ffmpeg_pids[process_id] = []
        _active_ffmpeg_pids[process_id].append(pid)


async def _kill_ffmpeg_pids(process_id: str) -> int:
    """
    [FIX HIGH] Kill hanya PID ffmpeg milik process_id ini.
    Sebelumnya: pkill -f ffmpeg → bunuh SEMUA ffmpeg di sistem.
    """
    async with _ffmpeg_pid_lock:
        pids = _active_ffmpeg_pids.pop(process_id, [])

    killed = 0
    for pid in pids:
        try:
            import os
            import signal
            os.kill(pid, signal.SIGTERM)
            killed += 1
            LOGGER.debug(f"🔴 Kill FFmpeg PID {pid} (process: {process_id})")
        except ProcessLookupError:
            pass   # Proses sudah selesai sendiri
        except Exception as e:
            LOGGER.warning(f"⚠️  Gagal kill PID {pid}: {e}")
    return killed


# ═══════════════════════════════════════════════════════════════════════
#  UTILITY & MESSAGING HELPER
# ═══════════════════════════════════════════════════════════════════════

async def _safe_send(process_status, text: str, reply_markup=None):
    """
    [FIX HIGH] Kirim pesan dengan aman. Jika reply gagal (karena pesan dihapus),
    maka fallback ke send_message biasa.
    """
    try:
        kwargs = {}
        if reply_markup:
            kwargs["reply_markup"] = reply_markup
        await process_status.event.reply(text, **kwargs)
    except Exception:
        try:
            kwargs = {}
            if reply_markup:
                kwargs["reply_markup"] = reply_markup
            await process_status.event.bot.send_message(chat_id=process_status.chat_id, text=text, **kwargs)
        except Exception as err:
            LOGGER.error(f"Gagal mengirim pesan peringatan ke {process_status.chat_id}: {err}")


def create_log_file(log_file: str) -> None:
    """
    Buat file log kosong.
    [FIX] Pakai pathlib.touch() — lebih Pythonic, tidak perlu open/close manual.
    """
    try:
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        Path(log_file).touch(exist_ok=True)
        LOGGER.debug(f"Log file dibuat: {log_file}")
    except OSError as e:
        LOGGER.warning(f"⚠️  Gagal buat log file {log_file}: {e}")


def get_queued_tasks_len() -> int:
    return len(queued_task)


def get_user_id(process_id: str):
    """Return user_id dari process_id, atau False jika tidak ditemukan."""
    for task in working_task:
        if task["process_status"].process_id == process_id:
            return task["process_status"].user_id
    return False


# ═══════════════════════════════════════════════════════════════════════
#  TRASH CLEANUP
# ═══════════════════════════════════════════════════════════════════════

async def clear_trash(task: dict, trash_objects: list, multi_tasks: list) -> None:
    """
    Cleanup setelah task selesai.

    [FIX HIGH] Hapus pkill ffmpeg global → kill hanya PID task ini
    [FIX]      bare except rmtree → (OSError, FileNotFoundError) dengan warning
    """
    new_task = False
    process_id = task["process_status"].process_id

    if len(multi_tasks):
        if check_running_process(process_id):
            new_process_status = multi_tasks[0]
            new_process_status.move_send_files(task["process_status"].send_files)
            multi_tasks.pop(0)
            new_process_status.replace_multi_tasks(multi_tasks)
            new_process_status.move_custom_thumbnail(task["process_status"].thumbnail)
            new_task = {"process_status": new_process_status, "functions": []}
        else:
            for t in multi_tasks:
                del t

    async with working_task_lock:
        if task in working_task:
            working_task.remove(task)
        if new_task:
            create_task(start_task(new_task))
            working_task.append(new_task)

    await remove_running_process(process_id)

    # [FIX HIGH] Kill hanya PID ffmpeg milik task ini
    killed = await _kill_ffmpeg_pids(process_id)
    if killed:
        LOGGER.info(f"✅ Killed {killed} FFmpeg process(es) untuk task {process_id}")

    # [FIX] bare except → specific exception dengan logging
    try:
        rmtree(task["process_status"].dir, ignore_errors=False)
    except (OSError, FileNotFoundError) as e:
        LOGGER.warning(f"⚠️  rmtree gagal untuk {task['process_status'].dir}: {e}")

    del task["process_status"]
    if trash_objects:
        for trash in trash_objects:
            del trash
    del task


# ═══════════════════════════════════════════════════════════════════════
#  UPLOAD
# ═══════════════════════════════════════════════════════════════════════

async def upload_files(process_status) -> None:
    """
    Upload files ke Telegram atau Drive.

    [FIX HIGH] get_data()[user_id] → .get() dengan fallback
    [IMPROVE]  Cache user_data sekali bukan panggil get_data() 2x
    """
    # [FIX] Cache user_data sekali
    user_data    = get_data().get(process_status.user_id, {})
    drive_upload = False

    if not user_data.get("upload_tg", True):
        r_config   = f"./userdata/{process_status.user_id}_rclone.conf"
        drive_name = user_data.get("drive_name", "")
        if exists(r_config) and drive_name and verify_rclone_account(r_config, drive_name):
            drive_upload = True

    if not drive_upload:
        await Telegram.upload_videos(process_status)
    else:
        await upload_drive(process_status)


# ═══════════════════════════════════════════════════════════════════════
#  PROCESS STATUS CHECKER
# ═══════════════════════════════════════════════════════════════════════

async def process_status_checker() -> None:
    """
    Background task: monitor dan kill task yang tidak responding > 10 menit.

    [FIX]      Iterasi snapshot list(working_task) bukan langsung — cegah RuntimeError
    [IMPROVE]  LOGGER.debug untuk routine check, bukan LOGGER.info
    """
    async with process_status_checker_lock:
        if process_status_checker_value[0] == 1:
            LOGGER.debug("Process Status Checker sudah berjalan")
            return
        process_status_checker_value[0] = 1
        LOGGER.info("🔵 Process Status Checker dimulai")

    while True:
        LOGGER.debug("Process Status Checker: cek dead processes")

        if not working_task and not queued_task:
            LOGGER.info("✅ Process Status Checker berhenti — tidak ada task aktif")
            break

        try:
            # [FIX] Iterasi snapshot list() — cegah RuntimeError jika working_task dimodifikasi
            for task in list(working_task):
                ps = task["process_status"]
                if time() - ps.ping > 600:
                    LOGGER.warning(
                        f"⚠️  Task {ps.process_type} tidak respond 10 menit — dihapus"
                    )
                    await _safe_send(ps, "❗ Task ini dihapus karena tidak ada respons selama 10 menit.")
                    await clear_trash(task, False, [])
                    await task_manager()

        except Exception as e:
            LOGGER.error(f"❌ process_status_checker error: {e}", exc_info=True)

        await sleep(60)

    async with process_status_checker_lock:
        process_status_checker_value[0] = 0


# ═══════════════════════════════════════════════════════════════════════
#  TASK MANAGEMENT
# ═══════════════════════════════════════════════════════════════════════

async def add_task(task: dict) -> None:
    """Tambahkan task ke working atau queue."""
    async with working_task_lock:
        if len(working_task) < get_task_limit():
            LOGGER.info("➕ Task ditambahkan ke working")
            create_task(start_task(task))
            working_task.append(task)
        else:
            async with queued_task_lock:
                queued_task.append(task)
                LOGGER.info(f"⏳ Task ditambahkan ke queue (posisi: {len(queued_task)})")

    await process_status_checker()


async def task_manager() -> None:
    """Pindahkan task dari queue ke working jika ada slot."""
    async with working_task_lock:
        if len(working_task) < get_task_limit():
            async with queued_task_lock:
                if queued_task:
                    task = queued_task.popleft()   # [FIX] deque.popleft() O(1)
                    LOGGER.info("🔄 Task dipindah dari queue ke working")
                    create_task(start_task(task))
                    working_task.append(task)


async def refresh_tasks() -> None:
    """
    Pindahkan semua task dari queue ke working selama ada slot.

    [FIX HIGH] return di dalam while loop → sekarang loop sampai kondisi habis
    """
    while True:
        moved = False
        async with working_task_lock:
            if len(working_task) < get_task_limit():
                async with queued_task_lock:
                    if queued_task:
                        task = queued_task.popleft()
                        create_task(start_task(task))
                        working_task.append(task)
                        moved = True
        # [FIX] Break hanya jika tidak ada yang dipindah atau working penuh
        if not moved:
            break


async def remove_from_working_task(process_id: str) -> bool:
    """Hapus task dari working_task berdasarkan process_id."""
    async with working_task_lock:
        for task in list(working_task):
            if task["process_status"].process_id == process_id:
                working_task.remove(task)
                LOGGER.info(f"✅ Task {process_id} dihapus dari working")
                return True
    return False


async def get_ffmpeg_log_file(process_id: str) -> str | bool:
    """Return path log file untuk process_id, atau False jika tidak ada."""
    async with working_task_lock:
        for task in list(working_task):
            if task["process_status"].process_id == process_id:
                log_path = f"{task['process_status'].dir}/FFMPEG_LOG.txt"
                return log_path if exists(log_path) else False
    return False


async def get_status_message(reply) -> str | bool:
    """Return status message semua working task untuk display."""
    if not working_task and not queued_task:
        return False

    retry = 0
    if not working_task:
        try:
            await reply.edit("⏳ Menunggu task dimulai...")
        except Exception:
            pass
        while not working_task and retry < 30:
            await sleep(1)
            retry += 1

    if working_task:
        final_status = ""
        for task in list(working_task):
            final_status += task["process_status"].status_message + "\n\n"
        return final_status.strip()

    return False


# ═══════════════════════════════════════════════════════════════════════
#  SPECIAL HANDLERS
# ═══════════════════════════════════════════════════════════════════════

async def handle_autocrop(process_status) -> bool:
    """
    Deteksi dan crop black bars otomatis.

    [FIX] stdout=DEVNULL — cegah deadlock karena stdout tidak di-drain
    """
    input_file = process_status.send_files[-1]
    process_status.update_process_message("✨ Mendeteksi bilah hitam...")

    detect_cmd = [
        "ffmpeg", "-hide_banner",
        "-i", input_file,
        "-vf", "cropdetect",
        "-f", "null", "-",
    ]
    process = await create_subprocess_exec(
        *detect_cmd,
        stdout=asyncioDEVNULL,   # [FIX] Bukan default (tidak di-pipe tapi tidak di-drain)
        stderr=asyncioPIPE,
    )
    _, stderr = await process.communicate()

    stderr_str  = stderr.decode("utf-8", "replace")
    crop_values = re.findall(r"crop=\d+:\d+:\d+:\d+", stderr_str)

    if not crop_values:
        await _safe_send(process_status, "❌ Gagal mendeteksi bilah hitam.")
        return False

    crop_params = crop_values[-1]
    LOGGER.info(f"Autocrop detected: {crop_params}")
    process_status.crop_params = crop_params

    command, log_file, _, output_file, file_duration = get_commands(process_status)
    if not command:
        await _safe_send(process_status, "❌ Gagal membuat perintah FFmpeg untuk autocrop.")
        return False

    create_log_file(log_file)
    ffmpeg_process = await create_subprocess_exec(*command, stdout=asyncioPIPE, stderr=asyncioPIPE)

    # [FIX HIGH] Daftarkan PID agar bisa di-kill spesifik
    await _register_ffmpeg_pid(process_status.process_id, ffmpeg_process.pid)

    ffmpeg_status = FfmpegStatus(ffmpeg_process, log_file, input_file, output_file, file_duration)
    create_task(ffmpeg_status.logger(process_status.process_id, process_status.dir, command))
    await process_status.update_status(ffmpeg_status)
    await ffmpeg_process.wait()

    if ffmpeg_process.returncode == 0:
        process_status.replace_send_list([output_file])
        return True

    log_path = f"{process_status.dir}/FFMPEG_LOG.txt"
    if exists(log_path):
        from aiogram.types import FSInputFile
        try:
            await process_status.event.bot.send_document(
                process_status.chat_id,
                document=FSInputFile(log_path),
                caption=f"❌ Autocrop gagal (returncode: {ffmpeg_process.returncode})",
            )
        except Exception:
            pass
    return False


async def handle_extract(process_status) -> bool:
    """
    Extract stream dari video.

    [FIX] asyncio.gather → Semaphore(3) cegah saturasi I/O
    """
    input_file = process_status.send_files[-1]
    output_dir = f"{process_status.dir}/extract/"
    await make_direc(output_dir)

    process_status.update_process_message(
        f"📤 Extracting streams...\n{process_status.get_task_details()}"
    )

    try:
        probe_cmd = [
            "ffprobe", "-v", "quiet",
            "-print_format", "json", "-show_streams",
            input_file,
        ]
        probe_process = await create_subprocess_exec(*probe_cmd, stdout=asyncioPIPE, stderr=asyncioDEVNULL)
        stdout, _ = await probe_process.communicate()
        all_streams = json_loads(stdout.decode("utf-8", "replace")).get("streams", [])
    except Exception as e:
        LOGGER.error(f"❌ ffprobe gagal untuk extract: {e}", exc_info=True)
        await _safe_send(process_status, f"❌ Gagal membaca stream dari video: `{e}`")
        return False

    commands     = []
    output_files = []

    for stream_map in process_status.extract_maps:
        stream_index = int(stream_map.split(":")[-1])
        stream_info  = next((s for s in all_streams if s["index"] == stream_index), None)
        if not stream_info:
            continue

        codec_type = stream_info.get("codec_type", "")
        codec_name = stream_info.get("codec_name", "bin")

        # Tentukan ekstensi output
        ext = codec_name
        if codec_type == "subtitle":
            ext_map = {"subrip": "srt", "ass": "ass", "mov_text": "srt"}
            ext = ext_map.get(codec_name, "srt")
        elif codec_type == "audio":
            if "aac" in codec_name:   ext = "m4a"
            elif "mp3" in codec_name: ext = "mp3"
            elif "opus" in codec_name: ext = "opus"
            elif "ac3" in codec_name: ext = "ac3"
            else:                     ext = "mka"

        lang        = stream_info.get("tags", {}).get("language", "und")
        output_file = path_join(output_dir, f"track_{stream_index}_{lang}.{ext}")
        output_files.append(output_file)
        commands.append(["ffmpeg", "-hide_banner", "-i", input_file, "-map", stream_map, "-c", "copy", "-y", output_file])

    if not commands:
        await _safe_send(process_status, "❌ Tidak ada stream yang bisa diekstrak.")
        return False

    # [FIX] Semaphore(3) — max 3 ekstraksi paralel bukan semua sekaligus
    semaphore = asyncio.Semaphore(3)

    async def _run_with_sem(cmd):
        async with semaphore:
            return await run_process_command(cmd)

    results = await asyncio.gather(*[_run_with_sem(cmd) for cmd in commands])

    if all(results):
        process_status.replace_send_list([f for f in output_files if exists(f)])
        return True

    await _safe_send(process_status, "❌ Terjadi kesalahan saat mengekstrak satu atau lebih stream.")
    return False


# ═══════════════════════════════════════════════════════════════════════
#  MAIN TASK RUNNER
# ═══════════════════════════════════════════════════════════════════════

async def start_task(task: dict) -> None:
    """
    Main task runner — download → process → upload.

    [FIX HIGH] get_data()[user_id] → .get() dengan fallback
    [FIX HIGH] analyze_ffmpeg_error return dict → ambil ['diagnosis'] dan ['solutions_text']
    [FIX HIGH] Daftarkan PID ffmpeg ke _active_ffmpeg_pids
    [FIX CRIT] Menggunakan InlineKeyboardMarkup dari Aiogram (Bukan Button.inline Telethon)
    """
    process_status = task["process_status"]
    multi_tasks    = process_status.multi_tasks
    process_status.update_start_time(time())
    await append_running_process(process_status.process_id)

    loop_range        = len(task["functions"])
    trash_objects     = []
    process_completed = (loop_range == 0)
    upload_needed     = True

    # ── DOWNLOAD PHASE ────────────────────────────────────────────────
    for i in range(loop_range):
        dw_index = f"{i + 1}/{loop_range}"
        func_info = task["functions"][i]
        func_type = func_info[0]

        if func_type == Names.aria:
            func_call, func_args = func_info[1], func_info[2]
            process_status.set_dw_index(dw_index)
            download, aria2_status = await func_call(*func_args)
            if not download:
                await _safe_send(process_status, process_status.status_message)
                break
            trash_objects.append(aria2_status)
            await process_status.update_status(aria2_status)
            if aria2_status.process_status != 1:
                await _safe_send(process_status, process_status.message)
                break
            process_status.move_dw_file(aria2_status.name())
        else:
            telegram_file_object = func_info[1]
            try:
                if not await Telegram.download_tg_file(process_status, telegram_file_object, dw_index):
                    break
            except Exception as e:
                LOGGER.error(f"❌ Telegram download error: {e}", exc_info=True)
                break

        if not check_running_process(process_status.process_id):
            break

        if i == loop_range - 1:
            process_completed = True
            process_status.set_file_name_from_send_list()

    if not check_running_process(process_status.process_id):
        await clear_trash(task, trash_objects, multi_tasks)
        await task_manager()
        return

    # Pre-download only — skip upload
    if process_status.process_type == Names.pre_download:
        LOGGER.info(f"Pre-download selesai untuk {process_status.process_id}")
        async with working_task_lock:
            if task in working_task:
                working_task.remove(task)
        await remove_running_process(process_status.process_id)
        await task_manager()
        return

    # ── PROCESS PHASE ─────────────────────────────────────────────────
    if process_completed:

        if process_status.process_type == Names.gensample:
            await gen_sample_video(process_status, force_gen=True)
            upload_needed     = False
            process_completed = True

        elif process_status.process_type == Names.genss:
            await generate_ss(process_status, force_gen=True)
            upload_needed     = False
            process_completed = True

        elif process_status.process_type == Names.autocrop:
            process_completed = await handle_autocrop(process_status)

        elif process_status.process_type == Names.extract:
            process_completed = await handle_extract(process_status)

        elif process_status.process_type in Names.FFMPEG_PROCESSES:
            output_list = []

            # [FIX HIGH] .get() dengan fallback
            user_data    = get_data().get(process_status.user_id, {})
            convert_list = (
                user_data.get("convert", {}).get("convert_list", [720, 480])
                if process_status.process_type == Names.convert
                else [1]
            )

            for c, _ in enumerate(convert_list):
                if process_status.process_type == Names.convert:
                    process_status.update_convert_quality(convert_list[c])
                    process_status.update_convert_index(f"{c + 1}/{len(convert_list)}")

                command, log_file, input_file, output_file, file_duration = get_commands(process_status)
                if not command:
                    # Bisa jadi subtitle copy — output_file sudah ada
                    if output_file and exists(output_file):
                        output_list.append(output_file)
                    continue

                create_log_file(log_file)
                ffmpeg_process = await create_subprocess_exec(
                    *command, stdout=asyncioPIPE, stderr=asyncioPIPE
                )

                # [FIX HIGH] Daftarkan PID agar bisa di-kill spesifik
                await _register_ffmpeg_pid(process_status.process_id, ffmpeg_process.pid)

                ffmpeg_status = FfmpegStatus(
                    ffmpeg_process, log_file, input_file, output_file, file_duration
                )
                create_task(ffmpeg_status.logger(
                    process_status.process_id, process_status.dir, command
                ))
                trash_objects.append(ffmpeg_status)
                await process_status.update_status(ffmpeg_status)

                try:
                    await asyncio.wait_for(ffmpeg_process.wait(), timeout=7200)

                    # [FIX BUG UPLOAD] Perbaikan logika kondisi sukses/gagal di sini!
                    if ffmpeg_process.returncode == 0:
                        output_list.append(output_file)
                        process_completed = True
                    else:
                        log_path = f"{process_status.dir}/FFMPEG_LOG.txt"

                        if exists(log_path):
                            # [FIX HIGH] analyze_ffmpeg_error return dict bukan tuple
                            result        = await analyze_ffmpeg_error(log_path)
                            error_reason  = result.get("diagnosis", "Unknown Error")
                            suggestions   = result.get("solutions_text", "Tidak ada saran.")

                            reply_text = (
                                f"**Proses `{process_status.process_type}` gagal!**\n\n"
                                f"**🔬 Diagnosis:**\n{error_reason}\n\n"
                                f"**💡 Rekomendasi:**\n{suggestions}"
                            )
                            # [FIX CRIT] Menggunakan InlineKeyboardMarkup dari Aiogram
                            markup = InlineKeyboardMarkup(inline_keyboard=[
                                [InlineKeyboardButton(text="🎬 Pengaturan Video", callback_data="video_settings"),
                                 InlineKeyboardButton(text="🎧 Pengaturan Audio", callback_data="audio_settings")],
                                [InlineKeyboardButton(text="🗒️ Kirim Log Lengkap", callback_data=f"send_log_{process_status.process_id}")],
                            ])
                            await _safe_send(process_status, reply_text, reply_markup=markup)
                        else:
                            await _safe_send(
                                process_status,
                                f"❌ Proses `{process_status.process_type}` gagal "
                                f"(returncode: {ffmpeg_process.returncode})."
                            )
                        
                        # Set False dan hentikan jika proses gagal
                        process_completed = False
                        break

                except asyncio.TimeoutError:
                    LOGGER.error(
                        f"❌ FFmpeg PID {ffmpeg_process.pid} timeout (>2 jam), dihentikan paksa"
                    )
                    try:
                        ffmpeg_process.kill()
                    except ProcessLookupError:
                        pass
                    await _safe_send(
                        process_status,
                        "❌ Proses encoding terlalu lama (> 2 jam) dan dihentikan otomatis."
                    )
                    process_completed = False
                    break

            if process_completed:
                process_status.replace_send_list(output_list)

        elif process_status.process_type in [Names.leech, Names.mirror]:
            pass

        elif process_status.process_type == Names.split:
            process_status.update_process_message(
                f"✂️ Membagi video...\n{process_status.get_task_details()}"
            )
            split_dir   = f"{process_status.dir}/split/"
            await make_direc(split_dir)
            input_video = process_status.send_files[-1]
            mode, value = process_status.split_mode, process_status.split_value

            splitted_files = []
            if mode == "duration":
                splitted_files = await split_by_duration(input_video, value, split_dir)
            elif mode == "parts":
                splitted_files = await split_by_parts(input_video, value, split_dir)
            elif mode == "size":
                splitted_files = await split_by_size(input_video, value, process_status.dir)

            if splitted_files:
                process_status.replace_send_list(splitted_files)
            else:
                await _safe_send(process_status, "❌ Gagal membagi video.")
                process_completed = False

    # ── UPLOAD PHASE ──────────────────────────────────────────────────
    if process_completed:
        is_final_step = not multi_tasks
        user_data     = get_data().get(process_status.user_id, {})

        if upload_needed and (user_data.get("upload_all", True) or is_final_step):
            await upload_files(process_status)

        if is_final_step and upload_needed:
            if check_running_process(process_status.process_id):
                await gen_sample_video(process_status)
            if check_running_process(process_status.process_id):
                await generate_ss(process_status)

    await clear_trash(task, trash_objects, multi_tasks)
    await task_manager()
