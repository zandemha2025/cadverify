const CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ";

function encodeTime(value: number, length: number): string {
  let output = "";
  for (let index = 0; index < length; index += 1) {
    output = CROCKFORD[value % 32] + output;
    value = Math.floor(value / 32);
  }
  return output;
}

function encodeRandom(bytes: Uint8Array): string {
  let output = "";
  let buffer = 0;
  let bits = 0;
  for (const byte of bytes) {
    buffer = (buffer << 8) | byte;
    bits += 8;
    while (bits >= 5) {
      bits -= 5;
      output += CROCKFORD[(buffer >>> bits) & 31];
      buffer &= (1 << bits) - 1;
    }
  }
  if (bits > 0) output += CROCKFORD[(buffer << (5 - bits)) & 31];
  return output;
}

/**
 * Generate a browser-side ULID used as both reconstruction job ID and
 * Idempotency-Key. One call is reused by every automatic POST retry.
 */
export function createReconstructionSubmissionId(
  nowMs = Date.now(),
  fillRandom: (bytes: Uint8Array) => void = (bytes) =>
    globalThis.crypto.getRandomValues(bytes),
): string {
  const random = new Uint8Array(10);
  fillRandom(random);
  return `${encodeTime(nowMs, 10)}${encodeRandom(random)}`;
}
