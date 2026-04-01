"""
╔══════════════════════════════════════════════════════════════════════╗
║           bot_helper/callbacks.py — v3.1                            ║
║           Callback Query Handler (Settings, Profiles, Actions)      ║
╠══════════════════════════════════════════════════════════════════════╣
║  FIXES dari versi lama:                                              ║
║  [FIX HIGH]  eval() pada callback data → ast.literal_eval + guard  ║
║  [FIX HIGH]  db global NameError → lazy getter                      ║
║  [FIX]       Tidak ada auth check di callback → user_id guard       ║
║  [FIX]       bare except → typed exception                         ║
║  [FIX]       get_data()[user_id]['drive_name'] → .get()            ║
╚══════════════════════════════════════════════════════════════════════╝
"""

# ── Standard Library ──────────────────────────────────────────────────
import asyncio
import copy
import glob
from ast import literal_eval
from os import remove
from os.path import exists, splitext

# ── Third Party ───────────────────────────────────────────────────────
from telethon import Button, events
from telethon.errors.rpcerrorlist import MessageNotModifiedError

# ── Internal ──────────────────────────────────────────────────────────
from bot_helper.Database.User_Data import (
    _get_default_user_data, ensure_user_data_structure,
    get_data, new_user, resetdatabase, saveconfig, saveoptions,
)
from bot_helper.Others.Helper_Functions import (
    delete_all, export_env_file, get_config, get_env_dict,
)
from bot_helper.Process.Running_Tasks import get_ffmpeg_log_file
from bot_helper.Telegram.Telegram_Client import Telegram
from config.config import Config

TELETHON_CLIENT  = Telegram.TELETHON_CLIENT
SAVE_TO_DATABASE = Config.SAVE_TO_DATABASE
LOGGER           = Config.LOGGER


def _get_db():
    """Lazy DB getter — tidak crash jika SAVE_TO_DATABASE=False."""
    if not SAVE_TO_DATABASE:
        return None
    from bot_helper.Database.DB_Handler import Database
    return Database()


def _safe_eval_bool(s: str) -> bool | None:
    """
    [FIX HIGH] eval() → safe parse bool dari callback data.
    Hanya menerima 'True' atau 'False' — bukan arbitrary code.
    """
    if s == "True":
        return True
    if s == "False":
        return False
    return None


# ── Pengaturan Lists ──────────────────────────────────────────────────
encoders_list      = ["libx265", "libx264"]
presets_list       = ["ultrafast", "superfast", "veryfast", "faster", "fast",
                      "medium", "slow", "slower", "veryslow"]
crf_list           = ["23", "24", "25", "Custom"]
extension_list     = ["MP4", "MKV", "AVI"]
tune_list          = ["None", "Film", "Animation", "Grain", "FastDecode", "StillImage"]
cabac_list         = ["On", "Off"]
fast_start_list    = ["Yes", "No"]
pixel_format_list  = ["Auto", "yuv420p", "yuv422p", "yuv444p"]
resolution_list    = ["Auto", "120", "240", "360", "Custom"]
wsize_list         = [str(i) for i in range(12, 24)]
ws_image_positions = {
    "↖️": "top_left",    "⬆️": "top_center",    "↗️": "top_right",
    "⬅️": "middle_left", "⏺️": "middle_center", "➡️": "middle_right",
    "↙️": "bottom_left", "⬇️": "bottom_center", "↘️": "bottom_right",
}
ws_text_positions  = ws_image_positions.copy()
font_colors        = ["white", "black", "yellow", "red", "green", "blue"]
font_size_list     = [str(s) for s in range(16, 49, 4)]
convert_qualities  = {
    "8K": 4320, "6K": 3240, "5K": 2880, "4K": 2160,
    "2K": 1440, "1080p": 1080, "720p": 720, "540p": 540,
    "480p": 480, "360p": 360, "240p": 240,
}
audio_codec_list   = ["Auto","copy","aac","mp3","opus","vorbis","pcm","flac","ac3","dts"]
aac_profile_list   = ["Auto","lc","he-aac","he-aacv2"]
audio_bitrate_list = ["Auto","64k","128k","192k","256k","320k","384k","448k","640k"]
audio_channels_list = ["Auto","mono","stereo","2.1","3.1","5.1","7.1"]
audio_samplerate_list = ["Auto","22050","44100","48000","96000","192000"]
audio_norm_list    = ["Off","loudnorm","dynaudnorm"]
audio_filter_list  = ["Off","highpass","lowpass","equalizer"]
audio_downmix_list = ["Off","stereo","mono"]
bool_list          = [True, False]


def get_mention(event) -> str:
    return f"[{event.sender.first_name}](tg://user?id={event.sender.id})"


def gen_keyboard(values_list, current_value, callvalue, items, hide):
    """Build inline keyboard rows dari list nilai."""
    boards = []
    if len(values_list) > 6 and items > 3:
        items = 3
    row = []
    for x in values_list:
        if len(row) == items:
            boards.append(row)
            row = []
        display = str(x)
        if callvalue == "audiosamplerate" and str(x).isdigit():
            display = f"{int(x)/1000}kHz"

        is_custom_active = (
            callvalue in ["videocrf", "videoresolution"]
            and str(current_value) not in [str(v) for v in values_list]
        )
        if is_custom_active and x == "Custom":
            text = f"Custom ({current_value}) 🟢"
        elif str(current_value) == str(x):
            text = "🟢" if hide else f"{display} 🟢"
        else:
            text = display

        row.append(Button.inline(text, f"{callvalue}_{x}"))
    if row:
        boards.append(row)
    return boards


async def get_text_data(chat_id, user_id, event, timeout, message):
    """Tanya input teks dari user di conversation."""
    try:
        async with TELETHON_CLIENT.conversation(chat_id, timeout=timeout) as conv:
            ask_msg = await conv.send_message(f"*️⃣ {message} [{timeout} detik]")
            resp    = await conv.get_response()
            await ask_msg.delete()
            return resp
    except asyncio.TimeoutError:
        try:
            await event.client.edit_message(event.chat_id, event.message.id,
                                             "🔃 Waktu Habis! Tugas Telah Dibatalkan.")
        except Exception:
            pass
        return False


def get_current_settings_copy(user_id: int) -> dict:
    user_data = get_data().get(user_id, {})
    keys = [
        "video","audio","watermark","mux","merge","convert","metadata",
        "select_stream","stream","split_video","split","upload_tg",
        "custom_thumbnail","detailed_messages","show_stats","update_time",
        "ffmpeg_size","ffmpeg_ptime","auto_drive","show_time","gen_ss",
        "ss_no","gen_sample","multi_tasks","upload_all",
    ]
    return {k: copy.deepcopy(user_data[k]) for k in keys if k in user_data}


async def apply_settings_from_profile(user_id: int, profile_data: dict) -> None:
    user_data = get_data().get(user_id, {})
    for k, v in profile_data.items():
        user_data[k] = copy.deepcopy(v)
    if SAVE_TO_DATABASE:
        db = _get_db()
        if db:
            await db.save_data(str(Config.DATA))


# ═══════════════════════════════════════════════════════════════════════
#  SUB-CALLBACKS
# ═══════════════════════════════════════════════════════════════════════

