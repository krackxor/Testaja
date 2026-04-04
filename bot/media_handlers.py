"""
╔══════════════════════════════════════════════════════════════════════╗
║       bot_helper/Handlers/media_handlers.py — v3.1                   ║
║       Media Processing Command Handlers (Aiogram 3.x)                ║
╠══════════════════════════════════════════════════════════════════════╣
║  CHANGELOG dari versi lama:                                          ║
║  [FIX HIGH] Implementasi CMD_SUFFIX pada semua Command filter        ║
║  [NEW] Migrasi total decorator Telethon ke Aiogram Router            ║
║  [FIX] `event` diubah menjadi `message` (Aiogram Message object)     ║
║  [FIX] `event.message.sender.id` → `message.from_user.id`            ║
║  [FIX] `event.message.file` → `message.document` atau `message.video`║
║  [FIX] `download_media()` → `Telegram.AIOGRAM_BOT.download()`        ║
║  [FIX] Mengambil teks dengan `message.text` bukan `message.message`  ║
║  [FIX] Menutup celah Markdown Parser Crash pada variabel dinamis     ║
╚══════════════════════════════════════════════════════════════════════╝
"""

# ── Standard Library ──────────────────────────────────────────────────
from asyncio import create_task

# ── Aiogram ───────────────────────────────────────────────────────────
from aiogram import Router, F
from aiogram.types import Message
from aiogram.filters import Command

# ── Internal ──────────────────────────────────────────────────────────
from bot_helper.Database.User_Data import get_data, new_user
from bot_helper.Others.Names import Names
from bot_helper.Process.Process_Status import ProcessStatus
from bot_helper.Telegram.Telegram_Client import Telegram
from config.config import Config

from .shared import (
    CMD_SUFFIX, LOGGER, SAVE_TO_DATABASE,
    ask_media_OR_url, ask_text_event, ask_url, build_task,
    check_file, create_direc, finalize_multi_tasks,
    get_custom_name, get_link, get_thumbnail, get_url_from_message,
    get_username, safe_reply, submit_task, update_status_message,
    user_auth_checker, vip_check,
)

owner_id = Config.OWNER_ID

# Inisialisasi Router Aiogram untuk mendaftarkan command FFMPEG
router = Router()

# ═══════════════════════════════════════════════════════════════════════
#  MULTI-TASK SYSTEM
# ═══════════════════════════════════════════════════════════════════════

async def hardmux_multi_task(multi_ps, message: Message, chat_id, user_id, process_command) -> bool:
    new_msg = await ask_media_OR_url(
        message, chat_id, user_id,
        [process_command, "stop"], "Kirim Berkas Subtitle SRT", 120,
        False, True, allow_magnet=False, allow_url=False,
    )
    if not new_msg or new_msg in ["cancelled", "stopped"]:
        return False
        
    if not new_msg.document:
        await safe_reply(message, "❗ Hanya Berkas Dokumen Telegram yang Didukung")
        return False
        
    mime = str(new_msg.document.mime_type)
    if mime.startswith("video/") or mime.startswith("image/"):
        await safe_reply(message, "❌ Saya Membutuhkan Berkas Subtitle (SRT/ASS).")
        return False
        
    if new_msg.document.file_size >= 512_000:
        await safe_reply(message, "❌ Ukuran Subtitle Lebih dari 500KB")
        return False
        
    sub_name = new_msg.document.file_name
    create_direc(f"{multi_ps.dir}/subtitles")
    sub_dw_loc = check_file(f"{multi_ps.dir}/subtitles", sub_name)
    
    # Download file menggunakan Aiogram Bot
    await Telegram.AIOGRAM_BOT.download(new_msg.document, destination=sub_dw_loc)
    multi_ps.append_subtitles(sub_dw_loc)
    return True


async def append_multi_task(process_status, process_name, cmd, message: Message) -> bool:
    multi_ps = ProcessStatus(
        process_status.user_id, process_status.chat_id,
        process_status.user_name, process_status.user_first_name,
        message, process_name, process_status.file_name,
    )
    ok = True
    if process_name == Names.hardmux:
        ok = await hardmux_multi_task(multi_ps, message, process_status.chat_id,
                                       process_status.user_id, cmd)
    elif process_name == Names.watermark:
        ok = await ask_watermark_local(message, process_status.chat_id,
                                        process_status.user_id, cmd)
    if not ok:
        del multi_ps
        return False
    process_status.append_multi_tasks(multi_ps)
    return True


