"""
╔══════════════════════════════════════════════════════════════════════╗
║            bot_helper/Others/SrtCompiler.py — v1.0                   ║
║            Encoder1 Bot — SubEdit Integration                        ║
╠══════════════════════════════════════════════════════════════════════╣
║  CHANGELOG v1.0:                                                     ║
║  [FIX] Menggunakan get_db() Singleton alih-alih variabel DATA.       ║
║  [FIX] Menambahkan validasi dan pembuatan folder ./temp/ otomatis.   ║
║  [FIX] Menambahkan try-except untuk error handling dan Logging.      ║
╚══════════════════════════════════════════════════════════════════════╝
"""

import os
import pysrt
from bot_helper.Database.DB_Handler import get_db
from config.config import Config

LOGGER = Config.LOGGER

async def compile_db_to_srt(user_id: int) -> str | None:
    """
    Mengambil data baris subtitle dari MongoDB dan menyusunnya kembali
    menjadi file fisik berformat .srt yang siap digunakan untuk proses Encode/Hardmux.
    """
    db = get_db()
    if db is None:
        LOGGER.error("❌ Compile SRT Gagal: Koneksi Database tidak tersedia.")
        return None

    try:
        # Ambil semua baris milik user dari koleksi subtitle_temp, urutkan berdasarkan index
        cursor = db.db["subtitle_temp"].find({"user_id": user_id}).sort("index", 1)
        lines = await cursor.to_list(length=None)
        
        if not lines:
            LOGGER.warning(f"⚠️ Tidak ada data subtitle untuk user {user_id} saat kompilasi.")
            return None
            
        # Buat objek file SubRip baru
        new_subs = pysrt.SubRipFile()
        
        # Masukkan setiap baris ke dalam objek file
        for i, line in enumerate(lines, start=1):
            item = pysrt.SubRipItem(
                index=i,
                start=pysrt.SubRipTime.from_string(line["start"]),
                end=pysrt.SubRipTime.from_string(line["end"]),
                text=line["text"]
            )
            new_subs.append(item)
        
        # Pastikan direktori temp tersedia sebelum menyimpan
        os.makedirs("./temp", exist_ok=True)
        
        # Simpan sebagai file fisik
        output_path = f"./temp/edited_{user_id}.srt"
        new_subs.save(output_path, encoding='utf-8')
        
        LOGGER.info(f"✅ Subtitle berhasil dikompilasi ke: {output_path}")
        return output_path

    except Exception as e:
        LOGGER.error(f"❌ Error saat mengompilasi SRT untuk user {user_id}: {e}", exc_info=True)
        return None
