"""
╔══════════════════════════════════════════════════════════════════════╗
║    bot_helper/Handlers/advanced_media_handlers.py — v3.1            ║
║    Advanced Media Handlers (Interactive/Conversation-based)         ║
╠══════════════════════════════════════════════════════════════════════╣
║  Commands: /trim /split /cut /rotate /crop /autocrop                ║
║            /extension /extract /mediainfo                           ║
╚══════════════════════════════════════════════════════════════════════╝
"""

# ── Standard Library ──────────────────────────────────────────────────
import asyncio
from json import loads as json_loads
from os.path import exists
from shutil import rmtree

# ── Third Party ───────────────────────────────────────────────────────
from asyncio import create_subprocess_exec
from asyncio.subprocess import PIPE as asyncioPIPE
from telethon import Button, events
from telethon.tl.types import DocumentAttributeVideo

# ── Internal ──────────────────────────────────────────────────────────
from bot_helper.Aria2.Aria2_Engine import Aria2
from bot_helper.Database.User_Data import get_data, new_user
from bot_helper.Others.Helper_Functions import (
    get_human_size, seconds_to_readable_str, time_string_to_seconds,
)
from bot_helper.Others.Names import Names
from bot_helper.Process.Process_Status import ProcessStatus
from bot_helper.Process.Running_Tasks import add_task, working_task
from bot_helper.Telegram.Telegram_Client import Telegram
from config.config import Config

from .shared import (
    CMD_SUFFIX, LOGGER, SAVE_TO_DATABASE, TELETHON_CLIENT,
    build_task, command, get_link, get_thumbnail, get_username,
    safe_reply, submit_task, update_status_message, user_auth_checker, vip_check,
)

import re as _re


# ═══════════════════════════════════════════════════════════════════════
#  TIME VALIDATION
# ═══════════════════════════════════════════════════════════════════════

def is_valid_time_format(time_str: str) -> bool:
    """Validasi format HH:MM:SS atau MM:SS."""
    try:
        parts = list(map(int, time_str.strip().split(":")))
        if len(parts) > 3 or len(parts) == 0:
            return False
        for i, p in enumerate(parts):
            if i > 0 and (p < 0 or p > 59):
                return False
        return True
    except (ValueError, TypeError):
        return False


def parse_single_cut_range(text: str):
    """Parse 'MM:SS-MM:SS' → (start_sec, end_sec) atau None."""
    parts = text.strip().split("-", 1)
    if len(parts) != 2:
        # Handle HH:MM:SS-HH:MM:SS (ada 5 dash)
        parts = text.strip().rsplit("-", 1)
        if len(parts) != 2:
            return None
    start_str, end_str = parts[0].strip(), parts[1].strip()
    if not is_valid_time_format(start_str) or not is_valid_time_format(end_str):
        return None
    s = time_string_to_seconds(start_str)
    e = time_string_to_seconds(end_str)
    if s >= e:
        return None
    return (s, e)


# ═══════════════════════════════════════════════════════════════════════
#  /trim
# ═══════════════════════════════════════════════════════════════════════

@TELETHON_CLIENT.on(events.NewMessage(incoming=True, pattern=command("trim")))
async def _trim_video(event):
    if not await vip_check(event):
        return
    user_id = event.message.sender.id
    chat_id = event.message.chat.id
    if user_id not in get_data():
        await new_user(user_id, SAVE_TO_DATABASE)

    link, custom_file_name = await get_link(event)
    video_event_for_task   = None
    orig_duration          = 0

    if link == "invalid":
        await safe_reply(event, "❗ Tautan tidak valid.")
        return
    if not link:
        try:
            async with event.client.conversation(chat_id, timeout=120) as conv:
                await conv.send_message("Kirim Video atau URL yang ingin di-trim.")
                resp = await conv.get_response()
                if resp.media and resp.media.document:
                    link = resp
                elif resp.text.startswith("http"):
                    link = resp.text
                else:
                    await conv.send_message("Input tidak valid. Dibatalkan.")
                    return
        except asyncio.TimeoutError:
            await safe_reply(event, "⏱ Waktu habis, proses dibatalkan.")
            return

    video_event_for_task = link
    if not isinstance(link, str) and hasattr(link.media, "document"):
        for attr in link.media.document.attributes:
            if isinstance(attr, DocumentAttributeVideo):
                orig_duration = attr.duration
                break

    orig_str = seconds_to_readable_str(orig_duration) if orig_duration else "Tidak Diketahui"

    try:
        async with event.client.conversation(chat_id, timeout=300) as conv:
            await conv.send_message("Masukkan **Waktu Mulai** (Start Time).\nFormat: `HH:MM:SS` atau `MM:SS`")
            st_res = await conv.get_response()
            if not is_valid_time_format(st_res.text):
                await conv.send_message("❌ Format waktu mulai tidak valid. Dibatalkan.")
                return

            await conv.send_message("Masukkan **Waktu Selesai** (End Time).\nFormat: `HH:MM:SS` atau `MM:SS`")
            et_res = await conv.get_response()
            if not is_valid_time_format(et_res.text):
                await conv.send_message("❌ Format waktu selesai tidak valid. Dibatalkan.")
                return

            start_time = st_res.text.strip()
            end_time   = et_res.text.strip()
            start_sec  = time_string_to_seconds(start_time)
            end_sec    = time_string_to_seconds(end_time)

            if start_sec >= end_sec:
                await conv.send_message("❌ Waktu selesai harus lebih besar dari waktu mulai.")
                return
            if orig_duration > 0 and end_sec > orig_duration:
                await conv.send_message(
                    f"❌ Waktu selesai melebihi durasi video (`{orig_str}`)."
                )
                return

            dur_str = seconds_to_readable_str(end_sec - start_sec)
            conf_msg = await conv.send_message(
                f"**✂️ KONFIRMASI PANGKAS VIDEO**\n\n"
                f"⏳ Durasi Asli: `{orig_str}`\n"
                f"🎬 Waktu Mulai: `{start_time}`\n"
                f"🏁 Waktu Selesai: `{end_time}`\n"
                f"✂️ Hasil: `{dur_str}`\n\n"
                "Lanjutkan?",
                buttons=[
                    [Button.inline("✅ Mulai Pangkas", "trim_confirm")],
                    [Button.inline("❌ Batal",         "trim_cancel")],
                ],
            )
            press = await conv.wait_event(
                events.CallbackQuery(func=lambda e: e.sender_id == user_id)
            )
            await press.answer()
            if press.data == b"trim_cancel":
                await conf_msg.edit("Dibatalkan.")
                return
            await conf_msg.edit("✅ Mempersiapkan proses...")
    except asyncio.TimeoutError:
        await safe_reply(event, "⏱ Waktu habis, proses dibatalkan.")
        return
    except Exception as e:
        await safe_reply(event, f"❌ Error: {e}")
        LOGGER.error(f"/trim conversation error: {e}", exc_info=True)
        return

    ps = ProcessStatus(user_id, chat_id, get_username(event),
                       event.message.sender.first_name, event, Names.trim, custom_file_name)
    ps.trim_start = start_time
    ps.trim_end   = end_time
    await get_thumbnail(ps, [f"/trim{CMD_SUFFIX}", "pass"], 120)
    task = build_task(ps, video_event_for_task)
    await submit_task(task)
    await update_status_message(event)