async def ask_watermark_local(message: Message, chat_id, user_id, cmd) -> bool:
    from .shared import ask_watermark
    return await ask_watermark(message, chat_id, user_id, cmd, True, all_handle=True)


async def multi_tasks(process_status, cmd) -> bool:
    """Interaktif multi-task builder."""
    ffmpeg_funcs = [Names.compress, Names.watermark, Names.convert, Names.hardmux]
    p_text       = "\n".join(f"`{p}`" for p in ffmpeg_funcs)
    q            = 1
    p_cmd        = cmd
    valid_list   = ffmpeg_funcs + ["stop", "cancel"]
    m_result     = True
    chat_message = process_status.event  # Di Aiogram ini adalah object Message

    while True:
        text = (
            f"Apa yang Harus Dilakukan dengan Hasil **{p_cmd.replace('/', '').upper()}**\n"
            f"🔶 Tugas Multi Ke-{q}\n\n{p_text}\n\n"
            "🔷 Kirim `stop` untuk Proses | `cancel` untuk Batalkan"
        )
        result = await ask_text_list_local(process_status, chat_message, text, valid_list)
        if not result:
            m_result = False
            break
            
        msg_text = result.text.lower()
        if msg_text == "stop":
            break
        if msg_text == "cancel":
            await safe_reply(result, "✅ Tugas Dibatalkan")
            m_result = False
            break
            
        ok = await append_multi_task(process_status, msg_text, cmd, result)
        if ok:
            p_cmd        = msg_text
            chat_message = result
            q           += 1

    return m_result


async def ask_text_list_local(ps, message: Message, text, include_list):
    from .shared import ask_text_list
    return await ask_text_list(ps.chat_id, ps.user_id, message, 120, text, include_list)


def _apply_multi_tasks(process_status, task, user_id) -> bool:
    finalize_multi_tasks(process_status)
    return True


# ═══════════════════════════════════════════════════════════════════════
#  GENERIC VIDEO HANDLER FACTORY
# ═══════════════════════════════════════════════════════════════════════

async def _generic_video_handler(message: Message, process_name: str, cmd_name: str):
    if not await vip_check(message):
        return
    user_id = message.from_user.id
    chat_id = message.chat.id
    if user_id not in get_data():
        await new_user(user_id, SAVE_TO_DATABASE)

    link, custom_file_name = await get_link(message)
    if link == "invalid":
        await safe_reply(message, "❗ Tautan tidak valid")
        return
        
    if not link:
        ne = await ask_media_OR_url(
            message, chat_id, user_id,
            [f"/{cmd_name}{CMD_SUFFIX}", "stop"], "Kirim Video atau URL", 120, "video/", True,
        )
        if ne and ne not in ["cancelled", "stopped"]:
            link = await get_url_from_message(ne)
        else:
            return

    ps = ProcessStatus(user_id, chat_id, get_username(message),
                       message.from_user.first_name, message, process_name, custom_file_name)
    await get_thumbnail(ps, [f"/{cmd_name}{CMD_SUFFIX}", "pass"], 120)
    task = build_task(ps, link)
    await submit_task(task)
    await update_status_message(message)


async def _generic_video_with_multitask(message: Message, process_name: str, cmd_name: str):
    if not await vip_check(message):
        return
    user_id = message.from_user.id
    chat_id = message.chat.id
    if user_id not in get_data():
        await new_user(user_id, SAVE_TO_DATABASE)

    link, custom_file_name = await get_link(message)
    if link == "invalid":
        await safe_reply(message, "❗ Tautan tidak valid")
        return
        
    if not link:
        ne = await ask_media_OR_url(
            message, chat_id, user_id,
            [f"/{cmd_name}{CMD_SUFFIX}", "stop"], "Kirim Video atau URL", 120, "video/", True,
        )
        if ne and ne not in ["cancelled", "stopped"]:
            link = await get_url_from_message(ne)
        else:
            return

    ps   = ProcessStatus(user_id, chat_id, get_username(message),
                         message.from_user.first_name, message, process_name, custom_file_name)
    cmd_ = f"/{cmd_name}{CMD_SUFFIX}"
    await get_thumbnail(ps, [cmd_, "pass"], 120)
    task = build_task(ps, link)

    if get_data().get(user_id, {}).get("multi_tasks"):
        ok = await multi_tasks(ps, cmd_)
        if not ok:
            del ps
            return
        finalize_multi_tasks(ps)

    await submit_task(task)
    await update_status_message(message)


