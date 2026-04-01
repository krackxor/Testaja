"""
╔══════════════════════════════════════════════════════════════════════╗
║       bot_helper/Handlers/media_handlers.py — v3.1                  ║
║       Media Processing Command Handlers (FFmpeg)                    ║
╠══════════════════════════════════════════════════════════════════════╣
║  Commands: /compress /watermark /merge /softmux /softremux          ║
║            /convert /hardmux /gensample /genss /changemetadata      ║
║            /changeindex /leech /mirror                              ║
╚══════════════════════════════════════════════════════════════════════╝
"""

# ── Standard Library ──────────────────────────────────────────────────
from asyncio import create_task

# ── Third Party ───────────────────────────────────────────────────────
from telethon import events

# ── Internal ──────────────────────────────────────────────────────────
from bot_helper.Database.User_Data import get_data, new_user
from bot_helper.Others.Names import Names
from bot_helper.Process.Process_Status import ProcessStatus
from bot_helper.Telegram.Telegram_Client import Telegram
from config.config import Config

from .shared import (
    CMD_SUFFIX, LOGGER, SAVE_TO_DATABASE, TELETHON_CLIENT,
    ask_media_OR_url, ask_text_event, ask_url, build_task,
    check_file, command, create_direc, finalize_multi_tasks,
    get_custom_name, get_link, get_thumbnail, get_url_from_message,
    get_username, safe_reply, submit_task, update_status_message,
    user_auth_checker, vip_check,
)

owner_id = Config.OWNER_ID


# ═══════════════════════════════════════════════════════════════════════
#  MULTI-TASK SYSTEM
# ═══════════════════════════════════════════════════════════════════════

async def hardmux_multi_task(multi_ps, event, chat_id, user_id, process_command) -> bool:
    new_event = await ask_media_OR_url(
        event, chat_id, user_id,
        [process_command, "stop"], "Kirim Berkas Subtitle SRT", 120,
        False, True, allow_magnet=False, allow_url=False,
    )
    if not new_event or new_event in ["cancelled", "stopped"]:
        return False
    if not new_event.message.file:
        await safe_reply(event, "❗ Hanya Berkas Telegram yang Didukung")
        return False
    mime = str(new_event.message.file.mime_type)
    if mime.startswith("video/") or mime.startswith("image/"):
        await safe_reply(event, "❌ Saya Membutuhkan Berkas Subtitle.")
        return False
    if new_event.message.file.size >= 512_000:
        await safe_reply(event, "❌ Ukuran Subtitle Lebih dari 500KB")
        return False
    sub_name = new_event.message.file.name
    create_direc(f"{multi_ps.dir}/subtitles")
    sub_dw_loc = check_file(f"{multi_ps.dir}/subtitles", sub_name)
    sub_path   = await new_event.download_media(file=sub_dw_loc)
    multi_ps.append_subtitles(sub_path)
    return True


async def append_multi_task(process_status, process_name, cmd, event) -> bool:
    multi_ps = ProcessStatus(
        process_status.user_id, process_status.chat_id,
        process_status.user_name, process_status.user_first_name,
        event, process_name, process_status.file_name,
    )
    ok = True
    if process_name == Names.hardmux:
        ok = await hardmux_multi_task(multi_ps, event, process_status.chat_id,
                                       process_status.user_id, cmd)
    elif process_name == Names.watermark:
        ok = await ask_watermark_local(event, process_status.chat_id,
                                        process_status.user_id, cmd)
    if not ok:
        del multi_ps
        return False
    process_status.append_multi_tasks(multi_ps)
    return True


async def ask_watermark_local(event, chat_id, user_id, cmd) -> bool:
    from .shared import ask_watermark
    return await ask_watermark(event, chat_id, user_id, cmd, True, all_handle=True)


async def multi_tasks(process_status, cmd) -> bool:
    """Interaktif multi-task builder."""
    ffmpeg_funcs = [Names.compress, Names.watermark, Names.convert, Names.hardmux]
    p_text       = "\n".join(f"`{p}`" for p in ffmpeg_funcs)
    q            = 1
    p_cmd        = cmd
    valid_list   = ffmpeg_funcs + ["stop", "cancel"]
    m_result     = True
    chat_event   = process_status.event

    while True:
        text = (
            f"Apa yang Harus Dilakukan dengan Hasil **{p_cmd.replace('/', '').upper()}**\n"
            f"🔶 Tugas Multi Ke-{q}\n\n{p_text}\n\n"
            "🔷 Kirim `stop` untuk Proses | `cancel` untuk Batalkan"
        )
        result = await ask_text_list_local(process_status, chat_event, text, valid_list)
        if not result:
            m_result = False
            break
        msg = result.message.message
        if msg == "stop":
            break
        if msg == "cancel":
            await safe_reply(result, "✅ Tugas Dibatalkan")
            m_result = False
            break
        ok = await append_multi_task(process_status, msg, cmd, result)
        if ok:
            p_cmd      = msg
            chat_event = result
            q         += 1

    return m_result


