/** Request-body preparation for the same-origin API proxy.
 *
 * Large CAD and batch uploads must remain streamed. Small JSON commands are
 * deliberately buffered with a hard cap: Node/Undici can fail a streaming
 * upload with `expected non-null body source` when the API rejects the request
 * before consuming the stream (for example, an unauthenticated invite accept).
 * Buffering only bounded JSON removes that race without making CAD uploads an
 * in-memory operation.
 */

export const MAX_BUFFERED_PROXY_JSON_BYTES = 1024 * 1024;

export type PreparedProxyBody =
  | { body: BodyInit | undefined; streaming: boolean; tooLarge: false }
  | { body: undefined; streaming: false; tooLarge: true };

export function isJsonContentType(contentType: string | null): boolean {
  const mime = (contentType || "").split(";", 1)[0].trim().toLowerCase();
  return mime === "application/json" || mime.endsWith("+json");
}

async function readBounded(
  stream: ReadableStream<Uint8Array>,
  maxBytes: number,
): Promise<ArrayBuffer | null> {
  const reader = stream.getReader();
  const chunks: Uint8Array[] = [];
  let total = 0;

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      if (!value?.byteLength) continue;
      total += value.byteLength;
      if (total > maxBytes) {
        await reader.cancel("bounded JSON proxy body exceeded limit");
        return null;
      }
      chunks.push(value);
    }
  } finally {
    reader.releaseLock();
  }

  const joined = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    joined.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return joined.buffer;
}

export async function prepareProxyRequestBody(
  method: string,
  contentType: string | null,
  stream: ReadableStream<Uint8Array> | null,
): Promise<PreparedProxyBody> {
  if (method === "GET" || method === "HEAD" || !stream) {
    return { body: undefined, streaming: false, tooLarge: false };
  }

  if (!isJsonContentType(contentType)) {
    return { body: stream, streaming: true, tooLarge: false };
  }

  const buffered = await readBounded(stream, MAX_BUFFERED_PROXY_JSON_BYTES);
  if (buffered === null) {
    return { body: undefined, streaming: false, tooLarge: true };
  }
  return { body: buffered, streaming: false, tooLarge: false };
}
