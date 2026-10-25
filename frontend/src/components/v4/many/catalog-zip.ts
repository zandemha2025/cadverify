/**
 * Many files or a whole folder become one ZIP in the browser, so a catalog run
 * is one upload. Entries are stored, not compressed: CAD files are mostly
 * already dense, storing is fast, and the server's zip-bomb guard (100:1) can
 * never trip on a repetitive STL. Each file's bytes go into the Blob as the
 * File itself; only its CRC-32 is computed, one file at a time, so memory
 * stays near the size of the largest file. Pure apart from Blob/File, so it
 * runs under `node --test`. No ZIP64: a free run is at most 1 GB, and the
 * caller refuses anything near 4 GB.
 */

const TABLE = (() => {
  const t = new Uint32Array(256);
  for (let n = 0; n < 256; n++) {
    let c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    t[n] = c >>> 0;
  }
  return t;
})();

export function crc32(data: Uint8Array, prev = 0): number {
  let c = (prev ^ 0xffffffff) >>> 0;
  for (let i = 0; i < data.length; i++) c = TABLE[(c ^ data[i]) & 0xff] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}

export const MAX_STORED_ZIP_BYTES = 4 * 1024 ** 3 - 64 * 1024 * 1024;

export interface ZipInput {
  /** Path inside the ZIP, "/"-separated. */
  name: string;
  data: Blob;
}

function dosTime(d: Date): { time: number; date: number } {
  const year = Math.max(1980, d.getFullYear());
  return {
    time: (d.getHours() << 11) | (d.getMinutes() << 5) | Math.floor(d.getSeconds() / 2),
    date: ((year - 1980) << 9) | ((d.getMonth() + 1) << 5) | d.getDate(),
  };
}

const CHUNK = 8 * 1024 * 1024;

async function blobCrc(b: Blob): Promise<number> {
  let crc = 0;
  for (let at = 0; at < b.size; at += CHUNK) {
    const part = new Uint8Array(await b.slice(at, Math.min(b.size, at + CHUNK)).arrayBuffer());
    crc = crc32(part, crc);
  }
  return crc;
}

/**
 * A stored ZIP of ``entries``. ``onProgress(done, total)`` reports bytes read
 * for the CRCs. Names repeated exactly are suffixed, as the server would.
 */
export async function storedZip(entries: readonly ZipInput[], onProgress?: (done: number, total: number) => void, now = new Date()): Promise<Blob> {
  const total = entries.reduce((s, e) => s + e.data.size, 0);
  if (total > MAX_STORED_ZIP_BYTES) throw new Error("These files are too large for one upload. Split them into smaller runs.");
  const enc = new TextEncoder();
  const { time, date } = dosTime(now);
  const parts: BlobPart[] = [];
  const central: Uint8Array<ArrayBuffer>[] = [];
  const used = new Set<string>();
  let offset = 0;
  let done = 0;
  for (const e of entries) {
    let name = e.name;
    for (let i = 1; used.has(name); i++) {
      const dot = e.name.lastIndexOf(".");
      name = dot > 0 ? `${e.name.slice(0, dot)}_${i}${e.name.slice(dot)}` : `${e.name}_${i}`;
    }
    used.add(name);
    const nameBytes = new Uint8Array(enc.encode(name));
    const crc = await blobCrc(e.data);
    const size = e.data.size;
    const local = new DataView(new ArrayBuffer(30));
    local.setUint32(0, 0x04034b50, true);
    local.setUint16(4, 20, true); // version needed
    local.setUint16(6, 0x0800, true); // UTF-8 names
    local.setUint16(8, 0, true); // stored
    local.setUint16(10, time, true);
    local.setUint16(12, date, true);
    local.setUint32(14, crc, true);
    local.setUint32(18, size, true);
    local.setUint32(22, size, true);
    local.setUint16(26, nameBytes.length, true);
    local.setUint16(28, 0, true);
    parts.push(new Uint8Array(local.buffer), nameBytes, e.data);

    const cd = new DataView(new ArrayBuffer(46));
    cd.setUint32(0, 0x02014b50, true);
    cd.setUint16(4, 20, true); // made by
    cd.setUint16(6, 20, true); // needed
    cd.setUint16(8, 0x0800, true);
    cd.setUint16(10, 0, true);
    cd.setUint16(12, time, true);
    cd.setUint16(14, date, true);
    cd.setUint32(16, crc, true);
    cd.setUint32(20, size, true);
    cd.setUint32(24, size, true);
    cd.setUint16(28, nameBytes.length, true);
    cd.setUint16(30, 0, true);
    cd.setUint16(32, 0, true);
    cd.setUint16(34, 0, true);
    cd.setUint16(36, 0, true);
    cd.setUint32(38, 0, true);
    cd.setUint32(42, offset, true);
    central.push(new Uint8Array(cd.buffer), nameBytes);

    offset += 30 + nameBytes.length + size;
    done += size;
    onProgress?.(done, total);
  }
  const cdSize = central.reduce((s, b) => s + b.length, 0);
  const end = new DataView(new ArrayBuffer(22));
  end.setUint32(0, 0x06054b50, true);
  end.setUint16(8, entries.length, true);
  end.setUint16(10, entries.length, true);
  end.setUint32(12, cdSize, true);
  end.setUint32(16, offset, true);
  end.setUint16(20, 0, true);
  return new Blob([...parts, ...central, new Uint8Array(end.buffer)], { type: "application/zip" });
}

