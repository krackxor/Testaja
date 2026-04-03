"""
╔══════════════════════════════════════════════════════════════════════╗
║       bot_helper/Handlers/vip_handlers.py — v3.1                     ║
║       VIP Management & Trakteer Payment Verification (Aiogram)       ║
╠══════════════════════════════════════════════════════════════════════╣
║  Commands: /verify /myvip /add_vip /delete_vip /view_vip             ║
╠══════════════════════════════════════════════════════════════════════╣
║  CHANGELOG dari versi lama:                                          ║
║  [NEW] Migrasi total ke Aiogram Router & Message objects             ║
║  [FIX] event.reply_to_msg_id diubah ke message.reply_to_message      ║
║  [FIX] event.edit() diubah menjadi message.edit_text()               ║
║  [FIX] Pengiriman dokumen lokal dengan FSInputFile                   ║
╚══════════════════════════════════════════════════════════════════════╝
"""

# ── Standard Library ──────────────────────────────────────────────────
import asyncio
from datetime import datetime, timedelta
from os import remove

# ── Third Party ───────────────────────────────────────────────────────
import requests
from aiogram import Router
from aiogram.types import Message, FSInputFile
from aiogram.filters import Command

# ── Internal ──────────────────────────────────────────────────────────
from bot_helper.Database.DB_Handler import get_db
from bot_helper.Database.User_Data import (
    ensure_user_data_structure, get_data,
    get_fresh_user_data, new_user, saveoptions,
)
from bot_helper.Telegram.Telegram_Client import Telegram
from config.config import Config

from bot.shared import (
    LOGGER, SAVE_TO_DATABASE,
    ask_text_event, owner_checker,
    safe_reply, user_auth_checker,
)

# Inisialisasi Router Aiogram
router = Router()

# ── Konstanta VIP ─────────────────────────────────────────────────────
VIP_PRICE_PER_MONTH      = 15_000    # Rp
ACTIVATION_WINDOW_HOURS  = 48        # Jam batas aktivasi setelah donasi


# ═══════════════════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════════════════

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

@router.message(Command("verify"))
async def _verify_payment(message: Message):
    if not await user_auth_checker(message):
        return
        
    user_id = message.from_user.id
    chat_id = message.chat.id

    await ensure_user_data_structure(user_id)

    order_id_msg = await ask_text_event(
        chat_id, user_id, message, 120,
        "Setelah donasi di Trakteer, masukkan **Order ID** Anda untuk verifikasi.",
    )
    if not order_id_msg:
        return

    order_id = str(order_id_msg.text).strip()
    api_key  = Config.TRAKTEER_API_KEY

    if not api_key:
        await safe_reply(message, "❗ Fitur verifikasi belum dikonfigurasi oleh pemilik bot.")
        return

    # Cek apakah order_id sudah diklaim
    all_data    = get_data()
    claimed_ids = all_data.get("claimed_order_ids", [])
    if order_id in claimed_ids:
        await safe_reply(message, "❌ Order ID ini sudah pernah digunakan.")
        return

    verif_msg = await message.reply("🔎 Memverifikasi Order ID, harap tunggu...")
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
        msg_text = "❌ API Key Trakteer salah." if code == 401 else f"❌ HTTP Error {code}."
        await verif_msg.edit_text(msg_text)
        LOGGER.error(f"Trakteer HTTP error: {e}")
        return
    except requests.exceptions.RequestException as e:
        await verif_msg.edit_text(f"❌ Gagal terhubung ke Trakteer: {e}")
        LOGGER.error(f"Trakteer connection error: {e}")
        return

    if data.get("status") != "success":
        await verif_msg.edit_text(f"❌ Error dari Trakteer: {data.get('message', 'Unknown')}")
        return

    # Cari transaksi yang cocok
    target = None
    for support in data.get("result", {}).get("data", []):
        if str(support.get("order_id", "")).strip() == order_id:
            target = support
            break

    if not target:
        await verif_msg.edit_text("❌ Order ID tidak ditemukan. Pastikan ID sudah benar.")
        return

    # Validasi status pembayaran
    if target.get("status", "success") != "success":
        await verif_msg.edit_text(f"❌ Status pembayaran: `{target.get('status')}`")
        return

    # Validasi tanggal (batas aktivasi)
    try:
        trx_date = datetime.strptime(target.get("updated_at", ""), "%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        await verif_msg.edit_text("❌ Format tanggal tidak valid. Hubungi admin.")
        return

    if datetime.now() > trx_date + timedelta(hours=ACTIVATION_WINDOW_HOURS):
        days = int(ACTIVATION_WINDOW_HOURS / 24)
        await verif_msg.edit_text(
            f"❌ Order ID sudah hangus — tidak diaktifkan dalam **{days} hari** setelah donasi."
        )
        return

    # Hitung durasi
    amount = target.get("amount", 0)
    if amount < VIP_PRICE_PER_MONTH:
        await verif_msg.edit_text(
            f"❌ Jumlah donasi kurang dari minimum 1 bulan (Rp {VIP_PRICE_PER_MONTH:,})."
        )
        return

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
    await verif_msg.edit_text(
        f"✅ **Verifikasi Berhasil!**\n\n"
        f"Anda mendapatkan **{months} bulan** akses VIP.\n"
        f"Status aktif hingga: **{expiry_fmt}**"
    )


# ═══════════════════════════════════════════════════════════════════════
#  /myvip — Cek Status VIP Sendiri
# ═══════════════════════════════════════════════════════════════════════

@router.message(Command("myvip"))
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
            "│  dan gunakan `/verify` untuk upgrade VIP!\n"
            "│\n"
            "╰─╼ • Upgrade untuk fitur premium • ╾─╯"
        )