async def ask_text_list_local(ps, event, message, include_list):
    from .shared import ask_text_list
    return await ask_text_list(ps.chat_id, ps.user_id, event, 120, message, include_list)


def _apply_multi_tasks(process_status, task, user_id) -> bool:
    """
    Jalankan multi-tasks flow jika aktif.
    Return True jika berhasil, False jika dibatalkan.
    """
    # Dipanggil setelah multi_tasks() selesai
    finalize_multi_tasks(process_status)
    return True


# ═══════════════════════════════════════════════════════════════════════
#  GENERIC VIDEO HANDLER FACTORY
# ═══════════════════════════════════════════════════════════════════════

async def _generic_video_handler(event, process_name: str, cmd_name: str):
    """
    Template untuk handler video sederhana (compress, convert, gensample, genss, dll).
    Menghindari duplikasi kode di setiap handler.
    """
    if not await vip_check(event):
        return
    user_id = event.message.sender.id
    chat_id = event.message.chat.id
    if user_id not in get_data():
        await new_user(user_id, SAVE_TO_DATABASE)

    link, custom_file_name = await get_link(event)
    if link == "invalid":
        await safe_reply(event, "❗ Tautan tidak valid")
        return
    if not link:
        ne = await ask_media_OR_url(
            event, chat_id, user_id,
            [f"/{cmd_name}{CMD_SUFFIX}", "stop"], "Kirim Video atau URL", 120, "video/", True,
        )
        if ne and ne not in ["cancelled", "stopped"]:
            link = await get_url_from_message(ne)
        else:
            return

    ps = ProcessStatus(user_id, chat_id, get_username(event),
                       event.message.sender.first_name, event, process_name, custom_file_name)
    await get_thumbnail(ps, [f"/{cmd_name}{CMD_SUFFIX}", "pass"], 120)
    task = build_task(ps, link)
    await submit_task(task)
    await update_status_message(event)


async def _generic_video_with_multitask(event, process_name: str, cmd_name: str):
    """Template untuk handler yang mendukung multi-task (compress, watermark, merge, dll)."""
    if not await vip_check(event):
        return
    user_id = event.message.sender.id
    chat_id = event.message.chat.id
    if user_id not in get_data():
        await new_user(user_id, SAVE_TO_DATABASE)

    link, custom_file_name = await get_link(event)
    if link == "invalid":
        await safe_reply(event, "❗ Tautan tidak valid")
        return
    if not link:
        ne = await ask_media_OR_url(
            event, chat_id, user_id,
            [f"/{cmd_name}{CMD_SUFFIX}", "stop"], "Kirim Video atau URL", 120, "video/", True,
        )
        if ne and ne not in ["cancelled", "stopped"]:
            link = await get_url_from_message(ne)
        else:
            return

    ps   = ProcessStatus(user_id, chat_id, get_username(event),
                         event.message.sender.first_name, event, process_name, custom_file_name)
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
    await update_status_message(event)


# ═══════════════════════════════════════════════════════════════════════
#  COMPRESS
# ═══════════════════════════════════════════════════════════════════════

@TELETHON_CLIENT.on(events.NewMessage(incoming=True, pattern=command("compress")))
async def _compress_video(event):
    await _generic_video_with_multitask(event, Names.compress, "compress")


# ═══════════════════════════════════════════════════════════════════════
#  WATERMARK
# ═══════════════════════════════════════════════════════════════════════

@TELETHON_CLIENT.on(events.NewMessage(incoming=True, pattern=command("watermark")))
async def _add_watermark(event):
    if not await vip_check(event):
        return
    user_id = event.message.sender.id
    chat_id = event.message.chat.id
    if user_id not in get_data():
        await new_user(user_id, SAVE_TO_DATABASE)

    from .shared import ask_watermark
    if not await ask_watermark(event, chat_id, user_id, "watermark", True):
        await safe_reply(event, "❗ Gagal Mendapatkan Watermark.")
        return
    await _generic_video_with_multitask(event, Names.watermark, "watermark")


