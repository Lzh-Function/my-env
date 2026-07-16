-- bashls (from the util.dot extra) only attaches inside a git repo by default
-- (root_markers = {".git"}), so a standalone file like ~/.bashrc never gets it.
-- Fall back to the file's own directory when no .git is found, so dotfiles edited
-- directly in $HOME still get LSP support.
return {
  {
    "neovim/nvim-lspconfig",
    opts = {
      servers = {
        bashls = {
          root_dir = function(bufnr, on_dir)
            local fname = vim.api.nvim_buf_get_name(bufnr)
            local root = vim.fs.root(fname, { ".git" }) or vim.fs.dirname(fname)
            on_dir(root)
          end,
        },
      },
    },
  },
}
