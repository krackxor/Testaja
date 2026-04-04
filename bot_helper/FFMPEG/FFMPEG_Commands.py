"""
╔══════════════════════════════════════════════════════════════════════╗
║            bot_helper/FFMPEG/FFMPEG_Commands.py                      ║
║            Encoder1 Bot — v3.2                                       ║
╠══════════════════════════════════════════════════════════════════════╣
║  CHANGELOG dari versi lama:                                          ║
║  [FIX CRITICAL] Memasukkan kembali semua instruksi untuk Split,      ║
║                 Extract, Autocrop, GenSample, dan GenSS.             ║
║  [NEW]      Alat cepat (/trim, /cut) menggunakan Stream Copy instan  ║
║  [NEW]      Perintah modifikasi piksel (Watermark/Crop/Rotate) kebal ║
║             dari settingan global agar menghindari re-encode lambat. ║
║  [SECURITY] get_data()[user_id] → .get() — tidak crash KeyError      ║
║  [SECURITY] drawtext escape lebih ketat — cegah filter injection     ║
╚══════════════════════════════════════════════════════════════════════╝
"""

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

from bot_helper.Database.User_Data import get_data
from bot_helper.Others.Helper_Functions import get_video_duration
from bot_helper.Others.Names import Names

logger = logging.getLogger(__name__)

FFPROBE_TIMEOUT  = 30       
DEFAULT_CRF      = 23
DEFAULT_PRESET   = "medium"
DEFAULT_AUDIO_BR = "192k"

_FFMPEG_FILTER_ESCAPE = str.maketrans({
    "'": r"\'", ":": r"\:", "[": r"\[", "]": r"\]",
    ";": r"\;", ",": r"\,", "\\": "\\\\",
})

def create_direc(direc: str) -> None:
    if not isdir(direc): makedirs(direc, exist_ok=True)

def _sanitize_filename(name: str) -> str:
    normalized = unicodedata.normalize("NFKD", name)
    ascii_name = normalized.encode("ascii", "ignore").decode("ascii")
    safe = re.sub(r'[^\w\s\-.]', '', ascii_name).strip()
    return re.sub(r'\s+', ' ', safe) or "output"

def _safe_crf(value, default: int = DEFAULT_CRF) -> int:
    try: return max(0, min(51, int(str(value).strip())))
    except (ValueError, TypeError): return default

def _escape_ffmpeg_filter_text(text: str) -> str:
    return text.translate(_FFMPEG_FILTER_ESCAPE)

def _validate_metadata_string(metadata_str: str) -> list[str]:
    result = []
    entries = re.split(r'[\n;]+', metadata_str)
    for entry in entries:
        entry = entry.strip()
        if not entry: continue
        if '=' not in entry: continue
        key, _, value = entry.partition('=')
        key, value = key.strip(), value.strip()
        if not re.match(r'^[a-zA-Z0-9_]+$', key): continue
        if value.startswith('"') and value.endswith('"'): value = value[1:-1]
        elif value.startswith("'") and value.endswith("'"): value = value[1:-1]
        result.extend(["-metadata", f"{key}={value}"])
    return result

def _escape_subtitle_path(path: str) -> str:
    abs_path = os.path.abspath(path)
    return abs_path.replace("\\", "\\\\\\\\").replace(":", "\\:").replace("'", "\\'")

class StreamInfo:
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
        try:
            result = subprocess.run(["ffprobe", "-v", "quiet", "-print_format", "json", "-show_streams", "-show_format", self.file_path], capture_output=True, text=True, timeout=FFPROBE_TIMEOUT)
            if result.returncode != 0: return
            data        = json.loads(result.stdout)
            for stream in data.get("streams", []):
                codec_type = stream.get("codec_type")
                if codec_type == "video":
                    self.has_video, self.video_codec, self.width, self.height = True, stream.get("codec_name"), int(stream.get("width", 0)), int(stream.get("height", 0))
                elif codec_type == "audio":
                    self.has_audio, self.audio_codec = True, stream.get("codec_name")
                elif codec_type == "subtitle":
                    self.has_subtitle = True
            format_info = data.get("format", {})
            self.duration  = float(format_info.get("duration", 0))
            self.container = format_info.get("format_name", "").split(",")[0]
        except Exception as e: logger.error(f"❌ Error probe {self.file_path}: {e}", exc_info=True)

