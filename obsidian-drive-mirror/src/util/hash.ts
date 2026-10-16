import { sha256 } from "@noble/hashes/sha2.js";
import { bytesToHex } from "@noble/hashes/utils.js";

// Pure-JS SHA-256 so that large files can be hashed incrementally (WebCrypto has no streaming digest).

export function sha256Hex(data: ArrayBuffer | Uint8Array): string {
  return bytesToHex(sha256(data instanceof Uint8Array ? data : new Uint8Array(data)));
}

export interface IncrementalHash {
  update(chunk: ArrayBuffer | Uint8Array): void;
  hex(): string;
}

export function createSha256(): IncrementalHash {
  const h = sha256.create();
  return {
    update(chunk) {
      h.update(chunk instanceof Uint8Array ? chunk : new Uint8Array(chunk));
    },
    hex() {
      return bytesToHex(h.digest());
    },
  };
}