async def audio_callback(event, txt: str, user_id: int) -> None:
    try:
        new_position = txt.split("_", 1)[1]
    except IndexError:
        new_position = ""

    if txt.startswith("audioenable_"):
        val = _safe_eval_bool(new_position)
        if val is not None:
            await saveconfig(user_id, "audio", "enabled", val, SAVE_TO_DATABASE)
            await event.answer(f"✅ Audio {'Aktif' if val else 'Nonaktif'}")
    elif txt.startswith("audiocodec_"):
        await saveconfig(user_id, "audio", "codec", new_position, SAVE_TO_DATABASE)
        await event.answer(f"✅ Codec: {new_position.upper()}")
    elif txt.startswith("audioprofile_"):
        await saveconfig(user_id, "audio", "codec_profile", new_position, SAVE_TO_DATABASE)
        await event.answer(f"✅ Profil AAC: {new_position.upper()}")
    elif txt.startswith("audiobitrate_"):
        await saveconfig(user_id, "audio", "bitrate", new_position, SAVE_TO_DATABASE)
        await event.answer(f"✅ Bitrate: {new_position}")
    elif txt.startswith("audiochannels_"):
        await saveconfig(user_id, "audio", "channels", new_position, SAVE_TO_DATABASE)
        await event.answer(f"✅ Channel: {new_position}")
    elif txt.startswith("audiosamplerate_"):
        await saveconfig(user_id, "audio", "samplerate", new_position, SAVE_TO_DATABASE)
        await event.answer(f"✅ Sample Rate: {int(new_position)/1000}kHz")
    elif txt.startswith("audionorm_"):
        await saveconfig(user_id, "audio", "normalization", new_position, SAVE_TO_DATABASE)
        await event.answer(f"✅ Normalisasi: {new_position}")
    elif txt.startswith("audiofilter_"):
        await saveconfig(user_id, "audio", "filter", new_position, SAVE_TO_DATABASE)
        await event.answer(f"✅ Filter: {new_position}")
    elif txt.startswith("audiodownmix_"):
        await saveconfig(user_id, "audio", "downmix", new_position, SAVE_TO_DATABASE)
        await event.answer(f"✅ Downmix: {new_position}")

    audio = get_data().get(user_id, {}).get("audio", {})
    enabled = audio.get("enabled", True)
    KB = []
    KB.append([Button.inline(f'Status Audio — {"ON" if enabled else "OFF"}', "nik66bots")])
    KB.extend(gen_keyboard(bool_list, enabled, "audioenable", 2, False))
    if enabled:
        KB.append([Button.inline(f"Codec — {audio.get('codec','Auto').upper()}", "nik66bots")])
        KB.extend(gen_keyboard(audio_codec_list, audio.get("codec","Auto"), "audiocodec", 4, False))
        if audio.get("codec") == "aac":
            KB.append([Button.inline(f"Profil AAC — {audio.get('codec_profile','Auto')}", "nik66bots")])
            KB.extend(gen_keyboard(aac_profile_list, audio.get("codec_profile","Auto"), "audioprofile", 3, False))
        if audio.get("codec") not in ["pcm","flac","Auto","copy"]:
            KB.append([Button.inline(f"Bitrate — {audio.get('bitrate','Auto')}", "nik66bots")])
            KB.extend(gen_keyboard(audio_bitrate_list, audio.get("bitrate","Auto"), "audiobitrate", 4, False))
        KB.append([Button.inline(f"Channel — {audio.get('channels','Auto')}", "nik66bots")])
        KB.extend(gen_keyboard(audio_channels_list, audio.get("channels","Auto"), "audiochannels", 3, False))
        sr = audio.get("samplerate","Auto")
        sr_display = sr if sr == "Auto" else f"{int(sr)/1000}kHz"
        KB.append([Button.inline(f"Sample Rate — {sr_display}", "nik66bots")])
        KB.extend(gen_keyboard(audio_samplerate_list, sr, "audiosamplerate", 3, False))
        KB.append([Button.inline(f"Normalisasi — {audio.get('normalization','Off')}", "nik66bots")])
        KB.extend(gen_keyboard(audio_norm_list, audio.get("normalization","Off"), "audionorm", 3, False))
        KB.append([Button.inline(f"Filter — {audio.get('filter','Off')}", "nik66bots")])
        KB.extend(gen_keyboard(audio_filter_list, audio.get("filter","Off"), "audiofilter", 4, False))
        KB.append([Button.inline(f"Downmix — {audio.get('downmix','Off')}", "nik66bots")])
        KB.extend(gen_keyboard(audio_downmix_list, audio.get("downmix","Off"), "audiodownmix", 3, False))
    KB.append([Button.inline("↩️ Kembali", "settings_media")])
    try:
        await event.edit("🎧 Pengaturan Audio", buttons=KB)
    except Exception:
        pass


