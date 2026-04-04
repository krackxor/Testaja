"""
╔══════════════════════════════════════════════════════════════════════╗
║            bot_helper/callbacks.py — v3.2                            ║
║            Callback Query Handler (Aiogram 3.x)                      ║
╠══════════════════════════════════════════════════════════════════════╣
║  FIXES dari versi lama:                                              ║
║  [NEW] Migrasi total dari Telethon CallbackQuery ke Aiogram          ║
║  [NEW] Menggunakan sistem wait_for_message dari shared.py            ║
║  [IMPROVE] Desain UI yang lebih interaktif, mudah dibaca, & rapi.    ║
║  [FIX] Menutup celah crash Markdown pada pesan respons.              ║
║  [FIX] Menyelesaikan error Pydantic ValidationError (Frozen Object)  ║
╚══════════════════════════════════════════════════════════════════════╝
"""

# ── Standard Library ──────────────────────────────────────────────────
import asyncio
import copy
import glob
from ast import literal_eval
from os import remove
from os.path import exists, splitext

# ── Aiogram ───────────────────────────────────────────────────────────
from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramBadRequest

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

# Memanggil fitur "Inline Waiter" dari shared.py
from bot.shared import wait_for_message

SAVE_TO_DATABASE = Config.SAVE_TO_DATABASE
LOGGER           = Config.LOGGER

router = Router()

def _get_db():
    if not SAVE_TO_DATABASE:
        return None
    from bot_helper.Database.DB_Handler import Database
    return Database()

def _safe_eval_bool(s: str) -> bool | None:
    if s == "True":
        return True
    if s == "False":
        return False
    return None

# ── UI Decorators ─────────────────────────────────────────────────────
def _menu_header(title: str) -> str:
    return f"╭─── • **{title.upper()}** • ───╮\n│\n"

def _menu_footer() -> str:
    return "\n│\n╰─╼ • Pilih Opsi di Bawah • ╾─╯"

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


def gen_keyboard(values_list, current_value, callvalue, items, hide):
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

        row.append(InlineKeyboardButton(text=text, callback_data=f"{callvalue}_{x}"))
    if row:
        boards.append(row)
    return boards


async def get_text_data(chat_id, user_id, call: CallbackQuery, timeout, message_text):
    """Integrasi dengan sistem Inline Waiter dari shared.py"""
    ask_msg = await call.message.reply(f"📌 {message_text}\n_Waktu: {timeout} detik_")
    try:
        resp = await wait_for_message(chat_id, user_id, timeout)
        await ask_msg.delete()
        return resp
    except asyncio.TimeoutError:
        try:
            await ask_msg.edit_text("🔃 Waktu Habis! Tugas Telah Dibatalkan.")
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

async def audio_callback(call: CallbackQuery, txt: str, user_id: int) -> None:
    try:
        new_position = txt.split("_", 1)[1]
    except IndexError:
        new_position = ""

    if txt.startswith("audioenable_"):
        val = _safe_eval_bool(new_position)
        if val is not None:
            await saveconfig(user_id, "audio", "enabled", val, SAVE_TO_DATABASE)
            await call.answer(f"✅ Audio {'Aktif' if val else 'Nonaktif'}")
    elif txt.startswith("audiocodec_"):
        await saveconfig(user_id, "audio", "codec", new_position, SAVE_TO_DATABASE)
        await call.answer(f"✅ Codec: {new_position.upper()}")
    elif txt.startswith("audioprofile_"):
        await saveconfig(user_id, "audio", "codec_profile", new_position, SAVE_TO_DATABASE)
        await call.answer(f"✅ Profil AAC: {new_position.upper()}")
    elif txt.startswith("audiobitrate_"):
        await saveconfig(user_id, "audio", "bitrate", new_position, SAVE_TO_DATABASE)
        await call.answer(f"✅ Bitrate: {new_position}")
    elif txt.startswith("audiochannels_"):
        await saveconfig(user_id, "audio", "channels", new_position, SAVE_TO_DATABASE)
        await call.answer(f"✅ Channel: {new_position}")
    elif txt.startswith("audiosamplerate_"):
        await saveconfig(user_id, "audio", "samplerate", new_position, SAVE_TO_DATABASE)
        await call.answer(f"✅ Sample Rate: {int(new_position)/1000}kHz")
    elif txt.startswith("audionorm_"):
        await saveconfig(user_id, "audio", "normalization", new_position, SAVE_TO_DATABASE)
        await call.answer(f"✅ Normalisasi: {new_position}")
    elif txt.startswith("audiofilter_"):
        await saveconfig(user_id, "audio", "filter", new_position, SAVE_TO_DATABASE)
        await call.answer(f"✅ Filter: {new_position}")
    elif txt.startswith("audiodownmix_"):
        await saveconfig(user_id, "audio", "downmix", new_position, SAVE_TO_DATABASE)
        await call.answer(f"✅ Downmix: {new_position}")

    audio = get_data().get(user_id, {}).get("audio", {})
    enabled = audio.get("enabled", True)
    KB = []
    KB.append([InlineKeyboardButton(text=f'Status Audio — {"ON ✅" if enabled else "OFF ❌"}', callback_data="nik66bots")])
    KB.extend(gen_keyboard(bool_list, enabled, "audioenable", 2, False))
    if enabled:
        KB.append([InlineKeyboardButton(text=f"🎧 Codec — {audio.get('codec','Auto').upper()}", callback_data="nik66bots")])
        KB.extend(gen_keyboard(audio_codec_list, audio.get("codec","Auto"), "audiocodec", 4, False))
        if audio.get("codec") == "aac":
            KB.append([InlineKeyboardButton(text=f"Profil AAC — {audio.get('codec_profile','Auto')}", callback_data="nik66bots")])
            KB.extend(gen_keyboard(aac_profile_list, audio.get("codec_profile","Auto"), "audioprofile", 3, False))
        if audio.get("codec") not in ["pcm","flac","Auto","copy"]:
            KB.append([InlineKeyboardButton(text=f"🎚 Bitrate — {audio.get('bitrate','Auto')}", callback_data="nik66bots")])
            KB.extend(gen_keyboard(audio_bitrate_list, audio.get("bitrate","Auto"), "audiobitrate", 4, False))
        KB.append([InlineKeyboardButton(text=f"🔊 Channel — {audio.get('channels','Auto')}", callback_data="nik66bots")])
        KB.extend(gen_keyboard(audio_channels_list, audio.get("channels","Auto"), "audiochannels", 3, False))
        sr = audio.get("samplerate","Auto")
        sr_display = sr if sr == "Auto" else f"{int(sr)/1000}kHz"
        KB.append([InlineKeyboardButton(text=f"📻 Sample Rate — {sr_display}", callback_data="nik66bots")])
        KB.extend(gen_keyboard(audio_samplerate_list, sr, "audiosamplerate", 3, False))
        KB.append([InlineKeyboardButton(text=f"🎛 Normalisasi — {audio.get('normalization','Off')}", callback_data="nik66bots")])
        KB.extend(gen_keyboard(audio_norm_list, audio.get("normalization","Off"), "audionorm", 3, False))
        KB.append([InlineKeyboardButton(text=f"🎛 Filter — {audio.get('filter','Off')}", callback_data="nik66bots")])
        KB.extend(gen_keyboard(audio_filter_list, audio.get("filter","Off"), "audiofilter", 4, False))
        KB.append([InlineKeyboardButton(text=f"🎛 Downmix — {audio.get('downmix','Off')}", callback_data="nik66bots")])
        KB.extend(gen_keyboard(audio_downmix_list, audio.get("downmix","Off"), "audiodownmix", 3, False))
    KB.append([InlineKeyboardButton(text="↩️ Kembali ke Media", callback_data="settings_media")])
    
    try:
        msg = _menu_header("Pengaturan Audio") + "Sesuaikan pengaturan ekstraksi dan kompresi Audio." + _menu_footer()
        await call.message.edit_text(msg, reply_markup=InlineKeyboardMarkup(inline_keyboard=KB))
    except Exception:
        pass


