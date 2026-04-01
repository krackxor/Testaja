"""
╔══════════════════════════════════════════════════════════════════════╗
║           bot_helper/Telegram/Fast_Telethon.py                       ║
║           Encoder1 Bot — v3.1                                        ║
╠══════════════════════════════════════════════════════════════════════╣
║  CHANGELOG dari versi lama:                                          ║
║  [FIX HIGH]  Hapus global 'filename' — race condition multi-user    ║
║  [FIX HIGH]  client.loop deprecated → asyncio.get_running_loop()    ║
║  [FIX HIGH]  loop.create_task → asyncio.create_task() di async ctx  ║
║  [FIX HIGH]  except BaseException:pass → except Exception + log     ║
║  [FIX]       loop parameter dihapus dari UploadSender               ║
║  [FIX]       parallel_transfer_locks sekarang benar-benar dipakai   ║
║  [FIX]       _cleanup() guard jika senders=None                     ║
║  [FIX]       sender.connect() pakai timeout 30 detik                ║
║  [FIX]       Custom exception TransferCancelled (bukan string check)║
║  [IMPROVE]   stream_file chunk_size 1KB → 1MB                      ║
║  [IMPROVE]   Type hints modern Python 3.10+                         ║
║  [IMPROVE]   Logging ditambahkan untuk debug transfer               ║
║  [IMPROVE]   auth_key cache per DC                                  ║
╚══════════════════════════════════════════════════════════════════════╝
"""

# ── Standard Library ──────────────────────────────────────────────────
import asyncio
from collections import defaultdict
from hashlib import md5
from inspect import isawaitable
from math import ceil
from os.path import getsize
from typing import AsyncGenerator, BinaryIO

# ── Telethon ──────────────────────────────────────────────────────────
from telethon import TelegramClient, helpers, utils
from telethon.crypto import AuthKey
from telethon.network import MTProtoSender
from telethon.tl.alltlobjects import LAYER
from telethon.tl.functions import InvokeWithLayerRequest
from telethon.tl.functions.auth import (
    ExportAuthorizationRequest,
    ImportAuthorizationRequest,
)
from telethon.tl.functions.upload import (
    GetFileRequest,
    SaveBigFilePartRequest,
    SaveFilePartRequest,
)
from telethon.tl.types import (
    Document,
    InputDocumentFileLocation,
    InputFile,
    InputFileBig,
    InputFileLocation,
    InputPeerPhotoFileLocation,
    InputPhotoFileLocation,
)

# ── Internal ──────────────────────────────────────────────────────────
from bot_helper.Process.Running_Process import check_running_process
from config.config import Config

LOGGER = Config.LOGGER

# ── Type aliases (Python 3.10+ style) ────────────────────────────────
TypeLocation = (
    Document
    | InputDocumentFileLocation
    | InputPeerPhotoFileLocation
    | InputFileLocation
    | InputPhotoFileLocation
)
TypeInputFile = InputFile | InputFileBig

# ── Konstanta ─────────────────────────────────────────────────────────
CHUNK_SIZE        = 1024 * 1024   # [FIX] 1MB (was: 1KB — terlalu kecil untuk video)
SENDER_TIMEOUT    = 30            # Detik timeout untuk connect ke DC
DC_AUTH_CACHE: dict[int, AuthKey] = {}  # [NEW] Cache auth_key per DC


# ═══════════════════════════════════════════════════════════════════════
#  CUSTOM EXCEPTION
#  [FIX] Ganti raise Exception("Cancelled") — fragile string comparison
#        di caller: if str(e)=="Cancelled" bisa salah jika pesan berubah
# ═══════════════════════════════════════════════════════════════════════

class TransferCancelled(Exception):
    """Raised ketika transfer dibatalkan oleh pengguna."""
    pass


# ═══════════════════════════════════════════════════════════════════════
#  DOWNLOAD SENDER
# ═══════════════════════════════════════════════════════════════════════