# ═══════════════════════════════════════════════════════════════════════
#  /split
# ═══════════════════════════════════════════════════════════════════════

@TELETHON_CLIENT.on(events.NewMessage(incoming=True, pattern=command("split")))
async def _split_video(event):
    if not await vip_check(event):
        return
    user_id = event.message.sender.id
    chat_id = event.message.chat.id
    if user_id not in get_data():
        await new_user(user_id, SAVE_TO_DATABASE)

    link, custom_file_name = await get_link(event)
    video_event_for_task   = None
    orig_duration          = 0

    if link == "invalid":
        await safe_reply(event, "❗ Tautan tidak valid.")
        return
    if not link:
        try:
            async with event.client.conversation(chat_id, timeout=120) as conv:
                await conv.send_message("Kirim Video atau URL yang ingin dibagi (split).")
                resp = await conv.get_response()
                link = resp if (resp.media and resp.media.document) else (resp.text if resp.text.startswith("http") else None)
                if not link:
                    await conv.send_message("Input tidak valid. Dibatalkan.")
                    return
        except asyncio.TimeoutError:
            await safe_reply(event, "⏱ Waktu habis.")
            return

    video_event_for_task = link
    if not isinstance(link, str) and hasattr(link.media, "document"):
        for attr in link.media.document.attributes:
            if isinstance(attr, DocumentAttributeVideo):
                orig_duration = attr.duration

    orig_str   = seconds_to_readable_str(orig_duration) if orig_duration else "Tidak Diketahui"
    split_mode = split_value = None

    try:
        async with event.client.conversation(chat_id, timeout=300) as conv:
            mode_msg = await conv.send_message(
                "**Pilih Mode Pembagian Video:**",
                buttons=[
                    [Button.inline("⏱ Berdasarkan Durasi",      "duration")],
                    [Button.inline("🔢 Berdasarkan Jumlah Bagian", "parts")],
                    [Button.inline("📦 Berdasarkan Ukuran Berkas", "size")],
                    [Button.inline("❌ Batal", "cancel")],
                ],
            )
            press = await conv.wait_event(events.CallbackQuery(func=lambda e: e.sender_id == user_id))
            cb    = press.data.decode()
            await press.answer()

            if cb == "cancel":
                await mode_msg.edit("Dibatalkan.")
                return

            mode_labels = {"duration": "Durasi (detik)", "parts": "Jumlah Bagian", "size": "Ukuran (MB)"}
            split_mode  = cb
            await mode_msg.edit(f"Masukkan nilai untuk **{mode_labels[cb]}**:")
            val_res = await conv.get_response()
            if not val_res.text.isdigit():
                await conv.send_message("Input tidak valid. Dibatalkan.")
                return
            split_value = int(val_res.text)

            info = {"duration": f"Setiap `{split_value}s`",
                    "parts":    f"Menjadi `{split_value}` bagian",
                    "size":     f"Setiap `~{split_value}MB`"}[cb]

            conf_msg = await conv.send_message(
                f"**✂️ KONFIRMASI PEMBAGIAN VIDEO**\n\n"
                f"⏳ Durasi Asli: `{orig_str}`\n"
                f"⚙️ Mode: `{cb.capitalize()}`\n"
                f"📊 Pengaturan: {info}\n\nLanjutkan?",
                buttons=[
                    [Button.inline("✅ Mulai Bagi", "confirm")],
                    [Button.inline("❌ Batal",       "cancel")],
                ],
            )
            press2 = await conv.wait_event(events.CallbackQuery(func=lambda e: e.sender_id == user_id))
            await press2.answer()
            if press2.data == b"cancel":
                await conf_msg.edit("Dibatalkan.")
                return
            await conf_msg.edit("✅ Mempersiapkan pembagian...")
    except asyncio.TimeoutError:
        await safe_reply(event, "⏱ Waktu habis.")
        return
    except Exception as e:
        await safe_reply(event, f"❌ Error: {e}")
        LOGGER.error(f"/split error: {e}", exc_info=True)
        return

    ps = ProcessStatus(user_id, chat_id, get_username(event),
                       event.message.sender.first_name, event, Names.split, custom_file_name)
    ps.split_mode  = split_mode
    ps.split_value = split_value
    await get_thumbnail(ps, [f"/split{CMD_SUFFIX}", "pass"], 120)
    task = build_task(ps, video_event_for_task)
    await submit_task(task)
    await update_status_message(event)