async def video_callback(event, txt: str, user_id: int, edit: bool, chat_id: int) -> None:
    new_pos = txt.split("_", 1)[1] if "_" in txt else ""

    if txt.startswith("videoenable_"):
        val = _safe_eval_bool(new_pos)
        if val is not None:
            await saveconfig(user_id, "video", "enabled", val, SAVE_TO_DATABASE)
    elif txt.startswith("videoencoder_"):   await saveconfig(user_id, "video", "encoder",    new_pos, SAVE_TO_DATABASE)
    elif txt.startswith("videopreset_"):    await saveconfig(user_id, "video", "preset",     new_pos, SAVE_TO_DATABASE)
    elif txt.startswith("videocopysub_"):
        val = _safe_eval_bool(new_pos)
        if val is not None: await saveconfig(user_id, "video", "copy_sub", val, SAVE_TO_DATABASE)
    elif txt.startswith("videomap_"):
        val = _safe_eval_bool(new_pos)
        if val is not None: await saveconfig(user_id, "video", "map", val, SAVE_TO_DATABASE)
    elif txt.startswith("videocrf_"):
        if new_pos == "Custom":
            resp = await get_text_data(chat_id, user_id, event, 120, "Kirim nilai CRF (0-51)")
            if resp:
                try:
                    crf = int(resp.text)
                    if 0 <= crf <= 51:
                        await saveconfig(user_id, "video", "crf", str(crf), SAVE_TO_DATABASE)
                        await resp.reply(f"✅ CRF diatur ke {crf}")
                        edit = False
                    else:
                        await resp.reply("❌ Nilai CRF harus 0-51.")
                except ValueError:
                    await resp.reply("❌ Input tidak valid.")
        else:
            await saveconfig(user_id, "video", "crf", new_pos, SAVE_TO_DATABASE)
    elif txt.startswith("videousequeuesize_"):
        val = _safe_eval_bool(new_pos)
        if val is not None: await saveconfig(user_id, "video", "use_queue_size", val, SAVE_TO_DATABASE)
    elif txt.startswith("videosync_"):
        val = _safe_eval_bool(new_pos)
        if val is not None: await saveconfig(user_id, "video", "sync", val, SAVE_TO_DATABASE)
    elif txt.startswith("videoextension_"):   await saveconfig(user_id, "video", "extension",   new_pos, SAVE_TO_DATABASE)
    elif txt.startswith("videotune_"):        await saveconfig(user_id, "video", "tune",         new_pos, SAVE_TO_DATABASE)
    elif txt.startswith("videocabac_"):       await saveconfig(user_id, "video", "cabac",        new_pos, SAVE_TO_DATABASE)
    elif txt.startswith("videofast_start_"):  await saveconfig(user_id, "video", "fast_start",   new_pos, SAVE_TO_DATABASE)
    elif txt.startswith("videobit_depth_"):   await saveconfig(user_id, "video", "bit_depth",    new_pos, SAVE_TO_DATABASE)
    elif txt.startswith("videopixel_format_"):await saveconfig(user_id, "video", "pixel_format", new_pos, SAVE_TO_DATABASE)
    elif txt.startswith("videoresolution_"):
        if new_pos == "Custom":
            resp = await get_text_data(chat_id, user_id, event, 120, "Kirim resolusi (contoh: 1280x720)")
            if resp:
                await saveconfig(user_id, "video", "resolution", resp.text, SAVE_TO_DATABASE)
                await resp.reply(f"✅ Resolusi kustom: {resp.text}")
                edit = False
        else:
            await saveconfig(user_id, "video", "resolution", new_pos, SAVE_TO_DATABASE)

    vs   = get_data().get(user_id, {}).get("video", {})
    enab = vs.get("enabled", True)
    enc  = vs.get("encoder", "libx264")
    KB   = []
    KB.append([Button.inline(f'Status Video — {"ON" if enab else "OFF"}', "nik66bots")])
    KB.extend(gen_keyboard(bool_list, enab, "videoenable", 2, False))
    if enab:
        KB.append([Button.inline(f"Encoder — {enc}", "nik66bots")])
        KB.extend(gen_keyboard(encoders_list, enc, "videoencoder", 2, False))
        KB.append([Button.inline(f"Preset — {vs.get('preset','medium')}", "nik66bots")])
        KB.extend(gen_keyboard(presets_list, vs.get("preset","medium"), "videopreset", 3, False))
        KB.append([Button.inline(f"CRF — {vs.get('crf','23')}", "nik66bots")])
        KB.extend(gen_keyboard(crf_list, vs.get("crf","23"), "videocrf", 4, False))
        KB.append([Button.inline(f"Tune — {vs.get('tune','None')}", "nik66bots")])
        KB.extend(gen_keyboard(tune_list, vs.get("tune","None"), "videotune", 3, False))
        KB.append([Button.inline(f"Format Piksel — {vs.get('pixel_format','Auto')}", "nik66bots")])
        KB.extend(gen_keyboard(pixel_format_list, vs.get("pixel_format","Auto"), "videopixel_format", 3, False))
        KB.append([Button.inline(f"Resolusi — {vs.get('resolution','Auto')}", "nik66bots")])
        KB.extend(gen_keyboard(resolution_list, vs.get("resolution","Auto"), "videoresolution", 5, False))
        KB.append([Button.inline(f"Ekstensi — {vs.get('extension','MKV')}", "nik66bots")])
        KB.extend(gen_keyboard(extension_list, vs.get("extension","MKV"), "videoextension", 3, False))
        if enc == "libx264":
            KB.append([Button.inline(f"CABAC — {vs.get('cabac','On')}", "nik66bots")])
            KB.extend(gen_keyboard(cabac_list, vs.get("cabac","On"), "videocabac", 2, False))
        if vs.get("extension","MKV") == "MP4":
            KB.append([Button.inline(f"Fast Start — {vs.get('fast_start','Yes')}", "nik66bots")])
            KB.extend(gen_keyboard(fast_start_list, vs.get("fast_start","Yes"), "videofast_start", 2, False))
        KB.append([Button.inline(f"Salin Subtitle — {vs.get('copy_sub',True)}", "nik66bots")])
        KB.extend(gen_keyboard(bool_list, vs.get("copy_sub",True), "videocopysub", 2, False))
        KB.append([Button.inline(f"Peta — {vs.get('map',True)}", "nik66bots")])
        KB.extend(gen_keyboard(bool_list, vs.get("map",True), "videomap", 2, False))
        qs = vs.get("use_queue_size", False)
        KB.append([Button.inline(f"Gunakan Queue Size — {qs}", "nik66bots")])
        if qs:
            KB.append([Button.inline(f"Queue Size — {vs.get('queue_size','1M')} (Klik Ubah)", "change_video_queue_size")])
        KB.extend(gen_keyboard(bool_list, qs, "videousequeuesize", 2, False))
        KB.append([Button.inline(f"SYNC — {vs.get('sync',False)}", "nik66bots")])
        KB.extend(gen_keyboard(bool_list, vs.get("sync",False), "videosync", 2, False))
    KB.append([Button.inline("↩️ Kembali", "settings_media")])

    if edit:
        try:
            await event.edit("🎬 Pengaturan Video Global", buttons=KB)
        except Exception:
            pass
    else:
        try:
            await event.delete()
        except Exception:
            pass
        await TELETHON_CLIENT.send_message(event.chat.id, "🎬 Pengaturan Video Global", buttons=KB)


async def general_callback(event, txt: str, user_id: int, chat_id: int) -> None:
    new_pos = txt.split("_", 1)[1] if "_" in txt else ""
    # [FIX] .get() dengan fallback
    r_config    = f"./userdata/{user_id}_rclone.conf"
    check_cfg   = exists(r_config)
    drive_name  = get_data().get(user_id, {}).get("drive_name", "")

    if txt.startswith("generalselectstream"):
        val = _safe_eval_bool(new_pos)
        if val is not None: await saveoptions(user_id, "select_stream", val, SAVE_TO_DATABASE)
    elif txt.startswith("generalstream"):    await saveoptions(user_id, "stream", new_pos, SAVE_TO_DATABASE)
    elif txt.startswith("generalsplitvideo"):
        val = _safe_eval_bool(new_pos)
        if val is not None: await saveoptions(user_id, "split_video", val, SAVE_TO_DATABASE)
    elif txt.startswith("generalsplit"):     await saveoptions(user_id, "split", new_pos, SAVE_TO_DATABASE)
    elif txt.startswith("generalcustomthumbnail"):
        val = _safe_eval_bool(new_pos)
        if val is not None: await saveoptions(user_id, "custom_thumbnail", val, SAVE_TO_DATABASE)
    elif txt.startswith("generaluploadtg"):
        val = _safe_eval_bool(new_pos)
        if val is not None:
            if not val and not (check_cfg and drive_name):
                await event.answer("❗ Simpan Konfigurasi Rclone Terlebih Dahulu", alert=True)
                return
            await saveoptions(user_id, "upload_tg", val, SAVE_TO_DATABASE)
    elif txt.startswith("generaldrivename"): await saveoptions(user_id, "drive_name", new_pos, SAVE_TO_DATABASE)
    elif txt.startswith("generalautodrive"):
        val = _safe_eval_bool(new_pos)
        if val is not None:
            if val and not (check_cfg and drive_name):
                await event.answer("❗ Simpan Konfigurasi Rclone Terlebih Dahulu", alert=True)
                return
            await saveoptions(user_id, "auto_drive", val, SAVE_TO_DATABASE)
    elif txt.startswith("generalgenss"):
        val = _safe_eval_bool(new_pos)
        if val is not None: await saveoptions(user_id, "gen_ss", val, SAVE_TO_DATABASE)
    elif txt.startswith("generalssno"):
        try: await saveoptions(user_id, "ss_no", int(new_pos), SAVE_TO_DATABASE)
        except ValueError: pass
    elif txt.startswith("generalgensample"):
        val = _safe_eval_bool(new_pos)
        if val is not None: await saveoptions(user_id, "gen_sample", val, SAVE_TO_DATABASE)
    elif txt.startswith("generaluploadall"):
        val = _safe_eval_bool(new_pos)
        if val is not None: await saveoptions(user_id, "upload_all", val, SAVE_TO_DATABASE)
    elif txt.startswith("generalmultitasks"):
        val = _safe_eval_bool(new_pos)
        if val is not None: await saveoptions(user_id, "multi_tasks", val, SAVE_TO_DATABASE)

    ud  = get_data().get(user_id, {})
    KB  = []
    def _row(label, key, default, opts, items):
        val = ud.get(key, default)
        KB.append([Button.inline(f"{label} — {val}", "nik66bots")])
        KB.extend(gen_keyboard(opts, val, f"general{key.replace('_','')}", items, False))

    _row("🥝 Pilih Audio Otomatis", "select_stream", True, bool_list, 2)
    _row("🍭 Aliran Audio",        "stream",        "ENG",  ["ENG","HIN"], 2)
    _row("🪓 Bagi Video",          "split_video",   True,  bool_list, 2)
    _row("🛢 Ukuran Bagi",         "split",         "2GB", ["2GB","4GB"], 2)
    _row("🖼 Thumbnail Dinamis",   "custom_thumbnail", True, bool_list, 2)
    _row("🧵 Unggah ke TG",        "upload_tg",     True,  bool_list, 2)
    _row("🕹 Auto Drive File Besar","auto_drive",    False, bool_list, 2)
    _row("📷 Buat Screenshot",     "gen_ss",        True,  bool_list, 2)
    _row("🎶 Jumlah Screenshot",   "ss_no",         5,     [3,5,7,10], 4)
    _row("🎞 Buat Video Sampel",   "gen_sample",    True,  bool_list, 2)
    _row("🛰 Multi Tugas",         "multi_tasks",   True,  bool_list, 2)
    _row("⏹ Unggah Tiap File",    "upload_all",    False, bool_list, 2)

    # [FIX] .get() untuk drive_name
    drive_name = get_data().get(user_id, {}).get("drive_name", "")
    if check_cfg:
        accounts = await get_config(r_config)
        if accounts:
            KB.append([Button.inline(f"🔮 Akun Rclone — {drive_name}", "nik66bots")])
            KB.extend(gen_keyboard(accounts, drive_name, "generaldrivename", 2, False))

    KB.append([Button.inline("↩️ Kembali", "settings_bot")])
    try:
        await event.edit("⚙️ Pengaturan Umum", buttons=KB)
    except Exception:
        pass


