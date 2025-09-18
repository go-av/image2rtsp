#!/bin/bash

# 检查Python是否安装
if ! command -v python3 &> /dev/null
then
    echo "Python 3 未安装，请先安装Python 3"
    exit 1
fi

# 检查pip是否安装
if ! command -v pip3 &> /dev/null
then
    echo "pip3 未安装，请先安装pip3"
    exit 1
fi

# 检查FFmpeg是否安装
if ! command -v ffmpeg &> /dev/null
then
    echo "警告: FFmpeg 未安装，推流功能将无法正常工作"
    echo "请按照系统要求安装FFmpeg"
    echo "Ubuntu/Debian: sudo apt-get install ffmpeg"
    echo "macOS: brew install ffmpeg"
    echo "Windows: 请从官方网站下载安装包"
    echo ""
    read -p "是否继续？(y/n): " choice
    case "$choice" in 
      y|Y ) echo "继续执行...";
            ;;
      * ) echo "程序已退出";
          exit 1;
            ;;
    esac
fi

# 创建虚拟环境
if [ ! -d ".venv" ]; then
    echo "创建Python虚拟环境..."
    python3 -m venv .venv
fi

# 激活虚拟环境
source .venv/bin/activate

# 安装依赖
echo "安装依赖..."
pip install -r requirements.txt

# 创建必要的目录
echo "创建必要的目录..."
mkdir -p static/images data data/tasks

# 启动应用
echo "启动应用..."
python app.py