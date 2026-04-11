"""
╔══════════════════════════════════════════════════════════════════════╗
║    bot_helper/Handlers/vip_handlers.py — v5.1 (PAY-AS-YOU-GO FINAL)  ║
║    Sistem Top-Up Poin & Trakteer Payment Verification                ║
╠══════════════════════════════════════════════════════════════════════╣
║  Commands: /verify /myvip /history /add_vip /delete_vip /view_vip    ║
╠══════════════════════════════════════════════════════════════════════╣
║  CHANGELOG v5.1:                                                     ║
║  [NEW] Merombak logika dari "Sistem Hari/Bulan" menjadi "Poin".      ║
║  [NEW] 1 Rupiah Donasi = 1 Poin (Otomatis deteksi dari Trakteer).    ║
║  [NEW] Menambahkan perintah /history untuk melihat riwayat mutasi.   ║
║  [FIX] Command admin diubah agar menambah/mengurangi Poin.           ║
║  [FIX] Aman dari manipulasi data (Thread-Safe integration).          ║
╚══════════════════════════════════════════════════════════════════════╝
"""

# ── Standard Library ──────────────────────────────────────────────────
import asyncio
from datetime import datetime, timedelta
from os import remove
from os.path import exists

# ── Third Party ───────────────────────────────────────────────────────
import aiohttp
from aiogram import Router
from aiogram.types import (
    Message, FSInputFile, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
)
from aiogram.filters import Command

# ── Internal ──────────────────────────────────────────────────────────
from bot_helper.Database.DB_Handler import get_db
from bot_helper.Database.User_Data import (
    ensure_user_data_structure, get_data,
    get_user_balance, add_user_balance, deduct_user_balance
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

# ── Konstanta Poin ────────────────────────────────────────────────────
ACTIVATION_WINDOW_HOURS  = 48        # Jam batas aktivasi setelah donasi
MINIMUM_TOPUP_RP         = 5_000     # Minimal Top-up Rp 5.000


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
    """Membuat Reply Keyboard dengan warna Native Telegram."""
    kb = []
    row = []
    for opt in options:
        if "Batal" in opt or "❌" in opt:
            btn_style = "danger"
        elif "Ya" in opt or "✅" in opt:
            btn_style = "success"
        else:
            btn_style = "primary"
            
        row.append(KeyboardButton(text=opt, style=btn_style))
        
        if len(row) == row_width:
            kb.append(row)
            row = []
    if row:
        kb.append(row)
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True, one_time_keyboard=True)


# ═══════════════════════════════════════════════════════════════════════
#  /verify — Verifikasi Pembayaran Trakteer (Konversi ke POIN)
# ═══════════════════════════════════════════════════════════════════════

@router.message(Command(f"verify{CMD_SUFFIX}"))
async def _verify_payment(message: Message):
    if not await user_auth_checker(message): return
        
    user_id, chat_id = message.from_user.id, message.chat.id
    await ensure_user_data_structure(user_id)

    kb = _make_reply_kb(["❌ Batal"], 1)
    ask_txt = "💳 **VERIFIKASI TOP-UP (TRAKTEER)**\n\nSilakan kirimkan (Ketik) **Order ID** Anda setelah berdonasi:"
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

    verif_msg = await message.answer("⏳ 🔎 Sedang memverifikasi Order ID ke Trakteer...", reply_markup=ReplyKeyboardRemove())
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://api.trakteer.id/v1/public/supports",
                headers={"Accept": "application/json", "key": api_key},
                params={"include": "order_id"}, 
                timeout=15
            ) as api_resp:
                
                if api_resp.status == 401:
                    return await verif_msg.edit_text("❌ API Key Trakteer salah (Unauthorized).")
                elif api_resp.status != 200:
                    return await verif_msg.edit_text(f"❌ HTTP Error {api_resp.status}.")
                    
                data = await api_resp.json()
                
    except asyncio.TimeoutError:
        return await verif_msg.edit_text("❌ Gagal terhubung: Trakteer Server Timeout.")
    except Exception as e:
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
        return await verif_msg.edit_text("❌ Order ID tidak ditemukan di Trakteer. (Pastikan Order ID benar).")

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

    # Hitung Poin (Rp 1 = 1 Poin)
    amount_rp = int(target.get("amount", 0))
    if amount_rp < MINIMUM_TOPUP_RP:
        return await verif_msg.edit_text(f"❌ Jumlah Top-up (Rp {amount_rp:,}) kurang dari minimum (Rp {MINIMUM_TOPUP_RP:,}).")

    # Tambahkan Saldo ke Database
    await add_user_balance(user_id, amount_rp, SAVE_TO_DATABASE)
    new_balance = get_user_balance(user_id)

    # Simpan claimed_order_id
    claimed_ids.append(order_id)
    all_data["claimed_order_ids"] = claimed_ids
    if Config.SAVE_TO_DATABASE:
        db_instance = get_db()
        if db_instance:
            await db_instance.save_data(all_data)

    box_txt = (
        f"✅ 💎 **TOP-UP POIN BERHASIL!**\n\n"
        f"🎉 Terima kasih atas dukungan Anda!\n"
        f"├ Nominal Donasi: **Rp {amount_rp:,}**\n"
        f"├ Saldo Didapat: **+{amount_rp:,} Poin**\n"
        f"└ Total Saldo Anda: **{new_balance:,} Poin**"
    )
    await verif_msg.edit_text(box_txt)


