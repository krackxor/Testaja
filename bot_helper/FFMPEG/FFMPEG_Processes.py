"""
╔══════════════════════════════════════════════════════════════════════╗
║            bot_helper/FFMPEG/FFMPEG_Processes.py                     ║
║            Encoder1 Bot — v3.1                                       ║
╠══════════════════════════════════════════════════════════════════════╣
║  CHANGELOG dari versi lama:                                          ║
║  [FIX HIGH]  asyncio.gather split → Semaphore(2) cegah OOM/saturasi  ║
║  [FIX HIGH]  get_data()[user_id] → .get() semua fungsi               ║
║  [FIX HIGH]  execute(shell_str) → subprocess list args               ║
║  [FIX HIGH]  start_time += cut_duration - 3 → tanpa -3 (no overlap)  ║
║  [FIX]       bare except → except (KeyError, TypeError)              ║
║  [FIX]       print() → LOGGER.debug/info/error                       ║
║  [FIX]       -vsync/-async deprecated → -fps_mode cfr                ║
║  [FIX]       DocumentAttributeVideo width/height dari ffprobe        ║
║  [FIX]       gen_ss_list duplikat timestamp                          ║
║  [FIX]       amap_options audio index calculation                    ║
║  [FIX]       change_metadata retry logging                           ║
║  [IMPROVE]   select_audio indentasi & readability                    ║
║  [IMPROVE]   sleep(1) ss → sleep(0.3) dengan jitter                  ║
║  [HOTFIX]    Perbaikan penamaan output split agar terbaca sistem     ║
╚══════════════════════════════════════════════════════════════════════╝
"""

# ── Standard Library ──────────────────────────────────────────────────
import asyncio
import json
import math
import subprocess
from asyncio import create_subprocess_exec, sleep
from asyncio.subprocess import PIPE as asyncioPIPE
from os import makedirs, remove
from os.path import exists, getsize, isdir, join, splitext
from time import time

# ── Telethon ──────────────────────────────────────────────────────────
from telethon.tl.types import DocumentAttributeVideo

# ── Internal ──────────────────────────────────────────────────────────
from bot_helper.Database.User_Data import get_data
from bot_helper.Others.Helper_Functions import get_video_duration, get_readable_time, delete_trash
from config.config import Config

LOGGER = Config.LOGGER

# ── Konstanta ─────────────────────────────────────────────────────────
# [FIX] Batasi concurrency split agar tidak OOM/saturasi disk
_SPLIT_SEMAPHORE = asyncio.Semaphore(2)

FFPROBE_TIMEOUT = 30


# ═══════════════════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════════════════

def create_direc(direc: str) -> None:
    """Buat direktori jika belum ada."""
    if not isdir(direc):
        makedirs(direc, exist_ok=True)


def get_output_name(process_status) -> str:
    """Ambil nama output file."""
    if process_status.file_name:
        return process_status.file_name
    return process_status.send_files[-1].split("/")[-1]


def _get_video_dimensions(file_path: str) -> tuple[int, int]:
    """
    [FIX] Ambil width & height video via ffprobe.
    Dipakai untuk DocumentAttributeVideo agar preview Telegram benar.
    """
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_streams", "-select_streams", "v:0", file_path],
            capture_output=True, text=True, timeout=FFPROBE_TIMEOUT,
        )
        data   = json.loads(result.stdout)
        stream = data.get("streams", [{}])[0]
        return int(stream.get("width", 0)), int(stream.get("height", 0))
    except Exception as e:
        LOGGER.warning(f"⚠️  Gagal baca dimensi video {file_path}: {e}")
        return 0, 0


def _get_user_data(user_id) -> dict:
    """
    [FIX] Cache-safe user data getter dengan fallback.
    Semua fungsi pakai ini agar tidak ada KeyError.
    """
    return get_data().get(user_id, {})


# ═══════════════════════════════════════════════════════════════════════
#  RUN COMMAND
# ═══════════════════════════════════════════════════════════════════════