# ═══════════════════════════════════════════════════════════════════════
#  COMPRESS
# ═══════════════════════════════════════════════════════════════════════

@router.message(Command(f"compress{CMD_SUFFIX}"))
async def _compress_video(message: Message):
    await _generic_video_with_multitask(message, Names.compress, "compress")


# ═══════════════════════════════════════════════════════════════════════
#  WATERMARK
# ═══════════════════════════════════════════════════════════════════════

@router.message(Command(f"watermark{CMD_SUFFIX}"))
async def _add_watermark(message: Message):
    if not await vip_check(message):
        return
    user_id = message.from_user.id
    chat_id = message.chat.id
    if user_id not in get_data():
        await new_user(user_id, SAVE_TO_DATABASE)

    from .shared import ask_watermark
    if not await ask_watermark(message, chat_id, user_id, "watermark", True):
        await safe_reply(message, "❗ Gagal Mendapatkan Watermark.")
        return
    await _generic_video_with_multitask(message, Names.watermark, "watermark")


# ═══════════════════════════════════════════════════════════════════════
#  MERGE
# ═══════════════════════════════════════════════════════════════════════

@router.message(Command(f"merge{CMD_SUFFIX}"))
async def _merge_videos(message: Message):
    if not await vip_check(message):
        return
    user_id = message.from_user.id
    chat_id = message.chat.id
    if user_id not in get_data():
        await new_user(user_id, SAVE_TO_DATABASE)

    custom_file_name = await get_custom_name(message)
    ps   = ProcessStatus(user_id, chat_id, get_username(message),
                         message.from_user.first_name, message, Names.merge, custom_file_name)
    task = {"process_status": ps, "functions": []}
    idx  = 1

    while True:
        ne = await ask_media_OR_url(
            message, chat_id, user_id,
            [f"/merge{CMD_SUFFIX}", "stop", "cancel"], f"Kirim Video/URL No {idx}", 120,
            "video/", False,
            message_hint="🔷 `stop` untuk Proses | `cancel` untuk Batalkan",
            allow_command=True,
        )
        if ne in [None, "cancelled"]:
            del ps
            return
        if ne == "stopped":
            break
        if ne == "pass":
            continue
            
        link = await get_url_from_message(ne)
        from bot_helper.Aria2.Aria2_Engine import Aria2
        if isinstance(link, str):
            task["functions"].append(["Aria", Aria2.add_aria2c_download,
                                      [link, ps, False, False, False, False]])
        else:
            task["functions"].append(["TG", [link]])
        idx += 1

    if len(task["functions"]) < 2:
        del ps
        await safe_reply(message, "❗ Minimal 2 Berkas Diperlukan untuk Menggabungkan")
        return

    await get_thumbnail(ps, [f"/merge{CMD_SUFFIX}", "pass"], 120)

    if get_data().get(user_id, {}).get("multi_tasks"):
        ok = await multi_tasks(ps, f"/merge{CMD_SUFFIX}")
        if not ok:
            del ps
            return
        finalize_multi_tasks(ps)

    await submit_task(task)
    await update_status_message(message)


# ═══════════════════════════════════════════════════════════════════════
#  SOFTMUX / SOFTREMUX
# ═══════════════════════════════════════════════════════════════════════

