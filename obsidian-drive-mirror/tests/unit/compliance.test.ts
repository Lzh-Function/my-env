import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

// DESIGN §0 / §10.3: custom code must not talk to Google APIs, and the read path must not be able to write.

function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((n) => {
    const p = join(dir, n);
    return statSync(p).isDirectory() ? sources(p) : p.endsWith(".ts") ? [p] : [];
  });
}

const files = [...sources("src"), ...sources("bridge/src")];

describe("compliance guards", () => {
  it("contains no Google API / OAuth endpoints or client libraries", () => {
    const forbidden = /googleapis|accounts\.google\.com|oauth2|gapi\b|client_secret|refresh_token|google-auth-library/i;
    for (const f of files) expect(readFileSync(f, "utf8"), f).not.toMatch(forbidden);
  });

  it("RemoteReadProvider exposes no mutating methods", () => {
    const iface = /interface RemoteReadProvider \{([\s\S]*?)\n\}/.exec(readFileSync("src/provider/types.ts", "utf8"))![1]!;
    expect(iface).not.toMatch(/\b(write|upload|delete|remove|rename|move|trash|create|update|patch|put|post)\w*\s*\(/i);
  });

  it("bridge never opens files for writing under root and only serves GET/HEAD", () => {
    const server = readFileSync("bridge/src/server.ts", "utf8");
    const scan = readFileSync("bridge/src/scan.ts", "utf8");
    for (const src of [server, scan]) {
      expect(src).not.toMatch(/\b(writeFile|appendFile|unlink|rmSync|rm\(|rename|mkdir|createWriteStream|chmod|utimes)\b/);
    }
    expect(server).toMatch(/req\.method !== "GET" && req\.method !== "HEAD"/);
  });

  it("plugin code does not import Node or Electron (iOS)", () => {
    for (const f of sources("src")) expect(readFileSync(f, "utf8"), f).not.toMatch(/from "(node:|fs"|path"|crypto"|electron")/);
  });
});
