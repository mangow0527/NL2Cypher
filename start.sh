#!/bin/bash

# 启动 Text2Cypher 闭环系统
# 启动三个服务：查询语句生成服务、测试服务、修复服务

set -e

echo "🚀 启动 Text2Cypher 闭环系统..."

# 检查 Python 环境
if ! command -v python3 &> /dev/null; then
    echo "❌ 错误: 未找到 python3"
    exit 1
fi

# 检查数据目录
if [ ! -d "data" ]; then
    echo "📁 创建数据目录..."
    mkdir -p data
fi

# 启动查询语句生成服务 (端口 8000)
echo "🔧 启动查询语句生成服务 (端口 8000)..."
cd services/query_generator_service
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 &
QUERY_PID=$!
cd ../..

# 启动测试服务 (端口 8001)
echo "🔧 启动测试服务 (端口 8001)..."
cd services/testing_service
python -m uvicorn app.main:app --host 0.0.0.0 --port 8001 &
TEST_PID=$!
cd ../..

# 启动修复服务 (端口 8002)
echo "🔧 启动修复服务 (端口 8002)..."
cd services/repair_service
python -m uvicorn app.main:app --host 0.0.0.0 --port 8002 &
REPAIR_PID=$!
cd ../..

echo "✅ 所有服务启动完成！"
echo ""
echo "📊 服务状态："
echo "  查询语句生成服务: http://localhost:8000"
echo "  测试服务: http://localhost:8001"
echo "  修复服务: http://localhost:8002"
echo ""
echo "🌐 Web 控制台："
echo "  查询生成控制台: http://localhost:8000/console"
echo "  测试服务控制台: http://localhost:8001/console"
echo "  修复服务控制台: http://localhost:8002/console"
echo ""
echo "💡 按Ctrl+C停止所有服务"
echo ""

# 等待用户按Ctrl+C
trap 'echo "🛑 正在停止所有服务..."; kill $QUERY_PID $TEST_PID $REPAIR_PID; exit 0' INT
wait