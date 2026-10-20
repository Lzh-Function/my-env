"""Bounded, explicit review inputs. No repository code is executed here."""

import difflib
import fnmatch
import hashlib
import json
import os
import stat
import subprocess
import time
from pathlib import Path

MAX_FILE = 4 * 1024 * 1024
MAX_TOTAL = 32 * 1024 * 1024
MAX_FILES = 10000
PRIVATE = {
    ".git",
    ".agent-runs",
    ".agentrun",
    ".ssh",
    ".aws",
    ".gnupg",
    ".codex",
    ".claude",
    ".reviewer",
    "node_modules",
    ".venv",
    "__pycache__",
}
SPECIAL = {"AGENTS.md", "CLAUDE.md", ".mcp.json"}


def digest(value):
    return hashlib.sha256(value).hexdigest()


def canonical(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def git(repo, *args, binary=False):
    result = subprocess.run(
        [
            "git",
            "-c",
            "core.fsmonitor=false",
            "-c",
            "core.hooksPath=/dev/null",
            "-C",
            str(repo),
            *args,
        ],
        capture_output=True,
        timeout=30,
        check=True,
    )
    return result.stdout if binary else result.stdout.decode("utf-8").strip()


def private(path):
    return any(
        part in PRIVATE
        or part == ".env"
        or part.startswith(".env.")
        or part.endswith((".pem", ".key"))
        or part in {"auth.json", ".credentials.json"}
        for part in Path(path).parts
    )


def safe_file(path, roots):
    """Reject symlinks in every component, including links back inside a root."""
    path = Path(os.path.abspath(path))
    root = next((r for r in roots if path.is_relative_to(r)), None)
    if root is None or private(path.relative_to(root)):
        raise ValueError(
            "Input is outside allowed roots or contains private/cache data: "
            + str(path)
        )
    current = root
    for part in path.relative_to(root).parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("Symlink inputs are not supported: " + str(path))
    return path


def read_file(path, roots):
    path = safe_file(path, roots)
    root = next(r for r in roots if path.is_relative_to(r))
    parts = path.relative_to(root).parts
    if not parts:
        raise ValueError("Input must be a regular file")
    directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        # Resolve every component relative to an open directory descriptor, so
        # replacing a parent directory with a symlink cannot escape the roots.
        for part in parts[:-1]:
            child = os.open(
                part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory
            )
            os.close(directory)
            directory = child
        fd = os.open(
            parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory
        )
    finally:
        os.close(directory)
    with os.fdopen(fd, "rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_FILE:
            raise ValueError("Input is not a bounded regular file: " + str(path))
        content = stream.read(MAX_FILE + 1)
        after = os.fstat(stream.fileno())
        if len(content) > MAX_FILE or (
            before.st_size,
            before.st_mtime_ns,
            before.st_ino,
        ) != (after.st_size, after.st_mtime_ns, after.st_ino):
            raise ValueError("Input changed while being read: " + str(path))
    return content


def capture(
    repo, run, destination, base, includes, brief, baseline, excludes=(), cancelled=None
):
    deadline = time.monotonic() + 120
    repo, run, destination = (
        Path(repo).resolve(),
        Path(run).resolve(),
        Path(destination),
    )
    roots = (repo, run / "artifacts", run / "reviews")
    base = git(repo, "rev-parse", "--verify", base + "^{commit}")
    head = git(repo, "rev-parse", "HEAD")
    status = git(
        repo, "status", "--porcelain=v1", "-z", "--untracked-files=no", binary=True
    )
    index_hash = digest(git(repo, "ls-files", "--stage", "-z", binary=True))
    names = set(git(repo, "ls-files", "-z", binary=True).decode().split("\0")) - {""}
    names.update(
        git(repo, "diff", "--name-only", "-z", "--no-renames", base, binary=True)
        .decode()
        .split("\0")
    )
    entries, omitted, excluded, total = [], [], [], 0

    def add(path, category, explicit=False):
        nonlocal total
        if cancelled is not None and cancelled.is_set():
            raise InterruptedError("Review cancelled during snapshot acquisition")
        if time.monotonic() >= deadline:
            raise TimeoutError("Review snapshot acquisition deadline exceeded")
        path = Path(os.path.abspath(path))
        is_private = (
            private(path.relative_to(repo))
            if path.is_relative_to(repo)
            else private(path.name)
        )
        if is_private:
            if explicit:
                raise ValueError("Private/cache input cannot be included: " + str(path))
            excluded.append({"path": str(path), "reason": "private/cache"})
            return
        if len(entries) >= MAX_FILES:
            raise ValueError("Too many review files; exclude irrelevant paths")
        if not path.exists() and not path.is_symlink():
            entries.append(
                {"original": str(path), "path": None, "sha256": None, "deleted": True}
            )
            return
        content = read_file(path, roots)
        total += len(content)
        if total > MAX_TOTAL:
            raise ValueError(
                "Review input exceeds total size limit; select a smaller scope"
            )
        if category == "source":
            relative = path.relative_to(repo)
        else:
            relative = Path(digest(str(path).encode())[:12]) / path.name
        # Instructions/configurations are data, never discovered configuration.
        if relative.name in SPECIAL or any(p.startswith(".") for p in relative.parts):
            relative = Path("configuration-data") / (
                digest(str(path).encode())[:12] + ".txt"
            )
        target = Path(category) / relative
        output = destination / target
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(content)
        output.chmod(0o444)
        try:
            content.decode("utf-8")
            textual = True
        except UnicodeError:
            textual = False
            omitted.append(
                {
                    "path": str(path),
                    "reason": "binary requires independent visual/content validation",
                }
            )
        entries.append(
            {
                "original": str(path),
                "path": target.as_posix(),
                "sha256": digest(content),
                "size": len(content),
                "text": textual,
                "mode": stat.S_IMODE(path.stat().st_mode),
            }
        )

    for name in sorted(names - {""}):
        if any(fnmatch.fnmatchcase(name, pattern) for pattern in excludes):
            excluded.append({"path": name, "reason": "explicit scope exclusion"})
            continue
        add(repo / name, "source")
    for name in sorted(set(includes)):
        add(Path(name) if Path(name).is_absolute() else repo / name, "artifacts", True)
    brief_path = Path(brief) if Path(brief).is_absolute() else repo / brief
    add(brief_path, "brief", True)
    # Generate a patch only for selected, non-private source paths.
    selected = [
        str(Path(e["original"]).relative_to(repo))
        for e in entries
        if Path(e["original"]).is_relative_to(repo)
        and not private(Path(e["original"]).relative_to(repo))
    ]
    patch = (
        git(
            repo,
            "diff",
            "--binary",
            "--no-ext-diff",
            "--no-textconv",
            "--no-renames",
            base,
            "--",
            *selected,
            binary=True,
        )
        if selected
        else b""
    )
    if len(patch) + total > MAX_TOTAL:
        raise ValueError("Review patch exceeds total input limit")
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "diff.patch").write_bytes(patch)
    if head != git(repo, "rev-parse", "HEAD") or status != git(
        repo, "status", "--porcelain=v1", "-z", "--untracked-files=no", binary=True
    ):
        raise ValueError("Repository changed during snapshot capture")
    result = {
        "version": 1,
        "repo": str(repo),
        "base": base,
        "head": head,
        "status": status.decode(),
        "index_sha256": index_hash,
        "worker_start": baseline,
        "files": entries,
        "omitted": omitted,
        "excluded": excluded,
        "limits": {
            "file_bytes": MAX_FILE,
            "total_bytes": MAX_TOTAL,
            "files": MAX_FILES,
        },
        "patch_sha256": digest(patch),
    }
    result["target_id"] = digest(canonical(result))
    atomic_json(destination / "manifest.json", result)
    if not current(result, roots):
        raise ValueError("Files changed during snapshot capture")
    return result


def current(manifest, roots):
    if manifest.get("repo"):
        try:
            if (
                git(manifest["repo"], "rev-parse", "HEAD") != manifest["head"]
                or git(
                    manifest["repo"],
                    "status",
                    "--porcelain=v1",
                    "-z",
                    "--untracked-files=no",
                    binary=True,
                ).decode()
                != manifest["status"]
            ):
                return False
            if (
                digest(git(manifest["repo"], "ls-files", "--stage", "-z", binary=True))
                != manifest["index_sha256"]
            ):
                return False
        except (OSError, subprocess.SubprocessError):
            return False
    for entry in manifest["files"]:
        path = Path(entry["original"])
        try:
            if entry.get("deleted"):
                if path.exists() or path.is_symlink():
                    return False
            elif (
                digest(read_file(path, roots)) != entry["sha256"]
                or "mode" in entry
                and stat.S_IMODE(path.stat().st_mode) != entry["mode"]
            ):
                return False
        except (OSError, ValueError):
            return False
    return True


def supplement(paths, repo, run, destination):
    entries = []
    roots = (repo, run / "artifacts", run / "reviews")
    for name in paths:
        path = Path(name) if Path(name).is_absolute() else repo / name
        content = read_file(path, roots)
        if sum(e["size"] for e in entries) + len(content) > MAX_TOTAL:
            raise ValueError("Additional evidence exceeds size limit")
        target = "supplements/" + digest(str(path).encode())[:12] + "-" + path.name
        output = destination / target
        output.parent.mkdir(parents=True, exist_ok=True)
        if output.exists() and digest(output.read_bytes()) != digest(content):
            raise ValueError("Additional evidence changed; start another round")
        output.write_bytes(content)
        output.chmod(0o444)
        entries.append(
            {
                "original": str(path),
                "path": target,
                "size": len(content),
                "sha256": digest(content),
            }
        )
    return entries


def compare_snapshots(previous, current_manifest, old_input, new_input):
    """Compare captured bytes, never mutable original files, for a recheck."""
    before = {e["original"]: e for e in previous["files"]}
    after = {e["original"]: e for e in current_manifest["files"]}
    changes, patches = [], []
    for name in sorted(before.keys() | after.keys()):
        old, new = before.get(name, {}), after.get(name, {})
        if old.get("sha256") == new.get("sha256"):
            continue
        changes.append(
            {
                "original": name,
                "before_sha256": old.get("sha256"),
                "after_sha256": new.get("sha256"),
                "before_path": old.get("path"),
                "after_path": new.get("path"),
            }
        )
        if all(not e.get("path") or e.get("text") for e in (old, new)):
            a = (
                (old_input / old["path"]).read_text().splitlines(keepends=True)
                if old.get("path")
                else []
            )
            b = (
                (new_input / new["path"]).read_text().splitlines(keepends=True)
                if new.get("path")
                else []
            )
            patches.extend(
                difflib.unified_diff(
                    a, b, fromfile="before/" + name, tofile="after/" + name
                )
            )
    patch = "".join(patches).encode()
    if (
        len(patch) + sum(e.get("size", 0) for e in current_manifest["files"])
        > MAX_TOTAL
    ):
        raise ValueError("Recheck input and prior diff exceed size limit")
    atomic_json(new_input / "prior/changes.json", changes)
    (new_input / "prior/changes.patch").write_bytes(patch)
