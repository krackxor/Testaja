"""
╔══════════════════════════════════════════════════════════════════════╗
║    bot_helper/Handlers/vip_handlers.py — v3.2                        ║
║    VIP Management & Trakteer Payment Verification (Aiogram)          ║
╠══════════════════════════════════════════════════════════════════════╣
║  Commands: /verify /myvip /add_vip /delete_vip /view_vip             ║
╠══════════════════════════════════════════════════════════════════════╣
║  CHANGELOG dari versi lama:                                          ║
║  [UX PREMIUM] Menerapkan Auto-Delete agar chat tetap bersih.         ║
║  [UX PREMIUM] Menerapkan Reply Keyboard "❌ Batal" yang konsisten.   ║
║  [UX PREMIUM] Penataan pesan info dengan Box Konfirmasi yang rapi.   ║
║  [FIX HIGH] Menambahkan import 'exists' yang hilang.                 ║
║  [FIX HIGH] Implementasi CMD_SUFFIX pada semua Command filter        ║
║  [NEW] Migrasi total ke Aiogram Router & Message objects             ║
║  [UPDATE] Konsistensi UI, Ikon, Timeout, dan Batal selaras 100%.     ║
╚══════════════════════════════════════════════════════════════════════╝
"""

# ── Standard Library ──────────────────────────────────────────────────
import asyncio
from datetime import datetime, timedelta
from os import remove
from os.path import exists

# ── Third Party ───────────────────────────────────────────────────────
import requests
from aiogram import Router
from aiogram.types import (
    Message, FSInputFile, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
)
from aiogram.filters import Command

# ── Internal ──────────────────────────────────────────────────────────
from bot_helper.Database.DB_Handler import get_db
from bot_helper.Database.User_Data import (
    ensure_user_data_structure, get_data,
    get_fresh_user_data, new_user, saveoptions,
)
from bot_helper.Telegram.Telegram_Client import Telegram
from config.config import Config

from .shared import (
    CMD_SUFFIX, LOGGER, SAVE_TO_DATABASE,
    ask_text_event, owner_checker, wait_for_message,
    safe_reply, user_auth_checker,
)

# Inisialisasi Router Aiogram
router = Router()

# ── Konstanta VIP ─────────────────────────────────────────────────────
VIP_PRICE_PER_MONTH      = 15_000    # Rp
ACTIVATION_WINDOW_HOURS  = 48        # Jam batas aktivasi setelah donasi


# ═══════════════════════════════════════════════════════════════════════
#  HELPERS & UI
# ═══════════════════════════════════════════════════════════════════════

async def _clean_msgs(*msgs):
    """Menghapus pesan untuk menjaga chat tetap rapi."""
    for m in msgs:
        if m:
            try: await m.delete()
            except Exception: pass

def _make_reply_kb(options: list, row_width: int = 2) -> ReplyKeyboardMarkup:
    """Membuat Reply Keyboard dengan mudah."""
    kb = []
    row = []
    for opt in options:
        row.append(KeyboardButton(text=opt))
        if len(row) == row_width:
            kb.append(row)
            row = []
    if row:
        kb.append(row)
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True, one_time_keyboard=True)

def parse_duration(duration_str: str) -> int:
    """Konversi string durasi '30d' / '2m' / '1y' ke hari."""
    s = duration_str.strip().lower()
    try:
        if s.endswith("d"):   return int(s[:-1])
        if s.endswith("m"):   return int(s[:-1]) * 30
        if s.endswith("y"):   return int(s[:-1]) * 365
        if s.isdigit():       return int(s)
    except ValueError:
        pass
    return 30   # default


def _extend_vip(user_id: int, duration_days: int) -> datetime:
    """
    Hitung tanggal kedaluwarsa VIP baru.
    Jika user sudah VIP aktif, tambahkan dari tanggal kedaluwarsa lama.
    """
    start = datetime.now()
    user_data = get_data().get(user_id, {})
    expiry_str = user_data.get("premium_expiry_date")
    if expiry_str:
        try:
            current_expiry = datetime.fromisoformat(str(expiry_str))
            if current_expiry > start:
                start = current_expiry
        except (ValueError, TypeError):
            pass
    return start + timedelta(days=duration_days)


# ═══════════════════════════════════════════════════════════════════════
#  /verify — Verifikasi Pembayaran Trakteer
# ═══════════════════════════════════════════════════════════════════════

