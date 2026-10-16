# Drive Mirror for Obsidian — 技術設計書

- **Version:** 1.2-compliance-first（v1.1 + §0.1 運用決定）
- **Date:** 2026-10-16
- **Status:** Implementation draft / default transport is Drive for desktop → self-hosted read-only bridge (NO Google API/OAuth in custom code)
- **Target:** iOS版Obsidian（開発・診断はWindows 11 + WSL2 Ubuntu）
- **Distribution:** ソースは`my-env/obsidian-drive-mirror/`（public）。BRAT配布は別のprivate repo `Lzh-Function/drive-mirror`へRelease（§0.1 D-1）
- **Project working name:** `drive-mirror`（manifest IDも`drive-mirror`）

> **この文書の目的**：個人用のiPhone版Obsidianプラグインを開発するエージェントに渡す仕様書。Google Drive内の既存Vaultを唯一の正本として、iPhone側の専用Vaultに一方向の閲覧用ミラーを作る。ローカル編集・削除・追加は、同期成功時にGoogle Drive側の状態で破棄／復元／削除する。

---

## 0. 規約コンプライアンス優先の最上位決定（ADR-000 / 2026-10-16）

> **本節は後続のGoogle API直接接続・OAuth Gatewayの記述より優先する。v1の実装では、自作プログラムによるGoogle OAuth / Google Drive API呼び出しを一切行わない。** 後続のA/B方式は将来検討用の設計資料であり、エージェントは明示的な再承認なしに実装してはならない。

**採用方式C: Drive for desktop + Tailscale + 読み取り専用ローカルブリッジ**

```text
Google Drive
     │ 公式 Google Drive for desktop (Windows)
     ▼
Windows H: (Drive for desktop / ストリーミング)
     │ WSLから ~/workspace/GDrive (drvfs) でローカルファイルとして読み取り
     ▼
WSL Read-Only Bridge  ── Tailscaleのみ ──► iPhone Obsidian Drive Mirror Plugin
GET /v1/manifest                        GET /v1/file/<opaque-id>
                                               │
                                               ▼
                                         iPhone専用Vault
```

- **Google Developer OAuth client、API key、Google refresh tokenは自作プログラムには存在しない。** Drive for desktopの公式同期機能だけを利用する。自作プラグインからGoogleの非公開API・Cookie・既存公式クライアント認証情報を流用しない。
- Bridgeは指定されたローカルディレクトリ配下だけを**読み取り**、ファイルの生成・更新・削除やGoogle Drive API呼び出しをしない。Windows/WSLのファイル権限も可能な範囲で読み取り専用にする。
- Bridge APIは`GET /v1/manifest`, `GET /v1/file/{opaque-id}`, `GET /v1/health`等に絞り、Drive側に更新を及ぼす経路を作らない。
- 接続はTailscale tailnetで限定し、ACL/grantsでiPhone端末だけに許可。認証を追加し、OSレベルの転送暗号化（Tailscale）を用いる。可能ならTailscale ServeのHTTPSも利用する。パブリックインターネットへAPIポートを公開しない。
- Bridgeは`../`、シンボリックリンク、ジャンクション、パス正規化、ルートディレクトリ脱出を拒否する。ファイル要求はmanifest由来の不透明IDを使い、任意パスをURLパラメータに受け取らない。
- Google Drive for desktopが未起動、フォルダ未認識、列挙不完全、オンライン専用ファイルにアクセス不能、またはDriveの同期完了を確認できないときは`manifest`を**完全スナップショットとして返さない**。iPhone側で破壊的削除を禁止する。
- iPhone内の編集・新規・削除・リネームは、完全で検証済みの同期時に正本へ収束させる。`.obsidian/`は保護する。
- PC停止中は更新できず、iPhoneは最後に取得したコピーをオフライン閲覧できる。Driveのストリーミング方式ではPC稼働中でもネット接続・オンデマンド取得が必要になる。
- 外部で使う場合、Tailscale接続やWindows側のWSLポート到達性を先に実機検証する。WindowsホストとWSLのネットワーク構成に応じてWindows側のTailscale ServeやWSLへの中継を設定する。固定グローバルIPは不要。

**変更前のA/B方式が保留となった理由：** Google OAuth 2.0ポリシーはネイティブiOSアプリにWeb application型クライアントを流用することを認めず、`drive.readonly`はRestricted scope。個人利用はOAuth検証の例外になり得るが、セキュリティ・適切なOAuthクライアント型・ユーザーデータポリシーの義務を免除されない。Cloudflare Workers等の第三者サーバー経由の設計はRestricted scopeデータのサーバー送信・保存に関連する審査・セキュリティ要件の判断が必要なため、v1の既定方式にしない。

**本決定の根拠（Google公式）：**
- https://developers.google.com/identity/protocols/oauth2/policies
- https://support.google.com/cloud/answer/13464323
- https://developers.google.com/workspace/drive/api/guides/api-specific-auth
- https://developers.google.com/workspace/drive/api/terms
- https://support.google.com/drive/answer/13401938


## 0.1 v1.2 運用決定（2026-10-16 / 利用者確認済み）

本節は v1.1 本文中の対応記述より優先する。