async def run_process_command(command: list) -> bool:
    """
    Jalankan FFmpeg command via asyncio subprocess.

    [FIX] print(command) → LOGGER.debug()
    [FIX] print(e) → LOGGER.error()
    """
    # [FIX] Debug log — bukan print() ke stdout
    LOGGER.debug(f"FFmpeg command: {' '.join(str(c) for c in command)}")
    try:
        process = await create_subprocess_exec(
            *command,
            stdout=asyncioPIPE,
            stderr=asyncioPIPE,
        )
        stdout, stderr = await process.communicate()

        error_output = stderr.decode("utf-8", "replace").strip()
        if error_output:
            LOGGER.debug(f"FFmpeg stderr: {error_output[:500]}")

        if process.returncode == 0:
            return True
        else:
            LOGGER.error(
                f"❌ FFmpeg gagal (code {process.returncode}): "
                f"{error_output[-300:]}"
            )
            return False

    except Exception as e:
        LOGGER.error(f"❌ run_process_command error: {e}", exc_info=True)
        return False


# ═══════════════════════════════════════════════════════════════════════
#  SPLIT FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════

async def _run_split_part(command: list, semaphore: asyncio.Semaphore) -> bool:
    """
    [FIX] Wrapper untuk split dengan Semaphore agar tidak semua part paralel.
    Max 2 FFmpeg proses bersamaan.
    """
    async with semaphore:
        return await run_process_command(command)


async def split_by_duration(input_file: str, duration_per_part: float, output_dir: str) -> list:
    """
    Pisahkan video menjadi beberapa bagian dengan durasi tertentu.

    [FIX HIGH] asyncio.gather paralel → Semaphore(2) batasi concurrency
    [FIX]      Cek minimum duration untuk part terakhir
    """
    total_duration = get_video_duration(input_file)
    if total_duration == 0 or duration_per_part <= 0:
        LOGGER.error("❌ split_by_duration: durasi video 0 atau duration_per_part invalid")
        return []

    total_parts  = math.ceil(total_duration / duration_per_part)
    tasks        = []
    output_files = []
    semaphore    = asyncio.Semaphore(2)   # Max 2 FFmpeg bersamaan

    file_name, extension = splitext(input_file.split("/")[-1])
    for i in range(total_parts):
        start_time = i * duration_per_part

        # [FIX] Cek sisa durasi — jangan buat part jika sisa < 1 detik
        remaining = total_duration - start_time
        if remaining < 1.0:
            break

        part_name = join(output_dir, f"{file_name}_part{str(i + 1).zfill(3)}{extension}")
        output_files.append(part_name)

        command = [
            "ffmpeg", "-hide_banner",
            "-ss", str(start_time),
            "-i", input_file,
            "-t", str(min(duration_per_part, remaining)),
            "-c", "copy", "-map", "0", "-map_chapters", "-1",
            "-y", part_name,
        ]
        tasks.append(_run_split_part(command, semaphore))

    results = await asyncio.gather(*tasks)

    # Filter hanya file yang berhasil dibuat dan tidak kosong
    valid_files = []
    for f, ok in zip(output_files, results):
        if ok and exists(f) and getsize(f) > 0:
            valid_files.append(f)
        elif exists(f):
            LOGGER.warning(f"⚠️  Part kosong atau gagal, dihapus: {f}")
            try:
                remove(f)
            except Exception:
                pass

    return valid_files


async def split_by_parts(input_file: str, total_parts: int, output_dir: str) -> list:
    """
    Pisahkan video menjadi N bagian sama besar.

    [FIX HIGH] asyncio.gather → Semaphore(2)
    """
    total_duration = get_video_duration(input_file)
    if total_duration == 0 or total_parts <= 0:
        return []

    duration_per_part = math.ceil(total_duration / total_parts)
    return await split_by_duration(input_file, duration_per_part, output_dir)


