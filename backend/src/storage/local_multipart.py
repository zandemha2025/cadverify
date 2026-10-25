"""Multipart uploads on local disk, for the local object-store backend.

Production stores incoming uploads in S3 and the browser PUTs each part to a
presigned S3 URL. A server on the local backend (development, staging) has no
presigned URLs, so the browser PUTs each part to the API itself
(``PUT /api/v1/uploads/{id}/parts/{n}``), which streams it here. The interface
matches the S3 adapter's multipart methods (``create_multipart_upload``,
``list_parts``, ``complete_multipart_upload``, ``abort_multipart_upload``,
``stat``), so the direct-upload service treats both the same way.

Layout under ``root``::

    .multipart/<upload_id>/meta.json        key, content type, metadata
    .multipart/<upload_id>/00001.part       one file per received part
    <key>                                   the completed object
    <key>.meta.json                         its content type and ETag

A part is written to a temp file and renamed, so a dropped connection leaves
no half part, and re-sending a part replaces it (S3 semantics). Each part's
ETag is the quoted MD5 of its bytes, as S3 returns for an unencrypted part.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shutil
import tempfile
from pathlib import Path
from typing import Any, BinaryIO

from src.storage.base import CHUNK_SIZE, ObjectMetadata, ObjectNotFoundError, ObjectStoreError
from src.storage.local import LocalObjectStore

_UPLOAD_ID = re.compile(r"^[0-9a-f]{32}$")
_META_SUFFIX = ".meta.json"
MAX_PART_NUMBER = 10_000


class PartTooLargeError(ObjectStoreError):
    """A part body exceeded the size the upload allows for it."""


class LocalMultipartStore(LocalObjectStore):
    """A local directory that also takes multipart uploads part by part."""

    transport = "relay"

    def _parts_dir(self, upload_id: str) -> Path:
        if not isinstance(upload_id, str) or not _UPLOAD_ID.fullmatch(upload_id):
            raise ValueError("invalid multipart upload id")
        return self.root / ".multipart" / upload_id

    def _meta(self, upload_id: str) -> dict[str, Any]:
        path = self._parts_dir(upload_id) / "meta.json"
        try:
            return json.loads(path.read_text("utf-8"))
        except FileNotFoundError as exc:
            raise ObjectNotFoundError(upload_id) from exc

    def _check_key(self, key: str, upload_id: str) -> dict[str, Any]:
        meta = self._meta(upload_id)
        if meta.get("key") != key:
            raise ObjectStoreError("multipart upload does not belong to this key")
        return meta

    # -- the S3-shaped multipart interface -----------------------------------
    def create_multipart_upload(self, key: str, *, content_type: str, metadata: dict[str, str] | None = None) -> str:
        if not content_type:
            raise ValueError("multipart upload requires a content type")
        self._resolve(key)  # traversal guard before anything is written
        upload_id = secrets.token_hex(16)
        parts = self._parts_dir(upload_id)
        parts.mkdir(parents=True, exist_ok=False)
        (parts / "meta.json").write_text(
            json.dumps({"key": key, "content_type": content_type, "metadata": dict(metadata or {})}), "utf-8"
        )
        return upload_id

    def put_part(self, key: str, upload_id: str, part_number: int, stream: BinaryIO | Any, *, max_bytes: int) -> tuple[str, int]:
        """Store one part from a readable stream (or async-free iterator); return (ETag, size).

        Reads at most ``max_bytes`` + 1 bytes: a longer body raises
        :class:`PartTooLargeError` and leaves any earlier copy of the part as it was.
        """
        if not 1 <= int(part_number) <= MAX_PART_NUMBER:
            raise ValueError("multipart part_number must be in [1, 10000]")
        self._check_key(key, upload_id)
        parts = self._parts_dir(upload_id)
        fd, tmp = tempfile.mkstemp(dir=str(parts), suffix=".tmp")
        digest = hashlib.md5(usedforsecurity=False)
        size = 0
        try:
            with os.fdopen(fd, "wb") as out:
                while True:
                    chunk = stream.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > max_bytes:
                        raise PartTooLargeError(f"part {part_number} is over {max_bytes} bytes")
                    digest.update(chunk)
                    out.write(chunk)
            etag = f'"{digest.hexdigest()}"'
            # The ETag sits next to the part so listing parts never re-reads them.
            (parts / f"{int(part_number):05d}.etag").write_text(etag, "utf-8")
            os.replace(tmp, parts / f"{int(part_number):05d}.part")
        except BaseException:
            try:
                os.unlink(tmp)
            except FileNotFoundError:
                pass
            raise
        return etag, size

    def _part_etag(self, path: Path) -> str:
        try:
            return path.with_suffix(".etag").read_text("utf-8").strip()
        except FileNotFoundError:
            pass
        digest = hashlib.md5(usedforsecurity=False)
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(CHUNK_SIZE), b""):
                digest.update(chunk)
        return f'"{digest.hexdigest()}"'

    def list_parts(self, key: str, upload_id: str) -> list[dict[str, Any]]:
        """Parts received so far, in order: ``{part_number, etag, size_bytes}``."""
        self._check_key(key, upload_id)
        out = []
        for path in sorted(self._parts_dir(upload_id).glob("*.part")):
            try:
                number = int(path.stem)
            except ValueError:
                continue
            out.append({"part_number": number, "etag": self._part_etag(path), "size_bytes": path.stat().st_size})
        return out

    def complete_multipart_upload(self, key: str, upload_id: str, parts: list[dict[str, Any]]) -> ObjectMetadata:
        """Join the named parts, in order, into the object at ``key``.

        Every named part must have been received with the given ETag (as S3
        checks); the object is written atomically and the parts are removed.
        """
        if not parts:
            raise ValueError("multipart completion requires at least one part")
        meta = self._check_key(key, upload_id)
        folder = self._parts_dir(upload_id)
        ordered = sorted(parts, key=lambda p: int(p["PartNumber"]))
        files = []
        for p in ordered:
            path = folder / f"{int(p['PartNumber']):05d}.part"
            if not path.is_file():
                raise ObjectStoreError(f"part {p['PartNumber']} was never received")
            if self._part_etag(path) != str(p.get("ETag", "")).strip():
                raise ObjectStoreError(f"part {p['PartNumber']} does not match its ETag")
            files.append(path)
        dest = self._resolve(key)
        dest.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(dest.parent), suffix=".tmp")
        whole = hashlib.md5(usedforsecurity=False)
        try:
            with os.fdopen(fd, "wb") as out:
                for path in files:
                    with open(path, "rb") as fh:
                        for chunk in iter(lambda: fh.read(CHUNK_SIZE), b""):
                            whole.update(chunk)
                            out.write(chunk)
            os.replace(tmp, dest)
        except BaseException:
            try:
                os.unlink(tmp)
            except FileNotFoundError:
                pass
            raise
        etag = f'"{whole.hexdigest()}-{len(files)}"'
        Path(str(dest) + _META_SUFFIX).write_text(json.dumps({"content_type": meta.get("content_type"), "etag": etag}), "utf-8")
        shutil.rmtree(folder, ignore_errors=True)
        return self.stat(key)

    def abort_multipart_upload(self, key: str, upload_id: str) -> None:
        """Drop an unfinished upload's parts. Idempotent, like S3's NoSuchUpload."""
        try:
            self._check_key(key, upload_id)
        except ObjectNotFoundError:
            return
        shutil.rmtree(self._parts_dir(upload_id), ignore_errors=True)

    def stat(self, key: str) -> ObjectMetadata:
        path = self._resolve(key)
        try:
            size = path.stat().st_size
        except FileNotFoundError as exc:
            raise ObjectNotFoundError(key) from exc
        info: dict[str, Any] = {}
        try:
            info = json.loads(Path(str(path) + _META_SUFFIX).read_text("utf-8"))
        except (FileNotFoundError, ValueError):
            info = {}
        return ObjectMetadata(size_bytes=size, content_type=info.get("content_type"), etag=info.get("etag"))

    def delete(self, key: str) -> None:
        super().delete(key)
        try:
            Path(str(self._resolve(key)) + _META_SUFFIX).unlink()
        except FileNotFoundError:
            pass

    def list_keys(self, prefix: str = "") -> list[str]:
        return [k for k in super().list_keys(prefix) if not k.startswith(".multipart/") and not k.endswith(_META_SUFFIX)]

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"LocalMultipartStore(root={self.root!s})"
