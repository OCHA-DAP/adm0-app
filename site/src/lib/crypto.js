// PBKDF2-SHA-256 to AES-GCM-256, shared by scripts/seal-url.mjs and unlock.ts so both derive the same key.
/** @param {string} password @param {Uint8Array<ArrayBuffer>} salt @param {number} iterations @param {KeyUsage} usage */
export async function deriveKey(password, salt, iterations, usage) {
  const material = await crypto.subtle.importKey("raw", new TextEncoder().encode(password), "PBKDF2", false, [
    "deriveKey",
  ]);
  return crypto.subtle.deriveKey(
    { name: "PBKDF2", salt, iterations, hash: "SHA-256" },
    material,
    { name: "AES-GCM", length: 256 },
    false,
    [usage],
  );
}
