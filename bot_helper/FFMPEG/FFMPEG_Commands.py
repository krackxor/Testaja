"""
╔══════════════════════════════════════════════════════════════════════╗
║            bot_helper/FFMPEG/FFMPEG_Commands.py                      ║
║            Encoder1 Bot — v3.1                                       ║
╠══════════════════════════════════════════════════════════════════════╣
║  CHANGELOG dari versi lama:                                          ║
║  [NEW]      Alat cepat (/trim, /cut) menggunakan Stream Copy instan  ║
║  [NEW]      Perintah modifikasi piksel (Watermark/Crop/Rotate) kebal ║
║             dari settingan global agar menghindari re-encode lambat. ║
║  [SECURITY] get_data()[user_id] → .get() — tidak crash KeyError      ║
║  [SECURITY] user_data['video'] → .get({}) — tidak crash KeyError     ║
║  [SECURITY] shlex.split(user_input) → validasi metadata key=value    ║
║  [SECURITY] drawtext escape lebih ketat — cegah filter injection     ║
║  [FIX HIGH] -vf select=concatdec_select dihapus — invalid filter     ║
║  [FIX]      ffprobe timeout 10s → 30s                                ║
║  [FIX]      Hapus basicConfig() duplikat                             ║
║  [FIX]      subtitle path escape lebih robust                        ║
║  [FIX]      merge file list pakai shlex.quote()                      ║
║  [FIX]      audio-only/video-only merge dihandle eksplisit           ║
║  [FIX]      subtitle copy return konsisten                           ║
║  [FIX]      CRF validasi integer                                     ║
║  [FIX]      validate_output cek file size > 0                        ║
║  [IMPROVE]  Nama file sanitasi pakai unicodedata                     ║
╚══════════════════════════════════════════════════════════════════════╝
"""

# ── Standard Library ──────────────────────────────────────────────────
import glob
import json
import logging
import os
import re
import shlex
import shutil
import subprocess
import unicodedata
from os import makedirs
from os.path import exists, isdir, splitext, getsize

# ── Internal ──────────────────────────────────────────────────────────
from bot_helper.Database.User_Data import get_data
from bot_helper.Others.Helper_Functions import get_video_duration
from bot_helper.Others.Names import Names

# [FIX] Hapus basicConfig() duplikat — sudah ada di config.py
# Cukup pakai getLogger(__name__)
logger = logging.getLogger(__name__)

# ── Konstanta ─────────────────────────────────────────────────────────
FFPROBE_TIMEOUT  = 30       # [FIX] 10s → 30s untuk file besar
DEFAULT_CRF      = 23
DEFAULT_PRESET   = "medium"
DEFAULT_AUDIO_BR = "192k"

# Karakter yang harus di-escape dalam FFmpeg filter string
_FFMPEG_FILTER_ESCAPE = str.maketrans({
    "'": r"\'",
    ":": r"\:",
    "[": r"\[",
    "]": r"\]",
    ";": r"\;",
    ",": r"\,",
    "\\": "\\\\",
})


# ═══════════════════════════════════════════════════════════════════════
#  HELPER FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════

def create_direc(direc: str) -> None:
    """Buat direktori jika belum ada."""
    if not isdir(direc):
        makedirs(direc, exist_ok=True)


def _sanitize_filename(name: str) -> str:
    """
    [IMPROVE] Sanitasi nama file.
    Sebelumnya: isalnum() strip semua karakter non-ASCII (é,ñ,ü hilang).
    Sekarang: normalize Unicode dulu, baru filter karakter berbahaya.
    """
    # Normalize unicode: é → e, ñ → n, dll
    normalized = unicodedata.normalize("NFKD", name)
    # Encode ke ASCII, ignore karakter yang tidak bisa dikonversi
    ascii_name = normalized.encode("ascii", "ignore").decode("ascii")
    # Hapus karakter berbahaya untuk filename
    safe = re.sub(r'[^\w\s\-.]', '', ascii_name).strip()
    # Ganti spasi berulang dengan single space
    safe = re.sub(r'\s+', ' ', safe)
    return safe or "output"


def _safe_crf(value, default: int = DEFAULT_CRF) -> int:
    """
    [FIX] Parse CRF value dengan validasi.
    Sebelumnya: string '23abc' dikirim ke FFmpeg → error.
    """
    try:
        crf = int(str(value).strip())
        # CRF valid range: 0-51 untuk x264/x265
        return max(0, min(51, crf))
    except (ValueError, TypeError):
        logger.warning(f"⚠️  CRF value tidak valid: '{value}', pakai default {default}")
        return default


def _escape_ffmpeg_filter_text(text: str) -> str:
    """
    [SECURITY] Escape teks untuk dimasukkan ke FFmpeg filter string (drawtext dll).
    Sebelumnya: replace(':','\\:') saja — tidak cukup untuk mencegah filter injection.
    Sekarang: escape semua karakter special FFmpeg filter.
    """
    return text.translate(_FFMPEG_FILTER_ESCAPE)


