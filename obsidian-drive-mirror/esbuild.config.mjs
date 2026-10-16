import esbuild from "esbuild";
import builtins from "builtin-modules";

const prod = process.argv[2] === "production";

const plugin = {
  entryPoints: ["src/main.ts"],
  bundle: true,
  // Obsidian provides these at runtime; never bundle Node/Electron (iOS has neither).
  external: ["obsidian", "electron", "@codemirror/*", "@lezer/*", ...builtins],
  format: "cjs",
  target: "es2022",
  platform: "browser",
  logLevel: "info",
  sourcemap: prod ? false : "inline",
  treeShaking: true,
  outfile: "main.js",
};

const bridge = {
  entryPoints: ["bridge/src/cli.ts"],
  bundle: true,
  format: "esm",
  platform: "node",
  target: "node20",
  logLevel: "info",
  outfile: "dist/bridge/cli.mjs",
  banner: { js: "#!/usr/bin/env node" },
};

if (prod) {
  await esbuild.build(plugin);
  await esbuild.build(bridge);
} else {
  const ctx = await esbuild.context(plugin);
  await ctx.watch();
}
