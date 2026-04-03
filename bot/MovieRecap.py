"""
╔══════════════════════════════════════════════════════════════════════╗
║                    bot/MovieRecap.py — v3.1                          ║
║       Movie Recap: Rangkuman Film Otomatis dengan Voiceover AI       ║
╠══════════════════════════════════════════════════════════════════════╣
║  CHANGELOG: Migrasi total ke Aiogram 3.x Router & Message objects    ║
╚══════════════════════════════════════════════════════════════════════╝
"""

import asyncio, os, re, subprocess, time
from datetime import datetime
from typing import Optional

from moviepy import (AudioFileClip, CompositeAudioClip, CompositeVideoClip, VideoFileClip, ColorClip, ImageClip, concatenate_videoclips)
from moviepy.video.fx import FadeIn, FadeOut
import edge_tts

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
from aiogram.filters import Command, CommandObject
from aiogram.exceptions import TelegramBadRequest

from bot_helper.Database.User_Data import get_data, ensure_user_data_structure, get_task_limit
from bot_helper.Others.Helper_Functions import get_human_size, get_readable_time
from bot_helper.Others.Names import Names
from bot_helper.Process.Process_Status import ProcessStatus, get_progress_bar_string
from bot_helper.Process.Running_Process import append_running_process, check_running_process, remove_running_process
from bot_helper.Process.Running_Tasks import working_task, working_task_lock, queued_task, queued_task_lock
from bot_helper.Telegram.Telegram_Client import Telegram
from config.config import Config

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
ORIG_AUDIO_VOL, _recap_state = 0.10, {}
os.makedirs(TEMP_DIR, exist_ok=True)

def _is_vip(user_id: int) -> bool:
    if user_id == Config.OWNER_ID or user_id in Config.SUDO_USERS: return True
    expiry_str = get_data().get(user_id, {}).get("premium_expiry_date")
    if not expiry_str: return False
    try: return datetime.now(datetime.fromisoformat(str(expiry_str)).tzinfo) < datetime.fromisoformat(str(expiry_str))
    except Exception: return False

