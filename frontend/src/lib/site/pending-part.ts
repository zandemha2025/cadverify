import { isSupportedCad } from "../cad-file";

// A local handoff across email-link navigation; CAD bytes never enter analytics or a URL.
async function database(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open("scalecad-pending-part", 1);
    request.onupgradeneeded = () => request.result.createObjectStore("part");
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}
export async function savePendingPart(file: File): Promise<void> {
  if (!isSupportedCad(file.name) || file.size === 0) throw new Error("Choose a non-empty STEP, STL or IGES file.");
  const db = await database();
  try {
    await new Promise<void>((resolve, reject) => {
      const tx = db.transaction("part", "readwrite");
      tx.objectStore("part").put({ file, expires: Date.now() + 60 * 60 * 1000 }, "pending");
      tx.oncomplete = () => resolve();
      tx.onabort = () => reject(tx.error);
      tx.onerror = () => reject(tx.error);
    });
  } finally { db.close(); }
}
export async function takePendingPart(): Promise<File | null> {
  const db = await database();
  try {
    return await new Promise<File | null>((resolve, reject) => {
      const tx = db.transaction("part", "readwrite");
      const request = tx.objectStore("part").get("pending");
      let file: File | null = null;
      request.onsuccess = () => {
        const value = request.result;
        if (value?.file instanceof File && value.expires > Date.now() && isSupportedCad(value.file.name)) file = value.file;
        tx.objectStore("part").delete("pending");
      };
      tx.oncomplete = () => resolve(file);
      tx.onabort = () => reject(tx.error);
      tx.onerror = () => reject(tx.error);
    });
  } finally { db.close(); }
}
export async function clearPendingPart(): Promise<void> { await takePendingPart(); }

export async function hasPendingPart(): Promise<boolean> {
  const db = await database();
  try {
    return await new Promise<boolean>((resolve, reject) => {
      const request = db.transaction("part", "readonly").objectStore("part").get("pending");
      request.onsuccess = () => resolve(request.result?.file instanceof File && request.result.expires > Date.now());
      request.onerror = () => reject(request.error);
    });
  } finally { db.close(); }
}