@router.message(Command(f"verify{CMD_SUFFIX}"))
async def _verify_payment(message: Message):
    if not await user_auth_checker(message): return
        
    user_id, chat_id = message.from_user.id, message.chat.id
    await ensure_user_data_structure(user_id)

    kb = _make_reply_kb(["❌ Batal"], 1)
    ask_txt = "🎁 **VERIFIKASI TRAKTEER**\n\nSetelah berdonasi di Trakteer, silakan kirimkan (Ketik) **Order ID** Anda di sini:"
    ask_msg = await message.reply(ask_txt, reply_markup=kb)
    
    resp = await wait_for_message(chat_id, user_id, 120)
    await _clean_msgs(ask_msg, resp)

    if not resp:
        return await message.answer("❌ Waktu habis. Dibatalkan.", reply_markup=ReplyKeyboardRemove())
        
    if "batal" in (resp.text or "").lower():
        return await message.answer("❌ Dibatalkan.", reply_markup=ReplyKeyboardRemove())

    order_id = str(resp.text).strip()
    api_key  = Config.TRAKTEER_API_KEY

    if not api_key:
        return await message.answer("❌ Fitur verifikasi belum dikonfigurasi oleh pemilik bot.", reply_markup=ReplyKeyboardRemove())

    all_data    = get_data()
    claimed_ids = all_data.get("claimed_order_ids", [])
    if order_id in claimed_ids:
        return await message.answer("❌ Order ID ini sudah pernah diklaim sebelumnya.", reply_markup=ReplyKeyboardRemove())

    verif_msg = await message.answer("🔎 Sedang memverifikasi Order ID ke Trakteer...", reply_markup=ReplyKeyboardRemove())
    try:
        resp = await asyncio.to_thread(
            requests.get,
            "https://api.trakteer.id/v1/public/supports",
            headers={"Accept": "application/json", "key": api_key},
            params={"include": "order_id"},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
    except requests.exceptions.HTTPError as e:
        code = e.response.status_code
        msg_text = "❌ API Key Trakteer salah (Unauthorized)." if code == 401 else f"❌ HTTP Error {code}."
        LOGGER.error(f"Trakteer HTTP error: {e}")
        return await verif_msg.edit_text(msg_text)
    except requests.exceptions.RequestException as e:
        LOGGER.error(f"Trakteer connection error: {e}")
        return await verif_msg.edit_text(f"❌ Gagal terhubung ke Trakteer: `{e}`")

    if data.get("status") != "success":
        return await verif_msg.edit_text(f"❌ Error dari Trakteer: `{data.get('message', 'Unknown')}`")

    # Cari transaksi yang cocok
    target = None
    for support in data.get("result", {}).get("data", []):
        if str(support.get("order_id", "")).strip() == order_id:
            target = support
            break

    if not target:
        return await verif_msg.edit_text("❌ Order ID tidak ditemukan di Trakteer. Pastikan ID diketik dengan benar.")

    # Validasi status pembayaran
    if target.get("status", "success") != "success":
        return await verif_msg.edit_text(f"❌ Status pembayaran Order ID ini: `{target.get('status')}`")

    # Validasi tanggal (batas aktivasi)
    try:
        trx_date = datetime.strptime(target.get("updated_at", ""), "%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        return await verif_msg.edit_text("❌ Format tanggal tidak valid dari Trakteer. Hubungi admin.")

    if datetime.now() > trx_date + timedelta(hours=ACTIVATION_WINDOW_HOURS):
        days = int(ACTIVATION_WINDOW_HOURS / 24)
        return await verif_msg.edit_text(f"❌ Order ID hangus. Tidak diklaim dalam **{days} hari** setelah donasi.")

    # Hitung durasi
    amount = target.get("amount", 0)
    if amount < VIP_PRICE_PER_MONTH:
        return await verif_msg.edit_text(f"❌ Jumlah donasi (Rp {amount:,}) kurang dari harga minimum (Rp {VIP_PRICE_PER_MONTH:,}/bulan).")

    months        = int(amount // VIP_PRICE_PER_MONTH)
    duration_days = months * 30
    new_expiry    = _extend_vip(user_id, duration_days)

    await saveoptions(user_id, "premium_expiry_date", new_expiry.isoformat(), SAVE_TO_DATABASE)

    # Simpan claimed_order_id
    claimed_ids.append(order_id)
    all_data["claimed_order_ids"] = claimed_ids
    if Config.SAVE_TO_DATABASE:
        db_instance = get_db()
        if db_instance:
            await db_instance.save_data(all_data)

    expiry_fmt = new_expiry.strftime("%d %B %Y, %H:%M WIB")
    box_txt = (
        f"✅ **VERIFIKASI BERHASIL!**\n\n"
        f"🎉 Terima kasih atas dukungan Anda!\n"
        f"├ Tambahan Waktu: **{months} Bulan** (`{duration_days} Hari`)\n"
        f"└ Berakhir Pada: **{expiry_fmt}**"
    )
    await verif_msg.edit_text(box_txt)


# ═══════════════════════════════════════════════════════════════════════
#  /myvip — Cek Status VIP Sendiri
# ═══════════════════════════════════════════════════════════════════════

@router.message(Command(f"myvip{CMD_SUFFIX}"))
async def _my_vip_status(message: Message):
    user_id = message.from_user.id
    await ensure_user_data_structure(user_id)
    user_data  = await get_fresh_user_data(user_id)
    expiry_str = user_data.get("premium_expiry_date")
    is_vip     = False
    expiry     = None

    if expiry_str:
        try:
            expiry = datetime.fromisoformat(str(expiry_str))
            if expiry > datetime.now():
                is_vip = True
        except (ValueError, TypeError):
            pass

    if is_vip:
        remaining = expiry - datetime.now()
        days  = remaining.days
        hours = remaining.seconds // 3600
        await message.reply(
            "╭─── • **Kartu Anggota VIP** • ───╮\n"
            "│\n"
            f"├  **Status:** `Premium (VIP) ✅`\n"
            f"├  **Aktif Hingga:** `{expiry.strftime('%d %B %Y, %H:%M WIB')}`\n"
            f"├  **Sisa Waktu:** `{days} hari, {hours} jam`\n"
            "│\n"
            "╰─╼ • Nikmati semua fitur premium • ╾─╯"
        )
    else:
        await message.reply(
            "╭─── • **Status Keanggotaan** • ───╮\n"
            "│\n"
            "├  **Status:** `Pengguna Reguler`\n"
            "│\n"
            "├  Ingin akses penuh? Lakukan donasi\n"
            f"│  dan gunakan `/verify{CMD_SUFFIX}` untuk upgrade VIP!\n"
            "│\n"
            "╰─╼ • Upgrade untuk fitur premium • ╾─╯"
        )


# ═══════════════════════════════════════════════════════════════════════
#  /add_vip — Tambah VIP Manual (Owner)
# ═══════════════════════════════════════════════════════════════════════

@router.message(Command(f"add_vip{CMD_SUFFIX}"))
async def _add_vip_manual(message: Message):
    if not owner_checker(message): return
        
    parts        = (message.text or "").split()
    target_uid   = None
    duration_str = "30d"

    try:
        if message.reply_to_message and message.reply_to_message.from_user:
            target_uid = message.reply_to_message.from_user.id
            if len(parts) > 1: duration_str = parts[1]
        elif len(parts) > 1 and parts[1].isdigit():
            target_uid = int(parts[1])
            if len(parts) > 2: duration_str = parts[2]
        else:
            await safe_reply(message,
                "❌ **Format tidak valid:**\n"
                f"`/add_vip{CMD_SUFFIX} [durasi]` (balas pesan) — contoh: `/add_vip{CMD_SUFFIX} 2m`\n"
                f"`/add_vip{CMD_SUFFIX} <user_id> [durasi]` — contoh: `/add_vip{CMD_SUFFIX} 12345 1y`\n\n"
                "Durasi: `30d`, `2m`, `1y`, atau angka hari"
            )
            return

        duration_days = parse_duration(duration_str)
        await ensure_user_data_structure(target_uid)

        user_data      = get_data().get(target_uid, {})
        total_duration = user_data.get("total_vip_duration", 0) + duration_days
        new_expiry     = _extend_vip(target_uid, duration_days)

        await saveoptions(target_uid, "premium_expiry_date", new_expiry.isoformat(), SAVE_TO_DATABASE)
        await saveoptions(target_uid, "total_vip_duration",  total_duration,         SAVE_TO_DATABASE)

        await safe_reply(message,
            f"✅ **VIP MANUAL BERHASIL DITAMBAHKAN**\n\n"
            f"├ User ID: `{target_uid}`\n"
            f"├ Durasi Baru: **{duration_days} hari**\n"
            f"└ Aktif Hingga: **{new_expiry.strftime('%d %B %Y, %H:%M WIB')}**"
        )
    except Exception as e:
        LOGGER.error(f"/add_vip error: {e}", exc_info=True)
        await safe_reply(message, f"❌ Terjadi kesalahan: `{e}`")


# ═══════════════════════════════════════════════════════════════════════
#  /delete_vip — Hapus VIP (Owner)
# ═══════════════════════════════════════════════════════════════════════

@router.message(Command(f"delete_vip{CMD_SUFFIX}"))
async def _delete_vip_manual(message: Message):
    if not owner_checker(message): return
        
    target_uid = None
    parts      = (message.text or "").split()
    try:
        if message.reply_to_message and message.reply_to_message.from_user:
            target_uid = message.reply_to_message.from_user.id
        elif len(parts) > 1 and parts[1].isdigit():
            target_uid = int(parts[1])
        else:
            return await safe_reply(message, f"❌ Format: `/delete_vip{CMD_SUFFIX} <user_id>` atau balas pesan.")

        await ensure_user_data_structure(target_uid)
        if not get_data().get(target_uid, {}).get("premium_expiry_date"):
            return await safe_reply(message, f"❌ User `{target_uid}` tidak memiliki VIP aktif.")

        await saveoptions(target_uid, "premium_expiry_date", None, SAVE_TO_DATABASE)
        await saveoptions(target_uid, "total_vip_duration",  0,    SAVE_TO_DATABASE)
        await safe_reply(message, f"✅ VIP user `{target_uid}` berhasil dihapus paksa.")

    except Exception as e:
        LOGGER.error(f"/delete_vip error: {e}", exc_info=True)
        await safe_reply(message, f"❌ Terjadi kesalahan: `{e}`")


# ═══════════════════════════════════════════════════════════════════════
#  /view_vip — Lihat Daftar VIP (Owner)
# ═══════════════════════════════════════════════════════════════════════

@router.message(Command(f"view_vip{CMD_SUFFIX}"))
async def _view_vip_list(message: Message):
    if not owner_checker(message): return
        
    path = "vip_list.txt"
    try:
        all_data   = get_data()
        now        = datetime.now()
        vip_list   = []

        for uid, udata in all_data.items():
            if not isinstance(uid, int):
                continue
            expiry_str = udata.get("premium_expiry_date")
            if not expiry_str:
                continue
            try:
                expiry = datetime.fromisoformat(str(expiry_str))
                if expiry > now:
                    total_dur = udata.get("total_vip_duration", 0)
                    vip_list.append((uid, expiry, total_dur))
            except (ValueError, TypeError):
                continue

        if not vip_list:
            return await safe_reply(message, "ℹ️ Tidak ada pengguna VIP aktif saat ini.")

        vip_list.sort(key=lambda x: x[1])   # sort by expiry (terdekat dulu)

        lines = ["**📋 Daftar Pengguna VIP Aktif**\n"]
        for i, (uid, expiry, total_dur) in enumerate(vip_list, 1):
            days_left  = (expiry - now).days
            expiry_fmt = expiry.strftime("%d %b %Y")
            lines.append(
                f"\n**{i}.** `{uid}`\n"
                f"   ├ Berakhir: `{expiry_fmt}`\n"
                f"   ├ Total: `{total_dur} hari`\n"
                f"   └ Sisa: `{days_left} hari`"
            )

        text_msg = "".join(lines)

        if len(text_msg) > 4096:
            with open(path, "w", encoding="utf-8") as f:
                plain = text_msg.replace("**", "").replace("`", "")
                f.write(plain)
            await message.reply_document(document=FSInputFile(path), caption="Daftar VIP terlalu panjang, dikirim sebagai file.")
        else:
            await message.reply(text_msg)

    except Exception as e:
        LOGGER.error(f"/view_vip error: {e}", exc_info=True)
        await safe_reply(message, f"❌ Terjadi kesalahan: `{e}`")
    finally:
        if exists(path):
            remove(path)
