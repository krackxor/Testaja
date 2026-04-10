"""
╔══════════════════════════════════════════════════════════════════════╗
║           bot_helper/FFMPEG/FFMPEG_Status.py                         ║
║           Encoder1 Bot — v3.2 (Anti-Deadlock Update)                 ║
╠══════════════════════════════════════════════════════════════════════╣
║  CHANGELOG dari versi lama:                                          ║
║  [FIX CRITICAL] Mengubah `async for` menjadi loop `readline()`       ║
║  [FIX CRITICAL] Menambahkan Pipe Drainer: Jika terjadi ValueError    ║
║                 (Line too long), sisa log di memori akan disedot dan ║
║                 dibuang agar FFmpeg tidak membeku/stuck selamanya.   ║
║  [FIX HIGH]  File log dibuka tiap baris → buka sekali di luar loop   ║
║  [FIX]       check_running_process throttle (tiap 50 baris)          ║
║  [NEW]       read_progress() — parse -progress log untuk persen      ║
║  [NEW]       get_progress_info() — return dict lengkap progress      ║
║  [IMPROVE]   process_logs dipakai sebagai ring buffer (max 100)      ║
╚══════════════════════════════════════════════════════════════════════╝
"""

# ── Standard Library ──────────────────────────────────────────────────
import time
from collections import deque
from os.path import exists, getsize

# ── Third Party ───────────────────────────────────────────────────────
from aiofiles import open as aio_open

# ── Internal ──────────────────────────────────────────────────────────
from bot_helper.Others.Names import Names
from bot_helper.Process.Running_Process import check_running_process
from config.config import Config

LOGGER = Config.LOGGER

# ── Konstanta ─────────────────────────────────────────────────────────
# Cek cancel setiap N baris stderr — cegah overhead DB query tiap baris
_CANCEL_CHECK_INTERVAL = 50
# Max baris yang disimpan di memory (ring buffer)
_MAX_LOG_BUFFER        = 100


# ═══════════════════════════════════════════════════════════════════════
#  FFMPEG STATUS CLASS
# ═══════════════════════════════════════════════════════════════════════