# ═══════════════════════════════════════════════════════════════════════
#  /cut
# ═══════════════════════════════════════════════════════════════════════

@TELETHON_CLIENT.on(events.NewMessage(incoming=True, pattern=command("cut")))
async def _cut_video(event):
    if not await vip_check(event):
        return
    user_id = event.message.sender.id
    chat_id = event.message.chat.id
    if user_id not in get_data():
        await new_user(user_id, SAVE_TO_DATABASE)

    link, custom_file_name = await get_link(event)
    video_event_for_task   = None

    if link == "invalid":
        await safe_reply(event, "❗ Tautan tidak valid.")
        return
    if not link:
        try:
            async with event.client.conversation(chat_id, timeout=120) as conv:
                await conv.send_message("Kirim Video atau URL yang bagiannya ingin dibuang.")
                resp = await conv.get_response()
                link = resp if (resp.media and resp.media.document) else (resp.text if resp.text.startswith("http") else None)
                if not link:
                    await conv.send_message("Input tidak valid. Dibatalkan.")
                    return
        except asyncio.TimeoutError:
            await safe_reply(event, "⏱ Waktu habis.")
            return

    video_event_for_task = link
    cut_ranges = []

    async def _menu_text():
        title = "**✂️ Potong Segmen Video**\n\n"
        body  = "**Segmen yang akan Dibuang:**\n"
        if not cut_ranges:
            body += "*(Belum ada)*\n"
        else:
            for s, e in cut_ranges:
                body += f"• `{seconds_to_readable_str(s)}` - `{seconds_to_readable_str(e)}`\n"
        return title + body

    async def _build_buttons():
        btns = []
        if cut_ranges:
            btns.append([Button.inline("➕ Tambah Lagi",    "add"),
                         Button.inline("🗑️ Hapus Semua",    "clear")])
        else:
            btns.append([Button.inline("➕ Tambah Segmen",  "add")])
        btns.append([Button.inline("🏁 Lanjutkan",  "finish"),
                     Button.inline("❌ Batal",       "cancel")])
        return btns

    try:
        async with event.client.conversation(chat_id, timeout=600) as conv:
            menu_msg = await conv.send_message(await _menu_text(), buttons=await _build_buttons())

            while True:
                press = await conv.wait_event(events.CallbackQuery(func=lambda e: e.sender_id == user_id))
                action = press.data.decode()
                await press.answer()

                if action == "add":
                    ask_msg = await conv.send_message(
                        "Kirim rentang waktu yang akan dibuang.\n**Format:** `MM:SS-MM:SS`"
                    )
                    resp = await conv.get_response()
                    parsed = parse_single_cut_range(resp.text)
                    await ask_msg.delete()
                    await resp.delete()
                    if parsed:
                        cut_ranges.append(parsed)
                    else:
                        err = await conv.send_message("⚠️ Format tidak valid. Coba lagi.")
                        await asyncio.sleep(2)
                        await err.delete()
                    await menu_msg.edit(await _menu_text(), buttons=await _build_buttons())

                elif action == "clear":
                    cut_ranges.clear()
                    await menu_msg.edit(await _menu_text(), buttons=await _build_buttons())

                elif action == "finish":
                    if not cut_ranges:
                        await conv.send_message("Tidak ada segmen. Dibatalkan.")
                        await menu_msg.delete()
                        return
                    await menu_msg.edit("✅ Mempersiapkan proses cut...", buttons=None)
                    break

                elif action == "cancel":
                    await menu_msg.edit("Dibatalkan.", buttons=None)
                    return

    except asyncio.TimeoutError:
        await safe_reply(event, "⏱ Waktu habis.")
        return
    except Exception as e:
        await safe_reply(event, f"❌ Error: {e}")
        LOGGER.error(f"/cut error: {e}", exc_info=True)
        return

    ps = ProcessStatus(user_id, chat_id, get_username(event),
                       event.message.sender.first_name, event, Names.cut, custom_file_name)
    ps.cut_ranges = cut_ranges
    await get_thumbnail(ps, [f"/cut{CMD_SUFFIX}", "pass"], 120)
    task = build_task(ps, video_event_for_task)
    await submit_task(task)
    await update_status_message(event)


