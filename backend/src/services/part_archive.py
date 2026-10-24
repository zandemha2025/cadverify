"""Unpack a compressed single part: ``.step.gz`` (any CAD suffix + ``.gz``) or a one-part ZIP.

Runs on the worker, on a file already on local disk, and writes the part to a
new temp file; nothing is held in memory. Bomb-safe by construction:

* the output is counted as it is written, never trusted from a header, and
  stops past ``max_bytes`` (the single-file limit, 2 GiB by default);
* the output may be at most ``max_ratio`` times the compressed input
  (``PART_ARCHIVE_MAX_RATIO``, 200 by default: CAD text compresses 5-20x, a
  bomb 1000x and more);
* a ZIP may list at most ``max_entries`` entries (``PART_ARCHIVE_MAX_ENTRIES``,
  64), must hold exactly one STEP, IGES or STL file (folders and OS clutter such
  as ``__MACOSX/`` and ``.DS_Store`` are ignored), and is refused when any entry
  is an absolute path, climbs out with ``..``, is a symlink, is encrypted, or is
  itself an archive;
* a gzipped part or a ZIP's part whose bytes are themselves an archive (gzip,
  ZIP, 7z, RAR, xz, bzip2 signatures) is refused: no nested archives.

Every refusal is a :class:`PartArchiveError` with a stable ``code`` and a
message that says what to do.
"""
from __future__ import annotations

import gzip
import os
import stat
import tempfile
import zipfile
import zlib
from dataclasses import dataclass
from pathlib import PurePosixPath

CAD_SUFFIXES = (".step", ".stp", ".iges", ".igs", ".stl")
ARCHIVE_SUFFIXES = (".zip", ".gz", ".tgz", ".tar", ".7z", ".rar", ".xz", ".bz2", ".zst")
_ARCHIVE_MAGIC = (
    b"\x1f\x8b",            # gzip
    b"PK\x03\x04",          # zip
    b"PK\x05\x06",          # empty zip
    b"7z\xbc\xaf\x27\x1c",  # 7z
    b"Rar!\x1a\x07",        # rar
    b"\xfd7zXZ\x00",        # xz
    b"BZh",                 # bzip2
    b"\x28\xb5\x2f\xfd",    # zstd
)
_JUNK_PARTS = {"__MACOSX"}
_JUNK_NAMES = {".DS_Store", "Thumbs.db", "desktop.ini"}
_CHUNK = 1024 * 1024


class PartArchiveError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class UnpackedPart:
    path: str
    filename: str
    compressed_bytes: int
    part_bytes: int
    container: str  # "gzip" | "zip" | "none"


def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(value, maximum))


def max_ratio() -> int:
    return _env_int("PART_ARCHIVE_MAX_RATIO", 200, 2, 10_000)


def max_entries() -> int:
    return _env_int("PART_ARCHIVE_MAX_ENTRIES", 64, 1, 10_000)


def compression_of(filename: str) -> str:
    lower = (filename or "").lower()
    if lower.endswith(".gz"):
        return "gzip"
    if lower.endswith(".zip"):
        return "zip"
    return "none"


def _gib(n: int) -> str:
    return f"{n / 1024**3:.1f} GB" if n >= 1024**3 else f"{max(1, round(n / 1024**2))} MB"


def _looks_like_archive(head: bytes) -> bool:
    return any(head.startswith(m) for m in _ARCHIVE_MAGIC)


def _copy_bounded(src, out_path: str, *, compressed_bytes: int, max_bytes: int, name: str) -> int:
    """Stream ``src`` into ``out_path``, counting real bytes against both limits."""
    ceiling = min(max_bytes, max(compressed_bytes, 1) * max_ratio())
    total = 0
    head = b""
    with open(out_path, "wb") as out:
        while True:
            chunk = src.read(_CHUNK)
            if not chunk:
                break
            if len(head) < 8:
                head = (head + chunk)[:8]
                if total == 0 and _looks_like_archive(head):
                    raise PartArchiveError(
                        "ARCHIVE_NESTED",
                        f"{name} is itself a compressed archive. Upload the STEP, IGES or STL file, or one ZIP of it.",
                    )
            total += len(chunk)
            if total > max_bytes:
                raise PartArchiveError(
                    "ARCHIVE_TOO_LARGE",
                    f"{name} unpacks to more than {_gib(max_bytes)}, the largest single file ScaleCAD takes.",
                )
            if total > ceiling:
                raise PartArchiveError(
                    "ARCHIVE_RATIO",
                    f"{name} unpacks to over {max_ratio()} times its compressed size, which CAD files don't. "
                    "It was not unpacked.",
                )
            out.write(chunk)
    if total == 0:
        raise PartArchiveError("ARCHIVE_EMPTY", f"{name} is empty inside.")
    return total


def _inner_gzip_name(filename: str) -> str:
    inner = os.path.basename(filename)[:-3] if filename.lower().endswith(".gz") else os.path.basename(filename)
    if not inner.lower().endswith(CAD_SUFFIXES):
        raise PartArchiveError(
            "ARCHIVE_NOT_CAD",
            "A gzipped part must be named like part.step.gz, part.igs.gz or part.stl.gz.",
        )
    return inner


