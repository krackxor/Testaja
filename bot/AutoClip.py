"""
╔══════════════════════════════════════════════════════════════════════╗
║                    bot/AutoClip.py — v3.1                            ║
║       Auto Clip: Potong video panjang → Shorts/Reels terpisah        ║
╠══════════════════════════════════════════════════════════════════════╣
║  FORMAT FILE .TXT:                                                   ║
║  ─────────────────                                                   ║
║  # komentar diabaikan                                                ║
║  00:15 - 01:30 | Judul Segmen | Deskripsi opsional                  ║
║  01:45 - 03:00 | Judul Segmen 2                                      ║
║                                                                      ║
║  ALUR KERJA:                                                         ║
║  1. /clip{CMD_SUFFIX} NamaVideo reply .txt                          ║
║  2. Dashboard muncul — pilih mode, quality, YT privacy              ║
║  3. Masuk QUEUE → download .txt → render per scene → upload         ║
║                                                                      ║
║  INTEGRASI PENUH:                                                    ║
║  ✅ ProcessStatus — tracking, ping, status_message                  ║
║  ✅ Queue system — working_task / queued_task                       ║
║  ✅ check_running_process() — cancel support                         ║
║  ✅ CMD_SUFFIX — semua command                                       ║
║  ✅ VIP check + expiry date                                         ║
║  ✅ upload_to_youtube dari YTUpload.py (sudah difix Step 14)        ║
║  ✅ Full inline buttons                                              ║
║  ✅ Render mode: Shorts (9:16) / Landscape (16:9) / Auto            ║
║  ✅ Quality: Fast / Balanced / HQ                                    ║
╚══════════════════════════════════════════════════════════════════════╝
"""

# ── Standard Library ──────────────────────────────────────────────────
import asyncio
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

# ── MoviePy 2.x ───────────────────────────────────────────────────────
from moviepy import VideoFileClip, CompositeVideoClip, ColorClip, ImageClip
from moviepy.video.fx import FadeIn, FadeOut

# ── Telethon ──────────────────────────────────────────────────────────
from telethon import events
from telethon.tl.custom import Button
from telethon.tl.types import DocumentAttributeVideo

# ── Internal ──────────────────────────────────────────────────────────
from bot_helper.Database.User_Data import get_data, ensure_user_data_structure
from bot_helper.Others.Helper_Functions import get_human_size, get_readable_time
from bot_helper.Others.Names import Names
from bot_helper.Process.Process_Status import ProcessStatus, get_progress_bar_string
from bot_helper.Process.Running_Process import (
    append_running_process, check_running_process, remove_running_process,
)
from bot_helper.Process.Running_Tasks import (
    working_task, working_task_lock,
    queued_task, queued_task_lock,
)
from bot_helper.Database.User_Data import get_task_limit
from bot_helper.Telegram.Telegram_Client import Telegram
from config.config import Config

# ── YouTube (optional) ────────────────────────────────────────────────
try:
    from bot.YTUpload import upload_to_youtube, _is_vip, YOUTUBE_ENABLED
    _HAS_YTUPLOAD = True
except ImportError:
    YOUTUBE_ENABLED = False
    _HAS_YTUPLOAD   = False
    def _is_vip(user_id: int) -> bool:
        return user_id == Config.OWNER_ID or user_id in Config.SUDO_USERS

LOGGER     = Config.LOGGER
CMD_SUFFIX = Config.CMD_SUFFIX

# ── Konstanta ─────────────────────────────────────────────────────────
TEMP_DIR        = "./temp/autoclip/"
SHORT_W, SHORT_H   = 1080, 1920   # 9:16 portrait
LAND_W,  LAND_H    = 1920, 1080   # 16:9 landscape
TARGET_FPS         = 30
QUEUE_TIMEOUT      = 7200  # 2 jam

# Quality presets
QUALITY_PRESETS = {
    "fast":     {"bitrate": "4000k", "preset": "ultrafast", "label": "⚡ Cepat"},
    "balanced": {"bitrate": "6000k", "preset": "fast",      "label": "⚖️ Seimbang"},
    "hq":       {"bitrate": "8000k", "preset": "slow",      "label": "💎 HQ"},
}

# State per-user sebelum konfirmasi
# {user_id: {reply_msg, topic, mode, quality, yt_privacy, yt_enabled}}
_clip_state: dict = {}

os.makedirs(TEMP_DIR, exist_ok=True)


# ═══════════════════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════════════════

async def _safe_edit(msg, text: str, buttons=None) -> None:
    """Edit pesan tanpa crash jika gagal."""
    try:
        await msg.edit(text, buttons=buttons)
    except Exception:
        pass


def _tmp(name: str) -> str:
    """Return path file temporary."""
    return os.path.join(TEMP_DIR, name)


def _cleanup(*paths: str) -> None:
    """Hapus file-file temporary, abaikan error."""
    for p in paths:
        if p and os.path.exists(p):
            try:
                os.remove(p)
            except OSError:
                pass


def _vip_expiry_text(user_id: int) -> str:
    """Return teks masa aktif VIP."""
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