# ═══════════════════════════════════════════════════════════════════════
#  /rotate
# ═══════════════════════════════════════════════════════════════════════

@TELETHON_CLIENT.on(events.NewMessage(incoming=True, pattern=command("rotate")))
async def _rotate_video(event):
    if not await vip_check(event):
        return
    user_id = event.message.sender.id
    chat_id = event.message.chat.id
    if user_id not in get_data():
        await new_user(user_id, SAVE_TO_DATABASE)

    link, custom_file_name = await get_link(event)
    video_event_for_task   = None

    if link == "invalid":
        await safe_reply(event, "❗ Tautan tidak valid.")
        return
    if not link:
        try:
            async with event.client.conversation(chat_id, timeout=120) as conv:
                await conv.send_message("Kirim Video atau URL yang ingin diputar/dibalik.")
                resp = await conv.get_response()
                link = resp if (resp.media and hasattr(resp.media, "document") and
                                "video" in resp.media.document.mime_type) else (
                    resp.text if resp.text.startswith("http") else None)
                if not link:
                    await conv.send_message("Input tidak valid. Dibatalkan.")
                    return
        except asyncio.TimeoutError:
            await safe_reply(event, "⏱ Waktu habis.")
            return

    video_event_for_task = link
    rotate_option = None

    try:
        async with event.client.conversation(chat_id, timeout=120) as conv:
            menu_msg = await conv.send_message(
                "**🔄 Pilih Opsi Rotasi Video:**",
                buttons=[
                    [Button.inline("➡️ 90° Searah Jarum Jam",   "transpose=1")],
                    [Button.inline("⬅️ 90° Berlawanan Arah",    "transpose=2")],
                    [Button.inline("🔃 Balik Vertikal",  "vflip"),
                     Button.inline("↔️ Balik Horizontal","hflip")],
                    [Button.inline("⚙️ Kustom (Derajat)", "custom")],
                    [Button.inline("❌ Batal",            "cancel")],
                ],
            )
            press = await conv.wait_event(events.CallbackQuery(func=lambda e: e.sender_id == user_id))
            action = press.data.decode()
            await press.answer()

            if action == "cancel":
                await menu_msg.edit("Dibatalkan.", buttons=None)
                return
            if action == "custom":
                await menu_msg.delete()
                await conv.send_message(
                    "Masukkan derajat (`45` atau `-45`) atau filter FFmpeg kustom.\n"
                    "Contoh: `45`, `hflip,vflip`"
                )
                resp = await conv.get_response()
                inp  = resp.text.strip()
                try:
                    angle = float(inp)
                    rotate_option = f"rotate={angle}*PI/180"
                except ValueError:
                    rotate_option = inp
            else:
                rotate_option = action
            await conv.send_message(
                f"✅ Filter: `{rotate_option}`. Mempersiapkan...", buttons=None
            )
            try:
                await menu_msg.delete()
            except Exception:
                pass

    except asyncio.TimeoutError:
        await safe_reply(event, "⏱ Waktu habis.")
        return
    except Exception as e:
        await safe_reply(event, f"❌ Error: {e}")
        LOGGER.error(f"/rotate error: {e}", exc_info=True)
        return

    ps = ProcessStatus(user_id, chat_id, get_username(event),
                       event.message.sender.first_name, event, Names.rotate, custom_file_name)
    ps.rotate_option = rotate_option
    await get_thumbnail(ps, [f"/rotate{CMD_SUFFIX}", "pass"], 120)
    task = build_task(ps, video_event_for_task)
    await submit_task(task)
    await update_status_message(event)


# ═══════════════════════════════════════════════════════════════════════
#  /crop
# ═══════════════════════════════════════════════════════════════════════