| ID | 決定 | 影響する節 |
|---|---|---|
| D-1 | **リポジトリ:** ソース・テスト・Bridgeは`my-env/obsidian-drive-mirror/`（public）に置く。BRAT配布専用のprivate repo `Lzh-Function/drive-mirror`には`manifest.json`/`README.md`とRelease assetsのみをpushする。リリースはWSLの`npm run release:dist`（利用者の`gh`認証）で行い、my-envのActionsにはPATを置かない。CIはmy-env側で`lint/typecheck/test/build`のみ。 | §4, §9, §11.3, §11.4 |
| D-2 | **正本Vault:** `マイドライブ/LLM-Wiki`のみ。WSL上のパスは`~/workspace/GDrive/マイドライブ/LLM-Wiki`（H:をsystemd drvfs mountで`~/workspace/GDrive`に接続）。`/mnt/g`は使わない。Bridgeのルートは設定ファイルで絶対パス固定。 | §0, §5 |
| D-3 | **Drive for desktopのストリーミングモードを許容。** Bridgeの読み取りがオンデマンド取得を誘発しうる。全件再ハッシュを避けるため、Bridgeは`(relpath, size, mtimeMs)`をキーとするSHA-256キャッシュを持つ（キャッシュは正本外、Bridge状態ディレクトリに保存）。iPhone側の厳密ハッシュ検証は不変。 | §5, §7.3 |
| D-4 | **完全性判定:** Bridgeは間隔をあけた2回の走査が（パス・サイズ・mtime）で完全一致し、読み取り不能ファイル・Drive一時ファイル（`~$*`, `*.tmp`, `.~lock*`等）が無い場合のみ`complete=true`を返す。これは「Google側と同期済み」の証明ではない旨をUIに表示する。 | §5, §8 |
| D-5 | **大容量:** 20 MiB超も**v1で分割ダウンロード対応**。Bridgeは`GET /v1/file/{id}`で`Range: bytes=`を受け付け（206）、プラグインはチャンク（既定4 MiB）ごとにステージングへ追記し、全体SHA-256検証後に反映する。ファイル上限は設定値（既定 512 MiB）とし、超過分のみ`SKIPPED_OVERSIZE`/`PARTIAL`。 | §5, §7.4 |
| D-6 | **経路:** Windows側Tailscaleの`tailscale serve`（HTTPS, `*.ts.net`）→ WSLの`127.0.0.1:<port>`（WSL localhost forwarding）。BridgeはWSLの`127.0.0.1`のみにbindし、0.0.0.0にはbindしない。 | §0, §14-2 |
| D-7 | **認証:** ランダムな256-bit Bearerトークン（Bridge側はSHA-256ハッシュのみ保持、プラグインは`data.json`）＋ Tailscale Serveが付与する`Tailscale-User-Login`を許可リストと照合。加えてTailscale ACL/grantsでiPhone→PCのServeのみ許可。ヘッダー欠落時は拒否（開発用に設定で無効化可）。 | §0, §9 |
| D-8 | **ルート識別:** 方式Cでは「Drive root folder ID」は存在しない。設定・状態の`rootFolderId`は**Bridgeが返す`rootIdentity`**（Bridge設定の`rootId`ランダム値＋ルート名）で置き換える。初回同期で固定し、変化したら同期停止・再確認。 | §6, §7.1, §8 |
| D-9 | **opaque ID:** スナップショットごとにランダム生成し、Bridgeがメモリ上で`snapshotId→{id→path,size,mtime,sha256}`を保持（直近4件）。古い`snapshotId`は`409 snapshot_expired`、読み出し時にsize/mtime不一致なら`409 changed`。 | §5 |
| D-10 | **エラー処理:** §7.4の「401はtoken refresh」「invalid_grant」は方式Cに該当しない。401/403はBridge認証失敗として同期中断・通知、409は再計画、429/5xx/ネットワークは指数バックオフ（上限・jitter付き）。 | §7.4 |
| D-11 | **内部領域:** ステージング・ジャーナル・状態は`<configDir>/plugins/drive-mirror/`配下（`staging/`, `state.json`）。Bridgeトークンは`data.json`ではなくObsidianの`app.secretStorage`（端末ローカル、Vault外、API 1.11.4+）に保存し、`data.json`には非秘密の設定のみ。 | §4, §6 |
| D-12 | **Windowsテスト用Vault:** `C:\Users\TAKUH\Documents\DriveMirrorTest`（`scripts/copy-to-test-vault.sh`の既定、`TEST_VAULT`で上書き可）。 | §11.2 |
| D-14 | **Windows禁止文字を含む名前**（実データで`35_Remote_Captures/10_Registered/remote-capture:<hash>/`を確認）: Bridgeは`\\ : * ? " < > \|`を含むエントリを`unsupported_name`として除外・件数表示し、配下に降りない。制御文字・過長名・衝突は従来どおりsnapshot不完全扱い。 | §5, §6 |
| D-15 | **読み取り専用の強制と安全なopen:** Bridgeのルートは`scripts/install-ro-mount.sh`で作るread-only bind mount（`/srv/drivemirror/vault`、systemd mount unit、`Options=bind,ro`）とし、Bridgeはルートが書き込み可能なら`complete`を返さない（`requireReadOnlyRoot`、既定true）。ファイルは`O_RDONLY|O_NOFOLLOW|O_NONBLOCK`で開き、`/proc/self/fd`で実体パスが期待値と一致することと`fstat`が通常ファイルであることを確認してから、そのfdだけから読む（確認と読み取りの間のすり替え＝TOCTOUを排除）。 | §0, §5 |
| D-13 | **Google形式ファイル:** Drive for desktop上の`.gdoc`/`.gsheet`/`.gslides`等は対象外として件数表示。 | §3.3 |

---

## 1. エグゼクティブサマリー