def _find_source_video(topic: str) -> Optional[str]:
    """
    Cari file video sumber di folder gameplay.
    Coba beberapa folder umum.
    """
    search_dirs = ["./gameplay/", "./userdata/gameplay/", "./videos/"]
    exts        = [".mp4", ".mkv", ".avi", ".mov", ".webm"]

    for folder in search_dirs:
        if not os.path.isdir(folder):
            continue
        for f in os.listdir(folder):
            name_lower  = f.lower()
            topic_lower = topic.lower().replace(" ", "_")
            # Match exact atau partial
            if topic_lower in name_lower or name_lower.startswith(topic_lower):
                full_path = os.path.join(folder, f)
                if any(name_lower.endswith(ext) for ext in exts):
                    return full_path

    # Coba pakai find_gameplay_for_game dari Gameplay.py jika ada
    try:
        from bot.Gameplay import find_gameplay_for_game
        return find_gameplay_for_game(topic)
    except ImportError:
        pass

    return None


def _list_available_sources() -> list[str]:
    """Return list nama video yang tersedia sebagai sumber."""
    sources = []
    search_dirs = ["./gameplay/", "./userdata/gameplay/", "./videos/"]
    exts = [".mp4", ".mkv", ".avi", ".mov", ".webm"]
    for folder in search_dirs:
        if not os.path.isdir(folder):
            continue
        for f in os.listdir(folder):
            if any(f.lower().endswith(ext) for ext in exts):
                sources.append(os.path.splitext(f)[0])
    return sorted(set(sources))


# ═══════════════════════════════════════════════════════════════════════
#  PARSER FILE .TXT
# ═══════════════════════════════════════════════════════════════════════

def _time_to_sec(t_str: str) -> float:
    """Convert string waktu (HH:MM:SS atau MM:SS atau SS) ke detik."""
    parts = [p.strip() for p in t_str.strip().split(":")]
    if len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    elif len(parts) == 2:
        return int(parts[0]) * 60 + float(parts[1])
    return float(parts[0])