@TELETHON_CLIENT.on(events.NewMessage(incoming=True, pattern=command("crop")))
async def _crop_video(event):
    if not await vip_check(event):
        return
    user_id = event.message.sender.id
    chat_id = event.message.chat.id
    if user_id not in get_data():
        await new_user(user_id, SAVE_TO_DATABASE)

    link, custom_file_name = await get_link(event)
    video_event_for_task   = None
    crop_params            = None

    if link == "invalid":
        await safe_reply(event, "❗ Tautan tidak valid.")
        return
    if not link:
        try:
            async with event.client.conversation(chat_id, timeout=120) as conv:
                await conv.send_message("Kirim Video atau URL yang ingin di-crop.")
                resp = await conv.get_response()
                link = resp if (resp.media and hasattr(resp.media, "document") and
                                "video" in resp.media.document.mime_type) else (
                    resp.text if resp.text.startswith("http") else None)
                if not link:
                    await conv.send_message("Input tidak valid atau bukan video. Dibatalkan.")
                    return
        except asyncio.TimeoutError:
            await safe_reply(event, "⏱ Waktu habis.")
            return

    video_event_for_task = link

    try:
        async with event.client.conversation(chat_id, timeout=300) as conv:
            menu_msg = await conv.send_message(
                "**🖼️ Pilih Opsi Crop Video:**",
                buttons=[
                    [Button.inline("🖼️ 1:1 (Persegi)",     "crop='min(in_w,in_h):min(in_w,in_h)'")],
                    [Button.inline("🎬 16:9 (Layar Lebar)", "crop=in_w:in_w*9/16")],
                    [Button.inline("📱 9:16 (Vertikal)",    "crop=in_h*9/16:in_h")],
                    [Button.inline("⚙️ Kustom",             "custom")],
                    [Button.inline("❌ Batal",               "cancel")],
                ],
            )
            press = await conv.wait_event(events.CallbackQuery(func=lambda e: e.sender_id == user_id))
            action = press.data.decode()
            await press.answer()

            if action == "cancel":
                await menu_msg.edit("Dibatalkan.", buttons=None)
                return

            if action == "custom":
                await menu_msg.delete()
                for label in ["**Lebar** (Width):", "**Tinggi** (Height):", "**X** (0=tengah):", "**Y** (0=tengah):"]:
                    await conv.send_message(label)
                    resp = await conv.get_response()
                w, h, x, y = [r.text for r in await _collect_4(conv, ["Lebar", "Tinggi", "X", "Y"])]
                # simplified — tunggu 4 response berurutan
                await menu_msg.delete()
                await conv.send_message("Masukkan **Lebar** (Width):")
                w = (await conv.get_response()).text
                await conv.send_message("Masukkan **Tinggi** (Height):")
                h = (await conv.get_response()).text
                await conv.send_message("Masukkan **X** (0=tengah):")
                x = (await conv.get_response()).text
                await conv.send_message("Masukkan **Y** (0=tengah):")
                y = (await conv.get_response()).text
                if not all(v.lstrip("-").isdigit() for v in [w, h, x, y]):
                    await conv.send_message("Input tidak valid. Dibatalkan.")
                    return
                x_pos = f"(in_w-{w})/2" if x == "0" else x
                y_pos = f"(in_h-{h})/2" if y == "0" else y
                crop_params = f"crop={w}:{h}:{x_pos}:{y_pos}"
            else:
                crop_params = action

            await conv.send_message(f"✅ Parameter: `{crop_params}`. Mempersiapkan...", buttons=None)
    except asyncio.TimeoutError:
        await safe_reply(event, "⏱ Waktu habis.")
        return
    except Exception as e:
        await safe_reply(event, f"❌ Error: {e}")
        LOGGER.error(f"/crop error: {e}", exc_info=True)
        return

    ps = ProcessStatus(user_id, chat_id, get_username(event),
                       event.message.sender.first_name, event, Names.crop, custom_file_name)
    ps.crop_params = crop_params
    await get_thumbnail(ps, [f"/crop{CMD_SUFFIX}", "pass"], 120)
    task = build_task(ps, video_event_for_task)
    await submit_task(task)
    await update_status_message(event)


async def _collect_4(conv, labels):
    """Kumpulkan 4 response dari conv."""
    results = []
    for label in labels:
        await conv.send_message(f"Masukkan **{label}**:")
        results.append(await conv.get_response())
    return results


# ═══════════════════════════════════════════════════════════════════════
#  /autocrop
# ═══════════════════════════════════════════════════════════════════════

@TELETHON_CLIENT.on(events.NewMessage(incoming=True, pattern=command("autocrop")))
async def _autocrop_video(event):
    if not await vip_check(event):
        return
    user_id = event.message.sender.id
    chat_id = event.message.chat.id
    if user_id not in get_data():
        await new_user(user_id, SAVE_TO_DATABASE)

    link, custom_file_name = await get_link(event)
    video_event_for_task   = None

    if link == "invalid":
        await safe_reply(event, "❗ Tautan tidak valid.")
        return
    if not link:
        try:
            async with event.client.conversation(chat_id, timeout=120) as conv:
                await conv.send_message("Kirim Video atau URL untuk autocrop.")
                resp = await conv.get_response()
                link = resp if (resp.media and hasattr(resp.media, "document") and
                                "video" in resp.media.document.mime_type) else (
                    resp.text if resp.text.startswith("http") else None)
                if not link:
                    await conv.send_message("Input tidak valid. Dibatalkan.")
                    return
        except asyncio.TimeoutError:
            await safe_reply(event, "⏱ Waktu habis.")
            return

    video_event_for_task = link

    try:
        async with event.client.conversation(chat_id, timeout=120) as conv:
            menu_msg = await conv.send_message(
                "**✨ Autocrop** akan otomatis membuang black bars dari video. Lanjutkan?",
                buttons=[
                    [Button.inline("✅ Mulai Autocrop", "start")],
                    [Button.inline("❌ Batal",           "cancel")],
                ],
            )
            press = await conv.wait_event(events.CallbackQuery(func=lambda e: e.sender_id == user_id))
            await press.answer()
            if press.data == b"cancel":
                await menu_msg.edit("Dibatalkan.", buttons=None)
                return
            await menu_msg.edit("✅ Mempersiapkan autocrop...", buttons=None)
    except asyncio.TimeoutError:
        await safe_reply(event, "⏱ Waktu habis.")
        return
    except Exception as e:
        await safe_reply(event, f"❌ Error: {e}")
        LOGGER.error(f"/autocrop error: {e}", exc_info=True)
        return

    ps = ProcessStatus(user_id, chat_id, get_username(event),
                       event.message.sender.first_name, event, Names.autocrop, custom_file_name)
    await get_thumbnail(ps, [f"/autocrop{CMD_SUFFIX}", "pass"], 120)
    task = build_task(ps, video_event_for_task)
    await submit_task(task)
    await update_status_message(event)