# ═══════════════════════════════════════════════════════════════════════
#  /myvip — Cek Saldo Poin (Dompet)
# ═══════════════════════════════════════════════════════════════════════

@router.message(Command(f"myvip{CMD_SUFFIX}"))
async def _my_vip_status(message: Message):
    user_id = message.from_user.id
    await ensure_user_data_structure(user_id)
    
    current_balance = get_user_balance(user_id)

    await message.reply(
        "╭─── • **DOMPET STUDIO KHOIRUL** • ───╮\n"
        "│\n"
        f"├  **Status:** `Premium Pay-As-You-Go 🟢`\n"
        f"├  **Sisa Saldo:** `{current_balance:,} Poin`\n"
        "│\n"
        "├  Saldo Poin tidak akan pernah hangus\n"
        f"│  (Gunakan `/verify{CMD_SUFFIX}` untuk Top-up)\n"
        "│\n"
        "╰─╼ • Nikmati semua fitur premium • ╾─╯"
    )


# ═══════════════════════════════════════════════════════════════════════
#  /history — Cek Mutasi & Riwayat Pemakaian Poin
# ═══════════════════════════════════════════════════════════════════════

@router.message(Command(f"history{CMD_SUFFIX}"))
async def _my_usage_history(message: Message):
    user_id = message.from_user.id
    await ensure_user_data_structure(user_id)
    
    all_data = get_data()
    user_data = all_data.get(user_id, {})
    
    history = user_data.get("usage_history", [])
    current_balance = user_data.get("balance_points", 0)
    
    if not history:
        return await message.reply(
            "📜 **RIWAYAT PEMAKAIAN POIN**\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "Belum ada catatan transaksi.\n"
            f"💳 Saldo Anda saat ini: `{current_balance:,} Poin`"
        )
        
    lines = [
        "📜 **RIWAYAT PEMAKAIAN (MUTASI)**",
        "━━━━━━━━━━━━━━━━━━━━\n"
    ]
    
    for idx, record in enumerate(history, 1):
        date = record.get("date", "Unknown")
        action = record.get("action", "SYSTEM")
        cost = record.get("cost", 0)
        lines.append(f"**{idx}. {action}**")
        lines.append(f"   └ 🗓 `{date}` | 💎 `- {cost:,} Poin`")
        
    lines.append("\n━━━━━━━━━━━━━━━━━━━━")
    lines.append(f"💳 **Sisa Saldo:** `{current_balance:,} Poin`")
    
    await message.reply("\n".join(lines))


# ═══════════════════════════════════════════════════════════════════════
#  /add_vip — Tambah Poin Manual (Owner)
# ═══════════════════════════════════════════════════════════════════════

