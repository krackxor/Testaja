"""
╔══════════════════════════════════════════════════════════════════════╗
║            bot_helper/Process/Running_Tasks.py                       ║
║            Encoder1 Bot — v3.6 (Global Synergy Edition)              ║
╠══════════════════════════════════════════════════════════════════════╣
║  CHANGELOG v3.6:                                                     ║
║  [SYNERGY] Fungsi get_status_message() kini menggabungkan data dari  ║
║            Standard Engine (FFmpeg Core) & Unified Engine (Studio)   ║
║            ke dalam satu pesan status global yang rapi.              ║
║  [UX]      UI Antrean Standard dirombak agar persis dengan Studio.   ║
╚══════════════════════════════════════════════════════════════════════╝
"""

# ── Standard Library ──────────────────────────────────────────────────
import asyncio
import re
import os
import shutil
from asyncio import Lock, create_task, create_subprocess_exec, sleep
from asyncio.subprocess import PIPE as asyncioPIPE, DEVNULL as asyncioDEVNULL
from collections import deque
from json import loads as json_loads
from os.path import exists, join as path_join
from pathlib import Path
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

# [SYNERGY] Import data UI dari Unified Engine
from bot_helper.Process.Unified_Engine import _ue_working, _ue_queued, _ue_ui_objects

LOGGER = Config.LOGGER

# ── Task Queues ───────────────────────────────────────────────────────
working_task: list       = []
working_task_lock        = Lock()
queued_task: deque       = deque()
queued_task_lock         = Lock()

process_status_checker_value = [0]
process_status_checker_lock  = Lock()

_active_ffmpeg_pids: dict[str, list[int]] = {}
_ffmpeg_pid_lock = Lock()

DIVIDER = "━━━━━━━━━━━━━━━━━━━━"

# ═══════════════════════════════════════════════════════════════════════
#  PID MANAGEMENT
# ═══════════════════════════════════════════════════════════════════════

async def _register_ffmpeg_pid(process_id: str, pid: int) -> None:
    async with _ffmpeg_pid_lock:
        if process_id not in _active_ffmpeg_pids:
            _active_ffmpeg_pids[process_id] = []
        _active_ffmpeg_pids[process_id].append(pid)

async def _kill_ffmpeg_pids(process_id: str) -> int:
    async with _ffmpeg_pid_lock:
        pids = _active_ffmpeg_pids.pop(process_id, [])

    killed = 0
    for pid in pids:
        try:
            import signal
            os.kill(pid, signal.SIGTERM)
            killed += 1
            LOGGER.debug(f"🔴 Kill FFmpeg PID {pid} (process: {process_id})")
        except ProcessLookupError: pass
        except Exception as e: LOGGER.warning(f"⚠️  Gagal kill PID {pid}: {e}")
    return killed

# ═══════════════════════════════════════════════════════════════════════
#  UTILITY & MESSAGING HELPER
# ═══════════════════════════════════════════════════════════════════════

async def _safe_send(process_status, text: str, reply_markup=None):
    try:
        kwargs = {}
        if reply_markup: kwargs["reply_markup"] = reply_markup
        await process_status.event.reply(text, **kwargs)
    except Exception:
        try:
            kwargs = {}
            if reply_markup: kwargs["reply_markup"] = reply_markup
            await process_status.event.bot.send_message(chat_id=process_status.chat_id, text=text, **kwargs)
        except Exception as err:
            LOGGER.error(f"Gagal mengirim pesan peringatan: {err}")

def create_log_file(log_file: str) -> None:
    try:
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        Path(log_file).touch(exist_ok=True)
    except OSError: pass

def get_queued_tasks_len() -> int:
    return len(queued_task) + len(_ue_queued) # Sinergi Counter

def get_user_id(process_id: str):
    for task in working_task:
        if task["process_status"].process_id == process_id:
            return task["process_status"].user_id
    return False

def get_user_task_stats(user_id: int) -> dict:
    active = [t for t in working_task if getattr(t.get("process_status"), "user_id", None) == user_id]
    queued = [t for t in queued_task if getattr(t.get("process_status"), "user_id", None) == user_id]
    
    return {
        "active_count": len(active),
        "queued_count": len(queued),
        "total": len(active) + len(queued),
        "details": active + queued
    }

# ═══════════════════════════════════════════════════════════════════════
#  TRASH CLEANUP
# ═══════════════════════════════════════════════════════════════════════

async def clear_all_trash_on_startup():
    trash_dirs = ["./temp/", "./gameplay/temp/", "./userdata/temp/", "./temp/cloud_uploads/"]
    for d in trash_dirs:
        if os.path.exists(d):
            try:
                shutil.rmtree(d)
                os.makedirs(d, exist_ok=True)
            except Exception: pass

