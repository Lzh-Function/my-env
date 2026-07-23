# Obsidian × Claude Code / Codex

Obsidianの執筆を、Claude Code / Codexから直接操作できるようにするためのセットアップ。
`wsl-wezterm-zellij`(このリポジトリの別ディレクトリ)とは独立した構成で、chezmoiの
管理対象にも含めていない。

Vault本体は別リポジトリ(private, `obsidian-vault`)で、このリポジトリには含めない。

## アーキテクチャ(3つの経路)

```
Windows(このディレクトリ直下、setup_obsidian.ps1)
 ├─ Obsidian(GUI, ネイティブ)── Vaultを直接開く
 ├─ Vault本体を Windows側にclone(%USERPROFILE%\ObsidianVault)
 ├─ Claude Code(ネイティブ)┐
 └─ Codex CLI(ネイティブ)  ┴─ Vaultディレクトリ内で起動、obsidian-skills経由でVaultを操作
    (Obsidian公式CLIがGUIアプリ起動中前提・Windowsネイティブ実行ファイルのため)

WSL(参考。セットアップ不要)
 └─ /mnt/c/Users/<user>/ObsidianVault 経由でVaultのファイルに直接アクセス可能
    (git/nvimなどで軽く読み書きする分には問題ない速度)

Slurmクラスタ(slurm/、GPU実験結果をノート化)
 └─ ログインノードで認証・vault clone → 計算ノードのApptainerコンテナへbind mount
    → エージェントが実験結果を見てノートを書き、vaultへpush(詳細は slurm/README.md)
```

Windows側とSlurm側は完全に独立していて、どちらも同じ`obsidian-vault`リポジトリへ
それぞれ独自にgit push/pullする(お互いの存在を意識しない)。

### なぜWindowsネイティブなのか(WSL側のzjとは別系統にした理由)

Obsidianは2026年時点でGUIアプリ内に公式CLI機能を持つ(Obsidian 1.12.7+、設定から
有効化)。このCLIは**Obsidianアプリ本体が起動している時だけ**使え、Windows版は
"Obsidian.com terminal redirector"というWindowsネイティブの実行ファイルとして
PATHに登録される。

Vault・Obsidian本体がWindows側にある以上、この公式CLIを確実に使うにはClaude Code /
CodexもWindows側で動かすのが一番堅い。WSL側から`ssh.exe`のようにinterop越しに
Windowsの実行ファイルを叩く手も理論上はあるが、GUIアプリとやり取りする分ネットワーク
クライアントの`ssh.exe`より複雑になりそうで未検証。そのため今回は「Windows側で完結」
を選んだ(`wsl-wezterm-zellij`側の`zj [py|tex|] [claude|codex|both]`とは完全に別の
インストール・別のログインになる)。

## 前提: Vault用リポジトリを先に作成しておく

このリポジトリ(`my-env`)にVault本体は含めない。**先にGitHubで`obsidian-vault`と
いう名前のprivateリポジトリを作成しておくこと**(`setup_obsidian.ps1`はリポジトリの
作成は行わない、cloneだけ):

```bash
gh repo create Lzh-Function/obsidian-vault --private
```

(`gh`が無ければ https://github.com/new から手動作成でもよい。privateにすること)

## セットアップ

Windows側でPowerShellを開いて:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
& "$env:USERPROFILE\.local\share\chezmoi\obsidian-agents\setup_obsidian.ps1"
```

`setup_obsidian.ps1`が行うこと:

1. winget: Obsidian・Node.js・Git を導入
2. Claude Code(ネイティブ版)を`irm https://claude.ai/install.ps1 | iex`で導入
3. Codex CLI を`npm install -g @openai/codex`で導入
4. `obsidian-vault`を`%USERPROFILE%\ObsidianVault`へclone
5. [`kepano/obsidian-skills`](https://github.com/kepano/obsidian-skills)を
   `npx skills add`で導入(Claude Code / Codexの両方を自動検出し、それぞれ正しい
   場所に配置される: Claude Codeは`%USERPROFILE%\ObsidianVault\.claude\skills\`
   にプロジェクトスコープで、Codexは`~/.codex/skills/`にグローバルスコープで)

### スクリプト実行後、手動で必要な操作

- Obsidianを起動して`%USERPROFILE%\ObsidianVault`をVaultとして開く
- 設定 → General → 「Command line interface」を有効化(自動化不可)
- `claude`・`codex`をそれぞれ初回起動してログイン(WSL側とは別アカウント状態なので
  別途ログインが必要)

## 日常の使い方

```powershell
cd $env:USERPROFILE\ObsidianVault
claude   # または codex
```

(obsidian-skillsがVault直下の`.claude/`にプロジェクトスコープで入っているため、
必ずVaultディレクトリ内から起動すること)

起動方法(WezTermに専用タブを作るか、普通のPowerShell/Windows Terminalで十分か)は
まだ決めていない。実際に使ってみてから調整する。

## WSL側からVaultを読み書きする場合

```bash
cd /mnt/c/Users/<Windowsユーザー名>/ObsidianVault
```

Neovimなどで軽く読み書きする分には問題ないが、Obsidianアプリ自身の動作(インデックス
更新やファイル監視)に影響が出るような重い操作は避ける。gitでVaultをバージョン管理
する場合、Windows側(NTFS)にあるためCRLF問題が出やすい点に注意
(`.gitattributes`に`* text=auto`などを入れておくと安全)。

## Slurmクラスタ(GPU実験結果をノート化する場合)

ログインノードでエージェントを直接動かさず、`srun`で計算ノード上のApptainer
コンテナに乗せて動かす構成。詳しくは[`slurm/README.md`](./slurm/README.md)。

まだプレースホルダーの状態(パーティション名など要調整)。「大枠」としてまず形にした
段階で、実際のクラスタに合わせて詰めていく。

## 既知の未決事項

- 日常の起動方法(Windows側: WezTerm統合 vs 素のPowerShell)
- obsidian-skills以外に必要なagent向け設定があるか
- Vaultの構造(フォルダ分け、テンプレートなど)
- Slurm側の詳細(Slurm/README.mdの「要調整・後回しにしている点」参照)
- Windows側とSlurm側、両方から同時にVaultへpushした場合のコンフリクト対応
