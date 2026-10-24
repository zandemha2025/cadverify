/**
 * Hold a part someone dropped before signing in, so it checks itself the
 * moment the email link signs them in (same browser). Stored in IndexedDB
 * (Files survive structured clone), keyed to the normalized sign-in email so
 * a different account on a shared browser never receives it, and dropped
 * after a short window either way.
 */

import { FORM_MAX_BYTES } from "./upload-limit.ts";

export const PENDING_PART_TTL_MS = 2 * 60 * 60 * 1000;
// Held in this browser over sign-in: a web request's size, not a big file's.
export const PENDING_PART_MAX_BYTES = FORM_MAX_BYTES;

export type PendingPartRecord = {
  file: Blob;
  name: string;
  type: string;
  lastModified: number;
  email: string;
  savedAt: number;
};

/** The storage seam: IndexedDB in browsers, a Map in tests. */
export interface PendingPartStore {
  get(): Promise<PendingPartRecord | undefined>;
  set(record: PendingPartRecord): Promise<void>;
  clear(): Promise<void>;
}

/** Mirrors backend normalize_email: lowercase, strip +tags, Gmail dots. */
export function normalizeEmail(email: string): string {
  const at = email.lastIndexOf("@");
  if (at < 1) return email.trim().toLowerCase();
  let local = email.slice(0, at).trim().toLowerCase();
  const domain = email.slice(at + 1).trim().toLowerCase();
  local = local.split("+", 1)[0];
  if (domain === "gmail.com") local = local.replace(/\./g, "");
  return `${local}@${domain}`;
}

export async function holdPendingPart(store: PendingPartStore, file: File, email: string, now = Date.now()): Promise<boolean> {
  if (!file.size || file.size > PENDING_PART_MAX_BYTES || !email.includes("@")) return false;
  try {
    await store.set({
      file,
      name: file.name,
      type: file.type,
      lastModified: file.lastModified,
      email: normalizeEmail(email),
      savedAt: now,
    });
    return true;
  } catch {
    return false;
  }
}

/** Read without consuming: lets a page say which file is waiting. */
export async function peekPendingPart(store: PendingPartStore, now = Date.now()): Promise<{ name: string; email: string } | null> {
  try {
    const record = await store.get();
    if (!record || now - record.savedAt > PENDING_PART_TTL_MS) return null;
    return { name: record.name, email: record.email };
  } catch {
    return null;
  }
}

/** Consume the held part for this signed-in account, or nothing. Always
 * clears, so a held part is offered at most once. */
export async function takePendingPart(store: PendingPartStore, accountEmail: string, now = Date.now()): Promise<File | null> {
  let record: PendingPartRecord | undefined;
  try {
    record = await store.get();
  } catch {
    return null;
  }
  if (!record) return null;
  try {
    await store.clear();
  } catch {
    // Expiry still bounds an uncleared record.
  }
  if (now - record.savedAt > PENDING_PART_TTL_MS) return null;
  if (record.email !== normalizeEmail(accountEmail)) return null;
  return new File([record.file], record.name, { type: record.type, lastModified: record.lastModified });
}

const DB_NAME = "scalecad-pending-part";
const STORE = "parts";
const KEY = "pending";

function request<T>(req: IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

/** IndexedDB-backed store. Rejects where IndexedDB is unavailable (private
 * modes, old browsers); callers then simply ask for the file again. */
export function browserPendingPartStore(): PendingPartStore {
  const open = (): Promise<IDBDatabase> => {
    const req = indexedDB.open(DB_NAME, 1);
    req.onupgradeneeded = () => req.result.createObjectStore(STORE);
    return request(req);
  };
  const run = async <T>(mode: IDBTransactionMode, body: (store: IDBObjectStore) => IDBRequest<T>): Promise<T> => {
    const db = await open();
    try {
      return await request(body(db.transaction(STORE, mode).objectStore(STORE)));
    } finally {
      db.close();
    }
  };
  return {
    get: () => run("readonly", (store) => store.get(KEY) as IDBRequest<PendingPartRecord | undefined>),
    set: async (record) => { await run("readwrite", (store) => store.put(record, KEY)); },
    clear: async () => { await run("readwrite", (store) => store.delete(KEY)); },
  };
}