class DownloadSender:
    """Handle download dari satu DC connection."""

    client: TelegramClient
    sender: MTProtoSender
    request: GetFileRequest
    remaining: int
    stride: int

    def __init__(
        self,
        client: TelegramClient,
        sender: MTProtoSender,
        file: TypeLocation,
        offset: int,
        limit: int,
        stride: int,
        count: int,
    ) -> None:
        self.sender    = sender
        self.client    = client
        self.request   = GetFileRequest(file, offset=offset, limit=limit)
        self.stride    = stride
        self.remaining = count

    async def next(self) -> bytes | None:
        if not self.remaining:
            return None
        result = await self.client._call(self.sender, self.request)
        self.remaining         -= 1
        self.request.offset    += self.stride
        return result.bytes

    def disconnect(self) -> asyncio.coroutine:
        return self.sender.disconnect()


# ═══════════════════════════════════════════════════════════════════════
#  UPLOAD SENDER
#  [FIX] Hapus loop parameter — pakai asyncio.get_running_loop()
#        Loop dari __init__ bisa stale jika event loop di-restart
#  [FIX] asyncio.create_task() di dalam async method
# ═══════════════════════════════════════════════════════════════════════

class UploadSender:
    """Handle upload ke satu DC connection."""

    client: TelegramClient
    sender: MTProtoSender
    request: SaveFilePartRequest | SaveBigFilePartRequest
    part_count: int
    stride: int
    previous: asyncio.Task | None

    def __init__(
        self,
        client: TelegramClient,
        sender: MTProtoSender,
        file_id: int,
        part_count: int,
        big: bool,
        index: int,
        stride: int,
        # [FIX] loop parameter DIHAPUS — tidak lagi di-pass dari luar
    ) -> None:
        self.client     = client
        self.sender     = sender
        self.part_count = part_count
        self.stride     = stride
        self.previous   = None

        if big:
            self.request = SaveBigFilePartRequest(file_id, index, part_count, b"")
        else:
            self.request = SaveFilePartRequest(file_id, index, b"")

    async def next(self, data: bytes) -> None:
        if self.previous:
            await self.previous
        # [FIX] asyncio.create_task() di dalam async context — loop selalu benar
        self.previous = asyncio.create_task(self._next(data))

    async def _next(self, data: bytes) -> None:
        self.request.bytes      = data
        await self.client._call(self.sender, self.request)
        self.request.file_part += self.stride

    async def disconnect(self) -> None:
        if self.previous:
            await self.previous
        return await self.sender.disconnect()


# ═══════════════════════════════════════════════════════════════════════
#  PARALLEL TRANSFERRER
#  [FIX] Hapus self.loop = self.client.loop — deprecated di Telethon 1.28+
#  [FIX] _cleanup() guard jika senders=None
#  [FIX] sender.connect() dengan timeout
#  [IMPROVE] auth_key cache per DC — tidak export/import ulang tiap kali
# ═══════════════════════════════════════════════════════════════════════

