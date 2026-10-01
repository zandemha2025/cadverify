"""Fail the image build if a patched package or the Expat UTF-16 fix is missing."""
import ctypes
import subprocess

VERSIONS = {
    "libexpat1": "2.8.5-2+cadverify1",
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
    assert not subprocess.check_output(["dpkg", "--verify", package], text=True)

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
print("Patched package integrity and Expat UTF-16 regression checks passed.")