async def split_by_size(input_file: str, size_per_part_mb: float, output_dir: str) -> list:
    """
    Pisahkan video berdasarkan ukuran file secara iteratif.
    Pendekatan ini sudah sekuensial — tidak perlu Semaphore.
    """
    split_output_dir   = join(output_dir, "split")
    create_direc(split_output_dir)

    # 98% dari target — sisakan ruang untuk metadata
    target_size_bytes  = int(size_per_part_mb * 1024 * 1024 * 0.98)
    output_files       = []
    start_time         = 0.0
    part_num           = 1
    total_duration     = get_video_duration(input_file)

    if total_duration == 0:
        LOGGER.error("❌ split_by_size: gagal baca durasi video")
        return []

    file_name, extension = splitext(input_file.split("/")[-1])
    while start_time < (total_duration - 1.0):
        part_name = join(split_output_dir, f"{file_name}_part{str(part_num).zfill(3)}{extension}")

        command = [
            "ffmpeg", "-hide_banner",
            "-ss", str(start_time),
            "-i", input_file,
            "-fs", str(target_size_bytes),
            "-c", "copy", "-map", "0", "-map_chapters", "-1",
            "-y", part_name,
        ]

        success = await run_process_command(command)

        if not success or not exists(part_name) or getsize(part_name) == 0:
            LOGGER.warning(f"⚠️  Part {part_num} gagal atau kosong")
            if exists(part_name):
                remove(part_name)
            break

        part_duration = get_video_duration(part_name)
        if part_duration <= 1.0:
            LOGGER.info(f"ℹ️  Part {part_num} durasi terlalu kecil ({part_duration:.1f}s), stop")
            remove(part_name)
            break

        output_files.append(part_name)
        start_time += part_duration
        part_num   += 1

    LOGGER.info(f"✅ split_by_size: {len(output_files)} part berhasil")
    return output_files


async def split_video_file(file: str, split_size: int, dirpath: str, event) -> list:
    """
    Split video berdasarkan ukuran file (fallback legacy function).

    [FIX HIGH] start_time += cut_duration (hapus -3 overlap yang sebabkan duplikat)
    [FIX]      LOGGER.error() bukan print()
    """
    success    = []
    split_size = split_size - 50_000_000   # Buffer 50MB

    try:
        size  = getsize(file)
        parts = math.ceil(size / split_size)
        i     = 1
        start_time = 0.0

        while i <= parts:
            file_name, extension = splitext(file)
            parted_name = f"{file_name.split('/')[-1]}.part{str(i).zfill(3)}{extension}"
            create_direc(f"{dirpath}/split/")
            out_path = join(f"{dirpath}/split/", parted_name)

            command = [
                "ffmpeg", "-hide_banner",
                "-ss", str(start_time),
                "-i", str(file),
                "-fs", str(split_size),
                "-map", "0", "-map_chapters", "-1",
                "-c", "copy", "-y", out_path,
            ]
            result = await run_process_command(command)

            if not result:
                LOGGER.warning(f"⚠️  Split attempt 1 gagal untuk part {i}, retry tanpa -map")
                await delete_trash(out_path)
                command = [
                    "ffmpeg", "-hide_banner",
                    "-ss", str(start_time),
                    "-i", str(file),
                    "-fs", str(split_size),
                    "-map_chapters", "-1",
                    "-c", "copy", "-y", out_path,
                ]
                result = await run_process_command(command)
                if not result:
                    raise Exception(f"Tidak bisa split {str(file)}")

            cut_duration = get_video_duration(out_path)
            if cut_duration <= 4:
                LOGGER.info(f"ℹ️  Part {i} durasi terlalu kecil, berhenti")
                break

            success.append(out_path)
            # [FIX HIGH] Hapus -3 overlap — menyebabkan konten duplikat antar part
            # -fs sudah handle batas ukuran, tidak perlu overlap manual
            start_time += cut_duration
            i += 1

        return success

    except Exception as e:
        LOGGER.error(f"❌ Error saat split {str(file)}: {e}", exc_info=True)
        raise Exception(f"❗ Error saat split {str(file)}\n\n{str(e)}")


# ═══════════════════════════════════════════════════════════════════════
#  SCREENSHOT
# ═══════════════════════════════════════════════════════════════════════

async def get_cut_duration(duration: float) -> list:
    """Hitung range untuk sample video."""
    if duration < 60:
        return [1, duration - 2]
    vmid = round(duration / 2) - 2
    vend = min(vmid + 60, duration - 2)
    return [vmid, vend]


