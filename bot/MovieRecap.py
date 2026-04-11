"""
╔══════════════════════════════════════════════════════════════════════╗
║                    bot/MovieRecap.py — v4.2                          ║
║        Movie Recap: Rangkuman Film Otomatis dengan Voiceover AI      ║
╠══════════════════════════════════════════════════════════════════════╣
║  CHANGELOG v4.2:                                                     ║
║  [NEW] INTEGRASI SISTEM POIN! Memotong saldo sebelum render.         ║
║  [UX PREMIUM] Implementasi API Warna Tombol Native Telegram 9.4+     ║
║  [UX PREMIUM] Standardisasi Hierarki Emoji (❌ Error, ⏳ Proses).      ║
║  [UX PREMIUM] Migrasi Total Dashboard Inline menjadi Interactive     ║
║                Wizard (Step-by-step) dengan Reply Keyboard Singkat!  ║
╚══════════════════════════════════════════════════════════════════════╝
"""

import asyncio, os, re, subprocess, time
from datetime import datetime
from typing import Optional

from moviepy import (AudioFileClip, CompositeAudioClip, CompositeVideoClip, VideoFileClip, ColorClip, ImageClip, concatenate_videoclips)
from moviepy.video.fx import FadeIn, FadeOut
import edge_tts

from aiogram import Router, F
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile,
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
)
from aiogram.filters import Command, CommandObject
from aiogram.exceptions import TelegramBadRequest

from bot_helper.Database.User_Data import get_data, ensure_user_data_structure, get_task_limit, get_user_balance
from bot_helper.Others.Helper_Functions import get_human_size, get_readable_time
from bot_helper.Others.Names import Names
from bot_helper.Process.Process_Status import ProcessStatus, get_progress_bar_string
from bot_helper.Process.Running_Process import append_running_process, check_running_process, remove_running_process
from bot_helper.Process.Running_Tasks import working_task, working_task_lock, queued_task, queued_task_lock
from bot_helper.Telegram.Telegram_Client import Telegram
from config.config import Config

from bot.shared import wait_for_message

# [NEW v4.2] Import Mesin Kasir
from bot_helper.Process.point_manager import process_payment

try:
    from bot.YTUpload import upload_to_youtube, YOUTUBE_ENABLED
    _HAS_YTUPLOAD = True
except ImportError:
    YOUTUBE_ENABLED, _HAS_YTUPLOAD = False, False

try:
    from bot.Gameplay import (tmp as _gp_tmp, cleanup_temp as _gp_cleanup, find_gameplay_for_game, normalize_clip, split_gameplay as sample_best_segments, GAMEPLAY_DIR, TEMP_DIR as _GP_TEMP, TARGET_FPS, BITRATE, AUDIO_BR, FFMPEG_PARAMS, VOICE)
    _HAS_GAMEPLAY = True