- Google Drive上の指定**フォルダID**（Vault）を唯一の正本とする。
- iPhone側は **専用の使い捨てVault** とし、同期時に内容を強制的に収束させる。Driveへアップロードしない。
- **v1ではGoogle Drive APIを使わない。** Google公式Drive for desktopが同期したWindows上のVaultを、WSLの読み取り専用BridgeからiPhoneへ配信する。OAuth ClientとGoogle Tokenを自作コードに持たない。
- ローカルのファイルは必ず内容ハッシュを検証する。Drive側に更新がなくても、iPhone側の変更を検知して復元する。
- Drive側の削除・リネームはiPhoneに反映する。Driveにないローカルファイルは削除する。
- `.obsidian/`、プラグインの秘密情報・状態、内部ステージングは絶対にミラー／削除対象にしない。
- **P0の最優先検証事項はWSLから公式Drive for desktopのVaultを安全に読み取れること、およびTailscale経由でiPhoneからBridgeへ到達できること。** 直接Google OAuth方式は将来の独立した法令・規約適合性レビューが完了するまで保留。

### 1.1 実装上の不変条件（Must hold）

1. **Remote immutable:** アプリからGoogle Driveへの内容更新、名前変更、権限変更、ゴミ箱移動、削除を一切しない。Google Driveアクセス層はGET系のみ。
2. **Remote authoritative:** 正常同期後、管理対象のiPhone側ファイルはDriveの対応ファイルと内容一致する。
3. **Local changes disposable:** ローカル独自の編集・新規・リネームは同期成功時に破棄される。ローカルで削除したDriveファイルは再取得される。
4. **Failure non-destructive:** リモート列挙失敗、認証失敗、競合パス、検証不能、途中失敗時は削除フェーズへ進まない。
5. **Dedicated vault only:** 本番の既存ローカルVaultに無差別導入させない。初回同期前に空の専用Vaultであることを確認する。
6. **Internal isolation:** `.obsidian` と指定された内部ステージング・ログの内容には同期で触れない。
7. **Observable:** 実行件数、失敗ファイル、予定削除件数、最後に完全に成功した日時、警告をUIから確認できる。

## 2. 主要ユースケースと同期規則

| 状況 | 正常同期後の期待結果 |
|---|---|
| Driveに新規ファイル | iPhoneへダウンロード |
| Driveで内容変更 | iPhoneの対応ファイルを上書き |
| Driveでファイル削除 | iPhoneの対応ファイルを削除 |
| Driveでファイル移動・リネーム | iPhoneでは旧パスを削除し新パスに反映 |
| iPhoneで既存ファイル編集 | Drive版で強制上書き |
| iPhoneでファイル削除 | Driveから再ダウンロード |
| iPhoneで新規ファイル作成 | 削除（保護領域除く） |
| iPhoneでローカルの名前変更 | 変更後パスを削除しDrive側パスを復元 |
| iPhoneオフライン | 最後の成功同期済みデータを読む。同期はエラーで停止 |
| 途中失敗 | 可能な限り既存の正常なコピーを維持。次回同期で回復 |
| `.obsidian/` 変更 | その端末独自の設定として保持。Driveからは同期しない |

**厳密な対象範囲:** Vault内の通常のファイルとフォルダ。`.obsidian/`・隠しファイル・隠しフォルダ・プラグインが予約する名前は除外し、UIで対象外数を表示する。したがって「完全一致」はこの明示した**管理対象集合**に対する一致である。空ディレクトリはv1ではミラー不要とする。

## 3. アーキテクチャ

### 3.1 論理構成（v1採用 / C）

```text
[Google Drive: Source of truth]
          |
          v
[Official Google Drive for desktop on Windows]
          |
          v
[Windows G: vault] -- local read --> [WSL Read-only Bridge]
                                              |
                                              | Tailscale-secured read-only HTTPS/API
                                              v
                                  [iPhone: Drive Mirror plugin]
                                              |
                                              v
                                  [iPhone: dedicated local vault]
```

- Windowsでは**Google Drive for desktopだけがGoogle同期を担う**。Bridgeは正本へ変更を加えない。
- iPhone側のローカル編集は破棄、iPhoneローカル削除は再取得、Windows/Drive側削除はiPhoneに伝播。
- iPhoneはBridgeから完全なマニフェストが取得できない限り、削除フェーズを実行しない。
- iPhoneからBridgeへのアクセスはTailscale経由に限定する。

### 3.2 認証の重要な設計判断（ADR-001）

**背景:** Drive.readonlyはGoogleのRestricted scope。GoogleのOAuth 2.0ポリシーでは、ネイティブiOSアプリにはプラットフォームに適したOAuthクライアントを用いることを要求する。Obsidianプラグインは他社iOSアプリ内で動作するため、任意のiOS bundle IDやUniversal Linkを自前で登録できない。したがって「Web application型のクライアント＋公開静的コールバック＋obsidian://への転送」を当然に正規方式だと扱わない。

**将来の代替候補（B、v1では実装禁止）:** 自分で管理するHTTPSの小さな認証・読み取りゲートウェイ（例：Cloudflare Workers）を **Web application** として登録する。Web側でGoogle OAuth Authorization Code + PKCEを完了し、Google Refresh Tokenをサーバー側で安全に保管する。iPhoneプラグインは一度だけ端末ペアリングしてゲートウェイの専用APIに認証し、指定Driveフォルダ以下の**読み取りだけ**を行う。

