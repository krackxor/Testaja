Tentu, Mas Khoirul! Kita perlu memperbarui *database* harga di "Mesin Kasir" agar sistem poin Anda bisa memotong saldo pengguna saat mereka menggunakan fitur Cloud Upload yang baru saja kita tambahkan (`/gofile`, `/pixeldrain`, dll).

### 💡 Apa yang Berubah di Versi 1.4 ini?
1. **Penambahan Harga Cloud**: Memasukkan `gofile`, `pixeldrain`, `buzzheavier`, `terabox`, `vimeo`, dan `rclone` ke dalam `PRICE_LIST`.
2. **Kategori Baru**: Saya membuatkan kategori khusus di komentar (Tier 6) agar daftar harga Anda tetap rapi dan mudah diatur kelak.

Berikut adalah **`bot_helper/Process/point_manager.py` — Versi 1.4**. Silakan timpa seluruh isinya:

```python
"""
╔══════════════════════════════════════════════════════════════════════╗
║    bot_helper/Process/point_manager.py — v1.4 (KASIR STUDIO FINAL)   ║
║    Sistem Manajemen Saldo Poin & Harga Fitur (Pay-As-You-Go)         ║
╠══════════════════════════════════════════════════════════════════════╣
║  CHANGELOG v1.4:                                                     ║
║  [NEW]  Menambahkan harga untuk Cloud Uploads (GoFile, PxDrain, dll) ║
║  [FITUR] Katalog Harga Dinamis (Per MB) & Flat Rate (Per Tugas).     ║
║  [FITUR] Fungsi Cek Saldo & Potong Saldo Otomatis.                   ║
║  [FITUR] Keamanan Transaksi (Thread-Safe / Mencegah saldo minus).    ║
║  [FITUR] Pencatatan Riwayat Transaksi (History Mutasi).              ║
║  [FIX]   Bypass Poin: Owner & Admin (SUDO) 100% Gratis & Unlimited.  ║
╚══════════════════════════════════════════════════════════════════════╝
"""

# [NEW] Mengambil fungsi keamanan database langsung dari User_Data.py
from bot_helper.Database.User_Data import get_user_balance, deduct_user_balance, add_usage_history
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
    
    # ☁️ TIER 5: CLOUD UPLOAD & MIRRORING (500 Poin)
    "gofile": 500,
    "pixeldrain": 500,
    "buzzheavier": 500,
    "terabox": 500,
    "vimeo": 500,
    "rclone": 500,
    
    # 📥 TIER 6: DYNAMIC BANDWIDTH (Tarif Dasar Per MB)
    "leech_per_mb": 3,
    "mirror_per_mb": 3
}

# ==========================================
# 2. FUNGSI INTI KEUANGAN (TRANSAKSI)
# ==========================================

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
    Fungsi utama kasir: Mengecek hak akses, mengecek harga, dan memotong saldo.
    Mengembalikan dict: {"success": bool, "cost": int, "message": str}
    """
    
    # 👑 1. [CEK AKSES ADMIN] Jika user adalah Admin/Owner, langsung loloskan gratis!
    if user_id in Config.SUDO_USERS:
        return {
            "success": True, 
            "cost": 0, 
            "message": "👑 **Akses Admin:** Bypass sistem poin (Gratis)."
        }

    # -- PROSES UNTUK USER REGULER --
    
    cost = await calculate_cost(command, file_size_mb)
    friendly_name = command.replace("/", "").upper()
    
    # 🆓 2. [CEK FITUR GRATIS]
    if cost == 0:
        return {"success": True, "cost": 0, "message": "Fitur ini gratis."}

    # 💳 3. [CEK SALDO]
    current_balance = get_user_balance(user_id)
    
    if current_balance < cost:
        return {
            "success": False, 
            "cost": cost, 
            "message": f"❌ **Saldo Poin tidak cukup!**\n\n💎 Harga Proses: `{cost:,}` Poin\n💳 Saldo Anda: `{current_balance:,}` Poin\n\n<i>Silakan Top-Up melalui menu /verify untuk menambah saldo.</i>"
        }
        
    # 💸 4. [POTONG SALDO]
    is_success = await deduct_user_balance(user_id, cost, dbsave=True)
    
    if is_success:
        # 📝 5. [CATAT RIWAYAT TRANSAKSI]
        await add_usage_history(user_id, friendly_name, cost, dbsave=True)
        
        new_balance = get_user_balance(user_id)
        return {
            "success": True, 
            "cost": cost, 
            "message": f"✅ Pembayaran berhasil. Saldo dipotong `{cost:,}` Poin.\n💳 Sisa Saldo: `{new_balance:,}` Poin"
        }
    else:
        return {
            "success": False, 
            "cost": cost, 
            "message": "❌ Transaksi gagal (Terjadi kesalahan sinkronisasi sistem)."
        }
```
