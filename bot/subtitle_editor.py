"""
╔══════════════════════════════════════════════════════════════════════╗
║                bot/subtitle_editor.py — v1.0 (PREMIUM)               ║
║      Subtitle Editor: Resync, Edit, & Translate (Studio Khoirul)     ║
╠══════════════════════════════════════════════════════════════════════╣
║  CHANGELOG v1.0:                                                     ║
║  [UX PREMIUM] Implementasi API Warna Tombol Native Telegram 9.4+     ║
║  [UX PREMIUM] Pagination Sistem Fokus (Max 5 baris agar rapi)        ║
║  [UX PREMIUM] Integrasi Pencarian Teks & Resync Cepat (+/- 0.5s)     ║
║  [FIX HIGH] Menggunakan Motor (Async MongoDB) untuk performa tinggi. ║
╚══════════════════════════════════════════════════════════════════════╝
"""

import asyncio
from aiogram import Router, F
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardRemove
)
from aiogram.filters import Command
from aiogram.exceptions import TelegramBadRequest

from config.config import Config
from bot_helper.Database.User_Data import get_data, saveoptions
# Asumsi helper ini sudah Anda buat di bot_helper/Others/
from bot_helper.Others.SrtParser import parse_srt_to_db
from bot_helper.Others.SrtCompiler import compile_db_to_srt
from bot.shared import wait_for_message, CMD_SUFFIX, LOGGER

router = Router()

# ═══════════════════════════════════════════════════════════════════════
#  UI GENERATORS
# ═══════════════════════════════════════════════════════════════════════

def get_editor_kb(lines, current_page, total_pages, user_id):
    """Layout Utama Editor: Daftar Baris & Navigasi."""
    kb = []
    
    # 1. Baris Subtitle (Focus Mode)
    for line in lines:
        preview = line['text'][:35] + "..." if len(line['text']) > 35 else line['text']
        kb.append([
            InlineKeyboardButton(
                text=f"#{line['index']} | {preview}", 
                callback_data=f"sub_focus_{user_id}_{line['index']}"
            )
        ])
    
    # 2. Navigasi Halaman
    nav_row = []
    if current_page > 1:
        nav_row.append(InlineKeyboardButton(text="⏪ Prev", callback_data=f"sub_pg_{user_id}_{current_page-1}"))
    
    nav_row.append(InlineKeyboardButton(text=f"📄 {current_page}/{total_pages}", callback_data="none"))
    
    if current_page < total_pages:
        nav_row.append(InlineKeyboardButton(text="Next ⏩", callback_data=f"sub_pg_{user_id}_{current_page+1}"))
    kb.append(nav_row)
    
    # 3. Quick Actions
    kb.append([
        InlineKeyboardButton(text="⏳ Resync All", callback_data=f"sub_resync_all_{user_id}", style="primary"),
        InlineKeyboardButton(text="🌐 Trans All", callback_data=f"sub_trans_all_{user_id}", style="primary")
    ])
    
    # 4. Finalizing
    kb.append([InlineKeyboardButton(text="✅ Selesai & Kompilasi", callback_data=f"sub_compile_{user_id}", style="success")])
    kb.append([InlineKeyboardButton(text="❌ Batal", callback_data=f"sub_cancel_{user_id}", style="danger")])
    
    return InlineKeyboardMarkup(inline_keyboard=kb)

