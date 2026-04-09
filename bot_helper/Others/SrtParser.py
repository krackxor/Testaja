import pysrt
from bot_helper.Database.User_Data import DATA # Sesuaikan dengan variabel DB Anda

async def parse_srt_to_db(user_id: int, srt_path: str):
    """Membaca file SRT dan menyimpannya ke koleksi subtitle_temp di MongoDB."""
    subs = pysrt.open(srt_path)
    lines_data = []
    
    # Bersihkan data lama user jika ada
    await DATA.subtitle_temp.delete_many({"user_id": user_id})
    
    for sub in subs:
        lines_data.append({
            "user_id": user_id,
            "index": sub.index,
            "start": str(sub.start),
            "end": str(sub.end),
            "text": sub.text,
            "start_ms": sub.start.ordinal, # Untuk mempermudah Resync
            "end_ms": sub.end.ordinal
        })
    
    if lines_data:
        # Gunakan insert_many untuk kecepatan (bulk upload)
        await DATA.subtitle_temp.insert_many(lines_data)
        
    return len(lines_data)