async def video_callback(call: CallbackQuery, txt: str, user_id: int, edit: bool, chat_id: int) -> None:
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
            resp = await get_text_data(chat_id, user_id, call, 120, "Kirim nilai CRF (0-51)")
            if resp:
                try:
                    crf = int(resp.text)
                    if 0 <= crf <= 51:
                        await saveconfig(user_id, "video", "crf", str(crf), SAVE_TO_DATABASE)
                        await resp.reply(f"✅ CRF diatur ke {crf}")
                        edit = False
                    else:
                        await resp.reply("❌ Nilai CRF harus antara 0 hingga 51.")
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
    elif txt.startswith("videotune_"):        await saveconfig(user_id, "video", "tune",        new_pos, SAVE_TO_DATABASE)
    elif txt.startswith("videocabac_"):       await saveconfig(user_id, "video", "cabac",       new_pos, SAVE_TO_DATABASE)
    elif txt.startswith("videofast_start_"):  await saveconfig(user_id, "video", "fast_start",  new_pos, SAVE_TO_DATABASE)
    elif txt.startswith("videobit_depth_"):   await saveconfig(user_id, "video", "bit_depth",   new_pos, SAVE_TO_DATABASE)
    elif txt.startswith("videopixel_format_"):await saveconfig(user_id, "video", "pixel_format", new_pos, SAVE_TO_DATABASE)
    elif txt.startswith("videoresolution_"):
        if new_pos == "Custom":
            resp = await get_text_data(chat_id, user_id, call, 120, "Kirim resolusi kustom (contoh: `1280x720`)")
            if resp:
                await saveconfig(user_id, "video", "resolution", resp.text, SAVE_TO_DATABASE)
                await resp.reply(f"✅ Resolusi diatur ke: `{resp.text}`")
                edit = False
        else:
            await saveconfig(user_id, "video", "resolution", new_pos, SAVE_TO_DATABASE)

    vs   = get_data().get(user_id, {}).get("video", {})
    enab = vs.get("enabled", True)
    enc  = vs.get("encoder", "libx264")
    KB   = []
    KB.append([InlineKeyboardButton(text=f'Status Video — {"ON ✅" if enab else "OFF ❌"}', callback_data="nik66bots")])
    KB.extend(gen_keyboard(bool_list, enab, "videoenable", 2, False))
    if enab:
        KB.append([InlineKeyboardButton(text=f"🎞 Encoder — {enc}", callback_data="nik66bots")])
        KB.extend(gen_keyboard(encoders_list, enc, "videoencoder", 2, False))
        KB.append([InlineKeyboardButton(text=f"⚡ Preset — {vs.get('preset','medium')}", callback_data="nik66bots")])
        KB.extend(gen_keyboard(presets_list, vs.get("preset","medium"), "videopreset", 3, False))
        KB.append([InlineKeyboardButton(text=f"🎚 CRF (Kualitas) — {vs.get('crf','23')}", callback_data="nik66bots")])
        KB.extend(gen_keyboard(crf_list, vs.get("crf","23"), "videocrf", 4, False))
        KB.append([InlineKeyboardButton(text=f"📺 Resolusi — {vs.get('resolution','Auto')}", callback_data="nik66bots")])
        KB.extend(gen_keyboard(resolution_list, vs.get("resolution","Auto"), "videoresolution", 5, False))
        KB.append([InlineKeyboardButton(text=f"🎨 Format Piksel — {vs.get('pixel_format','Auto')}", callback_data="nik66bots")])
        KB.extend(gen_keyboard(pixel_format_list, vs.get("pixel_format","Auto"), "videopixel_format", 3, False))
        KB.append([InlineKeyboardButton(text=f"🎭 Tune — {vs.get('tune','None')}", callback_data="nik66bots")])
        KB.extend(gen_keyboard(tune_list, vs.get("tune","None"), "videotune", 3, False))
        KB.append([InlineKeyboardButton(text=f"📁 Ekstensi — {vs.get('extension','MKV')}", callback_data="nik66bots")])
        KB.extend(gen_keyboard(extension_list, vs.get("extension","MKV"), "videoextension", 3, False))
        if enc == "libx264":
            KB.append([InlineKeyboardButton(text=f"CABAC — {vs.get('cabac','On')}", callback_data="nik66bots")])
            KB.extend(gen_keyboard(cabac_list, vs.get("cabac","On"), "videocabac", 2, False))
        if vs.get("extension","MKV") == "MP4":
            KB.append([InlineKeyboardButton(text=f"Fast Start — {vs.get('fast_start','Yes')}", callback_data="nik66bots")])
            KB.extend(gen_keyboard(fast_start_list, vs.get("fast_start","Yes"), "videofast_start", 2, False))
            
        KB.append([InlineKeyboardButton(text="─── Lainnya ───", callback_data="nik66bots")])
        KB.append([InlineKeyboardButton(text=f"Salin Subtitle — {vs.get('copy_sub',True)}", callback_data="nik66bots")])
        KB.extend(gen_keyboard(bool_list, vs.get("copy_sub",True), "videocopysub", 2, False))
        KB.append([InlineKeyboardButton(text=f"Peta — {vs.get('map',True)}", callback_data="nik66bots")])
        KB.extend(gen_keyboard(bool_list, vs.get("map",True), "videomap", 2, False))
        qs = vs.get("use_queue_size", False)
        KB.append([InlineKeyboardButton(text=f"Gunakan Queue Size — {qs}", callback_data="nik66bots")])
        if qs:
            KB.append([InlineKeyboardButton(text=f"Queue Size — {vs.get('queue_size','1M')} (Klik Ubah)", callback_data="change_video_queue_size")])
        KB.extend(gen_keyboard(bool_list, qs, "videousequeuesize", 2, False))
        KB.append([InlineKeyboardButton(text=f"SYNC — {vs.get('sync',False)}", callback_data="nik66bots")])
        KB.extend(gen_keyboard(bool_list, vs.get("sync",False), "videosync", 2, False))
        
    KB.append([InlineKeyboardButton(text="↩️ Kembali ke Media", callback_data="settings_media")])
    
    msg = _menu_header("Pengaturan Video") + "Sesuaikan parameter kompresi dan kualitas Video." + _menu_footer()
    markup = InlineKeyboardMarkup(inline_keyboard=KB)
    
    if edit:
        try: await call.message.edit_text(msg, reply_markup=markup)
        except Exception: pass
    else:
        try: await call.message.delete()
        except Exception: pass
        await call.message.answer(msg, reply_markup=markup)


