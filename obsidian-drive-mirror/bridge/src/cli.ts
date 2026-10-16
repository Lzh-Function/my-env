import { createHash, randomBytes } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { basename, dirname, resolve } from "node:path";
import { parseArgs } from "node:util";
import { defaultConfigPath, defaultStateDir, loadConfig, resolveRoot, validateConfig, type BridgeConfig } from "./config";
import { createBridgeServer } from "./server";
import { createSnapshotter, IncompleteError } from "./snapshot";

const USAGE = `drive-mirror-bridge — read-only vault bridge (DESIGN §0, §5)

Usage:
  drive-mirror-bridge init --root <abs-path> --login <tailscale-login>[,<login>...] [--name LLM-Wiki] [--port 8787] [--force]
  drive-mirror-bridge rotate-token
  drive-mirror-bridge check          # build one snapshot and print counts/problems (no server)
  drive-mirror-bridge serve

Options:
  --config <path>   default: ${defaultConfigPath()}
`;

function writeConfig(path: string, cfg: BridgeConfig): void {
  mkdirSync(dirname(path), { recursive: true, mode: 0o700 });
  writeFileSync(path, JSON.stringify(cfg, null, 2) + "\n", { mode: 0o600 });
}

function newToken(): { token: string; sha: string } {
  const token = randomBytes(32).toString("base64url");
  return { token, sha: createHash("sha256").update(token).digest("hex") };
}

async function main(): Promise<void> {
  const { values, positionals } = parseArgs({
    allowPositionals: true,
    options: {
      config: { type: "string" },
      root: { type: "string" },
      login: { type: "string" },
      name: { type: "string" },
      port: { type: "string" },
      force: { type: "boolean" },
      help: { type: "boolean", short: "h" },
    },
  });
  const cmd = positionals[0];
  const configPath = resolve(values.config ?? defaultConfigPath());
  if (!cmd || values.help) {
    process.stdout.write(USAGE);
    return;
  }

  if (cmd === "init") {
    if (existsSync(configPath) && !values.force) throw new Error(`${configPath} exists; use --force to overwrite`);
    if (!values.root) throw new Error("--root is required");
    const root = resolve(values.root);
    const { token, sha } = newToken();
    const cfg: BridgeConfig = {
      root,
      rootId: randomBytes(12).toString("base64url"),
      rootName: values.name ?? basename(root),
      host: "127.0.0.1",
      port: values.port ? Number(values.port) : 8787,
      tokenSha256: sha,
      allowedTailscaleLogins: (values.login ?? "").split(",").map((s) => s.trim()).filter(Boolean),
      requireTailscaleIdentity: true,
      requireMarker: ".obsidian",
      requireReadOnlyRoot: true,
      stabilityDelayMs: 3000,
      maxSnapshots: 4,
      stateDir: defaultStateDir(),
    };
    validateConfig(cfg);
    writeConfig(configPath, cfg);
    process.stdout.write(`Wrote ${configPath}\n\nBridge token (shown once; paste into the plugin settings, never commit it):\n\n  ${token}\n\n`);
    return;
  }

  if (cmd === "rotate-token") {
    const cfg = JSON.parse(readFileSync(configPath, "utf8")) as BridgeConfig;
    const { token, sha } = newToken();
    cfg.tokenSha256 = sha;
    writeConfig(configPath, cfg);
    process.stdout.write(`New bridge token (old one is now invalid; restart the service):\n\n  ${token}\n\n`);
    return;
  }

  const cfg = loadConfig(configPath);
  const root = resolveRoot(cfg);

  if (cmd === "check") {
    const snaps = await createSnapshotter(cfg, root);
    const t0 = Date.now();
    try {
      const s = await snaps.build();
      const bytes = s.files.reduce((a, f) => a + f.size, 0);
      const max = s.files.reduce((a, f) => Math.max(a, f.size), 0);
      process.stdout.write(
        `complete: true\nfiles: ${s.files.length}\nbytes: ${bytes}\nlargest: ${max}\nexcluded: ${JSON.stringify(s.excluded)}\nelapsed: ${Date.now() - t0}ms\n`,
      );
    } catch (e) {
      if (!(e instanceof IncompleteError)) throw e;
      process.stdout.write(`complete: false\nproblems:\n${e.problems.map((p) => `  - ${p}`).join("\n")}\n`);
      process.exitCode = 2;
    }
    return;
  }

  if (cmd === "serve") {
    const snapshots = await createSnapshotter(cfg, root);
    const log = (line: string) => process.stdout.write(`${new Date().toISOString()} ${line}\n`);
    const server = createBridgeServer({ cfg, root, snapshots, log });
    server.listen(cfg.port, cfg.host, () => log(`listening on http://${cfg.host}:${cfg.port} root=${cfg.rootName}`));
    const stop = () => server.close(() => process.exit(0));
    process.on("SIGTERM", stop);
    process.on("SIGINT", stop);
    return;
  }

  throw new Error(`unknown command ${cmd}\n\n${USAGE}`);
}

main().catch((e: unknown) => {
  process.stderr.write(`error: ${(e as Error).message}\n`);
  process.exit(1);
});