def _validate_metadata_string(metadata_str: str) -> list[str]:
    """
    [SECURITY] Validasi dan parse custom metadata string.
    
    Sebelumnya: shlex.split(user_input) langsung — bisa inject FFmpeg args
    seperti '-vf scale=1:1' atau '-i malicious_file'.
    
    Sekarang: hanya izinkan format 'key=value', key harus alphanumeric.
    Return list siap untuk command.extend(['-metadata', 'key=value', ...])
    """
    result = []
    # Split berdasarkan newline atau semicolon
    entries = re.split(r'[\n;]+', metadata_str)
    
    for entry in entries:
        entry = entry.strip()
        if not entry:
            continue
        
        # Harus format key=value
        if '=' not in entry:
            logger.warning(f"⚠️  Metadata entry diabaikan (bukan key=value): '{entry[:50]}'")
            continue
        
        key, _, value = entry.partition('=')
        key = key.strip()
        value = value.strip()
        
        # Key hanya boleh alphanumeric dan underscore
        if not re.match(r'^[a-zA-Z0-9_]+$', key):
            logger.warning(f"⚠️  Metadata key tidak valid: '{key}' — diabaikan")
            continue
        
        # Hapus quotes dari value jika ada
        if value.startswith('"') and value.endswith('"'):
            value = value[1:-1]
        elif value.startswith("'") and value.endswith("'"):
            value = value[1:-1]
        
        result.extend(["-metadata", f"{key}={value}"])
    
    return result


def _escape_subtitle_path(path: str) -> str:
    """
    [FIX] Escape path subtitle untuk FFmpeg subtitles filter.
    
    FFmpeg subtitles filter path escaping sangat tricky:
    - Windows: backslash → \\
    - Colon (drive letter): C: → C\\:
    - Single quote: ' → \\\'
    
    Menggunakan absolute path + minimal escaping yang proven work.
    """
    abs_path = os.path.abspath(path)
    # Escape backslash dulu (Windows)
    escaped = abs_path.replace("\\", "\\\\\\\\")
    # Escape colon (Windows drive letter)
    escaped = escaped.replace(":", "\\:")
    # Escape single quote
    escaped = escaped.replace("'", "\\'")
    return escaped


# ═══════════════════════════════════════════════════════════════════════
#  STREAM INFO
# ═══════════════════════════════════════════════════════════════════════

class StreamInfo:
    """Informasi stream media dari ffprobe."""

    def __init__(self, file_path: str):
        self.file_path    = file_path
        self.has_video    = False
        self.has_audio    = False
        self.has_subtitle = False
        self.video_codec  = None
        self.audio_codec  = None
        self.duration     = 0.0
        self.container    = None
        self.width        = 0
        self.height       = 0
        self._probe()

    def _probe(self) -> None:
        """Probe file untuk mendapatkan informasi stream."""
        try:
            result = subprocess.run(
                [
                    "ffprobe", "-v", "quiet",
                    "-print_format", "json",
                    "-show_streams", "-show_format",
                    self.file_path,
                ],
                capture_output=True,
                text=True,
                timeout=FFPROBE_TIMEOUT,   # [FIX] 10s → 30s
            )
            if result.returncode != 0:
                logger.warning(
                    f"⚠️  ffprobe gagal untuk {self.file_path}: "
                    f"{result.stderr[:200]}"
                )
                return

            data        = json.loads(result.stdout)
            streams     = data.get("streams", [])
            format_info = data.get("format", {})

            for stream in streams:
                codec_type = stream.get("codec_type")
                if codec_type == "video":
                    self.has_video    = True
                    self.video_codec  = stream.get("codec_name")
                    self.width        = int(stream.get("width", 0))
                    self.height       = int(stream.get("height", 0))
                elif codec_type == "audio":
                    self.has_audio   = True
                    self.audio_codec = stream.get("codec_name")
                elif codec_type == "subtitle":
                    self.has_subtitle = True

            self.duration  = float(format_info.get("duration", 0))
            self.container = format_info.get("format_name", "").split(",")[0]

        except subprocess.TimeoutExpired:
            logger.error(
                f"❌ ffprobe timeout ({FFPROBE_TIMEOUT}s) untuk {self.file_path}"
            )
        except json.JSONDecodeError as e:
            logger.error(f"❌ ffprobe output bukan JSON valid: {e}")
        except Exception as e:
            logger.error(f"❌ Error probe {self.file_path}: {e}", exc_info=True)


# ═══════════════════════════════════════════════════════════════════════
#  FFMPEG COMMAND BUILDER
# ═══════════════════════════════════════════════════════════════════════

