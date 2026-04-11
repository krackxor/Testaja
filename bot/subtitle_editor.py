import asyncio
import os
import pysrt
import html
from bson.objectid import ObjectId
from aiogram import Router, F
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove, FSInputFile
)
from aiogram.filters import Command
from aiogram.exceptions import TelegramBadRequest
from deep_translator import GoogleTranslator

from config.config import Config
from bot_helper.Database.DB_Handler import get_db
from bot_helper.Database.User_Data import (
    get_data, DATA, get_subtitle_page, get_total_sub_lines, 
    get_single_sub_line, clear_subtitle_temp, get_active_settings,
    _DATA_LOCK, _save_to_db
)
from bot_helper.Others.SrtParser import parse_srt_to_db
from bot_helper.Others.SrtCompiler import compile_db_to_srt
from bot.shared import wait_for_message, CMD_SUFFIX, LOGGER, Telegram # [FIX] Telegram ditambahkan ke import

# [NEW v3.1] Import Mesin Kasir
from bot_helper.Process.point_manager import process_payment

router = Router()

def get_cancel_kb():
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Batal")]], resize_keyboard=True, one_time_keyboard=True)

async def get_current_page(user_id: int, line_idx: int) -> int:
    db = get_db()
    count = await db.db["subtitle_temp"].count_documents({"user_id": user_id, "index": {"$lte": line_idx}})
    return max(1, ((count - 1) // 5) + 1)

# ─── CORE HELPERS: UNDO & REINDEX ───
async def save_undo_state(user_id: int):
    """Menyimpan snapshot data saat ini sebelum diubah (Untuk Undo)"""
    db = get_db()
    lines = await db.db["subtitle_temp"].find({"user_id": user_id}).to_list(length=None)
    await db.db["subtitle_undo"].delete_many({"user_id": user_id})
    if lines:
        for line in lines:
            del line["_id"] # Buang ID lama agar bisa di-insert baru
        await db.db["subtitle_undo"].insert_many(lines)

async def check_has_undo(user_id: int) -> bool:
    db = get_db()
    count = await db.db["subtitle_undo"].count_documents({"user_id": user_id})
    return count > 0

async def reindex_lines(user_id: int):
    """Menyusun ulang nomor urut (index) baris berdasarkan waktu start"""
    db = get_db()
    lines = await db.db["subtitle_temp"].find({"user_id": user_id}).sort([("start", 1)]).to_list(length=None)
    
    # [OPTIMIZATION] Bulk Write untuk Re-Indexing
    from pymongo import UpdateOne
    bulk_ops = []
    for i, line in enumerate(lines, start=1):
        if line.get("index") != i:  # Hanya update jika index berubah
            bulk_ops.append(UpdateOne({"_id": line["_id"]}, {"$set": {"index": i}}))
    
    if bulk_ops:
        await db.db["subtitle_temp"].bulk_write(bulk_ops)


# ═══════════════════════════════════════════════════════════════════════
#  UI GENERATORS (INLINE KEYBOARDS)
# ═══════════════════════════════════════════════════════════════════════

async def get_workspace_kb(user_id: int):
    db = get_db()
    kb = [[InlineKeyboardButton(text="🆕 Buat Proyek Baru", callback_data=f"sub_new_{user_id}")]]
    active = await db.db["subtitle_temp"].count_documents({"user_id": user_id})
    if active > 0: kb.append([InlineKeyboardButton(text=f"▶️ Lanjutkan Proyek Aktif ({active} Baris)", callback_data=f"sub_pg_{user_id}_1")])
    saved = await db.db["subtitle_projects"].count_documents({"user_id": user_id})
    if saved > 0: kb.append([InlineKeyboardButton(text=f"📂 Buka Proyek Tersimpan ({saved})", callback_data=f"sub_proj_{user_id}")])
    kb.append([InlineKeyboardButton(text="❌ Tutup Workspace", callback_data=f"sub_cancel_{user_id}")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

async def get_saved_projects_kb(user_id: int):
    db = get_db()
    projects = await db.db["subtitle_projects"].find({"user_id": user_id}).sort("_id", -1).to_list(length=10)
    kb = []
    for p in projects:
        name, pid = p.get("project_name", "Untitled"), str(p["_id"])
        kb.append([
            InlineKeyboardButton(text=f"📁 {name}", callback_data=f"sub_load_{user_id}_{pid}"),
            InlineKeyboardButton(text="🗑️ Hapus", callback_data=f"sub_delp_{user_id}_{pid}")
        ])
    kb.append([InlineKeyboardButton(text="↩️ Kembali ke Workspace", callback_data=f"sub_main_{user_id}")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

def get_editor_kb(lines, current_page, total_pages, user_id, target_lang, has_undo=False):
    kb = []
    for line in lines:
        raw_text = str(line.get('text', ''))
        preview = raw_text[:35] + "..." if len(raw_text) > 35 else raw_text
        idx = line.get('index', 0)
        kb.append([InlineKeyboardButton(text=f"#{idx} | {preview}", callback_data=f"sub_focus_{user_id}_{idx}")])
    
    nav_row = []
    if current_page > 1: nav_row.append(InlineKeyboardButton(text="⏪ Prev", callback_data=f"sub_pg_{user_id}_{current_page-1}"))
    nav_row.append(InlineKeyboardButton(text=f"🔍 {current_page}/{total_pages}", callback_data=f"sub_jump_{user_id}"))
    if current_page < total_pages: nav_row.append(InlineKeyboardButton(text="Next ⏩", callback_data=f"sub_pg_{user_id}_{current_page+1}"))
    kb.append(nav_row)
    
    # Tombol Tools Tingkat Lanjut
    kb.append([
        InlineKeyboardButton(text=f"🌐 Lang: {target_lang.upper()}", callback_data=f"sub_setlang_{user_id}"),
        InlineKeyboardButton(text="🩺 QC & Fix", callback_data=f"sub_qc_{user_id}")
    ])
    
    tools_row = [InlineKeyboardButton(text="🔎 Cari & Ganti", callback_data=f"sub_replace_{user_id}")]
    if has_undo: tools_row.append(InlineKeyboardButton(text="↩️ Undo Terakhir", callback_data=f"sub_undo_{user_id}"))
    kb.append(tools_row)

    kb.append([
        InlineKeyboardButton(text="⏳ Resync All", callback_data=f"sub_rsall_{user_id}"),
        InlineKeyboardButton(text="🌐 Trans All", callback_data=f"sub_trall_{user_id}")
    ])
    kb.append([
        InlineKeyboardButton(text="💾 Simpan Proyek", callback_data=f"sub_save_{user_id}"),
        InlineKeyboardButton(text="✅ Kompilasi SRT", callback_data=f"sub_compile_{user_id}")
    ])
    kb.append([InlineKeyboardButton(text="❌ Keluar Editor", callback_data=f"sub_main_{user_id}")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

def get_focus_kb(user_id, line_index, current_page):
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📝 Edit Teks", callback_data=f"sub_edit_txt_{user_id}_{line_index}"),
            InlineKeyboardButton(text="🌐 Terjemahkan", callback_data=f"sub_edit_tr_{user_id}_{line_index}")
        ],
        [
            InlineKeyboardButton(text="⏪ -0.5s", callback_data=f"sub_adj_{user_id}_{line_index}_-500"),
            InlineKeyboardButton(text="+0.5s ⏩", callback_data=f"sub_adj_{user_id}_{line_index}_500")
        ],
        [
            InlineKeyboardButton(text="✂️ Split Baris", callback_data=f"sub_split_{user_id}_{line_index}"),
            InlineKeyboardButton(text="🔗 Merge Bawah", callback_data=f"sub_merge_{user_id}_{line_index}")
        ],
        [
            InlineKeyboardButton(text="🗑️ Hapus Baris", callback_data=f"sub_del_{user_id}_{line_index}"),
            InlineKeyboardButton(text="↩️ Kembali", callback_data=f"sub_pg_{user_id}_{current_page}")
        ]
    ])

# ═══════════════════════════════════════════════════════════════════════
#  CORE PARSER LOGIC
# ═══════════════════════════════════════════════════════════════════════

async def start_new_project_from_file(message: Message, document, user_id: int):
    file_name = document.file_name
    status_msg = await message.answer("⏳ 📝 **Menganalisis Subtitle untuk Proyek Baru...**", reply_markup=ReplyKeyboardRemove())
    try:
        os.makedirs("./temp", exist_ok=True)
        srt_path = f"./temp/sub_{user_id}.srt"
        await Telegram.AIOGRAM_BOT.download(document, destination=srt_path)
        
        total_lines = await parse_srt_to_db(user_id, srt_path)
        await save_undo_state(user_id) # Backup awal
        
        lines = await get_subtitle_page(user_id, page=1, limit=5)
        total_pages = (total_lines // 5) + (1 if total_lines % 5 > 0 else 0)
        target_lang = get_active_settings(user_id).get("ai_subtitle", {}).get("target_lang", "id")
        has_undo = await check_has_undo(user_id)
        
        text = f"<b>📝 SUBTITLE EDITOR (Proyek Aktif)</b>\n━━━━━━━━━━━━━━━━━━━━\n📦 <b>File:</b> <code>{file_name}</code>\n📊 <b>Total:</b> <code>{total_lines} Baris</code>\n\n<i>Silakan pilih baris:</i>"
        await status_msg.edit_text(text, reply_markup=get_editor_kb(lines, 1, total_pages, user_id, target_lang, has_undo), parse_mode="HTML")
        if os.path.exists(srt_path): os.remove(srt_path)
    except Exception as e:
        await status_msg.edit_text(f"❌ **Error:** {e}")

# ═══════════════════════════════════════════════════════════════════════
#  ENTRY POINTS & WORKSPACE HANDLERS
# ═══════════════════════════════════════════════════════════════════════

@router.message(Command(f"subedit{CMD_SUFFIX}"))
async def subedit_start(message: Message):
    user_id = message.from_user.id
    if message.reply_to_message and message.reply_to_message.document:
        if not message.reply_to_message.document.file_name.lower().endswith('.srt'):
            return await message.reply("❌ Hanya mendukung `.srt`.")
        return await start_new_project_from_file(message, message.reply_to_message.document, user_id)
    kb = await get_workspace_kb(user_id)
    return await message.answer("<b>🗂️ SUBTITLE WORKSPACE</b>\n━━━━━━━━━━━━━━━━━━━━\nSelamat datang di Manajer Proyek Subtitle.\n\n<i>Pilih opsi di bawah ini:</i>", reply_markup=kb, parse_mode="HTML")

@router.callback_query(F.data == "open_sub_workspace")
async def handle_open_workspace_external(call: CallbackQuery):
    kb = await get_workspace_kb(call.from_user.id)
    try: await call.message.edit_text("<b>🗂️ SUBTITLE WORKSPACE</b>\n━━━━━━━━━━━━━━━━━━━━\nSelamat datang di Manajer Proyek Subtitle.\n\n<i>Pilih opsi di bawah ini:</i>", reply_markup=kb, parse_mode="HTML")
    except TelegramBadRequest: pass
    await call.answer()

@router.callback_query(F.data.startswith("sub_new_"))
async def handle_new_project_btn(call: CallbackQuery):
    user_id = int(call.data.split("_")[2])
    if call.from_user.id != user_id: return await call.answer("Bukan milikmu!", show_alert=True)
    prompt = await call.message.answer("🆕 <b>BUAT PROYEK BARU</b>\nKirim file <code>.srt</code> Anda.", reply_markup=get_cancel_kb(), parse_mode="HTML")
    try: res = await wait_for_message(call.message.chat.id, user_id, 120)
    except asyncio.TimeoutError: res = None
    if not res or (res.text and res.text.lower() == "batal"): return await call.message.answer("Dibatalkan.", reply_markup=ReplyKeyboardRemove())
    if not res.document or not res.document.file_name.lower().endswith('.srt'): return await call.message.answer("❌ Harus file .srt!", reply_markup=ReplyKeyboardRemove())
    await prompt.delete()
    await start_new_project_from_file(res, res.document, user_id)

@router.callback_query(F.data.startswith("sub_main_"))
async def handle_workspace_main(call: CallbackQuery):
    user_id = int(call.data.split("_")[2])
    kb = await get_workspace_kb(user_id)
    try: await call.message.edit_text("<b>🗂️ SUBTITLE WORKSPACE</b>\n━━━━━━━━━━━━━━━━━━━━\nPilih opsi di bawah ini:", reply_markup=kb, parse_mode="HTML")
    except TelegramBadRequest: pass

@router.callback_query(F.data.startswith("sub_proj_"))
async def handle_list_projects(call: CallbackQuery):
    user_id = int(call.data.split("_")[2])
    kb = await get_saved_projects_kb(user_id)
    try: await call.message.edit_text("<b>💾 PROYEK TERSIMPAN</b>\n━━━━━━━━━━━━━━━━━━━━\nPilih proyek:", reply_markup=kb, parse_mode="HTML")
    except TelegramBadRequest: pass

@router.callback_query(F.data.startswith("sub_save_"))
async def handle_save_project(call: CallbackQuery):
    user_id = int(call.data.split("_")[2])
    prompt = await call.message.answer("💾 <b>SIMPAN PROYEK</b>\nKetik nama proyek:", reply_markup=get_cancel_kb(), parse_mode="HTML")
    try: res = await wait_for_message(call.message.chat.id, user_id, 60)
    except asyncio.TimeoutError: res = None
    if not res or res.text.lower() == "batal": return await call.message.answer("Dibatalkan.", reply_markup=ReplyKeyboardRemove())
    db = get_db()
    lines = await db.db["subtitle_temp"].find({"user_id": user_id}).to_list(length=None)
    await db.db["subtitle_projects"].update_one({"user_id": user_id, "project_name": res.text.strip()}, {"$set": {"lines": lines}}, upsert=True)
    await prompt.delete()
    await res.delete()
    temp = await call.message.answer("✅ Proyek berhasil disimpan!", reply_markup=ReplyKeyboardRemove())
    await asyncio.sleep(2)
    await temp.delete()

@router.callback_query(F.data.startswith("sub_load_"))
async def handle_load_project(call: CallbackQuery):
    user_id, proj_id = int(call.data.split("_")[2]), call.data.split("_")[3]
    db = get_db()
    proj = await db.db["subtitle_projects"].find_one({"_id": ObjectId(proj_id), "user_id": user_id})
    await db.db["subtitle_temp"].delete_many({"user_id": user_id})
    await db.db["subtitle_temp"].insert_many(proj["lines"])
    await save_undo_state(user_id)
    lines = await get_subtitle_page(user_id, page=1, limit=5)
    total = await get_total_sub_lines(user_id)
    pages = (total // 5) + (1 if total % 5 > 0 else 0)
    lang = get_active_settings(user_id).get("ai_subtitle", {}).get("target_lang", "id")
    has_undo = await check_has_undo(user_id)
    await call.message.edit_text(f"<b>📝 EDITOR (Proyek: {proj.get('project_name')})</b>\n━━━━━━━━━━━━━━━━━━━━\n📊 Total: <code>{total} Baris</code>", reply_markup=get_editor_kb(lines, 1, pages, user_id, lang, has_undo), parse_mode="HTML")

@router.callback_query(F.data.startswith("sub_delp_"))
async def handle_delete_project(call: CallbackQuery):
    user_id, proj_id = int(call.data.split("_")[2]), call.data.split("_")[3]
    db = get_db()
    await db.db["subtitle_projects"].delete_one({"_id": ObjectId(proj_id), "user_id": user_id})
    kb = await get_saved_projects_kb(user_id)
    try: await call.message.edit_text("<b>💾 PROYEK TERSIMPAN</b>\n━━━━━━━━━━━━━━━━━━━━\nPilih proyek:", reply_markup=kb, parse_mode="HTML")
    except TelegramBadRequest: pass

# ═══════════════════════════════════════════════════════════════════════
#  NEW FEATURES: UNDO, QC, FIND & REPLACE, SPLIT & MERGE
# ═══════════════════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("sub_undo_"))
async def handle_undo_state(call: CallbackQuery):
    try:
        user_id = int(call.data.split("_")[2])
        db = get_db()
        undo_lines = await db.db["subtitle_undo"].find({"user_id": user_id}).to_list(length=None)
        if not undo_lines:
            return await call.answer("❌ Tidak ada history untuk di-undo.", show_alert=True)
        
        await call.answer("⏳ Mengembalikan state sebelumnya...", show_alert=False)
        await db.db["subtitle_temp"].delete_many({"user_id": user_id})
        
        for line in undo_lines: del line["_id"]
        await db.db["subtitle_temp"].insert_many(undo_lines)
        await db.db["subtitle_undo"].delete_many({"user_id": user_id}) # Kosongkan memori undo
        
        lines = await get_subtitle_page(user_id, page=1, limit=5)
        total = await get_total_sub_lines(user_id)
        pages = (total // 5) + (1 if total % 5 > 0 else 0)
        lang = get_active_settings(user_id).get("ai_subtitle", {}).get("target_lang", "id")
        
        await call.message.edit_text(f"<b>📝 SUBTITLE EDITOR</b>\n━━━━━━━━━━━━━━━━━━━━\n✅ <b>Undo Berhasil!</b>\n📊 Total: <code>{total} Baris</code>", reply_markup=get_editor_kb(lines, 1, pages, user_id, lang, False), parse_mode="HTML")
    except Exception as e:
        await call.answer(f"⚠️ Error: {str(e)[:40]}", show_alert=True)

@router.callback_query(F.data.startswith("sub_qc_"))
async def handle_qc_autofix(call: CallbackQuery):
    try:
        user_id = int(call.data.split("_")[2])
        await call.answer("⏳ Menjalankan Quality Control...", show_alert=False)
        await save_undo_state(user_id) # Backup untuk undo
        
        db = get_db()
        lines = await db.db["subtitle_temp"].find({"user_id": user_id}).sort([("start", 1)]).to_list(length=None)
        
        fixed_count = 0
        from pymongo import UpdateOne # [OPTIMIZATION] Bulk Write
        bulk_ops = []

        for i in range(len(lines)):
            changed = False
            st = pysrt.SubRipTime.from_string(str(lines[i]["start"]).replace('.', ','))
            et = pysrt.SubRipTime.from_string(str(lines[i]["end"]).replace('.', ','))
            
            # 1. Fix Durasi Terlalu Pendek (< 0.5s)
            if et.ordinal - st.ordinal < 500:
                et = pysrt.SubRipTime.from_ordinal(st.ordinal + 500)
                changed = True
            
            # 2. Fix Overlap dengan baris sebelumnya
            if i > 0:
                prev_et = pysrt.SubRipTime.from_string(str(lines[i-1]["end"]).replace('.', ','))
                if st.ordinal < prev_et.ordinal:
                    st = pysrt.SubRipTime.from_ordinal(prev_et.ordinal + 50)
                    changed = True
                    
            if changed:
                bulk_ops.append(
                    UpdateOne(
                        {"_id": lines[i]["_id"]},
                        {"$set": {"start": str(st).replace(',', '.'), "end": str(et).replace(',', '.')}}
                    )
                )
                fixed_count += 1
                lines[i]["start"], lines[i]["end"] = str(st), str(et) # Update array memory
        
        if bulk_ops:
            await db.db["subtitle_temp"].bulk_write(bulk_ops)

        lines_pg = await get_subtitle_page(user_id, page=1, limit=5)
        total = await get_total_sub_lines(user_id)
        pages = (total // 5) + (1 if total % 5 > 0 else 0)
        lang = get_active_settings(user_id).get("ai_subtitle", {}).get("target_lang", "id")
        
        text = f"<b>📝 SUBTITLE EDITOR</b>\n━━━━━━━━━━━━━━━━━━━━\n🩺 <b>Laporan QC:</b>\n✅ Memperbaiki <b>{fixed_count} baris</b> yang rusak (Overlap/Kecepatan).\n📊 Total: <code>{total} Baris</code>"
        await call.message.edit_text(text, reply_markup=get_editor_kb(lines_pg, 1, pages, user_id, lang, True), parse_mode="HTML")
    except Exception as e:
        await call.answer(f"⚠️ Error QC: {str(e)[:40]}", show_alert=True)

@router.callback_query(F.data.startswith("sub_replace_"))
async def handle_find_replace(call: CallbackQuery):
    try:
        user_id = int(call.data.split("_")[2])
        prompt = await call.message.answer(
            "🔎 <b>CARI & GANTI (Massal)</b>\n\n"
            "Format ketik: <code>KataLama > KataBaru</code>\n"
            "Contoh: <code>Zoro > Joro</code>\n\n<i>Ketik 'batal' untuk membatalkan.</i>", 
            reply_markup=get_cancel_kb(), parse_mode="HTML"
        )
        
        try: res = await wait_for_message(call.message.chat.id, user_id, 60)
        except asyncio.TimeoutError: res = None
        if not res or res.text.lower() == "batal":
            await prompt.delete()
            return await call.message.answer("Dibatalkan.", reply_markup=ReplyKeyboardRemove())

        if ">" not in res.text:
            await prompt.delete()
            return await call.message.answer("❌ Format salah. Harus ada tanda '>'.", reply_markup=ReplyKeyboardRemove())

        old_word, new_word = [x.strip() for x in res.text.split(">", 1)]
        await prompt.delete()
        await res.delete()
        
        await save_undo_state(user_id) # Backup
        
        db = get_db()
        lines = await db.db["subtitle_temp"].find({"user_id": user_id}).to_list(length=None)
        count = 0
        from pymongo import UpdateOne # [OPTIMIZATION] Bulk Write
        bulk_ops = []

        for line in lines:
            txt = str(line.get("text", ""))
            if old_word in txt:
                new_txt = txt.replace(old_word, new_word)
                bulk_ops.append(UpdateOne({"_id": line["_id"]}, {"$set": {"text": new_txt}}))
                count += 1
                
        if bulk_ops:
             await db.db["subtitle_temp"].bulk_write(bulk_ops)

        temp = await call.message.answer(f"✅ Berhasil mengganti kata di {count} baris!", reply_markup=ReplyKeyboardRemove())
        await asyncio.sleep(2)
        await temp.delete()
        
        lines_pg = await get_subtitle_page(user_id, page=1, limit=5)
        total = await get_total_sub_lines(user_id)
        pages = (total // 5) + (1 if total % 5 > 0 else 0)
        lang = get_active_settings(user_id).get("ai_subtitle", {}).get("target_lang", "id")
        
        try: await call.message.edit_text(f"<b>📝 SUBTITLE EDITOR</b>\n━━━━━━━━━━━━━━━━━━━━\n📊 Total: <code>{total} Baris</code>", reply_markup=get_editor_kb(lines_pg, 1, pages, user_id, lang, True), parse_mode="HTML")
        except TelegramBadRequest: pass
    except Exception as e:
        await call.answer(f"⚠️ Error: {str(e)[:40]}", show_alert=True)

@router.callback_query(F.data.startswith("sub_split_"))
async def handle_split_line(call: CallbackQuery):
    try:
        parts = call.data.split("_")
        user_id, line_idx = int(parts[2]), int(parts[3])
        
        await save_undo_state(user_id)
        
        db = get_db()
        line = await db.db["subtitle_temp"].find_one({"user_id": user_id, "index": line_idx})
        if not line: return await call.answer("❌ Baris tidak ditemukan.", show_alert=True)
        
        words = str(line.get("text", "")).split()
        if len(words) < 2: return await call.answer("❌ Teks terlalu pendek untuk di-split.", show_alert=True)
        
        mid = len(words) // 2
        text1, text2 = " ".join(words[:mid]), " ".join(words[mid:])
        
        st = pysrt.SubRipTime.from_string(str(line["start"]).replace('.', ','))
        et = pysrt.SubRipTime.from_string(str(line["end"]).replace('.', ','))
        mid_time = pysrt.SubRipTime.from_ordinal(st.ordinal + (et.ordinal - st.ordinal) // 2)
        
        # Update baris saat ini (Setengah pertama)
        await db.db["subtitle_temp"].update_one({"_id": line["_id"]}, {"$set": {"text": text1, "end": str(mid_time).replace(',', '.')}})
        
        # Buat baris baru (Setengah kedua)
        new_line = {"user_id": user_id, "start": str(mid_time).replace(',', '.'), "end": str(et).replace(',', '.'), "text": text2}
        await db.db["subtitle_temp"].insert_one(new_line)
        
        await reindex_lines(user_id) # Rapikan index
        await call.answer("✂️ Baris berhasil dibelah!")
        
        cur_page = await get_current_page(user_id, line_idx)
        lines = await get_subtitle_page(user_id, page=cur_page, limit=5)
        total = await get_total_sub_lines(user_id)
        pages = (total // 5) + (1 if total % 5 > 0 else 0)
        lang = get_active_settings(user_id).get("ai_subtitle", {}).get("target_lang", "id")
        
        try: await call.message.edit_text(f"<b>📝 SUBTITLE EDITOR</b>\n━━━━━━━━━━━━━━━━━━━━\n📊 Total: <code>{total} Baris</code>", reply_markup=get_editor_kb(lines, cur_page, pages, user_id, lang, True), parse_mode="HTML")
        except TelegramBadRequest: pass
    except Exception as e:
        await call.answer(f"⚠️ Error Split: {str(e)[:40]}", show_alert=True)

@router.callback_query(F.data.startswith("sub_merge_"))
async def handle_merge_line(call: CallbackQuery):
    try:
        parts = call.data.split("_")
        user_id, line_idx = int(parts[2]), int(parts[3])
        
        await save_undo_state(user_id)
        db = get_db()
        
        line1 = await db.db["subtitle_temp"].find_one({"user_id": user_id, "index": line_idx})
        line2 = await db.db["subtitle_temp"].find_one({"user_id": user_id, "index": line_idx + 1})
        
        if not line1 or not line2:
            return await call.answer("❌ Baris bawah tidak ditemukan.", show_alert=True)
            
        new_text = str(line1.get("text", "")) + " " + str(line2.get("text", ""))
        new_end = str(line2.get("end"))
        
        await db.db["subtitle_temp"].update_one({"_id": line1["_id"]}, {"$set": {"text": new_text, "end": new_end}})
        await db.db["subtitle_temp"].delete_one({"_id": line2["_id"]})
        
        await reindex_lines(user_id)
        await call.answer("🔗 Baris digabungkan!")
        
        cur_page = await get_current_page(user_id, line_idx)
        lines = await get_subtitle_page(user_id, page=cur_page, limit=5)
        total = await get_total_sub_lines(user_id)
        pages = (total // 5) + (1 if total % 5 > 0 else 0)
        lang = get_active_settings(user_id).get("ai_subtitle", {}).get("target_lang", "id")
        
        try: await call.message.edit_text(f"<b>📝 SUBTITLE EDITOR</b>\n━━━━━━━━━━━━━━━━━━━━\n📊 Total: <code>{total} Baris</code>", reply_markup=get_editor_kb(lines, cur_page, pages, user_id, lang, True), parse_mode="HTML")
        except TelegramBadRequest: pass
    except Exception as e:
        await call.answer(f"⚠️ Error Merge: {str(e)[:40]}", show_alert=True)

# ═══════════════════════════════════════════════════════════════════════
#  PAGINATION & STANDARD LOGIC (Jump, Del, Edit, Trans, Compile)
# ═══════════════════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("sub_jump_"))
async def handle_jump_prompt(call: CallbackQuery):
    user_id = int(call.data.split("_")[2])
    total_lines = await get_total_sub_lines(user_id)
    prompt = await call.message.answer(f"🔍 <b>LOMPAT KE BARIS</b>\nTotal: <code>{total_lines}</code>\nKetik nomor baris (contoh: <code>500</code>):", reply_markup=get_cancel_kb(), parse_mode="HTML")
    try: res = await wait_for_message(call.message.chat.id, user_id, 60)
    except asyncio.TimeoutError: res = None
    if not res or res.text.lower() == "batal": return await call.message.answer("Pencarian dibatalkan.", reply_markup=ReplyKeyboardRemove())
    try:
        line_idx = int(res.text.strip())
        target_page = await get_current_page(user_id, line_idx)
    except: return await call.message.answer("❌ Angka tidak valid.", reply_markup=ReplyKeyboardRemove())
    await prompt.delete()
    await res.delete()
    temp = await call.message.answer(f"🚀 Melompat ke baris #{line_idx}...", reply_markup=ReplyKeyboardRemove())
    await asyncio.sleep(0.5)
    await temp.delete()
    lines = await get_subtitle_page(user_id, page=target_page, limit=5)
    pages = (total_lines // 5) + (1 if total_lines % 5 > 0 else 0)
    lang = get_active_settings(user_id).get("ai_subtitle", {}).get("target_lang", "id")
    has_undo = await check_has_undo(user_id)
    try: await call.message.edit_text(f"<b>📝 SUBTITLE EDITOR</b>\n━━━━━━━━━━━━━━━━━━━━\n📊 Total: <code>{total_lines}</code> | Lokasi: #{line_idx}", reply_markup=get_editor_kb(lines, target_page, pages, user_id, lang, has_undo), parse_mode="HTML")
    except TelegramBadRequest: pass

@router.callback_query(F.data.startswith("sub_pg_"))
async def handle_pagination(call: CallbackQuery):
    parts = call.data.split("_")
    user_id, page = int(parts[2]), int(parts[3])
    lines = await get_subtitle_page(user_id, page=page, limit=5)
    total = await get_total_sub_lines(user_id)
    pages = (total // 5) + (1 if total % 5 > 0 else 0)
    lang = get_active_settings(user_id).get("ai_subtitle", {}).get("target_lang", "id")
    has_undo = await check_has_undo(user_id)
    try: await call.message.edit_text(f"<b>📝 SUBTITLE EDITOR</b>\n━━━━━━━━━━━━━━━━━━━━\n📊 Total: <code>{total} Baris</code>", reply_markup=get_editor_kb(lines, page, pages, user_id, lang, has_undo), parse_mode="HTML")
    except TelegramBadRequest: pass 
    await call.answer()

@router.callback_query(F.data.startswith("sub_focus_"))
async def handle_focus(call: CallbackQuery):
    parts = call.data.split("_")
    user_id, line_idx = int(parts[2]), int(parts[3])
    line_data = await get_single_sub_line(user_id, line_idx)
    cur_page = await get_current_page(user_id, line_idx)
    safe_text = html.escape(str(line_data.get('text', ''))) 
    text = f"<b>🛠 EDITING BARIS #{line_idx}</b>\n────────────────────\n⏰ <b>Waktu:</b> <code>{line_data.get('start')} --> {line_data.get('end')}</code>\n💬 <b>Teks:</b> <code>{safe_text}</code>\n────────────────────"
    await call.message.edit_text(text, reply_markup=get_focus_kb(user_id, line_idx, cur_page), parse_mode="HTML")
    await call.answer()

@router.callback_query(F.data.startswith("sub_adj_"))
async def handle_adjust_time(call: CallbackQuery):
    parts = call.data.split("_")
    user_id, line_idx, ms = int(parts[2]), int(parts[3]), int(parts[4])
    line = await get_single_sub_line(user_id, line_idx)
    st = pysrt.SubRipTime.from_string(str(line.get("start", "00:00:00,000")).replace('.', ','))
    et = pysrt.SubRipTime.from_string(str(line.get("end", "00:00:00,000")).replace('.', ','))
    st.shift(milliseconds=ms)
    et.shift(milliseconds=ms)
    db = get_db()
    await db.db["subtitle_temp"].update_one({"user_id": user_id, "index": line_idx}, {"$set": {"start": str(st).replace(',', '.'), "end": str(et).replace(',', '.')}})
    await call.answer(f"✅ Digeser {ms}ms")
    cur_page = await get_current_page(user_id, line_idx)
    line_data = await get_single_sub_line(user_id, line_idx)
    safe_text = html.escape(str(line_data.get('text', '')))
    try: await call.message.edit_text(f"<b>🛠 EDITING BARIS #{line_idx}</b>\n────────────────────\n⏰ <b>Waktu:</b> <code>{line_data.get('start')} --> {line_data.get('end')}</code>\n💬 <b>Teks:</b> <code>{safe_text}</code>\n────────────────────", reply_markup=get_focus_kb(user_id, line_idx, cur_page), parse_mode="HTML")
    except TelegramBadRequest: pass

@router.callback_query(F.data.startswith("sub_edit_tr_"))
async def handle_translate_line(call: CallbackQuery):
    parts = call.data.split("_")
    user_id, line_idx = int(parts[3]), int(parts[4])
    line = await get_single_sub_line(user_id, line_idx)
    lang = get_active_settings(user_id).get("ai_subtitle", {}).get("target_lang", "id")
    await call.answer(f"⏳ Menerjemahkan ke {lang.upper()}...", show_alert=False)
    translated = await asyncio.to_thread(GoogleTranslator(source='auto', target=lang).translate, str(line.get("text", "")))
    db = get_db()
    await db.db["subtitle_temp"].update_one({"user_id": user_id, "index": line_idx}, {"$set": {"text": translated}})
    cur_page = await get_current_page(user_id, line_idx)
    line_data = await get_single_sub_line(user_id, line_idx)
    safe_text = html.escape(str(line_data.get('text', '')))
    await call.message.edit_text(f"<b>🛠 EDITING BARIS #{line_idx}</b>\n────────────────────\n⏰ <b>Waktu:</b> <code>{line_data.get('start')} --> {line_data.get('end')}</code>\n💬 <b>Teks:</b> <code>{safe_text}</code>\n────────────────────", reply_markup=get_focus_kb(user_id, line_idx, cur_page), parse_mode="HTML")

@router.callback_query(F.data.startswith("sub_edit_txt_"))
async def handle_edit_text_prompt(call: CallbackQuery):
    parts = call.data.split("_")
    user_id, line_idx = int(parts[3]), int(parts[4])
    prompt = await call.message.answer(f"📝 **Kirimkan teks baru untuk baris #{line_idx}:**", reply_markup=get_cancel_kb())
    try: res = await wait_for_message(call.message.chat.id, user_id, 120)
    except asyncio.TimeoutError: res = None
    if not res or res.text.lower() == "batal":
        await prompt.delete()
        return await call.message.answer("Batal.", reply_markup=ReplyKeyboardRemove())
    db = get_db()
    await db.db["subtitle_temp"].update_one({"user_id": user_id, "index": line_idx}, {"$set": {"text": res.text}})
    await prompt.delete()
    await res.delete()
    temp = await call.message.answer("✅ Teks diperbarui!", reply_markup=ReplyKeyboardRemove())
    await asyncio.sleep(1)
    await temp.delete()
    cur_page = await get_current_page(user_id, line_idx)
    line_data = await get_single_sub_line(user_id, line_idx)
    safe_text = html.escape(str(line_data.get('text', '')))
    try: await call.message.edit_text(f"<b>🛠 EDITING BARIS #{line_idx}</b>\n────────────────────\n⏰ <b>Waktu:</b> <code>{line_data.get('start')} --> {line_data.get('end')}</code>\n💬 <b>Teks:</b> <code>{safe_text}</code>\n────────────────────", reply_markup=get_focus_kb(user_id, line_idx, cur_page), parse_mode="HTML")
    except TelegramBadRequest: pass

@router.callback_query(F.data.startswith("sub_setlang_"))
async def handle_set_lang(call: CallbackQuery):
    user_id = int(call.data.split("_")[2])
    prompt = await call.message.answer("🌐 **Masukkan kode bahasa target:**\n(Contoh: `id`, `en`, `ja`)", reply_markup=get_cancel_kb())
    try: res = await wait_for_message(call.message.chat.id, user_id, 60)
    except asyncio.TimeoutError: res = None
    if not res or res.text.lower() == "batal":
        await prompt.delete()
        return await call.message.answer("Batal.", reply_markup=ReplyKeyboardRemove())
    new_lang = res.text.strip().lower()
    async with _DATA_LOCK:
        active = DATA.get(user_id, {}).get("active_profile", "Default")
        if "profiles" not in DATA[user_id]: DATA[user_id]["profiles"] = {}
        if active not in DATA[user_id]["profiles"]: DATA[user_id]["profiles"][active] = {}
        if "ai_subtitle" not in DATA[user_id]["profiles"][active]: DATA[user_id]["profiles"][active]["ai_subtitle"] = {}
        DATA[user_id]["profiles"][active]["ai_subtitle"]["target_lang"] = new_lang
    await _save_to_db({user_id: DATA[user_id]})
    await prompt.delete()
    await res.delete()
    temp = await call.message.answer(f"✅ Bahasa diubah ke: `{new_lang}`", reply_markup=ReplyKeyboardRemove())
    await asyncio.sleep(1)
    await temp.delete()
    lines = await get_subtitle_page(user_id, page=1, limit=5)
    total = await get_total_sub_lines(user_id)
    pages = (total // 5) + (1 if total % 5 > 0 else 0)
    has_undo = await check_has_undo(user_id)
    try: await call.message.edit_text(f"<b>📝 SUBTITLE EDITOR</b>\n━━━━━━━━━━━━━━━━━━━━\n📊 Total: <code>{total} Baris</code>", reply_markup=get_editor_kb(lines, 1, pages, user_id, new_lang, has_undo), parse_mode="HTML")
    except TelegramBadRequest: pass

@router.callback_query(F.data.startswith("sub_trall_"))
async def handle_translate_all(call: CallbackQuery):
    user_id = int(call.data.split("_")[2])
    if call.from_user.id != user_id: return await call.answer("Bukan milikmu!", show_alert=True)
    
    # [NEW v3.1] Cek Saldo Poin sebelum mengeksekusi "Translate All"
    payment = await process_payment(user_id, "autotranslate")
    if not payment["success"]:
        return await call.answer("❌ Saldo Poin tidak cukup! Fitur ini membutuhkan 500 Poin.", show_alert=True)

    await save_undo_state(user_id) # Backup
    lang = get_active_settings(user_id).get("ai_subtitle", {}).get("target_lang", "id")
    status_msg = await call.message.edit_text(f"⏳ <b>Menerjemahkan ke {lang.upper()} di latar belakang...</b>", parse_mode="HTML")
    
    db = get_db()
    all_lines = await db.db["subtitle_temp"].find({"user_id": user_id}).to_list(length=None)
    translator = GoogleTranslator(source='auto', target=lang)
    count = 0
    
    from pymongo import UpdateOne # [OPTIMIZATION] Bulk Write
    bulk_ops = []

    for line in all_lines:
        # [FIX] Eksekusi translasi massal harus di-batch agar tidak diblokir Google API
        try:
            translated = await asyncio.to_thread(translator.translate, str(line.get("text", "")))
            bulk_ops.append(UpdateOne({"_id": line["_id"]}, {"$set": {"text": translated}}))
            count += 1
            if count % 10 == 0: 
                await asyncio.sleep(1) # [FIX] Tambah delay untuk menghindari rate limit Google Translate API
        except Exception as e:
             LOGGER.error(f"Translation Error on line {line.get('index')}: {e}")
             
    if bulk_ops:
         await db.db["subtitle_temp"].bulk_write(bulk_ops)
         
    await status_msg.edit_text(f"✅ <b>Berhasil menerjemahkan {count} baris!</b>", parse_mode="HTML")

@router.callback_query(F.data.startswith("sub_rsall_"))
async def handle_resync_all(call: CallbackQuery):
    user_id = int(call.data.split("_")[2])
    prompt = await call.message.answer("⏳ <b>RESYNC SEMUA BARIS</b>\nKetik jumlah milidetik (ms).", reply_markup=get_cancel_kb(), parse_mode="HTML")
    try: res = await wait_for_message(call.message.chat.id, user_id, 60)
    except asyncio.TimeoutError: res = None
    if not res or res.text.lower() == "batal":
        await prompt.delete()
        return await call.message.answer("Batal.", reply_markup=ReplyKeyboardRemove())
    try: ms_shift = int(res.text.strip())
    except ValueError:
        await prompt.delete()
        return await call.message.answer("❌ Harus angka bulat.", reply_markup=ReplyKeyboardRemove())
    
    await save_undo_state(user_id) # Backup
    status_msg = await call.message.edit_text(f"⏳ <b>Memproses Resync {ms_shift}ms...</b>", parse_mode="HTML")
    await call.message.answer("Memulai...", reply_markup=ReplyKeyboardRemove())
    
    db = get_db()
    all_lines = await db.db["subtitle_temp"].find({"user_id": user_id}).to_list(length=None)
    count = 0
    
    from pymongo import UpdateOne # [OPTIMIZATION] Bulk Write
    bulk_ops = []

    for line in all_lines:
        st = pysrt.SubRipTime.from_string(str(line.get("start", "00:00:00,000")).replace('.', ','))
        et = pysrt.SubRipTime.from_string(str(line.get("end", "00:00:00,000")).replace('.', ','))
        st.shift(milliseconds=ms_shift)
        et.shift(milliseconds=ms_shift)
        
        bulk_ops.append(
            UpdateOne(
                {"_id": line["_id"]}, 
                {"$set": {"start": str(st).replace(',', '.'), "end": str(et).replace(',', '.')}}
            )
        )
        count += 1
        
    if bulk_ops:
         await db.db["subtitle_temp"].bulk_write(bulk_ops)
         
    await status_msg.edit_text(f"✅ <b>Berhasil Resync {count} baris!</b>", parse_mode="HTML")

@router.callback_query(F.data.startswith("sub_del_"))
async def handle_delete_line(call: CallbackQuery):
    user_id, line_idx = int(call.data.split("_")[2]), int(call.data.split("_")[3])
    await save_undo_state(user_id) # Backup
    cur_page = await get_current_page(user_id, line_idx)
    
    db = get_db()
    await db.db["subtitle_temp"].delete_one({"user_id": user_id, "index": line_idx})
    await reindex_lines(user_id) # Rapikan Index
    await call.answer("🗑️ Baris dihapus & di-reindex!")
    
    total = await get_total_sub_lines(user_id)
    pages = (total // 5) + (1 if total % 5 > 0 else 0)
    if cur_page > pages and pages > 0: cur_page = pages
    elif pages == 0: cur_page = 1
        
    lines = await get_subtitle_page(user_id, page=cur_page, limit=5)
    lang = get_active_settings(user_id).get("ai_subtitle", {}).get("target_lang", "id")
    has_undo = await check_has_undo(user_id)
    try: await call.message.edit_text(f"<b>📝 SUBTITLE EDITOR</b>\n━━━━━━━━━━━━━━━━━━━━\n📊 Total: <code>{total} Baris</code>", reply_markup=get_editor_kb(lines, cur_page, pages, user_id, lang, has_undo), parse_mode="HTML")
    except TelegramBadRequest: pass

@router.callback_query(F.data.startswith("sub_compile_"))
async def handle_compile(call: CallbackQuery):
    user_id = int(call.data.split("_")[2])
    if call.from_user.id != user_id: return await call.answer("Bukan milikmu!", show_alert=True)
    
    # [NEW v3.1] Menyiapkan gerbang pembayaran untuk kompilasi. Saat ini gratis (karena tidak ada di price list point_manager)
    payment = await process_payment(user_id, "compile")
    if not payment["success"]:
        return await call.answer("❌ Saldo Poin tidak cukup!", show_alert=True)
    
    msg = await call.message.edit_text("⏳ 🏗 **Menyusun file SRT baru...**")
    output_path = await compile_db_to_srt(user_id)
    if output_path and os.path.exists(output_path):
        await call.message.answer_document(document=FSInputFile(output_path), caption="✅ **Kompilasi Berhasil!**")
        await msg.delete()
    else: await call.message.edit_text("❌ Gagal.")

@router.callback_query(F.data.startswith("sub_cancel_"))
async def handle_cancel(call: CallbackQuery):
    user_id = int(call.data.split("_")[2])
    await clear_subtitle_temp(user_id)
    db = get_db()
    await db.db["subtitle_undo"].delete_many({"user_id": user_id})
    await call.message.edit_text("❌ <b>Workspace Ditutup.</b>", parse_mode="HTML")
    await call.answer()
