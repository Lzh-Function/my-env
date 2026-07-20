<#
=============================================================================
 Windows 側セットアップ (PowerShell)
 WezTerm + Nerd Font + SumatraPDF + chezmoi を入れ、my-env リポジトリを
 clone して source dir を wsl-wezterm-zellij に固定し、wezterm 設定を適用する。

 実行方法(PowerShell を通常権限で開いて):
     Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
     .\setup-windows.ps1

 前提:
   - winget が使えること(Windows 10 1809+ / 11 なら標準)
   - GitHub に SSH でアクセスできること(鍵登録済み)。未登録なら下記メモ参照。
=============================================================================
#>

$ErrorActionPreference = 'Stop'
function Info($m) { Write-Host "==> $m" -ForegroundColor Cyan }
function Warn($m) { Write-Host "[warn] $m" -ForegroundColor Yellow }

$RepoUrl   = 'git@github.com:Lzh-Function/my-env.git'
$SourceSub = 'wsl-wezterm-zellij'   # chezmoi の source root にするサブディレクトリ

# --- 1. winget で各種インストール ------------------------------------------
Info 'winget でインストール(WezTerm / JetBrainsMono Nerd Font / SumatraPDF / chezmoi / Git)'
$pkgs = @(
    'wez.wezterm',
    'DEVCOM.JetBrainsMonoNerdFont',
    'SumatraPDF.SumatraPDF',
    'twpayne.chezmoi',
    'Git.Git'
)
foreach ($p in $pkgs) {
    Info "  -> $p"
    winget install -e --id $p --accept-source-agreements --accept-package-agreements --silent
}

# winget で入れた実行ファイルを今のセッションの PATH に反映
$env:Path = [System.Environment]::GetEnvironmentVariable('Path','Machine') + ';' +
            [System.Environment]::GetEnvironmentVariable('Path','User')

# chezmoi のパス解決(PATH に出ていない場合のフォールバック)
# Windows PowerShell 5.1(?. 非対応)でも動くよう、null条件演算子は使わない
$chezmoiCmd = Get-Command chezmoi -ErrorAction SilentlyContinue
$chezmoi = if ($chezmoiCmd) { $chezmoiCmd.Source } else { $null }
if (-not $chezmoi) { $chezmoi = "$env:LOCALAPPDATA\Microsoft\WinGet\Links\chezmoi.exe" }
if (-not (Test-Path $chezmoi)) { throw "chezmoi が見つかりません。新しい PowerShell を開いて再実行してください。" }

# --- 2. my-env を clone(まず clone のみ。apply はしない)------------------
Info "my-env を clone ($RepoUrl)"
& $chezmoi init $RepoUrl

# --- 3. source dir を wsl-wezterm-zellij に固定 ----------------------------
Info 'chezmoi 設定 (sourceDir をサブディレクトリに固定)'
$cfgDir = "$env:USERPROFILE\.config\chezmoi"
New-Item -ItemType Directory -Force -Path $cfgDir | Out-Null
$srcPath = "$env:USERPROFILE/.local/share/chezmoi/$SourceSub"
@"
sourceDir = "$srcPath"
"@ | Set-Content -Path "$cfgDir\chezmoi.toml" -Encoding utf8

# 念のため source-path を確認表示
$resolved = & $chezmoi source-path
Info "source-path = $resolved"

# --- 4. wezterm 設定のみ apply ---------------------------------------------
# .chezmoiignore 側で「Windows では wezterm 以外を無視」する設定になっている前提。
Info 'chezmoi apply(Windows では wezterm 設定のみ展開される)'
& $chezmoi apply

# --- 5. WEZTERM_CONFIG_FILE を WSL 上の単一ソースへ向ける(任意) -----------
# dot_wezterm.lua を chezmoi が Windows home に ~/.wezterm.lua として展開する構成なら
# この手順は不要。もし「WSL 上の1ファイルを直接読ませたい」運用なら下を有効化する。
#
# $wslUser = 'function'          # WSL のユーザー名に置換
# $distro  = 'Ubuntu'           # wsl -l -v の NAME
# $cfgFile = "\\wsl.localhost\$distro\home\$wslUser\.local\share\chezmoi\$SourceSub\wezterm.lua"
# [System.Environment]::SetEnvironmentVariable('WEZTERM_CONFIG_FILE', $cfgFile, 'User')
# Info "WEZTERM_CONFIG_FILE = $cfgFile"

# --- 完了 -------------------------------------------------------------------
Write-Host ""
Info '完了'
@"
  次の手順:
    - フォント反映のため WezTerm を一度終了して起動し直す
    - ~/.wezterm.lua が配置されているか確認: notepad "$env:USERPROFILE\.wezterm.lua"
    - default_domain が効かない場合は wezterm.lua 内を default_prog フルパス版に切替

  SSH 未設定でこのスクリプトが clone で失敗した場合:
    1) WSL 側で ssh-keygen -t ed25519 → ~/.ssh/id_ed25519.pub を GitHub に登録
    2) Windows でも使うなら同じ鍵を使うか、GitHub CLI (gh auth login) で認証
"@ | Write-Host
