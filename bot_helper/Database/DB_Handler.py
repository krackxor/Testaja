"""
╔══════════════════════════════════════════════════════════════════════╗
║            bot_helper/Database/DB_Handler.py                         ║
║            Encoder1 Bot — v4.2 (Trinity & SubEdit Update)            ║
╠══════════════════════════════════════════════════════════════════════╣
║  CHANGELOG v4.2:                                                     ║
║  [SECURITY] eval(data_from_db) → json.loads()                        ║
║  [SECURITY] str(dict) serialize → json.dumps()                       ║
║  [FIX HIGH] Connection leak → Singleton pattern                      ║
║  [FIX HIGH] Module-level variables crash NameError → class-level     ║
║  [FIX]      Timeout ditambahkan ke AsyncIOMotorClient                ║
║  [FIX]      valu==False → not valu                                   ║
║  [FIX]      find_one() None → guard sebelum .get()                   ║
║  [FIX]      LOGGER.info(e) → LOGGER.error(..., exc_info=True)        ║
║  [FIX]      Index 'id' dibuat saat connect                           ║
║  [IMPROVE]  Date disimpan sebagai datetime object bukan string       ║
║  [IMPROVE]  Retry logic untuk transient network errors               ║
║  [IMPROVE]  Ekspos properti `self.db` untuk custom collection        ║
╚══════════════════════════════════════════════════════════════════════╝
"""

# ── Standard Library ──────────────────────────────────────────────────
import asyncio
import json
from datetime import datetime

# ── Third Party ───────────────────────────────────────────────────────
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.errors import (
    ConnectionFailure,
    ServerSelectionTimeoutError,
    OperationFailure,
)
from pytz import timezone

# ── Internal ──────────────────────────────────────────────────────────
from config.config import Config

LOGGER = Config.LOGGER
IST    = timezone(Config.TIMEZONE)

# ── Konstanta ─────────────────────────────────────────────────────────
_DB_TIMEOUT_MS = 5_000    # 5 detik timeout koneksi
_MAX_RETRY     = 3        # Max retry untuk transient errors
_RETRY_DELAY   = 2.0      # Detik delay antar retry


# ═══════════════════════════════════════════════════════════════════════
#  HELPER FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════

def _serialize(data) -> str:
    """
    [SECURITY] Serialize data ke JSON string.
    Sebelumnya: str(dict) menghasilkan Python repr — membutuhkan eval() untuk baca kembali.
    Sekarang: json.dumps() menghasilkan valid JSON — dibaca dengan json.loads() yang aman.
    """
    if isinstance(data, str):
        # Validasi sudah JSON atau konversi dari Python repr lama
        try:
            json.loads(data)
            return data          # Sudah valid JSON
        except json.JSONDecodeError:
            try:
                # Coba parse sebagai Python literal (data lama dari str(dict))
                import ast
                parsed = ast.literal_eval(data)
                return json.dumps(parsed, ensure_ascii=False)
            except Exception:
                return data      # Kembalikan apa adanya jika gagal
    elif isinstance(data, dict):
        return json.dumps(data, ensure_ascii=False)
    else:
        return json.dumps(data, ensure_ascii=False)


def _deserialize(data: str | None) -> dict:
    """
    [SECURITY] Deserialize data dari database.
    Sebelumnya: eval() — bisa execute arbitrary code.
    Sekarang: json.loads() — aman, hanya parse JSON.

    Handle backward compat: data lama mungkin Python repr string (dari str(dict)).
    """
    if data is None:
        return {}
    if isinstance(data, dict):
        return data  # Motor kadang return dict langsung

    try:
        return json.loads(data)
    except (json.JSONDecodeError, TypeError):
        # [BACKWARD COMPAT] Data lama disimpan sebagai Python repr str(dict)
        # Gunakan ast.literal_eval yang aman (tidak execute code, hanya parse literals)
        try:
            import ast
            result = ast.literal_eval(data)
            if isinstance(result, dict):
                LOGGER.warning(
                    "⚠️  Data lama (Python repr) ditemukan di DB — "
                    "akan otomatis dikonversi ke JSON saat update berikutnya."
                )
                return result
        except Exception as e:
            LOGGER.error(f"❌ Gagal deserialize data DB: {e} — data: {str(data)[:100]}")
        return {}


async def _retry_db_op(coro_func, *args, max_retry: int = _MAX_RETRY, **kwargs):
    """
    [IMPROVE] Retry wrapper untuk operasi MongoDB.
    Handle transient network errors dengan exponential backoff.
    """
    last_error = None
    for attempt in range(1, max_retry + 1):
        try:
            return await coro_func(*args, **kwargs)
        except (ConnectionFailure, ServerSelectionTimeoutError) as e:
            last_error = e
            if attempt < max_retry:
                wait = _RETRY_DELAY * attempt
                LOGGER.warning(
                    f"⚠️  DB transient error (attempt {attempt}/{max_retry}), "
                    f"retry dalam {wait:.0f}s: {e}"
                )
                await asyncio.sleep(wait)
            else:
                LOGGER.error(f"❌ DB gagal setelah {max_retry} retry: {e}")
        except Exception as e:
            # Non-transient error — jangan retry
            raise e
    raise last_error