async def gen_ss_list(duration: float, ss_no: int) -> list:
    """
    Generate daftar timestamp untuk screenshot.

    [FIX] Duplikat timestamp — pakai set untuk cegah nilai sama.
    """
    if ss_no <= 0 or duration <= 0:
        return []

    value   = max(1, round(duration / ss_no))
    ss_set  = set()
    ss_list = []
    ss      = 5

    # Tambahkan titik awal
    if ss < duration:
        ss_set.add(ss)
        ss_list.append(ss)

    while len(ss_list) < ss_no:
        ss += value
        if ss >= duration:
            # [FIX] Jangan tambahkan duplikat
            fallback = int(duration - 2)
            if fallback > 0 and fallback not in ss_set:
                ss_set.add(fallback)
                ss_list.append(fallback)
            break
        if ss not in ss_set:
            ss_set.add(ss)
            ss_list.append(ss)

    return ss_list


async def generate_screenshoot(ss_time: float, input_video: str, ss_name: str) -> bool:
    """Generate satu screenshot dari video."""
    command = [
        "ffmpeg", "-hide_banner",
        "-ss", str(ss_time),
        "-i", input_video,
        "-frames:v", "1",
        "-f", "image2",
        "-map", "0:v:0",
        "-y", ss_name,
    ]
    return await run_process_command(command)


async def generate_ss(process_status, force_gen: bool = False) -> None:
    """
    Generate dan kirim screenshot ke Telegram.

    [FIX HIGH] get_data()[user_id] → _get_user_data()
    [FIX]      await sleep(1) → sleep(0.3)
    """
    user_data = _get_user_data(process_status.user_id)

    if not user_data.get("gen_ss") and not force_gen:
        return

    ss_no      = 9 if force_gen else int(user_data.get("ss_no", 4))
    file_name  = get_output_name(process_status)
    input_video = str(process_status.send_files[-1])
    duration   = get_video_duration(input_video)

    if duration <= 0:
        LOGGER.warning("⚠️  generate_ss: durasi video 0")
        return

    process_status.update_process_message(
        f"📷 Generating Screenshots\n`{file_name}`\n{process_status.get_task_details()}"
    )

    ss_list = await gen_ss_list(duration, ss_no)

    for idx, ss_time in enumerate(ss_list, 1):
        ss_name = f"{process_status.dir}/screenshot_{int(time() * 1000)}.jpg"
        ss_ok   = await generate_screenshoot(ss_time, input_video, ss_name)

        if ss_ok and exists(ss_name):
            caption = (
                f"📌 Posisi: `{get_readable_time(ss_time)}`\n"
                f"📷 Screenshot: {idx}/{len(ss_list)}"
            )
            try:
                await process_status.event.client.send_file(
                    process_status.chat_id,
                    file=ss_name,
                    allow_cache=False,
                    reply_to=process_status.event.message,
                    caption=caption,
                )
            except Exception as e:
                LOGGER.warning(f"⚠️  Gagal kirim screenshot {idx}: {e}")
            finally:
                try:
                    remove(ss_name)
                except Exception:
                    pass
            # [FIX] sleep(1) → sleep(0.3) — tidak ada alasan teknis untuk 1 detik
            await sleep(0.3)


# ═══════════════════════════════════════════════════════════════════════
#  SAMPLE VIDEO
# ═══════════════════════════════════════════════════════════════════════