```text
Safari --Google OAuth--> Your HTTPS OAuth gateway
                            |  refresh token (encrypted at rest)
                            v
                     Google Drive API (readonly)
                            |
iPhone plugin <--authenticated read-only API-- Gateway
```

ゲートウェイには以下の制約を適用する。
- `GET /v1/manifest` / `GET /v1/file/{opaque_id}` など**読み取りのみ**。外部公開の任意Google Drive API proxyを実装しない。
- Googleアカウントと対象root folder IDをサーバー設定に固定し、ファイルIDを管理対象ツリー内に照合する。
- Google Refresh TokenはWorkersの平文環境変数やGitHubに残さず、暗号化してDurableなストアに保持。暗号鍵はsecretとして管理し、OAuth資格情報の扱いはクラウド基盤の公式ドキュメントで検証する。
- iPhoneにはゲートウェイ接続資格情報だけを保存し、復旧・失効操作を用意する。通信はHTTPS。
- Pairingは一時的・使い捨てコード＋端末側のnonce＋短い有効期限。コードをURL経由で返してもGoogle refresh token自体は渡さない。
- ゲートウェイを利用すると転送内容がクラウド側を経由する。機密性の高い研究資料を使う場合は、この信頼境界を明示して代替案を検討する。

**将来の代替候補（A / 直接Drive API、v1では実装禁止）:** iPhoneプラグインからGoogle Drive APIに直接アクセスし、トークンを端末側に保存する。サーバーレスで、ユーザー体験・通信経路は優れる。一方、Obsidian iOS上でGoogleポリシーに合うOAuthクライアント/redirect URI方式が確立できることが採用条件。**個人用であってもWeb clientをネイティブクライアントへ無条件流用しない。** P0でGoogle公式仕様・実機動作を確認し、適合性を立証できた場合のみAへ切り替える。

**開発の選択:** v1ではCのみを実装する。コア同期エンジンは`RemoteReadProvider`インターフェースを使い、将来A/Bに切り替えても同じ同期エンジンを再利用可能にする。

**補足:** 個人利用のOAuthアプリはGoogleの検証例外になり得るが、Restricted scopeの利用条件・未検証アプリ警告・ユーザー上限には留意。External/Testingのrefresh tokenは通常7日で失効するため、継続運用では設定を確認する。

### 3.3 RemoteReadProvider

```ts
interface RemoteEntry {
  id: string;              // opaque provider ID（v1はBridgeが払い出すID）
  path: string;            // relative POSIX vault path
  mimeType: string;
  size: number | null;
  modifiedTime: string | null;
  version?: string;
  sha256Checksum?: string; // Google Drive reports it when available
  md5Checksum?: string;
}

interface RemoteReadProvider {
  verifyRoot(): Promise<{ rootId: string; name: string }>;
  listCompleteTree(): Promise<RemoteEntry[]>;
  download(entry: RemoteEntry): Promise<ArrayBuffer>;
  signOut(): Promise<void>;
}
```

注：Google Docs/Sheets等のGoogleネイティブファイルは通常の`alt=media`では取得できない。v1では対象外としてUI警告し、v2でPDF/Markdown等のエクスポート対応を追加する。Driveのショートカットもv1では対象外とし、明示的に件数表示する。

## 4. ファイルの配置

```text
[Source repository under WSL: ~/src/drive-mirror/]
  src/
    main.ts
    auth/             # local bridge session auth; no Google OAuth in v1
    provider/         # RemoteReadProvider, self-hosted Bridge client
    inventory/        # folder walk, normalization, collision detection
    mirror/           # scanner, diff planner, downloader, apply, local integrity
    ui/               # settings, status, sync preview, diagnostics
    security/         # path validation, protected paths
  tests/
    unit/
    integration/
    fixtures/
  bridge/              # WSL Node.js read-only server (separate runtime; no Obsidian API)
  scripts/
    copy-to-test-vault.sh
  .github/workflows/
    ci.yml
    release.yml
  manifest.json
  package.json
  package-lock.json
  tsconfig.json
  esbuild.config.mjs
  README.md
  AGENTS.md
  DESIGN.md

[iPhone dedicated vault]
  .obsidian/
    plugins/drive-mirror/
      main.js
      manifest.json
      data.json           # Bridge config / client credential (sensitive; NO Google token)
  Notes/
  Assets/
  ...                    # mirrored content
```

同期ジャーナルやmanifestを`data.json`に格納するか、`.obsidian/plugins/drive-mirror/`内部の別ファイルに保存する。プラグイン以外が触れない保証はないため、シークレットがVault外に同期・バックアップされないことを構成で守る。ログにtoken・Authorization header・ノート本文を出力しない。

## 5. リモート列挙（v1：WSL Bridge仕様）

1. サーバー設定で許可するルートディレクトリを**絶対パス固定**。プラグインからルート変更不可。
2. `GET /v1/manifest`でディレクトリ内の全ファイルを列挙する。返却JSONに`schemaVersion`, `snapshotId`, `complete=true`, `generatedAt`, `rootIdentity`, ファイルの`opaqueId/path/size/mtime/hash`を含める。**不完全な走査結果は200/complete=trueで返さない。**
3. フォルダ列挙とファイル内容取得はサーバーの許可ルート内に限定。シンボリックリンク/ジャンクションをスキップし、パス正規化衝突に厳格対応する。
4. `GET /v1/file/{opaqueId}`は同じスナップショット中のIDのみ受け付ける。`ETag`, `Content-Length`, 利用可能ならSHA-256の検証値を返す。ファイルが更新されて一致が保証できない場合は409などのエラーを返し、iPhone側は同期を再計画する。
5. サイズ大のファイルはストリーミングを優先し、ネットワーク/ストレージ中断に対応する。iOS側はファイルごとのステージングと検証後反映を使う。
6. Drive for desktopがまだ同期中、Drive仮想ドライブが未マウント、プレースホルダー内容を読めない場合は成功扱いにしない。APIの200レスポンスが`complete=true`であっても、Google側と同期済みかどうかの厳密な外部証明にはならない。運用ではDrive for desktopの同期状態を確認する。

