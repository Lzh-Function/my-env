#!/usr/bin/env bash

set -u

echo "============================================================"
echo "Dev Container verification"
echo "============================================================"


echo
echo "========== OS =========="
cat /etc/os-release | grep -E 'PRETTY_NAME|VERSION='


echo
echo "========== User =========="
whoami
id


echo
echo "========== Workspace =========="
pwd
ls -ld /workspace


echo
echo "========== GPU =========="
if command -v nvidia-smi >/dev/null 2>&1; then
    nvidia-smi
else
    echo "ERROR: nvidia-smi not found"
fi


echo
echo "========== Python =========="
python --version || python3 --version
uv --version
uvx --version


echo
echo "========== C/C++ =========="
gcc --version | head -n 1
g++ --version | head -n 1
clang --version | head -n 1
clangd --version | head -n 1
cmake --version | head -n 1
ninja --version


# lld / llvm は cargo-xwin の Windows target link に必要
echo
echo "========== LLVM / LLD =========="
lld --version | head -n 1
llvm-config --version


echo
echo "========== Rust =========="
rustc --version
cargo --version
rustup --version


# cargo install した CLI (post-create.sh 側)
echo
echo "========== Rust CLI =========="
/usr/local/cargo/bin/dust --version | head -n 1
/usr/local/cargo/bin/cargo-xwin --version


echo
echo "========== Node.js =========="
node --version
npm --version


# CUDA toolkit は Strata の build 用。
# PATH には入れていないため、絶対パスで存在を確認する。
echo
echo "========== CUDA Toolkit =========="
if [ -x /usr/local/cuda-13.0/bin/nvcc ]; then
    /usr/local/cuda-13.0/bin/nvcc --version | tail -n 1
    du -sh /usr/local/cuda-13.0 2>/dev/null
else
    echo "ERROR: cuda toolkit not found"
fi


echo
echo "========== ffmpeg =========="
ffmpeg -version | head -n 1


echo
echo "========== LaTeX =========="
latex --version | head -n 1
latexmk --version | head -n 2
biber --version | head -n 1


echo
echo "========== Git / GitHub =========="
git --version
gh --version | head -n 1


echo
echo "========== Hugging Face CLI =========="
hf --help >/dev/null && echo "hf CLI available"


# Playwright の browser binary (post-create.sh 側で download)
echo
echo "========== Playwright Chromium =========="
if find "${HOME}/.cache/ms-playwright" -maxdepth 1 -type d \
        -name 'chromium-*' 2>/dev/null | grep -q .; then
    ls -1 "${HOME}/.cache/ms-playwright"
else
    echo "ERROR: playwright chromium not installed"
fi


echo
echo "========== AI coding agents =========="
codex --version
claude --version
opencode --version
opencode2 --version
colab --help >/dev/null && echo "colab CLI available"


echo
echo "============================================================"
echo "Verification finished"
echo "============================================================"