/**
 * The entry names of a ZIP, read from its central directory only (the last few
 * KB of the file), so a dropped ZIP can be told apart cheaply: one part is a
 * single check, many parts a catalog run. Null when the ZIP can't be read this
 * way (ZIP64, a comment longer than the search window, not a ZIP): the server
 * then decides.
 */
export async function zipEntryNames(file: Blob): Promise<string[] | null> {
  const tailSize = Math.min(file.size, 22 + 65_535);
  if (tailSize < 22) return null;
  const tail = new DataView(await file.slice(file.size - tailSize).arrayBuffer());
  let eocd = -1;
  for (let i = tailSize - 22; i >= 0; i--) {
    if (tail.getUint32(i, true) === 0x06054b50) {
      eocd = i;
      break;
    }
  }
  if (eocd < 0) return null;
  const count = tail.getUint16(eocd + 10, true);
  const cdSize = tail.getUint32(eocd + 12, true);
  const cdOffset = tail.getUint32(eocd + 16, true);
  if (count === 0xffff || cdSize === 0xffffffff || cdOffset === 0xffffffff) return null; // ZIP64
  if (cdOffset + cdSize > file.size || cdSize > 16 * 1024 * 1024) return null;
  const cd = new DataView(await file.slice(cdOffset, cdOffset + cdSize).arrayBuffer());
  const dec = new TextDecoder();
  const names: string[] = [];
  for (let p = 0, n = 0; n < count && p + 46 <= cd.byteLength; n++) {
    if (cd.getUint32(p, true) !== 0x02014b50) return null;
    const nameLen = cd.getUint16(p + 28, true);
    const extraLen = cd.getUint16(p + 30, true);
    const commentLen = cd.getUint16(p + 32, true);
    names.push(dec.decode(new Uint8Array(cd.buffer, cd.byteOffset + p + 46, nameLen)));
    p += 46 + nameLen + extraLen + commentLen;
  }
  return names;
}

/** CAD parts among a ZIP's entries (folders and OS clutter left out), as the server counts them. */
export function cadEntries(names: readonly string[]): string[] {
  return names.filter((n) => {
    const parts = n.split("/");
    const base = parts[parts.length - 1] ?? "";
    if (!base || n.endsWith("/") || parts.includes("__MACOSX") || base.startsWith("._")) return false;
    return /\.(step|stp|iges|igs|stl)$/i.test(base);
  });
}
