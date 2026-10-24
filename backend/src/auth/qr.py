"""A small QR code encoder for the two-step enrolment link (no dependency).

Byte mode, error correction level M, versions 1 to 10 (up to 213 bytes), which
covers every ``otpauth://`` link ScaleCAD makes (see ``totp.otpauth_uri``).
Follows ISO/IEC 18004: Reed-Solomon over GF(256) with polynomial 0x11D, the
standard function patterns, zigzag placement, and the mask with the lowest
penalty score. The result is a list of rows, "1" for a dark module, without
the quiet zone (the page draws the four-module margin).
"""
from __future__ import annotations

MAX_VERSION = 10
# Level M, versions 1..10: error-correction codewords per block, and block count.
_ECC_PER_BLOCK = (10, 16, 26, 18, 24, 16, 18, 22, 22, 26)
_BLOCKS = (1, 1, 1, 2, 2, 4, 4, 4, 5, 5)
_FORMAT_ECL_M = 0  # the two format bits for level M


def _raw_data_modules(ver: int) -> int:
    result = (16 * ver + 128) * ver + 64
    if ver >= 2:
        align = ver // 7 + 2
        result -= (25 * align - 10) * align - 55
        if ver >= 7:
            result -= 36
    return result


def _data_codewords(ver: int) -> int:
    return _raw_data_modules(ver) // 8 - _ECC_PER_BLOCK[ver - 1] * _BLOCKS[ver - 1]


def capacity(ver: int) -> int:
    """Bytes of data a level-M code of this version holds in byte mode."""
    count_bits = 8 if ver <= 9 else 16
    return (_data_codewords(ver) * 8 - 4 - count_bits) // 8


MAX_BYTES = capacity(MAX_VERSION)


# ── Reed-Solomon ──────────────────────────────────────────────────────────────
def _gf_mul(x: int, y: int) -> int:
    z = 0
    for i in reversed(range(8)):
        z = (z << 1) ^ ((z >> 7) * 0x11D)
        z ^= ((y >> i) & 1) * x
    return z & 0xFF


def _rs_divisor(degree: int) -> list[int]:
    result = [0] * (degree - 1) + [1]
    root = 1
    for _ in range(degree):
        for j in range(degree):
            result[j] = _gf_mul(result[j], root)
            if j + 1 < degree:
                result[j] ^= result[j + 1]
        root = _gf_mul(root, 0x02)
    return result


def _rs_remainder(data: list[int], divisor: list[int]) -> list[int]:
    result = [0] * len(divisor)
    for b in data:
        factor = b ^ result.pop(0)
        result.append(0)
        for i, coef in enumerate(divisor):
            result[i] ^= _gf_mul(coef, factor)
    return result


# ── layout ────────────────────────────────────────────────────────────────────
def _alignment_positions(ver: int) -> list[int]:
    if ver == 1:
        return []
    count = ver // 7 + 2
    step = (ver * 8 + count * 3 + 5) // (count * 4 - 4) * 2
    positions = [ver * 4 + 10 - i * step for i in range(count - 1)]
    return [6] + sorted(positions)