async def _subtitle_mux_handler(message: Message, process_name: str, cmd_name: str):
    if not await vip_check(message):
        return
    user_id = message.from_user.id
    chat_id = message.chat.id
    if user_id not in get_data():
        await new_user(user_id, SAVE_TO_DATABASE)

    link, custom_file_name = await get_link(message)
    if link == "invalid":
        await safe_reply(message, "❗ Tautan tidak valid")
        return
    if not link:
        ne = await ask_media_OR_url(
            message, chat_id, user_id,
            [f"/{cmd_name}{CMD_SUFFIX}", "stop"], "Kirim Video atau URL", 120, "video/", True,
        )
        if ne and ne not in ["cancelled", "stopped"]:
            link = await get_url_from_message(ne)
        else:
            return

    ps     = ProcessStatus(user_id, chat_id, get_username(message),
                           message.from_user.first_name, message, process_name, custom_file_name)
    idx    = 1
    cancel = False

    while True:
        ne = await ask_media_OR_url(
            message, chat_id, user_id,
            [f"/{cmd_name}{CMD_SUFFIX}", "stop", "cancel"], f"Kirim Subtitle SRT No {idx}",
            120, False, False,
            message_hint=f"🔷 `stop` Proses | `cancel` Batalkan",
            allow_command=True, allow_magnet=False, allow_url=False, stop_on_url=False,
        )
        if ne in [None, "pass"]:
            cancel = True
            break
        if ne == "cancelled":
            cancel = True
            break
        if ne == "stopped":
            break
            
        if ne.document:
            mime = str(ne.document.mime_type)
            if mime.startswith("video/") or mime.startswith("image/"):
                await safe_reply(message, "❌ Saya Membutuhkan Berkas Subtitle")
                continue
            if ne.document.file_size >= 512_000:
                await safe_reply(message, "❌ Ukuran Subtitle Lebih dari 500KB")
                continue
                
            sub_name   = ne.document.file_name
            create_direc(f"{ps.dir}/subtitles")
            sub_dw_loc = check_file(f"{ps.dir}/subtitles", sub_name)
            
            # Download file menggunakan Aiogram Bot
            await Telegram.AIOGRAM_BOT.download(ne.document, destination=sub_dw_loc)
            ps.append_subtitles(sub_dw_loc)
            idx += 1
        else:
            await safe_reply(message, "❗ Hanya Berkas Telegram yang Didukung")

    if cancel:
        del ps
        return
    if not ps.subtitles:
        del ps
        await safe_reply(message, f"❗ Minimal 1 Subtitle Diperlukan untuk {process_name}")
        return

    await get_thumbnail(ps, [f"/{cmd_name}{CMD_SUFFIX}", "pass"], 120)
    task = build_task(ps, link)

    if get_data().get(user_id, {}).get("multi_tasks"):
        ok = await multi_tasks(ps, f"/{cmd_name}{CMD_SUFFIX}")
        if not ok:
            del ps
            return
        finalize_multi_tasks(ps)

    await submit_task(task)
    await update_status_message(message)


@router.message(Command(f"softmux{CMD_SUFFIX}"))
async def _softmux(message: Message):
    await _subtitle_mux_handler(message, Names.softmux, "softmux")


@router.message(Command(f"softremux{CMD_SUFFIX}"))
async def _softremux(message: Message):
    await _subtitle_mux_handler(message, Names.softremux, "softremux")


# ═══════════════════════════════════════════════════════════════════════
#  CONVERT
# ═══════════════════════════════════════════════════════════════════════

@router.message(Command(f"convert{CMD_SUFFIX}"))
async def _convert_video(message: Message):
    await _generic_video_handler(message, Names.convert, "convert")


# ═══════════════════════════════════════════════════════════════════════
#  HARDMUX
# ═══════════════════════════════════════════════════════════════════════