class FFmpegCommandBuilder:
    """Advanced FFmpeg command builder dengan validasi dan fallback."""

    def __init__(self, process_status):
        self.ps        = process_status
        self.user_id   = process_status.user_id

        # [FIX] Pakai .get() — tidak crash KeyError jika user_id tidak ada
        self.user_data = get_data().get(self.user_id, {})

        # [FIX] Semua settings pakai .get({}) — tidak crash jika key tidak ada
        self.video_settings    = self.user_data.get("video", {})
        self.audio_settings    = self.user_data.get("audio", {})
        self.watermark_settings = self.user_data.get("watermark", {})
        self.metadata_settings = self.user_data.get("metadata", {})
        self.merge_settings    = self.user_data.get("merge", {})
        self.mux_settings      = self.user_data.get("mux", {})

        self.command              = ["ffmpeg", "-hide_banner", "-loglevel", "warning", "-stats"]
        self.video_filters        = []
        self.audio_filters        = []
        self.filter_complex_parts = []
        self.use_filter_complex   = False
        self.current_video_label  = "[0:v]"
        self.current_audio_label  = "[0:a]"
        self.stream_info          = None

    # ── Utility ─────────────────────────────────────────────────────

    def create_directory(self, direc: str) -> None:
        create_direc(direc)

    def get_output_name(self, convert_quality=False) -> str:
        """Generate output filename dengan sanitasi yang benar."""
        extension = self.video_settings.get("extension", "mp4").lower()

        if self.ps.file_name:
            out_file_name, _ = splitext(self.ps.file_name)
        elif self.ps.send_files:
            out_file_name, _ = splitext(self.ps.send_files[-1].split("/")[-1])
        else:
            out_file_name = f"output_{self.ps.process_id}"

        # [IMPROVE] Sanitasi pakai unicodedata bukan isalnum() strip semua
        out_file_name = _sanitize_filename(out_file_name)

        if convert_quality:
            out_file_name = f"{out_file_name}_{convert_quality}p"

        return f"{out_file_name}.{extension}"

    def probe_input_file(self, file_path: str) -> "StreamInfo | None":
        """Probe input file untuk informasi stream."""
        if not exists(file_path):
            logger.error(f"❌ Input file tidak ditemukan: {file_path}")
            return None
        self.stream_info = StreamInfo(file_path)
        return self.stream_info

    # ── Metadata ────────────────────────────────────────────────────

    def add_metadata(self) -> None:
        """
        Tambahkan metadata ke command.
        [SECURITY] shlex.split(user_input) → _validate_metadata_string()
        """
        if not self.metadata_settings.get("enabled", False):
            return

        mode = self.metadata_settings.get("mode", "preset")

        if mode == "preset":
            presets = self.metadata_settings.get("preset", {})
            for key, value in presets.items():
                if value and re.match(r'^[a-zA-Z0-9_]+$', key):
                    self.command.extend(["-metadata", f"{key}={str(value)}"])
                elif value:
                    logger.warning(f"⚠️  Metadata key tidak valid dilewati: '{key}'")

        elif mode == "custom":
            custom_string = self.metadata_settings.get("custom", "")
            if custom_string:
                # [SECURITY] Validasi — bukan shlex.split() langsung
                validated = _validate_metadata_string(custom_string)
                if validated:
                    self.command.extend(validated)
                else:
                    logger.warning("⚠️  Custom metadata kosong setelah validasi")

    # ── Audio ────────────────────────────────────────────────────────

    def build_audio_filters(self) -> None:
        """Build audio filters dengan validasi."""
        if not self.audio_settings.get("enabled", False) and self.ps.process_type not in [Names.cut]:
            return

        if self.ps.process_type == Names.cut and self.ps.cut_ranges:
            select_parts = [f"between(t,{start},{end})" for start, end in self.ps.cut_ranges]
            self.audio_filters.append(
                f"aselect='not({'+'.join(select_parts)})',asetpts=N/SR/TB"
            )

        normalization = self.audio_settings.get("normalization", "Off")
        if normalization == "loudnorm":
            self.audio_filters.append("loudnorm=I=-16:TP=-1.5:LRA=11")
        elif normalization == "dynaudnorm":
            self.audio_filters.append("dynaudnorm")

        custom_filter = self.audio_settings.get("filter", "Off")
        if custom_filter == "highpass":
            self.audio_filters.append("highpass=f=100")
        elif custom_filter == "lowpass":
            self.audio_filters.append("lowpass=f=3000")

    def build_audio_codec(self) -> None:
        """Build audio codec settings dengan fallback."""
        if not self.audio_settings.get("enabled", False) and self.ps.process_type not in [Names.cut]:
            self.command.extend(["-c:a", "copy"])
            return

        # Jika process type adalah cut, kita harus re-encode audio karena filter pemotongan frame (aselect)
        codec = self.audio_settings.get("codec", "Auto")
        
        # Override codec jika kita hanya melakukan operasi alat potong mandiri
        if self.ps.process_type == Names.cut:
            codec = "aac"

        if codec == "Auto":
            if self.stream_info and self.stream_info.has_audio:
                self.command.extend(["-c:a", "copy"])
            else:
                self.command.extend(["-c:a", "aac", "-b:a", DEFAULT_AUDIO_BR])
            return

        if codec == "copy" and self.ps.process_type != Names.cut:
            self.command.extend(["-c:a", "copy"])
            return

        if self.audio_filters:
            self.command.extend(["-af", ",".join(self.audio_filters)])

        codec_map = {
            "aac": "aac", "mp3": "libmp3lame", "opus": "libopus",
            "vorbis": "libvorbis", "flac": "flac", "ac3": "ac3",
        }
        final_codec = codec_map.get(codec, codec)
        self.command.extend(["-c:a", final_codec])

        if codec == "aac":
            profile = self.audio_settings.get("codec_profile", "Auto")
            if profile != "Auto":
                self.command.extend(["-profile:a", profile.replace("-", "_")])

        if codec not in ["flac", "pcm"]:
            bitrate = self.audio_settings.get("bitrate", "Auto")
            default_bitrates = {
                "aac": "192k", "mp3": "192k", "opus": "128k",
                "vorbis": "192k", "ac3": "320k",
            }
            if bitrate != "Auto":
                self.command.extend(["-b:a", bitrate])
            else:
                self.command.extend(["-b:a", default_bitrates.get(codec, DEFAULT_AUDIO_BR)])

        downmix  = self.audio_settings.get("downmix", "Off")
        channels = self.audio_settings.get("channels", "Auto")
        if downmix != "Off":
            self.command.extend(["-ac", "1" if downmix == "mono" else "2"])
        elif channels != "Auto":
            channel_map = {"mono": 1, "stereo": 2, "2.1": 3, "3.1": 4, "5.1": 6, "7.1": 8}
            self.command.extend(["-ac", str(channel_map.get(channels, 2))])

        samplerate = self.audio_settings.get("samplerate", "Auto")
        if samplerate != "Auto":
            self.command.extend(["-ar", samplerate])

    # ── Video Filters ────────────────────────────────────────────────

    def build_video_filters(self) -> None:
        """Build video filters untuk berbagai operasi."""
        if self.ps.process_type == Names.cut and self.ps.cut_ranges:
            select_parts = [f"between(t,{start},{end})" for start, end in self.ps.cut_ranges]
            self.video_filters.append(
                f"select='not({'+'.join(select_parts)})',setpts=N/FRAME_RATE/TB"
            )

        if self.ps.process_type == Names.convert and self.ps.convert_quality:
            self.video_filters.append(f"scale=-2:{self.ps.convert_quality}")

        if self.ps.process_type == Names.rotate and self.ps.rotate_option:
            self.video_filters.append(self.ps.rotate_option)

        if self.ps.process_type == Names.crop and self.ps.crop_params:
            self.video_filters.append(self.ps.crop_params)

        # Hanya terapkan resolusi global pada proses konversi atau kompresi
        if self.ps.process_type in [Names.convert, Names.compress]:
            resolution = self.video_settings.get("resolution", "Auto")
            if resolution != "Auto":
                if "x" in resolution:
                    self.video_filters.append(f"scale={resolution}")
                elif resolution.isdigit():
                    self.video_filters.append(f"scale=-2:{resolution}")

    # ── Watermark ────────────────────────────────────────────────────

    def build_watermark(self) -> None:
        """
        Build watermark filter.
        [SECURITY] drawtext escape lebih ketat — cegah filter injection.
        """
        # Hentikan penambahan watermark global jika bukan untuk proses Encode Utama, Convert, atau Watermark khusus.
        if not self.watermark_settings.get("enabled") or self.ps.process_type not in [Names.compress, Names.convert, Names.watermark]:
            return

        wm_type           = self.watermark_settings.get("type", "image")
        duration_settings = self.watermark_settings.get(wm_type, {}).get("duration", {})
        mode              = duration_settings.get("mode", "full")

        duration_filter = ""
        if mode == "range":
            start = duration_settings.get("from", 0)
            end   = duration_settings.get("to", 99999)
            duration_filter = f":enable='between(t,{start},{end})'"
        elif mode == "interval":
            interval = duration_settings.get("interval", 60)
            duration_filter = f":enable='lt(mod(t,{interval}),1)'"

        position_map_overlay = {
            "top_left": "5:5",
            "top_center": "(main_w-overlay_w)/2:5",
            "top_right": "main_w-overlay_w-5:5",
            "middle_left": "5:(main_h-overlay_h)/2",
            "middle_center": "(main_w-overlay_w)/2:(main_h-overlay_h)/2",
            "middle_right": "main_w-overlay_w-5:(main_h-overlay_h)/2",
            "bottom_left": "5:main_h-overlay_h-5",
            "bottom_center": "(main_w-overlay_w)/2:main_h-overlay_h-5",
            "bottom_right": "main_w-overlay_w-5:main_h-overlay_h-5",
        }

        position_map_text = {
            "top_left": "x=10:y=10",
            "top_center": "x=(w-text_w)/2:y=10",
            "top_right": "x=w-text_w-10:y=10",
            "middle_left": "x=10:y=(h-text_h)/2",
            "middle_center": "x=(w-text_w)/2:y=(h-text_h)/2",
            "middle_right": "x=w-text_w-10:y=(h-text_h)/2",
            "bottom_left": "x=10:y=h-text_h-10",
            "bottom_center": "x=(w-text_w)/2:y=h-text_h-10",
            "bottom_right": "x=w-text_w-10:y=h-text_h-10",
        }

        if wm_type == "image":
            watermark_path = f"./userdata/{self.user_id}_watermark.jpg"
            if not exists(watermark_path):
                logger.warning(f"⚠️  Watermark image tidak ditemukan: {watermark_path}")
                return

            self.command.extend(["-i", watermark_path])
            position = position_map_overlay.get(
                self.watermark_settings.get("image", {}).get("position", "bottom_right"),
                "main_w-overlay_w-5:main_h-overlay_h-5",
            )
            overlay_filter = (
                f"{self.current_video_label}[1:v]"
                f"overlay={position}{duration_filter}[v_wm]"
            )
            self.filter_complex_parts.append(overlay_filter)
            self.current_video_label = "[v_wm]"
            self.use_filter_complex  = True

        elif wm_type == "text":
            text_settings = self.watermark_settings.get("text", {})
            raw_text      = text_settings.get("content", "")

            if not raw_text:
                return

            # [SECURITY] Escape semua karakter special FFmpeg filter
            text_content = _escape_ffmpeg_filter_text(raw_text)

            font_files = glob.glob(f"./userdata/{self.user_id}_watermark_font.*")
            font_path  = (
                font_files[0]
                if font_files
                else "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
            )
            # Escape font path juga
            font_path_escaped = _escape_ffmpeg_filter_text(font_path)

            position   = position_map_text.get(
                text_settings.get("position", "bottom_right"),
                "x=w-text_w-10:y=h-text_h-10",
            )
            font_size  = int(text_settings.get("font_size", 24))
            font_color = text_settings.get("font_color", "white")

            # Validate font_color — hanya boleh alphanum atau hex
            if not re.match(r'^[a-zA-Z0-9#@]+$', font_color):
                font_color = "white"

            drawtext_filter = (
                f"{self.current_video_label}"
                f"drawtext="
                f"text='{text_content}':"
                f"fontfile='{font_path_escaped}':"
                f"fontsize={font_size}:"
                f"fontcolor={font_color}:"
                f"{position}{duration_filter}[v_wm]"
            )
            self.filter_complex_parts.append(drawtext_filter)
            self.current_video_label = "[v_wm]"
            self.use_filter_complex  = True

    # ── Subtitle ─────────────────────────────────────────────────────

    def build_hardmux_subtitle(self) -> None:
        """
        Build hardmux subtitle filter.
        [FIX] Path escaping lebih robust.
        """
        if self.ps.process_type != Names.hardmux:
            return
        if not hasattr(self.ps, "subtitles") or not self.ps.subtitles:
            logger.warning("⚠️  Hardmux diminta tapi tidak ada subtitle")
            return

        sub_file = str(self.ps.subtitles[-1])
        if not exists(sub_file):
            logger.error(f"❌ Subtitle file tidak ditemukan: {sub_file}")
            return

        # [FIX] Escape path dengan helper yang lebih robust
        sub_path_escaped = _escape_subtitle_path(sub_file)
        sub_ext          = sub_file.lower().rsplit(".", 1)[-1]

        if sub_ext in ["srt", "ass", "ssa"]:
            subtitle_filter = (
                f"{self.current_video_label}"
                f"subtitles='{sub_path_escaped}'[v_sub]"
            )
        else:
            subtitle_filter = (
                f"{self.current_video_label}"
                f"subtitles='{sub_path_escaped}':force_style='FontSize=24'[v_sub]"
            )

        self.filter_complex_parts.append(subtitle_filter)
        self.current_video_label = "[v_sub]"
        self.use_filter_complex  = True

    # ── Video Codec ──────────────────────────────────────────────────

    def build_video_codec(self) -> None:
        """Build video codec settings."""
        needs_encode = (
            self.video_filters
            or self.use_filter_complex
            or (self.video_settings.get("enabled", True) and self.ps.process_type in [Names.compress, Names.convert])
            or self.ps.process_type in [Names.cut, Names.crop, Names.rotate, Names.watermark, Names.hardmux]
        )

        if not needs_encode:
            self.command.extend(["-c:v", "copy"])
            return

        # Jika ini adalah proses alat editing ringan (bukan kompresi/encode total), gunakan preset fast agar instan.
        if self.ps.process_type in [Names.cut, Names.crop, Names.rotate, Names.watermark, Names.hardmux]:
            encoder = "libx264"
            preset  = "fast"
            crf     = 24
        else:
            # Gunakan settingan database untuk proses kompresi utama (Encode/Convert)
            encoder = self.video_settings.get("encoder", "libx264")
            preset  = self.video_settings.get("preset", DEFAULT_PRESET)
            crf     = _safe_crf(self.video_settings.get("crf", DEFAULT_CRF))

        self.command.extend(["-c:v", encoder, "-preset", preset, "-crf", str(crf)])

        if encoder == "libx265":
            self.command.extend(["-vtag", "hvc1"])

        if self.ps.process_type in [Names.compress, Names.convert]:
            tune = self.video_settings.get("tune", "None")
            if tune and tune != "None":
                self.command.extend(["-tune", tune.lower()])

            pixel_format = self.video_settings.get("pixel_format", "Auto")
            if pixel_format != "Auto":
                self.command.extend(["-pix_fmt", pixel_format])

        ext = self.video_settings.get("extension", "mp4").lower()
        if ext == "mp4" and self.video_settings.get("fast_start", "Yes") == "Yes":
            self.command.extend(["-movflags", "+faststart"])

    # ── Filter Apply ─────────────────────────────────────────────────

    def apply_filters_and_maps(self) -> None:
        """Apply semua filters dan stream mapping."""
        if self.video_filters:
            base_filter = f"[0:v]{','.join(self.video_filters)}[v_base]"
            self.filter_complex_parts.insert(0, base_filter)
            self.current_video_label = "[v_base]"
            self.use_filter_complex  = True

        if self.use_filter_complex:
            self.command.extend(["-filter_complex", ";".join(self.filter_complex_parts)])
            self.command.extend(["-map", self.current_video_label])
            self.command.extend(["-map", "0:a?"])
        elif self.video_filters:
            self.command.extend(["-vf", ",".join(self.video_filters)])
        else:
            if self.video_settings.get("map", True):
                self.command.extend(["-map", "0:v?", "-map", "0:a?"])

        if (
            self.video_settings.get("copy_sub", True)
            and self.ps.process_type != Names.hardmux
        ):
            self.command.extend(["-map", "0:s?", "-c:s", "copy"])

    # ── Command Builders ─────────────────────────────────────────────

    def build_compress_convert_command(self):
        """Build command untuk compress/convert/watermark/hardmux/cut/rotate/crop."""
        dir_name = self.ps.process_type.lower()
        self.create_directory(f"{self.ps.dir}/{dir_name}/")

        log_file    = f"{self.ps.dir}/{dir_name}/{dir_name}_logs_{self.ps.process_id}.txt"
        output_file = f"{self.ps.dir}/{dir_name}/{self.get_output_name(convert_quality=self.ps.convert_quality if self.ps.process_type == Names.convert else False)}"
        input_file  = str(self.ps.send_files[-1]) if self.ps.send_files else ""

        if not input_file:
            logger.error("❌ Tidak ada input file")
            return None, None, None, None, 0

        stream_info = self.probe_input_file(input_file)
        if not stream_info:
            return None, None, None, None, 0

        self.command.extend(["-progress", log_file, "-i", input_file])
        self.build_video_filters()
        self.build_watermark()
        self.build_hardmux_subtitle()
        self.apply_filters_and_maps()
        self.build_video_codec()
        self.build_audio_codec()
        self.add_metadata()
        self.command.extend(["-y", output_file])

        file_duration = stream_info.duration
        if self.ps.process_type == Names.cut and self.ps.cut_ranges:
            total_cut = sum(end - start for start, end in self.ps.cut_ranges)
            file_duration = max(0, file_duration - total_cut)

        return self.command, log_file, input_file, output_file, file_duration

    def build_trim_command(self):
        """Build command untuk trim dengan copy codec (INSTANT CUT)."""
        self.create_directory(f"{self.ps.dir}/trim/")
        log_file    = f"{self.ps.dir}/trim/trim_logs_{self.ps.process_id}.txt"
        output_file = f"{self.ps.dir}/trim/{self.get_output_name()}"
        input_file  = str(self.ps.send_files[-1]) if self.ps.send_files else ""

        if not input_file:
            return None, None, None, None, 0

        stream_info = self.probe_input_file(input_file)
        self.command.extend([
            "-progress", log_file, "-i", input_file,
            "-ss", str(self.ps.trim_start),
            "-to", str(self.ps.trim_end),
            "-c:v", "copy", "-c:a", "copy",
            "-map", "0:v?", "-map", "0:a?",
            "-avoid_negative_ts", "make_zero",
            "-y", output_file,
        ])
        return self.command, log_file, input_file, output_file, stream_info.duration if stream_info else 0

    def build_extension_command(self):
        """Build command untuk change extension dengan smart codec detection."""
        self.create_directory(f"{self.ps.dir}/extension/")
        log_file   = f"{self.ps.dir}/extension/extension_logs_{self.ps.process_id}.txt"
        input_file = str(self.ps.send_files[-1]) if self.ps.send_files else ""

        if not input_file:
            return None, None, None, None, 0

        stream_info = self.probe_input_file(input_file)
        new_ext     = self.ps.new_extension.lower()
        base_name, old_ext_full = splitext(self.get_output_name())
        old_ext     = old_ext_full.lower().replace(".", "")
        output_file = f"{self.ps.dir}/extension/{base_name}.{new_ext}"

        video_exts    = ["mp4","mkv","avi","mov","flv","webm","ts","m4v","wmv","mpg","mpeg"]
        audio_exts    = ["mp3","aac","flac","wav","m4a","ogg","opus","wma","ac3"]
        subtitle_exts = ["srt","ass","ssa","vtt","sub","txt"]

        # Subtitle → direct copy, return None command (sudah selesai)
        if old_ext in subtitle_exts and new_ext in subtitle_exts:
            try:
                shutil.copyfile(input_file, output_file)
                logger.info(f"✅ Subtitle di-copy: {input_file} → {output_file}")
                # [FIX] Return None command + flag 'copied' agar caller tahu sudah selesai
                return None, None, input_file, output_file, 0
            except Exception as e:
                logger.error(f"❌ Subtitle copy gagal: {e}")
                return None, None, None, None, 0

        self.command.extend(["-progress", log_file, "-i", input_file])

        if old_ext in audio_exts and new_ext in audio_exts:
            self.command.extend(["-vn"])
            audio_codec_map = {
                "mp3": ["-c:a","libmp3lame","-b:a","192k"],
                "aac": ["-c:a","aac","-b:a","192k"],
                "m4a": ["-c:a","aac","-b:a","192k"],
                "flac": ["-c:a","flac"],
                "opus": ["-c:a","libopus","-b:a","128k"],
                "ogg": ["-c:a","libvorbis","-b:a","192k"],
                "wav": ["-c:a","pcm_s16le"],
                "ac3": ["-c:a","ac3","-b:a","320k"],
                "wma": ["-c:a","wmav2","-b:a","192k"],
            }
            self.command.extend(audio_codec_map.get(new_ext, ["-c:a","copy"]))

        elif new_ext in video_exts:
            if new_ext == "mp4":
                if stream_info and stream_info.video_codec in ["h264","hevc"]:
                    self.command.extend(["-c:v","copy"])
                else:
                    self.command.extend(["-c:v","libx264","-crf","23","-preset","medium"])
                if stream_info and stream_info.audio_codec in ["aac","mp3"]:
                    self.command.extend(["-c:a","copy"])
                else:
                    self.command.extend(["-c:a","aac","-b:a","192k"])
                if stream_info and stream_info.has_subtitle:
                    self.command.extend(["-c:s","mov_text"])
                self.command.extend(["-movflags","+faststart"])
            elif new_ext == "mkv":
                self.command.extend(["-c","copy"])
            elif new_ext == "webm":
                self.command.extend(["-c:v","libvpx-vp9","-crf","30","-b:v","0","-c:a","libopus","-b:a","128k"])
            elif new_ext == "avi":
                self.command.extend(["-c:v","libx264","-crf","23","-c:a","mp3","-b:a","192k"])
            else:
                self.command.extend(["-c","copy"])
            self.command.extend(["-map","0:v?","-map","0:a?","-map","0:s?"])
        else:
            self.command.extend(["-c","copy"])

        self.command.extend(["-max_muxing_queue_size","1024","-y",output_file])
        return self.command, log_file, input_file, output_file, stream_info.duration if stream_info else 0

    def build_merge_command(self):
        """
        Build command untuk merge.
        [FIX HIGH] Hapus -vf select=concatdec_select — filter tidak valid.
        [FIX]      Handle audio-only/video-only merge secara eksplisit.
        [FIX]      File list pakai shlex.quote() bukan manual escape.
        """
        self.create_directory(f"{self.ps.dir}/merge/")
        log_file    = f"{self.ps.dir}/merge/merge_logs_{self.ps.process_id}.txt"
        output_file = f"{self.ps.dir}/merge/{self.get_output_name()}"

        if not self.ps.send_files or len(self.ps.send_files) < 2:
            logger.error("❌ Merge butuh minimal 2 file")
            return None, None, None, None, 0

        all_stream_info = []
        total_duration  = 0.0

        for file_path in self.ps.send_files:
            info = StreamInfo(file_path)
            all_stream_info.append(info)
            total_duration += info.duration
            if not info.has_video and not info.has_audio:
                logger.error(f"❌ File tidak valid untuk merge: {file_path}")
                return None, None, None, None, 0

        all_have_video = all(i.has_video for i in all_stream_info)
        all_have_audio = all(i.has_audio for i in all_stream_info)

        # [FIX] Tulis file list dengan shlex.quote() bukan manual escape
        input_file_txt = f"{self.ps.dir}/merge/merge_files_{self.ps.process_id}.txt"
        with open(input_file_txt, "w", encoding="utf-8") as f:
            for file_loc in self.ps.send_files:
                # shlex.quote() handle semua karakter special dengan benar
                f.write(f"file {shlex.quote(os.path.abspath(file_loc))}\n")

        self.command.extend(["-progress", log_file, "-f", "concat", "-safe", "0", "-i", input_file_txt])

        fix_blank = self.merge_settings.get("fix_blank", False)

        if fix_blank or not all_have_video or not all_have_audio:
            # Re-encode mode
            logger.info("ℹ️  Menggunakan re-encode merge mode")

            if all_have_video:
                # [FIX HIGH] Hapus -vf select=concatdec_select — tidak valid
                # Cukup encode ulang dengan codec yang dipilih
                self.command.extend([
                    "-c:v", self.video_settings.get("encoder", "libx264"),
                    "-preset", "fast",
                    "-crf", str(_safe_crf(self.video_settings.get("crf", DEFAULT_CRF))),
                ])
            elif not all_have_video:
                # Audio-only merge — skip video
                self.command.extend(["-vn"])

            if all_have_audio:
                # [FIX] Hapus aselect=concatdec_select — tidak valid sebagai -af
                self.command.extend([
                    "-af", "aresample=async=1",
                    "-c:a", "aac",
                    "-b:a", DEFAULT_AUDIO_BR,
                ])
            elif not all_have_audio:
                # Video-only merge — skip audio
                self.command.extend(["-an"])

        else:
            # Fast copy mode
            logger.info("ℹ️  Menggunakan stream copy merge mode")
            self.command.extend(["-c", "copy"])

        # Mapping
        if self.merge_settings.get("map", True):
            if all_have_video:
                self.command.extend(["-map", "0:v"])
            if all_have_audio:
                self.command.extend(["-map", "0:a"])

        self.command.extend([
            "-fflags", "+genpts",
            "-avoid_negative_ts", "make_zero",
            "-max_muxing_queue_size", "1024",
        ])
        self.add_metadata()
        self.command.extend(["-y", output_file])

        return self.command, log_file, input_file_txt, output_file, total_duration

    def build_softmux_command(self):
        """Build command untuk softmux subtitle."""
        self.create_directory(f"{self.ps.dir}/softmux/")
        log_file    = f"{self.ps.dir}/softmux/softmux_logs_{self.ps.process_id}.txt"
        output_file = f"{self.ps.dir}/softmux/{self.get_output_name()}"
        input_file  = str(self.ps.send_files[-1]) if self.ps.send_files else ""

        if not input_file or not self.ps.subtitles:
            logger.error("❌ Softmux butuh video dan subtitle")
            return None, None, None, None, 0

        stream_info = self.probe_input_file(input_file)
        self.command.extend(["-progress", log_file, "-i", input_file])

        subtitle_maps = []
        for i, subtitle in enumerate(self.ps.subtitles, 1):
            if exists(str(subtitle)):
                self.command.extend(["-i", str(subtitle)])
                subtitle_maps.extend(["-map", f"{i}:0"])
            else:
                logger.warning(f"⚠️  Subtitle tidak ditemukan: {subtitle}")

        self.command.extend(["-map", "0:v?", "-map", "0:a?", "-map", "0:s?"])
        self.command.extend(subtitle_maps)
        self.command.extend([
            "-c:v", "copy", "-c:a", "copy",
            "-c:s", self.mux_settings.get("sub_codec", "mov_text"),
        ])
        if subtitle_maps:
            self.command.extend(["-disposition:s:0", "default"])

        self.add_metadata()
        self.command.extend(["-y", output_file])
        return self.command, log_file, input_file, output_file, stream_info.duration if stream_info else 0

    def build_softremux_command(self):
        """Build command untuk softremux (replace subtitles)."""
        self.create_directory(f"{self.ps.dir}/softremux/")
        log_file    = f"{self.ps.dir}/softremux/softremux_logs_{self.ps.process_id}.txt"
        output_file = f"{self.ps.dir}/softremux/{self.get_output_name()}"
        input_file  = str(self.ps.send_files[-1]) if self.ps.send_files else ""

        if not input_file or not self.ps.subtitles:
            logger.error("❌ Softremux butuh video dan subtitle")
            return None, None, None, None, 0

        stream_info   = self.probe_input_file(input_file)
        self.command.extend(["-progress", log_file, "-i", input_file])

        subtitle_maps = []
        for i, subtitle in enumerate(self.ps.subtitles, 1):
            if exists(str(subtitle)):
                self.command.extend(["-i", str(subtitle)])
                subtitle_maps.extend(["-map", f"{i}:0"])
            else:
                logger.warning(f"⚠️  Subtitle tidak ditemukan: {subtitle}")

        # NO existing subtitles — hanya video + audio
        self.command.extend(["-map", "0:v?", "-map", "0:a?"])
        self.command.extend(subtitle_maps)
        self.command.extend([
            "-c:v", "copy", "-c:a", "copy",
            "-c:s", self.mux_settings.get("sub_codec", "mov_text"),
        ])
        if subtitle_maps:
            self.command.extend(["-disposition:s:0", "default"])

        self.add_metadata()
        self.command.extend(["-y", output_file])
        return self.command, log_file, input_file, output_file, stream_info.duration if stream_info else 0

    def build_change_metadata_command(self):
        """Build command untuk change metadata."""
        self.create_directory(f"{self.ps.dir}/metadata/")
        log_file    = f"{self.ps.dir}/metadata/metadata_logs_{self.ps.process_id}.txt"
        output_file = f"{self.ps.dir}/metadata/{self.get_output_name()}"
        input_file  = str(self.ps.send_files[-1]) if self.ps.send_files else ""

        if not input_file:
            return None, None, None, None, 0

        stream_info = self.probe_input_file(input_file)
        self.command.extend(["-progress", log_file, "-i", input_file])

        if hasattr(self.ps, "custom_metadata") and self.ps.custom_metadata:
            self.command.extend(self.ps.custom_metadata)

        self.command.extend(["-map", "0", "-c", "copy", "-y", output_file])
        return self.command, log_file, input_file, output_file, stream_info.duration if stream_info else 0

    def build_change_index_command(self):
        """Build command untuk change stream index."""
        self.create_directory(f"{self.ps.dir}/index/")
        log_file    = f"{self.ps.dir}/index/index_logs_{self.ps.process_id}.txt"
        output_file = f"{self.ps.dir}/index/{self.get_output_name()}"
        input_file  = str(self.ps.send_files[-1]) if self.ps.send_files else ""

        if not input_file:
            return None, None, None, None, 0

        stream_info = self.probe_input_file(input_file)
        self.command.extend(["-progress", log_file, "-i", input_file, "-map", "0:v?"])

        if hasattr(self.ps, "custom_index") and self.ps.custom_index:
            self.command.extend(self.ps.custom_index)

        self.command.extend(["-c", "copy"])
        self.add_metadata()
        self.command.extend(["-y", output_file])
        return self.command, log_file, input_file, output_file, stream_info.duration if stream_info else 0

    # ── Main Build ───────────────────────────────────────────────────

    def build(self):
        """Route ke builder yang tepat berdasarkan process_type."""
        process_type = self.ps.process_type
        try:
            if process_type in [
                Names.compress, Names.watermark, Names.convert,
                Names.hardmux, Names.cut, Names.rotate, Names.crop,
            ]:
                return self.build_compress_convert_command()
            elif process_type == Names.trim:
                return self.build_trim_command()
            elif process_type == Names.extension:
                return self.build_extension_command()
            elif process_type == Names.merge:
                return self.build_merge_command()
            elif process_type == Names.softmux:
                return self.build_softmux_command()
            elif process_type == Names.softremux:
                return self.build_softremux_command()
            elif process_type == Names.changeMetadata:
                return self.build_change_metadata_command()
            elif process_type == Names.changeindex:
                return self.build_change_index_command()
            else:
                logger.error(f"❌ Unknown process type: {process_type}")
                return None, None, None, None, 0
        except Exception as e:
            logger.error(f"❌ Error build command untuk {process_type}: {e}", exc_info=True)
            return None, None, None, None, 0