class _Grid:
    def __init__(self, ver: int) -> None:
        self.ver = ver
        self.size = ver * 4 + 17
        self.dark = [[False] * self.size for _ in range(self.size)]
        self.func = [[False] * self.size for _ in range(self.size)]

    def set_func(self, x: int, y: int, dark: bool) -> None:
        self.dark[y][x] = dark
        self.func[y][x] = True

    def draw_function_patterns(self) -> None:
        size = self.size
        for i in range(size):
            self.set_func(6, i, i % 2 == 0)
            self.set_func(i, 6, i % 2 == 0)
        for cx, cy in ((3, 3), (size - 4, 3), (3, size - 4)):
            for dy in range(-4, 5):
                for dx in range(-4, 5):
                    x, y = cx + dx, cy + dy
                    if 0 <= x < size and 0 <= y < size:
                        self.set_func(x, y, max(abs(dx), abs(dy)) not in (2, 4))
        pos = _alignment_positions(self.ver)
        last = len(pos) - 1
        for i, ax in enumerate(pos):
            for j, ay in enumerate(pos):
                if (i, j) in ((0, 0), (0, last), (last, 0)):
                    continue
                for dy in range(-2, 3):
                    for dx in range(-2, 3):
                        self.set_func(ax + dx, ay + dy, max(abs(dx), abs(dy)) != 1)
        self.draw_format(0)
        if self.ver >= 7:
            rem = self.ver
            for _ in range(12):
                rem = (rem << 1) ^ ((rem >> 11) * 0x1F25)
            bits = self.ver << 12 | rem
            for i in range(18):
                bit = (bits >> i) & 1 == 1
                a, b = size - 11 + i % 3, i // 3
                self.set_func(a, b, bit)
                self.set_func(b, a, bit)

    def draw_format(self, mask: int) -> None:
        size = self.size
        data = _FORMAT_ECL_M << 3 | mask
        rem = data
        for _ in range(10):
            rem = (rem << 1) ^ ((rem >> 9) * 0x537)
        bits = (data << 10 | rem) ^ 0x5412

        def bit(i: int) -> bool:
            return (bits >> i) & 1 == 1

        for i in range(6):
            self.set_func(8, i, bit(i))
        self.set_func(8, 7, bit(6))
        self.set_func(8, 8, bit(7))
        self.set_func(7, 8, bit(8))
        for i in range(9, 15):
            self.set_func(14 - i, 8, bit(i))
        for i in range(8):
            self.set_func(size - 1 - i, 8, bit(i))
        for i in range(8, 15):
            self.set_func(8, size - 15 + i, bit(i))
        self.set_func(8, size - 8, True)  # the dark module

    def place(self, codewords: list[int]) -> None:
        size = self.size
        total_bits = len(codewords) * 8
        i = 0
        right = size - 1
        while right >= 1:
            if right == 6:
                right = 5
            for vert in range(size):
                for j in range(2):
                    x = right - j
                    upward = ((right + 1) & 2) == 0
                    y = size - 1 - vert if upward else vert
                    if not self.func[y][x] and i < total_bits:
                        self.dark[y][x] = (codewords[i >> 3] >> (7 - (i & 7))) & 1 == 1
                        i += 1
            right -= 2

    def apply_mask(self, mask: int) -> None:
        for y in range(self.size):
            for x in range(self.size):
                if self.func[y][x]:
                    continue
                if mask == 0:
                    flip = (x + y) % 2 == 0
                elif mask == 1:
                    flip = y % 2 == 0
                elif mask == 2:
                    flip = x % 3 == 0
                elif mask == 3:
                    flip = (x + y) % 3 == 0
                elif mask == 4:
                    flip = (x // 3 + y // 2) % 2 == 0
                elif mask == 5:
                    flip = x * y % 2 + x * y % 3 == 0
                elif mask == 6:
                    flip = (x * y % 2 + x * y % 3) % 2 == 0
                else:
                    flip = ((x + y) % 2 + x * y % 3) % 2 == 0
                if flip:
                    self.dark[y][x] = not self.dark[y][x]

    def penalty(self) -> int:
        size, dark = self.size, self.dark
        score = 0
        lines = [row for row in dark] + [[dark[y][x] for y in range(size)] for x in range(size)]
        finder_a = [True, False, True, True, True, False, True, False, False, False, False]
        finder_b = finder_a[::-1]
        for line in lines:
            run = 1
            for k in range(1, size + 1):
                if k < size and line[k] == line[k - 1]:
                    run += 1
                    continue
                if run >= 5:
                    score += 3 + (run - 5)
                run = 1
            for k in range(size - 10):
                window = line[k:k + 11]
                if window == finder_a or window == finder_b:
                    score += 40
        for y in range(size - 1):
            for x in range(size - 1):
                c = dark[y][x]
                if c == dark[y][x + 1] == dark[y + 1][x] == dark[y + 1][x + 1]:
                    score += 3
        total = size * size
        darks = sum(sum(1 for c in row if c) for row in dark)
        k = abs(darks * 20 - total * 10) // total
        score += k * 10
        return score


def _codewords(data: bytes, ver: int) -> list[int]:
    count_bits = 8 if ver <= 9 else 16
    bits: list[int] = []

    def push(value: int, n: int) -> None:
        bits.extend((value >> i) & 1 for i in reversed(range(n)))

    push(0b0100, 4)
    push(len(data), count_bits)
    for b in data:
        push(b, 8)
    capacity_bits = _data_codewords(ver) * 8
    push(0, min(4, capacity_bits - len(bits)))
    push(0, (-len(bits)) % 8)
    pad = 0xEC
    while len(bits) < capacity_bits:
        push(pad, 8)
        pad ^= 0xEC ^ 0x11
    data_words = [int("".join(map(str, bits[i:i + 8])), 2) for i in range(0, len(bits), 8)]

    blocks_n = _BLOCKS[ver - 1]
    ecc_len = _ECC_PER_BLOCK[ver - 1]
    raw = _raw_data_modules(ver) // 8
    short_n = blocks_n - raw % blocks_n
    short_len = raw // blocks_n
    divisor = _rs_divisor(ecc_len)
    blocks: list[list[int]] = []
    k = 0
    for i in range(blocks_n):
        take = short_len - ecc_len + (0 if i < short_n else 1)
        dat = data_words[k:k + take]
        k += take
        ecc = _rs_remainder(dat, divisor)
        if i < short_n:
            dat = dat + [0]
        blocks.append(dat + ecc)
    out: list[int] = []
    for i in range(len(blocks[0])):
        for j, blk in enumerate(blocks):
            if i != short_len - ecc_len or j >= short_n:
                out.append(blk[i])
    return out


def encode(text: str, *, version: int | None = None, mask: int | None = None) -> list[str]:
    """Rows of a level-M QR code for ``text`` ("1" dark, "0" light).

    ``version`` and ``mask`` are chosen automatically (smallest version, lowest
    penalty) unless given; tests pin them to compare with a reference encoder.
    """
    data = text.encode("utf-8")
    if version is None:
        version = next((v for v in range(1, MAX_VERSION + 1) if len(data) <= capacity(v)), None)
        if version is None:
            raise ValueError(f"QR text longer than {MAX_BYTES} bytes")
    elif not 1 <= version <= MAX_VERSION or len(data) > capacity(version):
        raise ValueError("QR text does not fit this version")
    words = _codewords(data, version)
    best: _Grid | None = None
    best_score = None
    for m in range(8) if mask is None else (mask,):
        grid = _Grid(version)
        grid.draw_function_patterns()
        grid.place(words)
        grid.apply_mask(m)
        grid.draw_format(m)
        score = grid.penalty() if mask is None else 0
        if best_score is None or score < best_score:
            best, best_score = grid, score
    assert best is not None
    return ["".join("1" if c else "0" for c in row) for row in best.dark]