class ParallelTransferrer:
    """Manage multiple parallel connections ke Telegram DC."""

    client: TelegramClient
    dc_id: int
    senders: list[DownloadSender | UploadSender] | None
    auth_key: AuthKey
    upload_ticker: int

    def __init__(self, client: TelegramClient, dc_id: int | None = None) -> None:
        self.client       = client
        # [FIX] Tidak lagi simpan self.loop — akan pakai asyncio.get_running_loop()
        self.dc_id        = dc_id or self.client.session.dc_id
        self.auth_key     = (
            None
            if dc_id and self.client.session.dc_id != dc_id
            else self.client.session.auth_key
        )
        self.senders      = None
        self.upload_ticker = 0

    async def _cleanup(self) -> None:
        # [FIX] Guard jika senders belum diinisialisasi
        if not self.senders:
            return
        await asyncio.gather(*[sender.disconnect() for sender in self.senders])
        self.senders = None

    @staticmethod
    def _get_connection_count(
        file_size: int,
        max_count: int = 20,
        full_size: int = 100 * 1024 * 1024,
    ) -> int:
        if file_size > full_size:
            return max_count
        return ceil((file_size / full_size) * max_count)

    async def _init_download(
        self,
        connections: int,
        file: TypeLocation,
        part_count: int,
        part_size: int,
    ) -> None:
        minimum, remainder = divmod(part_count, connections)

        def get_part_count() -> int:
            nonlocal remainder
            if remainder > 0:
                remainder -= 1
                return minimum + 1
            return minimum

        # First sender selalu dibuat dahulu karena dia yang handle auth export/import
        self.senders = [
            await self._create_download_sender(
                file, 0, part_size, connections * part_size, get_part_count()
            ),
            *await asyncio.gather(
                *[
                    self._create_download_sender(
                        file, i, part_size, connections * part_size, get_part_count()
                    )
                    for i in range(1, connections)
                ]
            ),
        ]

    async def _create_download_sender(
        self,
        file: TypeLocation,
        index: int,
        part_size: int,
        stride: int,
        part_count: int,
    ) -> DownloadSender:
        return DownloadSender(
            self.client,
            await self._create_sender(),
            file,
            index * part_size,
            part_size,
            stride,
            part_count,
        )

    async def _init_upload(
        self, connections: int, file_id: int, part_count: int, big: bool
    ) -> None:
        self.senders = [
            await self._create_upload_sender(file_id, part_count, big, 0, connections),
            *await asyncio.gather(
                *[
                    self._create_upload_sender(file_id, part_count, big, i, connections)
                    for i in range(1, connections)
                ]
            ),
        ]

    async def _create_upload_sender(
        self,
        file_id: int,
        part_count: int,
        big: bool,
        index: int,
        stride: int,
    ) -> UploadSender:
        return UploadSender(
            self.client,
            await self._create_sender(),
            file_id,
            part_count,
            big,
            index,
            stride,
            # [FIX] loop tidak di-pass lagi
        )

    async def _create_sender(self) -> MTProtoSender:
        """
        Buat koneksi MTProto ke DC.
        [FIX] Tambah timeout 30 detik — tidak hang selamanya jika DC tidak bisa diakses
        [IMPROVE] Cache auth_key per DC — tidak export/import ulang tiap koneksi baru
        """
        dc     = await self.client._get_dc(self.dc_id)
        sender = MTProtoSender(self.auth_key, loggers=self.client._log)

        try:
            # [FIX] Timeout untuk connect ke DC
            await asyncio.wait_for(
                sender.connect(
                    self.client._connection(
                        dc.ip_address,
                        dc.port,
                        dc.id,
                        loggers=self.client._log,
                        proxy=self.client._proxy,
                    )
                ),
                timeout=SENDER_TIMEOUT,
            )
        except asyncio.TimeoutError:
            LOGGER.error(f"❌ Timeout connect ke DC {self.dc_id} ({dc.ip_address})")
            raise

        if not self.auth_key:
            # [IMPROVE] Cek cache dulu sebelum export/import
            if self.dc_id in DC_AUTH_CACHE:
                LOGGER.debug(f"🔑 Pakai cached auth_key untuk DC {self.dc_id}")
                self.auth_key = DC_AUTH_CACHE[self.dc_id]
            else:
                LOGGER.debug(f"🔑 Export/import auth untuk DC {self.dc_id}")
                auth = await self.client(ExportAuthorizationRequest(self.dc_id))
                self.client._init_request.query = ImportAuthorizationRequest(
                    id=auth.id, bytes=auth.bytes
                )
                req = InvokeWithLayerRequest(LAYER, self.client._init_request)
                await sender.send(req)
                self.auth_key = sender.auth_key
                DC_AUTH_CACHE[self.dc_id] = self.auth_key

        return sender

    async def init_upload(
        self,
        file_id: int,
        file_size: int,
        part_size_kb: float | None = None,
        connection_count: int | None = None,
    ) -> tuple[int, int, bool]:
        connection_count = connection_count or self._get_connection_count(file_size)
        part_size        = (part_size_kb or utils.get_appropriated_part_size(file_size)) * 1024
        part_count       = (file_size + part_size - 1) // part_size
        is_large         = file_size > 10 * 1024 * 1024
        await self._init_upload(connection_count, file_id, part_count, is_large)
        LOGGER.debug(
            f"📤 Upload init — size: {file_size:,}B, "
            f"parts: {part_count}, connections: {connection_count}, big: {is_large}"
        )
        return part_size, part_count, is_large

    async def upload(self, part: bytes) -> None:
        await self.senders[self.upload_ticker].next(part)
        self.upload_ticker = (self.upload_ticker + 1) % len(self.senders)

    async def finish_upload(self) -> None:
        await self._cleanup()

    async def download(
        self,
        file: TypeLocation,
        file_size: int,
        check_data: str,
        part_size_kb: float | None = None,
        connection_count: int | None = None,
    ) -> AsyncGenerator[bytes, None]:
        connection_count = connection_count or self._get_connection_count(file_size)
        part_size        = (part_size_kb or utils.get_appropriated_part_size(file_size)) * 1024
        part_count       = ceil(file_size / part_size)
        await self._init_download(connection_count, file, part_count, part_size)

        LOGGER.debug(
            f"📥 Download init — size: {file_size:,}B, "
            f"parts: {part_count}, connections: {connection_count}"
        )

        part = 0
        while part < part_count:
            # [FIX] Pakai TransferCancelled bukan Exception("Cancelled")
            if not check_running_process(check_data):
                await self._cleanup()
                raise TransferCancelled("Download dibatalkan oleh pengguna")

            tasks = [
                asyncio.create_task(sender.next())
                for sender in self.senders
            ]
            for task in tasks:
                data = await task
                if not data:
                    break
                yield data
                part += 1

        await self._cleanup()