# ═══════════════════════════════════════════════════════════════════════
#  /extension
# ═══════════════════════════════════════════════════════════════════════

@TELETHON_CLIENT.on(events.NewMessage(incoming=True, pattern=command("extension")))
async def _extension_changer(event):
    if not await vip_check(event):
        return
    user_id = event.message.sender.id
    chat_id = event.message.chat.id
    if user_id not in get_data():
        await new_user(user_id, SAVE_TO_DATABASE)

    link, custom_file_name = await get_link(event)
    video_event_for_task   = None
    new_extension          = None

    if link == "invalid":
        await safe_reply(event, "❗ Tautan tidak valid.")
        return
    if not link:
        try:
            async with event.client.conversation(chat_id, timeout=120) as conv:
                await conv.send_message("Kirim file (video/audio/subtitle) yang ekstensinya ingin diubah.")
                resp = await conv.get_response()
                link = resp if (resp.media and resp.media.document) else (
                    resp.text if resp.text.startswith("http") else None)
                if not link:
                    await conv.send_message("Input tidak valid. Dibatalkan.")
                    return
        except asyncio.TimeoutError:
            await safe_reply(event, "⏱ Waktu habis.")
            return

    video_event_for_task = link

    file_type = "unknown"
    if not isinstance(link, str) and hasattr(link, "file") and link.file:
        mime = link.file.mime_type or ""
        name = link.file.name or ""
        if "video" in mime:   file_type = "video"
        elif "audio" in mime: file_type = "audio"
        elif any(name.endswith(e) for e in [".srt", ".ass", ".vtt", ".sub"]):
            file_type = "subtitle"

    if file_type == "unknown":
        await safe_reply(event, "❌ Jenis file tidak didukung.")
        return

    ext_map = {
        "video":    [".mkv", ".mp4", ".mov"],
        "audio":    [".mp3", ".opus", ".flac"],
        "subtitle": [".srt", ".ass", ".vtt"],
    }

    try:
        async with event.client.conversation(chat_id, timeout=300) as conv:
            btns = [[Button.inline(e, e.lstrip(".")) for e in ext_map[file_type]]]
            btns.append([Button.inline("⚙️ Kustom", "custom"), Button.inline("❌ Batal", "cancel")])
            menu_msg = await conv.send_message(
                f"Anda mengirim berkas **{file_type}**. Pilih ekstensi baru:",
                buttons=btns,
            )
            press = await conv.wait_event(events.CallbackQuery(func=lambda e: e.sender_id == user_id))
            action = press.data.decode()
            await press.answer()

            if action == "cancel":
                await menu_msg.edit("Dibatalkan.")
                return
            if action == "custom":
                await menu_msg.edit(f"Kirim ekstensi kustom (tanpa titik):")
                resp = await conv.get_response()
                new_extension = resp.text.strip().lstrip(".")
            else:
                new_extension = action
            await menu_msg.edit(f"✅ Berkas akan diubah ke `.{new_extension}`. Mempersiapkan...", buttons=None)
    except asyncio.TimeoutError:
        await safe_reply(event, "⏱ Waktu habis.")
        return
    except Exception as e:
        await safe_reply(event, f"❌ Error: {e}")
        LOGGER.error(f"/extension error: {e}", exc_info=True)
        return

    ps = ProcessStatus(user_id, chat_id, get_username(event),
                       event.message.sender.first_name, event, Names.extension, custom_file_name)
    ps.new_extension = new_extension
    await get_thumbnail(ps, [f"/extension{CMD_SUFFIX}", "pass"], 120)
    task = build_task(ps, video_event_for_task)
    await submit_task(task)
    await update_status_message(event)


# ═══════════════════════════════════════════════════════════════════════
#  /extract
# ═══════════════════════════════════════════════════════════════════════