# ═══════════════════════════════════════════════════════════════════════
#  DATABASE CLASS — SINGLETON PATTERN
# ═══════════════════════════════════════════════════════════════════════

class Database:
    """
    Async MongoDB handler dengan Singleton connection.

    [FIX HIGH] Connection leak: sebelumnya setiap Database() buat koneksi baru.
    Sekarang: satu koneksi shared (Motor sudah built-in connection pooling).

    Usage:
        db = Database()          # Singleton — koneksi dibuat sekali
        await db.save_data(...)  # Gunakan koneksi yang sama
    """

    # [FIX HIGH] Class-level client — dibuat sekali, dipakai semua instance
    _client: AsyncIOMotorClient | None = None
    _db      = None
    _initialized: bool = False

    def __init__(self):
        # [FIX HIGH] Pindah dari module-level variables ke class-level
        # Sebelumnya: mongodb_url di module level crash NameError jika SAVE_TO_DATABASE=False
        if not Config.SAVE_TO_DATABASE:
            LOGGER.warning("⚠️  Database dibuat tapi SAVE_TO_DATABASE=False")
            return

        # Validasi config
        if not Config.MONGODB_URI:
            raise ValueError("MONGODB_URI kosong — tidak bisa connect ke database")

        # [IMPROVE] Validasi collection_name
        if not Config.COLLECTION_NAME:
            raise ValueError("COLLECTION_NAME kosong — tidak bisa akses collection")

        # [FIX HIGH] Singleton — buat client hanya sekali
        if Database._client is None:
            LOGGER.info("🔵 Membuat MongoDB connection pool baru...")
            Database._client = AsyncIOMotorClient(
                Config.MONGODB_URI,
                serverSelectionTimeoutMS=_DB_TIMEOUT_MS,   # [FIX] timeout
                connectTimeoutMS=_DB_TIMEOUT_MS,
                socketTimeoutMS=10_000,
                maxPoolSize=10,     # Connection pool size
                minPoolSize=1,
            )
            Database._db = Database._client[Config.NAME]
            LOGGER.info("✅ MongoDB client dibuat (singleton)")

        self._client          = Database._client
        self.db               = Database._db
        self.bot_username     = Config.NAME
        self.save_id          = Config.SAVE_ID
        self.collection_name  = Config.COLLECTION_NAME

    async def initialize(self) -> bool:
        """
        [NEW] Inisialisasi: test koneksi + buat index.
        Harus dipanggil sekali saat startup bot.

        Returns:
            True jika berhasil, False jika gagal
        """
        if Database._initialized:
            return True

        if not Config.SAVE_TO_DATABASE:
            return True

        try:
            # Test koneksi
            await self._client.admin.command("ping")
            LOGGER.info("✅ MongoDB connection test berhasil")

            # [FIX] Buat index pada field 'id' — tanpa ini setiap query = full scan
            col = self.db[self.collection_name]
            await col.create_index("id", unique=True)
            LOGGER.info(f"✅ MongoDB index dibuat untuk collection '{self.collection_name}'")

            Database._initialized = True
            return True

        except ServerSelectionTimeoutError:
            LOGGER.error(
                f"❌ MongoDB tidak bisa diakses (timeout {_DB_TIMEOUT_MS}ms). "
                "Cek MONGODB_URI dan network."
            )
            return False
        except Exception as e:
            LOGGER.error(f"❌ MongoDB initialization error: {e}", exc_info=True)
            return False

    def _col(self, collection: str | None = None):
        """Helper: return collection object."""
        name = collection or self.collection_name
        if not name:
            raise ValueError("Collection name kosong")
        return self.db[name]

    # ── CRUD Operations ──────────────────────────────────────────────

    async def save_data(self, datam: str | dict) -> bool:
        """
        Simpan atau update data ke MongoDB.

        [SECURITY] eval() → json.loads() dan json.dumps()
        [FIX]      LOGGER.info → LOGGER.error dengan exc_info
        [IMPROVE]  Retry untuk transient errors
        [IMPROVE]  Date disimpan sebagai datetime object
        """
        if not Config.SAVE_TO_DATABASE:
            return True

        try:
            col    = self._col()
            exists = await self.is_data_exist(self.save_id, self.collection_name)

            if not exists:
                # [IMPROVE] Date sebagai datetime object bukan string
                document = {
                    "id":   self.save_id,
                    "data": _serialize(datam),
                    "date": datetime.now(IST),   # [FIX] datetime object, bukan string
                }
                await _retry_db_op(col.insert_one, document)
                LOGGER.info(f"✅ Data baru disimpan ke DB (id: {self.save_id})")
                return True

            else:
                # Merge data lama dengan data baru
                existing_raw = await self.get_data(self.save_id, self.collection_name)

                # [SECURITY] Tidak lagi pakai eval() — pakai _deserialize() yang aman
                dict_existing = _deserialize(existing_raw)
                dict_new      = _deserialize(datam) if isinstance(datam, str) else (datam if isinstance(datam, dict) else {})

                if dict_existing == dict_new:
                    return True   # Tidak ada perubahan

                dict_existing.update(dict_new)
                merged = _serialize(dict_existing)
                await self.update_data(merged, self.save_id, self.collection_name)
                return True

        except (ConnectionFailure, ServerSelectionTimeoutError) as e:
            LOGGER.error(f"❌ DB connection error saat save_data: {e}", exc_info=True)
            return False
        except Exception as e:
            LOGGER.error(f"❌ save_data error: {e}", exc_info=True)
            return False

    async def is_data_exist(self, id: str, colz: str) -> bool:
        """
        Cek apakah document dengan id tertentu ada.

        [IMPROVE] Pakai count_documents({...}, limit=1) lebih efisien dari find_one
        """
        try:
            col   = self._col(colz)
            count = await col.count_documents({"id": id}, limit=1)
            return count > 0
        except Exception as e:
            LOGGER.error(f"❌ is_data_exist error: {e}", exc_info=True)
            return False

    async def get_data(self, id: str, colz: str) -> str | None:
        """
        Ambil data dari MongoDB.

        [FIX] Guard: find_one() bisa return None → user.get() crash AttributeError
        """
        try:
            col  = self._col(colz)
            user = await col.find_one({"id": id})
            if not user:
                return None
            return user.get("data")
        except Exception as e:
            LOGGER.error(f"❌ get_data error: {e}", exc_info=True)
            return None

    async def update_data(self, datam: str | dict, id: str, colz: str) -> bool:
        """
        Update data yang sudah ada.

        [IMPROVE] Date disimpan sebagai datetime object
        [IMPROVE] Retry untuk transient errors
        """
        try:
            col        = self._col(colz)
            serialized = _serialize(datam) if isinstance(datam, dict) else datam
            await _retry_db_op(
                col.update_one,
                {"id": id},
                {"$set": {
                    "data": serialized,
                    "date": datetime.now(IST),   # [FIX] datetime object
                }},
            )
            return True
        except Exception as e:
            LOGGER.error(f"❌ update_data error: {e}", exc_info=True)
            return False

    async def get_data_as_dict(self, id: str, colz: str) -> dict:
        """
        [NEW] Convenience method — ambil data dan langsung deserialize ke dict.
        Eliminates need for callers to call json.loads() themselves.
        """
        raw = await self.get_data(id, colz)
        return _deserialize(raw)

    async def delete_data(self, id: str, colz: str) -> bool:
        """
        [NEW] Hapus document dari collection.
        Fungsi ini ada di kode lama tapi di-comment. Diaktifkan kembali.
        """
        try:
            col = self._col(colz)
            result = await col.delete_one({"id": id})
            deleted = result.deleted_count > 0
            if deleted:
                LOGGER.info(f"✅ Data dihapus (id: {id}, collection: {colz})")
            return deleted
        except Exception as e:
            LOGGER.error(f"❌ delete_data error: {e}", exc_info=True)
            return False

    async def close(self) -> None:
        """
        [NEW] Tutup koneksi MongoDB dengan bersih.
        Panggil saat bot shutdown.
        """
        if Database._client is not None:
            Database._client.close()
            Database._client = None
            Database._db     = None
            Database._initialized = False
            LOGGER.info("✅ MongoDB connection ditutup")

    async def health_check(self) -> dict:
        """
        [NEW] Check status koneksi database untuk /settings atau monitoring.

        Returns:
            dict: {ok: bool, latency_ms: float, error: str|None}
        """
        if not Config.SAVE_TO_DATABASE:
            return {"ok": True, "latency_ms": 0, "error": None, "note": "DB tidak diaktifkan"}

        try:
            start  = asyncio.get_event_loop().time()
            await self._client.admin.command("ping")
            latency = (asyncio.get_event_loop().time() - start) * 1000
            return {"ok": True, "latency_ms": round(latency, 2), "error": None}
        except Exception as e:
            return {"ok": False, "latency_ms": -1, "error": str(e)}


# ═══════════════════════════════════════════════════════════════════════
#  MODULE-LEVEL SINGLETON INSTANCE
# ═══════════════════════════════════════════════════════════════════════

# Instance tunggal yang dipakai di seluruh bot
# Import: from bot_helper.Database.DB_Handler import db_client
db_client: Database | None = None

def get_db() -> Database | None:
    """
    [NEW] Getter untuk database singleton.
    Lazily initialize jika belum dibuat.
    """
    global db_client
    if db_client is None and Config.SAVE_TO_DATABASE:
        db_client = Database()
    return db_client