class FfmpegStatus:
    """
    Tracking status dan log untuk satu proses FFmpeg.
    
    Attributes:
        returncode: None = belum selesai, 0 = sukses, non-zero = error
        process_logs: Ring buffer 100 baris terakhir stderr FFmpeg
    """

    def __init__(
        self,
        process,
        log_file: str,
        input_file: str,
        output_file: str,
        duration: float,
    ):
        self.process         = process
        self.name            = input_file.split("/")[-1]
        self.log_file        = log_file       # Path file -progress dari FFmpeg
        self.input_file      = input_file
        self.input_file_size = getsize(input_file)
        self.output_file     = output_file
        self.duration        = duration

        # [FIX] IMPROVE: pakai deque sebagai ring buffer (bukan list tak terbatas)
        # deque(maxlen=100) otomatis hapus entri lama jika buffer penuh
        self.process_logs: deque = deque(maxlen=_MAX_LOG_BUFFER)

        # [FIX] None = belum selesai (bukan False yang ambigu dengan returncode 0)
        self.returncode: int | None = None

        # Timestamp mulai untuk tracking durasi proses
        self._start_time: float = time.time()

    # ── Properties ──────────────────────────────────────────────────

    def input_size(self) -> int:
        """Return ukuran file input dalam bytes."""
        return self.input_file_size

    def output_size(self) -> int:
        """
        Return ukuran file output dalam bytes.
        [FIX] bare except → except (OSError, FileNotFoundError)
        """
        try:
            return getsize(self.output_file)
        except (OSError, FileNotFoundError):
            return 0

    def type(self) -> str:
        """Return tipe proses."""
        return Names.ffmpeg

    def elapsed_seconds(self) -> float:
        """Return berapa detik proses sudah berjalan."""
        return time.time() - self._start_time

    def is_done(self) -> bool:
        """Return True jika proses sudah selesai (sukses atau gagal)."""
        return self.returncode is not None

    def is_success(self) -> bool:
        """Return True jika proses selesai dengan sukses."""
        return self.returncode == 0

    def save_log(self, line: str) -> None:
        """Simpan baris log ke ring buffer."""
        self.process_logs.append(line)

    def get_last_logs(self, n: int = 10) -> list[str]:
        """Return N baris terakhir dari log buffer."""
        logs = list(self.process_logs)
        return logs[-n:] if len(logs) >= n else logs

    # ── Progress Parsing ─────────────────────────────────────────────

    def read_progress(self) -> dict:
        """
        [NEW] Parse file -progress yang dibuat FFmpeg.
        
        FFmpeg dengan flag -progress <file> menulis key=value lines seperti:
            out_time_ms=12345678
            speed=1.23x
            fps=29.97
            progress=continue / end
        
        Return dict dengan progress info, atau {} jika belum ada data.
        """
        if not self.log_file or not exists(self.log_file):
            return {}

        try:
            result   = {}
            # Baca file dari belakang untuk dapat data terbaru
            # Progress file bisa besar, ambil 4KB terakhir
            with open(self.log_file, "r", encoding="utf-8", errors="replace") as f:
                # Seek ke akhir file
                f.seek(0, 2)
                file_size = f.tell()
                # Baca 4KB terakhir
                read_size = min(4096, file_size)
                f.seek(max(0, file_size - read_size))
                tail = f.read()

            # Parse key=value dari baris terakhir progress block
            # Ambil block terakhir (pisahkan oleh progress=continue/end)
            blocks = tail.split("progress=")
            if len(blocks) > 1:
                last_block = blocks[-2]  # Block sebelum yang terakhir = paling baru lengkap
            else:
                last_block = tail

            for line in last_block.strip().splitlines():
                line = line.strip()
                if "=" in line:
                    key, _, val = line.partition("=")
                    result[key.strip()] = val.strip()

            # Hitung persen jika ada out_time_ms dan duration
            if "out_time_ms" in result and self.duration > 0:
                try:
                    out_time_sec = int(result["out_time_ms"]) / 1_000_000
                    result["progress_pct"] = min(100.0, (out_time_sec / self.duration) * 100)
                    result["out_time_sec"] = out_time_sec
                except (ValueError, ZeroDivisionError):
                    result["progress_pct"] = 0.0

            return result

        except (OSError, PermissionError) as e:
            LOGGER.debug(f"read_progress error: {e}")
            return {}

    def get_progress_info(self) -> dict:
        """
        [NEW] Return dict lengkap status progress untuk display ke user.
        
        Return:
            {
                "pct": float,        # 0-100
                "speed": str,        # "1.23x"
                "fps": str,          # "29.97"
                "out_time": str,     # "00:01:23"
                "out_size_mb": float,
                "elapsed_sec": float,
                "eta_sec": float,
            }
        """
        raw    = self.read_progress()
        pct    = raw.get("progress_pct", 0.0)
        speed  = raw.get("speed", "—")
        fps    = raw.get("fps", "—")

        # Format waktu output
        out_time_sec = raw.get("out_time_sec", 0.0)
        h  = int(out_time_sec // 3600)
        m  = int((out_time_sec % 3600) // 60)
        s  = int(out_time_sec % 60)
        out_time_str = f"{h:02d}:{m:02d}:{s:02d}"

        out_size_mb = self.output_size() / 1024 / 1024
        elapsed     = self.elapsed_seconds()

        # ETA estimasi
        eta_sec = 0.0
        if pct > 0:
            total_est = elapsed / (pct / 100)
            eta_sec   = max(0.0, total_est - elapsed)

        return {
            "pct":        round(pct, 1),
            "speed":      speed,
            "fps":        fps,
            "out_time":   out_time_str,
            "out_size_mb": round(out_size_mb, 2),
            "elapsed_sec": round(elapsed, 1),
            "eta_sec":    round(eta_sec, 1),
        }

    # ── Logger ───────────────────────────────────────────────────────

    async def logger(self, process_id: str, process_dir: str, command: list) -> None:
        """
        Baca stderr FFmpeg secara async dan simpan ke log file.

        [FIX CRITICAL] Menggunakan readline loop dengan mekanisme Pipe Drainer
                       untuk mencegah FFmpeg stuck/beku karena buffer memory penuh.
        """
        LOGGER.info(f"🔵 FFmpeg logger mulai: {process_id}")

        # Guard: jika stderr tidak di-pipe, return langsung
        if self.process.stderr is None:
            LOGGER.warning(f"⚠️  FFmpeg stderr tidak di-pipe untuk {process_id}")
            await self.process.wait()
            self.returncode = self.process.returncode
            return

        log_path = f"{process_dir}/FFMPEG_LOG.txt"

        try:
            async with aio_open(log_path, "a+", encoding="utf-8") as log_f:
                # Tulis command di awal log
                await log_f.write(f"CMD: {' '.join(str(c) for c in command)}\n")
                await log_f.write(f"{'─' * 60}\n")

                line_count = 0

                # [FIX CRITICAL: ANTI-DEADLOCK LOOP]
                while True:
                    try:
                        # Baca per baris secara manual
                        raw_line = await self.process.stderr.readline()
                        if not raw_line: # Jika kosong, berarti FFmpeg sudah selesai
                            break
                    except ValueError as e:
                        # [ANTI-MACET] Jika baris kepanjangan (chunk exceed limit),
                        # SEDOT dan BUANG isi pipa memori agar FFmpeg tidak membeku!
                        LOGGER.warning(f"⚠️ Pipa Log Mampet (Line too long): {e} — Menguras pipa untuk {process_id}...")
                        try:
                            # Baca sisa chunk memori secara paksa dan lupakan (drain)
                            await self.process.stderr.read(65536) 
                        except Exception as drain_err:
                            LOGGER.debug(f"Drain error: {drain_err}")
                        continue # Lanjut baca baris berikutnya dengan aman!

                    # Cek pembatalan (Cancel) setiap 50 baris
                    if line_count % _CANCEL_CHECK_INTERVAL == 0:
                        if not check_running_process(process_id):
                            LOGGER.info(f"🔒 FFmpeg {process_id} dibatalkan oleh user.")
                            try:
                                self.process.kill()
                            except ProcessLookupError:
                                pass
                            break

                    # Decode baris yang aman
                    line = raw_line.decode("utf-8", errors="replace").strip()
                    if not line:
                        line_count += 1
                        continue

                    # Simpan ke ring buffer UI
                    self.save_log(line)

                    # Hanya print ke console jika ada kata kunci error (Biar gak nyampah)
                    if any(kw in line.lower() for kw in ("error", "warning", "invalid", "failed")):
                        LOGGER.debug(f"FFmpeg [{process_id}]: {line}")

                    # Tulis ke file FFMPEG_LOG.txt
                    await log_f.write(f"{line}\n")
                    line_count += 1

        except (OSError, PermissionError) as e:
            LOGGER.error(f"❌ Gagal buka/tulis log file {log_path}: {e}")

        # Tunggu proses selesai dan ambil return code
        LOGGER.info(f"🔵 FFmpeg logger selesai baca stderr: {process_id}")

        if check_running_process(process_id):
            try:
                await self.process.wait()
            except Exception as e:
                LOGGER.warning(f"⚠️  process.wait() error: {e}")

        self.returncode = self.process.returncode
        LOGGER.info(
            f"{'✅' if self.returncode == 0 else '❌'} "
            f"FFmpeg {process_id} selesai — returncode: {self.returncode}"
        )
