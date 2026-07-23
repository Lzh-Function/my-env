<#
=============================================================================
 Obsidian + Claude Code + Codex セットアップ (Windows ネイティブ, PowerShell)

 Vaultは別のprivateリポジトリ(obsidian-vault)。Windows側に直接cloneし、Obsidianは
 そこを直接開く。WSL側からは /mnt/c/ 経由で読み書きする想定(このスクリプトの対象外)。

 Claude Code / Codex はここでは wsl-wezterm-zellij 側の zj(WSLネイティブ)とは完全に
 別に、Windowsネイティブでインストールする。理由: Obsidian公式CLIがWindowsネイティブの
 実行ファイル("Obsidian.com terminal redirector")として登録される方式のため、WSL側の
 エージェントから確実に届く保証がない。Windows側で完結させることでこれを回避する。
 (WSL側で既にclaude/codexにログイン済みでも、これは別インストール・別ログインになる)

 実行方法(PowerShell を通常権限で開いて):
     Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
     .\setup_obsidian.ps1

 前提:
   - winget が使えること
   - Vault用のリポジトリをGitHubに作成済みであること(private)。無ければ先に:
       gh repo create Lzh-Function/obsidian-vault --private
     (このスクリプトはリポジトリの作成そのものは行わない)
   - GitHubへのSSHアクセスができること(wsl-wezterm-zellij側のREADME参照)
=============================================================================
#>

$ErrorActionPreference = 'Stop'
function Info($m) { Write-Host "==> $m" -ForegroundColor Cyan }
function Warn($m) { Write-Host "[warn] $m" -ForegroundColor Yellow }

$VaultRepo  = 'git@github.com:Lzh-Function/obsidian-vault.git'
$VaultDir   = "$env:USERPROFILE\ObsidianVault"
$SkillsRepo = 'https://github.com/kepano/obsidian-skills'

# --- 1. winget で Obsidian・Node.js・Git を導入 -----------------------------
Info 'winget でインストール(Obsidian / Node.js / Git)'
$pkgs = @('Obsidian.Obsidian', 'OpenJS.NodeJS', 'Git.Git')
foreach ($p in $pkgs) {
    Info "  -> $p"
    winget install -e --id $p --accept-source-agreements --accept-package-agreements --silent
}

# winget で入れた実行ファイルを今のセッションの PATH に反映
$env:Path = [System.Environment]::GetEnvironmentVariable('Path','Machine') + ';' +
            [System.Environment]::GetEnvironmentVariable('Path','User')

# --- 2. Claude Code(Windowsネイティブ版)-------------------------------------
if (-not (Get-Command claude -ErrorAction SilentlyContinue)) {
    Info 'Claude Code をインストール(ネイティブ版)'
    irm https://claude.ai/install.ps1 | iex
    $env:Path = [System.Environment]::GetEnvironmentVariable('Path','Machine') + ';' +
                [System.Environment]::GetEnvironmentVariable('Path','User')
}

# --- 3. Codex CLI(npm経由)---------------------------------------------------
if (-not (Get-Command codex -ErrorAction SilentlyContinue)) {
    Info 'Codex CLI をインストール'
    npm install -g @openai/codex
}

# --- 4. Vaultリポジトリを clone ----------------------------------------------
if (-not (Test-Path $VaultDir)) {
    Info "Vaultリポジトリを clone: $VaultRepo -> $VaultDir"
    git clone $VaultRepo $VaultDir
} else {
    Warn "$VaultDir は既に存在するので clone をスキップ"
}

# --- 5. obsidian-skills を導入 -----------------------------------------------
# npx skills が Claude Code / Codex の存在を自動検出し、Claude Code には
# Vault直下の .claude/skills/(プロジェクトスコープ)、Codexには ~/.codex/skills/
# (グローバルスコープ)へそれぞれ配置する。そのためVaultディレクトリ内で実行する。
Info 'obsidian-skills を導入(Claude Code / Codex 両方を自動検出)'
Push-Location $VaultDir
npx skills add $SkillsRepo --all -y
Pop-Location

# --- 完了 ---------------------------------------------------------------------
Write-Host ""
Info 'セットアップ完了。ただし以下は手動での操作が必要です:'
@"

  1. Obsidianを起動し、このVaultを開く:
       $VaultDir

  2. Obsidianの設定 → General → 「Command line interface」を有効化
     (Obsidian公式CLIを使うのに必須。ここだけは自動化できません)

  3. Claude Code / Codex にそれぞれ初回ログイン(WSL側とは別のログインです):
       claude
       codex

  以降は $VaultDir に cd してから claude / codex を起動してください。
  (obsidian-skillsはVault直下の .claude/ にプロジェクトスコープで入っているため)

"@ | Write-Host