async def general_callback(call: CallbackQuery, txt: str, user_id: int, chat_id: int) -> None:
    new_pos = txt.split("_", 1)[1] if "_" in txt else ""
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
                await call.answer("❗ Simpan Konfigurasi Rclone Terlebih Dahulu", show_alert=True)
                return
            await saveoptions(user_id, "upload_tg", val, SAVE_TO_DATABASE)
    elif txt.startswith("generaldrivename"): await saveoptions(user_id, "drive_name", new_pos, SAVE_TO_DATABASE)
    elif txt.startswith("generalautodrive"):
        val = _safe_eval_bool(new_pos)
        if val is not None:
            if val and not (check_cfg and drive_name):
                await call.answer("❗ Simpan Konfigurasi Rclone Terlebih Dahulu", show_alert=True)
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
        # Tambahkan indikator status visual (ON/OFF)
        status_icon = "🟢" if val is True else "🔴" if val is False else ""
        KB.append([InlineKeyboardButton(text=f"{label} — {val} {status_icon}".strip(), callback_data="nik66bots")])
        KB.extend(gen_keyboard(opts, val, f"general{key.replace('_','')}", items, False))

    _row("🥝 Audio Otomatis", "select_stream", True, bool_list, 2)
    _row("🍭 Audio Utama",   "stream",        "ENG",  ["ENG","HIN"], 2)
    _row("🪓 Bagi Video",     "split_video",   True,  bool_list, 2)
    _row("🛢 Ukuran Bagi",    "split",         "2GB", ["2GB","4GB"], 2)
    _row("🖼 Thumbnail",   "custom_thumbnail", True, bool_list, 2)
    _row("🧵 Unggah ke Telegram",  "upload_tg",      True,  bool_list, 2)
    _row("🕹 Auto Drive",   "auto_drive",     False, bool_list, 2)
    _row("📷 Screenshot",     "gen_ss",         True,  bool_list, 2)
    _row("🎶 Jumlah Screenshot",   "ss_no",          5,     [3,5,7,10], 4)
    _row("🎞 Video Sampel",   "gen_sample",     True,  bool_list, 2)
    _row("🛰 Multi-Tugas","multi_tasks",    True,  bool_list, 2)
    _row("⏹ Unggah Setiap File",  "upload_all",     False, bool_list, 2)

    drive_name = get_data().get(user_id, {}).get("drive_name", "")
    if check_cfg:
        accounts = await get_config(r_config)
        if accounts:
            KB.append([InlineKeyboardButton(text=f"🔮 Akun Rclone — {drive_name}", callback_data="nik66bots")])
            KB.extend(gen_keyboard(accounts, drive_name, "generaldrivename", 2, False))

    KB.append([InlineKeyboardButton(text="↩️ Kembali ke Umum", callback_data="settings_bot")])
    
    msg = _menu_header("Pengaturan Umum") + "Sesuaikan perilaku bot secara keseluruhan." + _menu_footer()
    try:
        await call.message.edit_text(msg, reply_markup=InlineKeyboardMarkup(inline_keyboard=KB))
    except Exception:
        pass


async def progress_callback(call: CallbackQuery, txt: str, user_id: int) -> None:
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
        status_icon = "🟢" if val is True else "🔴" if val is False else ""
        KB.append([InlineKeyboardButton(text=f"{label} — {val} {status_icon}".strip(), callback_data="nik66bots")])
        KB.extend(gen_keyboard(opts, val, f"progress{key.replace('_','')}", items, False))

    _row("📋 Pesan Detail",       "detailed_messages", True,  bool_list, 2)
    _row("📊 Tampilkan Statistik","show_stats",          False, bool_list, 2)
    _row("📀 Ukuran Output FFMPEG","ffmpeg_size",        True,  bool_list, 2)
    _row("⏲ Waktu Proses",        "ffmpeg_ptime",        True,  bool_list, 2)
    _row("⌚ Tampilkan Jam",      "show_time",           False, bool_list, 2)
    ut = ud.get("update_time", 7)
    KB.append([InlineKeyboardButton(text=f"⏱ Durasi Pembaruan GUI — {ut}s", callback_data="nik66bots")])
    KB.extend(gen_keyboard([5,6,7,8,9,10], ut, "progressupdatetime", 3, False))
    KB.append([InlineKeyboardButton(text="↩️ Kembali ke Umum", callback_data="settings_bot")])
    
    msg = _menu_header("Tampilan Progress") + "Atur informasi yang muncul pada bilah proses (progress bar)." + _menu_footer()
    try:
        await call.message.edit_text(msg, reply_markup=InlineKeyboardMarkup(inline_keyboard=KB))
    except Exception:
        pass


async def telegram_callback(call: CallbackQuery, txt: str, user_id: int, chat_id: int) -> None:
    new_pos = txt.split("_", 1)[1] if "_" in txt else ""
    if txt.startswith("telegramupload"):
        await saveoptions(user_id, "tgupload", new_pos, SAVE_TO_DATABASE)
    elif txt.startswith("telegramdownload"):
        await saveoptions(user_id, "tgdownload", new_pos, SAVE_TO_DATABASE)
    ud  = get_data().get(user_id, {})
    up  = ud.get("tgupload",   "Telethon")
    dw  = ud.get("tgdownload", "Telethon")
    KB  = [
        [InlineKeyboardButton(text=f"🔼 Mesin Unggah — {up}", callback_data="nik66bots")],
        *gen_keyboard(["Telethon","Pyrogram"], up, "telegramupload", 2, False),
        [InlineKeyboardButton(text=f"🔽 Mesin Unduh — {dw}", callback_data="nik66bots")],
        *gen_keyboard(["Telethon","Pyrogram"], dw, "telegramdownload", 2, False),
        [InlineKeyboardButton(text="↩️ Kembali ke Umum", callback_data="settings_bot")],
    ]
    
    msg = _menu_header("Mesin Telegram") + "Pilih pustaka koneksi data (Pyrogram biasanya lebih cepat)." + _menu_footer()
    try:
        await call.message.edit_text(msg, reply_markup=InlineKeyboardMarkup(inline_keyboard=KB))
    except Exception:
        pass


