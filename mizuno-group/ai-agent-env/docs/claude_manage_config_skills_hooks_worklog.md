# Claude Code — config/skills/hooks 管理実装 作業記録

**実施日時:** 2026-06-12  
**担当エージェント:** Claude Code

---

## 現在の Claude Code レイアウト

```
common/AGENTS.md         ─(symlink)─► agents/claude/CLAUDE.md ─(bind:ro)─► /home/sandbox/.claude/CLAUDE.md
common/skills/           ─(symlink)─► agents/claude/skills     ─(bind:ro)─► /home/sandbox/.claude/skills
common/hooks/                                                   ─(bind:ro)─► /home/sandbox/.claude/hooks
agents/claude/hooks.manifest.json
  └─(agentrun sync-claude が生成)
      └─ agents/claude/settings.json (.hooks セクション)       ─(bind:ro)─► /home/sandbox/.claude/settings.json
```

- `agents/claude/CLAUDE.md` → `../../common/AGENTS.md` へのシンボリックリンク
- `agents/claude/skills` → `../../common/skills` へのシンボリックリンク
- `agents/claude/settings.json` — 実ファイル（hooks セクションは manifest から生成、その他は手動管理）
- `agents/claude/hooks.manifest.json` — hooks の **source of truth**（新規作成）

---

## 実装内容

### 1. `agents/claude/hooks.manifest.json` の新規作成

Claude Code の hooks 設定の source of truth となる manifest。  
Codex の manifest（`pre_command` / `post_command` / `ignored` の3分類）と異なり、  
Claude Code は event × matcher の2軸構造を持つため、より詳細なスキーマで定義した。

各エントリは `event` / `matcher` / `entries[]` で構成。  
`entries[].if` は Claude Code 固有の matcher 内フィルタ条件（例: `Bash(git *)`)。

`ignored` フィールドも用意（現在は空）。  
`common/hooks/` の全スクリプトが hooks か ignored のいずれかに分類されていることを validate で強制する。

### 2. `agentrun sync-claude` コマンドの実装

`runtime/agentrun/agentrun` に以下の関数を追加:

| 関数 | 役割 |
|---|---|
| `claude_hooks_manifest()` | manifest パスを返す |
| `render_claude_settings_hooks()` | manifest → hooks JSON（settings.json の `.hooks` キー相当）を生成 |
| `validate_claude_hook_manifest()` | manifest の整合性と common/hooks との一致を検証 |
| `command_sync_claude()` | manifest から settings.json の hooks を再生成、symlink を修正 |
| `validate_claude_sync()` | 生成済み内容と manifest の一致、symlink の正しさを検証 |

`sync-claude` の動作:
1. manifest を検証（スクリプト実在確認、全 common/hooks/ スクリプトの分類確認）
2. jq で manifest から hooks オブジェクト JSON を生成
3. `jq --slurpfile` で `settings.json` の `.hooks` キーのみ置換（permissions / env 等は保持）
4. CLAUDE.md, skills symlink を修正

### 3. `agentrun validate` への組み込み

- `agents/claude/hooks.manifest.json` の存在確認を追加
- `validate_claude_sync()` の呼び出しを追加

---

## 保守フロー

| 操作 | 必要な手順 |
|---|---|
| `common/AGENTS.md` を編集 | symlink 経由で即座に全エージェントに反映（sync 不要） |
| `common/skills/` にスキルを追加・編集 | symlink 経由で即座に反映（sync 不要） |
| `common/hooks/` にスクリプトを追加 | `hooks.manifest.json` に event/matcher 割り当てを追記 → `agentrun sync-claude` 実行 |
| `common/hooks/` からスクリプトを削除 | `hooks.manifest.json` から削除 → `agentrun sync-claude` 実行 |
| settings.json の permissions / env 等を変更 | 直接 `agents/claude/settings.json` を編集（sync は不要） |

hooks の event/matcher 割り当ては意味論的判断が必要なため自動化していない。  
`agentrun validate` が未分類スクリプトを `[FAIL]` で報告するので、追加し忘れは検知される。

---

## validate 出力例（正常時）

```
[OK] agents/claude/hooks.manifest.json
[OK] claude-hooks-manifest:block_dangerous_command.py
[OK] claude-hooks-manifest:check_login_node.py
...（全14スクリプト）
[OK] claude-hooks-classified:all-common-hooks
[OK] claude-hooks-manifest
[OK] claude-hooks-generated:agents/claude/settings.json
[OK] claude-agents-link:agents/claude/CLAUDE.md
[OK] claude-skills-link:agents/claude/skills
```

## 動作確認

```bash
agentrun sync-claude
# → [OK] synced agents/claude/settings.json hooks from agents/claude/hooks.manifest.json
# → [OK] synced agents/claude/CLAUDE.md -> ../../common/AGENTS.md
# → [OK] synced agents/claude/skills -> ../../common/skills

agentrun validate
# → FAIL なし（claude/codex 両方 OK）
```

idempotent 確認済み（2回 sync-claude 実行しても validate が FAIL にならない）。
