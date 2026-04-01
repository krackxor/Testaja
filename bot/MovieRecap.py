"""
╔══════════════════════════════════════════════════════════════════════╗
║                    bot/MovieRecap.py — v3.1                          ║
║       Movie Recap: Rangkuman Film Otomatis dengan Voiceover AI       ║
╠══════════════════════════════════════════════════════════════════════╣
║  2 MODE UTAMA:                                                       ║
║  ─────────────                                                       ║
║  🤖 AUTO     — AI Vision pilih momen terbaik, narasi otomatis       ║
║               Tidak butuh file .txt                                  ║
║                                                                      ║
║  📝 CHAPTER  — User tulis naskah .txt, AI bacakan voiceover         ║
║               Format .txt:                                           ║
║               00:15:30 | Narasi yang akan dibacakan AI              ║
║               01:22:00 | Adegan selanjutnya...                      ║
║               # ini komentar, diabaikan                              ║
║                                                                      ║
║  ALUR KERJA:                                                         ║
║  1. /recap NamaFilm reply video/.txt → dashboard tombol             ║
║  2. Pilih mode, durasi, narasi, quality, privacy YT                 ║
║  3. Masuk QUEUE → download → AI analysis → render → upload          ║
║                                                                      ║
║  INTEGRASI PENUH:                                                    ║
║  ✅ ProcessStatus — tracking, ping, status_message                  ║
║  ✅ Queue system — working_task / queued_task                       ║
║  ✅ check_running_process() — cancel support                         ║
║  ✅ CMD_SUFFIX — semua command konsisten                            ║
║  ✅ VIP check + expiry date                                         ║
║  ✅ upload_to_youtube dari YTUpload.py (headless-safe)              ║
║  ✅ Full inline buttons — tidak ada conversation blocking           ║
║  ✅ Progress bar real-time per adegan                               ║
║  ✅ TTS voiceover per segmen (edge-tts)                             ║
╚══════════════════════════════════════════════════════════════════════╝
"""

# ── Standard Library ──────────────────────────────────────────────────
import asyncio
import os
import re
import subprocess
import time
from datetime import datetime
from typing import Optional

# ── MoviePy 2.x ───────────────────────────────────────────────────────
from moviepy import (
    AudioFileClip, CompositeAudioClip, CompositeVideoClip,
    VideoFileClip, ColorClip, ImageClip, concatenate_videoclips,
)
from moviepy.video.fx import FadeIn, FadeOut

# ── TTS ───────────────────────────────────────────────────────────────
import edge_tts

# ── Telethon ──────────────────────────────────────────────────────────
from telethon import events
from telethon.tl.custom import Button
from telethon.tl.types import DocumentAttributeVideo

# ── Internal — bot helper ─────────────────────────────────────────────
from bot_helper.Database.User_Data import get_data, ensure_user_data_structure, get_task_limit
from bot_helper.Others.Helper_Functions import get_human_size, get_readable_time
from bot_helper.Others.Names import Names
from bot_helper.Process.Process_Status import ProcessStatus, get_progress_bar_string
from bot_helper.Process.Running_Process import (
    append_running_process, check_running_process, remove_running_process,
)
from bot_helper.Process.Running_Tasks import (
    working_task, working_task_lock, queued_task, queued_task_lock,
)
from bot_helper.Telegram.Telegram_Client import Telegram
from config.config import Config

# ── YouTube (opsional) ────────────────────────────────────────────────
try:
    from bot.YTUpload import upload_to_youtube, YOUTUBE_ENABLED
    _HAS_YTUPLOAD = True
except ImportError:
    YOUTUBE_ENABLED = False
    _HAS_YTUPLOAD   = False

# ── Gameplay utilities (import hanya yang diperlukan) ─────────────────
try:
    from bot.Gameplay import (
        tmp as _gp_tmp,
        cleanup_temp as _gp_cleanup,
        find_gameplay_for_game,
        normalize_clip,
        normalize_landscape,
        score_frame,
        sample_best_segments,
        GAMEPLAY_DIR,
        TEMP_DIR as _GP_TEMP,
        TARGET_FPS, BITRATE, AUDIO_BR, FFMPEG_PARAMS, FFMPEG_LS,
        VOICE,
    )
    _HAS_GAMEPLAY = True
except ImportError:
    _HAS_GAMEPLAY   = False
    GAMEPLAY_DIR    = "./gameplay/"
    _GP_TEMP        = "./temp/"
    TARGET_FPS      = 30
    BITRATE         = "8000k"
    AUDIO_BR        = "192k"
    VOICE           = "en-US-AndrewNeural"
    FFMPEG_PARAMS   = ["-preset", "fast", "-pix_fmt", "yuv420p", "-movflags", "+faststart"]
    FFMPEG_LS       = FFMPEG_PARAMS

    def normalize_clip(clip, w=1920, h=1080, fps=30):
        if clip.fps != fps: clip = clip.with_fps(fps)
        src_r = clip.w/clip.h; tgt_r = w/h
        if src_r > tgt_r: nw, nh = int(clip.w*(h/clip.h)), h
        else:             nw, nh = w, int(clip.h*(w/clip.w))
        clip = clip.resized((nw, nh))
        x1, y1 = (nw-w)//2, (nh-h)//2
        return clip.cropped(x1=x1, y1=y1, x2=x1+w, y2=y1+h)

    def find_gameplay_for_game(title):
        return None

    def score_frame(frame):
        import cv2, numpy as np
        gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)
        return float(np.std(gray) / 128.0)

    def sample_best_segments(path, total=720, seg=15, step=3, gap=60):
        return []

LOGGER     = Config.LOGGER
CMD_SUFFIX = Config.CMD_SUFFIX

# ── Konstanta ─────────────────────────────────────────────────────────
TEMP_DIR        = "./temp/movierecap/"
TARGET_W        = 1920
TARGET_H        = 1080
QUEUE_TIMEOUT   = 7200   # 2 jam
MAX_CHAPTERS    = 30     # Maksimum chapter per .txt

# Quality presets
QUALITY_PRESETS = {
    "fast":     {"bitrate": "4000k", "preset": "ultrafast", "label": "⚡ Cepat"},
    "balanced": {"bitrate": "6000k", "preset": "fast",      "label": "⚖️ Seimbang"},
    "hq":       {"bitrate": "8000k", "preset": "slow",      "label": "💎 HQ"},
}

# Durasi recap (menit)
DURATION_OPTIONS = {
    "5":  {"min": 5,  "label": "5 menit"},
    "10": {"min": 10, "label": "10 menit"},
    "12": {"min": 12, "label": "12 menit"},
    "15": {"min": 15, "label": "15 menit"},
}