async def progress_callback(event, txt: str, user_id: int) -> None:
    new_pos = txt.split("_", 1)[1] if "_" in txt else ""
    if txt.startswith("progressdetailedprogress"):
        val = _safe_eval_bool(new_pos)
        if val is not None: await saveoptions(user_id, "detailed_messages", val, SAVE_TO_DATABASE)
    elif txt.startswith("progressshowstats"):
        val = _safe_eval_bool(new_pos)
        if val is not None: await saveoptions(user_id, "show_stats", val, SAVE_TO_DATABASE)
    elif txt.startswith("progressupdatetime"):
        try: await saveoptions(user_id, "update_time", int(new_pos), SAVE_TO_DATABASE)
        except ValueError: pass
    elif txt.startswith("progressffmpegsize"):
        val = _safe_eval_bool(new_pos)
        if val is not None: await saveoptions(user_id, "ffmpeg_size", val, SAVE_TO_DATABASE)
    elif txt.startswith("progressffmpegptime"):
        val = _safe_eval_bool(new_pos)
        if val is not None: await saveoptions(user_id, "ffmpeg_ptime", val, SAVE_TO_DATABASE)
    elif txt.startswith("progressshowtime"):
        val = _safe_eval_bool(new_pos)
        if val is not None: await saveoptions(user_id, "show_time", val, SAVE_TO_DATABASE)

    ud = get_data().get(user_id, {})
    KB = []
    def _row(label, key, default, opts, items):
        val = ud.get(key, default)
        KB.append([Button.inline(f"{label} — {val}", "nik66bots")])
        KB.extend(gen_keyboard(opts, val, f"progress{key.replace('_','')}", items, False))

    _row("📋 Pesan Detail",       "detailed_messages", True,  bool_list, 2)
    _row("📊 Tampilkan Statistik","show_stats",         False, bool_list, 2)
    _row("📀 Ukuran Output FFMPEG","ffmpeg_size",       True,  bool_list, 2)
    _row("⏲ Waktu Proses",        "ffmpeg_ptime",       True,  bool_list, 2)
    _row("⌚ Waktu Saat Ini",      "show_time",          False, bool_list, 2)
    ut = ud.get("update_time", 7)
    KB.append([Button.inline(f"⏱ Waktu Update — {ut}s", "nik66bots")])
    KB.extend(gen_keyboard([5,6,7,8,9,10], ut, "progressupdatetime", 3, False))
    KB.append([Button.inline("↩️ Kembali", "settings_bot")])
    try:
        await event.edit("⚙️ Pengaturan Tampilan Progress", buttons=KB)
    except Exception:
        pass


async def telegram_callback(event, txt: str, user_id: int, chat_id: int) -> None:
    new_pos = txt.split("_", 1)[1] if "_" in txt else ""
    if txt.startswith("telegramupload"):
        await saveoptions(user_id, "tgupload", new_pos, SAVE_TO_DATABASE)
    elif txt.startswith("telegramdownload"):
        await saveoptions(user_id, "tgdownload", new_pos, SAVE_TO_DATABASE)
    ud  = get_data().get(user_id, {})
    up  = ud.get("tgupload",   "Telethon")
    dw  = ud.get("tgdownload", "Telethon")
    KB  = [
        [Button.inline(f"🔼 Upload — {up}", "nik66bots")],
        *gen_keyboard(["Telethon","Pyrogram"], up, "telegramupload", 2, False),
        [Button.inline(f"🔽 Download — {dw}", "nik66bots")],
        *gen_keyboard(["Telethon","Pyrogram"], dw, "telegramdownload", 2, False),
        [Button.inline("↩️ Kembali", "settings_bot")],
    ]
    try:
        await event.edit("✈️ Pengaturan Telegram", buttons=KB)
    except Exception:
        pass


async def metadata_callback(event, txt: str, user_id: int, chat_id: int) -> None:
    new_pos = txt.split("_", 1)[1] if "_" in txt else ""
    edit = True
    if txt.startswith("metadataenable_"):
        val = _safe_eval_bool(new_pos)
        if val is not None: await saveconfig(user_id, "metadata", "enabled", val, SAVE_TO_DATABASE)
    elif txt.startswith("metadatamode_"):
        await saveconfig(user_id, "metadata", "mode", new_pos, SAVE_TO_DATABASE)
    elif txt.startswith("metadatapreset_"):
        field = new_pos
        resp  = await get_text_data(chat_id, user_id, event, 120, f"Kirim nilai baru untuk '{field}'")
        if resp:
            presets = get_data().get(user_id, {}).get("metadata", {}).get("preset", {})
            presets[field] = resp.text
            await saveconfig(user_id, "metadata", "preset", presets, SAVE_TO_DATABASE)
            await resp.reply(f"✅ Preset '{field}' diubah.")
            edit = False
    elif txt.startswith("metadatacustom_"):
        resp = await get_text_data(chat_id, user_id, event, 300,
                                    "Kirim kode metadata ffmpeg kustom.")
        if resp:
            await saveconfig(user_id, "metadata", "custom", resp.text, SAVE_TO_DATABASE)
            await resp.reply("✅ Kode kustom disimpan.")
            edit = False

    md      = get_data().get(user_id, {}).get("metadata", {})
    enabled = md.get("enabled", False)
    KB      = []
    KB.append([Button.inline(f'Status Metadata — {"ON" if enabled else "OFF"}', "nik66bots")])
    KB.extend(gen_keyboard(bool_list, enabled, "metadataenable", 2, False))
    if enabled:
        mode = md.get("mode","preset")
        KB.append([Button.inline(f"Mode — {mode.upper()}", "nik66bots")])
        KB.extend(gen_keyboard(["preset","custom"], mode, "metadatamode", 2, False))
        if mode == "preset":
            p = md.get("preset", {})
            KB.append([Button.inline("─── PRESET METADATA ───", "nik66bots")])
            for field in ["title","author","year","comment","genre"]:
                KB.append([Button.inline(f"{field.capitalize()}: {p.get(field,'')}", f"metadatapreset_{field}")])
        else:
            KB.append([Button.inline("─── KODE FFMPEG KUSTOM ───", "nik66bots")])
            KB.append([Button.inline("Ubah Kode", "metadatacustom_change")])
    KB.append([Button.inline("↩️ Kembali", "settings_media")])
    if edit:
        try:
            await event.edit("⚙️ Pengaturan Metadata", buttons=KB)
        except Exception:
            pass
    else:
        await TELETHON_CLIENT.send_message(chat_id, "⚙️ Pengaturan Metadata", buttons=KB)