class FFmpegCommandBuilder:
    def __init__(self, process_status):
        self.ps        = process_status
        self.user_id   = process_status.user_id
        self.user_data = get_data().get(self.user_id, {})
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

    def create_directory(self, direc: str) -> None: create_direc(direc)

    def get_output_name(self, convert_quality=False) -> str:
        extension = self.video_settings.get("extension", "mp4").lower()
        if self.ps.file_name: out_file_name, _ = splitext(self.ps.file_name)
        elif self.ps.send_files: out_file_name, _ = splitext(self.ps.send_files[-1].split("/")[-1])
        else: out_file_name = f"output_{self.ps.process_id}"
        out_file_name = _sanitize_filename(out_file_name)
        if convert_quality: out_file_name = f"{out_file_name}_{convert_quality}p"
        return f"{out_file_name}.{extension}"

    def probe_input_file(self, file_path: str) -> "StreamInfo | None":
        if not exists(file_path): return None
        self.stream_info = StreamInfo(file_path); return self.stream_info

    def add_metadata(self) -> None:
        if not self.metadata_settings.get("enabled", False): return
        mode = self.metadata_settings.get("mode", "preset")
        if mode == "preset":
            presets = self.metadata_settings.get("preset", {})
            for key, value in presets.items():
                if value and re.match(r'^[a-zA-Z0-9_]+$', key): self.command.extend(["-metadata", f"{key}={str(value)}"])
        elif mode == "custom":
            custom_string = self.metadata_settings.get("custom", "")
            if custom_string:
                validated = _validate_metadata_string(custom_string)
                if validated: self.command.extend(validated)

    def build_audio_filters(self) -> None:
        if not self.audio_settings.get("enabled", False) and self.ps.process_type not in [Names.cut]: return
        if self.ps.process_type == Names.cut and self.ps.cut_ranges:
            select_parts = [f"between(t,{start},{end})" for start, end in self.ps.cut_ranges]
            self.audio_filters.append(f"aselect='not({'+'.join(select_parts)})',asetpts=N/SR/TB")
        normalization = self.audio_settings.get("normalization", "Off")
        if normalization == "loudnorm": self.audio_filters.append("loudnorm=I=-16:TP=-1.5:LRA=11")
        elif normalization == "dynaudnorm": self.audio_filters.append("dynaudnorm")
        custom_filter = self.audio_settings.get("filter", "Off")
        if custom_filter == "highpass": self.audio_filters.append("highpass=f=100")
        elif custom_filter == "lowpass": self.audio_filters.append("lowpass=f=3000")

    def build_audio_codec(self) -> None:
        if not self.audio_settings.get("enabled", False) and self.ps.process_type not in [Names.cut]:
            self.command.extend(["-c:a", "copy"]); return
        codec = self.audio_settings.get("codec", "Auto")
        if self.ps.process_type == Names.cut: codec = "aac"
        
        # [NEW FIX] Mendukung Dubbing Audio Khusus dari /encode
        if hasattr(self.ps, "custom_dub_audio") and self.ps.custom_dub_audio:
            if os.path.exists(self.ps.custom_dub_audio):
                codec = "aac"  # Wajib encode ulang jika ada dubbing
            
        if codec == "Auto":
            if self.stream_info and self.stream_info.has_audio: self.command.extend(["-c:a", "copy"])
            else: self.command.extend(["-c:a", "aac", "-b:a", DEFAULT_AUDIO_BR])
            return
        if codec == "copy" and self.ps.process_type != Names.cut:
            self.command.extend(["-c:a", "copy"]); return
        if self.audio_filters: self.command.extend(["-af", ",".join(self.audio_filters)])
        codec_map = {"aac": "aac", "mp3": "libmp3lame", "opus": "libopus", "vorbis": "libvorbis", "flac": "flac", "ac3": "ac3"}
        self.command.extend(["-c:a", codec_map.get(codec, codec)])
        if codec == "aac":
            profile = self.audio_settings.get("codec_profile", "Auto")
            if profile != "Auto": self.command.extend(["-profile:a", profile.replace("-", "_")])
        if codec not in ["flac", "pcm"]:
            bitrate = self.audio_settings.get("bitrate", "Auto")
            if bitrate != "Auto": self.command.extend(["-b:a", bitrate])
            else: self.command.extend(["-b:a", {"aac":"192k","mp3":"192k","opus":"128k","vorbis":"192k","ac3":"320k"}.get(codec, DEFAULT_AUDIO_BR)])
        downmix, channels = self.audio_settings.get("downmix", "Off"), self.audio_settings.get("channels", "Auto")
        if downmix != "Off": self.command.extend(["-ac", "1" if downmix == "mono" else "2"])
        elif channels != "Auto": self.command.extend(["-ac", str({"mono": 1, "stereo": 2, "2.1": 3, "3.1": 4, "5.1": 6, "7.1": 8}.get(channels, 2))])
        samplerate = self.audio_settings.get("samplerate", "Auto")
        if samplerate != "Auto": self.command.extend(["-ar", samplerate])

    def build_video_filters(self) -> None:
        if self.ps.process_type == Names.cut and self.ps.cut_ranges:
            select_parts = [f"between(t,{start},{end})" for start, end in self.ps.cut_ranges]
            self.video_filters.append(f"select='not({'+'.join(select_parts)})',setpts=N/FRAME_RATE/TB")
        if self.ps.process_type == Names.convert and self.ps.convert_quality: self.video_filters.append(f"scale=-2:{self.ps.convert_quality}")
        if self.ps.process_type == Names.rotate and self.ps.rotate_option: self.video_filters.append(self.ps.rotate_option)
        if self.ps.process_type == Names.crop and self.ps.crop_params: self.video_filters.append(self.ps.crop_params)
        if self.ps.process_type in [Names.convert, Names.compress]:
            resolution = self.video_settings.get("resolution", "Auto")
            if resolution != "Auto":
                if "x" in resolution: self.video_filters.append(f"scale={resolution}")
                elif resolution.isdigit(): self.video_filters.append(f"scale=-2:{resolution}")

    def build_watermark(self) -> None:
        if hasattr(self.ps, "custom_watermark") and self.ps.custom_watermark: wm_settings = self.ps.custom_watermark
        else:
            if not self.watermark_settings.get("enabled") or self.ps.process_type not in [Names.compress, Names.convert, Names.watermark]: return
            wm_settings = self.watermark_settings
            
        wm_type = wm_settings.get("type", "image"); duration_settings = wm_settings.get(wm_type, {}).get("duration", {}); mode = duration_settings.get("mode", "full")
        duration_filter = ""
        if mode == "range": duration_filter = f":enable='between(t,{duration_settings.get('from',0)},{duration_settings.get('to',99999)})'"
        elif mode == "interval": duration_filter = f":enable='lt(mod(t,{duration_settings.get('interval',60)}),1)'"

        position_map_overlay = {"top_left": "5:5", "top_center": "(main_w-overlay_w)/2:5", "top_right": "main_w-overlay_w-5:5", "middle_left": "5:(main_h-overlay_h)/2", "middle_center": "(main_w-overlay_w)/2:(main_h-overlay_h)/2", "middle_right": "main_w-overlay_w-5:(main_h-overlay_h)/2", "bottom_left": "5:main_h-overlay_h-5", "bottom_center": "(main_w-overlay_w)/2:main_h-overlay_h-5", "bottom_right": "main_w-overlay_w-5:main_h-overlay_h-5"}
        position_map_text = {"top_left": "x=10:y=10", "top_center": "x=(w-text_w)/2:y=10", "top_right": "x=w-text_w-10:y=10", "middle_left": "x=10:y=(h-text_h)/2", "middle_center": "x=(w-text_w)/2:y=(h-text_h)/2", "middle_right": "x=w-text_w-10:y=(h-text_h)/2", "bottom_left": "x=10:y=h-text_h-10", "bottom_center": "x=(w-text_w)/2:y=h-text_h-10", "bottom_right": "x=w-text_w-10:y=h-text_h-10"}

        if wm_type == "image":
            watermark_path = wm_settings.get("image", {}).get("path", f"./userdata/{self.user_id}_watermark.jpg")
            if not exists(watermark_path): return
            self.command.extend(["-i", watermark_path])
            position = position_map_overlay.get(wm_settings.get("image", {}).get("position", "bottom_right"), "main_w-overlay_w-5:main_h-overlay_h-5")
            has_dub = hasattr(self.ps, "custom_dub_audio") and self.ps.custom_dub_audio
            wm_stream_idx = "[2:v]" if has_dub else "[1:v]"
            self.filter_complex_parts.append(f"{self.current_video_label}{wm_stream_idx}overlay={position}{duration_filter}[v_wm]")
            self.current_video_label = "[v_wm]"
            self.use_filter_complex  = True
        elif wm_type == "text":
            text_settings = wm_settings.get("text", {})
            raw_text = text_settings.get("content", "")
            if not raw_text: return
            text_content = _escape_ffmpeg_filter_text(raw_text)
            font_files = glob.glob(f"./userdata/{self.user_id}_watermark_font.*")
            custom_font = text_settings.get("font_path")
            if custom_font and os.path.exists(custom_font): font_path = custom_font
            else: font_path = font_files[0] if font_files else "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
            position = position_map_text.get(text_settings.get("position", "bottom_right"), "x=w-text_w-10:y=h-text_h-10")
            font_color = text_settings.get("font_color", "white")
            if not re.match(r'^[a-zA-Z0-9#@]+$', font_color): font_color = "white"
            font_size = int(text_settings.get('size', text_settings.get('font_size', 24)))
            self.filter_complex_parts.append(f"{self.current_video_label}drawtext=text='{text_content}':fontfile='{_escape_ffmpeg_filter_text(font_path)}':fontsize={font_size}:fontcolor={font_color}:{position}{duration_filter}[v_wm]")
            self.current_video_label = "[v_wm]"
            self.use_filter_complex  = True

    def build_hardmux_subtitle(self) -> None:
        if self.ps.process_type not in [Names.hardmux, Names.compress, Names.convert]: return
        if not hasattr(self.ps, "subtitles") or not self.ps.subtitles: return
        sub_file = str(self.ps.subtitles[-1])
        if not exists(sub_file): return
        sub_path_escaped = _escape_subtitle_path(sub_file)
        if sub_file.lower().rsplit(".", 1)[-1] in ["srt", "ass", "ssa"]: self.filter_complex_parts.append(f"{self.current_video_label}subtitles='{sub_path_escaped}'[v_sub]")
        else: self.filter_complex_parts.append(f"{self.current_video_label}subtitles='{sub_path_escaped}':force_style='FontSize=24'[v_sub]")
        self.current_video_label = "[v_sub]"
        self.use_filter_complex  = True

    def build_video_codec(self) -> None:
        needs_encode = (self.video_filters or self.use_filter_complex or (self.video_settings.get("enabled", True) and self.ps.process_type in [Names.compress, Names.convert]) or self.ps.process_type in [Names.cut, Names.crop, Names.rotate, Names.watermark, Names.hardmux])
        if not needs_encode: self.command.extend(["-c:v", "copy"]); return

        if self.ps.process_type in [Names.cut, Names.crop, Names.rotate, Names.watermark, Names.hardmux]: encoder, preset, crf = "libx264", "fast", 24
        else: encoder, preset, crf = self.video_settings.get("encoder", "libx264"), self.video_settings.get("preset", DEFAULT_PRESET), _safe_crf(self.video_settings.get("crf", DEFAULT_CRF))

        self.command.extend(["-c:v", encoder, "-preset", preset, "-crf", str(crf)])
        if encoder == "libx265": self.command.extend(["-vtag", "hvc1"])

        if self.ps.process_type in [Names.compress, Names.convert]:
            tune = self.video_settings.get("tune", "None")
            if tune and tune != "None": self.command.extend(["-tune", tune.lower()])
            pixel_format = self.video_settings.get("pixel_format", "Auto")
            if pixel_format != "Auto": self.command.extend(["-pix_fmt", pixel_format])

        if self.video_settings.get("extension", "mp4").lower() == "mp4" and self.video_settings.get("fast_start", "Yes") == "Yes":
            self.command.extend(["-movflags", "+faststart"])

    def apply_filters_and_maps(self) -> None:
        has_dubbing = hasattr(self.ps, "custom_dub_audio") and self.ps.custom_dub_audio
        if has_dubbing and os.path.exists(self.ps.custom_dub_audio):
            self.command.extend(["-i", self.ps.custom_dub_audio])
            self.current_audio_label = "[1:a]"
            
        if self.video_filters:
            self.filter_complex_parts.insert(0, f"[0:v]{','.join(self.video_filters)}[v_base]")
            self.current_video_label = "[v_base]"
            self.use_filter_complex  = True

        if self.use_filter_complex:
            self.command.extend(["-filter_complex", ";".join(self.filter_complex_parts), "-map", self.current_video_label])
            self.command.extend(["-map", "1:a" if has_dubbing else "0:a?"])
        elif self.video_filters:
            self.command.extend(["-vf", ",".join(self.video_filters)])
            if has_dubbing: self.command.extend(["-map", "0:v", "-map", "1:a"])
        else:
            if self.video_settings.get("map", True): self.command.extend(["-map", "0:v?", "-map", "1:a" if has_dubbing else "0:a?"])

        if self.video_settings.get("copy_sub", True) and self.ps.process_type != Names.hardmux:
            self.command.extend(["-map", "0:s?", "-c:s", "copy"])
            
        if has_dubbing: self.command.extend(["-shortest"])

    # ── Command Builders ─────────────────────────────────────────────

    def build_compress_convert_command(self):
        dir_name = self.ps.process_type.lower(); self.create_directory(f"{self.ps.dir}/{dir_name}/")
        log_file = f"{self.ps.dir}/{dir_name}/{dir_name}_logs_{self.ps.process_id}.txt"
        output_file = f"{self.ps.dir}/{dir_name}/{self.get_output_name(convert_quality=self.ps.convert_quality if self.ps.process_type == Names.convert else False)}"
        input_file = str(self.ps.send_files[-1]) if self.ps.send_files else ""
        if not input_file: return None, None, None, None, 0
        stream_info = self.probe_input_file(input_file)
        if not stream_info: return None, None, None, None, 0

        self.command.extend(["-progress", log_file, "-i", input_file])
        self.build_video_filters(); self.build_watermark(); self.build_hardmux_subtitle(); self.apply_filters_and_maps(); self.build_video_codec(); self.build_audio_codec(); self.add_metadata()
        self.command.extend(["-y", output_file])
        
        file_duration = stream_info.duration
        if self.ps.process_type == Names.cut and self.ps.cut_ranges:
            total_cut = sum(end - start for start, end in self.ps.cut_ranges)
            file_duration = max(0, file_duration - total_cut)
        return self.command, log_file, input_file, output_file, file_duration

    def build_trim_command(self):
        self.create_directory(f"{self.ps.dir}/trim/")
        log_file = f"{self.ps.dir}/trim/trim_logs_{self.ps.process_id}.txt"
        output_file = f"{self.ps.dir}/trim/{self.get_output_name()}"
        input_file = str(self.ps.send_files[-1]) if self.ps.send_files else ""
        if not input_file: return None, None, None, None, 0
        stream_info = self.probe_input_file(input_file)
        self.command.extend(["-progress", log_file, "-i", input_file, "-ss", str(self.ps.trim_start), "-to", str(self.ps.trim_end), "-c:v", "copy", "-c:a", "copy", "-map", "0:v?", "-map", "0:a?", "-avoid_negative_ts", "make_zero", "-y", output_file])
        return self.command, log_file, input_file, output_file, stream_info.duration if stream_info else 0
        
    def build_split_command(self):
        self.create_directory(f"{self.ps.dir}/split/")
        log_file = f"{self.ps.dir}/split/split_logs_{self.ps.process_id}.txt"
        output_file = f"{self.ps.dir}/split/{self.get_output_name()}"
        input_file = str(self.ps.send_files[-1]) if self.ps.send_files else ""
        if not input_file: return None, None, None, None, 0
        stream_info = self.probe_input_file(input_file)
        
        name, ext = os.path.splitext(output_file)
        output_pattern = f"{name}_%03d{ext}"
        
        self.command.extend(["-progress", log_file, "-i", input_file, "-c", "copy", "-map", "0", "-f", "segment", "-reset_timestamps", "1"])
        if self.ps.split_mode == "parts":
            part_duration = max(1, int(stream_info.duration / max(1, int(self.ps.split_value))))
            self.command.extend(["-segment_time", str(part_duration)])
        elif self.ps.split_mode == "duration":
            self.command.extend(["-segment_time", str(int(self.ps.split_value) * 60)])
        elif self.ps.split_mode == "size":
            self.command.extend(["-segment_time", "1800"]) # Fallback to 30 mins
        self.command.extend(["-y", output_pattern])
        return self.command, log_file, input_file, output_pattern, stream_info.duration if stream_info else 0

    def build_extract_command(self):
        self.create_directory(f"{self.ps.dir}/extract/")
        log_file = f"{self.ps.dir}/extract/extract_logs_{self.ps.process_id}.txt"
        input_file = str(self.ps.send_files[-1]) if self.ps.send_files else ""
        if not input_file: return None, None, None, None, 0
        stream_info = self.probe_input_file(input_file)
        
        base_name, _ = os.path.splitext(self.get_output_name())
        output_file = f"{self.ps.dir}/extract/{base_name}.mkv"
        self.command.extend(["-progress", log_file, "-i", input_file])
        if hasattr(self.ps, "extract_maps") and self.ps.extract_maps:
            for m in self.ps.extract_maps: self.command.extend(["-map", m])
        else: self.command.extend(["-map", "0"])
        self.command.extend(["-c", "copy", "-y", output_file])
        return self.command, log_file, input_file, output_file, stream_info.duration if stream_info else 0

    def build_autocrop_command(self):
        self.create_directory(f"{self.ps.dir}/autocrop/")
        log_file = f"{self.ps.dir}/autocrop/autocrop_logs_{self.ps.process_id}.txt"
        output_file = f"{self.ps.dir}/autocrop/{self.get_output_name()}"
        input_file = str(self.ps.send_files[-1]) if self.ps.send_files else ""
        if not input_file: return None, None, None, None, 0
        stream_info = self.probe_input_file(input_file)
        
        try:
            detect_cmd = ["ffmpeg", "-hide_banner", "-i", input_file, "-vf", "cropdetect=24:16:0", "-vframes", "100", "-f", "null", "-"]
            result = subprocess.run(detect_cmd, capture_output=True, text=True)
            crops = re.findall(r'crop=[0-9]+:[0-9]+:[0-9]+:[0-9]+', result.stderr)
            crop_param = crops[-1] if crops else "crop=iw:ih"
        except Exception:
            crop_param = "crop=iw:ih"
            
        self.command.extend(["-progress", log_file, "-i", input_file, "-vf", crop_param, "-c:v", "libx264", "-preset", "fast", "-c:a", "copy", "-y", output_file])
        return self.command, log_file, input_file, output_file, stream_info.duration if stream_info else 0

    def build_gensample_command(self):
        self.create_directory(f"{self.ps.dir}/sample/")
        log_file = f"{self.ps.dir}/sample/sample_logs_{self.ps.process_id}.txt"
        output_file = f"{self.ps.dir}/sample/{self.get_output_name()}"
        input_file = str(self.ps.send_files[-1]) if self.ps.send_files else ""
        if not input_file: return None, None, None, None, 0
        stream_info = self.probe_input_file(input_file)
        self.command.extend(["-progress", log_file, "-i", input_file, "-ss", "00:00:05", "-t", "30", "-c", "copy", "-y", output_file])
        return self.command, log_file, input_file, output_file, 30

    def build_genss_command(self):
        self.create_directory(f"{self.ps.dir}/ss/")
        log_file = f"{self.ps.dir}/ss/ss_logs_{self.ps.process_id}.txt"
        base_name, _ = os.path.splitext(self.get_output_name())
        output_file = f"{self.ps.dir}/ss/{base_name}_%03d.jpg"
        input_file = str(self.ps.send_files[-1]) if self.ps.send_files else ""
        if not input_file: return None, None, None, None, 0
        stream_info = self.probe_input_file(input_file)
        
        ss_no = self.user_data.get("ss_no", 5)
        self.command.extend(["-progress", log_file, "-i", input_file, "-vf", f"fps={ss_no}/{max(1, stream_info.duration)}", "-y", output_file])
        return self.command, log_file, input_file, output_file, stream_info.duration if stream_info else 0

    def build_extension_command(self):
        self.create_directory(f"{self.ps.dir}/extension/")
        log_file   = f"{self.ps.dir}/extension/extension_logs_{self.ps.process_id}.txt"
        input_file = str(self.ps.send_files[-1]) if self.ps.send_files else ""

        if not input_file: return None, None, None, None, 0
        stream_info = self.probe_input_file(input_file)
        new_ext     = self.ps.new_extension.lower()
        base_name, old_ext_full = splitext(self.get_output_name())
        old_ext     = old_ext_full.lower().replace(".", "")
        output_file = f"{self.ps.dir}/extension/{base_name}.{new_ext}"

        video_exts    = ["mp4","mkv","avi","mov","flv","webm","ts","m4v","wmv","mpg","mpeg"]
        audio_exts    = ["mp3","aac","flac","wav","m4a","ogg","opus","wma","ac3"]
        subtitle_exts = ["srt","ass","ssa","vtt","sub","txt"]

        if old_ext in subtitle_exts and new_ext in subtitle_exts:
            try:
                shutil.copyfile(input_file, output_file)
                return None, None, input_file, output_file, 0
            except Exception as e:
                return None, None, None, None, 0

        self.command.extend(["-progress", log_file, "-i", input_file])
        if old_ext in audio_exts and new_ext in audio_exts:
            self.command.extend(["-vn"])
            audio_codec_map = {"mp3": ["-c:a","libmp3lame","-b:a","192k"], "aac": ["-c:a","aac","-b:a","192k"], "m4a": ["-c:a","aac","-b:a","192k"], "flac": ["-c:a","flac"], "opus": ["-c:a","libopus","-b:a","128k"], "ogg": ["-c:a","libvorbis","-b:a","192k"], "wav": ["-c:a","pcm_s16le"], "ac3": ["-c:a","ac3","-b:a","320k"], "wma": ["-c:a","wmav2","-b:a","192k"]}
            self.command.extend(audio_codec_map.get(new_ext, ["-c:a","copy"]))
        elif new_ext in video_exts:
            if new_ext == "mp4":
                if stream_info and stream_info.video_codec in ["h264","hevc"]: self.command.extend(["-c:v","copy"])
                else: self.command.extend(["-c:v","libx264","-crf","23","-preset","medium"])
                if stream_info and stream_info.audio_codec in ["aac","mp3"]: self.command.extend(["-c:a","copy"])
                else: self.command.extend(["-c:a","aac","-b:a","192k"])
                if stream_info and stream_info.has_subtitle: self.command.extend(["-c:s","mov_text"])
                self.command.extend(["-movflags","+faststart"])
            elif new_ext == "mkv": self.command.extend(["-c","copy"])
            elif new_ext == "webm": self.command.extend(["-c:v","libvpx-vp9","-crf","30","-b:v","0","-c:a","libopus","-b:a","128k"])
            elif new_ext == "avi": self.command.extend(["-c:v","libx264","-crf","23","-c:a","mp3","-b:a","192k"])
            else: self.command.extend(["-c","copy"])
            self.command.extend(["-map","0:v?","-map","0:a?","-map","0:s?"])
        else: self.command.extend(["-c","copy"])

        self.command.extend(["-max_muxing_queue_size","1024","-y",output_file])
        return self.command, log_file, input_file, output_file, stream_info.duration if stream_info else 0

    def build_merge_command(self):
        self.create_directory(f"{self.ps.dir}/merge/")
        log_file    = f"{self.ps.dir}/merge/merge_logs_{self.ps.process_id}.txt"
        output_file = f"{self.ps.dir}/merge/{self.get_output_name()}"

        if not self.ps.send_files or len(self.ps.send_files) < 2: return None, None, None, None, 0
        all_stream_info, total_duration  = [], 0.0
        for file_path in self.ps.send_files:
            info = StreamInfo(file_path); all_stream_info.append(info); total_duration += info.duration
            if not info.has_video and not info.has_audio: return None, None, None, None, 0
        all_have_video = all(i.has_video for i in all_stream_info)
        all_have_audio = all(i.has_audio for i in all_stream_info)

        input_file_txt = f"{self.ps.dir}/merge/merge_files_{self.ps.process_id}.txt"
        with open(input_file_txt, "w", encoding="utf-8") as f:
            for file_loc in self.ps.send_files: f.write(f"file {shlex.quote(os.path.abspath(file_loc))}\n")

        self.command.extend(["-progress", log_file, "-f", "concat", "-safe", "0", "-i", input_file_txt])
        fix_blank = self.merge_settings.get("fix_blank", False)
        if fix_blank or not all_have_video or not all_have_audio:
            if all_have_video: self.command.extend(["-c:v", self.video_settings.get("encoder", "libx264"), "-preset", "fast", "-crf", str(_safe_crf(self.video_settings.get("crf", DEFAULT_CRF)))])
            elif not all_have_video: self.command.extend(["-vn"])
            if all_have_audio: self.command.extend(["-af", "aresample=async=1", "-c:a", "aac", "-b:a", DEFAULT_AUDIO_BR])
            elif not all_have_audio: self.command.extend(["-an"])
        else: self.command.extend(["-c", "copy"])

        if self.merge_settings.get("map", True):
            if all_have_video: self.command.extend(["-map", "0:v"])
            if all_have_audio: self.command.extend(["-map", "0:a"])

        self.command.extend(["-fflags", "+genpts", "-avoid_negative_ts", "make_zero", "-max_muxing_queue_size", "1024"])
        self.add_metadata()
        self.command.extend(["-y", output_file])
        return self.command, log_file, input_file_txt, output_file, total_duration

    def build_softmux_command(self):
        self.create_directory(f"{self.ps.dir}/softmux/")
        log_file    = f"{self.ps.dir}/softmux/softmux_logs_{self.ps.process_id}.txt"
        output_file = f"{self.ps.dir}/softmux/{self.get_output_name()}"
        input_file  = str(self.ps.send_files[-1]) if self.ps.send_files else ""
        if not input_file or not self.ps.subtitles: return None, None, None, None, 0
        stream_info = self.probe_input_file(input_file)
        self.command.extend(["-progress", log_file, "-i", input_file])
        subtitle_maps = []
        for i, subtitle in enumerate(self.ps.subtitles, 1):
            if exists(str(subtitle)):
                self.command.extend(["-i", str(subtitle)])
                subtitle_maps.extend(["-map", f"{i}:0"])
        self.command.extend(["-map", "0:v?", "-map", "0:a?", "-map", "0:s?"])
        self.command.extend(subtitle_maps)
        self.command.extend(["-c:v", "copy", "-c:a", "copy", "-c:s", self.mux_settings.get("sub_codec", "mov_text")])
        if subtitle_maps: self.command.extend(["-disposition:s:0", "default"])
        self.add_metadata()
        self.command.extend(["-y", output_file])
        return self.command, log_file, input_file, output_file, stream_info.duration if stream_info else 0

    def build_softremux_command(self):
        self.create_directory(f"{self.ps.dir}/softremux/")
        log_file    = f"{self.ps.dir}/softremux/softremux_logs_{self.ps.process_id}.txt"
        output_file = f"{self.ps.dir}/softremux/{self.get_output_name()}"
        input_file  = str(self.ps.send_files[-1]) if self.ps.send_files else ""
        if not input_file or not self.ps.subtitles: return None, None, None, None, 0
        stream_info   = self.probe_input_file(input_file)
        self.command.extend(["-progress", log_file, "-i", input_file])
        subtitle_maps = []
        for i, subtitle in enumerate(self.ps.subtitles, 1):
            if exists(str(subtitle)):
                self.command.extend(["-i", str(subtitle)])
                subtitle_maps.extend(["-map", f"{i}:0"])
        self.command.extend(["-map", "0:v?", "-map", "0:a?"])
        self.command.extend(subtitle_maps)
        self.command.extend(["-c:v", "copy", "-c:a", "copy", "-c:s", self.mux_settings.get("sub_codec", "mov_text")])
        if subtitle_maps: self.command.extend(["-disposition:s:0", "default"])
        self.add_metadata()
        self.command.extend(["-y", output_file])
        return self.command, log_file, input_file, output_file, stream_info.duration if stream_info else 0

    def build_change_metadata_command(self):
        self.create_directory(f"{self.ps.dir}/metadata/")
        log_file    = f"{self.ps.dir}/metadata/metadata_logs_{self.ps.process_id}.txt"
        output_file = f"{self.ps.dir}/metadata/{self.get_output_name()}"
        input_file  = str(self.ps.send_files[-1]) if self.ps.send_files else ""
        if not input_file: return None, None, None, None, 0
        stream_info = self.probe_input_file(input_file)
        self.command.extend(["-progress", log_file, "-i", input_file])
        if hasattr(self.ps, "custom_metadata") and self.ps.custom_metadata: self.command.extend(self.ps.custom_metadata)
        self.command.extend(["-map", "0", "-c", "copy", "-y", output_file])
        return self.command, log_file, input_file, output_file, stream_info.duration if stream_info else 0

    def build_change_index_command(self):
        self.create_directory(f"{self.ps.dir}/index/")
        log_file    = f"{self.ps.dir}/index/index_logs_{self.ps.process_id}.txt"
        output_file = f"{self.ps.dir}/index/{self.get_output_name()}"
        input_file  = str(self.ps.send_files[-1]) if self.ps.send_files else ""
        if not input_file: return None, None, None, None, 0
        stream_info = self.probe_input_file(input_file)
        self.command.extend(["-progress", log_file, "-i", input_file, "-map", "0:v?"])
        if hasattr(self.ps, "custom_index") and self.ps.custom_index: self.command.extend(self.ps.custom_index)
        self.command.extend(["-c", "copy"])
        self.add_metadata()
        self.command.extend(["-y", output_file])
        return self.command, log_file, input_file, output_file, stream_info.duration if stream_info else 0

    def build(self):
        process_type = self.ps.process_type
        try:
            if process_type in [Names.compress, Names.watermark, Names.convert, Names.hardmux, Names.cut, Names.rotate, Names.crop]:
                return self.build_compress_convert_command()
            elif process_type == Names.trim: return self.build_trim_command()
            elif process_type == Names.extension: return self.build_extension_command()
            elif process_type == Names.merge: return self.build_merge_command()
            elif process_type == Names.softmux: return self.build_softmux_command()
            elif process_type == Names.softremux: return self.build_softremux_command()
            elif process_type == Names.changeMetadata: return self.build_change_metadata_command()
            elif process_type == Names.changeindex: return self.build_change_index_command()
            elif process_type == Names.split: return self.build_split_command()
            elif process_type == Names.extract: return self.build_extract_command()
            elif process_type == Names.autocrop: return self.build_autocrop_command()
            elif process_type == Names.gensample: return self.build_gensample_command()
            elif process_type == Names.genss: return self.build_genss_command()
            else:
                logger.error(f"❌ Unknown process type: {process_type}")
                return None, None, None, None, 0
        except Exception as e:
            logger.error(f"❌ Error build command untuk {process_type}: {e}", exc_info=True)
            return None, None, None, None, 0