### 5.1 非採用の参考仕様：直接Drive API方式

以下は将来OAuthの適合性レビューを経て採用する場合の参考であり、**v1では実装しない**。

1. 利用者がDriveフォルダの **folder ID** を指定する（名前ベース検索・自動フォルダ作成は禁止）。
2. `files.get`でIDが存在し、`mimeType=application/vnd.google-apps.folder`、非trashであることを検証する。
3. キューを使ってフォルダを幅優先探索。各フォルダの`files.list`を`q="'<id>' in parents and trashed = false"`で実行。
4. `pageSize<=1000`、`nextPageToken`がなくなるまで取得。`incompleteSearch=true`またはページングエラー時は全体を失敗扱い。
5. 各アイテムの `id,name,mimeType,modifiedTime,size,md5Checksum,sha256Checksum,version,parents` を取得。APIが返さない任意項目はnullable扱い。
6. リモートファイル名をバリデーション（次節）。同一階層の同名、Unicode正規化衝突、大文字小文字衝突を検知したら安全のため同期停止。
7. 全件列挙が終わった時点でmanifestを**不変のスナップショット**として確定。v1は毎回全件のメタデータを列挙する。Changes APIは将来の高速化候補であり、正しさは全件列挙で担保する。

**注意:** Driveの列挙は厳密なデータベーススナップショットとは限らない。列挙中に変更が発生した場合、API取得値の不整合が起こり得る。同期の終盤で重要なファイルのversion確認／必要に応じ再走査し、不一致を検出したときは破壊的削除を保留して再試行する。**瞬間的な全ファイルの完全な原子的一致は保証しない**。

## 6. セキュリティ：パス検証・除外

**絶対に書き込まない/削除しない:**
- `.obsidian/` とその全子孫（Obsidianの実際の設定ディレクトリ名 `vault.configDir` を参照）
- 内部ステージング・バックアップ・ジャーナルに割り当てた隠しディレクトリ
- `.git/`, `.trash/` を含む隠しフォルダ・隠しファイル
- ミラー対象として許容しない予約ファイル名

**リモート名検証:** 空、`.`、`..`、区切り文字 `/` と `\`、NUL/制御文字、先頭または途中に潜む危険なパス成分、Unicode NFKC/NFC・大文字小文字の衝突、端末ファイルシステムで扱えない名前を拒否。正規化後の相対パスがVaultルートから逸脱しないことを保証する。任意のリモート名をAPIのローカルファイルパスに直接連結しない。

**スコープガード:** 操作前に「専用Vaultの識別子」「接続先folder ID」「初回の利用者明示同意」を照合する。対象フォルダ変更時には自動同期を停止し、差分プレビューを要求する。

## 7. ミラー同期エンジン

### 7.1 状態モデル

```ts
type SyncPhase =
  | 'IDLE' | 'AUTH' | 'SCAN_REMOTE' | 'SCAN_LOCAL'
  | 'PLAN' | 'STAGE_DOWNLOADS' | 'VERIFY'
  | 'APPLY_UPSERTS' | 'PRUNE' | 'COMMIT' | 'DONE' | 'FAILED';

interface LocalRecord {
  remoteId: string;
  path: string;
  remoteFingerprint: string; // version/checksum
  contentSha256: string;     // hash computed after local write
  size: number;
}
interface MirrorState {
  schemaVersion: number;
  rootFolderId: string;
  vaultIdentity: string;
  generation: number;
  lastCompleteSyncAt: string | null;
  records: Record<string, LocalRecord>;
}
```

### 7.2 アルゴリズム（正しさ優先）

```text
LOCK: same vault concurrent sync prohibited
AUTH: validate read-only provider credentials
SCAN_REMOTE: retrieve a complete validated manifest
SCAN_LOCAL: enumerate all non-protected local files;
            compute SHA-256 of *every* managed local file
PLAN:
  create       := remote exists, local missing
  replace      := remote differs OR local hash != expected remote mirror hash
  delete       := local exists, remote missing (includes local-only new files)
  unchanged    := both match
STAGE_DOWNLOADS: retrieve all required bytes into bounded staging
VERIFY: validate size / checksum / remote version; reject inconsistent input
APPLY_UPSERTS: replace/create files safely; journal successful steps
PRUNE: only if full remote scan + verification + all planned downloads succeeded;
       delete local-only files in owned area, preserving .obsidian and protected paths