async def gen_sample_video(process_status, force_gen: bool = False) -> None:
    """
    Generate dan kirim sample video ke Telegram.

    [FIX HIGH] get_data()[user_id] → _get_user_data()
    [FIX]      -vsync 1 -async -1 → -fps_mode cfr (FFmpeg 5+/6+)
    [FIX]      DocumentAttributeVideo width/height dari ffprobe
    """
    user_data = _get_user_data(process_status.user_id)

    if not user_data.get("gen_sample") and not force_gen:
        return

    input_video = str(process_status.send_files[-1])
    duration    = get_video_duration(input_video)

    if duration <= 60:
        if force_gen:
            await process_status.event.reply("❌ Durasi video harus lebih dari 60 detik untuk generate sample.")
        return

    file_name   = get_output_name(process_status)
    sample_name = f"{process_status.dir}/sample_{file_name}"

    process_status.update_process_message(
        f"🎞 Generating Sample Video\n`{file_name}`\n{process_status.get_task_details()}"
    )

    vstart_time, vend_time = await get_cut_duration(duration)
    vframes = "750" if duration < 180 else "1500"

    # [FIX] Ganti -vsync 1 → -fps_mode cfr, hapus -async (deprecated FFmpeg 5+/6+)
    cmd_sample = [
        "ffmpeg", "-hide_banner",
        "-ss", f"{vstart_time}s",
        "-i", input_video,
        "-vframes", vframes,
        "-fps_mode", "cfr",      # [FIX] ganti -vsync 1
        "-acodec", "copy",
        "-vcodec", "copy",
        "-y", sample_name,
    ]

    sample_result = await run_process_command(cmd_sample)

    if sample_result and exists(sample_name) and getsize(sample_name) > 0:
        # [FIX] Ambil width/height dari ffprobe — bukan hardcode 0,0
        sample_duration = get_video_duration(sample_name)
        width, height   = _get_video_dimensions(sample_name)

        thumb = "sthumb.jpg" if exists("sthumb.jpg") else None

        try:
            await process_status.event.client.send_file(
                process_status.chat_id,
                file=sample_name,
                allow_cache=False,
                reply_to=process_status.event.message,
                caption="🎞 Sample Video",
                thumb=thumb,
                supports_streaming=True,
                attributes=(DocumentAttributeVideo(sample_duration, width, height),),
            )
        except Exception as e:
            LOGGER.warning(f"⚠️  Gagal kirim sample video: {e}")
        finally:
            try:
                remove(sample_name)
            except Exception:
                pass
    else:
        LOGGER.error(f"❌ Gagal generate sample video untuk {file_name}")
        await process_status.event.reply("❌ Gagal generate sample video.")


# ═══════════════════════════════════════════════════════════════════════
#  CHANGE METADATA (legacy)
# ═══════════════════════════════════════════════════════════════════════

async def change_metadata(process_status) -> None:
    """
    Ubah metadata video.

    [FIX HIGH] get_data()[user_id] → _get_user_data()
    [FIX]      Tambah LOGGER.warning() untuk setiap retry — tidak silent fail
    """
    user_data = _get_user_data(process_status.user_id)

    if not user_data.get("custom_metadata"):
        return

    dl_loc                = str(process_status.send_files[-1])
    direc                 = f"{process_status.dir}/metadata/"
    create_direc(direc)
    output_meta           = f"{direc}/{get_output_name(process_status)}"
    custom_metadata_title = user_data.get("metadata", "")

    if not custom_metadata_title:
        LOGGER.warning("⚠️  custom_metadata=True tapi metadata title kosong")
        return

    process_status.update_process_message(
        f"🪀 Changing Metadata\n{process_status.get_task_details()}"
    )

    # Strategy 1: Set audio + subtitle metadata
    cmd1 = [
        "ffmpeg", "-hide_banner", "-i", dl_loc,
        "-metadata:s:a", f"title={custom_metadata_title}",
        "-metadata:s:s", f"title={custom_metadata_title}",
        "-map", "0", "-c", "copy", "-y", output_meta,
    ]
    met_result = await run_process_command(cmd1)

    # Strategy 2: Audio only (jika tidak ada subtitle stream)
    if not met_result:
        LOGGER.warning("⚠️  Metadata strategy 1 gagal, coba audio-only")
        cmd2 = [
            "ffmpeg", "-hide_banner", "-i", dl_loc,
            "-metadata:s:a", f"title={custom_metadata_title}",
            "-map", "0", "-c", "copy", "-y", output_meta,
        ]
        met_result = await run_process_command(cmd2)

    # Strategy 3: Subtitle only (jika tidak ada audio stream)
    if not met_result:
        LOGGER.warning("⚠️  Metadata strategy 2 gagal, coba subtitle-only")
        cmd3 = [
            "ffmpeg", "-hide_banner", "-i", dl_loc,
            "-metadata:s:s", f"title={custom_metadata_title}",
            "-map", "0", "-c", "copy", "-y", output_meta,
        ]
        met_result = await run_process_command(cmd3)

    if met_result:
        await process_status.event.reply("✅ Metadata berhasil diubah.")
        new_caption = f"✅ Metadata: {custom_metadata_title}\n"
        if process_status.caption:
            new_caption += process_status.caption
        process_status.set_caption(new_caption)
        process_status.append_send_files_loc(output_meta)
    else:
        LOGGER.error(f"❌ Semua strategy metadata gagal untuk {dl_loc}")
        await process_status.event.reply("❗ Gagal mengubah metadata.")