async def metadata_callback(call: CallbackQuery, txt: str, user_id: int, chat_id: int) -> None:
    new_pos = txt.split("_", 1)[1] if "_" in txt else ""
    edit = True
    if txt.startswith("metadataenable_"):
        val = _safe_eval_bool(new_pos)
        if val is not None: await saveconfig(user_id, "metadata", "enabled", val, SAVE_TO_DATABASE)
    elif txt.startswith("metadatamode_"):
        await saveconfig(user_id, "metadata", "mode", new_pos, SAVE_TO_DATABASE)
    elif txt.startswith("metadatapreset_"):
        field = new_pos
        resp  = await get_text_data(chat_id, user_id, call, 120, f"Kirim teks baru untuk atribut '{field.upper()}'")
        if resp:
            presets = get_data().get(user_id, {}).get("metadata", {}).get("preset", {})
            presets[field] = resp.text
            await saveconfig(user_id, "metadata", "preset", presets, SAVE_TO_DATABASE)
            await resp.reply(f"✅ Atribut '{field}' berhasil diubah.")
            edit = False
    elif txt.startswith("metadatacustom_"):
        resp = await get_text_data(chat_id, user_id, call, 300,
                                    "Kirim kode metadata ffmpeg kustom Anda.")
        if resp:
            await saveconfig(user_id, "metadata", "custom", resp.text, SAVE_TO_DATABASE)
            await resp.reply("✅ Kode kustom berhasil disimpan.")
            edit = False

    md      = get_data().get(user_id, {}).get("metadata", {})
    enabled = md.get("enabled", False)
    KB      = []
    KB.append([InlineKeyboardButton(text=f'Status Penyemat Metadata — {"ON ✅" if enabled else "OFF ❌"}', callback_data="nik66bots")])
    KB.extend(gen_keyboard(bool_list, enabled, "metadataenable", 2, False))
    if enabled:
        mode = md.get("mode","preset")
        KB.append([InlineKeyboardButton(text=f"⚙️ Mode Pengisian — {mode.upper()}", callback_data="nik66bots")])
        KB.extend(gen_keyboard(["preset","custom"], mode, "metadatamode", 2, False))
        if mode == "preset":
            p = md.get("preset", {})
            KB.append([InlineKeyboardButton(text="─── 📋 NILAI PRESET METADATA ───", callback_data="nik66bots")])
            for field in ["title","author","year","comment","genre"]:
                val = p.get(field,'(Kosong)')
                KB.append([InlineKeyboardButton(text=f"{field.capitalize()}: {val}", callback_data=f"metadatapreset_{field}")])
        else:
            KB.append([InlineKeyboardButton(text="─── 💻 KODE FFMPEG KUSTOM ───", callback_data="nik66bots")])
            KB.append([InlineKeyboardButton(text="Ubah Kode Metadata Kustom", callback_data="metadatacustom_change")])
    KB.append([InlineKeyboardButton(text="↩️ Kembali ke Media", callback_data="settings_media")])
    
    msg = _menu_header("Pengaturan Metadata") + "Sematkan informasi hak cipta atau judul ke dalam video." + _menu_footer()
    markup = InlineKeyboardMarkup(inline_keyboard=KB)
    if edit:
        try: await call.message.edit_text(msg, reply_markup=markup)
        except Exception: pass
    else:
        await call.message.answer(msg, reply_markup=markup)


async def convert_callback(call: CallbackQuery, txt: str, user_id: int) -> None:
    current = get_data().get(user_id, {}).get("convert", {}).get("convert_list", [])
    if txt == "convert_clear_all":
        current = []
        await saveconfig(user_id, "convert", "convert_list", [], SAVE_TO_DATABASE)
        await call.answer("✅ Pilihan dihapus semua.", show_alert=True)
    elif txt.startswith("convert_toggle_"):
        try:
            val = int(txt.split("_")[-1])
            if val in current: current.remove(val)
            else:              current.append(val)
            current.sort(reverse=True)
            await saveconfig(user_id, "convert", "convert_list", current, SAVE_TO_DATABASE)
        except (ValueError, IndexError):
            pass
    KB    = [[InlineKeyboardButton(text="Pilih Kualitas Output (Bisa Multi)", callback_data="nik66bots")]]
    row   = []
    for name, val in sorted(convert_qualities.items(), key=lambda x: x[1], reverse=True):
        txt_ = f"{name} 🟢" if val in current else name
        row.append(InlineKeyboardButton(text=txt_, callback_data=f"convert_toggle_{val}"))
        if len(row) == 3:
            KB.append(row)
            row = []
    if row:
        KB.append(row)
    KB.append([InlineKeyboardButton(text="❌ Hapus Semua Pilihan", callback_data="convert_clear_all")])
    KB.append([InlineKeyboardButton(text="↩️ Kembali ke Media", callback_data="settings_media")])
    
    msg = _menu_header("Resolusi Konversi") + "Centang resolusi target untuk mode kompresi massa." + _menu_footer()
    try:
        await call.message.edit_text(msg, reply_markup=InlineKeyboardMarkup(inline_keyboard=KB))
    except Exception:
        pass


async def mux_callback(call: CallbackQuery, txt: str, user_id: int) -> None:
    new_pos = txt.split("_", 1)[1] if "_" in txt else ""
    if txt.startswith("muxsubcodec_"):
        await saveconfig(user_id, "mux", "sub_codec", new_pos, SAVE_TO_DATABASE)
    mux_codec = get_data().get(user_id, {}).get("mux", {}).get("sub_codec", "copy")
    KB = [
        [InlineKeyboardButton(text=f"🔤 Codec Subtitle — {mux_codec.upper()}", callback_data="nik66bots")],
        *gen_keyboard(["copy","mov_text"], mux_codec, "muxsubcodec", 2, False),
        [InlineKeyboardButton(text="↩️ Kembali ke Media", callback_data="settings_media")],
    ]
    
    msg = _menu_header("Pengaturan MUX") + "Atur cara video menyematkan berkas subtitle." + _menu_footer()
    try:
        await call.message.edit_text(msg, reply_markup=InlineKeyboardMarkup(inline_keyboard=KB))
    except Exception:
        pass


async def merge_callback(call: CallbackQuery, txt: str, user_id: int) -> None:
    new_pos = txt.split("_", 1)[1] if "_" in txt else ""
    if txt.startswith("mergemap"):
        val = _safe_eval_bool(new_pos)
        if val is not None: await saveconfig(user_id, "merge", "map", val, SAVE_TO_DATABASE)
    elif txt.startswith("mergefixblank"):
        val = _safe_eval_bool(new_pos)
        if val is not None: await saveconfig(user_id, "merge", "fix_blank", val, SAVE_TO_DATABASE)
    mg = get_data().get(user_id, {}).get("merge", {})
    KB = [
        [InlineKeyboardButton(text=f"🗺 Peta (Map) — {'ON ✅' if mg.get('map',True) else 'OFF ❌'}", callback_data="nik66bots")],
        *gen_keyboard(bool_list, mg.get("map",True), "mergemap", 2, False),
        [InlineKeyboardButton(text=f"🩹 Perbaiki Layar Hitam (Blank) — {'ON ✅' if mg.get('fix_blank',False) else 'OFF ❌'}", callback_data="nik66bots")],
        *gen_keyboard(bool_list, mg.get("fix_blank",False), "mergefixblank", 2, False),
        [InlineKeyboardButton(text="↩️ Kembali ke Media", callback_data="settings_media")],
    ]
    
    msg = _menu_header("Pengaturan Gabung Video") + "Atur perilaku alat penggabung video (merge)." + _menu_footer()
    try:
        await call.message.edit_text(msg, reply_markup=InlineKeyboardMarkup(inline_keyboard=KB))
    except Exception:
        pass