def get_commands(process_status):
    builder = FFmpegCommandBuilder(process_status)
    result  = builder.build()
    if result[0] is None and result[3] is not None: logger.info(f"✅ File sudah di-handle tanpa FFmpeg: {result[3]}")
    elif result[0] is None: logger.error(f"❌ Gagal build command untuk process {process_status.process_id}")
    return result

def validate_output(output_file: str) -> dict:
    if not exists(output_file): return {"success": False, "error": "File tidak ditemukan", "has_video": False, "has_audio": False, "duration": 0}
    if getsize(output_file) == 0: return {"success": False, "error": "File kosong (0 bytes) — FFmpeg mungkin gagal", "has_video": False, "has_audio": False, "duration": 0}
    try:
        result = subprocess.run(["ffprobe", "-v", "quiet", "-print_format", "json", "-show_streams", "-show_format", output_file], capture_output=True, text=True, timeout=FFPROBE_TIMEOUT)
        if result.returncode != 0: return {"success": False, "error": "ffprobe gagal", "has_video": False, "has_audio": False, "duration": 0}
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
    except subprocess.TimeoutExpired: return {"success": False, "error": f"ffprobe timeout ({FFPROBE_TIMEOUT}s)", "has_video": False, "has_audio": False, "duration": 0}
    except Exception as e: return {"success": False, "error": str(e), "has_video": False, "has_audio": False, "duration": 0}