COMMIT: save full mirror state and lastCompleteSyncAt only after successful operations
UNLOCK
```

**厳密な編集破棄:** Driveが更新されていなくても、iPhone側のSHA-256が同期記録にある`contentSha256`と違えば、Drive側から再ダウンロードする。mtime/sizeのみでは判定しない。多数ファイルを毎回ハッシュ化するコストをUIに表示する。高速モードを将来追加する場合、strictモードと明確に区別する。

**初期状態:** 空のiPhone専用Vaultから開始する。Driveと異なる既存コンテンツがあるVaultへ初期化を許可する場合は、デフォルト拒否・明示確認とバックアップを要求。

**ローカル削除:** ファイルはObsidianのVault/Adapter APIで処理する。大量削除時は事前プレビューし、設定閾値超過なら同期を停止して再確認。`.obsidian`と内部ステートは操作対象としない。削除の意味は「専用キャッシュの管理対象ファイルを消す」であり、Google Driveの削除操作ではない。

**ファイル転送失敗:** ダウンロード成功前に既存ファイルを消さない。staging先にダウンロード→長さ/checksum検証→書換え。Obsidianのアダプタにおけるatomic renameの保証を前提にしない。操作ジャーナルと一時バックアップを使って部分失敗からの再同期を可能にする。iOSメモリの制約上、サイズ上限／バッチ処理を実装する。

### 7.3 ファイル識別とハッシュ

- Drive IDは移動・リネーム追跡に利用できるが、**ローカルの最終配置は相対パス基準**。
- Driveが`sha256Checksum`を返す場合は転送後に照合。なければ`md5Checksum`とサイズ、version/modifiedTimeの再確認を組み合わせる（MD5は認証用途には使わない）。
- 取得した最終ローカルバイト列はSHA-256を計算し、以後の改変検知に用いる。
- 一時ファイルやダウンロード途中の断片をObsidianのノートとして表示させない。

### 7.4 大容量・オフライン

- 初期の同時ダウンロード数は **2**（設定で1～3程度）。
- v1の推奨1ファイル上限 **20 MiB**。超えるファイルは`SKIPPED_OVERSIZE`として明示し、同期を`PARTIAL`扱いにする。厳密な「完全ミラー」達成条件には含めない。
- 大きなPDF等を本当に必要とする場合は、Range download/分割転送＋ファイルストリーミング対応をv2で評価する。`requestUrl`の`ArrayBuffer`使用はメモリを消費するため全サイズ無制限の実装を避ける。
- オフラインではキャッシュを保持し、削除を実行しない。
- 401はtoken refresh 1回、429/5xxは指数バックオフ（上限とjitter付き）、403/404/invalid_grantは通知・処理中断。403でもrate-limitとpermission-deniedを区別する。
- iOSバックグラウンド実行・終了後の自動同期は前提にしない。Obsidian前面中の手動同期を基本とする。

### 7.5 削除のセーフティ

- `Prune`の前提: リモート全件列挙成功、全パス検証成功、必要なダウンロードと検証成功、初回所有チェック済み。
- 急激な件数減少（例：**20件以上かつ管理対象の20%以上**）がある場合は確認ダイアログ（閾値は設定可能）。
- **Driveが本当に空になった場合**も一律に破壊的削除を禁止するわけではない。意図的な空状態をユーザーがプレビューで承認した場合のみローカルを空にする。
- `Dry run`をv1必須とする。削除・置換・作成件数を適用前に確認できる。
- ローカルで作成したノートの削除は仕様であり、「同期時に失われる」旨を画面に明示する。

## 8. UI / 設定

**設定画面:**
- 接続方式（provider）・認証状態・サインアウト/資格情報失効
- Drive root folder ID（ロック/変更時再確認）
- 厳密なローカルハッシュ検証：ON固定（v1）
- 手動同期ボタン / Dry run ボタン
- 最大ファイルサイズ・ダウンロード同時数
- 自動同期：デフォルトOFF（十分な検証後、起動時同期ONを追加可）
- 削除警告閾値・同期除外のレポート
- エラー／検証失敗の一覧・直近同期履歴（token/本文無し）

**同期プレビューの表示例:**

```text
Drive Mirror Preview
  Remote files: 4,328
  Local files:  4,329
  Download:       16
  Replace:         7   (including 2 local edits)
  Delete:          1   (iPhone-only file)
  Unchanged:   4,305
  Skipped:         0