async def watermark_callback(call: CallbackQuery, txt: str, user_id: int, chat_id: int) -> None:
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
        await watermark_image_menu(call, txt, user_id, chat_id)
        return
    if txt.startswith("watermark_text"):
        await watermark_text_menu(call, txt, user_id, chat_id)
        return

    is_en   = settings.get("enabled", False)
    wm_type = settings.get("type", "image")
    KB      = [
        [InlineKeyboardButton(text=f'Status Watermark: {"AKTIF ✅" if is_en else "NONAKTIF ❌"}', callback_data="nik66bots")],
        gen_keyboard(bool_list, is_en, "watermark_enable", 2, False)[0],
    ]
    if is_en:
        KB.append([InlineKeyboardButton(text="─── Jenis Watermark ───", callback_data="nik66bots")])
        KB.append([
            InlineKeyboardButton(text=f'{"🖼️ GAMBAR 🟢" if wm_type=="image" else "🖼️ Gambar"}', callback_data="watermark_type_image"),
            InlineKeyboardButton(text=f'{"✍️ TEKS 🟢" if wm_type=="text" else "✍️ Teks"}', callback_data="watermark_type_text"),
        ])
        if wm_type == "image":
            KB.append([InlineKeyboardButton(text="➡️ Masuk Ke Menu Watermark GAMBAR", callback_data="watermark_image_menu")])
        else:
            KB.append([InlineKeyboardButton(text="➡️ Masuk Ke Menu Watermark TEKS", callback_data="watermark_text_menu")])
    KB.append([InlineKeyboardButton(text="↩️ Kembali ke Media", callback_data="settings_media")])
    
    msg = _menu_header("Watermark Global") + "Tempelkan Logo atau Teks pada video Anda." + _menu_footer()
    try:
        await call.message.edit_text(msg, reply_markup=InlineKeyboardMarkup(inline_keyboard=KB))
    except Exception:
        pass


async def watermark_image_menu(call: CallbackQuery, txt: str, user_id: int, chat_id: int) -> None:
    wm_path = f"./userdata/{user_id}_watermark.jpg"

    if txt == "watermark_image_upload":
        await call.message.delete()
        resp = await get_text_data(chat_id, user_id, call, 120, "Kirim gambar (JPG/PNG) untuk dijadikan watermark.")
        if resp and (resp.photo or resp.document):
            target_media = resp.photo[-1] if resp.photo else resp.document
            await Telegram.AIOGRAM_BOT.download(target_media, destination=wm_path)
            await resp.reply("✅ Gambar Watermark berhasil disimpan.")
        elif resp:
            await resp.reply("❌ Berkas bukan gambar.")
        await call.message.answer("Aksi Selesai:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Kembali Ke Menu Gambar", callback_data="watermark_image_menu")]]))
        return

    elif txt == "watermark_image_view":
        if exists(wm_path):
            await call.message.delete()
            from aiogram.types import FSInputFile
            await call.message.answer_photo(FSInputFile(wm_path), caption="🖼 Watermark gambar Anda saat ini.")
            await call.message.answer("Aksi Selesai:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Kembali Ke Menu Gambar", callback_data="watermark_image_menu")]]))
        else:
            await call.answer("❗ Belum ada watermark gambar tersimpan.", show_alert=True)
        return

    elif txt == "watermark_image_delete":
        if exists(wm_path):
            remove(wm_path)
            await call.answer("✅ Watermark berhasil dihapus.", show_alert=True)
        else:
            await call.answer("❗ Tidak ada watermark untuk dihapus.", show_alert=True)

    elif txt.startswith("watermark_image_duration_"):
        parts  = txt.split("_")
        action = parts[3]
        setts  = get_data().get(user_id, {}).get("watermark", {})
        if action == "mode":
            setts["image"]["duration"]["mode"] = parts[4]
        elif action == "from":
            resp = await get_text_data(chat_id, user_id, call, 120, "Kirim Waktu Mulai (Format HH:MM:SS):")
            if resp: setts["image"]["duration"]["from"] = resp.text
        elif action == "to":
            resp = await get_text_data(chat_id, user_id, call, 120, "Kirim Waktu Selesai (Format HH:MM:SS):")
            if resp: setts["image"]["duration"]["to"] = resp.text
        elif action == "interval":
            resp = await get_text_data(chat_id, user_id, call, 120, "Kirim Nilai Interval kedipan (dalam detik):")
            if resp and resp.text.isdigit():
                setts["image"]["duration"]["interval"] = int(resp.text)
        await saveoptions(user_id, "watermark", setts, SAVE_TO_DATABASE)
        await call.answer("✅ Pengaturan durasi gambar disimpan.")

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
            await call.answer("✅ Posisi gambar diubah.")
        elif part_type == "size" and new_pos:
            setts["image"]["size"] = new_pos
            await saveoptions(user_id, "watermark", setts, SAVE_TO_DATABASE)
            await call.answer(f"✅ Skala Ukuran: {new_pos}%")

    setts      = get_data().get(user_id, {}).get("watermark", {})
    img        = setts.get("image", {})
    dur        = img.get("duration", {})
    cur_pos    = img.get("position", "bottom_right")
    cur_size   = img.get("size", "12")
    v2i        = {v: k for k, v in ws_image_positions.items()}
    cur_icon   = v2i.get(cur_pos, "↘️")
    KB = [
        [InlineKeyboardButton(text="⬆️ Unggah Logo", callback_data="watermark_image_upload"),
         InlineKeyboardButton(text="🖼️ Cek Logo",   callback_data="watermark_image_view"),
         InlineKeyboardButton(text="🗑️ Hapus Logo", callback_data="watermark_image_delete")],
        [InlineKeyboardButton(text=f"📍 Posisi Saat Ini: {cur_icon}", callback_data="nik66bots")],
    ]
    row = []
    for icon, val in ws_image_positions.items():
        text = f"{icon} 🟢" if val == cur_pos else icon
        row.append(InlineKeyboardButton(text=text, callback_data=f"watermark_image_position_{val}"))
        if len(row) == 3:
            KB.append(row)
            row = []
    if row:
        KB.append(row)
    KB.append([InlineKeyboardButton(text=f"📏 Skala Ukuran Logo: {cur_size}%", callback_data="nik66bots")])
    KB.extend(gen_keyboard(wsize_list, cur_size, "watermark_image_size", 6, False))
    KB.append([InlineKeyboardButton(text="─── Perilaku Waktu ───", callback_data="nik66bots")])
    dur_mode = dur.get("mode","full")
    KB.append([
        InlineKeyboardButton(text=f'{"Tampil Terus 🟢" if dur_mode=="full" else "Tampil Terus"}', callback_data="watermark_image_duration_mode_full"),
        InlineKeyboardButton(text=f'{"Batas Waktu 🟢" if dur_mode=="range" else "Batas Waktu"}',        callback_data="watermark_image_duration_mode_range"),
        InlineKeyboardButton(text=f'{"Kedip/Interval 🟢" if dur_mode=="interval" else "Kedip/Interval"}',  callback_data="watermark_image_duration_mode_interval"),
    ])
    if dur_mode == "range":
        KB.append([InlineKeyboardButton(text=f"Mulai: {dur.get('from','00:00:00')}", callback_data="watermark_image_duration_from"),
                   InlineKeyboardButton(text=f"Berhenti: {dur.get('to','00:00:00')}",   callback_data="watermark_image_duration_to")])
    elif dur_mode == "interval":
        KB.append([InlineKeyboardButton(text=f"Durasi Kedip Tiap: {dur.get('interval',30)} detik", callback_data="watermark_image_duration_interval")])
    KB.append([InlineKeyboardButton(text="↩️ Kembali ke Watermark", callback_data="watermark_settings")])
    
    msg = _menu_header("Watermark Gambar") + "Kustomisasi peletakan logo (File PNG/JPG disarankan)." + _menu_footer()
    try:
        await call.message.edit_text(msg, reply_markup=InlineKeyboardMarkup(inline_keyboard=KB))
    except Exception:
        pass


