-- Jupyter風のセル実行(molten-nvim)。zj py(Python-Work)専用。
-- 画像出力(plt.show()など)は g:molten_image_provider = "none" で無効化している:
-- ZellijがSixel以外の画像プロトコルをパススルーせず、そのSixel実装自体も不安定なため。
-- text/tableの出力(df.head()含む)はこの制約と無関係にそのまま使える(docs/python.md参照)。
return {
  {
    "benlubas/molten-nvim",
    version = "^1.0",
    build = ":UpdateRemotePlugins",
    ft = { "python" },
    init = function()
      vim.g.molten_image_provider = "none"
      vim.g.molten_auto_open_output = true

      -- Python-Workコンテナのみに用意してある専用Python(Dockerfile参照)。無ければ
      -- 何もしない(WSLホスト・LaTeX-Workコンテナ・SSHサーバーでは未導入のため、
      -- pythonファイルを開いてもmolten系コマンドがエラーになるだけで実害はない)。
      local pynvim_python = "/opt/nvim-pyenv/bin/python"
      if vim.fn.executable(pynvim_python) == 1 then
        vim.g.python3_host_prog = pynvim_python
      end
    end,
    keys = {
      { "<leader>mi", "<cmd>MoltenInit<cr>", desc = "Molten: Init Kernel" },
      { "<leader>me", "<cmd>MoltenEvaluateOperator<cr>", desc = "Molten: Evaluate Operator" },
      { "<leader>ml", "<cmd>MoltenEvaluateLine<cr>", desc = "Molten: Evaluate Line" },
      { "<leader>mr", "<cmd>MoltenReevaluateCell<cr>", desc = "Molten: Re-evaluate Cell" },
      { "<leader>mv", ":<C-u>MoltenEvaluateVisual<cr>gv", mode = "v", desc = "Molten: Evaluate Visual" },
      { "<leader>mo", "<cmd>MoltenShowOutput<cr>", desc = "Molten: Show Output" },
      { "<leader>mh", "<cmd>MoltenHideOutput<cr>", desc = "Molten: Hide Output" },
    },
  },
}