[Cancel] [Apply]
```

注：UI上の数値は例示であり、実測値ではない。

**成功の定義:** 対象すべてのダウンロード・検証・上書き・削除・状態保存に成功。`PARTIAL`（大きいファイルのスキップ等）は`SUCCESS`と混同しない。

## 9. 非機能要件・セキュリティ

- iOS対応：`manifest.json` に `isDesktopOnly:false`。Node.js `fs`, `path`, `crypto`（Node固有）、Electronに実行時依存しない。WebCrypto, Obsidian `requestUrl`, Vault/Adapter APIを優先。
- **v1のプラグインは自分のTailscale Bridge宛てだけに通信**し、Google APIとは通信しない。アナリティクス/テレメトリー禁止。
- Markdown内容をconsole/error logsへ出さない。OAuth state・code・access token・refresh token・Cookie・APIキーもログに出さない。
- サービス側でGoogle資格情報を保持する場合は暗号化保存、秘密鍵分離、アクセス制御、失効経路、レート制限を必須とする。
- 暗号化されていないiPhoneローカルVaultは、iOS端末のアクセス制御・バックアップ設定の影響を受ける。Google Driveのread-only権限はiPhone側のノート機密保持を意味しない。
- アップデートはGitHub Private Repository経由。Release assetはCIで作り、ビルド・テスト成功を必須条件とする。
- GitHub PAT、OAuth credential、refresh token、個人ノート、バックアップは絶対にGit履歴へ含めない。

## 10. テスト計画

### 10.1 単体テスト（Vitest等）

1. 新規・更新・ローカル編集・ローカル追加・ローカル削除の差分判定。
2. mtime/sizeが同一でも本文だけ違う場合のSHA-256検出。
3. Drive側ファイル削除と移動・リネーム。
4. 非同期中断・401・429・5xx・ネットワーク切断。
5. ページング中の失敗・`incompleteSearch`・0件誤応答・フォルダ未発見。
6. Google Drive同名ファイル、Unicode正規化衝突、大小文字衝突。
7. `../`・特殊区切り・予約パスへの侵入試行。
8. `.obsidian/`・プラグインdata.jsonが変更・削除されないこと。
9. staging破損・チェックサム不一致・部分書込み・再開。
10. 削除閾値・Dry run・キャンセル・二重同期ロック。
11. 20MiB超の扱いと`PARTIAL`表示。
12. 失効トークン・サインアウト・秘密情報マスキング。

### 10.2 結合テスト

- Google Drive上に**独立した検証用フォルダ**を作成し、テストアカウントで実データを使用。
- Windows版Obsidianの**専用テストVault**で全ケースを実施。
- iPhone版Obsidianの専用VaultへBRAT配布し、手動同期を実施。
- ネットワーク切断、画面ロック、Obsidian強制終了、再開、連続同期を確認。
- 最後に同期対象のファイルパスと内容ハッシュがすべて一致することを検証（除外・未対応ファイルは別集計）。

### 10.3 受け入れ条件（Definition of Done）

- [ ] **自作コードにはGoogle APIやGoogle OAuth実装が存在しない**。WSL Bridgeにはアップロード・変更・削除のAPIが存在しない。
- [ ] Bridgeの許可ディレクトリが未設定/無効/読み取り不可なら同期不能。
- [ ] iPhoneの既存ノート編集が次回同期で確実にDrive版へ戻る。
- [ ] iPhoneだけの新規ファイルが同期後に削除される。
- [ ] Driveから削除したノートがiPhoneでも消える。
- [ ] Driveから削除したノートをiPhoneで再作成しても同期後は消える。
- [ ] 同一内容なら必要なダウンロードが発生しない。
- [ ] `.obsidian/` と資格情報、プラグイン自身を絶対に削除・上書きしない。
- [ ] 失敗したRemote listを根拠に全消去が実行されない。
- [ ] iOS実機でTailscale経由の認証済みBridgeアクセス、ファイルの作成・上書き・削除が動作する。
- [ ] GitHub Private RepoのReleaseからBRATでiPhoneへインストール・更新できる。
- [ ] 破壊的変更を加えず再実行でき、途中失敗後に回復可能。

## 11. 開発環境 — Windows 11 / WSL2 / VS Code

### 11.1 推奨構成

- **編集・ビルド・テスト:** WSL2 Ubuntu（または既存Dev Container）
- **ランタイム:** Node.js LTS、npm、TypeScript、esbuild、Vitest、ESLint
- **エディタ:** VS Code Remote WSL / Dev Containers
- **ソース:** `/home/<linux-user>/src/drive-mirror` などWSL ext4内
- **Windows実機検証:** Windows版Obsidianの独立テストVault
- **iOS実機検証:** iPhone上のObsidian + BRAT
- **GitHub:** Private Repo + GitHub Actions + Releases

**避けること:** `node_modules`やesbuildのwatch対象を `/mnt/c`、`/mnt/g`（Google Drive for Desktop）に置かない。WindowsのテストVaultにはビルド成果物だけをコピーする。

### 11.2 WSL導入コマンド例

```bash
# WSL内（既存のNode対応Dev Containerでもよい）
node --version
npm --version
git --version

