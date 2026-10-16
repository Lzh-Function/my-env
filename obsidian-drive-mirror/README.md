# obsidian-drive-mirror

iPhone版Obsidianの**専用Vault**に、Google Drive上のVault（`LLM-Wiki`）の一方向・読み取り専用ミラーを作るプラグインと、
その配信元となるWSL上の読み取り専用Bridge。設計は [DESIGN.md](DESIGN.md)（§0 / §0.1 が最優先）。

```text
Google Drive
  └─(公式 Drive for desktop, Windows のドライブ文字)
      └─ WSL: ~/workspace/GDrive/<マイドライブ>/LLM-Wiki          … fstab で永続マウント
          └─ /srv/drivemirror/vault  (read-only bind mount)       … Bridge のルート
              └─ Bridge (systemd user service, 127.0.0.1:8787, GET/HEAD のみ)
                  └─ Windows: tailscale serve (HTTPS :8443, tailnet 内のみ)
                      └─ iPhone: Tailscale → Obsidian "Drive Mirror" → 専用Vault
```

- 自作コードは Google OAuth / Drive API を一切使わない。Google との同期は公式 Drive for desktop だけが行う。
- iPhone 側の編集・新規作成・削除・リネームは、同期のたびに正本の状態へ戻る（iPhone からは何もアップロードしない）。
- ホスト PC が止まっている間は更新できない。iPhone は最後に同期した内容をオフラインで読める。

---

## 目次