def get_focus_kb(user_id, line_index):
    """Layout saat mengedit 1 baris spesifik."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📝 Edit Teks", callback_data=f"sub_edit_txt_{user_id}_{line_index}", style="primary"),
            InlineKeyboardButton(text="🌐 Terjemahkan", callback_data=f"sub_edit_tr_{user_id}_{line_index}", style="primary")
        ],
        [
            InlineKeyboardButton(text="⏪ -0.5s", callback_data=f"sub_adj_{user_id}_{line_index}_-500"),
            InlineKeyboardButton(text="+0.5s ⏩", callback_data=f"sub_adj_{user_id}_{line_index}_500")
        ],
        [
            InlineKeyboardButton(text="🗑️ Hapus Baris", callback_data=f"sub_del_{user_id}_{line_index}", style="danger"),
            InlineKeyboardButton(text="↩️ Kembali", callback_data=f"sub_pg_{user_id}_1", style="danger")
        ]
    ])

# ═══════════════════════════════════════════════════════════════════════
#  COMMAND HANDLER
# ═══════════════════════════════════════════════════════════════════════

@router.message(Command(f"subedit{CMD_SUFFIX}"))
async def subedit_start(message: Message):
    user_id = message.from_user.id
    if not message.reply_to_message or not message.reply_to_message.document:
        return await message.reply("❌ **Gagal:** Balas file `.srt` yang ingin Anda edit!")

    file_name = message.reply_to_message.document.file_name
    if not file_name.lower().endswith('.srt'):
        return await message.reply("❌ **Gagal:** Hanya mendukung format `.srt` untuk saat ini.")

    status_msg = await message.reply("⏳ 📝 **Menganalisis Subtitle...**\n_Mohon tunggu sebentar._")
    
    try:
        # Download ke temp
        srt_file = await Telegram.AIOGRAM_BOT.download(message.reply_to_message.document)
        srt_path = f"./temp/sub_{user_id}.srt"
        with open(srt_path, "wb") as f:
            f.write(srt_file.read())
        
        # Parsing ke DB (Asumsi mengembalikan jumlah baris)
        total_lines = await parse_srt_to_db(user_id, srt_path)
        
        # Ambil 5 baris pertama (Gunakan helper db Anda)
        from bot_helper.Database.User_Data import get_subtitle_page
        lines = await get_subtitle_page(user_id, page=1, limit=5)
        total_pages = (total_lines // 5) + (1 if total_lines % 5 > 0 else 0)
        
        text = (
            f"<b>📝 SUBTITLE EDITOR</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📦 <b>File:</b> <code>{file_name}</code>\n"
            f"📊 <b>Total:</b> <code>{total_lines} Baris</code>\n\n"
            f"<i>Silakan pilih baris yang ingin Anda edit di bawah ini 👇</i>"
        )
        
        await status_msg.edit_text(text, reply_markup=get_editor_kb(lines, 1, total_pages, user_id), parse_mode="HTML")
        os.remove(srt_path)
        
    except Exception as e:
        LOGGER.error(f"SubEdit Error: {e}")
        await status_msg.edit_text(f"❌ **Error:** Terjadi kesalahan saat memproses file.\n<code>{e}</code>", parse_mode="HTML")

# ═══════════════════════════════════════════════════════════════════════
#  CALLBACK HANDLERS
# ═══════════════════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("sub_pg_"))
async def handle_pagination(call: CallbackQuery):
    parts = call.data.split("_")
    user_id, page = int(parts[2]), int(parts[3])
    
    if call.from_user.id != user_id: return await call.answer("Bukan milikmu!", show_alert=True)
    
    from bot_helper.Database.User_Data import get_subtitle_page, get_total_sub_lines
    lines = await get_subtitle_page(user_id, page=page, limit=5)
    total_lines = await get_total_sub_lines(user_id)
    total_pages = (total_lines // 5) + (1 if total_lines % 5 > 0 else 0)
    
    try:
        await call.message.edit_reply_markup(reply_markup=get_editor_kb(lines, page, total_pages, user_id))
        await call.answer()
    except TelegramBadRequest:
        await call.answer("Halaman ini sudah terbuka.")

@router.callback_query(F.data.startswith("sub_focus_"))
async def handle_focus(call: CallbackQuery):
    parts = call.data.split("_")
    user_id, line_idx = int(parts[2]), int(parts[3])
    
    if call.from_user.id != user_id: return await call.answer("Bukan milikmu!", show_alert=True)
    
    from bot_helper.Database.User_Data import get_single_sub_line
    line_data = await get_single_sub_line(user_id, line_idx)
    
    text = (
        f"<b>🛠 EDITING BARIS #{line_idx}</b>\n"
        f"────────────────────\n"
        f"⏰ <b>Waktu:</b> <code>{line_data['start']} --> {line_data['end']}</code>\n"
        f"💬 <b>Teks:</b> <code>{line_data['text']}</code>\n"
        f"────────────────────\n"
        f"<i>Apa yang ingin Anda ubah?</i>"
    )
    await call.message.edit_text(text, reply_markup=get_focus_kb(user_id, line_idx), parse_mode="HTML")

@router.callback_query(F.data.startswith("sub_cancel_"))
async def handle_cancel(call: CallbackQuery):
    user_id = int(call.data.split("_")[2])
    if call.from_user.id != user_id: return await call.answer("Bukan milikmu!", show_alert=True)
    
    from bot_helper.Database.User_Data import clear_subtitle_temp
    await clear_subtitle_temp(user_id)
    await call.message.edit_text("❌ **Subtitle Editor ditutup. Data sementara dihapus.**")

@router.callback_query(F.data.startswith("sub_compile_"))
async def handle_compile(call: CallbackQuery):
    user_id = int(call.data.split("_")[2])
    if call.from_user.id != user_id: return await call.answer("Bukan milikmu!", show_alert=True)
    
    await call.message.edit_text("⏳ 🏗 **Menyusun file SRT baru...**")
    
    # Kompilasi DB ke file fisik
    output_path = await compile_db_to_srt(user_id)
    
    if output_path and os.path.exists(output_path):
        await call.message.answer_document(
            document=FSInputFile(output_path),
            caption="✅ **Subtitle Berhasil Diedit!**\n_Anda bisa menggunakan file ini untuk proses Hardmux berikutnya._"
        )
        await call.message.delete()
    else:
        await call.message.edit_text("❌ **Gagal:** Terjadi kesalahan saat mengompilasi subtitle.")

# ═══════════════════════════════════════════════════════════════════════
#  Daftarkan router ini di main.py Anda
# ═══════════════════════════════════════════════════════════════════════