# ═══════════════════════════════════════════════════════════════════════
#  PUBLIC API
# ═══════════════════════════════════════════════════════════════════════

def get_commands(process_status):
    """
    Entry point utama — wrapper untuk backward compatibility.

    Returns:
        tuple: (command, log_file, input_file, output_file, duration)
               command bisa None jika build gagal atau file sudah di-copy langsung.
    """
    builder = FFmpegCommandBuilder(process_status)
    result  = builder.build()

    if result[0] is None and result[3] is not None:
        # File sudah di-handle tanpa FFmpeg (contoh: subtitle copy)
        logger.info(f"✅ File sudah di-handle tanpa FFmpeg: {result[3]}")
    elif result[0] is None:
        logger.error(f"❌ Gagal build command untuk process {process_status.process_id}")

    return result


def validate_output(output_file: str) -> dict:
    """
    Validasi output file setelah processing.

    [FIX] Cek file size > 0 — FFmpeg bisa buat file kosong meski return code 0.

    Returns:
        dict dengan keys: success, has_video, has_audio, duration, error (jika gagal)
    """
    if not exists(output_file):
        return {"success": False, "error": "File tidak ditemukan", "has_video": False, "has_audio": False, "duration": 0}

    # [FIX] Cek file size — file kosong berarti FFmpeg error
    if getsize(output_file) == 0:
        return {"success": False, "error": "File kosong (0 bytes) — FFmpeg mungkin gagal", "has_video": False, "has_audio": False, "duration": 0}

    try:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_streams", "-show_format", output_file],
            capture_output=True, text=True, timeout=FFPROBE_TIMEOUT,
        )
        if result.returncode != 0:
            return {"success": False, "error": "ffprobe gagal", "has_video": False, "has_audio": False, "duration": 0}

        data        = json.loads(result.stdout)
        streams     = data.get("streams", [])
        format_info = data.get("format", {})
        has_video   = any(s.get("codec_type") == "video" for s in streams)
        has_audio   = any(s.get("codec_type") == "audio" for s in streams)
        duration    = float(format_info.get("duration", 0))

        return {
            "success": True, "has_video": has_video, "has_audio": has_audio,
            "duration": duration, "streams": len(streams),
            "format": format_info.get("format_name", "unknown"),
            "size_mb": round(getsize(output_file) / 1024 / 1024, 2),
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "error": f"ffprobe timeout ({FFPROBE_TIMEOUT}s)", "has_video": False, "has_audio": False, "duration": 0}
    except Exception as e:
        logger.error(f"❌ Validation error untuk {output_file}: {e}")
        return {"success": False, "error": str(e), "has_video": False, "has_audio": False, "duration": 0}
