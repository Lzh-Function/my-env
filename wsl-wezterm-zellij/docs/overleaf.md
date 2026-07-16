# Overleaf連携編: `zj tex`で書いてOverleafと同期する

共同執筆者がOverleaf(ブラウザ上のLaTeXエディタ)を使っている場合に、この環境
(`zj tex`、LazyVim + texlab + vimtex)でローカル編集しながらOverleaf側とファイルを
同期する方法。**Overleafの有料プラン(Cloud版の場合)が必要な機能**なので、まずは
その前提を確認してから読み進めること。

## 前提: Overleaf側の有料プランが必要

Overleaf公式ドキュメントによると、以下はどちらも**Overleaf Cloudの有料プラン**
(個人/コラボレーション向けプレミアムプラン)が必要な機能:

- **GitHub Sync**(OverleafプロジェクトをGitHubリポジトリとリンクする)
- **Git Integration**(通称「git bridge」。Overleafプロジェクトを直接gitリモートとして
  clone/push/pullする)

無料プランではどちらも使えない。共同執筆者に確認してから設定を始めること。

## 2つの連携方法、どちらを選ぶか

| | GitHub Sync | Git Integration(git bridge) |
|---|---|---|
| GitHubアカウントのリンクが必要 | 要 | 不要 |
| ブランチ | GitHub側は自由(Overleaf側はmainのみ反映) | **mainのみ**(ブランチ運用不可) |
| 同期のトリガー | Overleaf側で「Sync」ボタンを手動クリック | 普通の`git push`/`git pull` |
| 競合時の扱い | Overleaf側の変更を別ブランチに退避 → PRで解決 | 通常のgit競合として扱われる |
| 向いているケース | GitHubでレビュー・PRも絡めたい、Overleaf側にも
  共同執筆者がいる | シンプルに「gitリモートの1つ」として使いたいだけ |

「connect to overleaf by github」という要望なら**GitHub Sync**が該当する。以下は
GitHub Syncを主軸に説明し、Git Integrationは補足として後述する。

## GitHub Syncのセットアップ

### 1. アカウントをリンクする(初回のみ、Overleaf側で)

Overleafの Account Settings から GitHub アカウントを接続する。組織(Organization)配下の
リポジトリを使いたい場合は、その組織の Owner が GitHub 側で Overleaf の OAuth アプリに
アクセス許可を出す必要がある。

### 2a. 既存のOverleafプロジェクトをGitHubリポジトリ化する

1. Overleafでプロジェクトを開く
2. 左サイドバーの **Integrations** → **GitHub**
3. 作成したいリポジトリ名を入力

### 2b. 既存のGitHubリポジトリをOverleafプロジェクトとしてインポートする

1. Overleafの **New Project** メニュー
2. **Import from GitHub**
3. GitHubの権限で見えるリポジトリ一覧から選択

どちらの順でも最終的にOverleafプロジェクトとGitHubリポジトリがリンクされる。

### 3. このリポジトリの`~/workspace/LaTeX-Work`にclone(WSL側)

`README.md`のTutorialで案内している「サブフォルダ運用」(`<文書名>/main.tex`)に
合わせて、GitHubリポジトリを`LaTeX-Work`の下にサブフォルダとしてcloneする。
GitHub用のSSH鍵は`setup_wsl.sh`のセットアップで既に登録済みのはず(同じ鍵がその
GitHubアカウントでも使えるように、GitHub側で鍵を登録しておくこと)。

```
cd ~/workspace/LaTeX-Work
git clone git@github.com:ユーザー名/リポジトリ名.git 文書名
```

以降は`zj tex`から`文書名/main.tex`を`latexmk -cd`でビルドできる
([`latex.md`](./latex.md)参照)。

### 4. 編集・コミット・pushはこの環境でいつも通り

```
zj tex
```

1. nvimで編集 → `:w`
2. `latexmk -pvc -cd 文書名/main.tex`で自動ビルドしながら執筆
3. コミット・pushは`<space>gg`(lazygit)が一番早い
   ([`lazyvim.md`](./lazyvim.md)の「Git連携」参照)。`文書名`フォルダの中で
   lazygitを開けば、そのGitHubリポジトリに対してコミット・pushできる

### 5. Overleaf側に取り込む(Pull)

**同期は自動ではない。** GitHubへpushしただけではOverleafの画面には反映されない。

1. Overleafでプロジェクトを開く
2. **Integrations** → **GitHub**
3. GitHubにある新しい変更が一覧表示されるので、確認して **Pull**

### 6. Overleaf側で編集された内容をこちらに取り込む(逆方向)

共同執筆者がOverleafのブラウザエディタで直接編集した場合:

1. Overleaf側で **Integrations** → **GitHub** → 「Push Overleaf changes to GitHub」
   (コミットメッセージは任意)。コミットは連携したGitHubアカウント名で作成される
2. こちら側(`zj tex`)で`git pull`(またはlazygitの`p`)

### 競合したら

Overleaf側とこちら側で同時に同じ箇所を編集してpush/pullがぶつかると、Overleafは
**Overleaf側の変更を別ブランチとして退避**する。そのブランチをローカルの`git`
(またはGitHub上のPull Request)でmainにマージして解決する
(このリポジトリの環境なら、`zj tex`のshellペインで素の`git merge`コマンドを使うのが
確実)。

## Git Integration(git bridge)を使う場合の要点

GitHubアカウントを絡めず、シンプルにOverleafプロジェクトを1つのgitリモートとして
扱いたい場合の方法。

```
git clone https://git.overleaf.com/プロジェクトID 文書名
```

- プロジェクトIDとGit URLは、Overleafのプロジェクト画面 → **Integrations** → **Git**
  で確認できる
- 認証は初回`git clone`/`git push`時にユーザー名・パスワード(Overleafのgit連携用
  トークン)を求められる形式
- `git push`/`git pull`は普通のgitリモートと同じ感覚で使える

**制約(公式ドキュメントより)**:

- **ブランチは`main`のみ**。他のブランチを作っても同期対象にならない
- **Git LFSは非対応**。大きなバイナリファイル(画像など)は素のgit管理になる
- **シンボリックリンク非対応**。pushすると通常のファイルに変換される
- **ファイルのリネームは「削除+新規作成」扱い**。Overleaf側のコメントや変更履歴が
  失われることがある
- **Track Changes(変更履歴)やコメントは、git経由のpushで失われたりズレたりする
  ことがある**。共同執筆者がOverleaf上のコメント機能を使っている場合は特に注意

## この環境ならではの補足

- PDFプレビューについては、Overleaf自身がブラウザ上でPDFを表示してくれるので、
  `zj tex`から`<leader>v`が使えない([`latex.md`](./latex.md)の制約)ことは
  Overleaf連携時にはあまり問題にならない。ローカルでのクイック確認は
  `latexmk`でビルドしたPDFをWindows Explorer経由で見る(同上参照)、
  最終確認はOverleaf側で見る、という使い分けがしやすい
- `.latexmkrc`(lualatexエンジン指定)はこのリポジトリのコンテナ内のみの設定。
  Overleaf側のコンパイラ設定(プロジェクトの「Menu」→「Compiler」)を
  **lualatexに合わせておく**と、ローカルとOverleafで見た目が食い違う事故を防げる