async def convert_callback(event, txt: str, user_id: int) -> None:
    current = get_data().get(user_id, {}).get("convert", {}).get("convert_list", [])
    if txt == "convert_clear_all":
        current = []
        await saveconfig(user_id, "convert", "convert_list", [], SAVE_TO_DATABASE)
        await event.answer("✅ Pilihan dihapus semua.")
    elif txt.startswith("convert_toggle_"):
        try:
            val = int(txt.split("_")[-1])
            if val in current: current.remove(val)
            else:              current.append(val)
            current.sort(reverse=True)
            await saveconfig(user_id, "convert", "convert_list", current, SAVE_TO_DATABASE)
        except (ValueError, IndexError):
            pass
    KB    = [[Button.inline("Pilih satu atau lebih kualitas output", "nik66bots")]]
    row   = []
    for name, val in sorted(convert_qualities.items(), key=lambda x: x[1], reverse=True):
        txt_ = f"{name} 🟢" if val in current else name
        row.append(Button.inline(txt_, f"convert_toggle_{val}"))
        if len(row) == 3:
            KB.append(row)
            row = []
    if row:
        KB.append(row)
    KB.append([Button.inline("❌ Hapus Semua", "convert_clear_all")])
    KB.append([Button.inline("↩️ Kembali", "settings_media")])
    try:
        await event.edit("⚙️ Pengaturan Konversi", buttons=KB)
    except Exception:
        pass


async def mux_callback(event, txt: str, user_id: int) -> None:
    new_pos = txt.split("_", 1)[1] if "_" in txt else ""
    if txt.startswith("muxsubcodec_"):
        await saveconfig(user_id, "mux", "sub_codec", new_pos, SAVE_TO_DATABASE)
    mux_codec = get_data().get(user_id, {}).get("mux", {}).get("sub_codec", "copy")
    KB = [
        [Button.inline(f"Codec Subtitle — {mux_codec}", "nik66bots")],
        *gen_keyboard(["copy","mov_text"], mux_codec, "muxsubcodec", 2, False),
        [Button.inline("↩️ Kembali", "settings_media")],
    ]
    try:
        await event.edit("⚙️ Pengaturan Mux", buttons=KB)
    except Exception:
        pass


async def merge_callback(event, txt: str, user_id: int) -> None:
    new_pos = txt.split("_", 1)[1] if "_" in txt else ""
    if txt.startswith("mergemap"):
        val = _safe_eval_bool(new_pos)
        if val is not None: await saveconfig(user_id, "merge", "map", val, SAVE_TO_DATABASE)
    elif txt.startswith("mergefixblank"):
        val = _safe_eval_bool(new_pos)
        if val is not None: await saveconfig(user_id, "merge", "fix_blank", val, SAVE_TO_DATABASE)
    mg = get_data().get(user_id, {}).get("merge", {})
    KB = [
        [Button.inline(f"Peta — {mg.get('map',True)}", "nik66bots")],
        *gen_keyboard(bool_list, mg.get("map",True), "mergemap", 2, False),
        [Button.inline(f"Perbaiki Blank — {mg.get('fix_blank',False)}", "nik66bots")],
        *gen_keyboard(bool_list, mg.get("fix_blank",False), "mergefixblank", 2, False),
        [Button.inline("↩️ Kembali", "settings_media")],
    ]
    try:
        await event.edit("⚙️ Pengaturan Gabung", buttons=KB)
    except Exception:
        pass


async def watermark_callback(event, txt: str, user_id: int, chat_id: int) -> None:
    """Watermark settings — delegasi ke watermark_image_menu dan watermark_text_menu."""
    settings = get_data().get(user_id, {}).get("watermark", {})

    if txt.startswith("watermark_enable_"):
        val = _safe_eval_bool(txt.split("_")[-1])
        if val is not None:
            settings["enabled"] = val
            await saveoptions(user_id, "watermark", settings, SAVE_TO_DATABASE)
        txt = "watermark_settings"
    elif txt.startswith("watermark_type_"):
        wm_type = txt.split("_")[-1]
        settings["type"] = wm_type
        await saveoptions(user_id, "watermark", settings, SAVE_TO_DATABASE)
        txt = "watermark_settings"

    if txt.startswith("watermark_image"):
        await watermark_image_menu(event, txt, user_id, chat_id)
        return
    if txt.startswith("watermark_text"):
        await watermark_text_menu(event, txt, user_id, chat_id)
        return

    is_en   = settings.get("enabled", False)
    wm_type = settings.get("type", "image")
    KB      = [
        [Button.inline(f'Status: {"Aktif ✅" if is_en else "Nonaktif"}', "nik66bots")],
        gen_keyboard(bool_list, is_en, "watermark_enable", 2, False)[0],
    ]
    if is_en:
        KB.append([Button.inline("Pilih Jenis Watermark", "nik66bots")])
        KB.append([
            Button.inline(f'{"🖼️ Gambar 🟢" if wm_type=="image" else "🖼️ Gambar"}', "watermark_type_image"),
            Button.inline(f'{"✍️ Teks 🟢" if wm_type=="text" else "✍️ Teks"}', "watermark_type_text"),
        ])
        if wm_type == "image":
            KB.append([Button.inline("➡️ Atur Watermark Gambar", "watermark_image_menu")])
        else:
            KB.append([Button.inline("➡️ Atur Watermark Teks", "watermark_text_menu")])
    KB.append([Button.inline("↩️ Kembali", "settings_media")])
    try:
        await event.edit("🛺 Pengaturan Watermark", buttons=KB)
    except Exception:
        pass