@router.message(Command(f"add_vip{CMD_SUFFIX}"))
async def _add_vip_manual(message: Message):
    if not owner_checker(message): return
        
    parts        = (message.text or "").split()
    target_uid   = None
    amount_add   = 0

    try:
        if message.reply_to_message and message.reply_to_message.from_user:
            target_uid = message.reply_to_message.from_user.id
            if len(parts) > 1 and parts[1].isdigit(): 
                amount_add = int(parts[1])
        elif len(parts) > 2 and parts[1].isdigit() and parts[2].isdigit():
            target_uid = int(parts[1])
            amount_add = int(parts[2])
        else:
            await safe_reply(message,
                "❌ **Format tidak valid:**\n"
                f"`/add_vip{CMD_SUFFIX} [jumlah_poin]` (balas pesan) — contoh: `/add_vip{CMD_SUFFIX} 50000`\n"
                f"`/add_vip{CMD_SUFFIX} <user_id> [jumlah_poin]` — contoh: `/add_vip{CMD_SUFFIX} 12345 50000`\n"
            )
            return

        if amount_add <= 0:
            return await safe_reply(message, "❌ Jumlah Poin harus lebih dari 0.")

        await ensure_user_data_structure(target_uid)
        await add_user_balance(target_uid, amount_add, SAVE_TO_DATABASE)
        new_balance = get_user_balance(target_uid)

        await safe_reply(message,
            f"✅ ➕ 💎 **POIN MANUAL DITAMBAHKAN**\n\n"
            f"├ User ID: `{target_uid}`\n"
            f"├ Poin Ditambah: **+{amount_add:,}**\n"
            f"└ Saldo Sekarang: **{new_balance:,} Poin**"
        )
    except Exception as e:
        LOGGER.error(f"/add_vip error: {e}", exc_info=True)
        await safe_reply(message, f"❌ Terjadi kesalahan: `{e}`")


# ═══════════════════════════════════════════════════════════════════════
#  /delete_vip — Kurangi Poin / Reset Poin (Owner)
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
            return await safe_reply(message, f"❌ Format: `/delete_vip{CMD_SUFFIX} <user_id>` atau balas pesan (Ini akan MERESET saldo jadi 0).")

        await ensure_user_data_structure(target_uid)
        current = get_user_balance(target_uid)
        
        # Potong habis saldonya
        await deduct_user_balance(target_uid, current, SAVE_TO_DATABASE)
        
        await safe_reply(message, f"✅ ➖ Saldo Poin user `{target_uid}` berhasil di-reset menjadi 0.")

    except Exception as e:
        LOGGER.error(f"/delete_vip error: {e}", exc_info=True)
        await safe_reply(message, f"❌ Terjadi kesalahan: `{e}`")


# ═══════════════════════════════════════════════════════════════════════
#  /view_vip — Lihat Daftar User & Saldo Poin (Owner)
# ═══════════════════════════════════════════════════════════════════════

@router.message(Command(f"view_vip{CMD_SUFFIX}"))
async def _view_vip_list(message: Message):
    if not owner_checker(message): return
        
    path = "poin_list.txt"
    try:
        all_data   = get_data()
        point_list = []

        # Tarik semua user yang punya saldo > 0
        for uid, udata in list(all_data.items()):
            if not isinstance(uid, int):
                continue
            balance = udata.get("balance_points", 0)
            if balance > 0:
                point_list.append((uid, balance))

        if not point_list:
            return await safe_reply(message, "ℹ️ Belum ada pengguna yang memiliki Saldo Poin saat ini.")

        # Urutkan berdasarkan Saldo Terbanyak (Top Spender/Holder)
        point_list.sort(key=lambda x: x[1], reverse=True)

        lines = ["**💎 Daftar Pengguna (Berdasarkan Saldo Poin)**\n"]
        for i, (uid, balance) in enumerate(point_list, 1):
            lines.append(
                f"\n**{i}.** `{uid}`\n"
                f"   └ Saldo: `{balance:,} Poin`"
            )

        text_msg = "".join(lines)

        if len(text_msg) > 4096:
            with open(path, "w", encoding="utf-8") as f:
                plain = text_msg.replace("**", "").replace("`", "")
                f.write(plain)
            await message.reply_document(document=FSInputFile(path), caption="Daftar pengguna terlalu panjang, dikirim sebagai file.")
        else:
            await message.reply(text_msg)

    except Exception as e:
        LOGGER.error(f"/view_vip error: {e}", exc_info=True)
        await safe_reply(message, f"❌ Terjadi kesalahan: `{e}`")
    finally:
        if exists(path):
            remove(path)
