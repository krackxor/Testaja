"""
╔══════════════════════════════════════════════════════════════════════╗
║                 bot/subtitle_editor.py — v1.4 (FINAL ASYNC)          ║
║       Subtitle Editor: Resync, Edit, & Translate (Studio Khoirul)    ║
╠══════════════════════════════════════════════════════════════════════╣
║  CHANGELOG v1.4:                                                     ║
║  [FIX CRITICAL] Asyncio.to_thread pada GoogleTranslator (Anti-Macet).║
║  [NEW] Handler untuk 'Trans All' (Terjemahkan semua baris di DB).    ║
║  [NEW] Handler untuk 'Resync All' (Geser waktu semua baris).         ║
╚══════════════════════════════════════════════════════════════════════╝
"""

import asyncio
import os
import pysrt
from aiogram import Router, F
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardRemove, FSInputFile
)
from aiogram.filters import Command
from aiogram.exceptions import TelegramBadRequest
from deep_translator import GoogleTranslator

from config.config import Config
from bot_helper.Database.User_Data import (
    get_data, DATA, get_subtitle_page, get_total_sub_lines, 
    get_single_sub_line, clear_subtitle_temp
)
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
    for line in lines:
        preview = line['text'][:35] + "..." if len(line['text']) > 35 else line['text']
        kb.append([
            InlineKeyboardButton(
                text=f"#{line['index']} | {preview}", 
                callback_data=f"sub_focus_{user_id}_{line['index']}"
            )
        ])
    
    nav_row = []
    if current_page > 1:
        nav_row.append(InlineKeyboardButton(text="⏪ Prev", callback_data=f"sub_pg_{user_id}_{current_page-1}"))
    nav_row.append(InlineKeyboardButton(text=f"📄 {current_page}/{total_pages}", callback_data="none"))
    if current_page < total_pages:
        nav_row.append(InlineKeyboardButton(text="Next ⏩", callback_data=f"sub_pg_{user_id}_{current_page+1}"))
    kb.append(nav_row)
    
    kb.append([
        InlineKeyboardButton(text="⏳ Resync All", callback_data=f"sub_rsall_{user_id}", style="primary"),
        InlineKeyboardButton(text="🌐 Trans All", callback_data=f"sub_trall_{user_id}", style="primary")
    ])
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
            InlineKeyboardButton(text="↩️ Kembali", callback_data=f"sub_pg_{user_id}_back", style="danger")
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
        os.makedirs("./temp", exist_ok=True)
        srt_path = f"./temp/sub_{user_id}.srt"
        
        await message.bot.download(message.reply_to_message.document, destination=srt_path)
        
        total_lines = await parse_srt_to_db(user_id, srt_path)
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
        if os.path.exists(srt_path): os.remove(srt_path)
    except Exception as e:
        LOGGER.error(f"SubEdit Error: {e}", exc_info=True)
        await status_msg.edit_text(f"❌ **Error:** {e}")

