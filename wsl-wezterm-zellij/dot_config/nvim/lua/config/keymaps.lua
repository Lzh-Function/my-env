-- Keymaps are automatically loaded on the VeryLazy event
-- Default keymaps that are always set: https://github.com/LazyVim/LazyVim/blob/main/lua/lazyvim/config/keymaps.lua
-- Add any additional keymaps here

-- setup-wsl-dev:keymaps ------------------------------------------------------
-- Ctrl+Z(VS Code 癖のサスペンド暴発)を無効化。取り消しは u / やり直しは <C-r>
vim.keymap.set({ "n", "i", "v" }, "<C-z>", "<Nop>")

-- <leader>v : 現在の .tex に対応する PDF を Windows の SumatraPDF で開く
vim.keymap.set("n", "<leader>v", function()
  local pdf = vim.fn.expand("%:p:r") .. ".pdf"
  vim.fn.jobstart({ vim.fn.expand("$HOME/.local/bin/pdfview"), pdf })
end, { desc = "View PDF (SumatraPDF)" })
-- ---------------------------------------------------------------------------