def _unpack_gzip(path: str, filename: str, *, max_bytes: int) -> UnpackedPart:
    inner = _inner_gzip_name(filename)
    compressed = os.path.getsize(path)
    fd, out_path = tempfile.mkstemp(prefix="cv_part_", suffix=os.path.splitext(inner)[1].lower())
    os.close(fd)
    try:
        with gzip.open(path, "rb") as src:
            size = _copy_bounded(src, out_path, compressed_bytes=compressed, max_bytes=max_bytes, name=os.path.basename(filename))
    except PartArchiveError:
        os.unlink(out_path)
        raise
    except (OSError, EOFError, zlib.error) as exc:
        os.unlink(out_path)
        raise PartArchiveError("ARCHIVE_INVALID", f"{os.path.basename(filename)} isn't a complete gzip file: {exc}.") from exc
    return UnpackedPart(out_path, inner, compressed, size, "gzip")


def _entry_problem(info: zipfile.ZipInfo) -> str | None:
    name = info.filename
    if name.startswith("/") or name.startswith("\\") or (len(name) > 1 and name[1] == ":"):
        return "ARCHIVE_PATH"
    if "\\" in name or ".." in PurePosixPath(name).parts:
        return "ARCHIVE_PATH"
    mode = (info.external_attr >> 16) & 0xFFFF
    if mode and stat.S_ISLNK(mode):
        return "ARCHIVE_SYMLINK"
    if info.flag_bits & 0x1:
        return "ARCHIVE_ENCRYPTED"
    return None


def _is_junk(info: zipfile.ZipInfo) -> bool:
    parts = PurePosixPath(info.filename).parts
    base = parts[-1] if parts else ""
    return info.is_dir() or bool(_JUNK_PARTS.intersection(parts)) or base in _JUNK_NAMES or base.startswith("._")


def _unpack_zip(path: str, filename: str, *, max_bytes: int) -> UnpackedPart:
    shown = os.path.basename(filename)
    try:
        archive = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError) as exc:
        raise PartArchiveError("ARCHIVE_INVALID", f"{shown} isn't a readable ZIP file.") from exc
    with archive:
        infos = archive.infolist()
        if len(infos) > max_entries():
            raise PartArchiveError(
                "ARCHIVE_ENTRIES",
                f"{shown} lists {len(infos)} entries; a single-part ZIP may list up to {max_entries()}. "
                "Check many parts together as a catalog run.",
            )
        problems = {code for info in infos if (code := _entry_problem(info))}
        if "ARCHIVE_PATH" in problems:
            raise PartArchiveError("ARCHIVE_PATH", f"{shown} has an entry with an absolute path or '..' in it. It was not unpacked.")
        if "ARCHIVE_SYMLINK" in problems:
            raise PartArchiveError("ARCHIVE_SYMLINK", f"{shown} has a symbolic link in it. It was not unpacked.")
        if "ARCHIVE_ENCRYPTED" in problems:
            raise PartArchiveError("ARCHIVE_ENCRYPTED", f"{shown} is password-protected. Upload it without a password.")
        entries = [i for i in infos if not _is_junk(i)]
        nested = [i for i in entries if i.filename.lower().endswith(ARCHIVE_SUFFIXES)]
        if nested:
            raise PartArchiveError(
                "ARCHIVE_NESTED",
                f"{shown} has an archive inside it ({os.path.basename(nested[0].filename)}). Upload a ZIP of the part itself.",
            )
        cad = [i for i in entries if i.filename.lower().endswith(CAD_SUFFIXES)]
        if not cad:
            raise PartArchiveError("ARCHIVE_NO_PART", f"{shown} has no STEP, IGES or STL file in it.")
        if len(cad) > 1:
            raise PartArchiveError(
                "ARCHIVE_MANY_PARTS",
                f"{shown} has {len(cad)} parts in it. Check them together as a catalog run, or upload one part.",
            )
        info = cad[0]
        if info.file_size > max_bytes:
            raise PartArchiveError(
                "ARCHIVE_TOO_LARGE",
                f"{os.path.basename(info.filename)} is {_gib(info.file_size)}; the largest single file ScaleCAD takes is {_gib(max_bytes)}.",
            )
        if info.compress_size and info.file_size > info.compress_size * max_ratio():
            raise PartArchiveError(
                "ARCHIVE_RATIO",
                f"{shown} says its part unpacks to over {max_ratio()} times its compressed size, which CAD files don't. "
                "It was not unpacked.",
            )
        inner = os.path.basename(info.filename)
        fd, out_path = tempfile.mkstemp(prefix="cv_part_", suffix=os.path.splitext(inner)[1].lower())
        os.close(fd)
        try:
            with archive.open(info) as src:
                size = _copy_bounded(src, out_path, compressed_bytes=max(info.compress_size, 1),
                                     max_bytes=min(max_bytes, info.file_size or max_bytes), name=inner)
        except PartArchiveError:
            os.unlink(out_path)
            raise
        except (zipfile.BadZipFile, OSError, EOFError, zlib.error, NotImplementedError) as exc:
            os.unlink(out_path)
            raise PartArchiveError("ARCHIVE_INVALID", f"{inner} in {shown} couldn't be unpacked: {exc}.") from exc
        if info.file_size and size != info.file_size:
            os.unlink(out_path)
            raise PartArchiveError("ARCHIVE_INVALID", f"{inner} in {shown} unpacked to a different size than the ZIP says.")
    return UnpackedPart(out_path, inner, os.path.getsize(path), size, "zip")


def unpack_part(path: str, filename: str, *, max_bytes: int) -> UnpackedPart:
    """The part inside a compressed upload, as a new temp file (the caller deletes it).

    A plain CAD file comes back as itself (same path, container ``none``).
    """
    kind = compression_of(filename)
    if kind == "gzip":
        return _unpack_gzip(path, filename, max_bytes=max_bytes)
    if kind == "zip":
        return _unpack_zip(path, filename, max_bytes=max_bytes)
    size = os.path.getsize(path)
    return UnpackedPart(path, os.path.basename(filename), size, size, "none")