# ═══════════════════════════════════════════════════════════════════════
#  TRANSFER LOCKS
#  [FIX] Lock sekarang benar-benar DIPAKAI di download_file() dan upload_file()
#        Sebelumnya dibuat tapi tidak pernah dipakai — komentar bohong
# ═══════════════════════════════════════════════════════════════════════

parallel_transfer_locks: defaultdict[int, asyncio.Lock] = defaultdict(asyncio.Lock)


# ═══════════════════════════════════════════════════════════════════════
#  STREAM FILE
#  [FIX] chunk_size default 1MB (was: 1KB)
#        1KB untuk file video besar = jutaan iterasi loop
# ═══════════════════════════════════════════════════════════════════════

def stream_file(
    file_to_stream: BinaryIO,
    chunk_size: int = CHUNK_SIZE,
) -> bytes:
    """
    Generator untuk baca file per chunk.
    [FIX] chunk_size default 1MB bukan 1KB — jauh lebih efisien untuk video.
    """
    while True:
        data = file_to_stream.read(chunk_size)
        if not data:
            break
        yield data


# ═══════════════════════════════════════════════════════════════════════
#  INTERNAL TRANSFER — UPLOAD KE TELEGRAM
#  [FIX] Hapus global filename — race condition multi-user
#        filename sekarang di-pass sebagai parameter
#  [FIX] except BaseException → except Exception + logging
# ═══════════════════════════════════════════════════════════════════════

