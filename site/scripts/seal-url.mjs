// Writes src/lib/tiles.sealed.json from TILES_URL and SITE_PASSWORD.
import { writeFileSync } from "node:fs";
import { deriveKey } from "../src/lib/crypto.js";

const url = process.env.TILES_URL ?? (process.env.CI ? undefined : "/tiles");
if (!url) throw new Error("TILES_URL is not set");
const password = process.env.SITE_PASSWORD;
if (!password) throw new Error("SITE_PASSWORD is not set");

const iterations = 600000;
const salt = crypto.getRandomValues(new Uint8Array(16));
const iv = crypto.getRandomValues(new Uint8Array(12));
const key = await deriveKey(password, salt, iterations, "encrypt");
const data = new Uint8Array(await crypto.subtle.encrypt({ name: "AES-GCM", iv }, key, new TextEncoder().encode(url)));
const b64 = (a) => Buffer.from(a).toString("base64");
writeFileSync(
  new URL("../src/lib/tiles.sealed.json", import.meta.url),
  JSON.stringify({ iterations, salt: b64(salt), iv: b64(iv), data: b64(data) }) + "\n",
);
console.log(`sealed ${url.startsWith("/") ? url : "tiles URL"}`);