mkdir -p ~/src && cd ~/src
# テンプレートから自分のprivate repoを作成してcloneすることを推奨:
# https://github.com/obsidianmd/obsidian-sample-plugin
# 例: git clone git@github.com:<your-account>/drive-mirror.git
cd drive-mirror
npm ci
npm run build
npm test
```

**最初のセットアップ:** Obsidian公式Sample Pluginをテンプレートにし、`manifest.json` (`id=drive-mirror`, `isDesktopOnly=false`)・README・ビルド設定を変更。`package-lock.json`をコミットし、CIは`npm ci`を使う。

**Windows版Obsidianのテスト:**

```bash
# ビルド成果物のみをWindows test vaultへコピー（パスは適宜編集）
TEST_PLUGIN_DIR="/mnt/c/Users/<WindowsUser>/Documents/ObsidianTestVault/.obsidian/plugins/drive-mirror"
mkdir -p "$TEST_PLUGIN_DIR"
cp main.js manifest.json "$TEST_PLUGIN_DIR/"
# 必要に応じて styles.css もコピー
```

WindowsテストVaultには実データを使わない。デスクトップのDevToolsでログを見られるが、iOS実機の詳細Web Inspectorは通常Mac + Safariが必要。Macなしでもプラグイン内に診断画面を設ければブラックボックス実機テストは可能。

### 11.3 iPhoneへプライベート配布（BRAT）

1. Private RepositoryのGitHub Releaseに`main.js`・`manifest.json`（必要なら`styles.css`）を添付。
2. タグ名とmanifestの`version`を一致させる。
3. iPhone版Obsidianで**専用Vault**を作成し、コミュニティプラグインBRATを導入。
4. GitHub Fine-grained PAT（当該repoのみ、Contents Read-only）を発行しBRATへ設定。
5. BRATにprivate repositoryを追加し、対象バージョンをインストール（最初は固定バージョン推奨）。
6. Drive Mirrorを有効化し、実機の接続・同期・失敗回復テストを実行。

注意：BRATのバージョンによって設定UIは変わり得る。Private Repositoryについては公式BRAT Developer Guideに記載がある。PATをチャット・GitHub Issue・リポジトリには掲載しない。

### 11.4 CI構成

- PR / push: `npm ci` → `npm run lint` → `npm run typecheck` → `npm test` → `npm run build`。
- リリース: バージョン整合性確認、上記テスト、GitHub Release Assets作成（artifact provenanceを推奨）。
- リリースにOAuth Secretやtokenを含めない。
- CIで実Google Driveの長期有効トークンを扱わず、Mock APIと別の手動統合テストを使う。

## 12. 実装の順序（CLIエージェント向け）

| Phase | 成果物 | 完了条件 |
|---|---|---|
| P0 | **Drive for desktop → WSL Bridge → Tailscale → iPhone経路の実証** | 検証用Vaultの完全列挙/取得、ルート制限と到達性を実機で確認 |
| P1 | プラグイン雛形・Mock Provider | Windows/WSLでビルド、Obsidianデスクトップで動作 |
| P2 | Remote inventory + path validation | 多ページ・入れ子・重複・不正パスを正しく処理 |
| P3 | Strict diff planner + Dry run UI | ローカル編集/追加/削除のプランが全テスト合格 |
| P4 | Download + verify + journal | ダウンロード失敗で安全に再試行できる |
| P5 | Prune・保護パス・閾値 | 破壊的削除の安全テスト合格 |
| P6 | Windows公式Drive for desktop連携試験 | 検証用DriveフォルダのローカルファイルとiPhoneのミラー内容が一致 |
| P7 | iOS BRAT配布・実機試験 | iPhoneで手動同期、切断復帰、更新が動く |
| P8 | 運用版リリース | ドキュメント・バックアップ・エラーメッセージ・簡単な診断が揃う |

**エージェントへの実装規範:**
- 最初に `AGENTS.md` とこの`DESIGN.md`を読み、既存のテストを必ず確認してから変更する。
- 重要な実装は機能単位に切り、単体テストを追加する。
- RemoteReadProviderの`write`/`delete`などのメソッドを定義しない。
- `PLAN`・`APPLY`を分離し、Dry runでしか実行しないモードを必須とする。
- 安全性を落として「全ファイル削除して全件再ダウンロード」する近道を取らない。
- 端末動作未確認の機能を「iOSで動作済み」と記載しない。

## 13. 意図的なスコープ外

- iPhoneからDriveへの書き込み・アップロード・衝突マージ
- iCloud/Obsidian Syncとの二重同期
- `.obsidian`設定・コミュニティプラグイン設定のデバイス間同期
- iPhoneの編集UIを技術的に禁止する仕組み
- iOSアプリ未起動・バックグラウンドでの定期同期の保証
- 任意の共有ドライブやGoogle Workspace全形式の完全互換（v1は指定フォルダの標準バイナリファイルが中心）

## 14. 未解決の設計判断

1. **P0:** Windows Drive for desktop上のVaultをWSLから確実に読めるか。特にストリーミング時の同期状態・オンデマンド取得・ファイル権限・ファイルロックの扱いを検証する。
2. **P0:** Tailscale Windows→WSL中継（D-6: Windows側`tailscale serve`）を実機で確認し、iPhoneからBridgeへ認証済みで接続できるかを検証する。PCが停止中は更新不能。
3. **将来検討:** 直接Drive API接続やCloud OAuthゲートウェイを採用したい場合、Google OAuthクライアント型、Restricted scope、ユーザーデータポリシー、サーバー内restricted dataの扱いを改めて公式資料で確認する。勝手に有効化しない。
4. ~~PDFや画像が1件20MiBを大幅に超えるか~~ → D-5で分割ダウンロードをv1要件に昇格済み。
5. 隠しファイルを同期する必要があるか。` .obsidian`の保護と衝突しない明示的な別ポリシーが必要。

## 15. 参照資料（2026-10-16確認）

- Obsidian sample plugin: https://github.com/obsidianmd/obsidian-sample-plugin
- Obsidian plugin development: https://docs.obsidian.md/Plugins/Getting%20started/Build%20a%20plugin
- Obsidian mobile: https://docs.obsidian.md/Plugins/Getting%20started/Mobile%20development
- Obsidian manifest: https://docs.obsidian.md/Reference/Manifest
- BRAT Developer Guide (Private Repo / PAT): https://github.com/TfTHacker/obsidian42-brat/blob/main/BRAT-DEVELOPER-GUIDE.md
- Google Drive API files.list: https://developers.google.com/workspace/drive/api/reference/rest/v3/files/list
- Google Drive API files metadata: https://developers.google.com/workspace/drive/api/reference/rest/v3/files
- Google Drive readonly and scope classification: https://developers.google.com/workspace/drive/api/guides/api-specific-auth
- Google OAuth 2.0 policies (platform-appropriate clients): https://developers.google.com/identity/protocols/oauth2/policies
- Restricted scope personal-use verification exception: https://developers.google.com/identity/protocols/oauth2/production-readiness/restricted-scope-verification
- OAuth refresh token behavior: https://developers.google.com/identity/protocols/oauth2/

---

**一文で表す仕様:** `Drive Mirror v1 = one-way, authoritative, content-verified, deletion-propagating mirror of a Windows-local vault synced by official Google Drive for desktop, served to an iPhone Obsidian vault via a Tailscale-only read-only WSL bridge; custom code never invokes Google OAuth or Drive API.`
