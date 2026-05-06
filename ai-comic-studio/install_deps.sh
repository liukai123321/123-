#!/bin/bash
# ============================================
# AI漫剧音乐剪辑流水线 - 依赖安装脚本
# 支持 Windows (Git Bash) / macOS / Linux
# ============================================

set -e

echo "========================================"
echo " AI漫剧音乐剪辑流水线 - 环境安装"
echo "========================================"
echo ""

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR"

# 1. 检查/安装 ffmpeg
echo "[1/3] 检查 ffmpeg..."
if command -v ffmpeg &> /dev/null; then
    echo "  ffmpeg 已安装 ✓"
else
    echo "  正在安装 ffmpeg..."
    if [[ "$OSTYPE" == "msys" ]] || [[ "$OSTYPE" == "cygwin" ]]; then
        # Windows Git Bash
        if command -v winget &> /dev/null; then
            echo "  使用 winget 安装 ffmpeg..."
            winget install ffmpeg 2>/dev/null || true
        elif command -v scoop &> /dev/null; then
            echo "  使用 scoop 安装 ffmpeg..."
            scoop install ffmpeg
        else
            echo "  ⚠ 请手动安装 ffmpeg:"
            echo "     https://ffmpeg.org/download.html"
            echo "     或使用 winget: winget install ffmpeg"
        fi
    elif [[ "$OSTYPE" == "darwin"* ]]; then
        brew install ffmpeg
    else
        sudo apt update && sudo apt install ffmpeg -y
    fi
fi

# 2. 创建虚拟环境
echo ""
echo "[2/3] 创建 Python 虚拟环境..."
if [ ! -d "venv" ]; then
    python -m venv venv
    echo "  虚拟环境已创建"
else
    echo "  虚拟环境已存在"
fi

# 激活虚拟环境
if [[ "$OSTYPE" == "msys" ]] || [[ "$OSTYPE" == "cygwin" ]]; then
    source venv/Scripts/activate
else
    source venv/bin/activate
fi
echo "  虚拟环境已激活"

# 3. 安装 Python 依赖
echo ""
echo "[3/3] 安装 Python 依赖..."
pip install --upgrade pip -q
pip install -r requirements.txt

echo ""
echo "========================================"
echo " 安装完成！"
echo "========================================"
echo ""
echo "使用方法:"
echo "  cd $PROJECT_DIR"
echo "  source venv/Scripts/activate   # Windows"
echo "  # source venv/bin/activate     # macOS/Linux"
echo ""
echo "  1. 在 projects/demo/input/ 下准备素材:"
echo "     images/   - 漫画图片"
echo "     bgm/      - 背景音乐"
echo "     script/   - 配音剧本 (.txt)"
echo ""
echo "  2. 运行流水线:"
echo "     python scripts/main.py --project demo"
echo ""
echo "  3. 查看产出:"
echo "     projects/demo/output/release/"
echo ""