async def clear_trash(task: dict, trash_objects: list, multi_tasks: list) -> None:
    new_task = False
    process_id = task["process_status"].process_id
    ps = task["process_status"]

    if hasattr(ps, "garbage_messages") and ps.garbage_messages:
        for msg_id in ps.garbage_messages:
            try: await Telegram.AIOGRAM_BOT.delete_message(ps.chat_id, msg_id)
            except Exception: pass
        ps.garbage_messages = []

    if hasattr(ps, "custom_dub_audio") and ps.custom_dub_audio and os.path.exists(ps.custom_dub_audio):
        try:
            os.remove(ps.custom_dub_audio)
            parent_dir = os.path.dirname(ps.custom_dub_audio)
            if not os.listdir(parent_dir): os.rmdir(parent_dir)
        except Exception: pass

    if len(multi_tasks):
        if check_running_process(process_id):
            new_process_status = multi_tasks[0]
            new_process_status.move_send_files(ps.send_files)
            multi_tasks.pop(0)
            new_process_status.replace_multi_tasks(multi_tasks)
            new_process_status.move_custom_thumbnail(ps.thumbnail)
            new_task = {"process_status": new_process_status, "functions": []}
        else:
            for t in multi_tasks: del t

    async with working_task_lock:
        if task in working_task: working_task.remove(task)
        if new_task:
            create_task(start_task(new_task))
            working_task.append(new_task)

    await remove_running_process(process_id)
    killed = await _kill_ffmpeg_pids(process_id)

    try: shutil.rmtree(ps.dir, ignore_errors=False)
    except: pass

    del task["process_status"]
    if trash_objects:
        for trash in trash_objects: del trash
    del task

# ═══════════════════════════════════════════════════════════════════════
#  UPLOAD
# ═══════════════════════════════════════════════════════════════════════

async def upload_files(process_status) -> None:
    user_data    = get_data().get(process_status.user_id, {})
    drive_upload = False

    if not user_data.get("upload_tg", True):
        r_config   = f"./userdata/{process_status.user_id}_rclone.conf"
        drive_name = user_data.get("drive_name", "")
        if exists(r_config) and drive_name and verify_rclone_account(r_config, drive_name):
            drive_upload = True

    try:
        if not drive_upload: await asyncio.wait_for(Telegram.upload_videos(process_status), timeout=14400)
        else: await asyncio.wait_for(upload_drive(process_status), timeout=14400)
    except asyncio.TimeoutError:
        await _safe_send(process_status, "❌ Gagal mengunggah file karena koneksi timeout.")
    except Exception as e:
        LOGGER.error(f"❌ Upload error: {e}", exc_info=True)


# ═══════════════════════════════════════════════════════════════════════
#  GLOBAL STATUS SYNERGY (THE BRIDGE)
# ═══════════════════════════════════════════════════════════════════════

async def get_status_message(reply) -> str | bool:
    """
    [SYNERGY] Menarik status dari Standard Engine & Studio Engine secara bersamaan.
    """
    if not working_task and not queued_task and not _ue_ui_objects and not _ue_queued:
        return False
        
    final_status = ""
    
    # 1. TUGAS AKTIF (Yang sedang dirender/didownload)
    if working_task or _ue_ui_objects:
        if working_task:
            for task in list(working_task):
                final_status += task["process_status"].status_message + "\n\n"
        
        # Ekstrak UI dari Unified Engine (Studio)
        if _ue_ui_objects:
            for task_id, ui_obj in _ue_ui_objects.items():
                if ui_obj.last_text: # Ambil text animasi/bar terakhir
                    final_status += ui_obj.last_text + "\n\n"
                else:
                    final_status += f"**⚙️ Memproses Data...**\n📁 `{ui_obj.module_name}`\n🚀 **Engine:** `Unified Core`\n\n"
            
    # 2. TUGAS ANTREAN (Yang sedang menunggu giliran)
    if queued_task or _ue_queued:
        if final_status: final_status += f"{DIVIDER}\n"
        final_status += f"📋 **DAFTAR ANTREAN GLOBAL:**\n\n"
        
        if queued_task:
            for task in list(queued_task):
                final_status += task["process_status"].status_message + "\n\n"
                
        if _ue_queued:
            for task_id, module_name in _ue_queued.items():
                final_status += (
                    f"**⏳ Menunggu Giliran**\n"
                    f"📁 `{module_name}`\n"
                    f"{DIVIDER}\n"
                    f"🚀 **Engine:** `Unified Core`\n\n"
                )
                
    return final_status.strip() if final_status else False


