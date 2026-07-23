# Slurmクラスタ編: GPU実験ノードからObsidianへ

ログインノード(SSHサーバー)ではエージェントを直接動かさず、`srun`で計算ノードに
Apptainerコンテナを起動してそこでエージェントを駆動する構成。実験結果を見て、
エージェントに`obsidian-vault`へノートを書いてもらう用途を想定。

## 全体の流れ

```
ログインノード(SSH)
 ├─ claude / codex を導入 ── ログインのためだけ(実行はしない)
 ├─ obsidian-vault を ~/obsidian-vault に clone(persistent)
 └─ obsidian-skills を ~/obsidian-vault/.claude/skills/ 等に導入(npx skills add)

        │ srun (build_image.sh: CPUのみのパーティションでイメージビルド)
        │ srun (run_agent_node.sh: GPUパーティションでエージェント実行)
        ▼

計算ノード(Apptainerコンテナ内、GPU割り当て済み)
 ├─ ~/.claude・~/.claude.json・~/.codex ── ログインノードのものをbind mount(認証再利用)
 ├─ ~/.ssh ── 同上(vaultへのgit push/pull用、read-only)
 ├─ ~/obsidian-vault ── ログインノードのcloneをそのままbind mount(obsidian-skills込み)
 ├─ 実験の作業ディレクトリ ── bind mount。$EXPERIMENT_WORKDIR としてパスを渡す
 ├─ claude / codex はコンテナイメージに焼き込み済み(agent.def参照)
 └─ エージェントは ~/obsidian-vault で起動する(obsidian-skillsがプロジェクトスコープ
    のため。$EXPERIMENT_WORKDIRを参照するようエージェントに指示する)

エージェントが$EXPERIMENT_WORKDIRの実験結果を見てノートを書く
 → obsidian-vault内でgit commit && git push
 → Windows側のObsidian(「Obsidian Git」プラグインで自動pull)に反映
```

## セットアップ手順

**1. ログインノードで(1回だけ)**

```bash
bash setup_login_node.sh
# その後、指示に従って手動ログイン:
claude
codex
```

**2. コンテナイメージをビルド(1回だけ、こちらも計算ノード側で)**

```bash
bash build_image.sh
```

ビルドもベースイメージ取得・パッケージインストールでそれなりに負荷がかかるため、
ログインノードでは行わず`srun`経由で計算ノード側で行う(GPU割り当ては不要)。
unprivilegedユーザーでも既定でfakerootが使われてビルドできるはずだが、クラスタ側で
user namespaceが制限されている場合は失敗することがある(その場合は管理者に確認)。

**3. 実験のたびに(計算ノードでの作業)**

```bash
bash run_agent_node.sh /path/to/experiment/workdir
```

`~/obsidian-vault`にいる状態でコンテナ内のシェルに入る(obsidian-skillsがここに
入っているため)。そこで`claude`または`codex`を起動し、「`$EXPERIMENT_WORKDIR`の
実験結果を見てノートを書いて」のように実験の作業ディレクトリを明示して指示する。

## 要調整・後回しにしている点(そのままでは動かない箇所)

`run_agent_node.sh`と`build_image.sh`、両方の`SRUN_OPTS`が完全なプレースホルダーです。
少なくとも以下を実際のクラスタに合わせて書き換える必要があります:

- `--partition=CHANGE_ME`: 実際のパーティション名(ビルド用とGPU実行用で別パーティション
  になっているクラスタも多いので、2つのスクリプトで別の値になる可能性が高い)
- `--gres=gpu:1`(`run_agent_node.sh`のみ): 必要なGPU数・種類(クラスタによっては
  `--gres=gpu:a100:1`のような指定が必要な場合も)
- `--time=...`: それぞれのジョブの時間制限

その他、今の時点でまだ詰めていない点:

- エージェントに実験結果からノートを書かせる際の**具体的な指示テンプレート**
  (どのファイルを見て、どんな形式のノートを`obsidian-vault`のどこに書くか)
- `obsidian-vault`内でのcommit/pushを**エージェント自身にやらせるか**、それとも
  ログインノード側で別途手動/定期的に行うか
- 複数の実験・複数のジョブが同時に走る場合の`obsidian-vault`の扱い(同時書き込みで
  コンフリクトしないか)
- Apptainerイメージの`claude`/`codex`のバージョン更新方法(イメージの再ビルドが
  必要になる)
- `agent.def`はUbuntu 24.04ベースの最小構成。実験自体に必要なPython/CUDA関連の
  パッケージは含めていない(既存の実験用イメージに`claude`/`codex`だけ追加する形に
  作り変えるのが現実的かもしれない)