@TELETHON_CLIENT.on(events.NewMessage(incoming=True, pattern=command("extract")))
async def _extract_streams(event):
    if not await vip_check(event):
        return
    user_id = event.message.sender.id
    chat_id = event.message.chat.id
    if user_id not in get_data():
        await new_user(user_id, SAVE_TO_DATABASE)

    link, custom_file_name = await get_link(event)
    video_event_for_task   = None

    if link == "invalid":
        await safe_reply(event, "❗ Tautan tidak valid.")
        return
    if not link:
        try:
            async with event.client.conversation(chat_id, timeout=120) as conv:
                await conv.send_message("Kirim Video atau URL yang stream-nya ingin diekstrak.")
                resp = await conv.get_response()
                link = resp if (resp.media and resp.media.document) else (
                    resp.text if resp.text.startswith("http") else None)
                if not link:
                    await conv.send_message("Input tidak valid. Dibatalkan.")
                    return
        except asyncio.TimeoutError:
            await safe_reply(event, "⏱ Waktu habis.")
            return

    video_event_for_task = link

    # Download untuk analisis
    dling_msg = await event.reply("🔽 Mengunduh berkas untuk dianalisis...")

    async def _download_temp():
        from bot_helper.Others.Names import Names as N_
        temp_ps = ProcessStatus(user_id, chat_id, get_username(event),
                                event.message.sender.first_name, event, N_.pre_download)
        funcs   = ([["Aria", Aria2.add_aria2c_download,
                     [link, temp_ps, False, False, False, False]]]
                   if isinstance(link, str) else [["TG", [video_event_for_task]]])
        await add_task({"process_status": temp_ps, "functions": funcs})
        while any(t["process_status"].process_id == temp_ps.process_id for t in working_task):
            await asyncio.sleep(2)
        return (temp_ps.send_files[-1] if temp_ps.send_files else None), temp_ps

    input_file, temp_ps = await _download_temp()

    if not input_file or not exists(input_file):
        await dling_msg.edit("❌ Gagal mengunduh berkas.")
        try:
            rmtree(temp_ps.dir)
        except Exception:
            pass
        return
    await dling_msg.delete()

    # ffprobe
    try:
        proc = await create_subprocess_exec(
            "ffprobe", "-v", "quiet", "-print_format", "json", "-show_streams", input_file,
            stdout=asyncioPIPE,
        )
        stdout, _ = await proc.communicate()
        all_streams = json_loads(stdout.decode("utf-8", "replace")).get("streams", [])
    except Exception as e:
        await safe_reply(event, f"❌ Gagal menganalisis video: {e}")
        return

    audio_subs = [s for s in all_streams if s.get("codec_type") == "audio"]
    sub_subs   = [s for s in all_streams if s.get("codec_type") == "subtitle"]

    if not audio_subs and not sub_subs:
        await safe_reply(event, "❌ Tidak ada stream audio/subtitle.")
        return

    selected = []

    def _stream_label(s, mark=False):
        idx   = s["index"]
        lang  = s.get("tags", {}).get("language", "und")
        codec = s.get("codec_name", "?")
        label = f"#{idx}: {lang.upper()} ({codec})"
        return f"✅ {label}" if (idx in selected) else label

    async def _build_stream_menu(msg=None):
        btns = []
        if audio_subs:
            btns.append([Button.inline("─── 🎧 AUDIO ───", "ignore")])
            for s in audio_subs:
                btns.append([Button.inline(_stream_label(s), f"sel_{s['index']}")])
        if sub_subs:
            btns.append([Button.inline("─── 📖 SUBTITLE ───", "ignore")])
            for s in sub_subs:
                btns.append([Button.inline(_stream_label(s), f"sel_{s['index']}")])
        if audio_subs:
            btns.append([Button.inline("🎵 Semua Audio", "sel_all_audio")])
        if sub_subs:
            btns.append([Button.inline("📖 Semua Subtitle", "sel_all_sub")])
        btns.append([Button.inline("✅ Ekstrak", "finish"), Button.inline("❌ Batal", "cancel")])
        text = "**📤 Pilih Stream yang Ingin Diekstrak**\n\nKlik untuk pilih/batal."
        if msg:
            try:
                await msg.edit(text, buttons=btns)
            except Exception:
                pass
            return msg
        return await event.reply(text, buttons=btns)

    try:
        async with event.client.conversation(chat_id, timeout=300) as conv:
            menu_msg = await _build_stream_menu()
            while True:
                press = await conv.wait_event(events.CallbackQuery(func=lambda e: e.sender_id == user_id))
                action = press.data.decode()
                await press.answer()
                prev = selected.copy()

                if action == "sel_all_audio":
                    for s in audio_subs:
                        if s["index"] not in selected:
                            selected.append(s["index"])
                elif action == "sel_all_sub":
                    for s in sub_subs:
                        if s["index"] not in selected:
                            selected.append(s["index"])
                elif action.startswith("sel_"):
                    idx = int(action.split("_")[1])
                    if idx in selected:
                        selected.remove(idx)
                    else:
                        selected.append(idx)
                elif action == "finish":
                    if not selected:
                        await conv.send_message("Belum ada stream dipilih. Dibatalkan.")
                        await menu_msg.delete()
                        return
                    await menu_msg.edit("✅ Mempersiapkan ekstraksi...", buttons=None)
                    break
                elif action == "cancel":
                    await menu_msg.edit("Dibatalkan.", buttons=None)
                    return

                if prev != selected:
                    menu_msg = await _build_stream_menu(menu_msg)

    except asyncio.TimeoutError:
        await safe_reply(event, "⏱ Waktu habis.")
        return
    except Exception as e:
        if "MessageNotModified" not in str(e):
            await safe_reply(event, f"❌ Error: {e}")
            LOGGER.error(f"/extract error: {e}", exc_info=True)
        return

    ps = ProcessStatus(user_id, chat_id, get_username(event),
                       event.message.sender.first_name, event, Names.extract, custom_file_name)
    ps.extract_maps = [f"0:{s}" for s in selected]
    ps.move_send_files(temp_ps.send_files)
    try:
        rmtree(temp_ps.dir)
    except Exception:
        pass

    final_task = {"process_status": ps, "functions": []}
    await submit_task(final_task)
    await update_status_message(event)


# ═══════════════════════════════════════════════════════════════════════
#  /mediainfo
# ═══════════════════════════════════════════════════════════════════════

