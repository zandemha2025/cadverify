"""Compressed single parts: .gz and one-part ZIPs, unpacked bomb-safe on the worker."""
from __future__ import annotations

import gzip
import io
import os
import random
import stat
import zipfile

import pytest

from src.services.part_archive import PartArchiveError, compression_of, unpack_part

# STEP-like text that compresses as real CAD does (a few times, not hundreds).
_rng = random.Random(7)
STEP = (
    b"ISO-10303-21;\nHEADER;\nENDSEC;\nDATA;\n"
    + b"".join(
        f"#{i}=CARTESIAN_POINT('',({_rng.uniform(-500, 500):.6f},{_rng.uniform(-500, 500):.6f},{_rng.uniform(0, 90):.6f}));\n".encode()
        for i in range(1, 3000)
    )
    + b"ENDSEC;\nEND-ISO-10303-21;\n"
)


def _write(tmp_path, name: str, data: bytes) -> str:
    p = tmp_path / name
    p.write_bytes(data)
    return str(p)


def _zip(entries, *, method=zipfile.ZIP_DEFLATED) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", method) as z:
        for e in entries:
            if isinstance(e, zipfile.ZipInfo):
                z.writestr(e, b"x")
            else:
                name, data = e
                z.writestr(name, data)
    return buf.getvalue()


def _code(exc_info) -> str:
    return exc_info.value.code


def test_compression_is_read_from_the_name():
    assert compression_of("bracket.STEP.gz") == "gzip"
    assert compression_of("bracket.zip") == "zip"
    assert compression_of("bracket.step") == "none"


def test_a_gzipped_step_unpacks_to_its_own_name(tmp_path):
    src = _write(tmp_path, "bracket.step.gz", gzip.compress(STEP))
    part = unpack_part(src, "bracket.step.gz", max_bytes=10 * 1024**2)
    try:
        assert (part.filename, part.container, part.part_bytes) == ("bracket.step", "gzip", len(STEP))
        assert open(part.path, "rb").read() == STEP
        assert part.path.endswith(".step") and part.path != src
    finally:
        os.unlink(part.path)


def test_a_one_part_zip_ignores_folders_and_os_clutter(tmp_path):
    data = _zip([("Bracket Rev B/", b""), ("Bracket Rev B/bracket.stp", STEP), ("__MACOSX/._bracket.stp", b"junk"), (".DS_Store", b"x")])
    part = unpack_part(_write(tmp_path, "bracket.zip", data), "bracket.zip", max_bytes=10 * 1024**2)
    try:
        assert (part.filename, part.container) == ("bracket.stp", "zip")
        assert open(part.path, "rb").read() == STEP
    finally:
        os.unlink(part.path)


def test_a_plain_file_comes_back_as_itself(tmp_path):
    src = _write(tmp_path, "bracket.step", STEP)
    part = unpack_part(src, "bracket.step", max_bytes=10 * 1024**2)
    assert (part.path, part.container, part.part_bytes) == (src, "none", len(STEP))


def test_a_gzip_bomb_stops_at_the_ratio_without_writing_it_all(tmp_path):
    bomb = gzip.compress(b"\0" * (64 * 1024**2))  # 64 MiB of zeros in ~64 KB
    src = _write(tmp_path, "bomb.stl.gz", bomb)
    with pytest.raises(PartArchiveError) as exc:
        unpack_part(src, "bomb.stl.gz", max_bytes=2 * 1024**3)
    assert _code(exc) == "ARCHIVE_RATIO"
    assert not [p for p in os.listdir(os.path.dirname(src)) if p.startswith("cv_part_")]


def test_a_gzip_over_the_absolute_size_is_refused(tmp_path):
    data = os.urandom(3 * 1024**2)  # incompressible: the ratio stays near 1
    src = _write(tmp_path, "big.stl.gz", gzip.compress(data))
    with pytest.raises(PartArchiveError) as exc:
        unpack_part(src, "big.stl.gz", max_bytes=2 * 1024**2)
    assert _code(exc) == "ARCHIVE_TOO_LARGE"


def test_a_zip_bomb_is_refused_from_its_header_and_while_streaming(tmp_path, monkeypatch):
    data = _zip([("bomb.step", b"\0" * (32 * 1024**2))])
    with pytest.raises(PartArchiveError) as exc:
        unpack_part(_write(tmp_path, "bomb.zip", data), "bomb.zip", max_bytes=2 * 1024**3)
    assert _code(exc) == "ARCHIVE_RATIO"


def test_a_zip_whose_header_lies_about_size_is_stopped(tmp_path):
    data = bytearray(_zip([("part.step", STEP)], method=zipfile.ZIP_STORED))
    # Shrink the declared size in the central directory: the stream must not trust it.
    with zipfile.ZipFile(io.BytesIO(bytes(data))) as z:
        info = z.infolist()[0]
    cd = data.rfind(b"PK\x01\x02")
    data[cd + 24:cd + 28] = (100).to_bytes(4, "little")  # uncompressed size
    with pytest.raises(PartArchiveError) as exc:
        unpack_part(_write(tmp_path, "liar.zip", bytes(data)), "liar.zip", max_bytes=10 * 1024**2)
    assert _code(exc) in {"ARCHIVE_INVALID", "ARCHIVE_TOO_LARGE", "ARCHIVE_RATIO"}
    assert info.file_size == len(STEP)


