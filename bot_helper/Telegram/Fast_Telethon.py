"""
╔══════════════════════════════════════════════════════════════════════╗
║            bot_helper/Telegram/Fast_Telethon.py                      ║
║            Encoder1 Bot — v3.1                                       ║
╠══════════════════════════════════════════════════════════════════════╣
║  CHANGELOG dari versi lama:                                          ║
║  [FIX HIGH]  Hapus global 'filename' — race condition multi-user     ║
║  [FIX HIGH]  client.loop deprecated → asyncio.get_running_loop()     ║
║  [FIX HIGH]  loop.create_task → asyncio.create_task() di async ctx   ║
║  [FIX HIGH]  except BaseException:pass → except Exception + log      ║
║  [FIX]       loop parameter dihapus dari UploadSender                ║
║  [FIX]       parallel_transfer_locks sekarang benar-benar dipakai    ║
║  [FIX]       _cleanup() guard jika senders=None                      ║
║  [FIX]       sender.connect() pakai timeout 30 detik                 ║
║  [FIX]       Custom exception TransferCancelled (bukan string check) ║
║  [IMPROVE]   stream_file chunk_size 1KB → 1MB                        ║
║  [IMPROVE]   Type hints modern Python 3.10+                          ║
║  [IMPROVE]   Logging ditambahkan untuk debug transfer                ║
║  [IMPROVE]   auth_key cache per DC                                   ║
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
CHUNK_SIZE        = 1024 * 1024   # [FIX] 1MB untuk efisiensi video
SENDER_TIMEOUT    = 30            # Detik timeout untuk connect ke DC
DC_AUTH_CACHE: dict[int, AuthKey] = {}  # [NEW] Cache auth_key per DC


# ═══════════════════════════════════════════════════════════════════════
#  CUSTOM EXCEPTION
# ═══════════════════════════════════════════════════════════════════════

class TransferCancelled(Exception):
    """Raised ketika transfer dibatalkan oleh pengguna."""
    pass


# ═══════════════════════════════════════════════════════════════════════
#  DOWNLOAD SENDER
# ═══════════════════════════════════════════════════════════════════════

class DownloadSender:
    """Handle download dari satu DC connection."""

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

    async def disconnect(self) -> None:
        return await self.sender.disconnect()


# ═══════════════════════════════════════════════════════════════════════
#  UPLOAD SENDER
# ═══════════════════════════════════════════════════════════════════════

class UploadSender:
    """Handle upload ke satu DC connection."""

    def __init__(
        self,
        client: TelegramClient,
        sender: MTProtoSender,
        file_id: int,
        part_count: int,
        big: bool,
        index: int,
        stride: int,
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
# ═══════════════════════════════════════════════════════════════════════

class ParallelTransferrer:
    """Manage multiple parallel connections ke Telegram DC."""

    def __init__(self, client: TelegramClient, dc_id: int | None = None) -> None:
        self.client        = client
        self.dc_id         = dc_id or self.client.session.dc_id
        self.auth_key      = (
            None
            if dc_id and self.client.session.dc_id != dc_id
            else self.client.session.auth_key
        )
        self.senders       = None
        self.upload_ticker = 0

    async def _cleanup(self) -> None:
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
        )

    async def _create_sender(self) -> MTProtoSender:
        dc     = await self.client._get_dc(self.dc_id)
        sender = MTProtoSender(self.auth_key, loggers=self.client._log)

        try:
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
            if self.dc_id in DC_AUTH_CACHE:
                self.auth_key = DC_AUTH_CACHE[self.dc_id]
                sender.auth_key = self.auth_key
            else:
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

        part = 0
        while part < part_count:
            if not check_running_process(check_data):
                await self._cleanup()
                raise TransferCancelled("Download dibatalkan oleh pengguna")

            tasks = [asyncio.create_task(sender.next()) for sender in self.senders]
            for task in tasks:
                data = await task
                if not data:
                    break
                yield data
                part += 1

        await self._cleanup()


# ═══════════════════════════════════════════════════════════════════════
#  TRANSFER LOCKS & HELPERS
# ═══════════════════════════════════════════════════════════════════════

parallel_transfer_locks: defaultdict[int, asyncio.Lock] = defaultdict(asyncio.Lock)

def stream_file(file_to_stream: BinaryIO, chunk_size: int = CHUNK_SIZE):
    while True:
        data = file_to_stream.read(chunk_size)
        if not data:
            break
        yield data


# ═══════════════════════════════════════════════════════════════════════
#  PUBLIC API
# ═══════════════════════════════════════════════════════════════════════

async def upload_file(
    client: TelegramClient,
    file: BinaryIO,
    name: str,
    check_data: str,
    progress_callback=None,
) -> TypeInputFile:
    dc_id = client.session.dc_id
    async with parallel_transfer_locks[dc_id]:
        file_id   = helpers.generate_random_long()
        file_size = getsize(file.name)
        hash_md5  = md5()

        uploader = ParallelTransferrer(client)
        part_size, part_count, is_large = await uploader.init_upload(file_id, file_size)
        buffer = bytearray()

        for data in stream_file(file):
            if not check_running_process(check_data):
                await uploader.finish_upload()
                raise TransferCancelled("Upload dibatalkan oleh pengguna")

            if progress_callback:
                r = progress_callback(file.tell(), file_size)
                if isawaitable(r): await r

            if not is_large: hash_md5.update(data)

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

        if len(buffer) > 0:
            await uploader.upload(bytes(buffer))

        await uploader.finish_upload()

        if is_large:
            return InputFileBig(file_id, part_count, name)
        return InputFile(file_id, part_count, name, hash_md5.hexdigest())

async def download_file(
    client: TelegramClient,
    location: TypeLocation,
    out: BinaryIO,
    check_data: str,
    progress_callback=None,
) -> BinaryIO:
    size = location.size
    dc_id, input_location = utils.get_input_location(location)

    async with parallel_transfer_locks[dc_id]:
        downloader = ParallelTransferrer(client, dc_id)
        downloaded = downloader.download(input_location, size, check_data)

        async for chunk in downloaded:
            out.write(chunk)
            if progress_callback:
                r = progress_callback(out.tell(), size)
                if isawaitable(r): await r

    return out