except ImportError:
    _HAS_GAMEPLAY, GAMEPLAY_DIR, _GP_TEMP = False, "./gameplay/", "./temp/"
    TARGET_FPS, BITRATE, AUDIO_BR, VOICE = 30, "8000k", "192k", "en-US-AndrewNeural"
    FFMPEG_PARAMS = ["-preset", "fast", "-pix_fmt", "yuv420p", "-movflags", "+faststart"]
    def normalize_clip(clip, w=1920, h=1080, fps=30):
        if clip.fps != fps: clip = clip.with_fps(fps)
        src_r, tgt_r = clip.w/clip.h, w/h
        nw, nh = (int(clip.w*(h/clip.h)), h) if src_r > tgt_r else (w, int(clip.h*(w/clip.w)))
        return clip.resized((nw, nh)).cropped(x1=(nw-w)//2, y1=(nh-h)//2, x2=(nw-w)//2+w, y2=(nh-h)//2+h)
    def find_gameplay_for_game(title): return None
    def sample_best_segments(path, total=720, seg=15, step=3, gap=60): return []

LOGGER, CMD_SUFFIX, router = Config.LOGGER, Config.CMD_SUFFIX, Router()

TEMP_DIR, TARGET_W, TARGET_H, QUEUE_TIMEOUT, MAX_CHAPTERS = "./temp/movierecap/", 1920, 1080, 7200, 30

QUALITY_PRESETS = {
    "fast":     {"bitrate": "4000k", "preset": "ultrafast", "label": "⚡ Cepat"},
    "balanced": {"bitrate": "6000k", "preset": "fast",      "label": "⚖️ Seimbang"},
    "hq":       {"bitrate": "8000k", "preset": "slow",      "label": "💎 HQ"},
}
ORIG_AUDIO_VOL = 0.10
os.makedirs(TEMP_DIR, exist_ok=True)

# ═══════════════════════════════════════════════════════════════════════
#  UI & CLEANUP HELPERS (COLOR BUTTONS ENABLED)
# ═══════════════════════════════════════════════════════════════════════

async def _clean_msgs(*msgs):
    """Menghapus pesan untuk menjaga chat tetap rapi."""
    for m in msgs:
        if m:
            try: await m.delete()
            except Exception: pass

def _make_reply_kb(options: list, row_width: int = 2) -> ReplyKeyboardMarkup:
    """Membuat Reply Keyboard dengan mudah dan warna otomatis (Native Telegram)."""
    kb = []
    row = []
    for opt in options:
        if "Batal" in opt or "❌" in opt:
            btn_style = "danger"
        elif "Ya" in opt or "✅" in opt:
            btn_style = "success"
        else:
            btn_style = "primary"
            
        row.append(KeyboardButton(text=opt, style=btn_style))
        
        if len(row) == row_width:
            kb.append(row)
            row = []
    if row:
        kb.append(row)
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True, one_time_keyboard=True)


# ═══════════════════════════════════════════════════════════════════════
#  CORE FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════

async def _safe_edit(msg: Message, text: str, buttons=None) -> None:
    try:
        if buttons: await msg.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
        else: await msg.edit_text(text)
    except TelegramBadRequest: pass
    except Exception: pass

def _tmp(name: str) -> str: return os.path.join(TEMP_DIR, name)
def _cleanup(*paths: str) -> None:
    for p in paths:
        if p and os.path.exists(p):
            try: os.remove(p)
            except OSError: pass

def _time_to_sec(t_str: str) -> float:
    parts = [p.strip() for p in t_str.strip().split(":")]
    if len(parts) == 3: return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    elif len(parts) == 2: return int(parts[0]) * 60 + float(parts[1])
    return float(parts[0])

def _find_movie(title: str) -> Optional[str]:
    if _HAS_GAMEPLAY:
        res = find_gameplay_for_game(title)
        if res: return res
    for folder in [GAMEPLAY_DIR, "./videos/", "./movies/"]:
        if not os.path.isdir(folder): continue
        for f in os.listdir(folder):
            if title.lower().replace(" ", "_") in f.lower():
                if any(f.lower().endswith(ext) for ext in [".mp4", ".mkv", ".avi", ".mov"]): return os.path.join(folder, f)
    return None

def _list_movies() -> list[str]:
    names = []
    for folder in [GAMEPLAY_DIR, "./videos/", "./movies/"]:
        if not os.path.isdir(folder): continue
        for f in os.listdir(folder):
            if any(f.lower().endswith(ext) for ext in [".mp4", ".mkv", ".avi", ".mov"]): names.append(os.path.splitext(f)[0])
    return sorted(set(names))

def parse_recap_txt(path: str) -> list[dict]:
    scenes, errors = [], []
    with open(path, "r", encoding="utf-8", errors="replace") as f: lines = f.readlines()
    for i, raw in enumerate(lines, 1):
        line = raw.strip()
        if not line or line.startswith("#"): continue
        parts = [x.strip() for x in line.split("|")]
        if len(parts) < 2: errors.append(f"Baris {i}: Format harus `Waktu | Narasi`"); continue
        time_str, narration = parts[0], "|".join(parts[1:]).strip()
        if not narration: errors.append(f"Baris {i}: Narasi kosong"); continue
        try: scenes.append({"start": _time_to_sec(time_str), "narration": narration})
        except ValueError: errors.append(f"Baris {i}: Format waktu tidak valid — `{time_str}`")
    if errors: raise ValueError("❌ Format .txt salah:\n" + "\n".join(f"  • {e}" for e in errors))
    if not scenes: raise ValueError("❌ File .txt kosong atau tidak ada baris yang valid.")
    if len(scenes) > MAX_CHAPTERS: raise ValueError(f"❌ Terlalu banyak chapter ({len(scenes)}). Maksimum {MAX_CHAPTERS}.")
    scenes.sort(key=lambda x: x["start"])
    return scenes

