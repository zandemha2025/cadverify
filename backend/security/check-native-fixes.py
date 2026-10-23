"""Require patched packages and exercise Expat UTF-16 and buffer bounds fixes."""
import ctypes
import subprocess

VERSIONS = {
    "libexpat1": "2.9.0-1+cadverify1",
    "libx11-6": "2:1.8.12-1+cadverify1",
    "libx11-data": "2:1.8.12-1+cadverify1",
    "libx11-xcb1": "2:1.8.12-1+cadverify1",
    "libxrender1": "1:0.9.12-1+cadverify1",
}

for package, expected in VERSIONS.items():
    actual = subprocess.check_output(
        ["dpkg-query", "-W", "-f=${Version}", package], text=True
    ).strip()
    assert actual == expected, (package, actual, expected)
    integrity = subprocess.check_output(["dpkg", "--verify", package], text=True)
    assert not integrity, (package, integrity)

# Exercise the installed shared library, not Python's possibly bundled Expat.
lib = ctypes.CDLL("libexpat.so.1")
lib.XML_ParserCreate.argtypes = [ctypes.c_char_p]
lib.XML_ParserCreate.restype = ctypes.c_void_p
lib.XML_Parse.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int, ctypes.c_int]
lib.XML_Parse.restype = ctypes.c_int
lib.XML_ParserFree.argtypes = [ctypes.c_void_p]
lib.XML_GetErrorCode.argtypes = [ctypes.c_void_p]
lib.XML_GetErrorCode.restype = ctypes.c_int
for encoding in ("utf-16-le", "utf-16-be"):
    for content, expected in (("\U00010000", 1), ("\ud800A", 0), ("\ud800\ud800", 0)):
        data = f"<a>{content}</a>".encode(encoding, errors="surrogatepass")
        parser = lib.XML_ParserCreate(None)
        assert parser
        try:
            assert lib.XML_Parse(parser, data, len(data), 1) == expected
            if not expected:
                assert lib.XML_GetErrorCode(parser) == 4  # XML_ERROR_INVALID_TOKEN
        finally:
            lib.XML_ParserFree(parser)

# CVE-2026-77214: reject a caller-supplied length beyond the allocated buffer,
# both before parsing starts and after a valid chunk. Match the upstream
# regression at libexpat commit 4d9b1c499ecb66323260a7274edcf86c5eab0517.
lib.XML_GetBuffer.argtypes = [ctypes.c_void_p, ctypes.c_int]
lib.XML_GetBuffer.restype = ctypes.c_void_p
lib.XML_ParseBuffer.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
lib.XML_ParseBuffer.restype = ctypes.c_int
lib.XML_ErrorString.argtypes = [ctypes.c_int]
lib.XML_ErrorString.restype = ctypes.c_char_p
for is_final in (0, 1):
    parser = lib.XML_ParserCreate(None)
    assert parser
    try:
        buffer = lib.XML_GetBuffer(parser, 10)
        assert buffer
        assert lib.XML_ParseBuffer(parser, 10000, is_final) == 0
        assert lib.XML_ErrorString(lib.XML_GetErrorCode(parser)) == b"invalid argument"
        ctypes.memmove(buffer, b"<r></r>", 7)
        assert lib.XML_ParseBuffer(parser, 7, 0) == 1
        assert lib.XML_ParseBuffer(parser, 10000, is_final) == 0
        assert lib.XML_ErrorString(lib.XML_GetErrorCode(parser)) == b"invalid argument"
    finally:
        lib.XML_ParserFree(parser)
print("Patched package integrity and Expat UTF-16/buffer bounds checks passed.")