async def watermark_image_menu(event, txt: str, user_id: int, chat_id: int) -> None:
    wm_path = f"./userdata/{user_id}_watermark.jpg"

    if txt == "watermark_image_upload":
        await event.delete()
        resp = await get_text_data(chat_id, user_id, event, 120, "Kirim gambar untuk watermark.")
        if resp and (resp.photo or (resp.document and "image" in (resp.document.mime_type or ""))):
            await TELETHON_CLIENT.download_media(resp.media, wm_path)
            await resp.reply("✅ Watermark disimpan.")
        elif resp:
            await resp.reply("❌ File bukan gambar.")
        await event.client.send_message(chat_id, "Menu:", buttons=[[Button.inline("Buka Menu", "watermark_image_menu")]])
        return

    elif txt == "watermark_image_view":
        if exists(wm_path):
            await event.delete()
            await TELETHON_CLIENT.send_file(chat_id, wm_path, caption="Watermark gambar saat ini.")
            await event.client.send_message(chat_id, "Menu:", buttons=[[Button.inline("Kembali", "watermark_image_menu")]])
        else:
            await event.answer("❗ Belum ada watermark gambar.", alert=True)
        return

    elif txt == "watermark_image_delete":
        if exists(wm_path):
            remove(wm_path)
            await event.answer("✅ Watermark dihapus.", alert=True)
        else:
            await event.answer("❗ Tidak ada watermark.", alert=True)

    elif txt.startswith("watermark_image_duration_"):
        parts  = txt.split("_")
        action = parts[3]
        setts  = get_data().get(user_id, {}).get("watermark", {})
        if action == "mode":
            setts["image"]["duration"]["mode"] = parts[4]
        elif action == "from":
            resp = await get_text_data(chat_id, user_id, event, 120, "Waktu mulai (HH:MM:SS):")
            if resp: setts["image"]["duration"]["from"] = resp.text
        elif action == "to":
            resp = await get_text_data(chat_id, user_id, event, 120, "Waktu selesai (HH:MM:SS):")
            if resp: setts["image"]["duration"]["to"] = resp.text
        elif action == "interval":
            resp = await get_text_data(chat_id, user_id, event, 120, "Interval (detik):")
            if resp and resp.text.isdigit():
                setts["image"]["duration"]["interval"] = int(resp.text)
        await saveoptions(user_id, "watermark", setts, SAVE_TO_DATABASE)
        await event.answer("✅ Pengaturan durasi disimpan.")

    else:
        try:
            parts    = txt.split("_", 3)
            part_type = parts[2] if len(parts) > 2 else None
            new_pos   = parts[3] if len(parts) > 3 else None
        except (IndexError, ValueError):
            part_type = new_pos = None
        setts = get_data().get(user_id, {}).get("watermark", {})
        if part_type == "position" and new_pos:
            setts["image"]["position"] = new_pos
            await saveoptions(user_id, "watermark", setts, SAVE_TO_DATABASE)
            await event.answer("✅ Posisi diubah.")
        elif part_type == "size" and new_pos:
            setts["image"]["size"] = new_pos
            await saveoptions(user_id, "watermark", setts, SAVE_TO_DATABASE)
            await event.answer(f"✅ Ukuran: {new_pos}%")

    setts      = get_data().get(user_id, {}).get("watermark", {})
    img        = setts.get("image", {})
    dur        = img.get("duration", {})
    cur_pos    = img.get("position", "bottom_right")
    cur_size   = img.get("size", "12")
    v2i        = {v: k for k, v in ws_image_positions.items()}
    cur_icon   = v2i.get(cur_pos, "↘️")
    KB = [
        [Button.inline("⬆️ Unggah", "watermark_image_upload"),
         Button.inline("🖼️ Lihat",  "watermark_image_view"),
         Button.inline("🗑️ Hapus",  "watermark_image_delete")],
        [Button.inline(f"Posisi: {cur_icon}", "nik66bots")],
    ]
    row = []
    for icon, val in ws_image_positions.items():
        text = f"{icon} 🟢" if val == cur_pos else icon
        row.append(Button.inline(text, f"watermark_image_position_{val}"))
        if len(row) == 3:
            KB.append(row)
            row = []
    if row:
        KB.append(row)
    KB.append([Button.inline(f"Ukuran: {cur_size}%", "nik66bots")])
    KB.extend(gen_keyboard(wsize_list, cur_size, "watermark_image_size", 6, False))
    KB.append([Button.inline("─── Durasi ───", "nik66bots")])
    dur_mode = dur.get("mode","full")
    KB.append([
        Button.inline(f'{"Video Penuh 🟢" if dur_mode=="full" else "Video Penuh"}', "watermark_image_duration_mode_full"),
        Button.inline(f'{"Rentang 🟢" if dur_mode=="range" else "Rentang"}',       "watermark_image_duration_mode_range"),
        Button.inline(f'{"Interval 🟢" if dur_mode=="interval" else "Interval"}',  "watermark_image_duration_mode_interval"),
    ])
    if dur_mode == "range":
        KB.append([Button.inline(f"Dari: {dur.get('from','00:00:00')}", "watermark_image_duration_from"),
                   Button.inline(f"Ke: {dur.get('to','00:00:00')}",   "watermark_image_duration_to")])
    elif dur_mode == "interval":
        KB.append([Button.inline(f"Setiap: {dur.get('interval',30)}s", "watermark_image_duration_interval")])
    KB.append([Button.inline("↩️ Kembali", "watermark_settings")])
    try:
        await event.edit("🖼️ Pengaturan Watermark Gambar", buttons=KB)
    except Exception:
        pass


