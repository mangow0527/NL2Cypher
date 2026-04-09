#!/bin/bash

# 停止 Text2Cypher 闭环系统

echo "🛑 停止 Text2Cypher 闭环系统..."

# 查找并终止所有相关进程
PIDS=$(pgrep -f "uvicorn.*app.main:app" || true)

if [ -z "$PIDS" ]; then
    echo "ℹ️  没有找到运行中的服务进程"
else
    echo "🔍 找到以下进程: $PIDS"
    echo "💥 终止进程..."
    echo $PIDS | xargs kill -TERM
    sleep 2
    
    # 检查是否还有残留进程
    REMAINING=$(pgrep -f "uvicorn.*app.main:app" || true)
    if [ ! -z "$REMAINING" ]; then
        echo "⚠️  强制终止残留进程: $REMAINING"
        echo $REMAINING | xargs kill -KILL
    fi
fi

echo "✅ 所有服务已停止"