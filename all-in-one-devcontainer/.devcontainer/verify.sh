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


echo
echo "========== Rust =========="
rustc --version
cargo --version
rustup --version


echo
echo "========== Node.js =========="
node --version
npm --version


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


echo
echo "========== AI coding agents =========="
codex --version
claude --version
opencode --version


echo
echo "============================================================"
echo "Verification finished"
echo "============================================================"