def _vip_expiry_text(user_id: int) -> str:
    if user_id == Config.OWNER_ID or user_id in Config.SUDO_USERS: return "♾️ Unlimited (Owner/Sudo)"
    expiry_str = get_data().get(user_id, {}).get("premium_expiry_date")
    if not expiry_str: return "❌ Tidak aktif"
    try:
        expiry = datetime.fromisoformat(str(expiry_str)); now = datetime.now(expiry.tzinfo)
        if now >= expiry: return "❌ Sudah kadaluarsa"
        return f"✅ Aktif — sisa {(expiry - now).days} hari"
    except Exception: return "❓ Tidak diketahui"

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
    process_status.update_process_message(f"🤖 **AI Vision menganalisis film...**\nTarget: `{target_min:.0f} menit`\nAnalisis `{seg_dur:.0f}s`\n`/cancel{CMD_SUFFIX} process {process_status.process_id}`")
    await _safe_edit(status_msg, process_status.status_message)
    process_status.ping = time.time()

    segments = await asyncio.to_thread(sample_best_segments, movie_path, target_sec, seg_dur, 3.0, div_gap)
    if not segments: raise RuntimeError("AI Vision tidak menemukan segmen yang cukup baik.")
    n_segs, tot_time = len(segments), sum(e - s for s, e in segments)

    process_status.update_process_message(f"✂️ **Memotong & menggabungkan {n_segs} momen...**\nTotal: `{get_readable_time(tot_time)}`\n`/cancel{CMD_SUFFIX} process {process_status.process_id}`")
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
            process_status.update_process_message(f"🤖 **Mode AUTO — AI Vision**\n🎬 Film: `{movie_title}`\n`/cancel{CMD_SUFFIX} process {process_status.process_id}`")
            await _safe_edit(status_msg, process_status.status_message)
            out_file = _tmp(f"recap_auto_{process_status.process_id}.mp4")
            vid_dur  = await _auto_recap(movie_path, target_min, quality, out_file, process_status, status_msg)
            if not os.path.exists(out_file) or os.path.getsize(out_file) == 0: raise RuntimeError("Output tidak valid.")
            await _finish_and_send(process_status, original_message, movie_title, out_file, vid_dur, mode, quality, yt_enabled, yt_privacy, status_msg, render_start)
            return

        if mode == "chapter":
            if not reply_msg or not reply_msg.document: raise RuntimeError("Mode CHAPTER butuh file .txt")
            txt_path = _tmp(f"recap_{process_status.process_id}.txt")
            process_status.update_process_message(f"📥 **Mengunduh naskah chapter...**\n🎬 `{movie_title}`")
            await _safe_edit(status_msg, process_status.status_message)
            await Telegram.AIOGRAM_BOT.download(reply_msg.document, destination=txt_path)
            if not os.path.exists(txt_path): raise RuntimeError("Gagal download file .txt")
            scenes = parse_recap_txt(txt_path); total = len(scenes); _cleanup(txt_path); txt_path = None

            for idx, scene in enumerate(scenes, 1):
                if not check_running_process(process_status.process_id): raise asyncio.CancelledError("Dibatalkan")
                start_t = scene["start"]; narr = scene["narration"]; out_ch = _tmp(f"ch_{process_status.process_id}_{idx:03d}.mp4")
                elapsed = time.time() - render_start; eta_secs = (elapsed / idx * (total - idx + 1)) if idx > 1 else 0
                process_status.update_process_message(f"🎙️ **Merender Chapter [{idx}/{total}]**\n`{narr[:50]}...`\n{get_progress_bar_string(idx-1, total)} {(idx-1)*100//total}%\nETA: `{get_readable_time(eta_secs)}`")
                await _safe_edit(status_msg, process_status.status_message)
                process_status.ping = time.time()
                ok = await _render_chapter(movie_path, start_t, narr, out_ch, quality, idx, total, process_status)
                if ok and os.path.exists(out_ch): chapter_files.append(out_ch)

            if not chapter_files: raise RuntimeError("Semua chapter gagal.")
            process_status.update_process_message(f"🔄 **Menggabungkan {len(chapter_files)} chapter...**\n`/cancel{CMD_SUFFIX} process {process_status.process_id}`")
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
        _recap_state.pop(process_status.user_id, None)
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
        process_status.update_process_message(f"⬆️ **Mengirim ke Telegram...**\n`{movie_title}` · `{get_human_size(file_size)}`")
        await _safe_edit(status_msg, process_status.status_message)
        yt_buttons = None
        if YOUTUBE_ENABLED and _HAS_YTUPLOAD:
            yt_buttons = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬆️ Upload YouTube", callback_data=f"recap_yt_{process_status.user_id}_{process_status.process_id}")]])
        try:
            await Telegram.AIOGRAM_BOT.send_video(chat_id=original_message.chat.id, video=FSInputFile(out_file), caption=caption, supports_streaming=True, width=vw, height=vh, duration=vdur, reply_to_message_id=original_message.message_id, reply_markup=yt_buttons)
        except Exception as e:
            await original_message.answer(f"❌ Gagal kirim video: `{e}`"); return
        
        if yt_enabled and YOUTUBE_ENABLED and _HAS_YTUPLOAD:
            yt_title = f"Movie Recap — {movie_title}"; yt_desc  = f"Rangkuman film: {movie_title}\nMode: {mode_icon}\nDibuat oleh Studio Khoirul Bot"
            process_status.update_process_message(f"⬆️ **Upload ke YouTube...**\n`{yt_title}`\n🔒 `{yt_privacy}`")
            await _safe_edit(status_msg, process_status.status_message)
            try:
                yt_link = await upload_to_youtube(out_file, yt_title, yt_desc, yt_privacy, process_status, status_msg)
                await original_message.answer(f"📺 **YouTube:** [Tonton ↗]({yt_link})", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📺 Buka di YouTube", url=yt_link)]]))
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
            _recap_state.pop(process_status.user_id, None)
            return
        if not check_running_process(process_status.process_id):
            _recap_state.pop(process_status.user_id, None); return
    await _recap_worker(process_status, original_message, reply_msg, movie_title, mode, target_min, quality, narasi_on, yt_enabled, yt_privacy, status_msg)

def _build_dashboard(user_id, movie_title, mode, target_min, quality, narasi_on, yt_enabled, yt_privacy) -> tuple[str, list]:
    dash = f"🎬 **Movie Recap — Konfirmasi**\n{'─'*32}\n  🎞️ Film      `{movie_title}`\n  🤖 Mode      `{'Auto AI Vision' if mode=='auto' else 'Chapter + Narasi'}`\n  ⏱️ Durasi    `{int(target_min)} menit`\n  ⚙️ Quality   `{QUALITY_PRESETS[quality]['label']}`\n  🎙️ Narasi    `{'Aktif' if narasi_on else 'Nonaktif'}`\n  📺 YouTube   `{'✅ Upload ('+yt_privacy+')' if yt_enabled else '❌ Skip'}`\n{'─'*32}\n_Sesuaikan pengaturan lalu tekan ▶️ Mulai_"
    def _btn(lbl, cb): return InlineKeyboardButton(text=lbl, callback_data=cb)
    buttons = [
        [_btn(f"{'✅ ' if mode=='auto' else ''}🤖 Auto AI", f"rc_mode_{user_id}_auto"), _btn(f"{'✅ ' if mode=='chapter' else ''}📝 Chapter", f"rc_mode_{user_id}_chapter")],
        [_btn(f"{'✅ ' if target_min==m else ''}{m}m", f"rc_dur_{user_id}_{m}") for m in [5, 10, 12, 15]],
        [_btn(f"{'✅ ' if quality==q else ''}{lbl}", f"rc_qual_{user_id}_{q}") for q, lbl in zip(["fast", "balanced", "hq"], ["⚡ Cepat", "⚖️ Seimbang", "💎 HQ"])]
    ]
    if mode == "chapter": buttons.append([_btn("✅ Narasi Aktif" if narasi_on else "🔇 Tanpa Narasi", f"rc_narasi_{user_id}")])
    if YOUTUBE_ENABLED and _HAS_YTUPLOAD:
        buttons.append([_btn("✅ Upload YT" if yt_enabled else "☐ Upload YT", f"rc_yt_{user_id}")])
        if yt_enabled: buttons.append([_btn(f"{'✅ ' if yt_privacy==p else ''} {lbl}", f"rc_prv_{user_id}_{p}") for p, lbl in zip(["private","unlisted","public"], ["🔒 Private","🔗 Unlisted","🌍 Public"])])
    buttons.append([_btn("▶️ Mulai Recap", f"rc_go_{user_id}"), _btn("❌ Batal", f"rc_cancel_{user_id}")])
    return dash, buttons

@router.message(Command("recap"))
async def recap_handler(message: Message, command: CommandObject) -> None:
    user_id = message.from_user.id
    if not _is_vip(user_id): return await message.reply("👑 **Fitur Eksklusif VIP**\nHanya untuk member Premium.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="💬 Hubungi Admin", url=f"https://t.me/{Config.BOT_USERNAME}")]]))
    movie_title = (command.args or "").strip()
    reply_msg = message.reply_to_message; has_txt = False
    if reply_msg and reply_msg.document:
        fname = reply_msg.document.file_name or ""
        if fname.lower().endswith(".txt") or "text" in (reply_msg.document.mime_type or ""):
            has_txt = True
            if not movie_title: movie_title = fname.rsplit(".", 1)[0].strip() or ""
    if not movie_title:
        avail = _list_movies(); av_text = "\n".join(f"• `{m}`" for m in avail[:8]) if avail else "_Belum ada film_"
        return await message.reply(f"❌ **Sebutkan nama film!**\nFormat: `/recap{CMD_SUFFIX} NamaFilm`\n**Film tersedia:**\n{av_text}")
    await ensure_user_data_structure(user_id)
    default_mode = "chapter" if has_txt else "auto"
    _recap_state[user_id] = {"reply_msg": reply_msg if has_txt else None, "movie_title": movie_title, "mode": default_mode, "target_min": 10.0, "quality": "balanced", "narasi_on": True, "yt_enabled": False, "yt_privacy": "private"}
    dash, buttons = _build_dashboard(user_id, movie_title, default_mode, 10.0, "balanced", True, False, "private")
    await message.reply(dash, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

def _get_st(call, uid):
    if uid not in _recap_state: asyncio.create_task(call.answer("⚠️ Session expired.", show_alert=True)); return None
    return _recap_state[uid]

async def _reb(call, uid):
    st = _recap_state.get(uid)
    if st: dash, btns = _build_dashboard(uid, st["movie_title"], st["mode"], st["target_min"], st["quality"], st["narasi_on"], st["yt_enabled"], st["yt_privacy"]); await _safe_edit(call.message, dash, buttons=btns)

@router.callback_query(F.data.startswith("rc_mode_"))
async def rc_mode_cb(call: CallbackQuery):
    await call.answer(); uid = int(call.data.split("_")[2]); val = call.data.split("_")[3]
    if call.from_user.id != uid: return await call.answer("❌ Bukan milikmu!", show_alert=True)
    st = _get_st(call, uid)
    if st: st["mode"] = val; st["reply_msg"] = None if val == "auto" else st["reply_msg"]; await _reb(call, uid)

@router.callback_query(F.data.startswith("rc_dur_"))
async def rc_dur_cb(call: CallbackQuery):
    await call.answer(); uid = int(call.data.split("_")[2]); val = float(call.data.split("_")[3])
    if call.from_user.id != uid: return await call.answer("❌ Bukan milikmu!", show_alert=True)
    st = _get_st(call, uid)
    if st: st["target_min"] = val; await _reb(call, uid)

@router.callback_query(F.data.startswith("rc_qual_"))
async def rc_qual_cb(call: CallbackQuery):
    await call.answer(); uid = int(call.data.split("_")[2]); val = call.data.split("_")[3]
    if call.from_user.id != uid: return await call.answer("❌ Bukan milikmu!", show_alert=True)
    st = _get_st(call, uid)
    if st: st["quality"] = val; await _reb(call, uid)

@router.callback_query(F.data.startswith("rc_narasi_"))
async def rc_narasi_cb(call: CallbackQuery):
    await call.answer(); uid = int(call.data.split("_")[2])
    if call.from_user.id != uid: return await call.answer("❌ Bukan milikmu!", show_alert=True)
    st = _get_st(call, uid)
    if st: st["narasi_on"] = not st["narasi_on"]; await _reb(call, uid)

@router.callback_query(F.data.startswith("rc_yt_"))
async def rc_yt_cb(call: CallbackQuery):
    await call.answer(); uid = int(call.data.split("_")[2])
    if call.from_user.id != uid: return await call.answer("❌ Bukan milikmu!", show_alert=True)
    st = _get_st(call, uid)
    if st: st["yt_enabled"] = not st["yt_enabled"]; await _reb(call, uid)

@router.callback_query(F.data.startswith("rc_prv_"))
async def rc_prv_cb(call: CallbackQuery):
    await call.answer(); uid = int(call.data.split("_")[2]); val = call.data.split("_")[3]
    if call.from_user.id != uid: return await call.answer("❌ Bukan milikmu!", show_alert=True)
    st = _get_st(call, uid)
    if st: st["yt_privacy"] = val; await _reb(call, uid)

@router.callback_query(F.data.startswith("rc_cancel_"))
async def rc_cancel_cb(call: CallbackQuery):
    await call.answer("🚫 Membatalkan..."); parts = call.data.split("_"); uid = int(parts[2])
    if call.from_user.id != uid: return await call.answer("❌ Bukan milikmu!", show_alert=True)
    if len(parts) >= 4: await remove_running_process(parts[3])
    _recap_state.pop(uid, None); await _safe_edit(call.message, "❌ **Movie Recap dibatalkan.**")

@router.callback_query(F.data.startswith("rc_go_"))
async def rc_go_cb(call: CallbackQuery):
    await call.answer("⏳ Memulai..."); uid = int(call.data.split("_")[2])
    if call.from_user.id != uid: return await call.answer("❌ Bukan milikmu!", show_alert=True)
    if not _is_vip(uid): return await call.message.edit_text("❌ Akses VIP habis. Hubungi admin.")
    st = _recap_state.get(uid)
    if not st: return await call.message.edit_text("⚠️ Session expired.")
    if st["mode"] == "chapter" and st["reply_msg"] is None: return await call.message.edit_text("❌ **Mode CHAPTER membutuhkan file .txt!**")

    user_name = call.from_user.username or ""; user_first_name = call.from_user.first_name or str(uid)
    ps = ProcessStatus(uid, call.message.chat.id, user_name, user_first_name, call.message, getattr(Names, "movierecap", "MovieRecap"), "Telegram")
    ps.file_name = f"{st['movie_title']}_recap"
    init_text  = f"🎬 **Movie Recap Dimulai**\n{'─'*32}\n  🎞️ Film      `{st['movie_title']}`\n  🤖 Mode      `{'Auto AI Vision' if st['mode']=='auto' else 'Chapter + Narasi'}`\n  ⏱️ Durasi    `{int(st['target_min'])} menit`\n{'─'*32}\n**ID:** `{ps.process_id}`\n`/cancel{CMD_SUFFIX} process {ps.process_id}`"
    cancel_btn = [[InlineKeyboardButton(text="❌ Batalkan", callback_data=f"rc_cancel_{uid}_{ps.process_id}")]]
    try: status_msg = await call.message.edit_text(init_text, reply_markup=InlineKeyboardMarkup(inline_keyboard=cancel_btn))
    except: status_msg = await call.message.answer(init_text, reply_markup=InlineKeyboardMarkup(inline_keyboard=cancel_btn))
    asyncio.create_task(_start_recap_task(ps, call.message, st["reply_msg"], st["movie_title"], st["mode"], st["target_min"], st["quality"], st["narasi_on"], st["yt_enabled"], st["yt_privacy"], status_msg))