async def _generate_tts(narration: str, out_path: str) -> Optional[str]:
    try:
        clean = re.sub(r'[*_`#\[\](){}|>]', '', narration).strip()
        if not clean: clean = "Adegan berlanjut."
        await edge_tts.Communicate(clean, VOICE).save(out_path)
        if not os.path.exists(out_path) or os.path.getsize(out_path) < 512: return None
        return out_path
    except Exception as e:
        LOGGER.error(f"❌ TTS error: {e}", exc_info=True)
        return None

async def _render_chapter(movie_path: str, start_t: float, narration: str, out_path: str, quality: str, chapter_idx: int, total_chapters: int, process_status: ProcessStatus) -> bool:
    if not check_running_process(process_status.process_id): raise asyncio.CancelledError("Dibatalkan")
    tts_path = _tmp(f"tts_{process_status.process_id}_{chapter_idx}.mp3")
    q = QUALITY_PRESETS.get(quality, QUALITY_PRESETS["balanced"])
    raw = clip = vo = None
    try:
        tts_result = await _generate_tts(narration, tts_path)
        if not tts_result: return False
        vo = AudioFileClip(tts_path); vo_dur = max(vo.duration, 1.5)
        raw = VideoFileClip(movie_path); end_t = min(start_t + vo_dur, raw.duration)
        if end_t <= start_t: return False
        clip = normalize_clip(raw.subclip(start_t, end_t), TARGET_W, TARGET_H, TARGET_FPS)
        actual_dur = clip.duration
        
        if clip.audio is not None:
            orig_audio = clip.audio.with_volume_scaled(ORIG_AUDIO_VOL)
            if vo.duration > actual_dur: vo = vo.subclip(0, actual_dur)
            final_audio = CompositeAudioClip([orig_audio, vo])
        else:
            if vo.duration > actual_dur: vo = vo.subclip(0, actual_dur)
            final_audio = vo
            
        clip = clip.with_audio(final_audio)
        fade = min(0.4, actual_dur * 0.1)
        if chapter_idx > 1: clip = clip.with_effects([FadeIn(fade)])
        if chapter_idx < total_chapters: clip = clip.with_effects([FadeOut(fade)])
        ffmpeg_extra = ["-preset", q["preset"], "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-max_muxing_queue_size", "1024"]

        def _write():
            clip.write_videofile(out_path, fps=TARGET_FPS, codec="libx264", bitrate=q["bitrate"], audio_codec="aac", audio_bitrate=AUDIO_BR, ffmpeg_params=ffmpeg_extra, logger=None)
        await asyncio.to_thread(_write)
        return True
    except asyncio.CancelledError: raise
    except Exception as e:
        LOGGER.error(f"❌ Render chapter {chapter_idx} gagal: {e}", exc_info=True)
        return False
    finally:
        for obj in [clip, raw, vo]:
            if obj is not None:
                try: obj.close()
                except: pass
        _cleanup(tts_path)

async def _merge_chapters_ffmpeg(chapter_files: list[str], out_path: str, quality: str) -> float:
    q = QUALITY_PRESETS.get(quality, QUALITY_PRESETS["balanced"])
    concat_txt = _tmp(f"concat_{int(time.time())}.txt")
    try:
        with open(concat_txt, "w", encoding="utf-8") as f:
            for path in chapter_files: f.write(f"file '{os.path.abspath(path)}'\n")
        cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_txt, "-c:v", "libx264", "-preset", q["preset"], "-b:v", q["bitrate"], "-c:a", "aac", "-b:a", AUDIO_BR, "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-max_muxing_queue_size", "1024", out_path]
        proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        _, stderr = await proc.communicate()
        if proc.returncode != 0: raise RuntimeError(f"FFmpeg merge gagal: {stderr.decode(errors='replace')[-300:]}")
        dur = 0.0
        if os.path.exists(out_path):
            try: vc = VideoFileClip(out_path); dur = vc.duration; vc.close()
            except: pass
        return dur
    finally: _cleanup(concat_txt)