# Volume audio asli film (0.0 - 1.0)
ORIG_AUDIO_VOL = 0.10   # 10% volume asli, 100% voiceover

# State per-user sebelum konfirmasi
_recap_state: dict = {}

os.makedirs(TEMP_DIR, exist_ok=True)


# ═══════════════════════════════════════════════════════════════════════
#  VIP CHECK
# ═══════════════════════════════════════════════════════════════════════

def _is_vip(user_id: int) -> bool:
    if user_id == Config.OWNER_ID or user_id in Config.SUDO_USERS:
        return True
    user_data  = get_data().get(user_id, {})
    expiry_str = user_data.get("premium_expiry_date")
    if not expiry_str:
        return False
    try:
        expiry = datetime.fromisoformat(str(expiry_str))
        return datetime.now(expiry.tzinfo) < expiry
    except Exception:
        return False


def _vip_expiry_text(user_id: int) -> str:
    if user_id == Config.OWNER_ID or user_id in Config.SUDO_USERS:
        return "♾️ Unlimited (Owner/Sudo)"
    user_data  = get_data().get(user_id, {})
    expiry_str = user_data.get("premium_expiry_date")
    if not expiry_str:
        return "❌ Tidak aktif"
    try:
        expiry = datetime.fromisoformat(str(expiry_str))
        now    = datetime.now(expiry.tzinfo)
        if now >= expiry:
            return "❌ Sudah kadaluarsa"
        return f"✅ Aktif — sisa {(expiry - now).days} hari"
    except Exception:
        return "❓ Tidak diketahui"


# ═══════════════════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════════════════

async def _safe_edit(msg, text: str, buttons=None) -> None:
    try:
        await msg.edit(text, buttons=buttons)
    except Exception:
        pass


def _tmp(name: str) -> str:
    return os.path.join(TEMP_DIR, name)


def _cleanup(*paths: str) -> None:
    for p in paths:
        if p and os.path.exists(p):
            try:
                os.remove(p)
            except OSError:
                pass


def _time_to_sec(t_str: str) -> float:
    parts = [p.strip() for p in t_str.strip().split(":")]
    if len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    elif len(parts) == 2:
        return int(parts[0]) * 60 + float(parts[1])
    return float(parts[0])


def _find_movie(title: str) -> Optional[str]:
    """Cari file film di folder gameplay."""
    if _HAS_GAMEPLAY:
        return find_gameplay_for_game(title)
    # Fallback manual search
    search_dirs = [GAMEPLAY_DIR, "./videos/", "./movies/"]
    exts        = [".mp4", ".mkv", ".avi", ".mov"]
    for folder in search_dirs:
        if not os.path.isdir(folder):
            continue
        for f in os.listdir(folder):
            fl = f.lower()
            tl = title.lower().replace(" ", "_")
            if tl in fl or fl.startswith(tl):
                if any(fl.endswith(ext) for ext in exts):
                    return os.path.join(folder, f)
    return None


def _list_movies() -> list[str]:
    search_dirs = [GAMEPLAY_DIR, "./videos/", "./movies/"]
    exts        = [".mp4", ".mkv", ".avi", ".mov"]
    names       = []
    for folder in search_dirs:
        if not os.path.isdir(folder):
            continue
        for f in os.listdir(folder):
            if any(f.lower().endswith(ext) for ext in exts):
                names.append(os.path.splitext(f)[0])
    return sorted(set(names))


# ═══════════════════════════════════════════════════════════════════════
#  PARSER .TXT (MODE CHAPTER)
# ═══════════════════════════════════════════════════════════════════════