@router.message(Command(f"hardmux{CMD_SUFFIX}"))
async def _hardmux_subtitle(message: Message):
    if not await vip_check(message):
        return
    user_id = message.from_user.id
    chat_id = message.chat.id
    if user_id not in get_data():
        await new_user(user_id, SAVE_TO_DATABASE)

    link, custom_file_name = await get_link(message)
    if link == "invalid":
        await safe_reply(message, "❗ Tautan tidak valid")
        return
    if not link:
        ne = await ask_media_OR_url(
            message, chat_id, user_id,
            [f"/hardmux{CMD_SUFFIX}", "stop"], "Kirim Video atau URL", 120, "video/", True,
        )
        if ne and ne not in ["cancelled", "stopped"]:
            link = await get_url_from_message(ne)
        else:
            return

    ps = ProcessStatus(user_id, chat_id, get_username(message),
                       message.from_user.first_name, message, Names.hardmux, custom_file_name)

    ne = await ask_media_OR_url(
        message, chat_id, user_id,
        [f"/hardmux{CMD_SUFFIX}", "stop"], "Kirim Berkas Subtitle SRT", 120,
        False, True, allow_magnet=False, allow_url=False,
    )
    if not ne or ne in ["cancelled", "stopped"]:
        del ps
        return

    if not ne.document:
        await safe_reply(message, "❗ Hanya Berkas Subtitle/Dokumen Telegram yang Didukung")
        del ps
        return

    mime = str(ne.document.mime_type)
    if mime.startswith("video/") or mime.startswith("image/"):
        await safe_reply(message, "❌ Saya Membutuhkan Berkas Subtitle.")
        del ps
        return
    if ne.document.file_size >= 512_000:
        await safe_reply(message, "❌ Ukuran Subtitle Lebih dari 500KB")
        del ps
        return

    sub_name   = ne.document.file_name
    create_direc(f"{ps.dir}/subtitles")
    sub_dw_loc = check_file(f"{ps.dir}/subtitles", sub_name)
    
    # Menggunakan Aiogram untuk Download
    await Telegram.AIOGRAM_BOT.download(ne.document, destination=sub_dw_loc)
    ps.append_subtitles(sub_dw_loc)

    await get_thumbnail(ps, [f"/hardmux{CMD_SUFFIX}", "pass"], 120)
    task = build_task(ps, link)

    if get_data().get(user_id, {}).get("multi_tasks"):
        ok = await multi_tasks(ps, f"/hardmux{CMD_SUFFIX}")
        if not ok:
            del ps
            return
        finalize_multi_tasks(ps)

    await submit_task(task)
    await update_status_message(message)


# ═══════════════════════════════════════════════════════════════════════
#  GENSAMPLE / GENSS
# ═══════════════════════════════════════════════════════════════════════

@router.message(Command(f"gensample{CMD_SUFFIX}"))
async def _gen_video_sample(message: Message):
    await _generic_video_handler(message, Names.gensample, "gensample")


@router.message(Command(f"genss{CMD_SUFFIX}"))
async def _gen_screenshots(message: Message):
    await _generic_video_handler(message, Names.genss, "genss")


# ═══════════════════════════════════════════════════════════════════════
#  CHANGE METADATA
# ═══════════════════════════════════════════════════════════════════════

@router.message(Command(f"changemetadata{CMD_SUFFIX}"))
async def _change_metadata(message: Message):
    if not await vip_check(message):
        return
    user_id = message.from_user.id
    chat_id = message.chat.id
    cmd     = f"/changemetadata{CMD_SUFFIX}"
    if user_id not in get_data():
        await new_user(user_id, SAVE_TO_DATABASE)

    link, custom_file_name = await get_link(message)
    if link == "invalid":
        await safe_reply(message, "❗ Tautan tidak valid")
        return
    if not link:
        ne = await ask_media_OR_url(message, chat_id, user_id, [cmd, "stop"],
                                     "Kirim Video atau URL", 120, "video/", True)
        if ne and ne not in ["cancelled", "stopped"]:
            link = await get_url_from_message(ne)
        else:
            return

    me = await ask_text_event(
        chat_id, user_id, message, 120, "Kirim MetaData",
        message_hint=(
            "Format:\n`a:0-BahasaAudio-JudulAudio`\n`s:0-BahasaSub-JudulSub`\n\n"
            "Contoh: `a:1-eng-EncoderBot`"
        ),
    )
    if not me:
        return

    custom_metadata = []
    # Membaca isi teks pada Aiogram Message
    for m in str(me.text).split("\n"):
        mdata = str(m).strip().split("-")
        try:
            sindex = str(mdata[0]).strip().lower()
            mlang  = str(mdata[1]).lower()
            mtitle = str(mdata[2])
            custom_metadata.append([
                f"-metadata:s:{sindex}", f"language={mlang}",
                f"-metadata:s:{sindex}", f"title={mtitle}",
            ])
        except (IndexError, Exception) as e:
            await safe_reply(me, f"❗ Metadata Tidak Valid: `{e}`")
            return

    ps = ProcessStatus(user_id, chat_id, get_username(message),
                       message.from_user.first_name, message, Names.changeMetadata,
                       custom_file_name, custom_metadata=custom_metadata)
    await get_thumbnail(ps, [cmd, "pass"], 120)
    task = build_task(ps, link)
    await submit_task(task)
    await update_status_message(message)