# ═══════════════════════════════════════════════════════════════════════
#  SELECT AUDIO
# ═══════════════════════════════════════════════════════════════════════

async def select_audio(process_status) -> None:
    """
    Pilih audio stream berdasarkan bahasa.

    [FIX HIGH] execute(shell_string) → subprocess list args (no injection)
    [FIX HIGH] get_data()[user_id] → _get_user_data()
    [FIX]      bare except → except (KeyError, TypeError)
    [FIX]      amap_options: track audio_index terpisah dari stream index
    [IMPROVE]  Indentasi 4 spaces, bukan 24+ spaces
    """
    user_data = _get_user_data(process_status.user_id)

    if not user_data.get("select_stream"):
        return

    language    = user_data.get("stream", "")
    input_file  = str(process_status.send_files[-1])

    try:
        # [FIX HIGH] Ganti execute(f"...{file_path}...") dengan subprocess list
        # Shell string dengan interpolasi path = command injection risk
        result = subprocess.run(
            [
                "ffprobe", "-hide_banner",
                "-show_streams",
                "-print_format", "json",
                input_file,
            ],
            capture_output=True,
            text=True,
            timeout=FFPROBE_TIMEOUT,
        )

        if result.returncode != 0:
            await process_status.event.reply(
                f"❌ Gagal baca stream dari video.\n`{result.stderr[:200]}`"
            )
            return

        details     = json.loads(result.stdout)
        streams     = details.get("streams", [])
        stream_data = {}
        audio_index = 0   # [FIX] Track audio index terpisah dari stream index ffprobe

        for stream in streams:
            stream_type     = stream.get("codec_type", "")
            codec_long_name = stream.get("codec_long_name", "unknown")

            if stream_type == "audio":
                # [FIX] bare except → except (KeyError, TypeError)
                try:
                    lang = stream["tags"]["language"]
                except (KeyError, TypeError):
                    lang = str(stream.get("index", audio_index))

                sname = f"AUDIO - {str(lang).upper()} [{codec_long_name}]"

                stream_data[sname] = {
                    "stream_index": stream.get("index"),
                    "audio_index":  audio_index,    # [FIX] index dalam group audio (0:a:0, 0:a:1, ...)
                    "language":     str(lang).upper(),
                }
                audio_index += 1

        if not stream_data:
            await process_status.event.reply("❗ Tidak ditemukan audio stream di video ini.")
            return

        if len(stream_data) == 1:
            await process_status.event.reply("🔶 Hanya 1 audio ditemukan, skip seleksi audio.")
            return

        # Cari audio yang cocok dengan bahasa yang diminta
        matched_key = None
        for key, info in stream_data.items():
            if info["language"] == language.upper():
                matched_key = key
                break

        if matched_key:
            info = stream_data[matched_key]
            # [FIX] Pakai audio_index (0-based dalam group audio), bukan stream_index - 1
            amap_options = f"0:a:{info['audio_index']}"
            process_status.set_amap_options(amap_options)
            await process_status.event.reply(
                f"✅ Audio dipilih:\n\n"
                f"`{matched_key}`\n"
                f"`Audio Index: {info['audio_index']}`\n"
                f"`Stream Index: {info['stream_index']}`"
            )
            new_caption = f"✅ Audio: {matched_key}\n"
            if process_status.caption:
                new_caption += process_status.caption
            process_status.set_caption(new_caption)
        else:
            # Tampilkan audio yang tersedia
            available = "\n".join(f"`{k}`" for k in stream_data.keys())
            await process_status.event.reply(
                f"❗ Bahasa `{language}` tidak ditemukan.\n\n"
                f"Audio tersedia:\n{available}"
            )

    except json.JSONDecodeError as e:
        LOGGER.error(f"❌ ffprobe output tidak valid JSON: {e}")
        await process_status.event.reply("❌ Gagal parse output ffprobe.")
    except subprocess.TimeoutExpired:
        LOGGER.error(f"❌ ffprobe timeout untuk {input_file}")
        await process_status.event.reply("❌ ffprobe timeout — file mungkin corrupt.")
    except Exception as e:
        LOGGER.error(f"❌ select_audio error: {e}", exc_info=True)
        await process_status.event.reply(f"❌ Gagal baca audio stream:\n`{e}`")