# ═══════════════════════════════════════════════════════════════════════
#  /add_vip — Tambah VIP Manual (Owner)
# ═══════════════════════════════════════════════════════════════════════

@router.message(Command("add_vip"))
async def _add_vip_manual(message: Message):
    if not owner_checker(message):
        return
        
    parts         = (message.text or "").split()
    target_uid    = None
    duration_str  = "30d"

    try:
        if message.reply_to_message and message.reply_to_message.from_user:
            target_uid = message.reply_to_message.from_user.id
            if len(parts) > 1:
                duration_str = parts[1]
        elif len(parts) > 1 and parts[1].isdigit():
            target_uid = int(parts[1])
            if len(parts) > 2:
                duration_str = parts[2]
        else:
            await safe_reply(message,
                "**Format:**\n"
                "`/add_vip [durasi]` (balas pesan) — contoh: `/add_vip 2m`\n"
                "`/add_vip <user_id> [durasi]` — contoh: `/add_vip 12345 1y`\n\n"
                "Durasi: `30d`, `2m`, `1y`, atau angka hari"
            )
            return

        duration_days = parse_duration(duration_str)
        await ensure_user_data_structure(target_uid)

        user_data      = get_data().get(target_uid, {})
        total_duration = user_data.get("total_vip_duration", 0) + duration_days
        new_expiry     = _extend_vip(target_uid, duration_days)

        await saveoptions(target_uid, "premium_expiry_date", new_expiry.isoformat(), SAVE_TO_DATABASE)
        await saveoptions(target_uid, "total_vip_duration",  total_duration,          SAVE_TO_DATABASE)

        await safe_reply(message,
            f"✅ **VIP Berhasil Ditambahkan!**\n\n"
            f"User: `{target_uid}`\n"
            f"Durasi: **{duration_days} hari**\n"
            f"Aktif hingga: **{new_expiry.strftime('%d %B %Y, %H:%M WIB')}**"
        )
    except Exception as e:
        await safe_reply(message, f"❌ Terjadi kesalahan: {e}")
        LOGGER.error(f"/add_vip error: {e}", exc_info=True)


# ═══════════════════════════════════════════════════════════════════════
#  /delete_vip — Hapus VIP (Owner)
# ═══════════════════════════════════════════════════════════════════════

@router.message(Command("delete_vip"))
async def _delete_vip_manual(message: Message):
    if not owner_checker(message):
        return
        
    target_uid = None
    parts      = (message.text or "").split()
    try:
        if message.reply_to_message and message.reply_to_message.from_user:
            target_uid = message.reply_to_message.from_user.id
        elif len(parts) > 1 and parts[1].isdigit():
            target_uid = int(parts[1])
        else:
            await safe_reply(message, "❗ Format: `/delete_vip <user_id>` atau balas pesan.")
            return

        await ensure_user_data_structure(target_uid)
        if not get_data().get(target_uid, {}).get("premium_expiry_date"):
            await safe_reply(message, f"❗ User `{target_uid}` tidak memiliki VIP aktif.")
            return

        await saveoptions(target_uid, "premium_expiry_date", None, SAVE_TO_DATABASE)
        await saveoptions(target_uid, "total_vip_duration",  0,    SAVE_TO_DATABASE)
        await safe_reply(message, f"✅ VIP user `{target_uid}` berhasil dihapus.")

    except Exception as e:
        await safe_reply(message, f"❌ Terjadi kesalahan: {e}")
        LOGGER.error(f"/delete_vip error: {e}", exc_info=True)


# ═══════════════════════════════════════════════════════════════════════
#  /view_vip — Lihat Daftar VIP (Owner)
# ═══════════════════════════════════════════════════════════════════════

@router.message(Command("view_vip"))
async def _view_vip_list(message: Message):
    if not owner_checker(message):
        return
        
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
            await safe_reply(message, "ℹ️ Tidak ada pengguna VIP aktif saat ini.")
            return

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
            path = "vip_list.txt"
            with open(path, "w", encoding="utf-8") as f:
                plain = text_msg.replace("**", "").replace("`", "")
                f.write(plain)
            await message.reply_document(document=FSInputFile(path), caption="Daftar VIP terlalu panjang, dikirim sebagai file.")
            remove(path)
        else:
            await message.reply(text_msg)

    except Exception as e:
        await safe_reply(message, f"❌ Terjadi kesalahan: {e}")
        LOGGER.error(f"/view_vip error: {e}", exc_info=True)