# ═══════════════════════════════════════════════════════════════════════
#  CHANGE INDEX
# ═══════════════════════════════════════════════════════════════════════

@router.message(Command(f"changeindex{CMD_SUFFIX}"))
async def _change_index(message: Message):
    if not await vip_check(message):
        return
    user_id = message.from_user.id
    chat_id = message.chat.id
    cmd     = f"/changeindex{CMD_SUFFIX}"
    if user_id not in get_data():
        await new_user(user_id, SAVE_TO_DATABASE)

    link, custom_file_name = await get_link(message)
    if link == "invalid":
        await safe_reply(message, "❗ Tautan tidak valid")
        return
    if not link:
        ne = await ask_media_OR_url(message, chat_id, user_id, [cmd, "stop"],
                                     "Kirim Video atau URL", 120, "video/", True)
        if ne and ne not in ["cancelled", "stopped"]:
            link = await get_url_from_message(ne)
        else:
            return

    ie = await ask_text_event(
        chat_id, user_id, message, 120, "Kirim Indeks",
        message_hint=(
            "`a` Audio | `s` Subtitle\n"
            "Format: `a-3-1-2` (urutan 3,1,2)\n"
            "Contoh: `s-2-1`"
        ),
    )
    if not ie:
        return

    custom_index = []
    # Aiogram text
    for m in str(ie.text).split("\n"):
        mdata = str(m).strip().split("-")
        try:
            stream = str(mdata[0]).strip().lower()
            mdata.pop(0)
            for s in mdata:
                si = int(s.strip()) - 1
                custom_index += ["-map", f"0:{stream}:{si}"]
            custom_index += [f"-disposition:{stream}:0", "default"]
        except (ValueError, IndexError, Exception) as e:
            await safe_reply(ie, f"❗ Indeks Tidak Valid: `{e}`")
            return

    ps = ProcessStatus(user_id, chat_id, get_username(message),
                       message.from_user.first_name, message, Names.changeindex,
                       custom_file_name, custom_index=custom_index)
    await get_thumbnail(ps, [cmd, "pass"], 120)
    task = build_task(ps, link)
    await submit_task(task)
    await update_status_message(message)


# ═══════════════════════════════════════════════════════════════════════
#  LEECH / MIRROR
# ═══════════════════════════════════════════════════════════════════════

async def _leech_mirror_handler(message: Message, process_name: str, cmd_name: str):
    if not await vip_check(message):
        return
    user_id = message.from_user.id
    chat_id = message.chat.id
    if user_id not in get_data():
        await new_user(user_id, SAVE_TO_DATABASE)

    link, custom_file_name = await get_link(message)
    if link == "invalid":
        await safe_reply(message, "❗ Tautan tidak valid")
        return
    if not link:
        ne = await ask_url(message, chat_id, user_id, [f"/{cmd_name}{CMD_SUFFIX}", "stop"],
                            "Kirim Tautan", 120, True)
        if ne and ne not in ["cancelled", "stopped"]:
            link = await get_url_from_message(ne)
        else:
            return

    ps = ProcessStatus(user_id, chat_id, get_username(message),
                       message.from_user.first_name, message, process_name, custom_file_name)
    await get_thumbnail(ps, [f"/{cmd_name}{CMD_SUFFIX}", "pass"], 120)
    task = build_task(ps, link)
    await submit_task(task)
    await update_status_message(message)


@router.message(Command(f"leech{CMD_SUFFIX}"))
async def _leech_file(message: Message):
    await _leech_mirror_handler(message, Names.leech, "leech")


@router.message(Command(f"mirror{CMD_SUFFIX}"))
async def _mirror_file(message: Message):
    await _leech_mirror_handler(message, Names.mirror, "mirror")


# ═══════════════════════════════════════════════════════════════════════
#  STATUS
# ═══════════════════════════════════════════════════════════════════════

@router.message(Command(f"status{CMD_SUFFIX}"))
async def _status(message: Message):
    # Langsung panggil user_auth_checker di dalam fungsi
    if not await user_auth_checker(message):
        return
        
    user_id = message.from_user.id
    if user_id not in get_data():
        await new_user(user_id, SAVE_TO_DATABASE)
    await update_status_message(message)