@pytest.mark.parametrize("name", ["../evil.step", "/abs/evil.step", "a/../../evil.step", "C:/evil.step", "a\\..\\evil.step"])
def test_path_traversal_is_refused(tmp_path, name):
    with pytest.raises(PartArchiveError) as exc:
        unpack_part(_write(tmp_path, "t.zip", _zip([(name, STEP)])), "t.zip", max_bytes=10 * 1024**2)
    assert _code(exc) == "ARCHIVE_PATH"


def test_a_symlink_entry_is_refused(tmp_path):
    link = zipfile.ZipInfo("part.step")
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    with pytest.raises(PartArchiveError) as exc:
        unpack_part(_write(tmp_path, "l.zip", _zip([link])), "l.zip", max_bytes=10 * 1024**2)
    assert _code(exc) == "ARCHIVE_SYMLINK"


@pytest.mark.parametrize("inner", ["inner.zip", "parts.tar", "part.step.gz", "x.7z"])
def test_nested_archives_are_refused_by_name(tmp_path, inner):
    with pytest.raises(PartArchiveError) as exc:
        unpack_part(_write(tmp_path, "n.zip", _zip([(inner, b"PK\x03\x04"), ("part.step", STEP)])), "n.zip", max_bytes=10 * 1024**2)
    assert _code(exc) == "ARCHIVE_NESTED"


def test_nested_archives_are_refused_by_content(tmp_path):
    hidden = _zip([("part.step", STEP)])
    with pytest.raises(PartArchiveError) as exc:
        unpack_part(_write(tmp_path, "h.zip", _zip([("part.step", hidden)])), "h.zip", max_bytes=10 * 1024**2)
    assert _code(exc) == "ARCHIVE_NESTED"
    double = gzip.compress(gzip.compress(STEP))
    with pytest.raises(PartArchiveError) as exc:
        unpack_part(_write(tmp_path, "d.step.gz", double), "d.step.gz", max_bytes=10 * 1024**2)
    assert _code(exc) == "ARCHIVE_NESTED"


def test_too_many_entries_are_refused(tmp_path, monkeypatch):
    monkeypatch.setenv("PART_ARCHIVE_MAX_ENTRIES", "8")
    entries = [(f"notes/{i}.txt", b"n") for i in range(9)] + [("part.step", STEP)]
    with pytest.raises(PartArchiveError) as exc:
        unpack_part(_write(tmp_path, "m.zip", _zip(entries)), "m.zip", max_bytes=10 * 1024**2)
    assert _code(exc) == "ARCHIVE_ENTRIES"


def test_a_zip_needs_exactly_one_part(tmp_path):
    with pytest.raises(PartArchiveError) as exc:
        unpack_part(_write(tmp_path, "two.zip", _zip([("a.step", STEP), ("b.stl", STEP)])), "two.zip", max_bytes=10 * 1024**2)
    assert _code(exc) == "ARCHIVE_MANY_PARTS" and "catalog run" in exc.value.message
    with pytest.raises(PartArchiveError) as exc:
        unpack_part(_write(tmp_path, "none.zip", _zip([("readme.txt", b"hi")])), "none.zip", max_bytes=10 * 1024**2)
    assert _code(exc) == "ARCHIVE_NO_PART"


def test_broken_and_misnamed_archives_say_so(tmp_path):
    with pytest.raises(PartArchiveError) as exc:
        unpack_part(_write(tmp_path, "cut.step.gz", gzip.compress(STEP)[:200]), "cut.step.gz", max_bytes=10 * 1024**2)
    assert _code(exc) == "ARCHIVE_INVALID"
    with pytest.raises(PartArchiveError) as exc:
        unpack_part(_write(tmp_path, "notes.txt.gz", gzip.compress(b"x")), "notes.txt.gz", max_bytes=10 * 1024**2)
    assert _code(exc) == "ARCHIVE_NOT_CAD"
    with pytest.raises(PartArchiveError) as exc:
        unpack_part(_write(tmp_path, "fake.zip", b"not a zip"), "fake.zip", max_bytes=10 * 1024**2)
    assert _code(exc) == "ARCHIVE_INVALID"
    with pytest.raises(PartArchiveError) as exc:
        unpack_part(_write(tmp_path, "empty.step.gz", gzip.compress(b"")), "empty.step.gz", max_bytes=10 * 1024**2)
    assert _code(exc) == "ARCHIVE_EMPTY"


def test_an_encrypted_entry_is_refused(tmp_path):
    data = bytearray(_zip([("part.step", STEP)]))
    # Set the encryption flag bit in the local and central headers.
    lh = data.find(b"PK\x03\x04")
    data[lh + 6] |= 0x1
    cd = data.rfind(b"PK\x01\x02")
    data[cd + 8] |= 0x1
    with pytest.raises(PartArchiveError) as exc:
        unpack_part(_write(tmp_path, "e.zip", bytes(data)), "e.zip", max_bytes=10 * 1024**2)
    assert _code(exc) == "ARCHIVE_ENCRYPTED"
