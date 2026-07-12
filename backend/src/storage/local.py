"""Local-filesystem object-store adapter (default; zero third-party deps).

Maps keys onto a directory tree under ``root``. Writes are atomic (temp file
in the destination directory + ``os.replace``) so a reader never observes a
partially written blob. This is the adapter that runs in this container and in
the single-node ``/data``-volume deployment.
"""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from typing import BinaryIO

from src.storage.base import CHUNK_SIZE, ObjectNotFoundError, ObjectStore, Payload


class LocalObjectStore(ObjectStore):
    """Store objects as files under ``root``.

    ``content_type`` is accepted for interface parity and ignored: a bare
    filesystem has nowhere durable to record it. (An S3 backend records it as
    object metadata -- see :class:`~src.storage.s3.S3ObjectStore`.)
    """

    def __init__(self, root: str | os.PathLike[str]):
        self._root = Path(root).resolve()

    @property
    def root(self) -> Path:
        return self._root

    # -- key -> path with traversal guard ------------------------------------
    def _resolve(self, key: str) -> Path:
        if not key or key.startswith("/"):
            raise ValueError(f"invalid object key {key!r}")
        candidate = (self._root / key).resolve()
        # Reject anything that escapes the root (``..`` traversal, absolute).
        if candidate != self._root and self._root not in candidate.parents:
            raise ValueError(f"object key escapes storage root: {key!r}")
        return candidate

    def local_path(self, key: str) -> str:
        """Return the on-disk absolute path for ``key`` (local-adapter only).

        Consumers that still read blobs via ``open(path, 'rb')`` use this so the
        abstraction can be wired in without changing their read path.
        """
        return str(self._resolve(key))

    # -- write ---------------------------------------------------------------
    def put(self, key: str, data: Payload, *, content_type: str | None = None) -> str:
        dest = self._resolve(key)
        dest.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(dest.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as fh:
                for chunk in self._iter_chunks(data):
                    fh.write(chunk)
            os.replace(tmp, dest)
        except BaseException:
            try:
                os.unlink(tmp)
            except FileNotFoundError:
                pass
            raise
        return self.url(key)

    # -- read ----------------------------------------------------------------
    def get(self, key: str) -> bytes:
        path = self._resolve(key)
        try:
            return path.read_bytes()
        except FileNotFoundError as exc:
            raise ObjectNotFoundError(key) from exc

    def open(self, key: str) -> BinaryIO:
        path = self._resolve(key)
        try:
            return open(path, "rb", buffering=CHUNK_SIZE)
        except FileNotFoundError as exc:
            raise ObjectNotFoundError(key) from exc

    # -- metadata / lifecycle ------------------------------------------------
    def exists(self, key: str) -> bool:
        return self._resolve(key).is_file()

    def delete(self, key: str) -> None:
        try:
            self._resolve(key).unlink()
        except FileNotFoundError:
            pass

    def url(self, key: str) -> str:
        return self._resolve(key).as_uri()

    def list_keys(self, prefix: str = "") -> list[str]:
        if prefix:
            target = self._resolve(prefix)
        else:
            target = self._root
        if target.is_file():
            return [target.relative_to(self._root).as_posix()]
        if not target.exists():
            return []
        return sorted(
            path.relative_to(self._root).as_posix()
            for path in target.rglob("*")
            if path.is_file()
        )

    def delete_prefix(self, prefix: str) -> int:
        target = self._resolve(prefix)
        if target.is_file():
            target.unlink()
            return 1
        if not target.exists():
            return 0
        count = sum(1 for path in target.rglob("*") if path.is_file())
        shutil.rmtree(target)
        return count

    def healthcheck(self) -> None:
        self._root.mkdir(parents=True, exist_ok=True)
        if not os.access(self._root, os.R_OK | os.W_OK | os.X_OK):
            raise PermissionError(f"object-store root is not accessible: {self._root}")

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"LocalObjectStore(root={self._root!s})"

    # convenience for tests / cleanup
    def _rmtree(self) -> None:  # pragma: no cover - test helper
        shutil.rmtree(self._root, ignore_errors=True)
