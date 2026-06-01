#!/bin/bash

echo "📊 初始化数据库示例数据..."
echo ""

# 进入后端目录
cd "$(dirname "$0")/ModelHub-backend" || {
    echo "❌ 错误: 无法进入 ModelHub-backend 目录"
    exit 1
}

# 检查Python环境
if ! command -v python3 &> /dev/null; then
    echo "❌ 错误: 未找到 Python3"
    exit 1
fi

# 激活虚拟环境（如果存在）
if [ -d "venv" ]; then
    echo "🔧 激活虚拟环境..."
    source venv/bin/activate
else
    echo "📦 创建虚拟环境..."
    python3 -m venv venv
    source venv/bin/activate
fi

# 检查依赖
if [ ! -f ".deps_installed" ]; then
    echo "📥 安装依赖（使用国内镜像源加速）..."
    pip install -r requirements-fastapi.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
    touch .deps_installed
fi

# 运行初始化脚本
echo "🚀 开始初始化数据..."
echo ""
python3 scripts/init_sample_data.py

if [ $? -eq 0 ]; then
    echo ""
    echo "✅ 数据初始化完成！"
    echo ""
    echo "测试账号:"
    echo "  系统管理员: admin@example.com / admin123"
    echo "  学校管理员: school_admin@example.com / admin123"
    echo "  教师: teacher1@example.com / teacher123"
    echo "  学生: student1@example.com / student123"
else
    echo ""
    echo "❌ 数据初始化失败，请检查错误信息"
    exit 1
fi