# ═══════════════════════════════════════════════════════════════════════
#  TASK MANAGEMENT
# ═══════════════════════════════════════════════════════════════════════

async def process_status_checker() -> None:
    async with process_status_checker_lock:
        if process_status_checker_value[0] == 1: return
        process_status_checker_value[0] = 1

    while True:
        if not working_task and not queued_task: break
        try:
            for task in list(working_task):
                ps = task["process_status"]
                if time() - ps.ping > 600:
                    await _safe_send(ps, "❗ Task ini dihapus karena tidak ada respons koneksi selama 10 menit.")
                    await clear_trash(task, False, [])
                    await task_manager()
        except: pass
        await sleep(60)

    async with process_status_checker_lock: process_status_checker_value[0] = 0

async def add_task(task: dict) -> None:
    async with working_task_lock:
        if len(working_task) < get_task_limit():
            create_task(start_task(task))
            working_task.append(task)
        else:
            async with queued_task_lock:
                ps = task["process_status"]
                queued_task.append(task)
                queue_pos = len(queued_task)
                
                # Format Antrean identik dengan Unified_Engine
                ps.update_process_message(
                    f"**⏳ Menunggu Antrean**\n"
                    f"📁 `{ps.process_type}`\n"
                    f"{DIVIDER}\n"
                    f"{ps.get_task_details()}"
                    f"🚀 **Engine:** `Standard Core`\n"
                    f"📊 **Posisi Antrean:** `{queue_pos}`\n"
                    f"{DIVIDER}\n"
                    f"_Sistem sedang memproses tugas lain..._"
                )
    create_task(process_status_checker())

async def task_manager() -> None:
    async with working_task_lock:
        if len(working_task) < get_task_limit():
            async with queued_task_lock:
                if queued_task:
                    task = queued_task.popleft()
                    create_task(start_task(task))
                    working_task.append(task)
                    
                    for i, q_task in enumerate(queued_task):
                        q_ps = q_task["process_status"]
                        q_pos = i + 1
                        q_ps.update_process_message(
                            f"**⏳ Menunggu Antrean**\n"
                            f"📁 `{q_ps.process_type}`\n"
                            f"{DIVIDER}\n"
                            f"{q_ps.get_task_details()}"
                            f"🚀 **Engine:** `Standard Core`\n"
                            f"📊 **Posisi Antrean:** `{q_pos}`\n"
                            f"{DIVIDER}\n"
                            f"_Sistem sedang memproses tugas lain..._"
                        )

async def refresh_tasks() -> None:
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
        if not moved: break

async def remove_from_working_task(process_id: str) -> bool:
    async with working_task_lock:
        for task in list(working_task):
            if task["process_status"].process_id == process_id:
                working_task.remove(task)
                return True
    return False

async def get_ffmpeg_log_file(process_id: str) -> str | bool:
    async with working_task_lock:
        for task in list(working_task):
            if task["process_status"].process_id == process_id:
                log_path = f"{task['process_status'].dir}/FFMPEG_LOG.txt"
                return log_path if exists(log_path) else False
    return False

# ═══════════════════════════════════════════════════════════════════════
#  SPECIAL HANDLERS (Identical UI Update)
# ═══════════════════════════════════════════════════════════════════════

async def handle_autocrop(process_status) -> bool:
    if not process_status.send_files: return False
    input_file = process_status.send_files[-1]
    
    process_status.update_process_message(
        f"**✨ Mendeteksi Bilah Hitam**\n"
        f"📁 `{process_status.process_type}`\n"
        f"{DIVIDER}\n"
        f"{process_status.get_task_details()}"
        f"🚀 **Engine:** `FFmpeg Analyzer`\n"
        f"{DIVIDER}\n"
        f"_Sedang memproses frame video..._"
    )

    detect_cmd = ["ffmpeg", "-hide_banner", "-v", "warning", "-i", input_file, "-vf", "cropdetect", "-f", "null", "-"]
    process = await create_subprocess_exec(*detect_cmd, stdout=asyncioDEVNULL, stderr=asyncioPIPE)
    _, stderr = await process.communicate()
    crop_values = re.findall(r"crop=\d+:\d+:\d+:\d+", stderr.decode("utf-8", "replace"))

    if not crop_values: return False
    process_status.crop_params = crop_values[-1]
    command, log_file, _, output_file, file_duration = get_commands(process_status)
    if not command: return False

    create_log_file(log_file)
    ffmpeg_process = await create_subprocess_exec(*command, stdout=asyncioPIPE, stderr=asyncioPIPE)
    await _register_ffmpeg_pid(process_status.process_id, ffmpeg_process.pid)
    ffmpeg_status = FfmpegStatus(ffmpeg_process, log_file, input_file, output_file, file_duration)
    create_task(ffmpeg_status.logger(process_status.process_id, process_status.dir, command))
    await asyncio.gather(process_status.update_status(ffmpeg_status), ffmpeg_process.wait())

    if ffmpeg_process.returncode == 0:
        process_status.replace_send_list([output_file])
        return True
    return False

