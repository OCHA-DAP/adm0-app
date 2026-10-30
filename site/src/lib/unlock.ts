import { deriveKey } from "$lib/crypto.js";
import sealed from "$lib/tiles.sealed.json";

// The tiles base URL ships only as AES-GCM ciphertext, keyed by PBKDF2 of the password.
export async function unlock(password: string): Promise<string | null> {
  const bytes = (b64: string) => Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
  const key = await deriveKey(password, bytes(sealed.salt), sealed.iterations, "decrypt");
  try {
    const plain = await crypto.subtle.decrypt({ name: "AES-GCM", iv: bytes(sealed.iv) }, key, bytes(sealed.data));
    return new TextDecoder().decode(plain);
  } catch {
    return null;
  }
}
