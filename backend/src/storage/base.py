"""Object-store abstraction: a small, streaming-friendly blob interface.

CADVerify persists customer-derived binaries (meshes, reconstruction inputs/
outputs, extracted batch entries, cached PDFs). Historically each site
re-implemented ``getenv + makedirs + open`` against a local ``/data`` tree.
This module introduces a single seam so persistence is no longer hardwired to
local disk, while the *default* backend stays local disk with byte-identical
behavior (see ``factory.get_object_store``).

Design notes:
* ``ObjectStore`` is an :class:`abc.ABC` (a structural ``Protocol`` is also
  exported as :class:`ObjectStoreProtocol` for typing seams that prefer it).
* All read/write operations are streaming-friendly: ``put`` accepts either
  ``bytes`` or any binary file-like object and copies in bounded chunks, and
  ``open`` returns a readable binary stream so large blobs never have to be
  fully materialised in memory.
* Content type is first-class on ``put`` (adapters that have nowhere to store
  it -- e.g. a bare local filesystem -- accept and ignore it rather than
  erroring, which keeps the interface uniform).
"""
from __future__ import annotations

import abc
from typing import BinaryIO, Protocol, Union, runtime_checkable


class ReadableBinary(Protocol):
    """Minimal stream shape accepted by local and managed-transfer adapters."""

    def read(self, size: int = -1, /) -> bytes: ...

# Payload accepted by ``put``: raw bytes or a readable binary stream.
Payload = Union[bytes, bytearray, memoryview, ReadableBinary]

# Default streaming chunk size (256 KiB) -- bounds memory for large blobs.
CHUNK_SIZE = 256 * 1024


class ObjectStoreError(Exception):
    """Base class for object-store failures."""


class ObjectNotFoundError(ObjectStoreError, KeyError):
    """Raised by ``get``/``open`` when a key does not exist.

    Subclasses :class:`KeyError` so callers migrating from ``dict``-like or
    ``open()`` patterns can catch it naturally, and :class:`ObjectStoreError`
    so all store failures share a root.
    """

    def __init__(self, key: str):
        self.key = key
        super().__init__(key)


@runtime_checkable
class ObjectStoreProtocol(Protocol):
    """Structural view of an object store (for typing seams)."""

    def put(self, key: str, data: Payload, *, content_type: str | None = ...) -> str: ...

    def get(self, key: str) -> bytes: ...

    def open(self, key: str) -> BinaryIO: ...

    def delete(self, key: str) -> None: ...

    def exists(self, key: str) -> bool: ...

    def url(self, key: str) -> str: ...

    def list_keys(self, prefix: str = "") -> list[str]: ...

    def delete_prefix(self, prefix: str) -> int: ...

    def healthcheck(self) -> None: ...


class ObjectStore(abc.ABC):
    """Abstract, streaming-friendly, content-type-aware blob store.

    Keys are opaque forward-slash-delimited strings (e.g. ``"meshes/ab/cd.bin"``).
    Adapters MUST reject keys that escape their namespace (path traversal).
    """

    # -- write ---------------------------------------------------------------
    @abc.abstractmethod
    def put(self, key: str, data: Payload, *, content_type: str | None = None) -> str:
        """Store ``data`` under ``key`` and return a locator (see :meth:`url`).

        ``data`` may be ``bytes``-like or a readable binary file object; a file
        object is streamed in bounded chunks. Overwrites any existing object.
        ``content_type`` is stored where the backend supports metadata and is
        otherwise accepted and ignored.
        """

    # -- read ----------------------------------------------------------------
    @abc.abstractmethod
    def get(self, key: str) -> bytes:
        """Return the full object bytes, or raise :class:`ObjectNotFoundError`."""

    @abc.abstractmethod
    def open(self, key: str) -> BinaryIO:
        """Return a readable binary stream, or raise :class:`ObjectNotFoundError`.

        The caller owns the stream and must close it.
        """

    # -- metadata / lifecycle ------------------------------------------------
    @abc.abstractmethod
    def exists(self, key: str) -> bool:
        """Return whether an object exists at ``key``."""

    @abc.abstractmethod
    def delete(self, key: str) -> None:
        """Delete ``key``. Idempotent: deleting a missing key is a no-op."""

    @abc.abstractmethod
    def url(self, key: str) -> str:
        """Return a locator for ``key`` (scheme-qualified).

        This does not guarantee the object exists; it is the address a consumer
        would use to fetch it (``file://...`` for local, ``s3://...`` for S3).
        """

    @abc.abstractmethod
    def list_keys(self, prefix: str = "") -> list[str]:
        """Return keys below ``prefix`` in stable lexical order.

        Returned keys are relative to this store's namespace, never raw provider
        paths. Implementations must validate ``prefix`` with the same traversal
        protections used for ordinary object keys.
        """

    @abc.abstractmethod
    def delete_prefix(self, prefix: str) -> int:
        """Delete every object below ``prefix`` and return the delete count.

        This operation is idempotent. It exists for retention cleanup of batches
        and reconstruction jobs without exposing provider-specific list APIs.
        """

    @abc.abstractmethod
    def healthcheck(self) -> None:
        """Raise when the configured storage namespace is not reachable."""

    # -- shared helpers ------------------------------------------------------
    @staticmethod
    def _iter_chunks(data: Payload):
        """Yield ``bytes`` chunks from bytes-like data or a readable stream."""
        if isinstance(data, (bytes, bytearray, memoryview)):
            mv = memoryview(data)
            for start in range(0, len(mv), CHUNK_SIZE):
                yield bytes(mv[start : start + CHUNK_SIZE])
            return
        read = getattr(data, "read", None)
        if read is None:
            raise TypeError(
                "put() expects bytes-like data or a readable binary stream, "
                f"got {type(data).__name__}"
            )
        while True:
            chunk = read(CHUNK_SIZE)
            if not chunk:
                break
            if isinstance(chunk, str):
                raise TypeError("put() stream must be binary, not text")
            yield chunk
