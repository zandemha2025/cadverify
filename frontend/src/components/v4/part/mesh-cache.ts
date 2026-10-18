/**
 * A copy of a part's 3D preview mesh in THIS browser (IndexedDB), keyed by the
 * part's mesh hash: the fast path in front of the server's view of the kept
 * source (GET /parts/{hash}/preview.glb), so a saved part reopens in 3D without
 * another round trip. Nothing here leaves the browser. Every call fails soft
 * (private windows, blocked storage, quota): the page then asks the server, or
 * shows its "No 3D view" state.
 */

const DB = "scalecad-part-previews";
const STORE = "meshes";
const KEEP = 40;

export interface CachedMesh {
  hash: string;
  /** The analysis-space GLB the viewer renders. */
  blob: Blob;
  /** Fingerprint of the tessellation, matched against the analysis before faces are lit. */
  faceHash: string | null;
  faceSpace: "analysis" | "preview";
  filename: string;
  savedAt: number;
}

function open(): Promise<IDBDatabase | null> {
  return new Promise((resolve) => {
    try {
      if (typeof indexedDB === "undefined") return resolve(null);
      const req = indexedDB.open(DB, 1);
      req.onupgradeneeded = () => {
        const db = req.result;
        if (!db.objectStoreNames.contains(STORE)) {
          const s = db.createObjectStore(STORE, { keyPath: "hash" });
          s.createIndex("savedAt", "savedAt");
        }
      };
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => resolve(null);
      req.onblocked = () => resolve(null);
    } catch {
      resolve(null);
    }
  });
}

function done(tx: IDBTransaction): Promise<boolean> {
  return new Promise((resolve) => {
    tx.oncomplete = () => resolve(true);
    tx.onerror = () => resolve(false);
    tx.onabort = () => resolve(false);
  });
}

export async function getCachedMesh(hash: string): Promise<CachedMesh | null> {
  const db = await open();
  if (!db) return null;
  try {
    return await new Promise<CachedMesh | null>((resolve) => {
      const req = db.transaction(STORE, "readonly").objectStore(STORE).get(hash);
      req.onsuccess = () => resolve((req.result as CachedMesh | undefined) ?? null);
      req.onerror = () => resolve(null);
    });
  } catch {
    return null;
  } finally {
    db.close();
  }
}

export async function putCachedMesh(entry: CachedMesh): Promise<boolean> {
  const db = await open();
  if (!db) return false;
  try {
    const tx = db.transaction(STORE, "readwrite");
    const store = tx.objectStore(STORE);
    store.put(entry);
    // Keep the newest KEEP parts; older copies are dropped first.
    const keys = store.index("savedAt").getAllKeys();
    keys.onsuccess = () => {
      const all = keys.result as IDBValidKey[];
      const extra = all.length - KEEP;
      if (extra > 0) {
        const cursor = store.index("savedAt").openCursor();
        let left = extra;
        cursor.onsuccess = () => {
          const c = cursor.result;
          if (!c || left <= 0) return;
          if ((c.value as CachedMesh).hash !== entry.hash) {
            c.delete();
            left -= 1;
          }
          c.continue();
        };
      }
    };
    return await done(tx);
  } catch {
    return false;
  } finally {
    db.close();
  }
}