async def watermark_text_menu(call: CallbackQuery, txt: str, user_id: int, chat_id: int) -> None:
    font_glob = f"./userdata/{user_id}_watermark_font.*"

    if txt == "watermark_text_input":
        await call.message.delete()
        resp = await get_text_data(chat_id, user_id, call, 120, "Kirim teks kalimat yang ingin dijadikan watermark:")
        if resp:
            setts = get_data().get(user_id, {}).get("watermark", {})
            setts["text"]["content"] = resp.text
            await saveoptions(user_id, "watermark", setts, SAVE_TO_DATABASE)
            await resp.reply("✅ Kalimat teks berhasil disimpan.")
        await call.message.answer("Aksi Selesai:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Kembali Ke Menu Teks", callback_data="watermark_text_menu")]]))
        return

    elif txt == "watermark_text_upload_font":
        await call.message.delete()
        resp = await get_text_data(chat_id, user_id, call, 120, "Kirim file font kustom berformat (`.ttf` atau `.otf`):")
        if resp and resp.document:
            try:
                fname = resp.document.file_name
                _, ext = splitext(fname)
                if ext.lower() in [".ttf", ".otf"]:
                    for f in glob.glob(font_glob): remove(f)
                    await Telegram.AIOGRAM_BOT.download(resp.document, destination=f"./userdata/{user_id}_watermark_font{ext.lower()}")
                    await resp.reply(f"✅ File Font `{fname}` berhasil ditambahkan.")
                else:
                    await resp.reply("❌ Format font tidak didukung. Harap kirim ekstensi .ttf atau .otf")
            except Exception as e:
                await resp.reply(f"❌ Terjadi kesalahan: `{e}`")
        await call.message.answer("Aksi Selesai:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Kembali Ke Menu Teks", callback_data="watermark_text_menu")]]))
        return

    elif txt == "watermark_text_view_font":
        fonts = glob.glob(font_glob)
        name  = fonts[0].split("/")[-1] if fonts else None
        await call.answer(f"File Font: {name}" if name else "Menggunakan Font Default sistem.", show_alert=True)
        return

    elif txt == "watermark_text_delete_font":
        fonts = glob.glob(font_glob)
        if fonts:
            for f in fonts: remove(f)
            await call.answer("✅ Font kustom dihapus. Menggunakan Default sistem.", show_alert=True)
        else:
            await call.answer("❗ Anda sedang tidak menggunakan font kustom.", show_alert=True)

    elif txt.startswith("watermark_text_duration_"):
        parts  = txt.split("_")
        action = parts[3]
        setts  = get_data().get(user_id, {}).get("watermark", {})
        if action == "mode":
            setts["text"]["duration"]["mode"] = parts[4]
        elif action == "from":
            resp = await get_text_data(chat_id, user_id, call, 120, "Kirim Waktu Mulai (Format HH:MM:SS):")
            if resp: setts["text"]["duration"]["from"] = resp.text
        elif action == "to":
            resp = await get_text_data(chat_id, user_id, call, 120, "Kirim Waktu Selesai (Format HH:MM:SS):")
            if resp: setts["text"]["duration"]["to"] = resp.text
        elif action == "interval":
            resp = await get_text_data(chat_id, user_id, call, 120, "Kirim Nilai Interval kedipan (dalam detik):")
            if resp and resp.text.isdigit():
                setts["text"]["duration"]["interval"] = int(resp.text)
        await saveoptions(user_id, "watermark", setts, SAVE_TO_DATABASE)
        await call.answer("✅ Pengaturan durasi teks disimpan.")

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
            await call.answer("✅ Posisi teks diubah.")
        elif part == "size" and new_pos:
            setts["text"]["font_size"] = new_pos
            await saveoptions(user_id, "watermark", setts, SAVE_TO_DATABASE)
            await call.answer(f"✅ Ukuran Font Teks: {new_pos}px")
        elif part == "color" and new_pos:
            setts["text"]["font_color"] = new_pos
            await saveoptions(user_id, "watermark", setts, SAVE_TO_DATABASE)
            await call.answer(f"✅ Warna Teks: {new_pos}")

    setts     = get_data().get(user_id, {}).get("watermark", {})
    ts        = setts.get("text", {})
    dur       = ts.get("duration", {})
    cur_pos   = ts.get("position", "bottom_right")
    cur_size  = ts.get("font_size", "24")
    cur_color = ts.get("font_color", "white")
    v2i       = {v: k for k, v in ws_text_positions.items()}
    cur_icon  = v2i.get(cur_pos, "↘️")
    
    clean_txt = str(ts.get('content','(Belum diisi)')).replace("`","").replace("*","")
    
    KB = [
        [InlineKeyboardButton(text="✍️ Tulis Teks", callback_data="watermark_text_input")],
        [InlineKeyboardButton(text="⬆️ Upload Font", callback_data="watermark_text_upload_font"),
         InlineKeyboardButton(text="📄 Cek Font", callback_data="watermark_text_view_font"),
         InlineKeyboardButton(text="🗑️ Hapus Font", callback_data="watermark_text_delete_font")],
        [InlineKeyboardButton(text=f"📜 Kalimat: '{clean_txt}'", callback_data="nik66bots")],
        [InlineKeyboardButton(text=f"📍 Posisi Teks: {cur_icon}", callback_data="nik66bots")],
    ]
    row = []
    for icon, val in ws_text_positions.items():
        text = f"{icon} 🟢" if val == cur_pos else icon
        row.append(InlineKeyboardButton(text=text, callback_data=f"watermark_text_position_{val}"))
        if len(row) == 3:
            KB.append(row)
            row = []
    if row: KB.append(row)
    KB.append([InlineKeyboardButton(text=f"📐 Ukuran Font: {cur_size}px", callback_data="nik66bots")])
    KB.extend(gen_keyboard(font_size_list, cur_size, "watermark_text_size", 4, False))
    KB.append([InlineKeyboardButton(text=f"🎨 Warna Font: {cur_color.capitalize()}", callback_data="nik66bots")])
    KB.extend(gen_keyboard(font_colors, cur_color, "watermark_text_color", 3, False))
    KB.append([InlineKeyboardButton(text="─── Perilaku Waktu ───", callback_data="nik66bots")])
    dur_mode = dur.get("mode","full")
    KB.append([
        InlineKeyboardButton(text=f'{"Tampil Terus 🟢" if dur_mode=="full" else "Tampil Terus"}', callback_data="watermark_text_duration_mode_full"),
        InlineKeyboardButton(text=f'{"Batas Waktu 🟢" if dur_mode=="range" else "Batas Waktu"}',        callback_data="watermark_text_duration_mode_range"),
        InlineKeyboardButton(text=f'{"Kedip/Interval 🟢" if dur_mode=="interval" else "Kedip/Interval"}',  callback_data="watermark_text_duration_mode_interval"),
    ])
    if dur_mode == "range":
        KB.append([InlineKeyboardButton(text=f"Mulai: {dur.get('from','00:00:00')}", callback_data="watermark_text_duration_from"),
                   InlineKeyboardButton(text=f"Berhenti: {dur.get('to','00:00:00')}",   callback_data="watermark_text_duration_to")])
    elif dur_mode == "interval":
        KB.append([InlineKeyboardButton(text=f"Durasi Kedip Tiap: {dur.get('interval',30)} detik", callback_data="watermark_text_duration_interval")])
    KB.append([InlineKeyboardButton(text="↩️ Kembali ke Watermark", callback_data="watermark_settings")])
    
    msg = _menu_header("Watermark Teks") + "Kustomisasi penyematan Tulisan pada video Anda." + _menu_footer()
    try:
        await call.message.edit_text(msg, reply_markup=InlineKeyboardMarkup(inline_keyboard=KB))
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════════
#  MAIN CALLBACK HANDLER
# ═══════════════════════════════════════════════════════════════════════