@TELETHON_CLIENT.on(events.NewMessage(incoming=True, pattern=command("mediainfo")))
async def _media_info(event):
    if not await vip_check(event):
        return
    user_id = event.message.sender.id
    chat_id = event.message.chat.id
    if user_id not in get_data():
        await new_user(user_id, SAVE_TO_DATABASE)

    link, _ = await get_link(event)
    video_event_for_task = None

    if link == "invalid":
        await safe_reply(event, "❗ Tautan tidak valid.")
        return
    if not link:
        try:
            async with event.client.conversation(chat_id, timeout=120) as conv:
                await conv.send_message("Kirim berkas media atau URL untuk analisis.")
                resp = await conv.get_response()
                link = resp if (resp.media and resp.media.document) else (
                    resp.text if resp.text.startswith("http") else None)
                if not link:
                    await conv.send_message("Input tidak valid. Dibatalkan.")
                    return
        except asyncio.TimeoutError:
            await safe_reply(event, "⏱ Waktu habis.")
            return

    video_event_for_task = link
    dling_msg = await event.reply("🔽 Mengunduh berkas...")

    async def _download_temp():
        from bot_helper.Others.Names import Names as N_
        temp_ps = ProcessStatus(user_id, chat_id, get_username(event),
                                event.message.sender.first_name, event, N_.pre_download)
        funcs   = ([["Aria", Aria2.add_aria2c_download,
                     [link, temp_ps, False, False, False, False]]]
                   if isinstance(link, str) else [["TG", [video_event_for_task]]])
        await add_task({"process_status": temp_ps, "functions": funcs})
        while any(t["process_status"].process_id == temp_ps.process_id for t in working_task):
            await asyncio.sleep(2)
        return (temp_ps.send_files[-1] if temp_ps.send_files else None), temp_ps.dir

    input_file, temp_dir = await _download_temp()
    if not input_file or not exists(input_file):
        await dling_msg.edit("❌ Gagal mengunduh berkas.")
        if temp_dir:
            try:
                rmtree(temp_dir)
            except Exception:
                pass
        return

    await dling_msg.edit("🔍 Menganalisis berkas...")

    try:
        proc = await create_subprocess_exec(
            "ffprobe", "-v", "quiet", "-print_format", "json",
            "-show_format", "-show_streams", "-show_chapters", input_file,
            stdout=asyncioPIPE, stderr=asyncioPIPE,
        )
        stdout, _ = await proc.communicate()
        media_info = json_loads(stdout.decode("utf-8", "replace"))

        fname       = input_file.split("/")[-1]
        fmt         = media_info.get("format", {})
        duration    = float(fmt.get("duration", 0))
        size        = int(fmt.get("size", 0))
        bit_rate    = int(float(fmt.get("bit_rate", 0)))

        txt  = f"❏ **{fname}**\n\n"
        txt += f"├ **Ukuran**: {get_human_size(size)}\n"
        txt += f"├ **Durasi**: {seconds_to_readable_str(int(duration))}\n"
        txt += f"├ **Bitrate**: {int(bit_rate/1000)} kb/s\n"
        txt += f"└ **Wadah**: {fmt.get('format_name','N/A').upper()}\n\n"

        for s in media_info.get("streams", []):
            ct      = s.get("codec_type")
            si      = s.get("index")
            codec   = s.get("codec_name", "N/A")
            lang    = s.get("tags", {}).get("language", "und")
            title_  = s.get("tags", {}).get("title")
            sbr     = int(float(s.get("bit_rate", 0)))
            if ct == "video":
                txt += f"🎬 **Video (#{si})**\n"
                txt += f"├ **Codec**: {codec.upper()}\n"
                txt += f"├ **Resolusi**: {s.get('width')}x{s.get('height')}\n"
                txt += f"├ **Bitrate**: {int(sbr/1000)} kb/s\n"
                txt += f"└ **FPS**: {s.get('r_frame_rate','N/A')}\n\n"
            elif ct == "audio":
                txt += f"🎧 **Audio (#{si})**\n"
                txt += f"├ **Bahasa**: {lang.upper()}\n"
                txt += f"├ **Codec**: {codec.upper()}\n"
                txt += f"├ **Channel**: {s.get('channel_layout','N/A')}\n"
                txt += f"└ **Bitrate**: {int(sbr/1000)} kb/s\n\n"
            elif ct == "subtitle":
                txt += f"📖 **Subtitle (#{si})**\n"
                txt += f"├ **Bahasa**: {lang.upper()}\n"
                if title_:
                    txt += f"├ **Judul**: {title_}\n"
                txt += f"└ **Codec**: {codec.upper()}\n\n"

        for ch in media_info.get("chapters", []):
            s_t = seconds_to_readable_str(int(float(ch.get("start_time", 0))))
            e_t = seconds_to_readable_str(int(float(ch.get("end_time", 0))))
            ct_ = ch.get("tags", {}).get("title", f"Chapter {ch.get('id')}")
            txt += f"🔖 `{s_t}` - `{e_t}`: {ct_}\n"

        if len(txt) > 4096:
            path = f"{temp_dir}/mediainfo.txt"
            with open(path, "w", encoding="utf-8") as f:
                f.write(txt.replace("**", "").replace("`", ""))
            await dling_msg.delete()
            await event.client.send_file(chat_id, path,
                                          caption=f"📄 MediaInfo untuk `{fname}`",
                                          reply_to=event.message.id)
        else:
            await dling_msg.edit(txt, parse_mode="md")

    except Exception as e:
        await dling_msg.edit(f"❌ Error saat analisis: {e}")
        LOGGER.error(f"/mediainfo error: {e}", exc_info=True)
    finally:
        if temp_dir:
            try:
                rmtree(temp_dir)
            except Exception:
                pass
