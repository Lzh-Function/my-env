local wezterm = require 'wezterm'
local config = wezterm.config_builder()

-- 起動と同時に WSL(Ubuntu)のシェルへ入る
config.default_domain = 'WSL:Ubuntu'
-- ↑が効かない場合(config を WSL 側で管理して wsl.exe が PATH に無い等)は
-- 代わりに default_prog をフルパスで:
-- config.default_prog = { 'C:\\Windows\\System32\\wsl.exe', '--distribution', 'Ubuntu', '--cd', '~' }

-- フォント(Nerd Font 必須)
config.font = wezterm.font 'Moralerspace Neon'
config.font_size = 11.0

-- 透過設定
config.window_background_opacity = 0.9
config.text_background_opacity = 1.0
config.win32_system_backdrop = 'Auto'   -- 'Auto' | 'Disable' | 'Acrylic' | 'Mica' | 'Tabbed'

-- 多重化は Zellij に任せるので WezTerm のタブバーは消す(小画面の行を節約)
config.enable_tab_bar = false

-- 低スペック向け軽量化
config.front_end = 'OpenGL'   -- GPUが元気なら 'WebGpu' の方が速いことも。glitchが出たら OpenGL に固定
config.max_fps = 60
config.animation_fps = 1      -- カーソル等のアニメを抑える
config.cursor_blink_rate = 0  -- 点滅オフでCPU微減

config.window_padding = { left = 4, right = 4, top = 4, bottom = 4 }
config.color_scheme = 'Catppuccin Mocha'

-- 起動直後に Zellij へ入りたい場合は次行を有効化(手順6で alias を作る方が柔軟)
-- config.default_prog = { 'wsl.exe', '--cd', '~', '--', 'zellij' }

return config