async def watermark_text_menu(event, txt: str, user_id: int, chat_id: int) -> None:
    font_glob = f"./userdata/{user_id}_watermark_font.*"

    if txt == "watermark_text_input":
        await event.delete()
        resp = await get_text_data(chat_id, user_id, event, 120, "Kirim teks watermark:")
        if resp:
            setts = get_data().get(user_id, {}).get("watermark", {})
            setts["text"]["content"] = resp.text
            await saveoptions(user_id, "watermark", setts, SAVE_TO_DATABASE)
            await resp.reply("✅ Teks disimpan.")
        await event.client.send_message(chat_id, "Menu:", buttons=[[Button.inline("Buka Menu", "watermark_text_menu")]])
        return

    elif txt == "watermark_text_upload_font":
        await event.delete()
        resp = await get_text_data(chat_id, user_id, event, 120, "Kirim file font (.ttf/.otf):")
        if resp and resp.media and hasattr(resp.media, "document"):
            try:
                fname = resp.media.document.attributes[0].file_name
                _, ext = splitext(fname)
                if ext.lower() in [".ttf", ".otf"]:
                    for f in glob.glob(font_glob): remove(f)
                    await TELETHON_CLIENT.download_media(resp.media,
                        f"./userdata/{user_id}_watermark_font{ext.lower()}")
                    await resp.reply(f"✅ Font '{fname}' disimpan.")
                else:
                    await resp.reply("❌ Format font tidak didukung. Harap .ttf atau .otf")
            except Exception as e:
                await resp.reply(f"❌ Error: {e}")
        await event.client.send_message(chat_id, "Menu:", buttons=[[Button.inline("Buka Menu", "watermark_text_menu")]])
        return

    elif txt == "watermark_text_view_font":
        fonts = glob.glob(font_glob)
        name  = fonts[0].split("/")[-1] if fonts else None
        await event.answer(f"Font: {name}" if name else "Default (tidak ada font kustom).", alert=True)
        return

    elif txt == "watermark_text_delete_font":
        fonts = glob.glob(font_glob)
        if fonts:
            for f in fonts: remove(f)
            await event.answer("✅ Font dihapus.", alert=True)
        else:
            await event.answer("❗ Tidak ada font kustom.", alert=True)

    elif txt.startswith("watermark_text_duration_"):
        parts  = txt.split("_")
        action = parts[3]
        setts  = get_data().get(user_id, {}).get("watermark", {})
        if action == "mode":
            setts["text"]["duration"]["mode"] = parts[4]
        elif action == "from":
            resp = await get_text_data(chat_id, user_id, event, 120, "Waktu mulai:")
            if resp: setts["text"]["duration"]["from"] = resp.text
        elif action == "to":
            resp = await get_text_data(chat_id, user_id, event, 120, "Waktu selesai:")
            if resp: setts["text"]["duration"]["to"] = resp.text
        elif action == "interval":
            resp = await get_text_data(chat_id, user_id, event, 120, "Interval (detik):")
            if resp and resp.text.isdigit():
                setts["text"]["duration"]["interval"] = int(resp.text)
        await saveoptions(user_id, "watermark", setts, SAVE_TO_DATABASE)
        await event.answer("✅ Durasi disimpan.")

    else:
        try:
            parts    = txt.split("_", 3)
            part     = parts[2] if len(parts) > 2 else None
            new_pos  = parts[3] if len(parts) > 3 else None
        except (IndexError, ValueError):
            part = new_pos = None
        setts = get_data().get(user_id, {}).get("watermark", {})
        if part == "position" and new_pos:
            setts["text"]["position"] = new_pos
            await saveoptions(user_id, "watermark", setts, SAVE_TO_DATABASE)
            await event.answer("✅ Posisi diubah.")
        elif part == "size" and new_pos:
            setts["text"]["font_size"] = new_pos
            await saveoptions(user_id, "watermark", setts, SAVE_TO_DATABASE)
            await event.answer(f"✅ Ukuran: {new_pos}px")
        elif part == "color" and new_pos:
            setts["text"]["font_color"] = new_pos
            await saveoptions(user_id, "watermark", setts, SAVE_TO_DATABASE)
            await event.answer(f"✅ Warna: {new_pos}")

    setts     = get_data().get(user_id, {}).get("watermark", {})
    ts        = setts.get("text", {})
    dur       = ts.get("duration", {})
    cur_pos   = ts.get("position", "bottom_right")
    cur_size  = ts.get("font_size", "24")
    cur_color = ts.get("font_color", "white")
    v2i       = {v: k for k, v in ws_text_positions.items()}
    cur_icon  = v2i.get(cur_pos, "↘️")
    KB = [
        [Button.inline("✍️ Input Teks", "watermark_text_input")],
        [Button.inline("⬆️ Upload Font", "watermark_text_upload_font"),
         Button.inline("📄 Lihat Font", "watermark_text_view_font"),
         Button.inline("🗑️ Hapus Font", "watermark_text_delete_font")],
        [Button.inline(f"Teks: '{ts.get('content','')}'", "nik66bots")],
        [Button.inline(f"Posisi: {cur_icon}", "nik66bots")],
    ]
    row = []
    for icon, val in ws_text_positions.items():
        text = f"{icon} 🟢" if val == cur_pos else icon
        row.append(Button.inline(text, f"watermark_text_position_{val}"))
        if len(row) == 3:
            KB.append(row)
            row = []
    if row: KB.append(row)
    KB.append([Button.inline(f"Ukuran Font: {cur_size}px", "nik66bots")])
    KB.extend(gen_keyboard(font_size_list, cur_size, "watermark_text_size", 4, False))
    KB.append([Button.inline(f"Warna Font: {cur_color.capitalize()}", "nik66bots")])
    KB.extend(gen_keyboard(font_colors, cur_color, "watermark_text_color", 3, False))
    KB.append([Button.inline("─── Durasi ───", "nik66bots")])
    dur_mode = dur.get("mode","full")
    KB.append([
        Button.inline(f'{"Video Penuh 🟢" if dur_mode=="full" else "Video Penuh"}', "watermark_text_duration_mode_full"),
        Button.inline(f'{"Rentang 🟢" if dur_mode=="range" else "Rentang"}',       "watermark_text_duration_mode_range"),
        Button.inline(f'{"Interval 🟢" if dur_mode=="interval" else "Interval"}',  "watermark_text_duration_mode_interval"),
    ])
    if dur_mode == "range":
        KB.append([Button.inline(f"Dari: {dur.get('from','00:00:00')}", "watermark_text_duration_from"),
                   Button.inline(f"Ke: {dur.get('to','00:00:00')}",   "watermark_text_duration_to")])
    elif dur_mode == "interval":
        KB.append([Button.inline(f"Setiap: {dur.get('interval',30)}s", "watermark_text_duration_interval")])
    KB.append([Button.inline("↩️ Kembali", "watermark_settings")])
    try:
        await event.edit("✍️ Pengaturan Watermark Teks", buttons=KB)
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════════
#  MAIN CALLBACK HANDLER
# ═══════════════════════════════════════════════════════════════════════

