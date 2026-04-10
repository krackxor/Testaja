"""
╔══════════════════════════════════════════════════════════════════════╗
║                 bot/subtitle_editor.py — v1.6 (BULLETPROOF)          ║
║       Subtitle Editor: Resync, Edit, & Translate (Studio Khoirul)    ║
╠══════════════════════════════════════════════════════════════════════╣
║  CHANGELOG v1.6:                                                     ║
║  [FIX CRITICAL] Membungkus SEMUA tombol dengan Sabuk Pengaman        ║
║                 (try-except) untuk mencegah tombol stuck selamanya.  ║
║  [FIX CRITICAL] Fallback str() pada data DB untuk mencegah TypeError ║
║                 saat membaca baris subtitle yang kosong (NoneType).  ║
╚══════════════════════════════════════════════════════════════════════╝
"""

import asyncio
import os
import pysrt
import html
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
    kb = []
    for line in lines:
        raw_text = str(line.get('text', ''))
        preview = raw_text[:35] + "..." if len(raw_text) > 35 else raw_text
        idx = line.get('index', 0)
        kb.append([
            InlineKeyboardButton(
                text=f"#{idx} | {preview}", 
                callback_data=f"sub_focus_{user_id}_{idx}"
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
#  CALLBACK HANDLERS DENGAN SABUK PENGAMAN (ANTI STUCK)
# ═══════════════════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("sub_pg_"))
async def handle_pagination(call: CallbackQuery):
    try:
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
        except TelegramBadRequest: pass # Abaikan error jika klik halaman yang sama
        await call.answer()
        
    except Exception as e:
        LOGGER.error(f"PG Error: {e}", exc_info=True)
        await call.answer(f"⚠️ Error: {str(e)[:40]}", show_alert=True)

@router.callback_query(F.data.startswith("sub_focus_"))
async def handle_focus(call: CallbackQuery):
    try:
        parts = call.data.split("_")
        user_id, line_idx = int(parts[2]), int(parts[3])
        if call.from_user.id != user_id: return await call.answer("Bukan milikmu!", show_alert=True)
        
        line_data = await get_single_sub_line(user_id, line_idx)
        if not line_data: return await call.answer("Baris tidak ditemukan di DB.", show_alert=True)
        
        # Mencegah TypeError jika teks kosong (None)
        safe_text = html.escape(str(line_data.get('text', ''))) 
        start_time = str(line_data.get('start', '00:00:00,000'))
        end_time = str(line_data.get('end', '00:00:00,000'))
        
        text = (
            f"<b>🛠 EDITING BARIS #{line_idx}</b>\n"
            f"────────────────────\n"
            f"⏰ <b>Waktu:</b> <code>{start_time} --> {end_time}</code>\n"
            f"💬 <b>Teks:</b> <code>{safe_text}</code>\n"
            f"────────────────────"
        )
        await call.message.edit_text(text, reply_markup=get_focus_kb(user_id, line_idx), parse_mode="HTML")
        await call.answer()
        
    except Exception as e:
        LOGGER.error(f"Focus Error: {e}", exc_info=True)
        await call.answer(f"⚠️ Error: {str(e)[:40]}", show_alert=True)

@router.callback_query(F.data.startswith("sub_adj_"))
async def handle_adjust_time(call: CallbackQuery):
    try:
        parts = call.data.split("_")
        user_id, line_idx, ms = int(parts[2]), int(parts[3]), int(parts[4])
        if call.from_user.id != user_id: return await call.answer("Bukan milikmu!", show_alert=True)
        
        line = await get_single_sub_line(user_id, line_idx)
        start_str = str(line.get("start", "00:00:00,000")).replace('.', ',')
        end_str = str(line.get("end", "00:00:00,000")).replace('.', ',')
        
        st = pysrt.SubRipTime.from_string(start_str)
        et = pysrt.SubRipTime.from_string(end_str)
        st.shift(milliseconds=ms)
        et.shift(milliseconds=ms)
        
        await DATA.subtitle_temp.update_one(
            {"user_id": user_id, "index": line_idx},
            {"$set": {"start": str(st).replace(',', '.'), "end": str(et).replace(',', '.')}}
        )
        await call.answer(f"✅ Waktu digeser {ms}ms")
        
        # Refresh UI
        line_data = await get_single_sub_line(user_id, line_idx)
        safe_text = html.escape(str(line_data.get('text', '')))
        text = (
            f"<b>🛠 EDITING BARIS #{line_idx}</b>\n────────────────────\n"
            f"⏰ <b>Waktu:</b> <code>{line_data.get('start')} --> {line_data.get('end')}</code>\n"
            f"💬 <b>Teks:</b> <code>{safe_text}</code>\n────────────────────"
        )
        try:
            await call.message.edit_text(text, reply_markup=get_focus_kb(user_id, line_idx), parse_mode="HTML")
        except TelegramBadRequest: pass
        
    except Exception as e:
        LOGGER.error(f"Adjust Error: {e}", exc_info=True)
        await call.answer(f"⚠️ Error: {str(e)[:40]}", show_alert=True)

@router.callback_query(F.data.startswith("sub_edit_tr_"))
async def handle_translate_line(call: CallbackQuery):
    try:
        parts = call.data.split("_")
        user_id, line_idx = int(parts[3]), int(parts[4])
        if call.from_user.id != user_id: return await call.answer("Bukan milikmu!", show_alert=True)
        
        line = await get_single_sub_line(user_id, line_idx)
        raw_text = str(line.get("text", ""))
        await call.answer("⏳ Menerjemahkan...", show_alert=False)
        
        translator = GoogleTranslator(source='auto', target='id')
        translated = await asyncio.to_thread(translator.translate, raw_text)
        
        await DATA.subtitle_temp.update_one({"user_id": user_id, "index": line_idx}, {"$set": {"text": translated}})
        
        line_data = await get_single_sub_line(user_id, line_idx)
        safe_text = html.escape(str(line_data.get('text', '')))
        text = (
            f"<b>🛠 EDITING BARIS #{line_idx}</b>\n────────────────────\n"
            f"⏰ <b>Waktu:</b> <code>{line_data.get('start')} --> {line_data.get('end')}</code>\n"
            f"💬 <b>Teks:</b> <code>{safe_text}</code>\n────────────────────"
        )
        await call.message.edit_text(text, reply_markup=get_focus_kb(user_id, line_idx), parse_mode="HTML")
        
    except Exception as e:
        LOGGER.error(f"Trans Error: {e}", exc_info=True)
        await call.answer(f"⚠️ Gagal: {str(e)[:40]}", show_alert=True)

@router.callback_query(F.data.startswith("sub_edit_txt_"))
async def handle_edit_text_prompt(call: CallbackQuery):
    try:
        parts = call.data.split("_")
        user_id, line_idx = int(parts[3]), int(parts[4])
        if call.from_user.id != user_id: return await call.answer("Bukan milikmu!", show_alert=True)
        
        await call.answer()
        prompt = await call.message.answer(f"📝 **Kirimkan teks baru untuk baris #{line_idx}:**\n_Ketik 'batal' untuk mengabaikan._")
        
        try:
            response = await wait_for_message(call.message.chat.id, user_id, 60)
        except asyncio.TimeoutError:
            response = None
            
        if not response or response.text.lower() == "batal":
            if prompt: await prompt.delete()
            return await call.message.answer("Batal mengedit.")

        await DATA.subtitle_temp.update_one({"user_id": user_id, "index": line_idx}, {"$set": {"text": response.text}})
        try:
            await response.delete()
            await prompt.delete()
        except: pass
        
        line_data = await get_single_sub_line(user_id, line_idx)
        safe_text = html.escape(str(line_data.get('text', '')))
        text = (
            f"<b>🛠 EDITING BARIS #{line_idx}</b>\n────────────────────\n"
            f"⏰ <b>Waktu:</b> <code>{line_data.get('start')} --> {line_data.get('end')}</code>\n"
            f"💬 <b>Teks:</b> <code>{safe_text}</code>\n────────────────────"
        )
        try:
            await call.message.edit_text(text, reply_markup=get_focus_kb(user_id, line_idx), parse_mode="HTML")
        except TelegramBadRequest: pass
        
    except Exception as e:
        LOGGER.error(f"Edit Txt Error: {e}", exc_info=True)
        await call.answer(f"⚠️ Error: {str(e)[:40]}", show_alert=True)

@router.callback_query(F.data.startswith("sub_trall_"))
async def handle_translate_all(call: CallbackQuery):
    try:
        user_id = int(call.data.split("_")[2])
        if call.from_user.id != user_id: return await call.answer("Bukan milikmu!", show_alert=True)
        
        await call.answer("⏳ Memulai Auto Translate...", show_alert=True)
        status_msg = await call.message.edit_text("⏳ <b>Auto Translate berjalan di latar belakang...</b>\nAnda bisa menggunakan fitur bot lainnya.", parse_mode="HTML")
        
        cursor = DATA.subtitle_temp.find({"user_id": user_id})
        all_lines = await cursor.to_list(length=None)
        translator = GoogleTranslator(source='auto', target='id')
        
        count = 0
        for line in all_lines:
            raw_text = str(line.get("text", ""))
            translated = await asyncio.to_thread(translator.translate, raw_text)
            await DATA.subtitle_temp.update_one({"_id": line["_id"]}, {"$set": {"text": translated}})
            count += 1
            if count % 10 == 0: await asyncio.sleep(0.5) 
                    
        await status_msg.edit_text(f"✅ <b>Berhasil menerjemahkan {count} baris!</b>\nSilakan klik 'Selesai & Kompilasi'.", parse_mode="HTML")
    except Exception as e:
        LOGGER.error(f"Tr All Error: {e}", exc_info=True)
        await call.answer(f"⚠️ Error: {str(e)[:40]}", show_alert=True)

@router.callback_query(F.data.startswith("sub_rsall_"))
async def handle_resync_all(call: CallbackQuery):
    try:
        user_id = int(call.data.split("_")[2])
        if call.from_user.id != user_id: return await call.answer("Bukan milikmu!", show_alert=True)
        
        await call.answer()
        prompt = await call.message.answer(
            "⏳ <b>RESYNC SEMUA BARIS</b>\n\n"
            "Ketik jumlah milidetik (ms) untuk digeser.\n"
            "Contoh: <code>500</code> (maju 0.5 detik), <code>-1000</code> (mundur 1 detik).\n\n"
            "<i>Ketik 'batal' untuk mengabaikan.</i>", 
            parse_mode="HTML"
        )
        
        try:
            response = await wait_for_message(call.message.chat.id, user_id, 60)
        except asyncio.TimeoutError:
            response = None
            
        if not response or response.text.lower() == "batal":
            if prompt: await prompt.delete()
            return await call.message.answer("Batal resync.")

        try:
            ms_shift = int(response.text.strip())
        except ValueError:
            await prompt.delete()
            return await call.message.answer("❌ Harus berupa angka bulat (contoh: 500).")

        status_msg = await call.message.edit_text(f"⏳ <b>Memproses Resync {ms_shift}ms...</b>", parse_mode="HTML")
        
        cursor = DATA.subtitle_temp.find({"user_id": user_id})
        all_lines = await cursor.to_list(length=None)
        
        count = 0
        for line in all_lines:
            st = pysrt.SubRipTime.from_string(str(line.get("start", "00:00:00,000")).replace('.', ','))
            et = pysrt.SubRipTime.from_string(str(line.get("end", "00:00:00,000")).replace('.', ','))
            st.shift(milliseconds=ms_shift)
            et.shift(milliseconds=ms_shift)
            
            await DATA.subtitle_temp.update_one(
                {"_id": line["_id"]},
                {"$set": {"start": str(st).replace(',', '.'), "end": str(et).replace(',', '.')}}
            )
            count += 1
            if count % 50 == 0: await asyncio.sleep(0.05)
                    
        await status_msg.edit_text(f"✅ <b>Berhasil Resync {count} baris sebanyak {ms_shift}ms!</b>\nSilakan klik 'Selesai & Kompilasi'.", parse_mode="HTML")
        
    except Exception as e:
        LOGGER.error(f"Rs All Error: {e}", exc_info=True)
        await call.answer(f"⚠️ Error: {str(e)[:40]}", show_alert=True)

@router.callback_query(F.data.startswith("sub_compile_"))
async def handle_compile(call: CallbackQuery):
    try:
        user_id = int(call.data.split("_")[2])
        if call.from_user.id != user_id: return await call.answer("Bukan milikmu!", show_alert=True)
        
        await call.answer()
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
            await call.message.edit_text("❌ Gagal mengompilasi file.")
            
    except Exception as e:
        LOGGER.error(f"Compile Error: {e}", exc_info=True)
        await call.answer(f"⚠️ Error: {str(e)[:40]}", show_alert=True)

@router.callback_query(F.data.startswith("sub_del_"))
async def handle_delete_line(call: CallbackQuery):
    try:
        parts = call.data.split("_")
        user_id, line_idx = int(parts[2]), int(parts[3])
        if call.from_user.id != user_id: return await call.answer("Bukan milikmu!", show_alert=True)
        
        await DATA.subtitle_temp.delete_one({"user_id": user_id, "index": line_idx})
        await call.answer("🗑️ Baris dihapus!")
        
        lines = await get_subtitle_page(user_id, page=1, limit=5)
        total_lines = await get_total_sub_lines(user_id)
        total_pages = (total_lines // 5) + (1 if total_lines % 5 > 0 else 0)
        
        text = f"<b>📝 SUBTITLE EDITOR</b>\n━━━━━━━━━━━━━━━━━━━━\n📊 Total: <code>{total_lines} Baris</code>\n\n<i>Pilih baris:</i>"
        try:
            await call.message.edit_text(text, reply_markup=get_editor_kb(lines, 1, total_pages, user_id), parse_mode="HTML")
        except TelegramBadRequest: pass
        
    except Exception as e:
        LOGGER.error(f"Delete Error: {e}", exc_info=True)
        await call.answer(f"⚠️ Error: {str(e)[:40]}", show_alert=True)

@router.callback_query(F.data.startswith("sub_cancel_"))
async def handle_cancel(call: CallbackQuery):
    try:
        user_id = int(call.data.split("_")[2])
        await clear_subtitle_temp(user_id)
        await call.message.edit_text("❌ Subtitle Editor ditutup.")
        await call.answer("Berhasil ditutup.")
    except Exception as e:
        LOGGER.error(f"Cancel Error: {e}", exc_info=True)
        await call.answer(f"⚠️ Error: {str(e)[:40]}", show_alert=True)
