import pysrt
import os
from bot_helper.Database.User_Data import DATA

async def compile_db_to_srt(user_id: int):
    """Mengambil data dari DB dan menjadikannya file SRT."""
    # Ambil semua baris milik user, urutkan berdasarkan index
    cursor = DATA.subtitle_temp.find({"user_id": user_id}).sort("index", 1)
    lines = await cursor.to_list(length=None)
    
    if not lines:
        return None
        
    new_subs = pysrt.SubRipFile()
    
    for i, line in enumerate(lines, start=1):
        item = pysrt.SubRipItem(
            index=i,
            start=pysrt.SubRipTime.from_string(line["start"]),
            end=pysrt.SubRipTime.from_string(line["end"]),
            text=line["text"]
        )
        new_subs.append(item)
    
    output_path = f"./temp/edited_{user_id}.srt"
    new_subs.save(output_path, encoding='utf-8')
    
    # Opsional: Hapus data di DB setelah kompilasi selesai agar hemat storage
    # await DATA.subtitle_temp.delete_many({"user_id": user_id})
    
    return output_path
