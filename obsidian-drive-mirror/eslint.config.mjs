import js from "@eslint/js";
import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: ["main.js", "dist/**", "node_modules/**"] },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    rules: {
      "@typescript-eslint/no-unused-vars": ["error", { argsIgnorePattern: "^_" }],
    },
  },
  {
    files: ["*.mjs", "bridge/**/*.ts", "tests/**/*.ts", "scripts/**/*.mjs"],
    languageOptions: { globals: { process: "readonly", console: "readonly", Buffer: "readonly" } },
  },
  {
    files: ["tests/**/*.ts"],
    rules: { "@typescript-eslint/no-explicit-any": "off" },
  },
  {
    // The plugin must run on iOS: no Node built-ins, no Electron.
    files: ["src/**/*.ts"],
    rules: {
      "no-restricted-imports": ["error", {
        patterns: [{ regex: "^(node:|fs$|path$|crypto$|electron$|child_process$|os$)", message: "Plugin code must not depend on Node/Electron (iOS)." }],
      }],
    },
  },
);