def parse_recap_txt(path: str) -> list[dict]:
    """
    Parse file .txt format: Timestamp | Narasi

    Format baris:
        00:15:30 | Narasi yang akan dibacakan AI
        01:22:00 | Adegan selanjutnya...
        # komentar diabaikan

    Returns list of dicts:
        {"start": float, "narration": str}
    """
    scenes = []
    errors = []

    with open(path, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()

    for i, raw in enumerate(lines, 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue

        parts = [x.strip() for x in line.split("|")]
        if len(parts) < 2:
            errors.append(f"Baris {i}: Format harus `Waktu | Narasi`")
            continue

        time_str  = parts[0]
        narration = "|".join(parts[1:]).strip()   # Narasi bisa mengandung |

        if not narration:
            errors.append(f"Baris {i}: Narasi kosong")
            continue

        try:
            start_t = _time_to_sec(time_str)
            scenes.append({"start": start_t, "narration": narration})
        except (ValueError, IndexError):
            errors.append(f"Baris {i}: Format waktu tidak valid — `{time_str}`")

    if errors:
        raise ValueError("❌ Format .txt salah:\n" + "\n".join(f"  • {e}" for e in errors))
    if not scenes:
        raise ValueError("❌ File .txt kosong atau tidak ada baris yang valid.")
    if len(scenes) > MAX_CHAPTERS:
        raise ValueError(f"❌ Terlalu banyak chapter ({len(scenes)}). Maksimum {MAX_CHAPTERS}.")

    # Urutkan berdasarkan timestamp
    scenes.sort(key=lambda x: x["start"])
    return scenes


# ═══════════════════════════════════════════════════════════════════════
#  TTS GENERATOR
# ═══════════════════════════════════════════════════════════════════════

async def _generate_tts(narration: str, out_path: str) -> Optional[str]:
    """
    Generate TTS audio dari narasi menggunakan edge-tts.
    Return path file audio, atau None jika gagal.
    """
    try:
        # Bersihkan teks dari karakter yang mungkin ganggu TTS
        clean = re.sub(r'[*_`#\[\](){}|>]', '', narration).strip()
        if not clean:
            clean = "Adegan berlanjut."

        await edge_tts.Communicate(clean, VOICE).save(out_path)

        if not os.path.exists(out_path) or os.path.getsize(out_path) < 512:
            LOGGER.warning(f"⚠️  TTS gagal atau file terlalu kecil: {out_path}")
            return None

        return out_path
    except Exception as e:
        LOGGER.error(f"❌ TTS error: {e}", exc_info=True)
        return None


# ═══════════════════════════════════════════════════════════════════════
#  RENDER FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════

async def _render_chapter(
    movie_path: str,
    start_t: float,
    narration: str,
    out_path: str,
    quality: str,
    chapter_idx: int,
    total_chapters: int,
    process_status: ProcessStatus,
) -> bool:
    """
    Render satu chapter:
    1. Generate TTS dari narasi
    2. Potong video sesuai durasi TTS
    3. Mix audio asli (10%) + voiceover (100%)
    4. Render ke file

    Return True jika sukses.
    """
    if not check_running_process(process_status.process_id):
        raise asyncio.CancelledError("Dibatalkan")

    tts_path = _tmp(f"tts_{process_status.process_id}_{chapter_idx}.mp3")
    q        = QUALITY_PRESETS.get(quality, QUALITY_PRESETS["balanced"])

    raw  = None
    clip = None
    vo   = None

    try:
        # ── TTS ───────────────────────────────────────────────────────
        tts_result = await _generate_tts(narration, tts_path)
        if not tts_result:
            LOGGER.warning(f"⚠️  TTS chapter {chapter_idx} gagal, skip")
            return False

        vo        = AudioFileClip(tts_path)
        vo_dur    = max(vo.duration, 1.5)

        # ── Potong video sesuai durasi TTS ────────────────────────────
        raw   = VideoFileClip(movie_path)
        end_t = min(start_t + vo_dur, raw.duration)

        if end_t <= start_t:
            LOGGER.warning(f"⚠️  Chapter {chapter_idx}: timestamp {start_t}s melebihi durasi film {raw.duration:.1f}s")
            return False

        clip = raw.subclip(start_t, end_t)

        # Normalisasi ke 1920x1080
        clip = normalize_clip(clip, TARGET_W, TARGET_H, TARGET_FPS)
        actual_dur = clip.duration

        # ── Mix audio asli + voiceover ────────────────────────────────
        if clip.audio is not None:
            # Audio asli dikecilkan, voiceover penuh
            orig_audio = clip.audio.with_volume_scaled(ORIG_AUDIO_VOL)
            # Potong voiceover jika lebih panjang dari clip
            if vo.duration > actual_dur:
                vo = vo.subclip(0, actual_dur)
            final_audio = CompositeAudioClip([orig_audio, vo])
        else:
            # Tidak ada audio asli — pakai voiceover saja
            if vo.duration > actual_dur:
                vo = vo.subclip(0, actual_dur)
            final_audio = vo

        clip = clip.with_audio(final_audio)

        # ── FadeIn/FadeOut per chapter ────────────────────────────────
        fade = min(0.4, actual_dur * 0.1)
        if chapter_idx > 1:
            clip = clip.with_effects([FadeIn(fade)])
        if chapter_idx < total_chapters:
            clip = clip.with_effects([FadeOut(fade)])

        # ── Render ────────────────────────────────────────────────────
        ffmpeg_extra = [
            "-preset", q["preset"],
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            "-max_muxing_queue_size", "1024",
        ]

        def _write():
            clip.write_videofile(
                out_path,
                fps=TARGET_FPS,
                codec="libx264",
                bitrate=q["bitrate"],
                audio_codec="aac",
                audio_bitrate=AUDIO_BR,
                ffmpeg_params=ffmpeg_extra,
                logger=None,
            )

        await asyncio.to_thread(_write)
        return True

    except asyncio.CancelledError:
        raise
    except Exception as e:
        LOGGER.error(f"❌ Render chapter {chapter_idx} gagal: {e}", exc_info=True)
        return False

    finally:
        # Tutup semua clip — tidak perlu gc.collect()
        for obj in [clip, raw, vo]:
            if obj is not None:
                try:
                    obj.close()
                except Exception:
                    pass
        _cleanup(tts_path)


async def _merge_chapters_ffmpeg(chapter_files: list[str], out_path: str, quality: str) -> float:
    """
    Gabungkan semua chapter menggunakan FFmpeg concat.
    Lebih stabil dan hemat RAM vs MoviePy concatenate untuk banyak file.

    Return: durasi video hasil merge (detik)
    """
    q          = QUALITY_PRESETS.get(quality, QUALITY_PRESETS["balanced"])
    concat_txt = _tmp(f"concat_{int(time.time())}.txt")

    try:
        # Tulis file list — gunakan urutan asli (tidak sort)
        with open(concat_txt, "w", encoding="utf-8") as f:
            for path in chapter_files:   # [FIX] tidak pakai sorted()
                f.write(f"file '{os.path.abspath(path)}'\n")

        # FFmpeg concat dengan re-encode untuk konsistensi
        # [FIX] Hapus -threads 1 — biarkan FFmpeg auto-detect
        cmd = [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0",
            "-i", concat_txt,
            "-c:v", "libx264",
            "-preset", q["preset"],
            "-b:v", q["bitrate"],
            "-c:a", "aac",
            "-b:a", AUDIO_BR,
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            "-max_muxing_queue_size", "1024",
            out_path,
        ]

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()

        if proc.returncode != 0:
            raise RuntimeError(
                f"FFmpeg merge gagal (code {proc.returncode}): "
                f"{stderr.decode(errors='replace')[-300:]}"
            )

        # Ambil durasi hasil merge
        dur = 0.0
        try:
            probe = VideoFileClip(out_path)
            dur   = probe.duration
            probe.close()
        except Exception:
            pass

        return dur

    finally:
        _cleanup(concat_txt)


async def _auto_recap(
    movie_path: str,
    target_min: float,
    quality: str,
    out_path: str,
    process_status: ProcessStatus,
    status_msg,
) -> float:
    """
    Mode AUTO: AI Vision pilih momen terbaik, tidak ada voiceover.
    Menggunakan sample_best_segments dari Gameplay.py.

    Return: durasi video hasil (detik)
    """
    target_sec = target_min * 60.0
    seg_dur    = max(8.0, min(20.0, target_sec / 40))
    div_gap    = 45.0

    process_status.update_process_message(
        f"🤖 **AI Vision menganalisis film...**\n\n"
        f"Target: `{target_min:.0f} menit`\n"
        f"Analisis setiap `{seg_dur:.0f}s` segmen\n"
        f"**Ditambahkan Oleh:** {process_status.added_by}\n"
        f"`/cancel{CMD_SUFFIX} process {process_status.process_id}`"
    )
    await _safe_edit(status_msg, process_status.status_message)
    process_status.ping = time.time()

    # Sample segmen terbaik
    segments = await asyncio.to_thread(
        sample_best_segments,
        movie_path, target_sec, seg_dur, 3.0, div_gap,
    )

    if not segments:
        raise RuntimeError("AI Vision tidak menemukan segmen yang cukup baik. Coba film yang lebih panjang.")

    n_segs   = len(segments)
    tot_time = sum(e - s for s, e in segments)
    LOGGER.info(f"AutoRecap: {n_segs} segmen ditemukan, total {tot_time:.0f}s")

    process_status.update_process_message(
        f"✂️ **Memotong & menggabungkan {n_segs} momen...**\n\n"
        f"Total durasi: `{get_readable_time(tot_time)}`\n"
        f"`/cancel{CMD_SUFFIX} process {process_status.process_id}`"
    )
    await _safe_edit(status_msg, process_status.status_message)

    # Build video menggunakan MoviePy
    def _build():
        from bot.Gameplay import build_movies_sync
        return build_movies_sync(movie_path, segments, out_path)

    try:
        dur = await asyncio.to_thread(_build)
    except (ImportError, AttributeError):
        # Fallback jika Gameplay.py tidak tersedia
        dur = await _merge_chapters_ffmpeg_segments(movie_path, segments, out_path, quality)

    return dur


async def _merge_chapters_ffmpeg_segments(
    movie_path: str,
    segments: list[tuple],
    out_path: str,
    quality: str,
) -> float:
    """Fallback merge segments via FFmpeg tanpa MoviePy."""
    q          = QUALITY_PRESETS.get(quality, QUALITY_PRESETS["balanced"])
    concat_txt = _tmp(f"segs_{int(time.time())}.txt")
    temp_segs  = []

    try:
        # Potong setiap segmen dulu
        for i, (start, end) in enumerate(segments):
            seg_out = _tmp(f"seg_{i}_{int(time.time())}.mp4")
            cmd     = [
                "ffmpeg", "-y",
                "-ss", str(start), "-to", str(end),
                "-i", movie_path,
                "-c:v", "libx264", "-preset", "fast",
                "-c:a", "aac", "-pix_fmt", "yuv420p",
                seg_out,
            ]
            proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
            await proc.communicate()
            if os.path.exists(seg_out):
                temp_segs.append(seg_out)

        # Concat semua segmen
        with open(concat_txt, "w") as f:
            for p in temp_segs:
                f.write(f"file '{os.path.abspath(p)}'\n")

        cmd2 = [
            "ffmpeg", "-y", "-f", "concat", "-safe", "0",
            "-i", concat_txt, "-c", "copy", out_path,
        ]
        proc2 = await asyncio.create_subprocess_exec(*cmd2, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        await proc2.communicate()

        dur = 0.0
        if os.path.exists(out_path):
            try:
                vc = VideoFileClip(out_path); dur = vc.duration; vc.close()
            except Exception:
                pass
        return dur

    finally:
        _cleanup(concat_txt, *temp_segs)


# ═══════════════════════════════════════════════════════════════════════
#  MAIN WORKER
# ═══════════════════════════════════════════════════════════════════════

async def _recap_worker(
    process_status: ProcessStatus,
    original_event,
    reply_msg,           # Bisa None jika mode=auto tanpa .txt
    movie_title: str,
    mode: str,           # "auto" | "chapter"
    target_min: float,
    quality: str,
    narasi_on: bool,     # True = voiceover aktif (mode chapter)
    yt_enabled: bool,
    yt_privacy: str,
    status_msg,
) -> None:
    """
    Worker utama MovieRecap.
    mode='auto'    → AI Vision tanpa .txt
    mode='chapter' → .txt dengan timestamp + narasi TTS
    """
    txt_path     = None
    chapter_files = []
    render_start = time.time()

    try:
        # ── STEP 1: Cari film sumber ──────────────────────────────────
        movie_path = _find_movie(movie_title)
        if not movie_path:
            avail    = _list_movies()
            av_lines = "\n".join(f"  • `{m}`" for m in avail[:8]) if avail else "  _Belum ada film_"
            raise RuntimeError(
                f"Film `{movie_title}` tidak ditemukan!\n\n"
                f"**Film tersedia:**\n{av_lines}\n\n"
                f"Upload via `/addgameplay{CMD_SUFFIX} NamaFilm`"
            )

        # Probe film
        probe    = VideoFileClip(movie_path)
        film_dur = probe.duration
        film_res = f"{probe.w}×{probe.h}"
        probe.close()

        LOGGER.info(f"MovieRecap: {movie_title} | {film_res} | {film_dur:.0f}s | mode={mode}")

        # ── MODE AUTO ─────────────────────────────────────────────────
        if mode == "auto":
            process_status.update_process_message(
                f"🤖 **Mode AUTO — AI Vision**\n\n"
                f"🎬 Film: `{movie_title}`\n"
                f"📐 Sumber: `{film_res}` · `{get_readable_time(film_dur)}`\n"
                f"⏱️ Target: `{target_min:.0f} menit`\n"
                f"⚙️ Quality: `{QUALITY_PRESETS[quality]['label']}`\n"
                f"**Ditambahkan Oleh:** {process_status.added_by}\n"
                f"`/cancel{CMD_SUFFIX} process {process_status.process_id}`"
            )
            await _safe_edit(status_msg, process_status.status_message)

            out_file = _tmp(f"recap_auto_{process_status.process_id}.mp4")
            vid_dur  = await _auto_recap(
                movie_path, target_min, quality, out_file,
                process_status, status_msg,
            )

            if not os.path.exists(out_file) or os.path.getsize(out_file) == 0:
                raise RuntimeError("File output tidak valid setelah render AUTO.")

            await _finish_and_send(
                process_status, original_event, movie_title,
                out_file, vid_dur, mode, quality,
                yt_enabled, yt_privacy, status_msg, render_start,
            )
            return

        # ── MODE CHAPTER — download .txt ─────────────────────────────
        if mode == "chapter":
            if reply_msg is None:
                raise RuntimeError("Mode CHAPTER membutuhkan file .txt. Balas file .txt dengan /recap.")

            txt_path = _tmp(f"recap_{process_status.process_id}.txt")

            process_status.update_process_message(
                f"📥 **Mengunduh naskah chapter...**\n\n"
                f"🎬 Film: `{movie_title}`\n"
                f"`/cancel{CMD_SUFFIX} process {process_status.process_id}`"
            )
            await _safe_edit(status_msg, process_status.status_message)

            downloaded = await original_event.client.download_media(reply_msg, txt_path)
            if not downloaded or not os.path.exists(txt_path):
                raise RuntimeError("Gagal download file .txt")

            # Parse .txt
            scenes = parse_recap_txt(txt_path)
            total  = len(scenes)
            _cleanup(txt_path)
            txt_path = None

            LOGGER.info(f"MovieRecap CHAPTER: {total} chapter untuk '{movie_title}'")

            # Render tiap chapter
            for idx, scene in enumerate(scenes, 1):
                if not check_running_process(process_status.process_id):
                    raise asyncio.CancelledError("Dibatalkan")

                start_t = scene["start"]
                narr    = scene["narration"]
                out_ch  = _tmp(f"ch_{process_status.process_id}_{idx:03d}.mp4")

                # Update status
                elapsed  = time.time() - render_start
                eta_secs = (elapsed / idx * (total - idx + 1)) if idx > 1 else 0

                process_status.update_process_message(
                    f"🎙️ **Merender Chapter [{idx}/{total}]**\n\n"
                    f"`{narr[:60]}{'...' if len(narr) > 60 else ''}`\n"
                    f"{get_progress_bar_string(idx - 1, total)} {((idx-1)*100//total)}%\n"
                    f"**Film:** `{movie_title}`\n"
                    f"**Mulai:** `{start_t:.0f}s` | **Quality:** `{QUALITY_PRESETS[quality]['label']}`\n"
                    f"**W.Proses:** `{get_readable_time(elapsed)}` | **ETA:** `{get_readable_time(eta_secs)}`\n"
                    f"**Oleh:** {process_status.added_by}\n"
                    f"`/cancel{CMD_SUFFIX} process {process_status.process_id}`"
                )
                await _safe_edit(status_msg, process_status.status_message)
                process_status.ping = time.time()

                ok = await _render_chapter(
                    movie_path, start_t, narr, out_ch,
                    quality, idx, total, process_status,
                )

                if ok and os.path.exists(out_ch) and os.path.getsize(out_ch) > 0:
                    chapter_files.append(out_ch)
                else:
                    LOGGER.warning(f"⚠️  Chapter {idx} gagal atau kosong, di-skip")

            if not chapter_files:
                raise RuntimeError("Semua chapter gagal dirender. Cek format .txt dan durasi film.")

            # Merge semua chapter
            process_status.update_process_message(
                f"🔄 **Menggabungkan {len(chapter_files)} chapter...**\n\n"
                f"**Film:** `{movie_title}`\n"
                f"**W.Proses:** `{get_readable_time(time.time() - render_start)}`\n"
                f"`/cancel{CMD_SUFFIX} process {process_status.process_id}`"
            )
            await _safe_edit(status_msg, process_status.status_message)

            merged_path = _tmp(f"recap_merged_{process_status.process_id}.mp4")
            vid_dur     = await _merge_chapters_ffmpeg(chapter_files, merged_path, quality)

            if not os.path.exists(merged_path) or os.path.getsize(merged_path) == 0:
                raise RuntimeError("Merge gagal — file output tidak valid.")

            await _finish_and_send(
                process_status, original_event, movie_title,
                merged_path, vid_dur, mode, quality,
                yt_enabled, yt_privacy, status_msg, render_start,
            )

    except asyncio.CancelledError:
        await _safe_edit(status_msg, "🚫 **Movie Recap Dibatalkan.**")

    except Exception as e:
        LOGGER.error(f"❌ MovieRecap worker error: {e}", exc_info=True)
        err_text = f"❌ **Error Movie Recap:**\n\n`{str(e)[:400]}`"
        await _safe_edit(status_msg, err_text)

    finally:
        # Cleanup semua file temp
        if txt_path:
            _cleanup(txt_path)
        for f in chapter_files:
            _cleanup(f)
        _recap_state.pop(process_status.user_id, None)

        # Remove dari queue
        await remove_running_process(process_status.process_id)
        async with working_task_lock:
            for task in list(working_task):
                ps = task.get("process_status")
                if ps and ps.process_id == process_status.process_id:
                    working_task.remove(task)
                    break


async def _finish_and_send(
    process_status: ProcessStatus,
    original_event,
    movie_title: str,
    out_file: str,
    vid_dur: float,
    mode: str,
    quality: str,
    yt_enabled: bool,
    yt_privacy: str,
    status_msg,
    render_start: float,
) -> None:
    """Kirim hasil recap ke Telegram + YouTube (opsional)."""
    try:
        elapsed   = time.time() - render_start
        file_size = os.path.getsize(out_file)
        mode_icon = "🤖 Auto AI" if mode == "auto" else "📝 Chapter"

        # Ambil dimensi video
        try:
            vc   = VideoFileClip(out_file)
            vdur = int(vc.duration)
            vw, vh = vc.size
            vc.close()
        except Exception:
            vdur, vw, vh = int(vid_dur), TARGET_W, TARGET_H

        caption = (
            f"🎬 **MOVIE RECAP — {movie_title.upper()}**\n\n"
            f"**Mode:** `{mode_icon}`\n"
            f"**Durasi:** `{get_readable_time(vid_dur)}`\n"
            f"**Resolusi:** `{TARGET_W}×{TARGET_H}`\n"
            f"**Quality:** `{QUALITY_PRESETS[quality]['label']}`\n"
            f"**Ukuran:** `{get_human_size(file_size)}`\n"
            f"**Render:** `{get_readable_time(elapsed)}`\n"
            f"**Oleh:** {process_status.added_by}"
        )

        # Update status sebelum upload
        process_status.update_process_message(
            f"⬆️ **Mengirim ke Telegram...**\n\n"
            f"`{movie_title}` · `{get_human_size(file_size)}`\n"
            f"`/cancel{CMD_SUFFIX} process {process_status.process_id}`"
        )
        await _safe_edit(status_msg, process_status.status_message)

        yt_buttons = [[Button.inline("⬆️ Upload YouTube", f"recap_yt_{process_status.user_id}_{process_status.process_id}".encode())]] if YOUTUBE_ENABLED and _HAS_YTUPLOAD else None

        try:
            await original_event.client.send_file(
                original_event.chat_id,
                out_file,
                caption=caption,
                supports_streaming=True,
                attributes=(DocumentAttributeVideo(vdur, vw, vh),),
                reply_to=original_event.message,
                buttons=yt_buttons,
            )
        except Exception as e:
            LOGGER.error(f"❌ Kirim ke Telegram gagal: {e}", exc_info=True)
            await original_event.respond(f"❌ Gagal kirim video: `{e}`")
            return

        # Upload YouTube langsung jika diminta
        if yt_enabled and YOUTUBE_ENABLED and _HAS_YTUPLOAD:
            yt_title = f"Movie Recap — {movie_title}"
            yt_desc  = (
                f"Rangkuman film: {movie_title}\n"
                f"Mode: {mode_icon}\n"
                f"Dibuat oleh Studio Khoirul Bot"
            )
            process_status.update_process_message(
                f"⬆️ **Upload ke YouTube...**\n\n"
                f"`{yt_title}`\n"
                f"🔒 `{yt_privacy}`\n"
                f"`/cancel{CMD_SUFFIX} process {process_status.process_id}`"
            )
            await _safe_edit(status_msg, process_status.status_message)

            try:
                yt_link = await upload_to_youtube(
                    out_file, yt_title, yt_desc,
                    yt_privacy, process_status, status_msg,
                )
                await original_event.respond(
                    f"📺 **YouTube:** [Tonton ↗]({yt_link})",
                    buttons=[[Button.url("📺 Buka di YouTube", yt_link)]],
                )
            except asyncio.CancelledError:
                raise
            except Exception as e:
                LOGGER.warning(f"⚠️  YouTube upload recap gagal: {e}")
                await original_event.respond(f"⚠️ YouTube upload gagal: `{e}`")

        # Final success message
        final_text = (
            f"✅ **Movie Recap Selesai!**\n\n"
            f"🎬 **Film:** `{movie_title}`\n"
            f"**Mode:** `{mode_icon}`\n"
            f"**Durasi:** `{get_readable_time(vid_dur)}`\n"
            f"**Total Waktu:** `{get_readable_time(elapsed)}`\n"
            f"**Oleh:** {process_status.added_by}"
        )
        await _safe_edit(status_msg, final_text)

    finally:
        _cleanup(out_file)


# ═══════════════════════════════════════════════════════════════════════
#  QUEUE STARTER
# ═══════════════════════════════════════════════════════════════════════

async def _start_recap_task(
    process_status: ProcessStatus,
    original_event,
    reply_msg,
    movie_title: str,
    mode: str,
    target_min: float,
    quality: str,
    narasi_on: bool,
    yt_enabled: bool,
    yt_privacy: str,
    status_msg,
) -> None:
    """Queue-aware task starter untuk MovieRecap."""
    task_wrapper = {
        "process_status": process_status,
        "functions": [],
        "_movierecap": True,
    }

    queued = False
    async with working_task_lock:
        if len(working_task) < get_task_limit():
            working_task.append(task_wrapper)
            await append_running_process(process_status.process_id)
        else:
            queued = True

    if queued:
        async with queued_task_lock:
            pos = len(queued_task) + 1
            queued_task.append(task_wrapper)

        queue_text = (
            f"⏳ **Masuk Antrian Movie Recap**\n\n"
            f"📋 **Posisi:** `{pos}`\n"
            f"🎬 **Film:** `{movie_title}`\n"
            f"🤖 **Mode:** `{'AUTO AI' if mode == 'auto' else 'CHAPTER'}`\n"
            f"**ID:** `{process_status.process_id}`\n"
            f"`/cancel{CMD_SUFFIX} process {process_status.process_id}`"
        )
        await _safe_edit(status_msg, queue_text)

        waited = 0
        while waited < QUEUE_TIMEOUT:
            await asyncio.sleep(5)
            waited += 5
            async with queued_task_lock:
                if task_wrapper not in queued_task:
                    break
        else:
            async with queued_task_lock:
                if task_wrapper in queued_task:
                    queued_task.remove(task_wrapper)
            await _safe_edit(status_msg, "❌ **Timeout antrian (2 jam).** Coba lagi.")
            _recap_state.pop(process_status.user_id, None)
            return

        if not check_running_process(process_status.process_id):
            _recap_state.pop(process_status.user_id, None)
            return

    await _recap_worker(
        process_status, original_event, reply_msg,
        movie_title, mode, target_min, quality,
        narasi_on, yt_enabled, yt_privacy, status_msg,
    )


# ═══════════════════════════════════════════════════════════════════════
#  DASHBOARD BUILDER
# ═══════════════════════════════════════════════════════════════════════

def _build_dashboard(
    user_id: int,
    movie_title: str,
    mode: str,
    target_min: float,
    quality: str,
    narasi_on: bool,
    yt_enabled: bool,
    yt_privacy: str,
) -> tuple[str, list]:
    """Build teks dashboard dan tombol inline."""
    mode_label  = "🤖 Auto AI Vision" if mode == "auto" else "📝 Chapter + Narasi"
    q_label     = QUALITY_PRESETS[quality]["label"]
    vip_text    = _vip_expiry_text(user_id)
    priv_icons  = {"private": "🔒", "unlisted": "🔗", "public": "🌍"}
    dur_label   = f"{int(target_min)} menit"
    narasi_txt  = "🎙️ Aktif" if narasi_on else "🔇 Nonaktif"
    yt_txt      = f"✅ Upload ({yt_privacy})" if yt_enabled else "❌ Skip"

    dash = (
        f"🎬 **Movie Recap — Konfirmasi**\n"
        f"{'─' * 32}\n"
        f"  🎞️ Film      `{movie_title}`\n"
        f"  🤖 Mode      `{mode_label}`\n"
        f"  ⏱️ Durasi    `{dur_label}`\n"
        f"  ⚙️ Quality   `{q_label}`\n"
        f"  🎙️ Narasi    `{narasi_txt}`\n"
        f"  📺 YouTube   `{yt_txt}`\n"
        f"  👑 VIP       {vip_text}\n"
        f"{'─' * 32}\n"
        f"_Sesuaikan pengaturan lalu tekan ▶️ Mulai_"
    )

    def _mode_btn(label: str, val: str) -> Button:
        return Button.inline(f"{'✅ ' if val == mode else ''}{label}", f"rc_mode_{user_id}_{val}")

    def _dur_btn(label: str, val: str) -> Button:
        cur = str(int(target_min))
        return Button.inline(f"{'✅ ' if val == cur else ''}{label}", f"rc_dur_{user_id}_{val}")

    def _qual_btn(label: str, val: str) -> Button:
        return Button.inline(f"{'✅ ' if val == quality else ''}{label}", f"rc_qual_{user_id}_{val}")

    def _prv_btn(label: str, val: str) -> Button:
        return Button.inline(f"{'✅ ' if val == yt_privacy else ''}{label}", f"rc_prv_{user_id}_{val}")

    buttons = [
        # Row 1: Mode
        [_mode_btn("🤖 Auto AI", "auto"),
         _mode_btn("📝 Chapter", "chapter")],
        # Row 2: Durasi
        [_dur_btn("5m", "5"), _dur_btn("10m", "10"),
         _dur_btn("12m", "12"), _dur_btn("15m", "15")],
        # Row 3: Quality
        [_qual_btn("⚡ Cepat", "fast"),
         _qual_btn("⚖️ Seimbang", "balanced"),
         _qual_btn("💎 HQ", "hq")],
    ]

    # Row 4: Narasi toggle (hanya di mode chapter)
    if mode == "chapter":
        narasi_toggle = "✅ Narasi Aktif" if narasi_on else "🔇 Tanpa Narasi"
        buttons.append([Button.inline(narasi_toggle, f"rc_narasi_{user_id}")])

    # Row 5: YouTube (jika tersedia)
    if YOUTUBE_ENABLED and _HAS_YTUPLOAD:
        yt_toggle = "✅ Upload YT" if yt_enabled else "☐ Upload YT"
        buttons.append([Button.inline(yt_toggle, f"rc_yt_{user_id}")])
        if yt_enabled:
            buttons.append([
                _prv_btn("🔒 Private", "private"),
                _prv_btn("🔗 Unlisted", "unlisted"),
                _prv_btn("🌍 Public", "public"),
            ])

    # Row akhir: Aksi
    buttons.append([
        Button.inline("▶️ Mulai Recap", f"rc_go_{user_id}"),
        Button.inline("❌ Batal", f"rc_cancel_{user_id}"),
    ])

    return dash, buttons


# ═══════════════════════════════════════════════════════════════════════
#  HANDLER: /recap
# ═══════════════════════════════════════════════════════════════════════

@Telegram.TELETHON_CLIENT.on(events.NewMessage(pattern=rf"^/recap{CMD_SUFFIX}(?:\s+(.+))?$"))
async def recap_handler(event) -> None:
    """
    Handler /recap — bisa reply video (mode auto) atau reply .txt (mode chapter).

    Format:
        /recap NamaFilm               → mode auto, tidak perlu .txt
        /recap NamaFilm (reply .txt)  → mode chapter dengan naskah
    """
    user_id = event.sender_id

    # VIP Check
    if not _is_vip(user_id):
        return await event.reply(
            "👑 **Fitur Eksklusif VIP**\n\n"
            "Movie Recap membutuhkan resource render + AI yang besar.\n"
            "Fitur ini hanya untuk member **VIP/Premium**.\n\n"
            "Hubungi admin untuk info berlangganan.",
            buttons=[[Button.url("💬 Hubungi Admin", f"https://t.me/{Config.BOT_USERNAME}")]],
        )

    # Ambil nama film
    movie_title = event.pattern_match.group(1)
    if movie_title:
        movie_title = movie_title.strip()

    # Cek reply message
    reply_msg = None
    has_txt   = False
    if event.is_reply:
        reply_msg = await event.get_reply_message()
        if reply_msg and reply_msg.document:
            fname = ""
            if reply_msg.document.attributes:
                for attr in reply_msg.document.attributes:
                    if hasattr(attr, "file_name"):
                        fname = attr.file_name or ""
                        break
            if fname.lower().endswith(".txt") or "text" in (reply_msg.document.mime_type or ""):
                has_txt = True
                # Coba ambil nama film dari nama file .txt
                if not movie_title:
                    movie_title = fname.rsplit(".", 1)[0].strip() or ""

    if not movie_title:
        available = _list_movies()
        av_text   = "\n".join(f"• `{m}`" for m in available[:8]) if available else "_Belum ada film_"
        return await event.reply(
            f"❌ **Sebutkan nama film!**\n\n"
            f"Format: `/recap{CMD_SUFFIX} NamaFilm`\n\n"
            f"**Film tersedia:**\n{av_text}\n\n"
            f"**Cara pakai:**\n"
            f"• Mode AUTO: `/recap{CMD_SUFFIX} NamaFilm` (tanpa .txt)\n"
            f"• Mode CHAPTER: Reply file .txt dengan `/recap{CMD_SUFFIX} NamaFilm`\n\n"
            f"**Format .txt (mode chapter):**\n"
            f"```\n00:05:30 | Cerita dimulai dari sini...\n00:22:15 | Konflik utama terjadi...\n01:10:00 | Klimaks film...\n```"
        )

    await ensure_user_data_structure(user_id)

    # Default state
    default_mode = "chapter" if has_txt else "auto"
    _recap_state[user_id] = {
        "reply_msg":  reply_msg if has_txt else None,
        "movie_title": movie_title,
        "mode":       default_mode,
        "target_min": 10.0,
        "quality":    "balanced",
        "narasi_on":  True,
        "yt_enabled": False,
        "yt_privacy": "private",
    }

    dash, buttons = _build_dashboard(
        user_id, movie_title, default_mode, 10.0, "balanced", True, False, "private"
    )
    await event.reply(dash, buttons=buttons)


# ═══════════════════════════════════════════════════════════════════════
#  CALLBACKS
# ═══════════════════════════════════════════════════════════════════════

def _get_state_or_expire(event, user_id: int) -> Optional[dict]:
    """Helper: ambil state atau jawab expired."""
    if user_id not in _recap_state:
        asyncio.create_task(event.answer("⚠️ Session expired. Ulangi /recap", alert=True))
        return None
    return _recap_state[user_id]


async def _rebuild_dashboard(event, user_id: int) -> None:
    """Helper: rebuild dan edit dashboard."""
    st = _recap_state.get(user_id)
    if not st:
        return
    dash, buttons = _build_dashboard(
        user_id, st["movie_title"], st["mode"], st["target_min"],
        st["quality"], st["narasi_on"], st["yt_enabled"], st["yt_privacy"],
    )
    await _safe_edit(event.message, dash, buttons=buttons)


@Telegram.TELETHON_CLIENT.on(events.CallbackQuery(pattern=b"rc_mode_(.+)"))
async def rc_mode_cb(event) -> None:
    await event.answer()
    parts   = event.data.decode().split("_")
    user_id = int(parts[2]); value = parts[3]
    if event.sender_id != user_id:
        return await event.answer("❌ Bukan milikmu!", alert=True)
    st = _get_state_or_expire(event, user_id)
    if not st: return
    st["mode"] = value
    # Mode auto tidak butuh .txt — clear reply_msg jika switch ke auto
    if value == "auto":
        st["reply_msg"] = None
    await _rebuild_dashboard(event, user_id)


@Telegram.TELETHON_CLIENT.on(events.CallbackQuery(pattern=b"rc_dur_(.+)"))
async def rc_dur_cb(event) -> None:
    await event.answer()
    parts   = event.data.decode().split("_")
    user_id = int(parts[2]); value = float(parts[3])
    if event.sender_id != user_id:
        return await event.answer("❌ Bukan milikmu!", alert=True)
    st = _get_state_or_expire(event, user_id)
    if not st: return
    st["target_min"] = value
    await _rebuild_dashboard(event, user_id)


@Telegram.TELETHON_CLIENT.on(events.CallbackQuery(pattern=b"rc_qual_(.+)"))
async def rc_qual_cb(event) -> None:
    await event.answer()
    parts   = event.data.decode().split("_")
    user_id = int(parts[2]); value = parts[3]
    if event.sender_id != user_id:
        return await event.answer("❌ Bukan milikmu!", alert=True)
    st = _get_state_or_expire(event, user_id)
    if not st: return
    st["quality"] = value
    await _rebuild_dashboard(event, user_id)


@Telegram.TELETHON_CLIENT.on(events.CallbackQuery(pattern=b"rc_narasi_(.+)"))
async def rc_narasi_cb(event) -> None:
    await event.answer()
    user_id = int(event.data.decode().split("_")[2])
    if event.sender_id != user_id:
        return await event.answer("❌ Bukan milikmu!", alert=True)
    st = _get_state_or_expire(event, user_id)
    if not st: return
    st["narasi_on"] = not st["narasi_on"]
    await _rebuild_dashboard(event, user_id)


@Telegram.TELETHON_CLIENT.on(events.CallbackQuery(pattern=b"rc_yt_(.+)"))
async def rc_yt_cb(event) -> None:
    await event.answer()
    user_id = int(event.data.decode().split("_")[2])
    if event.sender_id != user_id:
        return await event.answer("❌ Bukan milikmu!", alert=True)
    st = _get_state_or_expire(event, user_id)
    if not st: return
    st["yt_enabled"] = not st["yt_enabled"]
    await _rebuild_dashboard(event, user_id)


@Telegram.TELETHON_CLIENT.on(events.CallbackQuery(pattern=b"rc_prv_(.+)"))
async def rc_prv_cb(event) -> None:
    await event.answer()
    parts   = event.data.decode().split("_")
    user_id = int(parts[2]); value = parts[3]
    if event.sender_id != user_id:
        return await event.answer("❌ Bukan milikmu!", alert=True)
    st = _get_state_or_expire(event, user_id)
    if not st: return
    st["yt_privacy"] = value
    await _rebuild_dashboard(event, user_id)


@Telegram.TELETHON_CLIENT.on(events.CallbackQuery(pattern=b"rc_cancel_(.+)"))
async def rc_cancel_cb(event) -> None:
    await event.answer("🚫 Membatalkan...")
    parts   = event.data.decode().split("_")
    user_id = int(parts[2])
    if event.sender_id != user_id:
        return await event.answer("❌ Bukan milikmu!", alert=True)

    if len(parts) >= 4:
        # Ada process_id — cancel yang sedang berjalan
        process_id = parts[3]
        await remove_running_process(process_id)

    _recap_state.pop(user_id, None)
    await _safe_edit(event.message, "❌ **Movie Recap dibatalkan.**")


@Telegram.TELETHON_CLIENT.on(events.CallbackQuery(pattern=b"rc_go_(.+)"))
async def rc_go_cb(event) -> None:
    await event.answer("⏳ Memulai...")
    user_id = int(event.data.decode().split("_")[2])

    if event.sender_id != user_id:
        return await event.answer("❌ Bukan milikmu!", alert=True)
    if not _is_vip(user_id):
        return await event.edit("❌ Akses VIP habis. Hubungi admin.")

    st = _recap_state.get(user_id)
    if not st:
        return await event.edit(f"⚠️ Session expired.\nUlangi `/recap{CMD_SUFFIX} NamaFilm`")

    movie_title = st["movie_title"]
    mode        = st["mode"]
    target_min  = st["target_min"]
    quality     = st["quality"]
    narasi_on   = st["narasi_on"]
    yt_enabled  = st["yt_enabled"]
    yt_privacy  = st["yt_privacy"]
    reply_msg   = st["reply_msg"]

    # Validasi mode chapter butuh .txt
    if mode == "chapter" and reply_msg is None:
        return await event.edit(
            "❌ **Mode CHAPTER membutuhkan file .txt!**\n\n"
            "Balas file `.txt` dengan perintah `/recap`, atau ganti ke mode **🤖 Auto AI**."
        )

    sender          = await event.get_sender()
    user_name       = getattr(sender, "username", None) or ""
    user_first_name = getattr(sender, "first_name", None) or str(user_id)

    process_status = ProcessStatus(
        user_id         = user_id,
        chat_id         = event.chat_id,
        user_name       = user_name,
        user_first_name = user_first_name,
        event           = event,
        process_type    = getattr(Names, "movierecap", "MovieRecap"),
        input_mode      = "Telegram",
    )
    process_status.file_name = f"{movie_title}_recap"

    mode_label = "🤖 Auto AI Vision" if mode == "auto" else "📝 Chapter + Narasi"
    init_text  = (
        f"🎬 **Movie Recap Dimulai**\n"
        f"{'─' * 32}\n"
        f"  🎞️ Film     `{movie_title}`\n"
        f"  🤖 Mode     `{mode_label}`\n"
        f"  ⏱️ Durasi   `{int(target_min)} menit`\n"
        f"  ⚙️ Quality  `{QUALITY_PRESETS[quality]['label']}`\n"
        f"  🎙️ Narasi   `{'Aktif' if narasi_on else 'Nonaktif'}`\n"
        f"  📺 YouTube  `{'✅ ' + yt_privacy if yt_enabled else '❌ Skip'}`\n"
        f"{'─' * 32}\n"
        f"**ID:** `{process_status.process_id}`\n"
        f"`/cancel{CMD_SUFFIX} process {process_status.process_id}`"
    )

    cancel_btn = [[Button.inline(
        "❌ Batalkan",
        f"rc_cancel_{user_id}_{process_status.process_id}".encode(),
    )]]

    try:
        status_msg = await event.edit(init_text, buttons=cancel_btn)
    except Exception:
        status_msg = await event.respond(init_text, buttons=cancel_btn)

    asyncio.create_task(
        _start_recap_task(
            process_status, event, reply_msg,
            movie_title, mode, target_min, quality,
            narasi_on, yt_enabled, yt_privacy, status_msg,
        )
    )


# ═══════════════════════════════════════════════════════════════════════
#  NAMES EXTENSION — tambahkan ke Names.py
# ═══════════════════════════════════════════════════════════════════════
# Tambahkan ke bot_helper/Others/Names.py:
#
#   movierecap = "MovieRecap"
#   STATUS["MovieRecap"] = "🎬 Merangkum Film"
#