async def _internal_transfer_to_telegram(
    client: TelegramClient,
    response: BinaryIO,
    filename: str,           # [FIX] Parameter, bukan global variable
    check_data: str,         # DIPINDAHKAN KE ATAS KARENA TIDAK ADA DEFAULT VALUE
    progress_callback=None,  # DIPINDAHKAN KE BAWAH KARENA ADA DEFAULT VALUE =None
) -> tuple[TypeInputFile, int]:
    """
    Upload file ke Telegram menggunakan parallel transfer.

    [FIX] filename sekarang parameter (bukan global) — tidak ada race condition
    [FIX] except BaseException → except Exception dengan logging
    """
    file_id   = helpers.generate_random_long()
    file_size = getsize(response.name)
    hash_md5  = md5()

    LOGGER.debug(f"📤 Start upload: {filename} ({file_size:,} bytes)")

    uploader                      = ParallelTransferrer(client)
    part_size, part_count, is_large = await uploader.init_upload(file_id, file_size)
    buffer                        = bytearray()

    for data in stream_file(response):
        # Cancel check setiap chunk
        if not check_running_process(check_data):
            await uploader.finish_upload()
            # [FIX] TransferCancelled bukan Exception("Cancelled")
            raise TransferCancelled("Upload dibatalkan oleh pengguna")

        # Progress callback
        if progress_callback:
            r = progress_callback(response.tell(), file_size)
            if isawaitable(r):
                try:
                    await r
                except asyncio.CancelledError:
                    raise   # Re-raise cancel
                except Exception as e:
                    # [FIX] Log tapi tidak crash — progress error tidak harus stop upload
                    LOGGER.debug(f"Progress callback error (non-fatal): {e}")

        if not is_large:
            hash_md5.update(data)

        # Buffer management untuk alignment ke part_size
        if len(buffer) == 0 and len(data) == part_size:
            await uploader.upload(data)
            continue

        new_len = len(buffer) + len(data)
        if new_len >= part_size:
            cutoff = part_size - len(buffer)
            buffer.extend(data[:cutoff])
            await uploader.upload(bytes(buffer))
            buffer.clear()
            buffer.extend(data[cutoff:])
        else:
            buffer.extend(data)

    # Upload sisa buffer
    if len(buffer) > 0:
        await uploader.upload(bytes(buffer))

    await uploader.finish_upload()
    LOGGER.debug(f"✅ Upload selesai: {filename}")

    if is_large:
        return InputFileBig(file_id, part_count, filename), file_size
    else:
        return InputFile(file_id, part_count, filename, hash_md5.hexdigest()), file_size


# ═══════════════════════════════════════════════════════════════════════
#  PUBLIC API — DOWNLOAD
#  [FIX] Pakai lock yang benar-benar diimplementasikan
#  [FIX] TransferCancelled re-raise agar caller bisa handle
# ═══════════════════════════════════════════════════════════════════════

async def download_file(
    client: TelegramClient,
    location: TypeLocation,
    out: BinaryIO,
    check_data: str,
    progress_callback=None,
) -> BinaryIO:
    """
    Download file dari Telegram menggunakan parallel transfer.

    [FIX] Lock diimplementasikan (sebelumnya dibuat tapi tidak dipakai)
    [FIX] TransferCancelled ditangani dengan benar
    """
    size         = location.size
    dc_id, location = utils.get_input_location(location)

    LOGGER.debug(f"📥 Start download dari DC {dc_id}, size: {size:,} bytes")

    # [FIX] Lock per DC — cegah terlalu banyak concurrent connection ke DC yang sama
    async with parallel_transfer_locks[dc_id]:
        downloader = ParallelTransferrer(client, dc_id)
        downloaded = downloader.download(location, size, check_data)

        async for chunk in downloaded:
            out.write(chunk)
            if progress_callback:
                r = progress_callback(out.tell(), size)
                if isawaitable(r):
                    try:
                        await r
                    except asyncio.CancelledError:
                        raise
                    except Exception as e:
                        LOGGER.debug(f"Progress callback error (non-fatal): {e}")

    return out


# ═══════════════════════════════════════════════════════════════════════
#  PUBLIC API — UPLOAD
#  [FIX] filename di-pass sebagai parameter (tidak lagi global)
#  [FIX] Lock diimplementasikan
# ═══════════════════════════════════════════════════════════════════════

async def upload_file(
    client: TelegramClient,
    file: BinaryIO,
    name: str,
    check_data: str,
    progress_callback=None,
) -> TypeInputFile:
    """
    Upload file ke Telegram menggunakan parallel transfer.

    [FIX] name di-pass ke _internal_transfer_to_telegram sebagai parameter
          (bukan global variable — menghindari race condition multi-user)
    [FIX] Lock per session DC
    """
    dc_id = client.session.dc_id

    # [FIX] Lock per DC untuk cegah concurrent upload yang berlebihan
    async with parallel_transfer_locks[dc_id]:
        result, _ = await _internal_transfer_to_telegram(
            client=client,
            response=file,
            filename=name,          # [FIX] Parameter bukan global
            check_data=check_data,  # [FIX] Disesuaikan urutannya dengan pembaruan fungsi di atas
            progress_callback=progress_callback,
        )
    return result
