// Path rules shared by the plugin and the bridge. Pure functions only (runs on iOS and Node).

const MAX_SEGMENT_BYTES = 255;
// Characters that are invalid on Windows (the source) or rejected by Obsidian on some platforms.
const FORBIDDEN_CHARS = /[\\:*?"<>|]/;
// eslint-disable-next-line no-control-regex
const CONTROL_CHARS = /[\u0000-\u001f\u007f]/;

export type PathProblem =
  | "empty"
  | "absolute"
  | "backslash"
  | "control_char"
  | "forbidden_char"
  | "dot_segment"
  | "empty_segment"
  | "segment_too_long"
  | "trailing_space_or_dot";

/**
 * Validate a vault-relative POSIX path received from a remote or built locally.
 * Returns null when the path is acceptable as a *managed* path (hidden-ness is checked separately).
 */
export function validateRelPath(path: string): PathProblem | null {
  if (path.length === 0) return "empty";
  if (path.startsWith("/")) return "absolute";
  if (path.includes("\\")) return "backslash";
  if (CONTROL_CHARS.test(path)) return "control_char";
  for (const seg of path.split("/")) {
    const problem = validateSegment(seg);
    if (problem) return problem;
  }
  return null;
}

export function validateSegment(seg: string): PathProblem | null {
  if (seg.length === 0) return "empty_segment";
  if (seg === "." || seg === "..") return "dot_segment";
  if (seg.includes("\\")) return "backslash";
  if (CONTROL_CHARS.test(seg)) return "control_char";
  if (FORBIDDEN_CHARS.test(seg)) return "forbidden_char";
  if (/[ .]$/.test(seg)) return "trailing_space_or_dot";
  if (new TextEncoder().encode(seg).length > MAX_SEGMENT_BYTES) return "segment_too_long";
  return null;
}

/** True when any segment starts with "." (.obsidian, .trash, .git, .gitkeep, ...). Hidden paths are never managed. */
export function isHiddenPath(path: string): boolean {
  return path.split("/").some((seg) => seg.startsWith("."));
}

/**
 * Paths the mirror must never read for management, write, or delete.
 * `configDir` is Obsidian's `vault.configDir` (normally ".obsidian"; may be customised).
 */
export function isProtectedPath(path: string, configDir: string): boolean {
  if (path === configDir || path.startsWith(configDir + "/")) return true;
  return isHiddenPath(path);
}

/**
 * Key used to detect paths that a case-insensitive and/or normalization-insensitive
 * filesystem (Windows, default APFS) would treat as the same file.
 */
export function collisionKey(path: string): string {
  return path.normalize("NFC").toLowerCase();
}

export function parentDirs(path: string): string[] {
  const segs = path.split("/");
  const dirs: string[] = [];
  for (let i = 1; i < segs.length; i++) dirs.push(segs.slice(0, i).join("/"));
  return dirs;
}

export function joinPath(...parts: string[]): string {
  return parts.filter((p) => p.length > 0).join("/");
}