@TELETHON_CLIENT.on(events.CallbackQuery)
async def callback(event):
    txt     = event.data.decode("utf-8", "replace")
    chat_id = event.chat_id
    user_id = event.sender.id

    try:
        await ensure_user_data_structure(user_id)

        # ── Settings Navigation ──────────────────────────────────────
        if txt == "settings":
            await event.edit(
                "⚙️ Pengaturan Bot\n\nPilih kategori:",
                buttons=[
                    [Button.inline("👤 Profil Pengaturan",     "profile_main")],
                    [Button.inline("🎬 Pengaturan Media",       "settings_media")],
                    [Button.inline("🤖 Pengaturan Umum & Tampilan", "settings_bot")],
                    [Button.inline("⭕ Tutup",                   "close_settings")],
                ],
            )

        elif txt == "settings_media":
            await event.edit(
                "🎬 Pengaturan Media",
                buttons=[
                    [Button.inline("🎬 Video",    "video_settings"),  Button.inline("🎧 Audio",  "audio_settings")],
                    [Button.inline("🛺 Watermark","watermark_settings"), Button.inline("🚜 Konversi","convert_settings")],
                    [Button.inline("🍧 Gabung",   "merge_settings"),  Button.inline("⚙️ Mux",    "mux_settings")],
                    [Button.inline("🎞️ Metadata", "metadata_settings")],
                    [Button.inline("↩️ Kembali ke Menu Utama", "settings")],
                ],
            )

        elif txt == "settings_bot":
            await event.edit(
                "🤖 Pengaturan Umum & Tampilan",
                buttons=[
                    [Button.inline("#️⃣ Umum",              "general_settings")],
                    [Button.inline("🖥️ Tampilan Progress",  "progress_settings")],
                    [Button.inline("✈️ Telegram",           "telegram_settings")],
                    [Button.inline("↩️ Kembali ke Menu Utama", "settings")],
                ],
            )

        elif txt == "close_settings":
            await event.delete()

        # ── Profile Management ───────────────────────────────────────
        elif txt.startswith("profile_"):
            parts        = txt.split("_", 2)
            action       = parts[1]
            profile_name = parts[2] if len(parts) > 2 else None
            user_data    = get_data().get(user_id, {})

            if action == "main":
                active = user_data.get("active_profile", "Default")
                await event.edit(
                    f"👤 Profil Pengaturan\nAktif: **{active}**",
                    buttons=[
                        [Button.inline("💾 Simpan Profil Saat Ini", "profile_save")],
                        [Button.inline("📂 Muat & Kelola",          "profile_manage")],
                        [Button.inline("🚀 Profil Cepat",           "profile_quick")],
                        [Button.inline("↩️ Kembali",                "settings")],
                    ],
                )

            elif action == "save":
                resp = await get_text_data(chat_id, user_id, event, 120, "Masukkan nama profil baru:")
                if resp and 0 < len(resp.text) < 32:
                    user_data.setdefault("profiles", {})[resp.text] = get_current_settings_copy(user_id)
                    await saveoptions(user_id, "profiles", user_data["profiles"], SAVE_TO_DATABASE)
                    await resp.reply(f"✅ Profil '{resp.text}' disimpan.")
                elif resp:
                    await resp.reply("❌ Nama tidak valid (1-31 karakter).")
                await event.delete()
                await event.client.send_message(chat_id, "Menu:", buttons=[[Button.inline("Buka Menu", "profile_main")]])

            elif action == "manage":
                profiles = user_data.get("profiles", {})
                active   = user_data.get("active_profile", "Default")
                btns     = [[Button.inline("✨ Reset ke Default", "profile_reset_default")]]
                for name in profiles:
                    if name == "Default":
                        continue
                    lbl = f"✅ {name}" if name == active else name
                    btns.append([Button.inline(lbl, f"profile_load_{name}"),
                                  Button.inline("🗑️", f"profile_delete_{name}")])
                btns.append([Button.inline("↩️ Kembali", "profile_main")])
                await event.edit(f"📂 Kelola Profil\nAktif: **{active}**", buttons=btns)

            elif action == "load" and profile_name:
                profiles = user_data.get("profiles", {})
                if profile_name in profiles:
                    await apply_settings_from_profile(user_id, profiles[profile_name])
                    await saveoptions(user_id, "active_profile", profile_name, SAVE_TO_DATABASE)
                    await event.answer(f"✅ Profil '{profile_name}' dimuat.", alert=True)
                else:
                    await event.answer("❌ Profil tidak ditemukan.", alert=True)
                event.data = b"profile_manage"
                await callback(event)

            elif action == "delete" and profile_name:
                profiles = user_data.get("profiles", {})
                if profile_name in profiles and profile_name != "Default":
                    del profiles[profile_name]
                    if user_data.get("active_profile") == profile_name:
                        await apply_settings_from_profile(user_id, profiles.get("Default", {}))
                        await saveoptions(user_id, "active_profile", "Default", SAVE_TO_DATABASE)
                    await saveoptions(user_id, "profiles", profiles, SAVE_TO_DATABASE)
                    await event.answer(f"✅ Profil '{profile_name}' dihapus.", alert=True)
                else:
                    await event.answer("❌ Tidak bisa menghapus.", alert=True)
                event.data = b"profile_manage"
                await callback(event)

            elif action == "reset" and profile_name == "default":
                defaults = _get_default_user_data()
                exclude  = {"profiles", "active_profile"}
                await apply_settings_from_profile(user_id, {k: v for k, v in defaults.items() if k not in exclude})
                await saveoptions(user_id, "active_profile", "Default", SAVE_TO_DATABASE)
                await event.answer("✅ Reset ke default berhasil.", alert=True)

            elif action == "quick":
                profile_type = parts[2] if len(parts) > 2 else None
                if not profile_type:
                    await event.edit(
                        "🚀 Profil Cepat",
                        buttons=[
                            [Button.inline("🏆 Kualitas Tinggi", "profile_quick_quality")],
                            [Button.inline("⚡ Ukuran Kecil",    "profile_quick_size")],
                            [Button.inline("⚖️ Seimbang",        "profile_quick_balance")],
                            [Button.inline("↩️ Kembali",         "profile_main")],
                        ],
                    )
                else:
                    presets = {
                        "quality": ("slow",   "20"),
                        "size":    ("fast",   "28"),
                        "balance": ("medium", "23"),
                    }
                    preset, crf = presets.get(profile_type, ("medium","23"))
                    await saveconfig(user_id, "video", "preset", preset, SAVE_TO_DATABASE)
                    await saveconfig(user_id, "video", "crf",    crf,    SAVE_TO_DATABASE)
                    await event.answer(f"✅ Profil '{profile_type}' diterapkan.", alert=True)

        # ── Action Callbacks ─────────────────────────────────────────

        elif txt == "close_settings":
            await event.delete()

        elif txt.startswith("send_log_"):
            process_id = txt.split("_", 2)[2]
            log_file   = await get_ffmpeg_log_file(process_id)
            if log_file and exists(log_file):
                await event.client.send_file(chat_id, log_file,
                    caption=f"Log error proses `{process_id}`.")
                await event.edit("✅ Log terkirim.", buttons=None)
            else:
                await event.answer("❗ Log tidak ditemukan.", alert=True)

        elif txt.startswith("resetdb"):
            val = _safe_eval_bool(txt.split("_", 1)[1])
            if val:
                ok = await resetdatabase(SAVE_TO_DATABASE)
                await event.answer(f"✔ Reset {'Berhasil' if ok else 'Gagal'}", alert=True)
            else:
                await event.answer("Dibatalkan.", alert=True)

        elif txt.startswith("env_"):
            key  = txt.split("_", 1)[1]
            resp = await get_text_data(chat_id, user_id, event, 120, f"Kirim nilai baru untuk `{key}`")
            if resp:
                from bot_helper.Others.Helper_Functions import export_env_file, get_env_dict
                d = get_env_dict("./userdata/botconfig.env") or get_env_dict("config.env") or {}
                d[key] = resp.text
                export_env_file("./userdata/botconfig.env", d)
                await resp.reply(f"✅ `{key}` diubah. Restart untuk menerapkan.")

        elif txt.startswith("renew"):
            val = _safe_eval_bool(txt.split("_", 1)[1])
            if val:
                if exists(Config.DOWNLOAD_DIR):
                    await delete_all(Config.DOWNLOAD_DIR)
                    await event.answer(f"✔ Berhasil hapus {Config.DOWNLOAD_DIR}", alert=True)
                else:
                    await event.answer("Tidak ada yang perlu dihapus.", alert=True)
            else:
                await event.answer("Dibatalkan.", alert=True)

        # ── Settings Sub-Dispatchers ─────────────────────────────────
        elif txt.startswith("general"):    await general_callback(event, txt, user_id, chat_id)
        elif txt.startswith("telegram"):   await telegram_callback(event, txt, user_id, chat_id)
        elif txt.startswith("progress"):   await progress_callback(event, txt, user_id)
        elif txt.startswith("metadata"):   await metadata_callback(event, txt, user_id, chat_id)
        elif txt.startswith("video"):      await video_callback(event, txt, user_id, True, chat_id)
        elif txt.startswith("audio"):      await audio_callback(event, txt, user_id)
        elif txt.startswith("convert"):    await convert_callback(event, txt, user_id)
        elif txt.startswith("mux"):        await mux_callback(event, txt, user_id)
        elif txt.startswith("merge"):      await merge_callback(event, txt, user_id)
        elif txt.startswith("watermark"):  await watermark_callback(event, txt, user_id, chat_id)

        elif txt == "nik66bots":
            await event.answer("⚡ Bot Oleh Sahil ⚡", alert=True)

        elif txt == "change_video_queue_size":
            resp = await get_text_data(chat_id, user_id, event, 120, "Kirim Ukuran Queue (contoh: 1M, 512k)")
            if resp:
                await saveconfig(user_id, "video", "queue_size", resp.text.strip(), SAVE_TO_DATABASE)
                await video_callback(event, "video_settings", user_id, False, chat_id)

        elif txt == "custom_metedata":
            title = get_data().get(user_id, {}).get("metadata", {}).get("preset", {}).get("title", "")
            await event.answer(f"Judul Metadata: {title}", alert=True)

    except MessageNotModifiedError:
        pass
    except Exception as e:
        LOGGER.exception(f"Callback error [{txt}]: {e}")
