import { describe, expect, it } from "vitest";
import { ManifestError, validateManifest } from "../../src/inventory/manifest";
import { isProtectedPath, validateRelPath } from "../../src/security/paths";

const H = "a".repeat(64);
const base = (entries: unknown[]) => ({
  schemaVersion: 1,
  snapshotId: "s1",
  complete: true,
  generatedAt: "2026-10-16T00:00:00Z",
  rootIdentity: { rootId: "r", name: "LLM-Wiki" },
  entries,
  excluded: { hidden: 3 },
});
const entry = (path: string, id = path) => ({ id, path, size: 1, modifiedTime: null, sha256: H });

describe("validateRelPath", () => {
  it.each([
    ["", "empty"],
    ["/etc/passwd", "absolute"],
    ["../x", "dot_segment"],
    ["a/../../x", "dot_segment"],
    ["a/./b", "dot_segment"],
    ["a//b", "empty_segment"],
    ["a\\b", "backslash"],
    ["a\u0000b", "control_char"],
    ["a/b:c", "forbidden_char"],
    ["trailing.", "trailing_space_or_dot"],
    ["x".repeat(256), "segment_too_long"],
  ])("rejects %j", (p, problem) => {
    expect(validateRelPath(p)).toBe(problem);
  });

  it("accepts normal and Japanese paths", () => {
    expect(validateRelPath("Notes/日本語 ノート.md")).toBeNull();
  });

  it("protects configDir and hidden paths", () => {
    expect(isProtectedPath(".obsidian/plugins/drive-mirror/data.json", ".obsidian")).toBe(true);
    expect(isProtectedPath("_cfg/x", "_cfg")).toBe(true);
    expect(isProtectedPath("a/.git/config", ".obsidian")).toBe(true);
    expect(isProtectedPath("Notes/a.md", ".obsidian")).toBe(false);
  });
});

describe("validateManifest", () => {
  it("accepts a valid manifest", () => {
    const m = validateManifest(base([entry("a.md"), entry("d/b.md")]));
    expect(m.entries).toHaveLength(2);
    expect(m.excluded).toEqual({ hidden: 3 });
  });

  it("accepts an empty but complete manifest", () => {
    expect(validateManifest(base([])).entries).toEqual([]);
  });

  it.each([
    ["incomplete", { ...base([]), complete: false }],
    ["wrong schema", { ...base([]), schemaVersion: 2 }],
    ["no root", { ...base([]), rootIdentity: undefined }],
    ["traversal", base([entry("../evil.md")])],
    ["hidden", base([entry(".obsidian/app.json")])],
    ["case collision", base([entry("A.md", "1"), entry("a.md", "2")])],
    ["NFC/NFD collision", base([entry("が.md", "1"), entry("が.md", "2")])],
    ["duplicate id", base([entry("a.md", "x"), entry("b.md", "x")])],
    ["file/dir clash", base([entry("a"), entry("a/b.md")])],
    ["bad hash", base([{ ...entry("a.md"), sha256: "zz" }])],
    ["negative size", base([{ ...entry("a.md"), size: -1 }])],
  ])("rejects %s", (_name, raw) => {
    expect(() => validateManifest(raw)).toThrow(ManifestError);
  });
});