async def handle_extract(process_status) -> bool:
    if not process_status.send_files: return False
    input_file = process_status.send_files[-1]
    output_dir = f"{process_status.dir}/extract/"
    await make_direc(output_dir)

    process_status.update_process_message(
        f"**📤 Mengekstrak Streams**\n"
        f"📁 `{process_status.process_type}`\n"
        f"{DIVIDER}\n"
        f"{process_status.get_task_details()}"
        f"🚀 **Engine:** `FFmpeg Demuxer`\n"
        f"{DIVIDER}\n"
        f"_Sedang memisahkan audio & subtitle..._"
    )

    try:
        probe_cmd = ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_streams", input_file]
        probe_process = await create_subprocess_exec(*probe_cmd, stdout=asyncioPIPE, stderr=asyncioDEVNULL)
        stdout, _ = await process.communicate()
        all_streams = json_loads(stdout.decode("utf-8", "replace")).get("streams", [])
    except Exception: return False

    commands = []
    output_files = []

    for stream_map in process_status.extract_maps:
        stream_index = int(stream_map.split(":")[-1])
        stream_info  = next((s for s in all_streams if s["index"] == stream_index), None)
        if not stream_info: continue

        codec_type, codec_name = stream_info.get("codec_type", ""), stream_info.get("codec_name", "bin")
        ext = {"subtitle": {"subrip": "srt", "ass": "ass", "mov_text": "srt"}.get(codec_name, "srt")}.get(codec_type, codec_name)
        if codec_type == "audio":
            if "aac" in codec_name: ext = "m4a"
            elif "mp3" in codec_name: ext = "mp3"
            elif "opus" in codec_name: ext = "opus"
            elif "ac3" in codec_name: ext = "ac3"
            else: ext = "mka"

        lang = stream_info.get("tags", {}).get("language", "und")
        output_file = path_join(output_dir, f"track_{stream_index}_{lang}.{ext}")
        output_files.append(output_file)
        commands.append(["ffmpeg", "-hide_banner", "-i", input_file, "-map", stream_map, "-c", "copy", "-y", output_file])

    if not commands: return False

    semaphore = asyncio.Semaphore(3)
    async def _run_with_sem(cmd):
        async with semaphore: return await run_process_command(cmd)

    results = await asyncio.gather(*[_run_with_sem(cmd) for cmd in commands])
    if all(results):
        process_status.replace_send_list([f for f in output_files if exists(f)])
        return True
    return False

# ═══════════════════════════════════════════════════════════════════════
#  MAIN TASK RUNNER
# ═══════════════════════════════════════════════════════════════════════