async def _auto_recap(movie_path: str, target_min: float, quality: str, out_path: str, process_status: ProcessStatus, status_msg: Message) -> float:
    target_sec, seg_dur, div_gap = target_min * 60.0, max(8.0, min(20.0, target_min * 60.0 / 40)), 45.0
    process_status.update_process_message(f"⏳ 🤖 **AI Vision menganalisis film...**\nTarget: `{target_min:.0f} menit`\nAnalisis `{seg_dur:.0f}s`\n`/cancel{CMD_SUFFIX} process {process_status.process_id}`")
    await _safe_edit(status_msg, process_status.status_message)
    process_status.ping = time.time()

    segments = await asyncio.to_thread(sample_best_segments, movie_path, target_sec, seg_dur, 3.0, div_gap)
    if not segments: raise RuntimeError("AI Vision tidak menemukan segmen yang cukup baik.")
    n_segs, tot_time = len(segments), sum(e - s for s, e in segments)

    process_status.update_process_message(f"⏳ ✂️ **Memotong & menggabungkan {n_segs} momen...**\nTotal: `{get_readable_time(tot_time)}`\n`/cancel{CMD_SUFFIX} process {process_status.process_id}`")
    await _safe_edit(status_msg, process_status.status_message)

    def _build():
        try: from bot.Gameplay import build_movies_sync; return build_movies_sync(movie_path, segments, out_path)
        except Exception: return 0.0
    dur = await asyncio.to_thread(_build)
    if dur == 0.0: dur = await _merge_chapters_ffmpeg_segments(movie_path, segments, out_path, quality)
    return dur

