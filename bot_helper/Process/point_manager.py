"""
╔══════════════════════════════════════════════════════════════════════╗
║    bot_helper/Process/point_manager.py — v1.0 (KASIR STUDIO)         ║
║    Sistem Manajemen Saldo Poin & Harga Fitur (Pay-As-You-Go)         ║
╠══════════════════════════════════════════════════════════════════════╣
║  [FITUR] Katalog Harga Dinamis & Flat Rate.                          ║
║  [FITUR] Fungsi Cek Saldo & Potong Saldo Otomatis.                   ║
║  [FITUR] Keamanan Transaksi (Mencegah saldo minus).                  ║
╚══════════════════════════════════════════════════════════════════════╝
"""

from bot_helper.Database.DB_Handler import get_db
from config.config import Config

LOGGER = Config.LOGGER

# ==========================================
# 1. KATALOG HARGA (PRICE LIST)
# ==========================================

PRICE_LIST = {
    # 💎 TIER 1: HEAVY DUTY & COMBO (7.000 Poin)
    "encode": 7000,
    "customencode": 7000,
    "autosub": 7000,
    "recap": 7000,
    "clip": 7000,
    "toptier": 7000,
    "verdict": 7000,
    "lore": 7000,
    "radar": 7000,
    "patch": 7000,
    "archives": 7000,

    # 🗜️ TIER 2: HIGH-MID EDITOR (5.000 Poin)
    "compress": 5000,
    "merge": 5000,
    "dubbing": 5000,
    "watermark": 5000,
    "hardmux": 5000,
    "convert": 5000,

    # 🎨 TIER 3: STANDARD EDITOR (1.000 Poin)
    "crop": 1000,
    "autocrop": 1000,
    "rotate": 1000,
    "speed": 1000,
    "ytupload": 1000,

    # ✂️ TIER 4: LIGHT EDITOR (Mulai dari 500 Poin ke bawah)
    "trim": 500,
    "cut": 500,
    "split": 500,
    "softmux": 500,
    "softremux": 500,
    "autotranslate": 500,
    "mute": 300,
    "extract": 300,
    "changemetadata": 200,
    "changeindex": 200,
    "extension": 200,
    "genss": 50,
    "gensample": 50,
    
    # 📥 TIER 5: DYNAMIC BANDWIDTH (Tarif Dasar Per MB)
    "leech_per_mb": 3,
    "mirror_per_mb": 3
}

# ==========================================
# 2. FUNGSI INTI KEUANGAN (TRANSAKSI)
# ==========================================

async def get_user_balance(user_id: int) -> int:
    """Mengambil sisa saldo poin pengguna dari Database."""
    db = get_db()
    user_data = await db.db["users"].find_one({"user_id": user_id})
    if not user_data:
        return 0
    return user_data.get("balance_points", 0)

async def add_points(user_id: int, amount: int) -> bool:
    """Menambahkan poin ke akun pengguna (Untuk Top-Up/Verifikasi)."""
    if amount <= 0: return False
    db = get_db()
    
    # Gunakan $inc agar aman jika ada transaksi bersamaan (Thread-Safe)
    result = await db.db["users"].update_one(
        {"user_id": user_id},
        {"$inc": {"balance_points": amount}},
        upsert=True
    )
    return result.modified_count > 0 or result.upserted_id is not None

async def calculate_cost(command: str, file_size_mb: float = 0) -> int:
    """
    Menghitung total biaya poin untuk sebuah perintah.
    Mendukung harga flat (Pukul Rata) dan dinamis (Per-MB).
    """
    cmd = command.lower().replace("/", "")
    
    # Jika fitur Leech / Mirror (Hitung berdasarkan ukuran file)
    if cmd in ["leech", "mirror"]:
        rate = PRICE_LIST.get(f"{cmd}_per_mb", 3)
        return int(file_size_mb * rate)
    
    # Jika fitur Flat Rate
    return PRICE_LIST.get(cmd, 0)

async def process_payment(user_id: int, command: str, file_size_mb: float = 0) -> dict:
    """
    Fungsi utama kasir: Mengecek harga, mencocokkan saldo, dan memotongnya jika cukup.
    Mengembalikan dict: {"success": bool, "cost": int, "message": str}
    """
    cost = await calculate_cost(command, file_size_mb)
    
    # Jika harga 0 (Fitur Gratis / Tidak terdaftar di katalog)
    if cost == 0:
        return {"success": True, "cost": 0, "message": "Fitur ini gratis."}

    # Cek Saldo
    current_balance = await get_user_balance(user_id)
    
    if current_balance < cost:
        return {
            "success": False, 
            "cost": cost, 
            "message": f"❌ Saldo Poin Anda tidak cukup!\n\n💎 Harga Proses: `{cost:,}` Poin\n💳 Saldo Anda: `{current_balance:,}` Poin\n\n<i>Silakan Top-Up melalui menu /verify</i>"
        }
        
    # Potong Saldo (Gunakan $inc dengan nilai minus)
    db = get_db()
    result = await db.db["users"].update_one(
        {"user_id": user_id, "balance_points": {"$gte": cost}}, # Pastikan saldo masih cukup tepat sebelum dipotong
        {"$inc": {"balance_points": -cost}}
    )
    
    if result.modified_count > 0:
        new_balance = current_balance - cost
        return {
            "success": True, 
            "cost": cost, 
            "message": f"✅ Pembayaran berhasil. Saldo dipotong `{cost:,}` Poin.\n💳 Sisa Saldo: `{new_balance:,}` Poin"
        }
    else:
        return {
            "success": False, 
            "cost": cost, 
            "message": "❌ Transaksi gagal. Saldo mungkin berubah saat diproses."
        }
