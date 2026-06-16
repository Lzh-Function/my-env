# Agent Config Asymmetry Audit

**Date:** 2026-06-12T14:47:21+09:00

各エージェント（claude / codex / antigravity）の settings・hooks・skills・AGENTS.md のコンテナ内への渡し方の現状と非対称点をまとめる。

---

## 1. settings / config のコンテナへの渡し方

| | claude | codex | antigravity |
|---|---|---|---|
| ファイル形式 | JSON | TOML | JSON |
| モード別ファイル | `settings.assist.json`, `settings.experiment.json` | `config.assist.toml`, `config.experiment.toml` | **なし** |
| 生成処理 | `generate_container_config()` で jq によりベース+オーバーレイをマージ | `generate_container_config()` でファイルコピー | **何もしない** |
| コンテナへの渡し方 | `container_config/settings.json` をバインドマウント | `link_codex_shared_assets()` で `home/.codex/config.toml` にファイルコピー | `container_config/settings.json` をバインドマウント（`/home/sandbox/.gemini/settings.json`） |

> ~~**問題:** `agents/antigravity/settings.json` は `generate_container_config()` にも `home_config_mounts()` にも対応コードがなく、コンテナ内に渡されていない。~~ **修正済み** (`generate_container_config()` に antigravity ブランチ追加、`home_config_mounts()` にバインドマウント追加)

---

## 2. hooks のコンテナへの渡し方

| | claude | codex | antigravity |
|---|---|---|---|
| hooks 定義場所 | `settings.json` 内の `hooks:` フィールド | 独立した `hooks.json` | 独立した `hooks.json` |
| hooks スクリプトの参照パス形式 | `~/.claude/hooks/…`（ホーム相対） | `/home/sandbox/ai-agent-config/common/hooks/…`（**絶対パスハードコード**） | `~/.gemini/antigravity-cli/hooks/…`（ホーム相対） |
| `common/hooks` のマウント先 | `/home/sandbox/.claude/hooks` | マウントせず（絶対パス直参照） | `/home/sandbox/.gemini/antigravity-cli/hooks` |

> **問題:** codex の `hooks.json` が `/home/sandbox/ai-agent-config/common/hooks/…` を絶対パスでハードコードしており、マウントパスが変わると壊れる。claude・antigravity はホーム相対パスで参照しているため柔軟性がある。

> **問題:** claude だけ hooks が `settings.json` 内に内包されており、codex・antigravity の独立 `hooks.json` とは構造が異なる。

---

## 3. AGENTS.md のコンテナへの渡し方

| | claude | codex | antigravity |
|---|---|---|---|
| ファイル名 | `CLAUDE.md`（Claude Code 専用名） | `AGENTS.md` | `AGENTS.md` + `GEMINI.md` の 2 枚 |
| 実体 | `common/AGENTS.md` へのシンボリックリンク | `common/AGENTS.md` へのシンボリックリンク | 独立ファイル（`common/AGENTS.md` と未同期の可能性あり） |
| コンテナ内マウント先 | `/home/sandbox/.claude/CLAUDE.md` | `/home/sandbox/.codex/AGENTS.md` | `/home/sandbox/.gemini/AGENTS.md`, `/home/sandbox/.gemini/GEMINI.md` |

> **問題:** antigravity の `AGENTS.md` は独立ファイルで `common/AGENTS.md` へのシンボリックリンクになっていない。内容が乖離するリスクがある。

---

## 4. skills のコンテナへの渡し方

| | claude | codex | antigravity |
|---|---|---|---|
| ソース | `agents/claude/skills` → `common/skills` へのシンボリックリンク | `agents/codex/skills` → `common/skills` へのシンボリックリンク | `agents/antigravity/skills` → `common/skills` へのシンボリックリンク |
| コンテナへの渡し方 | シンボリックリンクごとバインドマウント | `link_codex_shared_assets()` で各スキルへのリンクを `home/.codex/skills/` に個別生成 | シンボリックリンクごとバインドマウント |
| コンテナ内パス | `~/.claude/skills` | `~/.codex/skills/` | `~/.gemini/antigravity-cli/skills` |

---

## 5. 問題点サマリー

| 優先度 | 問題 | 影響エージェント | 状態 |
|---|---|---|---|
| 高 | `settings.json` がコンテナに入らない | antigravity | **修正済み** |
| 高 | `settings.assist.json` の `extends` フィールドがマージ後の settings.json に漏れる（`/doctor 1 setup issue` の原因） | claude | **修正済み** (`del(.extends)` を追加) |
| 中 | hooks パスが絶対パスハードコード | codex | 未修正 |
| 中 | `AGENTS.md` が `common/AGENTS.md` と未同期 | antigravity | 未修正 |
| 低 | hooks 定義の構造が不統一（settings 内包 vs 独立ファイル） | claude vs codex/antigravity | 未修正 |
| 低 | `attribution` フィールドが空文字列で定義されている（無害の可能性大） | claude | 未修正 |
| 低 | `runtimeProfile` フィールドが Claude Code 公式設定かどうか不明 | claude | 未修正 |