# ═══════════════════════════════════════════════════════════════════════
#  CALLBACK HANDLERS
# ═══════════════════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("sub_pg_"))
async def handle_pagination(call: CallbackQuery):
    parts = call.data.split("_")
    user_id = int(parts[2])
    
    page = 1 if parts[3] == "back" else int(parts[3])
    
    if call.from_user.id != user_id: return await call.answer("Bukan milikmu!", show_alert=True)
    
    lines = await get_subtitle_page(user_id, page=page, limit=5)
    total_lines = await get_total_sub_lines(user_id)
    total_pages = (total_lines // 5) + (1 if total_lines % 5 > 0 else 0)
    
    text = f"<b>📝 SUBTITLE EDITOR</b>\n━━━━━━━━━━━━━━━━━━━━\n📊 Total: <code>{total_lines} Baris</code>\n\n<i>Pilih baris:</i>"
    try:
        await call.message.edit_text(text, reply_markup=get_editor_kb(lines, page, total_pages, user_id), parse_mode="HTML")
        await call.answer()
    except TelegramBadRequest:
        await call.answer()

@router.callback_query(F.data.startswith("sub_focus_"))
async def handle_focus(call: CallbackQuery):
    parts = call.data.split("_")
    user_id, line_idx = int(parts[2]), int(parts[3])
    if call.from_user.id != user_id: return await call.answer("Bukan milikmu!", show_alert=True)
    
    line_data = await get_single_sub_line(user_id, line_idx)
    if not line_data: return await call.answer("Baris tidak ditemukan.", show_alert=True)
    
    text = (
        f"<b>🛠 EDITING BARIS #{line_idx}</b>\n"
        f"────────────────────\n"
        f"⏰ <b>Waktu:</b> <code>{line_data['start']} --> {line_data['end']}</code>\n"
        f"💬 <b>Teks:</b> <code>{line_data['text']}</code>\n"
        f"────────────────────"
    )
    await call.message.edit_text(text, reply_markup=get_focus_kb(user_id, line_idx), parse_mode="HTML")
    await call.answer()

# --- Logika Penyesuaian Waktu (Resync) ---
@router.callback_query(F.data.startswith("sub_adj_"))
async def handle_adjust_time(call: CallbackQuery):
    parts = call.data.split("_")
    user_id, line_idx, ms = int(parts[2]), int(parts[3]), int(parts[4])
    if call.from_user.id != user_id: return await call.answer("Bukan milikmu!", show_alert=True)
    
    line = await get_single_sub_line(user_id, line_idx)
    st = pysrt.SubRipTime.from_string(line["start"].replace('.', ','))
    et = pysrt.SubRipTime.from_string(line["end"].replace('.', ','))
    st.shift(milliseconds=ms)
    et.shift(milliseconds=ms)
    
    await DATA.subtitle_temp.update_one(
        {"user_id": user_id, "index": line_idx},
        {"$set": {"start": str(st).replace(',', '.'), "end": str(et).replace(',', '.')}}
    )
    await call.answer(f"✅ Digeser {ms}ms")
    
    line_data = await get_single_sub_line(user_id, line_idx)
    text = (
        f"<b>🛠 EDITING BARIS #{line_idx}</b>\n────────────────────\n"
        f"⏰ <b>Waktu:</b> <code>{line_data['start']} --> {line_data['end']}</code>\n"
        f"💬 <b>Teks:</b> <code>{line_data['text']}</code>\n────────────────────"
    )
    try:
        await call.message.edit_text(text, reply_markup=get_focus_kb(user_id, line_idx), parse_mode="HTML")
    except: pass


# ─── FITUR ASYNC: TERJEMAHAN 1 BARIS (ANTI-MACET) ───
@router.callback_query(F.data.startswith("sub_edit_tr_"))
async def handle_translate_line(call: CallbackQuery):
    parts = call.data.split("_")
    user_id, line_idx = int(parts[3]), int(parts[4])
    if call.from_user.id != user_id: return await call.answer("Bukan milikmu!", show_alert=True)
    
    line = await get_single_sub_line(user_id, line_idx)
    await call.answer("⏳ Menerjemahkan di latar belakang...", show_alert=False)
    
    try:
        translator = GoogleTranslator(source='auto', target='id')
        # [PERBAIKAN]: Menggunakan to_thread agar bot lain tetap bisa jalan (Merge, Cut, dll)
        translated = await asyncio.to_thread(translator.translate, line["text"])
        
        await DATA.subtitle_temp.update_one({"user_id": user_id, "index": line_idx}, {"$set": {"text": translated}})
        
        line_data = await get_single_sub_line(user_id, line_idx)
        text = (
            f"<b>🛠 EDITING BARIS #{line_idx}</b>\n────────────────────\n"
            f"⏰ <b>Waktu:</b> <code>{line_data['start']} --> {line_data['end']}</code>\n"
            f"💬 <b>Teks:</b> <code>{line_data['text']}</code>\n────────────────────"
        )
        await call.message.edit_text(text, reply_markup=get_focus_kb(user_id, line_idx), parse_mode="HTML")
    except Exception as e:
        await call.answer(f"❌ Gagal: {e}", show_alert=True)


# ─── FITUR ASYNC: TERJEMAHKAN SEMUA BARIS (ANTI-MACET) ───
@router.callback_query(F.data.startswith("sub_trall_"))
async def handle_translate_all(call: CallbackQuery):
    user_id = int(call.data.split("_")[2])
    if call.from_user.id != user_id: return await call.answer("Bukan milikmu!", show_alert=True)
    
    await call.answer("⏳ Memulai Auto Translate...", show_alert=True)
    status_msg = await call.message.edit_text("⏳ <b>Auto Translate berjalan di latar belakang...</b>\nAnda bisa menggunakan fitur bot lainnya.", parse_mode="HTML")
    
    try:
        # Ambil semua data subtitle user ini dari MongoDB
        cursor = DATA.subtitle_temp.find({"user_id": user_id})
        all_lines = await cursor.to_list(length=None)
        
        translator = GoogleTranslator(source='auto', target='id')
        
        count = 0
        for line in all_lines:
            # Gunakan to_thread agar bot TIDAK MACET!
            translated = await asyncio.to_thread(translator.translate, line["text"])
            await DATA.subtitle_temp.update_one({"_id": line["_id"]}, {"$set": {"text": translated}})
            count += 1
            
            # Beri napas ke bot setiap 10 baris agar user lain bisa pakai fitur Merge/dll
            if count % 10 == 0:
                await asyncio.sleep(0.5) 
                
        await status_msg.edit_text(f"✅ <b>Berhasil menerjemahkan {count} baris!</b>\nSilakan klik 'Selesai & Kompilasi'.", parse_mode="HTML")
    except Exception as e:
        await status_msg.edit_text(f"❌ Gagal Translate All: {e}")


# --- Logika Edit Teks Manual ---
@router.callback_query(F.data.startswith("sub_edit_txt_"))
async def handle_edit_text_prompt(call: CallbackQuery):
    parts = call.data.split("_")
    user_id, line_idx = int(parts[3]), int(parts[4])
    if call.from_user.id != user_id: return await call.answer("Bukan milikmu!", show_alert=True)
    
    prompt = await call.message.answer(f"📝 **Kirimkan teks baru untuk baris #{line_idx}:**\n_Ketik 'batal' untuk mengabaikan._")
    
    try:
        response = await wait_for_message(call.message.chat.id, user_id, 60)
    except asyncio.TimeoutError:
        response = None
        
    if not response or response.text.lower() == "batal":
        if prompt: await prompt.delete()
        return await call.answer("Batal mengedit.")

    await DATA.subtitle_temp.update_one({"user_id": user_id, "index": line_idx}, {"$set": {"text": response.text}})
    try:
        await response.delete()
        await prompt.delete()
    except: pass
    await call.answer("✅ Teks diperbarui!")
    
    line_data = await get_single_sub_line(user_id, line_idx)
    text = (
        f"<b>🛠 EDITING BARIS #{line_idx}</b>\n────────────────────\n"
        f"⏰ <b>Waktu:</b> <code>{line_data['start']} --> {line_data['end']}</code>\n"
        f"💬 <b>Teks:</b> <code>{line_data['text']}</code>\n────────────────────"
    )
    try:
        await call.message.edit_text(text, reply_markup=get_focus_kb(user_id, line_idx), parse_mode="HTML")
    except: pass


# --- Finalizing & Closing ---
@router.callback_query(F.data.startswith("sub_compile_"))
async def handle_compile(call: CallbackQuery):
    user_id = int(call.data.split("_")[2])
    if call.from_user.id != user_id: return await call.answer("Bukan milikmu!", show_alert=True)
    
    msg = await call.message.edit_text("⏳ 🏗 **Menyusun file SRT baru...**")
    output_path = await compile_db_to_srt(user_id)
    
    if output_path and os.path.exists(output_path):
        await call.message.answer_document(
            document=FSInputFile(output_path),
            caption="✅ **Subtitle Berhasil Diedit!**"
        )
        await msg.delete()
        await clear_subtitle_temp(user_id)
    else:
        await call.message.edit_text("❌ Gagal mengompilasi.")

@router.callback_query(F.data.startswith("sub_cancel_"))
async def handle_cancel(call: CallbackQuery):
    user_id = int(call.data.split("_")[2])
    await clear_subtitle_temp(user_id)
    await call.message.edit_text("❌ Subtitle Editor ditutup.")
