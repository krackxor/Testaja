# Di dalam bot_helper/Others/SrtParser.py
import pysrt
from bot_helper.Database.DB_Handler import get_db
from config.config import Config

LOGGER = Config.LOGGER

async def parse_srt_to_db(user_id: int, srt_path: str) -> int:
    """Membaca file SRT dan menyimpannya ke koleksi subtitle_temp di MongoDB."""
    db = get_db()
    if db is None:
        LOGGER.error("❌ Parse SRT Gagal: DB tidak tersedia.")
        return 0

    try:
        subs = pysrt.open(srt_path)
        lines_data = []
        
        # Bersihkan data lama user jika ada
        await db.db["subtitle_temp"].delete_many({"user_id": user_id})
        
        for sub in subs:
            lines_data.append({
                "user_id": user_id,
                "index": sub.index,
                "start": str(sub.start),
                "end": str(sub.end),
                "text": sub.text,
                "start_ms": sub.start.ordinal,
                "end_ms": sub.end.ordinal
            })
        
        if lines_data:
            # Gunakan insert_many untuk kecepatan (bulk upload)
            await db.db["subtitle_temp"].insert_many(lines_data)
            
        return len(lines_data)
    except Exception as e:
        LOGGER.error(f"❌ Error saat parsing SRT: {e}", exc_info=True)
        return 0