async def _merge_chapters_ffmpeg_segments(movie_path: str, segments: list[tuple], out_path: str, quality: str) -> float:
    concat_txt, temp_segs = _tmp(f"segs_{int(time.time())}.txt"), []
    try:
        for i, (start, end) in enumerate(segments):
            seg_out = _tmp(f"seg_{i}_{int(time.time())}.mp4")
            cmd = ["ffmpeg", "-y", "-ss", str(start), "-to", str(end), "-i", movie_path, "-c:v", "libx264", "-preset", "fast", "-c:a", "aac", "-pix_fmt", "yuv420p", seg_out]
            proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
            await proc.communicate()
            if os.path.exists(seg_out): temp_segs.append(seg_out)
        with open(concat_txt, "w") as f:
            for p in temp_segs: f.write(f"file '{os.path.abspath(p)}'\n")
        cmd2 = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_txt, "-c", "copy", out_path]
        proc2 = await asyncio.create_subprocess_exec(*cmd2, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        await proc2.communicate()
        dur = 0.0
        if os.path.exists(out_path):
            try: vc = VideoFileClip(out_path); dur = vc.duration; vc.close()
            except: pass
        return dur
    finally: _cleanup(concat_txt, *temp_segs)

async def _recap_worker(process_status: ProcessStatus, original_message: Message, reply_msg: Message, movie_title: str, mode: str, target_min: float, quality: str, narasi_on: bool, yt_enabled: bool, yt_privacy: str, status_msg: Message) -> None:
    txt_path, chapter_files, render_start = None, [], time.time()
    try:
        movie_path = _find_movie(movie_title)
        if not movie_path: raise RuntimeError(f"Film `{movie_title}` tidak ditemukan!")
        probe = VideoFileClip(movie_path); film_dur = probe.duration; film_res = f"{probe.w}×{probe.h}"; probe.close()
        
        if mode == "auto":
            process_status.update_process_message(f"⏳ 🤖 **Mode AUTO — AI Vision**\n🎬 Film: `{movie_title}`\n`/cancel{CMD_SUFFIX} process {process_status.process_id}`")
            await _safe_edit(status_msg, process_status.status_message)
            out_file = _tmp(f"recap_auto_{process_status.process_id}.mp4")
            vid_dur  = await _auto_recap(movie_path, target_min, quality, out_file, process_status, status_msg)
            if not os.path.exists(out_file) or os.path.getsize(out_file) == 0: raise RuntimeError("Output tidak valid.")
            await _finish_and_send(process_status, original_message, movie_title, out_file, vid_dur, mode, quality, yt_enabled, yt_privacy, status_msg, render_start)
            return

        if mode == "chapter":
            if not reply_msg or not reply_msg.document: raise RuntimeError("Mode CHAPTER butuh file .txt")
            txt_path = _tmp(f"recap_{process_status.process_id}.txt")
            process_status.update_process_message(f"⏳ 📥 **Mengunduh naskah chapter...**\n🎬 `{movie_title}`")
            await _safe_edit(status_msg, process_status.status_message)
            await Telegram.AIOGRAM_BOT.download(reply_msg.document, destination=txt_path)
            if not os.path.exists(txt_path): raise RuntimeError("Gagal download file .txt")
            scenes = parse_recap_txt(txt_path); total = len(scenes); _cleanup(txt_path); txt_path = None

            for idx, scene in enumerate(scenes, 1):
                if not check_running_process(process_status.process_id): raise asyncio.CancelledError("Dibatalkan")
                start_t = scene["start"]; narr = scene["narration"]; out_ch = _tmp(f"ch_{process_status.process_id}_{idx:03d}.mp4")
                elapsed = time.time() - render_start; eta_secs = (elapsed / idx * (total - idx + 1)) if idx > 1 else 0
                process_status.update_process_message(f"⏳ 🎙️ **Merender Chapter [{idx}/{total}]**\n`{narr[:50]}...`\n{get_progress_bar_string(idx-1, total)} {(idx-1)*100//total}%\nETA: `{get_readable_time(eta_secs)}`")
                await _safe_edit(status_msg, process_status.status_message)
                process_status.ping = time.time()
                ok = await _render_chapter(movie_path, start_t, narr, out_ch, quality, idx, total, process_status)
                if ok and os.path.exists(out_ch): chapter_files.append(out_ch)

            if not chapter_files: raise RuntimeError("Semua chapter gagal.")
            process_status.update_process_message(f"⏳ 🔄 **Menggabungkan {len(chapter_files)} chapter...**\n`/cancel{CMD_SUFFIX} process {process_status.process_id}`")
            await _safe_edit(status_msg, process_status.status_message)
            merged_path = _tmp(f"recap_merged_{process_status.process_id}.mp4")
            vid_dur = await _merge_chapters_ffmpeg(chapter_files, merged_path, quality)
            if not os.path.exists(merged_path) or os.path.getsize(merged_path) == 0: raise RuntimeError("Merge gagal.")
            await _finish_and_send(process_status, original_message, movie_title, merged_path, vid_dur, mode, quality, yt_enabled, yt_privacy, status_msg, render_start)

    except asyncio.CancelledError: await _safe_edit(status_msg, "🚫 **Movie Recap Dibatalkan.**")
    except Exception as e:
        LOGGER.error(f"MovieRecap error: {e}", exc_info=True)
        await _safe_edit(status_msg, f"❌ **Error:**\n`{str(e)[:400]}`")
    finally:
        if txt_path: _cleanup(txt_path)
        for f in chapter_files: _cleanup(f)
        await remove_running_process(process_status.process_id)
        async with working_task_lock:
            for task in list(working_task):
                ps = task.get("process_status")
                if ps and ps.process_id == process_status.process_id:
                    working_task.remove(task); break

async def _finish_and_send(process_status, original_message, movie_title, out_file, vid_dur, mode, quality, yt_enabled, yt_privacy, status_msg, render_start) -> None:
    try:
        elapsed = time.time() - render_start; file_size = os.path.getsize(out_file)
        mode_icon = "🤖 Auto AI" if mode == "auto" else "📝 Chapter"
        try: vc = VideoFileClip(out_file); vdur = int(vc.duration); vw, vh = vc.size; vc.close()
        except Exception: vdur, vw, vh = int(vid_dur), TARGET_W, TARGET_H
        caption = f"🎬 **MOVIE RECAP — {movie_title.upper()}**\n**Mode:** `{mode_icon}`\n**Durasi:** `{get_readable_time(vid_dur)}`\n**Quality:** `{QUALITY_PRESETS[quality]['label']}`\n**Render:** `{get_readable_time(elapsed)}`"
        process_status.update_process_message(f"⏳ ⬆️ **Mengirim ke Telegram...**\n`{movie_title}` · `{get_human_size(file_size)}`")
        await _safe_edit(status_msg, process_status.status_message)
        yt_buttons = None
        if YOUTUBE_ENABLED and _HAS_YTUPLOAD:
            yt_buttons = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬆️ Upload YouTube", callback_data=f"recap_yt_{process_status.user_id}_{process_status.process_id}", style="success")]])
        try:
            await Telegram.AIOGRAM_BOT.send_video(chat_id=original_message.chat.id, video=FSInputFile(out_file), caption=caption, supports_streaming=True, width=vw, height=vh, duration=vdur, reply_to_message_id=original_message.message_id, reply_markup=yt_buttons)
        except Exception as e:
            await original_message.answer(f"❌ Gagal kirim video: `{e}`"); return
        
        if yt_enabled and YOUTUBE_ENABLED and _HAS_YTUPLOAD:
            yt_title = f"Movie Recap — {movie_title}"; yt_desc  = f"Rangkuman film: {movie_title}\nMode: {mode_icon}\nDibuat oleh Studio Khoirul Bot"
            process_status.update_process_message(f"⏳ ⬆️ **Upload ke YouTube...**\n`{yt_title}`\n🔒 `{yt_privacy}`")
            await _safe_edit(status_msg, process_status.status_message)
            try:
                yt_link = await upload_to_youtube(out_file, yt_title, yt_desc, yt_privacy, process_status, status_msg)
                await original_message.answer(f"📺 **YouTube:** [Tonton ↗]({yt_link})", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📺 Buka di YouTube", url=yt_link, style="success")]]))
            except Exception as e: await original_message.answer(f"⚠️ YouTube upload gagal: `{e}`")
        await _safe_edit(status_msg, f"✅ **Movie Recap Selesai!**\n🎬 **Film:** `{movie_title}`\n**Durasi:** `{get_readable_time(vid_dur)}`")
    finally: _cleanup(out_file)

async def _start_recap_task(process_status, original_message, reply_msg, movie_title, mode, target_min, quality, narasi_on, yt_enabled, yt_privacy, status_msg) -> None:
    task_wrapper = {"process_status": process_status, "functions": [], "_movierecap": True}; queued = False
    async with working_task_lock:
        if len(working_task) < get_task_limit():
            working_task.append(task_wrapper); await append_running_process(process_status.process_id)
        else: queued = True
    if queued:
        async with queued_task_lock: pos = len(queued_task) + 1; queued_task.append(task_wrapper)
        await _safe_edit(status_msg, f"⏳ **Masuk Antrian Movie Recap**\n📋 **Posisi:** `{pos}`\n🎬 **Film:** `{movie_title}`")
        waited = 0
        while waited < QUEUE_TIMEOUT:
            await asyncio.sleep(5); waited += 5
            async with queued_task_lock:
                if task_wrapper not in queued_task: break
        else:
            async with queued_task_lock:
                if task_wrapper in queued_task: queued_task.remove(task_wrapper)
            await _safe_edit(status_msg, "❌ **Timeout antrian (2 jam).** Coba lagi.")
            return
        if not check_running_process(process_status.process_id): return
    await _recap_worker(process_status, original_message, reply_msg, movie_title, mode, target_min, quality, narasi_on, yt_enabled, yt_privacy, status_msg)


# ═══════════════════════════════════════════════════════════════════════
#  MASTER COMMAND HANDLER (WIZARD UI)
# ═══════════════════════════════════════════════════════════════════════

@router.message(Command(f"recap{CMD_SUFFIX}"))
async def recap_handler(message: Message, command: CommandObject) -> None:
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    movie_title = (command.args or "").strip()
    reply_msg = message.reply_to_message
    has_txt = False
    
    if reply_msg and reply_msg.document:
        fname = reply_msg.document.file_name or ""
        if fname.lower().endswith(".txt") or "text" in (reply_msg.document.mime_type or ""):
            has_txt = True
            if not movie_title: movie_title = fname.rsplit(".", 1)[0].strip() or ""
            
    if not movie_title:
        avail = _list_movies()
        av_text = "\n".join(f"• `{m}`" for m in avail[:8]) if avail else "_Belum ada film lokal._"
        return await message.reply(f"❌ **Sebutkan nama film!**\nFormat: `/recap{CMD_SUFFIX} NamaFilm`\n**Film tersedia:**\n{av_text}")
        
    await ensure_user_data_structure(user_id)
    
    # ── WIZARD STEP 1: MODE ──
    kb_mode = _make_reply_kb(["🤖 Auto AI", "📝 Chapter", "❌ Batal"], 2)
    msg_mode = await message.reply("🤖 **Pilih Mode Recap:**", reply_markup=kb_mode)
    resp_mode = await wait_for_message(chat_id, user_id, 60)
    await _clean_msgs(msg_mode, resp_mode)
    
    if not resp_mode or "batal" in (resp_mode.text or "").lower():
        return await message.answer("❌ Dibatalkan.", reply_markup=ReplyKeyboardRemove())
        
    mode = "chapter" if "chapter" in (resp_mode.text or "").lower() else "auto"
    
    if mode == "chapter" and not has_txt:
        return await message.answer("❌ Mode CHAPTER butuh file .txt yang dibalas (reply). Dibatalkan.", reply_markup=ReplyKeyboardRemove())

    # ── WIZARD STEP 2: DURATION ──
    kb_dur = _make_reply_kb(["5 Menit", "10 Menit", "15 Menit", "Kustom", "❌ Batal"], 3)
    msg_dur = await message.reply("⏱️ **Pilih Target Durasi:**", reply_markup=kb_dur)
    resp_dur = await wait_for_message(chat_id, user_id, 60)
    await _clean_msgs(msg_dur, resp_dur)
    
    txt_dur = (resp_dur.text or "").lower()
    if not resp_dur or "batal" in txt_dur:
        return await message.answer("❌ Dibatalkan.", reply_markup=ReplyKeyboardRemove())
        
    target_min = 10.0
    if "kustom" in txt_dur:
        msg_cust = await message.reply("Ketik target durasi (dalam menit, contoh: `12`):", reply_markup=ReplyKeyboardRemove())
        resp_cust = await wait_for_message(chat_id, user_id, 60)
        await _clean_msgs(msg_cust, resp_cust)
        if not resp_cust or "batal" in (resp_cust.text or "").lower():
            return await message.answer("❌ Dibatalkan.", reply_markup=ReplyKeyboardRemove())
        try: target_min = float(resp_cust.text.strip())
        except: return await message.answer("❌ Input tidak valid. Dibatalkan.", reply_markup=ReplyKeyboardRemove())
    else:
        try: target_min = float(re.sub(r'[^\d.]', '', txt_dur))
        except: target_min = 10.0

    # ── WIZARD STEP 3: QUALITY ──
    kb_qual = _make_reply_kb(["⚡ Cepat", "⚖️ Seimbang", "💎 HQ", "❌ Batal"], 3)
    msg_qual = await message.reply("⚙️ **Pilih Kualitas Render:**", reply_markup=kb_qual)
    resp_qual = await wait_for_message(chat_id, user_id, 60)
    await _clean_msgs(msg_qual, resp_qual)
    
    txt_qual = (resp_qual.text or "").lower()
    if not resp_qual or "batal" in txt_qual: 
        return await message.answer("❌ Dibatalkan.", reply_markup=ReplyKeyboardRemove())
    quality = "fast" if "cepat" in txt_qual else "hq" if "hq" in txt_qual else "balanced"

    # ── WIZARD STEP 4: NARRATION (Chapter Only) ──
    narasi_on = True
    if mode == "chapter":
        kb_nar = _make_reply_kb(["✅ Aktif", "🔇 Tanpa Narasi", "❌ Batal"], 2)
        msg_nar = await message.reply("🎙️ **Gunakan Voiceover (Narasi AI)?**", reply_markup=kb_nar)
        resp_nar = await wait_for_message(chat_id, user_id, 60)
        await _clean_msgs(msg_nar, resp_nar)
        
        txt_nar = (resp_nar.text or "").lower()
        if not resp_nar or "batal" in txt_nar: 
            return await message.answer("❌ Dibatalkan.", reply_markup=ReplyKeyboardRemove())
        narasi_on = "aktif" in txt_nar

    # ── WIZARD STEP 5: YOUTUBE ──
    yt_enabled, yt_privacy = False, "private"
    if YOUTUBE_ENABLED and _HAS_YTUPLOAD:
        kb_yt = _make_reply_kb(["⏭️ Skip", "🌍 Public", "🔗 Unlisted", "🔒 Private", "❌ Batal"], 3)
        msg_yt = await message.reply("📺 **Upload ke YouTube Otomatis?**", reply_markup=kb_yt)
        resp_yt = await wait_for_message(chat_id, user_id, 60)
        await _clean_msgs(msg_yt, resp_yt)
        
        txt_yt = (resp_yt.text or "").lower()
        if not resp_yt or "batal" in txt_yt: 
            return await message.answer("❌ Dibatalkan.", reply_markup=ReplyKeyboardRemove())
        yt_enabled = "skip" not in txt_yt
        if yt_enabled:
            yt_privacy = "public" if "public" in txt_yt else "unlisted" if "unlisted" in txt_yt else "private"

    # ── WIZARD STEP 6: CONFIRMATION ──
    kb_conf = _make_reply_kb(["✅ Mulai Recap", "❌ Batal"], 2)
    conf_txt = (
        f"**🎬 KONFIRMASI MOVIE RECAP**\n\n"
        f"🎞️ **Film:** `{movie_title}`\n"
        f"🤖 **Mode:** `{'Auto AI Vision' if mode=='auto' else 'Chapter + Narasi'}`\n"
        f"⏱️ **Durasi:** `{int(target_min)} menit`\n"
        f"⚙️ **Quality:** `{QUALITY_PRESETS[quality]['label']}`\n"
        f"🎙️ **Narasi:** `{'Aktif' if narasi_on else 'Nonaktif'}`\n"
        f"📺 **YouTube:** `{'✅ Upload ('+yt_privacy.capitalize()+')' if yt_enabled else '⏭️ Skip'}`\n\n"
        "Lanjutkan?"
    )
    msg_conf = await message.reply(conf_txt, reply_markup=kb_conf)
    resp_conf = await wait_for_message(chat_id, user_id, 60)
    await _clean_msgs(msg_conf, resp_conf)
    
    if not resp_conf or "batal" in (resp_conf.text or "").lower():
        return await message.answer("❌ Dibatalkan.", reply_markup=ReplyKeyboardRemove())

    # [NEW v4.2] MESIN KASIR: POTONG SALDO POIN
    await message.answer("🔄 Mengecek Saldo Poin...", reply_markup=ReplyKeyboardRemove())
    payment = await process_payment(user_id=user_id, command="recap")
    if not payment["success"]:
        return await message.answer(payment["message"], reply_markup=ReplyKeyboardRemove())
        
    await message.answer(f"⏳ ✅ Menyiapkan Mesin Recap...\n{payment['message']}", reply_markup=ReplyKeyboardRemove())

    user_name = message.from_user.username or ""
    user_first_name = message.from_user.first_name or str(user_id)
    ps = ProcessStatus(user_id, chat_id, user_name, user_first_name, message, getattr(Names, "movierecap", "MovieRecap"), "Telegram")
    ps.file_name = f"{movie_title}_recap"
    
    init_text  = f"🎬 **Movie Recap Dimulai**\n{'─'*32}\n  🎞️ Film    `{movie_title}`\n  🤖 Mode      `{'Auto AI Vision' if mode=='auto' else 'Chapter + Narasi'}`\n  ⏱️ Durasi    `{int(target_min)} menit`\n{'─'*32}\n**ID:** `{ps.process_id}`\n`/cancel{CMD_SUFFIX} process {ps.process_id}`"
    cancel_btn = [[InlineKeyboardButton(text="❌ Batal", callback_data=f"rc_cancel_{user_id}_{ps.process_id}", style="danger")]]
    
    status_msg = await message.answer(init_text, reply_markup=InlineKeyboardMarkup(inline_keyboard=cancel_btn))
    
    asyncio.create_task(_start_recap_task(
        ps, message, reply_msg, movie_title, mode, target_min, quality, narasi_on, yt_enabled, yt_privacy, status_msg
    ))


@router.callback_query(F.data.startswith("rc_cancel_"))
async def rc_cancel_cb(call: CallbackQuery):
    await call.answer("⏳ 🚫 Membatalkan...", show_alert=False)
    parts = call.data.split("_")
    uid = int(parts[2])
    
    if call.from_user.id != uid: 
        return await call.answer("❌ Bukan milikmu!", show_alert=True)
        
    if len(parts) >= 4: 
        await remove_running_process(parts[3])
        
    await _safe_edit(call.message, "❌ **Movie Recap dibatalkan.**")