@router.callback_query()
async def callback(call: CallbackQuery):
    txt     = call.data
    chat_id = call.message.chat.id
    user_id = call.from_user.id

    try:
        await ensure_user_data_structure(user_id)

        # ── Settings Navigation ──────────────────────────────────────
        if txt == "settings":
            msg = _menu_header("Pengaturan Bot Utama") + "Pilih Kategori Konfigurasi Mesin" + _menu_footer()
            await call.message.edit_text(
                msg,
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="👤 Profil",       callback_data="profile_main")],
                    [InlineKeyboardButton(text="🎬 Pengolahan Media",        callback_data="settings_media")],
                    [InlineKeyboardButton(text="🤖 Umum & Tampilan", callback_data="settings_bot")],
                    [InlineKeyboardButton(text="⭕ Tutup Jendela",                  callback_data="close_settings")],
                ])
            )

        elif txt == "settings_media":
            msg = _menu_header("Modul Pengolahan Media") + "Sesuaikan hasil kompresi video atau audio." + _menu_footer()
            await call.message.edit_text(
                msg,
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🎬 Pengaturan Video",    callback_data="video_settings"),  InlineKeyboardButton(text="🎧 Audio",  callback_data="audio_settings")],
                    [InlineKeyboardButton(text="🛺 Watermark",callback_data="watermark_settings"), InlineKeyboardButton(text="🚜 Konversi",callback_data="convert_settings")],
                    [InlineKeyboardButton(text="🍧 Merge",   callback_data="merge_settings"),  InlineKeyboardButton(text="⚙️ MUX",    callback_data="mux_settings")],
                    [InlineKeyboardButton(text="🎞️ Metadata", callback_data="metadata_settings")],
                    [InlineKeyboardButton(text="↩️ Kembali", callback_data="settings")],
                ])
            )

        elif txt == "settings_bot":
            msg = _menu_header("Modul Umum & Tampilan") + "Sesuaikan kinerja server dan tampilan Bot." + _menu_footer()
            await call.message.edit_text(
                msg,
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="#️⃣ Pengaturan Umum",              callback_data="general_settings")],
                    [InlineKeyboardButton(text="🖥️ Tampilan Progress", callback_data="progress_settings")],
                    [InlineKeyboardButton(text="✈️ Pustaka Telegram",            callback_data="telegram_settings")],
                    [InlineKeyboardButton(text="↩️ Kembali", callback_data="settings")],
                ])
            )

        elif txt == "close_settings":
            await call.message.delete()

        # ── Profile Management ───────────────────────────────────────
        elif txt.startswith("profile_"):
            parts        = txt.split("_", 2)
            action       = parts[1]
            profile_name = parts[2] if len(parts) > 2 else None
            user_data    = get_data().get(user_id, {})

            # 🛠 Fungsi Pembantu Untuk Refresh UI Kelola Profil Tanpa Pydantic Error 🛠
            async def _refresh_manage_menu():
                profiles = user_data.get("profiles", {})
                active   = user_data.get("active_profile", "Default")
                btns     = [[InlineKeyboardButton(text="✨ Reset Profil ke Bawaan (Default)", callback_data="profile_reset_default")]]
                for name in profiles:
                    if name == "Default":
                        continue
                    lbl = f"🟢 AKTIF: {name}" if name == active else f"📁 {name}"
                    btns.append([InlineKeyboardButton(text=lbl, callback_data=f"profile_load_{name}"),
                                  InlineKeyboardButton(text="🗑️ Hapus", callback_data=f"profile_delete_{name}")])
                btns.append([InlineKeyboardButton(text="↩️ Kembali", callback_data="profile_main")])
                
                msg = _menu_header("Kelola Profil") + f"Mode Aktif: **{active}**" + _menu_footer()
                try:
                    await call.message.edit_text(msg, reply_markup=InlineKeyboardMarkup(inline_keyboard=btns))
                except TelegramBadRequest:
                    pass

            if action == "main":
                active = user_data.get("active_profile", "Default")
                msg = _menu_header("Profil Pengaturan") + f"Mode Aktif: **{active}**\nBantu pergantian pengaturan ganda secara kilat." + _menu_footer()
                await call.message.edit_text(
                    msg,
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="💾 Simpan Profil", callback_data="profile_save")],
                        [InlineKeyboardButton(text="📂 Kelola Profil",          callback_data="profile_manage")],
                        [InlineKeyboardButton(text="🚀 Profil Kilat",            callback_data="profile_quick")],
                        [InlineKeyboardButton(text="↩️ Kembali",                callback_data="settings")],
                    ])
                )

            elif action == "save":
                resp = await get_text_data(chat_id, user_id, call, 120, "Ketikkan nama profil baru Anda:")
                if resp and 0 < len(resp.text) < 32:
                    safe_name = resp.text.replace("`", "").replace("*", "")
                    user_data.setdefault("profiles", {})[safe_name] = get_current_settings_copy(user_id)
                    await saveoptions(user_id, "profiles", user_data["profiles"], SAVE_TO_DATABASE)
                    await resp.reply(f"✅ Profil `{safe_name}` berhasil disimpan.")
                elif resp:
                    await resp.reply("❌ Nama tidak valid (Harus 1-31 karakter).")
                await call.message.delete()
                await call.message.answer("Aksi Selesai:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Buka Menu Profil", callback_data="profile_main")]]))

            elif action == "manage":
                await _refresh_manage_menu()

            elif action == "load" and profile_name:
                profiles = user_data.get("profiles", {})
                if profile_name in profiles:
                    await apply_settings_from_profile(user_id, profiles[profile_name])
                    await saveoptions(user_id, "active_profile", profile_name, SAVE_TO_DATABASE)
                    user_data["active_profile"] = profile_name
                    await call.answer(f"✅ Profil '{profile_name}' berhasil diterapkan.", show_alert=True)
                else:
                    await call.answer("❌ Profil tidak ditemukan di sistem.", show_alert=True)
                
                await _refresh_manage_menu()

            elif action == "delete" and profile_name:
                profiles = user_data.get("profiles", {})
                if profile_name in profiles and profile_name != "Default":
                    del profiles[profile_name]
                    if user_data.get("active_profile") == profile_name:
                        await apply_settings_from_profile(user_id, profiles.get("Default", {}))
                        await saveoptions(user_id, "active_profile", "Default", SAVE_TO_DATABASE)
                        user_data["active_profile"] = "Default"
                    await saveoptions(user_id, "profiles", profiles, SAVE_TO_DATABASE)
                    await call.answer(f"✅ Profil '{profile_name}' dihapus.", show_alert=True)
                else:
                    await call.answer("❌ Profil dasar tidak bisa dihapus.", show_alert=True)
                
                await _refresh_manage_menu()

            elif action == "reset" and profile_name == "default":
                defaults = _get_default_user_data()
                exclude  = {"profiles", "active_profile"}
                await apply_settings_from_profile(user_id, {k: v for k, v in defaults.items() if k not in exclude})
                await saveoptions(user_id, "active_profile", "Default", SAVE_TO_DATABASE)
                await call.answer("✅ Pengaturan dikembalikan ke Default.", show_alert=True)

            elif action == "quick":
                profile_type = parts[2] if len(parts) > 2 else None
                if not profile_type:
                    msg = _menu_header("Template Cepat") + "Atur CRF dan Preset seketika tanpa harus menyetel manual." + _menu_footer()
                    await call.message.edit_text(
                        msg,
                        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                            [InlineKeyboardButton(text="🏆 Kualitas Tinggi", callback_data="profile_quick_quality")],
                            [InlineKeyboardButton(text="⚡ Kompresi Ekstrem",    callback_data="profile_quick_size")],
                            [InlineKeyboardButton(text="⚖️ Seimbang",        callback_data="profile_quick_balance")],
                            [InlineKeyboardButton(text="↩️ Kembali",         callback_data="profile_main")],
                        ])
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
                    await call.answer(f"✅ Template otomatis '{profile_type}' diaktifkan.", show_alert=True)

        # ── Action Callbacks ─────────────────────────────────────────

        elif txt.startswith("send_log_"):
            process_id = txt.split("_", 2)[2]
            log_file   = await get_ffmpeg_log_file(process_id)
            if log_file and exists(log_file):
                from aiogram.types import FSInputFile
                await Telegram.AIOGRAM_BOT.send_document(chat_id, document=FSInputFile(log_file),
                    caption=f"📄 Berkas Log Kesalahan untuk proses `{process_id}`.")
                await call.message.edit_text("✅ Berkas Log telah berhasil terkirim.", reply_markup=None)
            else:
                await call.answer("❗ Sayang sekali, berkas Log tidak ditemukan.", show_alert=True)

        elif txt.startswith("resetdb"):
            val = _safe_eval_bool(txt.split("_", 1)[1])
            if val:
                ok = await resetdatabase(SAVE_TO_DATABASE)
                await call.answer(f"✔ Format Data {'Berhasil' if ok else 'Gagal Dijalankan'}", show_alert=True)
            else:
                await call.answer("Perintah Formatting Dibatalkan.", show_alert=True)

        elif txt.startswith("env_"):
            key  = txt.split("_", 1)[1]
            resp = await get_text_data(chat_id, user_id, call, 120, f"Kirimkan nilai sistem baru yang ingin ditimpa pada variabel: `{key}`")
            if resp:
                from bot_helper.Others.Helper_Functions import export_env_file, get_env_dict
                d = get_env_dict("./userdata/botconfig.env") or get_env_dict("config.env") or {}
                d[key] = resp.text
                export_env_file("./userdata/botconfig.env", d)
                await resp.reply(f"✅ Variabel `{key}` berhasil diperbarui. Mulai ulang bot (Restart) untuk menerapkan konfigurasi sistem.")

        elif txt.startswith("renew"):
            val = _safe_eval_bool(txt.split("_", 1)[1])
            if val:
                if exists(Config.DOWNLOAD_DIR):
                    await delete_all(Config.DOWNLOAD_DIR)
                    await call.answer(f"✔ Seluruh Berkas Sementara pada folder {Config.DOWNLOAD_DIR} Berhasil Dihancurkan", show_alert=True)
                else:
                    await call.answer("Server Bersih: Tidak ada sampah berkas sementara.", show_alert=True)
            else:
                await call.answer("Perintah Pembersihan Dibatalkan.", show_alert=True)

        # ── Settings Sub-Dispatchers ─────────────────────────────────
        elif txt.startswith("general"):    await general_callback(call, txt, user_id, chat_id)
        elif txt.startswith("telegram"):   await telegram_callback(call, txt, user_id, chat_id)
        elif txt.startswith("progress"):   await progress_callback(call, txt, user_id)
        elif txt.startswith("metadata"):   await metadata_callback(call, txt, user_id, chat_id)
        elif txt.startswith("video"):      await video_callback(call, txt, user_id, True, chat_id)
        elif txt.startswith("audio"):      await audio_callback(call, txt, user_id)
        elif txt.startswith("convert"):    await convert_callback(call, txt, user_id)
        elif txt.startswith("mux"):        await mux_callback(call, txt, user_id)
        elif txt.startswith("merge"):      await merge_callback(call, txt, user_id)
        elif txt.startswith("watermark"):  await watermark_callback(call, txt, user_id, chat_id)

        elif txt == "nik66bots":
            await call.answer("⚡ Trinity Architecture by Sahil/Khoirul ⚡", show_alert=True)

        elif txt == "change_video_queue_size":
            resp = await get_text_data(chat_id, user_id, call, 120, "Kirim Ukuran Batasan Buffer Memory Antrian FFMpeg (Contoh: `1M`, `512k`)")
            if resp:
                safe_val = str(resp.text).replace("`","").replace("*","").strip()
                await saveconfig(user_id, "video", "queue_size", safe_val, SAVE_TO_DATABASE)
                await video_callback(call, "video_settings", user_id, False, chat_id)

        elif txt == "custom_metedata":
            title = get_data().get(user_id, {}).get("metadata", {}).get("preset", {}).get("title", "(Belum diisi)")
            safe_title = str(title).replace("`","").replace("*","")
            await call.answer(f"🏷 Judul Metadata Saat Ini: {safe_title}", show_alert=True)

    except TelegramBadRequest:
        pass
    except Exception as e:
        LOGGER.exception(f"Callback error [{txt}]: {e}")