1. [個人用PCでの初回セットアップ](#1-個人用pcでの初回セットアップ)
2. [iPhone のセットアップ](#2-iphone-のセットアップ)
3. [日常の運用](#3-日常の運用)
4. [更新](#4-更新)
5. [トラブルシューティング](#5-トラブルシューティング)
6. [保守作業（トークン再発行・ホスト移行・撤去）](#6-保守作業)
7. [セキュリティ上の運用ルール](#7-セキュリティ上の運用ルール)
8. [開発](#8-開発)
9. [検証状況](#9-検証状況)

---

## 1. 個人用PCでの初回セットアップ

ホストは**自分専用の Windows 11 + WSL2 (Ubuntu)** PC を前提とする（Mac / Linux サーバーは不可。理由は DESIGN §0 / D-15）。
`<...>` は自分の環境の値に置き換える。

### チェックリスト

- [ ] 1.1 Windows: Drive for desktop・電源設定
- [ ] 1.2 Windows: WSL2 と常駐設定
- [ ] 1.3 WSL: Node・リポジトリ・ビルド
- [ ] 1.4 WSL: Drive のマウントを永続化
- [ ] 1.5 WSL: 読み取り専用ビュー
- [ ] 1.6 WSL: Bridge の初期化（トークン発行）
- [ ] 1.7 WSL: Bridge のサービス化
- [ ] 1.8 Windows: Tailscale と Serve
- [ ] 1.9 Tailscale 管理画面: HTTPS・アクセス制限
- [ ] 1.10 疎通確認

### 1.1 Windows: Drive for desktop・電源設定

1. [Google Drive for desktop](https://www.google.com/drive/download/) をインストールし、**LLM-Wiki を持つ Google アカウント**でログイン。
2. 設定 → 「起動時に Google ドライブを起動」を ON。ストリーミング（既定）のままで良い（初回の Bridge 走査で全ファイルが取得される）。
3. エクスプローラーで Drive のドライブ文字（既定 `G:`）と、ルートフォルダ名（日本語表示なら `マイドライブ`、英語なら `My Drive`）を確認。
   以下 `<D>` = ドライブ文字（例 `G`）、`<MyDrive>` = ルートフォルダ名。
4. 電源設定でスリープを無効にする（スリープ中は同期不可）。
5. Windows Update 等で再起動した後は **Windows へのサインインが必要**（Drive for desktop はサインイン後に動くため）。

### 1.2 Windows: WSL2 と常駐設定

1. WSL2 + Ubuntu を導入（`wsl --install -d Ubuntu`）。ディストリ名は `wsl -l -v` で確認（以下 `<Distro>`）。
2. WSL 内で systemd を有効化（無ければ追記し、PowerShell で `wsl --shutdown` 後に再起動）:
   ```ini
   # /etc/wsl.conf
   [boot]
   systemd=true
   ```
3. ネットワークは既定（NAT + localhost forwarding）で良い。`%UserProfile%\.wslconfig` で `localhostForwarding=false` にしていないこと。
4. **WSL を常駐させる。** WSL は対話セッションが無いと停止し、Bridge も止まる。ログオン時に WSL を起動しっぱなしにするタスクを登録（PowerShell）:
   ```powershell
   $a = New-ScheduledTaskAction -Execute "$env:WINDIR\System32\conhost.exe" -Argument "--headless wsl.exe -d <Distro> --exec sleep infinity"
   $t = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
   $s = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
   Register-ScheduledTask -TaskName "WSL keepalive (drive-mirror)" -Action $a -Trigger $t -Settings $s
   ```
   一度サインアウト→サインインし、`wsl -l -v` で `<Distro>` が `Running` のままであることを確認。
   （**未検証**: 実機で確認したら §9 を更新すること）

### 1.3 WSL: Node・リポジトリ・ビルド

```bash
node --version   # v20 以上。無ければ NodeSource 等で導入（apt の古い nodejs は不可）
git --version

mkdir -p ~/workspace && cd ~/workspace
git clone git@github.com:Lzh-Function/my-env.git
cd my-env/obsidian-drive-mirror
npm ci
npm run build
```

`node_modules` やリポジトリを `/mnt/c` や Drive 上に置かないこと（WSL の ext4 上に置く）。

### 1.4 WSL: Drive のマウントを永続化

Drive のドライブ文字は WSL 起動時に自動マウントされないことがあるため、fstab に定義する（手動 `mount` は WSL 再起動で消える。
`install-ro-mount.sh` は手動マウントを検出すると停止する）。

```bash
mkdir -p ~/workspace/GDrive
echo '<D>:  /home/<user>/workspace/GDrive  drvfs  defaults,uid=1000,gid=1000,nofail,x-systemd.automount  0 0' | sudo tee -a /etc/fstab
sudo systemctl daemon-reload
sudo mount -a
ls ~/workspace/GDrive/<MyDrive>/LLM-Wiki/.obsidian   # 見えれば OK
```

`x-systemd.automount` は、WSL 起動時に Drive がまだ準備できていなくても初回アクセス時にマウントさせるため。

### 1.5 WSL: 読み取り専用ビュー

Bridge がバグっても Drive 側を変更できないよう、LLM-Wiki を read-only bind mount で `/srv/drivemirror/vault` に見せる（DESIGN D-15）。

```bash
SRC="$HOME/workspace/GDrive/<MyDrive>/LLM-Wiki" scripts/install-ro-mount.sh
```

最後に `OK: /srv/drivemirror/vault is a read-only bind mount.` と出れば成功。
Bridge はルートが書き込み可能だとスナップショットを返さない（`requireReadOnlyRoot`）ので、必ずこのビューをルートにする。

### 1.6 WSL: Bridge の初期化（トークン発行）

1. 自分の Tailscale ログイン名を確認する（1.8 の後でも良い）: Tailscale 管理画面の Users、または Windows で
   `tailscale whois <iPhoneのTailscale IP>` の `LoginName`。
2. **自分の普段のターミナルで**実行する（トークンが表示されるので、Claude Code の `!` やチャットには通さない）:
   ```bash
   cd ~/workspace/my-env/obsidian-drive-mirror
   node dist/bridge/cli.mjs init --root /srv/drivemirror/vault --name LLM-Wiki --login <tailscale-login>
   ```
3. 表示された **Bridge token** をパスワードマネージャーに保存（再表示不可。失くしたら §6 で再発行）。
4. 走査できるか確認（初回は Drive からの取得とハッシュ計算で数十秒〜）:
   ```bash
   node dist/bridge/cli.mjs check
   # complete: true / files: ... / excluded: {"hidden":..,"unsupported_name":..}
   ```
   `complete: false` の場合は §5 を参照。

設定は `~/.config/drive-mirror-bridge/config.json`（mode 600、トークンは SHA-256 のみ保存）、ハッシュキャッシュは
`~/.local/state/drive-mirror-bridge/`。どちらも Vault の外。

### 1.7 WSL: Bridge のサービス化

```bash
scripts/install-bridge-service.sh
```

`~/.config/systemd/user/drive-mirror-bridge.service` を作成・起動し、`loginctl enable-linger` で WSL 起動時に自動起動させる。

```bash
systemctl --user status drive-mirror-bridge
journalctl --user -u drive-mirror-bridge -f      # ログ（トークン・パス・本文は出力しない）
curl -s http://127.0.0.1:8787/v1/health          # {"ok":true,...}
```

### 1.8 Windows: Tailscale と Serve

1. [Tailscale for Windows](https://tailscale.com/download/windows) をインストールしてログイン。
   設定で「Run unattended」を ON にしておくと、サインアウト中も tailnet に残る。
2. PowerShell で WSL の Bridge に Windows から届くか確認:
   ```powershell
   curl.exe http://127.0.0.1:8787/v1/health
   ```
3. Serve で tailnet 内に HTTPS 公開（**`tailscale funnel` は使わない**）:
   ```powershell
   tailscale serve --bg --https=8443 http://127.0.0.1:8787
   tailscale serve status        # https://<pc>.<tailnet>.ts.net:8443 が表示される
   ```
   `--bg` の設定は再起動後も保持される。

### 1.9 Tailscale 管理画面: HTTPS・アクセス制限

1. DNS 設定で **MagicDNS** と **HTTPS Certificates** を有効化（Serve の HTTPS に必須）。
2. アクセス制御（tailnet policy file）で、**自分のユーザーからこの PC の `tcp:8443` だけ**を許可する。例（PC にタグを付ける場合）:
   ```jsonc
   {
     "tagOwners": { "tag:drive-mirror-pc": ["autogroup:admin"] },
     "grants": [
       { "src": ["<tailscale-login>"], "dst": ["tag:drive-mirror-pc"], "ip": ["tcp:8443"] }
       // 既定の全許可 grant が残っていると制限にならない。他の端末に必要な通信は個別に許可し直すこと。
     ]
   }
   ```
   PC へのタグ付けは Windows で `tailscale up --advertise-tags=tag:drive-mirror-pc`（または管理画面の Machines → Edit ACL tags）。
3. Bridge 側でも、トークンに加えて Serve が付ける `Tailscale-User-Login` を `allowedTailscaleLogins` と照合している。

### 1.10 疎通確認

```bash
scripts/p0-check.sh     # マウント・読み取り専用・設定・スナップショット・サービス・loopback bind を確認
```

続けて iPhone で（Tailscale アプリ ON）Safari から `https://<pc>.<tailnet>.ts.net:8443/v1/health` を開き `{"ok":true,...}` を確認。
Tailscale を OFF にすると開けないことも確認する。

---

## 2. iPhone のセットアップ

0. **前提: 配布用 repo `Lzh-Function/drive-mirror` に Release があること。** 無ければ開発マシンで `npm run release:dist`
   （§4）。repo 直下に `manifest.json`、Release に `main.js` / `manifest.json` / `styles.css` が無いと BRAT はインストールできない。
   確認: `gh release list --repo Lzh-Function/drive-mirror`
1. **Tailscale** アプリを入れ、PC と同じ tailnet・同じユーザーでログイン。
2. **Obsidian** で新しい Vault を作成。保存場所は「この iPhone 内」、**iCloud は使わない**。Obsidian Sync も使わない。
   この Vault は**専用**（同期のたびに Bridge の内容で上書き・削除される。ここで書いたものは消える）。
3. コミュニティプラグインを有効化し、**BRAT** をインストール・有効化。
4. GitHub で **Fine-grained PAT** を発行: Repository access = `Lzh-Function/drive-mirror` のみ、Permissions = Contents: Read-only。
5. BRAT の設定に PAT を登録 → 「Add beta plugin」で `Lzh-Function/drive-mirror` を追加（最初はバージョン固定推奨）。
6. コミュニティプラグイン一覧で **Drive Mirror** を有効化。
7. Drive Mirror の設定:
   - Provider: **Self-hosted bridge**
   - Bridge URL: `https://<pc>.<tailnet>.ts.net:8443`
   - Bridge token: 1.6 のトークン（Obsidian の secret storage に保存され、Vault の `data.json` には入らない）
   - 「Test」→ `Bridge OK: root "LLM-Wiki"` を確認
8. 「Dry run」で計画（ダウンロード件数など）を確認 → 「Sync now」→ プレビューで Apply。
   初回は空の Vault が必須（それ以外は BLOCKED になる）。初回同期時にルートが固定（pin）される。
9. **他のプラグインは入れない**（§7）。

---

## 3. 日常の運用

- 同期は**手動**: iPhone の Tailscale を ON → Obsidian で リボンの 🔄 / コマンド「Drive Mirror: Sync now」。
- 既定では毎回プレビューが出る（設定「Preview before every sync」）。大量削除・正本が空・初回非空 Vault の場合は必ず確認が要る。
- 結果は通知と「Show diagnostics」（直近20回の件数・失敗・警告。本文やトークンは含まない）で確認。
- 状態の意味:

  | 状態 | 意味 |
  |---|---|
  | SUCCESS | 管理対象すべて一致。`Last complete sync` が更新される |
  | PARTIAL | 上限（既定 512 MiB）超のファイルをスキップした以外は一致 |
  | FAILED | 何かが失敗。**削除は実行されていない**。原因を直して再実行すれば回復 |
  | BLOCKED | 安全装置で停止（ルート変更・初回非空・未承認の大量削除） |
  | CANCELLED | 取消。削除は実行されていない |

- `complete=true` は「PC 上のフォルダが2回の走査で安定していた」ことの確認であり、Drive for desktop が Google と同期し終えた証明ではない。
  PC で編集した直後などは、Drive for desktop の同期完了を待ってから iPhone で同期する。
- iPhone で編集したノートは次の同期で正本に戻る（仕様）。メモは別アプリか正本側で取る。
- `:` など Windows で使えない文字を含む名前（例 `remote-capture:xxxx`）はミラー対象外（診断の excluded `unsupported_name`）。

---

## 4. 更新

### Bridge（ホスト PC）

```bash
cd ~/workspace/my-env && git pull
cd obsidian-drive-mirror && npm ci && npm run build
systemctl --user restart drive-mirror-bridge
scripts/p0-check.sh
```

### プラグイン（開発マシンでリリース → iPhone で更新）

1. `manifest.json` と `package.json` の `version` を上げ、`versions.json` に `"<version>": "<minAppVersion>"` を追加してコミット。
2. `npm run release:dist`
   （lint・型・テスト・ビルド後、`Lzh-Function/drive-mirror` に manifest を push し GitHub Release を作成。自分の `gh` 認証を使う）
3. iPhone の BRAT で更新を確認・適用し、Obsidian を再起動。

---

## 5. トラブルシューティング

| 症状（iPhone の通知 / 診断） | 確認・対処 |
|---|---|
| `Cannot reach bridge` | iPhone の Tailscale が OFF / PC がスリープ・停止 / WSL 停止（1.2-4）/ サービス停止（`systemctl --user status drive-mirror-bridge`）/ `tailscale serve status` |
| HTTP 401 | トークン不一致。§6 で再発行して iPhone に入れ直す |
| HTTP 403 `tailscale_identity_not_allowed` | `config.json` の `allowedTailscaleLogins` に自分のログイン名が無い（修正してサービス再起動）。Serve を経由していないアクセスも 403 |
| HTTP 429 | 認証失敗が1分に20回を超えた。1分待つ。原因（古いトークン等）を直す |
| `incomplete`（503） | PC で `node dist/bridge/cli.mjs check` を実行し problems を見る ↓ |
| 　`marker .obsidian not found` | Drive for desktop 未起動・未サインイン、または マウント消失（`findmnt ~/workspace/GDrive`、`systemctl status srv-drivemirror-vault.mount`） |
| 　`root is writable` | ルートが `/srv/drivemirror/vault` になっていない、または read-only ビューが外れている（1.5 を再実行） |
| 　`tree changed between stability scans` | Drive が同期中。しばらく待って再実行 |
| 　`temporary file present` | Office の `~$*` 等が残っている。PC 側でファイルを閉じる |
| 　`name collision` / `invalid name` | 大文字小文字・Unicode 正規化だけが違う名前、制御文字など。正本側で名前を直す |
| 　`unreadable` | Drive からの取得失敗（オフライン等）。ネット接続と Drive for desktop を確認 |
| `Remote changed during sync`（409） | 同期中に正本が変わった。再実行 |
| BLOCKED `root_changed` | Bridge を `init` し直した等でルート ID が変わった。正しい Bridge か確認し、設定の「Re-pin」→ Dry run → Sync |
| BLOCKED `first_sync_nonempty` | 初回は空の専用 Vault を使う（既存 Vault に入れない） |
| WSL 再起動後に全部止まる | 1.4（fstab）・1.2-4（常駐タスク）・`loginctl show-user $USER -p Linger`（yes であること） |
| Windows から `curl 127.0.0.1:8787` が失敗 | WSL の localhost forwarding（`.wslconfig`）、サービス起動状態 |
| 同期後、iPhone のファイル一覧に反映されない | Obsidian を再起動（**未検証事項**。発生したら記録して報告） |

---

## 6. 保守作業

### トークン再発行（漏洩・紛失時）

```bash
node dist/bridge/cli.mjs rotate-token        # 自分のターミナルで。新トークンが表示される
systemctl --user restart drive-mirror-bridge
```

iPhone の設定で新トークンを入れ直す。iPhone を紛失した場合は、トークン再発行に加え Tailscale 管理画面でその端末を削除する。

### ホスト PC の移行

1. 新 PC で §1 を 1.1〜1.5、1.7〜1.10 の順に実施（1.6 の `init` は**しない**）。
2. 旧 PC の `~/.config/drive-mirror-bridge/config.json` を新 PC の同じ場所へコピー（`chmod 600`）。
   `rootId` とトークンが引き継がれるので iPhone 側の再設定はほぼ不要（`root` パスが同じ `/srv/drivemirror/vault` であること）。
3. Bridge URL（`<pc>.<tailnet>.ts.net`）が変わる場合は iPhone の設定を更新。旧 PC で `tailscale serve --https=8443 off`。
4. `init` をやり直した場合は `rootId` が変わり iPhone は BLOCKED `root_changed` になる → 「Re-pin」。

### 撤去

```bash
systemctl --user disable --now drive-mirror-bridge && rm ~/.config/systemd/user/drive-mirror-bridge.service
sudo systemctl disable --now srv-drivemirror-vault.mount && sudo rm /etc/systemd/system/srv-drivemirror-vault.mount && sudo systemctl daemon-reload
rm -rf ~/.config/drive-mirror-bridge ~/.local/state/drive-mirror-bridge
```

Windows: `tailscale serve --https=8443 off`、タスク「WSL keepalive (drive-mirror)」を削除。iPhone: GitHub の PAT を失効。

---

## 7. セキュリティ上の運用ルール

- iPhone の専用 Vault には **BRAT と Drive Mirror 以外のプラグインを入れない**。特にノート内のコードを実行するもの
  （Dataview JS、Templater、CustomJS 等）は禁止。LLM-Wiki はエージェントも書き込むため、その内容が iPhone 上のコードになり得る。
- tailnet のアクセス制御で、iPhone（自分のユーザー）→ PC の `tcp:8443` 以外を許可しない。`tailscale funnel` は使わない。
- トークンをチャット・Issue・リポジトリ・スクリーンショットに載せない。疑わしければ §6 で再発行。
- ホスト PC は自分専用であること（他人に管理者権限があるマシンでは Vault の全文が読める）。
- iOS のデバイスバックアップに Vault が含まれ得る。LLM-Wiki の内容に照らして許容できるか判断する。
- my-env は public リポジトリ。`config.json`・トークン・`data.json`・ノートをコミットしない（`.gitignore` 済み）。

---

## 8. 開発

| パス | 内容 |
|---|---|
| `src/` | Obsidian プラグイン（iOS 対応のため Node/Electron 不使用）。`mirror/` エンジン・計画・走査、`provider/` Bridge/Mock、`security/` パス規則、`ui/` |
| `bridge/src/` | 読み取り専用 HTTP サーバー + CLI（`init` / `check` / `serve` / `rotate-token`）。`safeOpen.ts` が TOCTOU 対策 |
| `tests/` | `unit/`（インメモリ FS でエンジン）、`bridge/`（一時ディレクトリで実サーバー）、`integration/`（エンジン ↔ Bridge）、`compliance` |
| `scripts/` | `install-ro-mount.sh`、`install-bridge-service.sh`、`p0-check.sh`、`copy-to-test-vault.sh`、`release-dist.sh` |
| `dist-README.md` | 配布用 repo に置く README |

```bash
npm ci
npm run lint && npm run typecheck && npm test && npm run build
TEST_VAULT=/mnt/c/Users/<WindowsUser>/Documents/DriveMirrorTest scripts/copy-to-test-vault.sh
```

- Windows 版 Obsidian のテスト Vault では、設定の Provider を **Mock** にすると Bridge なしで動作確認できる。
- テスト Vault・テストデータに実データを使わない。テスト Vault を Drive 上に置かない（スクリプトが拒否する）。
- 規約: [AGENTS.md](AGENTS.md)。

---

## 9. 検証状況

| 項目 | 状態 |
|---|---|
| P1–P5（プラグイン、Mock、パス検証、差分計画 + Dry run、分割 DL・検証、削除の安全装置） | 実装済み。Node 上の単体・結合テスト 66 件 |
| Bridge `check`（研究室 PC の実 LLM-Wiki、2026-10-16） | complete。717 ファイル / 197 MiB、初回 29 秒・キャッシュ後 13 秒 |
| read-only bind mount（研究室 PC） | 動作確認済み（書き込みは EROFS） |
| 個人用 PC での §1 一式（fstab、WSL 常駐タスク、サービス、Tailscale Serve） | **未実施** |
| Windows 版 Obsidian での動作（P6） | **未実施** |
| iOS 実機（P7）: `requestUrl` の Range/206、`appendBinary`/`rename`、一覧への反映、secret storage | **未実施** — iOS で動くとはまだ言えない |