def parse_clip_txt(path: str) -> list[dict]:
    """
    Parse file .txt format: Waktu | Judul | Deskripsi(opsional)

    Format baris:
        00:15 - 01:30 | Judul Segmen
        00:15 - 01:30 | Judul Segmen | Deskripsi tambahan
        # ini komentar, diabaikan

    Returns list of dicts:
        {"segment": str, "desc": str, "start": float, "end": float, "duration": float}
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
            errors.append(f"Baris {i}: Kurang kolom. Format: `Waktu | Judul`")
            continue

        time_str = parts[0]
        segment  = parts[1]
        desc     = parts[2] if len(parts) >= 3 else ""

        t_split  = [x.strip() for x in time_str.split("-")]
        if len(t_split) != 2:
            errors.append(f"Baris {i}: Format waktu salah. Contoh: `00:15 - 01:30`")
            continue

        try:
            start_t = _time_to_sec(t_split[0])
            end_t   = _time_to_sec(t_split[1])
            if end_t <= start_t:
                errors.append(f"Baris {i}: Waktu akhir harus lebih besar dari waktu awal")
                continue
            scenes.append({
                "segment":  segment,
                "desc":     desc,
                "start":    start_t,
                "end":      end_t,
                "duration": end_t - start_t,
            })
        except (ValueError, IndexError):
            errors.append(f"Baris {i}: Angka waktu tidak valid")

    if errors:
        raise ValueError("❌ Format .txt salah:\n" + "\n".join(f"  • {e}" for e in errors))
    if not scenes:
        raise ValueError("❌ File .txt kosong atau tidak ada scene yang valid.")

    return scenes


# ═══════════════════════════════════════════════════════════════════════
#  VIDEO RENDERER
# ═══════════════════════════════════════════════════════════════════════

def _reframe_to_portrait(clip, w: int, h: int) -> "VideoFileClip":
    """
    Reframe clip ke portrait (9:16) dengan smart crop.
    Crop bagian tengah untuk konten landscape, atau pad untuk konten portrait.
    """
    import numpy as np
    cw, ch = clip.size

    # Target aspect ratio
    target_ratio = w / h
    source_ratio = cw / ch

    if abs(source_ratio - target_ratio) < 0.05:
        # Sudah hampir sama — resize saja
        return clip.resized((w, h))

    if source_ratio > target_ratio:
        # Source lebih lebar — crop kiri/kanan (center crop)
        new_w = int(ch * target_ratio)
        x1    = (cw - new_w) // 2
        cropped = clip.cropped(x1=x1, x2=x1 + new_w)
        return cropped.resized((w, h))
    else:
        # Source lebih tinggi — crop atas/bawah (center crop)
        new_h = int(cw / target_ratio)
        y1    = (ch - new_h) // 2
        cropped = clip.cropped(y1=y1, y2=y1 + new_h)
        return cropped.resized((w, h))


def _make_title_overlay(title: str, duration: float, w: int, h: int) -> ImageClip:
    """Buat overlay judul segmen di bagian atas frame."""
    from PIL import Image, ImageDraw, ImageFont
    import numpy as np

    font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    img       = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw      = ImageDraw.Draw(img)

    # Background bar semi-transparan
    bar_h = int(h * 0.10)
    draw.rectangle([0, 0, w, bar_h], fill=(0, 0, 0, 180))

    # Teks judul
    try:
        font_size = max(24, int(h * 0.038))
        font      = ImageFont.truetype(font_path, font_size)
    except Exception:
        font = ImageFont.load_default()

    # Wrap teks
    max_chars = int(w / (font_size * 0.55))
    if len(title) > max_chars:
        title = title[:max_chars - 3] + "..."

    bbox = draw.textbbox((0, 0), title, font=font)
    tw   = bbox[2] - bbox[0]
    tx   = (w - tw) // 2
    ty   = (bar_h - (bbox[3] - bbox[1])) // 2

    # Shadow
    draw.text((tx + 2, ty + 2), title, font=font, fill=(0, 0, 0, 180))
    draw.text((tx, ty), title, font=font, fill=(255, 255, 255, 240))

    clip = ImageClip(
        __import__("numpy").array(img), is_mask=False
    ).with_duration(duration).with_effects([FadeIn(0.3), FadeOut(0.3)])
    return clip


def _make_progress_bar_overlay(duration: float, w: int, h: int) -> CompositeVideoClip:
    """Buat progress bar animasi di bagian bawah frame."""
    import numpy as np

    BAR_H = max(6, int(h * 0.007))
    y_pos = h - BAR_H

    # Background bar
    bg = ColorClip(size=(w, BAR_H), color=(50, 50, 50)).with_duration(duration)\
         .with_position((0, y_pos)).with_opacity(0.7)

    # Progress bar animasi
    def _make_frame(t: float):
        fill_w = max(1, int(w * t / max(duration, 0.001)))
        arr    = __import__("numpy").zeros((BAR_H, w, 3), dtype=__import__("numpy").uint8)
        arr[:, :fill_w] = [0, 200, 255]  # Cyan
        return arr

    bar = ImageClip(_make_frame, duration=duration, is_mask=False)\
          .with_position((0, y_pos))

    return bg, bar


def _make_watermark(duration: float, w: int, h: int) -> ImageClip:
    """Buat watermark bot di pojok kanan bawah."""
    from PIL import Image, ImageDraw, ImageFont
    import numpy as np

    img  = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    text = f"@{Config.BOT_USERNAME}" if Config.BOT_USERNAME else "Studio Khoirul"

    try:
        font_size = max(18, int(h * 0.022))
        font      = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", font_size
        )
    except Exception:
        font = ImageFont.load_default()

    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    pad  = 12
    tx   = w - tw - pad
    ty   = h - th - pad - 20  # Sedikit di atas progress bar

    draw.text((tx + 1, ty + 1), text, font=font, fill=(0, 0, 0, 160))
    draw.text((tx, ty), text, font=font, fill=(200, 200, 200, 200))

    clip = ImageClip(
        __import__("numpy").array(img), is_mask=False
    ).with_duration(duration).with_effects([FadeIn(0.5)])
    return clip


async def render_clip(
    scene: dict,
    source_path: str,
    output_path: str,
    mode: str,
    quality: str,
    process_status: ProcessStatus,
) -> str:
    """
    Render satu scene menjadi video clip.

    Args:
        scene: dict dengan start, end, segment, desc
        source_path: path video sumber
        output_path: path output file
        mode: "short" (9:16), "landscape" (16:9), "auto"
        quality: "fast", "balanced", "hq"
        process_status: untuk cancel check

    Returns:
        output_path jika berhasil
    """
    if not check_running_process(process_status.process_id):
        raise asyncio.CancelledError("Dibatalkan")

    start_t   = scene["start"]
    end_t     = scene["end"]
    title     = scene["segment"]
    dur       = scene["duration"]
    q         = QUALITY_PRESETS.get(quality, QUALITY_PRESETS["balanced"])

    raw = None
    try:
        raw = VideoFileClip(source_path)
        # Pastikan end_t tidak melebihi durasi video sumber
        end_t = min(end_t, raw.duration)
        dur   = end_t - start_t
        if dur <= 0.5:
            raise ValueError(f"Durasi terlalu pendek ({dur:.1f}s) untuk scene '{title}'")

        # ── Potong sesuai timestamp ───────────────────────────────────
        clip = raw.subclip(start_t, end_t)

        # ── Reframe sesuai mode ───────────────────────────────────────
        if mode == "short":
            W, H = SHORT_W, SHORT_H
            clip = _reframe_to_portrait(clip, W, H)
        elif mode == "landscape":
            W, H = LAND_W, LAND_H
            clip = clip.resized((W, H))
        else:
            # Auto: pertahankan aspect ratio asli, normalisasi ukuran
            W, H = clip.size
            # Pastikan dimensi genap (requirement libx264)
            W = W if W % 2 == 0 else W - 1
            H = H if H % 2 == 0 else H - 1
            clip = clip.resized((W, H))

        # Set FPS
        clip = clip.with_fps(TARGET_FPS)

        # ── Overlay visual ────────────────────────────────────────────
        title_overlay   = _make_title_overlay(title, dur, W, H)
        bg_bar, prog_bar = _make_progress_bar_overlay(dur, W, H)
        watermark       = _make_watermark(dur, W, H)

        # ── Compositing ───────────────────────────────────────────────
        final = CompositeVideoClip(
            [clip, title_overlay, watermark, bg_bar, prog_bar],
            size=(W, H),
        )

        # ── Render ke file ────────────────────────────────────────────
        ffmpeg_params = [
            "-preset", q["preset"],
            "-profile:v", "high",
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
        ]

        def _write():
            final.write_videofile(
                output_path,
                fps=TARGET_FPS,
                codec="libx264",
                bitrate=q["bitrate"],
                audio_codec="aac",
                audio_bitrate="192k",
                ffmpeg_params=ffmpeg_params,
                logger=None,
            )

        await asyncio.to_thread(_write)
        return output_path

    finally:
        # Tutup semua clip untuk cegah resource leak — tidak perlu gc.collect()
        for obj in [raw]:
            if obj:
                try:
                    obj.close()
                except Exception:
                    pass


# ═══════════════════════════════════════════════════════════════════════
#  THUMBNAIL
# ═══════════════════════════════════════════════════════════════════════

def _generate_clip_thumbnail(
    source_path: str,
    scene: dict,
    output_path: str,
    mode: str,
) -> Optional[str]:
    """
    Generate thumbnail untuk clip dari frame tengah scene.
    Return path thumbnail jika berhasil, None jika gagal.
    """
    try:
        from PIL import Image, ImageDraw, ImageFont
        import numpy as np

        mid_time = scene["start"] + scene["duration"] / 2
        raw      = VideoFileClip(source_path)
        frame    = raw.get_frame(min(mid_time, raw.duration - 0.1))
        raw.close()

        img = Image.fromarray(frame.astype("uint8"))

        # Crop ke aspect ratio yang benar
        if mode == "short":
            w, h = SHORT_W // 2, SHORT_H // 2
        elif mode == "landscape":
            w, h = LAND_W // 2, LAND_H // 2
        else:
            w, h = img.width, img.height

        img = img.resize((w, h), Image.LANCZOS)

        # Overlay judul di atas thumbnail
        draw = ImageDraw.Draw(img)
        try:
            font = ImageFont.truetype(
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                max(16, h // 20),
            )
        except Exception:
            font = ImageFont.load_default()

        title  = scene["segment"]
        bbox   = draw.textbbox((0, 0), title, font=font)
        margin = 10
        draw.rectangle([0, 0, w, bbox[3] - bbox[1] + margin * 2], fill=(0, 0, 0, 180))
        draw.text((margin, margin), title, font=font, fill=(255, 255, 255))

        img.save(output_path, "JPEG", quality=85)
        return output_path

    except Exception as e:
        LOGGER.debug(f"Thumbnail gagal untuk '{scene['segment']}': {e}")
        return None


# ═══════════════════════════════════════════════════════════════════════
#  MAIN WORKER
# ═══════════════════════════════════════════════════════════════════════

async def _autoclip_worker(
    process_status: ProcessStatus,
    original_event,
    reply_msg,
    topic: str,
    mode: str,
    quality: str,
    yt_enabled: bool,
    yt_privacy: str,
    status_msg,
) -> None:
    """
    Worker utama AutoClip.
    Alur: download .txt → parse → render per scene → upload
    """
    txt_path    = _tmp(f"clip_{process_status.process_id}.txt")
    temp_files  = [txt_path]
    render_start = time.time()

    try:
        # ── STEP 1: Download file .txt ────────────────────────────────
        process_status.update_process_message(
            f"📥 **Mengunduh naskah waktu cut...**\n\n"
            f"**Sumber:** `{topic}`\n"
            f"**Mode:** `{mode.upper()}`\n"
            f"**Quality:** `{QUALITY_PRESETS[quality]['label']}`\n"
            f"**ID:** `{process_status.process_id}`\n"
            f"`/cancel{CMD_SUFFIX} process {process_status.process_id}`"
        )
        await _safe_edit(status_msg, process_status.status_message)

        downloaded = await original_event.client.download_media(
            reply_msg, txt_path
        )
        if not downloaded or not os.path.exists(txt_path):
            raise RuntimeError("Gagal download file .txt")

        # ── STEP 2: Parse .txt ────────────────────────────────────────
        scenes = parse_clip_txt(txt_path)
        total  = len(scenes)
        LOGGER.info(f"AutoClip: {total} scene ditemukan untuk '{topic}'")

        # ── STEP 3: Cari video sumber ─────────────────────────────────
        source_path = _find_source_video(topic)
        if not source_path:
            available = _list_available_sources()
            av_text   = "\n".join(f"  • `{s}`" for s in available[:10]) if available else "  _Belum ada video_"
            raise RuntimeError(
                f"Video sumber `{topic}` tidak ditemukan!\n\n"
                f"**Video tersedia:**\n{av_text}\n\n"
                f"Upload dulu via `/addgameplay{CMD_SUFFIX}`"
            )

        source_size = os.path.getsize(source_path)
        LOGGER.info(f"AutoClip sumber: {source_path} ({get_human_size(source_size)})")

        # ── STEP 4: Render per scene ──────────────────────────────────
        success_count = 0

        for idx, scene in enumerate(scenes, 1):
            if not check_running_process(process_status.process_id):
                raise asyncio.CancelledError("Dibatalkan")

            seg_title = scene["segment"]
            seg_dur   = scene["duration"]
            out_file  = _tmp(f"clip_{process_status.process_id}_{idx:02d}.mp4")
            thumb_file = _tmp(f"thumb_{process_status.process_id}_{idx:02d}.jpg")

            # ── Update status render ──────────────────────────────────
            elapsed  = time.time() - render_start
            eta_secs = (elapsed / idx * (total - idx + 1)) if idx > 1 else 0

            process_status.update_process_message(
                f"✂️ **Merender Clip [{idx}/{total}]**\n\n"
                f"`{seg_title}`\n"
                f"{get_progress_bar_string(idx - 1, total)} {((idx-1)*100//total)}%\n"
                f"**Waktu:** `{scene['start']:.1f}s` → `{scene['end']:.1f}s` ({seg_dur:.0f}s)\n"
                f"**Sumber:** `{topic}`\n"
                f"**Mode:** `{mode.upper()}` | **Quality:** `{QUALITY_PRESETS[quality]['label']}`\n"
                f"**W.Proses:** `{get_readable_time(elapsed)}` | **ETA:** `{get_readable_time(eta_secs)}`\n"
                f"**Ditambahkan Oleh:** {process_status.added_by}\n"
                f"`/cancel{CMD_SUFFIX} process {process_status.process_id}`"
            )
            await _safe_edit(status_msg, process_status.status_message)
            process_status.ping = time.time()

            # ── Render ────────────────────────────────────────────────
            try:
                await render_clip(scene, source_path, out_file, mode, quality, process_status)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                LOGGER.error(f"❌ Render scene {idx} gagal: {e}", exc_info=True)
                await _safe_edit(
                    status_msg,
                    f"⚠️ **Clip [{idx}/{total}] gagal render:**\n`{e}`\n\nLanjut ke clip berikutnya..."
                )
                _cleanup(out_file)
                continue

            # ── Generate thumbnail ────────────────────────────────────
            thumb = _generate_clip_thumbnail(source_path, scene, thumb_file, mode)

            # ── Upload ke Telegram ────────────────────────────────────
            clip_size = os.path.getsize(out_file)
            caption   = (
                f"✂️ **CLIP {idx}/{total}**\n\n"
                f"📌 **Judul:** {seg_title}\n"
                f"🎬 **Sumber:** `{topic}`\n"
                f"⏱️ **Durasi:** `{seg_dur:.0f}` detik\n"
                f"📐 **Mode:** `{mode.upper()}` | `{QUALITY_PRESETS[quality]['label']}`\n"
                f"💽 **Ukuran:** `{get_human_size(clip_size)}`"
            )
            if scene.get("desc"):
                caption += f"\n📝 **Catatan:** {scene['desc']}"

            # Ambil dimensi untuk DocumentAttributeVideo
            try:
                _vc   = VideoFileClip(out_file)
                vdur  = int(_vc.duration)
                vw, vh = _vc.size
                _vc.close()
            except Exception:
                vdur, vw, vh = int(seg_dur), 1080, 1920

            try:
                await original_event.client.send_file(
                    original_event.chat_id,
                    out_file,
                    caption=caption,
                    thumb=thumb if thumb else None,
                    supports_streaming=True,
                    attributes=(DocumentAttributeVideo(vdur, vw, vh),),
                    reply_to=original_event.message,
                )
                success_count += 1
            except Exception as e:
                LOGGER.error(f"❌ Upload Telegram clip {idx} gagal: {e}", exc_info=True)
                await _safe_edit(status_msg, f"⚠️ Upload clip {idx} gagal: `{e}`")

            # ── Upload ke YouTube (opsional) ──────────────────────────
            if yt_enabled and YOUTUBE_ENABLED and _HAS_YTUPLOAD:
                yt_title_clip = f"{topic} — {seg_title}"
                yt_desc_clip  = (
                    f"Clip dari: {topic}\n"
                    f"Segmen: {seg_title}\n"
                    f"Durasi: {seg_dur:.0f} detik\n"
                    + (scene["desc"] if scene.get("desc") else "")
                )
                process_status.update_process_message(
                    f"⬆️ **Upload YouTube Clip [{idx}/{total}]**\n\n"
                    f"`{yt_title_clip}`\n"
                    f"**Ditambahkan Oleh:** {process_status.added_by}\n"
                    f"`/cancel{CMD_SUFFIX} process {process_status.process_id}`"
                )
                await _safe_edit(status_msg, process_status.status_message)
                try:
                    yt_link = await upload_to_youtube(
                        out_file, yt_title_clip, yt_desc_clip,
                        yt_privacy, process_status, status_msg,
                    )
                    await original_event.respond(
                        f"📺 **YouTube Clip {idx}:** [Buka ↗]({yt_link})",
                        buttons=[[Button.url("📺 Tonton di YouTube", yt_link)]],
                    )
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    LOGGER.warning(f"⚠️  YouTube upload clip {idx} gagal: {e}")
                    await original_event.respond(f"⚠️ YouTube clip {idx} gagal: `{e}`")

            # ── Cleanup file clip (sudah diupload) ────────────────────
            _cleanup(out_file, thumb_file)
            process_status.ping = time.time()

        # ── SELESAI ───────────────────────────────────────────────────
        total_time = get_readable_time(time.time() - render_start)
        final_text = (
            f"✅ **Auto Clip Selesai!**\n\n"
            f"📊 **Berhasil:** `{success_count}/{total}` clip\n"
            f"🎬 **Sumber:** `{topic}`\n"
            f"📐 **Mode:** `{mode.upper()}` | `{QUALITY_PRESETS[quality]['label']}`\n"
            f"⏱️ **Total Waktu:** `{total_time}`\n"
            f"**Oleh:** {process_status.added_by}"
        )

        if success_count < total:
            final_text += f"\n\n⚠️ {total - success_count} clip gagal (lihat log di atas)"

        await _safe_edit(status_msg, final_text)

    except asyncio.CancelledError:
        await _safe_edit(status_msg, "🚫 **Auto Clip Dibatalkan.**")

    except Exception as e:
        LOGGER.error(f"❌ AutoClip worker error: {e}", exc_info=True)
        err_short = str(e)[:400]
        await _safe_edit(status_msg, f"❌ **Error AutoClip:**\n\n`{err_short}`")

    finally:
        # Cleanup file .txt dan file temp yang belum dihapus
        _cleanup(txt_path)
        _clip_state.pop(process_status.user_id, None)

        # Remove dari running_process dan working_task
        await remove_running_process(process_status.process_id)
        async with working_task_lock:
            for task in list(working_task):
                ps = task.get("process_status")
                if ps and ps.process_id == process_status.process_id:
                    working_task.remove(task)
                    break


async def _start_autoclip_task(
    process_status: ProcessStatus,
    original_event,
    reply_msg,
    topic: str,
    mode: str,
    quality: str,
    yt_enabled: bool,
    yt_privacy: str,
    status_msg,
) -> None:
    """Queue-aware task starter untuk AutoClip."""
    task_wrapper = {
        "process_status": process_status,
        "functions": [],
        "_autoclip": True,
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
            f"⏳ **Masuk Antrian Auto Clip**\n\n"
            f"📋 **Posisi:** `{pos}`\n"
            f"🎬 **Sumber:** `{topic}`\n"
            f"📐 **Mode:** `{mode.upper()}` | `{QUALITY_PRESETS[quality]['label']}`\n"
            f"**ID:** `{process_status.process_id}`\n"
            f"`/cancel{CMD_SUFFIX} process {process_status.process_id}`"
        )
        await _safe_edit(status_msg, queue_text)

        # Tunggu giliran dengan timeout
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
            _clip_state.pop(process_status.user_id, None)
            return

        if not check_running_process(process_status.process_id):
            _clip_state.pop(process_status.user_id, None)
            return

    # Jalankan worker
    await _autoclip_worker(
        process_status, original_event, reply_msg,
        topic, mode, quality, yt_enabled, yt_privacy, status_msg,
    )


# ═══════════════════════════════════════════════════════════════════════
#  DASHBOARD BUILDER
# ═══════════════════════════════════════════════════════════════════════

def _build_clip_dashboard(user_id: int, topic: str, mode: str, quality: str, yt_enabled: bool, yt_privacy: str) -> tuple[str, list]:
    """Build teks dashboard dan tombol inline."""
    mode_icons    = {"short": "📱 Shorts 9:16", "landscape": "🖥️ Landscape 16:9", "auto": "🔄 Auto"}
    priv_icons    = {"private": "🔒", "unlisted": "🔗", "public": "🌍"}
    yt_icon       = "✅ YT Upload" if yt_enabled else "❌ Telegram Only"
    vip_text      = _vip_expiry_text(user_id)
    q_label       = QUALITY_PRESETS[quality]["label"]

    dash_text = (
        f"✂️ **Auto Clip — Konfirmasi**\n"
        f"{'─' * 32}\n"
        f"  🎬 Sumber    `{topic}`\n"
        f"  📐 Mode      `{mode_icons.get(mode, mode)}`\n"
        f"  ⚙️  Quality   `{q_label}`\n"
        f"  📺 YouTube   `{yt_icon}`"
    )
    if yt_enabled:
        dash_text += f"\n  🔒 Privasi   `{yt_privacy.capitalize()}`"
    dash_text += (
        f"\n  👑 VIP       {vip_text}\n"
        f"{'─' * 32}\n"
        f"_Sesuaikan pengaturan lalu tekan ▶️ Mulai_"
    )

    def _mode_btn(label: str, val: str) -> Button:
        icon = "✅ " if val == mode else ""
        return Button.inline(f"{icon}{label}", f"ac_mode_{user_id}_{val}")

    def _qual_btn(label: str, val: str) -> Button:
        icon = "✅ " if val == quality else ""
        return Button.inline(f"{icon}{label}", f"ac_qual_{user_id}_{val}")

    def _prv_btn(label: str, val: str) -> Button:
        icon = "✅ " if val == yt_privacy else ""
        return Button.inline(f"{icon}{label}", f"ac_prv_{user_id}_{val}")

    buttons = [
        # Row 1: Mode
        [_mode_btn("📱 Short", "short"),
         _mode_btn("🖥️ Wide", "landscape"),
         _mode_btn("🔄 Auto", "auto")],
        # Row 2: Quality
        [_qual_btn("⚡ Cepat", "fast"),
         _qual_btn("⚖️ Seimbang", "balanced"),
         _qual_btn("💎 HQ", "hq")],
    ]

    # Row 3: YouTube toggle + privacy (hanya jika YOUTUBE_ENABLED)
    if YOUTUBE_ENABLED and _HAS_YTUPLOAD:
        yt_toggle = "✅ Upload YT" if yt_enabled else "☐ Upload YT"
        buttons.append([
            Button.inline(yt_toggle, f"ac_yt_{user_id}"),
        ])
        if yt_enabled:
            buttons.append([
                _prv_btn("🔒 Private", "private"),
                _prv_btn("🔗 Unlisted", "unlisted"),
                _prv_btn("🌍 Public", "public"),
            ])

    # Row akhir: Aksi
    buttons.append([
        Button.inline("▶️ Mulai Render", f"ac_go_{user_id}"),
        Button.inline("❌ Batal", f"ac_cancel_{user_id}"),
    ])

    return dash_text, buttons


# ═══════════════════════════════════════════════════════════════════════
#  HANDLER: /clip
# ═══════════════════════════════════════════════════════════════════════

@Telegram.TELETHON_CLIENT.on(events.NewMessage(pattern=rf"^/clip{CMD_SUFFIX}(?:\s+(.+))?$"))
async def autoclip_handler(event) -> None:
    """
    Handler /clip — reply ke file .txt dengan nama video sumber.

    Format: /clip NamaVideo
    Atau:   /clip (nama dari teks .txt)
    """
    user_id = event.sender_id

    # ── VIP Check ────────────────────────────────────────────────────
    if not _is_vip(user_id):
        return await event.reply(
            "👑 **Fitur Eksklusif VIP**\n\n"
            "Auto Clip membutuhkan resource render yang besar.\n"
            "Fitur ini hanya untuk member **VIP/Premium**.\n\n"
            "Hubungi admin untuk info berlangganan.",
            buttons=[[Button.url("💬 Hubungi Admin", f"https://t.me/{Config.BOT_USERNAME}")]],
        )

    # ── Validasi reply ────────────────────────────────────────────────
    if not event.is_reply:
        return await event.reply(
            f"❌ **Cara Pakai:**\n"
            f"Balas file `.txt` dengan perintah:\n"
            f"`/clip{CMD_SUFFIX} NamaVideo`\n\n"
            f"**Contoh isi .txt:**\n"
            f"```\n"
            f"00:15 - 01:30 | Intro Keren\n"
            f"02:45 - 04:00 | Momen Epic\n"
            f"05:10 - 06:30 | Ending Seru\n"
            f"```\n"
            f"_Setiap baris = satu clip yang akan dibuat_"
        )

    reply_msg = await event.get_reply_message()
    if not reply_msg.document:
        return await event.reply("❌ Balas file `.txt` yang berisi daftar waktu cut.")

    # ── Ambil nama topic ──────────────────────────────────────────────
    topic = event.pattern_match.group(1)
    if topic:
        topic = topic.strip()
    else:
        # Coba ambil dari nama file
        try:
            fname = reply_msg.file.name or ""
            topic = fname.rsplit(".", 1)[0] if fname else ""
        except Exception:
            topic = ""

    if not topic:
        return await event.reply(
            f"❌ Sebutkan nama video sumber!\n"
            f"Contoh: `/clip{CMD_SUFFIX} NamaVideo`\n\n"
            f"Video tersedia:\n" +
            "\n".join(f"• `{s}`" for s in _list_available_sources()[:8]) or "_Belum ada video_"
        )

    await ensure_user_data_structure(user_id)

    # ── Simpan state dan tampilkan dashboard ──────────────────────────
    _clip_state[user_id] = {
        "reply_msg":  reply_msg,
        "topic":      topic,
        "mode":       "short",      # Default portrait/shorts
        "quality":    "balanced",   # Default balanced
        "yt_enabled": False,
        "yt_privacy": "private",
    }

    dash_text, buttons = _build_clip_dashboard(
        user_id, topic, "short", "balanced", False, "private"
    )
    await event.reply(dash_text, buttons=buttons)


# ═══════════════════════════════════════════════════════════════════════
#  CALLBACK: Mode selector
# ═══════════════════════════════════════════════════════════════════════

@Telegram.TELETHON_CLIENT.on(events.CallbackQuery(pattern=b"ac_mode_(.+)"))
async def ac_mode_cb(event) -> None:
    await event.answer()
    parts   = event.data.decode().split("_")
    # Format: ac_mode_{user_id}_{value}
    user_id = int(parts[2])
    value   = parts[3]

    if event.sender_id != user_id:
        return await event.answer("❌ Bukan milikmu!", alert=True)
    if user_id not in _clip_state:
        return await event.answer("⚠️ Session expired. Ulangi /clip", alert=True)

    _clip_state[user_id]["mode"] = value
    st = _clip_state[user_id]
    dash_text, buttons = _build_clip_dashboard(
        user_id, st["topic"], st["mode"], st["quality"],
        st["yt_enabled"], st["yt_privacy"],
    )
    await _safe_edit(event.message, dash_text, buttons=buttons)


# ═══════════════════════════════════════════════════════════════════════
#  CALLBACK: Quality selector
# ═══════════════════════════════════════════════════════════════════════

@Telegram.TELETHON_CLIENT.on(events.CallbackQuery(pattern=b"ac_qual_(.+)"))
async def ac_qual_cb(event) -> None:
    await event.answer()
    parts   = event.data.decode().split("_")
    user_id = int(parts[2])
    value   = parts[3]

    if event.sender_id != user_id:
        return await event.answer("❌ Bukan milikmu!", alert=True)
    if user_id not in _clip_state:
        return await event.answer("⚠️ Session expired. Ulangi /clip", alert=True)

    _clip_state[user_id]["quality"] = value
    st = _clip_state[user_id]
    dash_text, buttons = _build_clip_dashboard(
        user_id, st["topic"], st["mode"], st["quality"],
        st["yt_enabled"], st["yt_privacy"],
    )
    await _safe_edit(event.message, dash_text, buttons=buttons)


# ═══════════════════════════════════════════════════════════════════════
#  CALLBACK: YouTube toggle
# ═══════════════════════════════════════════════════════════════════════

@Telegram.TELETHON_CLIENT.on(events.CallbackQuery(pattern=b"ac_yt_(.+)"))
async def ac_yt_cb(event) -> None:
    await event.answer()
    user_id = int(event.data.decode().split("_")[2])

    if event.sender_id != user_id:
        return await event.answer("❌ Bukan milikmu!", alert=True)
    if user_id not in _clip_state:
        return await event.answer("⚠️ Session expired. Ulangi /clip", alert=True)

    _clip_state[user_id]["yt_enabled"] = not _clip_state[user_id]["yt_enabled"]
    st = _clip_state[user_id]
    dash_text, buttons = _build_clip_dashboard(
        user_id, st["topic"], st["mode"], st["quality"],
        st["yt_enabled"], st["yt_privacy"],
    )
    await _safe_edit(event.message, dash_text, buttons=buttons)


# ═══════════════════════════════════════════════════════════════════════
#  CALLBACK: Privacy selector
# ═══════════════════════════════════════════════════════════════════════

@Telegram.TELETHON_CLIENT.on(events.CallbackQuery(pattern=b"ac_prv_(.+)"))
async def ac_prv_cb(event) -> None:
    await event.answer()
    parts   = event.data.decode().split("_")
    user_id = int(parts[2])
    value   = parts[3]

    if event.sender_id != user_id:
        return await event.answer("❌ Bukan milikmu!", alert=True)
    if user_id not in _clip_state:
        return await event.answer("⚠️ Session expired. Ulangi /clip", alert=True)

    _clip_state[user_id]["yt_privacy"] = value
    st = _clip_state[user_id]
    dash_text, buttons = _build_clip_dashboard(
        user_id, st["topic"], st["mode"], st["quality"],
        st["yt_enabled"], st["yt_privacy"],
    )
    await _safe_edit(event.message, dash_text, buttons=buttons)


# ═══════════════════════════════════════════════════════════════════════
#  CALLBACK: Mulai
# ═══════════════════════════════════════════════════════════════════════

@Telegram.TELETHON_CLIENT.on(events.CallbackQuery(pattern=b"ac_go_(.+)"))
async def ac_go_cb(event) -> None:
    await event.answer("⏳ Memulai...")
    user_id = int(event.data.decode().split("_")[2])

    if event.sender_id != user_id:
        return await event.answer("❌ Bukan milikmu!", alert=True)
    if not _is_vip(user_id):
        return await event.edit("❌ Akses VIP habis. Hubungi admin.")
    if user_id not in _clip_state:
        return await event.edit(
            f"⚠️ Session expired.\nUlangi `/clip{CMD_SUFFIX} NamaVideo`"
        )

    st          = _clip_state[user_id]
    reply_msg   = st["reply_msg"]
    topic       = st["topic"]
    mode        = st["mode"]
    quality     = st["quality"]
    yt_enabled  = st["yt_enabled"]
    yt_privacy  = st["yt_privacy"]

    sender          = await event.get_sender()
    user_name       = getattr(sender, "username", None) or ""
    user_first_name = getattr(sender, "first_name", None) or str(user_id)

    process_status = ProcessStatus(
        user_id         = user_id,
        chat_id         = event.chat_id,
        user_name       = user_name,
        user_first_name = user_first_name,
        event           = event,
        process_type    = getattr(Names, "autoclip", "AutoClip"),
        input_mode      = "Telegram",
    )

    mode_icons = {"short": "📱 Shorts 9:16", "landscape": "🖥️ Landscape 16:9", "auto": "🔄 Auto"}
    init_text  = (
        f"✂️ **Auto Clip Dimulai**\n"
        f"{'─' * 32}\n"
        f"  🎬 Sumber   `{topic}`\n"
        f"  📐 Mode     `{mode_icons.get(mode, mode)}`\n"
        f"  ⚙️  Quality  `{QUALITY_PRESETS[quality]['label']}`\n"
        f"  📺 YouTube  `{'✅ Aktif (' + yt_privacy + ')' if yt_enabled else '❌ Off'}`\n"
        f"{'─' * 32}\n"
        f"**ID:** `{process_status.process_id}`\n"
        f"`/cancel{CMD_SUFFIX} process {process_status.process_id}`"
    )

    action_buttons = [[
        Button.inline("❌ Batalkan", f"ac_cancel_{user_id}_{process_status.process_id}"),
    ]]

    try:
        status_msg = await event.edit(init_text, buttons=action_buttons)
    except Exception:
        status_msg = await event.respond(init_text, buttons=action_buttons)

    asyncio.create_task(
        _start_autoclip_task(
            process_status, event, reply_msg,
            topic, mode, quality, yt_enabled, yt_privacy,
            status_msg,
        )
    )


# ═══════════════════════════════════════════════════════════════════════
#  CALLBACK: Cancel
# ═══════════════════════════════════════════════════════════════════════

@Telegram.TELETHON_CLIENT.on(events.CallbackQuery(pattern=b"ac_cancel_(.+)"))
async def ac_cancel_cb(event) -> None:
    await event.answer("🚫 Membatalkan...")
    parts   = event.data.decode().split("_")
    user_id = int(parts[2])

    if event.sender_id != user_id:
        return await event.answer("❌ Bukan milikmu!", alert=True)

    if len(parts) >= 4:
        # Ada process_id — cancel task yang sedang berjalan
        process_id = parts[3]
        await remove_running_process(process_id)
        await _safe_edit(event.message, "🚫 **Auto Clip dibatalkan.**")
    else:
        # Belum mulai — hapus state saja
        _clip_state.pop(user_id, None)
        await _safe_edit(event.message, "❌ **Auto Clip dibatalkan.**")


# ═══════════════════════════════════════════════════════════════════════
#  NAMES EXTENSION — tambahkan ke Names.py
# ═══════════════════════════════════════════════════════════════════════
# Tambahkan ke bot_helper/Others/Names.py:
#
#   autoclip = "AutoClip"
#   STATUS["AutoClip"] = "✂️ Memotong Clip"
#