async def start_task(task: dict) -> None:
    process_status = task["process_status"]
    multi_tasks    = process_status.multi_tasks
    process_status.update_start_time(time())
    await append_running_process(process_status.process_id)
    trash_objects = []

    try:
        loop_range        = len(task["functions"])
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
                    success = await asyncio.wait_for(Telegram.download_tg_file(process_status, telegram_file_object, dw_index), timeout=14400)
                    if not success: break
                except asyncio.TimeoutError:
                    await _safe_send(process_status, "❌ Download dari Telegram gagal karena timeout.")
                    break
                except Exception: break

            if not check_running_process(process_status.process_id): break
            if i == loop_range - 1:
                process_completed = True
                process_status.set_file_name_from_send_list()

        if not check_running_process(process_status.process_id): return
        if process_status.process_type == Names.pre_download:
            async with working_task_lock:
                if task in working_task: working_task.remove(task)
            await remove_running_process(process_status.process_id)
            return

        # ── PROCESS PHASE ─────────────────────────────────────────────────
        if process_completed:
            if process_status.process_type == Names.gensample:
                await gen_sample_video(process_status, force_gen=True)
                upload_needed, process_completed = False, True
            elif process_status.process_type == Names.genss:
                await generate_ss(process_status, force_gen=True)
                upload_needed, process_completed = False, True
            elif process_status.process_type == Names.autocrop:
                process_completed = await handle_autocrop(process_status)
            elif process_status.process_type == Names.extract:
                process_completed = await handle_extract(process_status)
            elif process_status.process_type == Names.split:
                process_status.update_process_message(
                    f"**✂️ Membagi Video**\n"
                    f"📁 `{process_status.process_type}`\n"
                    f"{DIVIDER}\n"
                    f"{process_status.get_task_details()}"
                    f"🚀 **Engine:** `FFmpeg Splitter`\n"
                    f"{DIVIDER}\n"
                    f"_Sedang memotong durasi/ukuran video..._"
                )
                split_dir   = f"{process_status.dir}/split/"
                await make_direc(split_dir)
                input_video = process_status.send_files[-1]
                mode, value = process_status.split_mode, process_status.split_value

                splitted_files = []
                if mode == "duration": splitted_files = await split_by_duration(input_video, value, split_dir)
                elif mode == "parts": splitted_files = await split_by_parts(input_video, value, split_dir)
                elif mode == "size": splitted_files = await split_by_size(input_video, value, process_status.dir)

                if splitted_files: process_status.replace_send_list(splitted_files)
                else:
                    await _safe_send(process_status, "❌ Gagal membagi video.")
                    process_completed = False

            elif process_status.process_type in Names.FFMPEG_PROCESSES:
                output_list = []
                convert_list = process_status.convert_list if (hasattr(process_status, "convert_list") and process_status.convert_list and process_status.process_type == Names.convert) else ([1] if process_status.process_type != Names.convert else [720, 480])

                for c, _ in enumerate(convert_list):
                    if process_status.process_type == Names.convert:
                        process_status.update_convert_quality(convert_list[c])
                        process_status.update_convert_index(f"{c + 1}/{len(convert_list)}")

                    command, log_file, input_file, output_file, file_duration = get_commands(process_status)
                    if not command:
                        if output_file and exists(output_file): output_list.append(output_file)
                        continue

                    create_log_file(log_file)
                    ffmpeg_process = await create_subprocess_exec(*command, stdout=asyncioPIPE, stderr=asyncioPIPE)
                    await _register_ffmpeg_pid(process_status.process_id, ffmpeg_process.pid)

                    ffmpeg_status = FfmpegStatus(ffmpeg_process, log_file, input_file, output_file, file_duration)
                    create_task(ffmpeg_status.logger(process_status.process_id, process_status.dir, command))
                    trash_objects.append(ffmpeg_status)

                    try:
                        timeout_limit = getattr(Config, 'FFMPEG_TIMEOUT', 7200)
                        await asyncio.wait_for(asyncio.gather(process_status.update_status(ffmpeg_status), ffmpeg_process.wait()), timeout=timeout_limit)
                        if ffmpeg_process.returncode == 0:
                            output_list.append(output_file)
                            process_completed = True
                        else:
                            log_path = f"{process_status.dir}/FFMPEG_LOG.txt"
                            if exists(log_path):
                                result = await analyze_ffmpeg_error(log_path)
                                reply_text = f"**Proses `{process_status.process_type}` gagal!**\n\n**🔬 Diagnosis:**\n{result.get('diagnosis', 'Unknown Error')}\n\n**💡 Rekomendasi:**\n{result.get('solutions_text', 'Tidak ada saran.')}"
                                markup = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🎬 Video", callback_data="video_settings"), InlineKeyboardButton(text="🎧 Audio", callback_data="audio_settings")], [InlineKeyboardButton(text="🗒️ Kirim Log", callback_data=f"send_log_{process_status.process_id}")]])
                                await _safe_send(process_status, reply_text, reply_markup=markup)
                            else:
                                await _safe_send(process_status, f"❌ Proses gagal (code: {ffmpeg_process.returncode}).")
                            process_completed = False
                            break
                    except asyncio.TimeoutError:
                        try: ffmpeg_process.kill()
                        except: pass
                        await _safe_send(process_status, "❌ Timeout: Proses terlalu lama dihentikan otomatis.")
                        process_completed = False
                        break

                if process_completed: process_status.replace_send_list(output_list)
            elif process_status.process_type in [Names.leech, Names.mirror]: pass

        # ── UPLOAD PHASE ──────────────────────────────────────────────────
        if process_completed:
            is_final_step = not multi_tasks
            user_data     = get_data().get(process_status.user_id, {})
            if upload_needed and (user_data.get("upload_all", True) or is_final_step): await upload_files(process_status)
            if is_final_step and upload_needed:
                if check_running_process(process_status.process_id): await gen_sample_video(process_status)
                if check_running_process(process_status.process_id): await generate_ss(process_status)

    except Exception: pass
    finally:
        await clear_trash(task, trash_objects, multi_tasks)
        await task_manager()
