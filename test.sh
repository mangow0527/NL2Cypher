#!/bin/bash

# 测试 Text2Cypher 闭环系统的功能完整性

set -e

echo "🧪 测试 Text2Cypher 闭环系统..."

BASE_URL="http://localhost"
SERVICES=(
    "8000:query-generator-service"
    "8001:runtime-results-service"
    "8002:repair-service"
    "8003:testing-service"
)

# 检查服务是否启动
echo "🔍 检查服务状态..."
for service in "${SERVICES[@]}"; do
    port="${service%%:*}"
    name="${service#*:}"
    
    echo -n "  检查 $name (端口 $port)... "
    if curl -s "$BASE_URL:$port/health" > /dev/null; then
        echo "✅ 运行中"
    else
        echo "❌ 未运行"
        echo "💡 请先运行 ./start.sh 启动服务"
        exit 1
    fi
done

echo ""
echo "📝 开始集成测试..."

# 测试1: 提交问题到查询语句生成服务
echo "📝 测试1: 提交问题到查询语句生成服务"
curl -X POST "$BASE_URL:8000/api/v1/qa/questions" \
    -H "Content-Type: application/json" \
    -d '{
        "id": "test-001",
        "question": "查询网络设备及其端口信息"
    }' || echo "⚠️  提交可能失败，继续测试..."

# 等待处理
sleep 3

# 测试2: 提交标准答案到测试服务
echo "📝 测试2: 提交标准答案到测试服务"
curl -X POST "$BASE_URL:8003/api/v1/qa/goldens" \
    -H "Content-Type: application/json" \
    -d '{
        "id": "test-001",
        "cypher": "MATCH (ne:NetworkElement)-[:HAS_PORT]->(p:Port) RETURN ne.name AS device_name, p.name AS port_name, p.status AS port_status LIMIT 20",
        "answer": [
            {"device_name": "edge-router-1", "port_name": "ge-0/0/0", "port_status": "up"},
            {"device_name": "core-switch-1", "port_name": "eth-0/1", "port_status": "down"}
        ],
        "difficulty": "L3"
    }' || echo "⚠️  提交可能失败，继续测试..."

# 等待处理
sleep 5

# 测试3: 查询评测状态
echo "📝 测试3: 查询评测状态"
curl -s "$BASE_URL:8003/api/v1/evaluations/test-001" | python3 -m json.tool || echo "⚠️  查询可能失败"

echo ""
echo "🔍 检查是否生成了问题单..."
sleep 3

# 尝试获取问题单（如果存在）
TICKET_ID=$(curl -s "$BASE_URL:8003/api/v1/evaluations/test-001" 2>/dev/null | grep -o '"issue_ticket_id":"[^"]*"' | cut -d'"' -f4 || echo "")

if [ ! -z "$TICKET_ID" ]; then
    echo "📝 发现问题单: $TICKET_ID"
    echo "📝 测试4: 获取问题单详情"
    curl -s "$BASE_URL:8003/api/v1/issues/$TICKET_ID" | python3 -m json.tool || echo "⚠️  获取问题单失败"
    
    echo "📝 测试5: 提交问题单到修复服务"
    curl -X POST "$BASE_URL:8002/api/v1/issue-tickets" \
        -H "Content-Type: application/json" \
        -d "$(curl -s "$BASE_URL:8003/api/v1/issues/$TICKET_ID" 2>/dev/null)" | python3 -m json.tool || echo "⚠️  提交问题单失败"
else
    echo "ℹ️  未发现问题单，可能系统运行正常"
fi

echo ""
echo "🎉 测试完成！"
echo ""
echo "📊 服务访问地址："
echo "  查询语句生成服务: http://localhost:8000"
echo "  运行结果中心: http://localhost:8001"
echo "  修复服务: http://localhost:8002"
echo "  测试服务: http://localhost:8003"
echo ""
echo "🌐 Web控制台："
echo "  查询生成控制台: http://localhost:8000/console"
echo "  运行结果中心: http://localhost:8001/console"
echo "  修复服务控制台: http://localhost:8002/console"