# ═══════════════════════════════════════════════════════════════════════
#  MERGE
# ═══════════════════════════════════════════════════════════════════════

@TELETHON_CLIENT.on(events.NewMessage(incoming=True, pattern=command("merge")))
async def _merge_videos(event):
    if not await vip_check(event):
        return
    user_id = event.message.sender.id
    chat_id = event.message.chat.id
    if user_id not in get_data():
        await new_user(user_id, SAVE_TO_DATABASE)

    custom_file_name = await get_custom_name(event)
    ps   = ProcessStatus(user_id, chat_id, get_username(event),
                         event.message.sender.first_name, event, Names.merge, custom_file_name)
    task = {"process_status": ps, "functions": []}
    idx  = 1

    while True:
        ne = await ask_media_OR_url(
            event, chat_id, user_id,
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
        await safe_reply(event, "❗ Minimal 2 Berkas Diperlukan untuk Menggabungkan")
        return

    await get_thumbnail(ps, [f"/merge{CMD_SUFFIX}", "pass"], 120)

    if get_data().get(user_id, {}).get("multi_tasks"):
        ok = await multi_tasks(ps, f"/merge{CMD_SUFFIX}")
        if not ok:
            del ps
            return
        finalize_multi_tasks(ps)

    await submit_task(task)
    await update_status_message(event)


# ═══════════════════════════════════════════════════════════════════════
#  SOFTMUX / SOFTREMUX
# ═══════════════════════════════════════════════════════════════════════

async def _subtitle_mux_handler(event, process_name: str, cmd_name: str):
    """Template untuk SoftMux dan SoftReMux."""
    if not await vip_check(event):
        return
    user_id = event.message.sender.id
    chat_id = event.message.chat.id
    if user_id not in get_data():
        await new_user(user_id, SAVE_TO_DATABASE)

    link, custom_file_name = await get_link(event)
    if link == "invalid":
        await safe_reply(event, "❗ Tautan tidak valid")
        return
    if not link:
        ne = await ask_media_OR_url(
            event, chat_id, user_id,
            [f"/{cmd_name}{CMD_SUFFIX}", "stop"], "Kirim Video atau URL", 120, "video/", True,
        )
        if ne and ne not in ["cancelled", "stopped"]:
            link = await get_url_from_message(ne)
        else:
            return

    ps     = ProcessStatus(user_id, chat_id, get_username(event),
                           event.message.sender.first_name, event, process_name, custom_file_name)
    idx    = 1
    cancel = False

    while True:
        ne = await ask_media_OR_url(
            event, chat_id, user_id,
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
        if ne.message.file:
            mime = str(ne.message.file.mime_type)
            if mime.startswith("video/") or mime.startswith("image/"):
                await safe_reply(event, "❌ Saya Membutuhkan Berkas Subtitle")
                continue
            if ne.message.file.size >= 512_000:
                await safe_reply(event, "❌ Ukuran Subtitle Lebih dari 500KB")
                continue
            sub_name   = ne.message.file.name
            create_direc(f"{ps.dir}/subtitles")
            sub_dw_loc = check_file(f"{ps.dir}/subtitles", sub_name)
            sub_path   = await ne.download_media(file=sub_dw_loc)
            ps.append_subtitles(sub_path)
            idx += 1
        else:
            await safe_reply(event, "❗ Hanya Berkas Telegram yang Didukung")

    if cancel:
        del ps
        return
    if not ps.subtitles:
        del ps
        await safe_reply(event, f"❗ Minimal 1 Subtitle Diperlukan untuk {process_name}")
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
    await update_status_message(event)


@TELETHON_CLIENT.on(events.NewMessage(incoming=True, pattern=command("softmux")))
async def _softmux(event):
    await _subtitle_mux_handler(event, Names.softmux, "softmux")


@TELETHON_CLIENT.on(events.NewMessage(incoming=True, pattern=command("softremux")))
async def _softremux(event):
    await _subtitle_mux_handler(event, Names.softremux, "softremux")


# ═══════════════════════════════════════════════════════════════════════
#  CONVERT
# ═══════════════════════════════════════════════════════════════════════

@TELETHON_CLIENT.on(events.NewMessage(incoming=True, pattern=command("convert")))
async def _convert_video(event):
    await _generic_video_handler(event, Names.convert, "convert")


# ═══════════════════════════════════════════════════════════════════════
#  HARDMUX
# ═══════════════════════════════════════════════════════════════════════

@TELETHON_CLIENT.on(events.NewMessage(incoming=True, pattern=command("hardmux")))
async def _hardmux_subtitle(event):
    if not await vip_check(event):
        return
    user_id = event.message.sender.id
    chat_id = event.message.chat.id
    if user_id not in get_data():
        await new_user(user_id, SAVE_TO_DATABASE)

    link, custom_file_name = await get_link(event)
    if link == "invalid":
        await safe_reply(event, "❗ Tautan tidak valid")
        return
    if not link:
        ne = await ask_media_OR_url(
            event, chat_id, user_id,
            [f"/hardmux{CMD_SUFFIX}", "stop"], "Kirim Video atau URL", 120, "video/", True,
        )
        if ne and ne not in ["cancelled", "stopped"]:
            link = await get_url_from_message(ne)
        else:
            return

    ps = ProcessStatus(user_id, chat_id, get_username(event),
                       event.message.sender.first_name, event, Names.hardmux, custom_file_name)

    ne = await ask_media_OR_url(
        event, chat_id, user_id,
        [f"/hardmux{CMD_SUFFIX}", "stop"], "Kirim Berkas Subtitle SRT", 120,
        False, True, allow_magnet=False, allow_url=False,
    )
    if not ne or ne in ["cancelled", "stopped"]:
        del ps
        return

    if not ne.message.file:
        await safe_reply(event, "❗ Hanya Berkas Telegram yang Didukung")
        del ps
        return

    mime = str(ne.message.file.mime_type)
    if mime.startswith("video/") or mime.startswith("image/"):
        await safe_reply(event, "❌ Saya Membutuhkan Berkas Subtitle.")
        del ps
        return
    if ne.message.file.size >= 512_000:
        await safe_reply(event, "❌ Ukuran Subtitle Lebih dari 500KB")
        del ps
        return

    sub_name   = ne.message.file.name
    create_direc(f"{ps.dir}/subtitles")
    sub_dw_loc = check_file(f"{ps.dir}/subtitles", sub_name)
    sub_path   = await ne.download_media(file=sub_dw_loc)
    ps.append_subtitles(sub_path)

    await get_thumbnail(ps, [f"/hardmux{CMD_SUFFIX}", "pass"], 120)
    task = build_task(ps, link)

    if get_data().get(user_id, {}).get("multi_tasks"):
        ok = await multi_tasks(ps, f"/hardmux{CMD_SUFFIX}")
        if not ok:
            del ps
            return
        finalize_multi_tasks(ps)

    await submit_task(task)
    await update_status_message(event)


# ═══════════════════════════════════════════════════════════════════════
#  GENSAMPLE / GENSS
# ═══════════════════════════════════════════════════════════════════════

@TELETHON_CLIENT.on(events.NewMessage(incoming=True, pattern=command("gensample")))
async def _gen_video_sample(event):
    await _generic_video_handler(event, Names.gensample, "gensample")


@TELETHON_CLIENT.on(events.NewMessage(incoming=True, pattern=command("genss")))
async def _gen_screenshots(event):
    await _generic_video_handler(event, Names.genss, "genss")


# ═══════════════════════════════════════════════════════════════════════
#  CHANGE METADATA
# ═══════════════════════════════════════════════════════════════════════

@TELETHON_CLIENT.on(events.NewMessage(incoming=True, pattern=command("changemetadata")))
async def _change_metadata(event):
    if not await vip_check(event):
        return
    user_id = event.message.sender.id
    chat_id = event.message.chat.id
    cmd     = f"/changemetadata{CMD_SUFFIX}"
    if user_id not in get_data():
        await new_user(user_id, SAVE_TO_DATABASE)

    link, custom_file_name = await get_link(event)
    if link == "invalid":
        await safe_reply(event, "❗ Tautan tidak valid")
        return
    if not link:
        ne = await ask_media_OR_url(event, chat_id, user_id, [cmd, "stop"],
                                     "Kirim Video atau URL", 120, "video/", True)
        if ne and ne not in ["cancelled", "stopped"]:
            link = await get_url_from_message(ne)
        else:
            return

    me = await ask_text_event(
        chat_id, user_id, event, 120, "Kirim MetaData",
        message_hint=(
            "Format:\n`a:0-BahasaAudio-JudulAudio`\n`s:0-BahasaSub-JudulSub`\n\n"
            "Contoh: `a:1-eng-EncoderBot`"
        ),
    )
    if not me:
        return

    custom_metadata = []
    for m in str(me.message.message).split("\n"):
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
            await safe_reply(me, f"❗ Metadata Tidak Valid: {e}")
            return

    ps = ProcessStatus(user_id, chat_id, get_username(event),
                       event.message.sender.first_name, event, Names.changeMetadata,
                       custom_file_name, custom_metadata=custom_metadata)
    await get_thumbnail(ps, [cmd, "pass"], 120)
    task = build_task(ps, link)
    await submit_task(task)
    await update_status_message(event)


# ═══════════════════════════════════════════════════════════════════════
#  CHANGE INDEX
# ═══════════════════════════════════════════════════════════════════════

@TELETHON_CLIENT.on(events.NewMessage(incoming=True, pattern=command("changeindex")))
async def _change_index(event):
    if not await vip_check(event):
        return
    user_id = event.message.sender.id
    chat_id = event.message.chat.id
    cmd     = f"/changeindex{CMD_SUFFIX}"
    if user_id not in get_data():
        await new_user(user_id, SAVE_TO_DATABASE)

    link, custom_file_name = await get_link(event)
    if link == "invalid":
        await safe_reply(event, "❗ Tautan tidak valid")
        return
    if not link:
        ne = await ask_media_OR_url(event, chat_id, user_id, [cmd, "stop"],
                                     "Kirim Video atau URL", 120, "video/", True)
        if ne and ne not in ["cancelled", "stopped"]:
            link = await get_url_from_message(ne)
        else:
            return

    ie = await ask_text_event(
        chat_id, user_id, event, 120, "Kirim Indeks",
        message_hint=(
            "`a` Audio | `s` Subtitle\n"
            "Format: `a-3-1-2` (urutan 3,1,2)\n"
            "Contoh: `s-2-1`"
        ),
    )
    if not ie:
        return

    custom_index = []
    for m in str(ie.message.message).split("\n"):
        mdata = str(m).strip().split("-")
        try:
            stream = str(mdata[0]).strip().lower()
            mdata.pop(0)
            for s in mdata:
                si = int(s.strip()) - 1
                custom_index += ["-map", f"0:{stream}:{si}"]
            custom_index += [f"-disposition:{stream}:0", "default"]
        except (ValueError, IndexError, Exception) as e:
            await safe_reply(ie, f"❗ Indeks Tidak Valid: {e}")
            return

    ps = ProcessStatus(user_id, chat_id, get_username(event),
                       event.message.sender.first_name, event, Names.changeindex,
                       custom_file_name, custom_index=custom_index)
    await get_thumbnail(ps, [cmd, "pass"], 120)
    task = build_task(ps, link)
    await submit_task(task)
    await update_status_message(event)


# ═══════════════════════════════════════════════════════════════════════
#  LEECH / MIRROR
# ═══════════════════════════════════════════════════════════════════════

async def _leech_mirror_handler(event, process_name: str, cmd_name: str):
    if not await vip_check(event):
        return
    user_id = event.message.sender.id
    chat_id = event.message.chat.id
    if user_id not in get_data():
        await new_user(user_id, SAVE_TO_DATABASE)

    link, custom_file_name = await get_link(event)
    if link == "invalid":
        await safe_reply(event, "❗ Tautan tidak valid")
        return
    if not link:
        ne = await ask_url(event, chat_id, user_id, [f"/{cmd_name}{CMD_SUFFIX}", "stop"],
                            "Kirim Tautan", 120, True)
        if ne and ne not in ["cancelled", "stopped"]:
            link = await get_url_from_message(ne)
        else:
            return

    ps = ProcessStatus(user_id, chat_id, get_username(event),
                       event.message.sender.first_name, event, process_name, custom_file_name)
    await get_thumbnail(ps, [f"/{cmd_name}{CMD_SUFFIX}", "pass"], 120)
    task = build_task(ps, link)
    await submit_task(task)
    await update_status_message(event)


@TELETHON_CLIENT.on(events.NewMessage(incoming=True, pattern=command("leech")))
async def _leech_file(event):
    await _leech_mirror_handler(event, Names.leech, "leech")


@TELETHON_CLIENT.on(events.NewMessage(incoming=True, pattern=command("mirror")))
async def _mirror_file(event):
    await _leech_mirror_handler(event, Names.mirror, "mirror")


# ═══════════════════════════════════════════════════════════════════════
#  STATUS
# ═══════════════════════════════════════════════════════════════════════

@TELETHON_CLIENT.on(events.NewMessage(incoming=True, pattern=command("status"),
                                       func=lambda e: user_auth_checker(e)))
async def _status(event):
    user_id = event.message.sender.id
    if user_id not in get_data():
        await new_user(user_id, SAVE_TO_DATABASE)
    await update_status_message(event)
