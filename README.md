# Text2Cypher 闭环系统

一个完整的自然语言到Cypher查询生成、测试、修复的闭环系统，基于网络图谱架构。

## 系统架构

系统包含三个主要服务：

1. **查询语句生成服务** (端口 8000) - 接收自然语言问题，生成Cypher查询
2. **测试服务** (端口 8001) - 接收标准答案和查询结果，进行评测
3. **修复服务** (端口 8002) - 分析问题，生成修复计划

## 快速开始

### 1. 启动系统

```bash
# 启动所有服务
./start.sh

# 停止所有服务
./stop.sh

# 测试系统功能
./test.sh
```

### 2. 访问Web控制台

- 查询语句生成控制台: http://localhost:8000/console
- 测试服务控制台: http://localhost:8001/console  
- 修复服务控制台: http://localhost:8002/console

### 3. 系统工作流程

1. **提交问题**: 向查询语句生成服务发送自然语言问题
2. **生成查询**: 系统加载知识包，生成Cypher查询
3. **执行查询**: 在TuGraph图谱中执行查询
4. **提交结果**: 将查询结果提交给测试服务
5. **标准答案**: 向测试服务提交标准答案
6. **自动评测**: 当查询结果和标准答案都齐全时自动评测
7. **问题分析**: 评测失败时生成问题单
8. **修复计划**: 修复服务分析问题并生成修复计划

## API接口

### 查询语句生成服务

#### 提交问题
```bash
curl -X POST http://localhost:8000/api/v1/qa/questions \
  -H "Content-Type: application/json" \
  -d '{
    "id": "qa-001",
    "question": "查询网络设备及其端口信息"
  }'
```

#### 获取执行状态
```bash
curl http://localhost:8000/api/v1/questions/qa-001
```

### 测试服务

#### 提交标准答案
```bash
curl -X POST http://localhost:8001/api/v1/qa/goldens \
  -H "Content-Type: application/json" \
  -d '{
    "id": "qa-001",
    "cypher": "MATCH (ne:NetworkElement)-[:HAS_PORT]->(p:Port) RETURN ne.name, p.name LIMIT 10",
    "answer": [{"device_name": "router-1", "port_name": "eth0"}],
    "difficulty": "L3"
  }'
```

#### 提交查询结果
```bash
curl -X POST http://localhost:8001/api/v1/evaluations/submissions \
  -H "Content-Type: application/json" \
  -d '{
    "id": "qa-001",
    "question": "查询网络设备及其端口信息",
    "generated_cypher": "MATCH (ne:NetworkElement)-[:HAS_PORT]->(p:Port) RETURN ne.name, p.name LIMIT 10",
    "execution": {
      "success": true,
      "rows": [{"device_name": "router-1", "port_name": "eth0"}],
      "row_count": 1,
      "error_message": null,
      "elapsed_ms": 15
    },
    "knowledge_context": {
      "package_id": "default-network-schema",
      "version": "v1",
      "graph_name": "network_schema_v10",
      "summary": "Default knowledge package",
      "loaded_knowledge_tags": ["network_element", "port"]
    }
  }'
```

#### 获取评测状态
```bash
curl http://localhost:8001/evaluations/qa-001
```

#### 获取问题单
```bash
curl http://localhost:8001/issues/{ticket_id}
```

### 修复服务

#### 提交问题单
```bash
curl -X POST http://localhost:8002/api/v1/issue-tickets \
  -H "Content-Type: application/json" \
  -d "$(curl -s http://localhost:8001/issues/{ticket_id})"
```

#### 获取修复计划
```bash
curl http://localhost:8002/api/v1/repair-plans/{plan_id}
```

## 配置说明

### 环境变量

#### 查询语句生成服务
- `QUERY_GENERATOR_HOST`: 服务监听地址 (默认: 0.0.0.0)
- `QUERY_GENERATOR_PORT`: 服务端口 (默认: 8000)
- `QUERY_GENERATOR_TUGRAPH_URL`: TuGraph服务地址 (默认: http://localhost:7070)
- `QUERY_GENERATOR_MOCK_TUGRAPH`: 是否使用模拟TuGraph (默认: true)
- `QUERY_GENERATOR_LLM_ENABLED`: 是否启用LLM (默认: false)

#### 测试服务
- `TESTING_SERVICE_HOST`: 服务监听地址 (默认: 0.0.0.0)
- `TESTING_SERVICE_PORT`: 服务端口 (默认: 8001)
- `TESTING_SERVICE_REPAIR_SERVICE_URL`: 修复服务地址 (默认: http://localhost:8002)

#### 修复服务
- `REPAIR_SERVICE_HOST`: 服务监听地址 (默认: 0.0.0.0)
- `REPAIR_SERVICE_PORT`: 服务端口 (默认: 8002)
- `REPAIR_SERVICE_QUERY_GENERATOR_SERVICE_URL`: 查询语句生成服务地址 (默认: http://localhost:8000)

### 知识包配置

系统使用默认的网络图谱知识包，包含：
- 节点标签: NetworkElement, Protocol, Tunnel, Service, Port, Fiber, Link
- 边标签: HAS_PORT, FIBER_SRC, FIBER_DST, LINK_SRC, LINK_DST, TUNNEL_SRC, TUNNEL_DST, TUNNEL_PROTO, PATH_THROUGH, SERVICE_USES_TUNNEL
- 业务术语映射: 网络设备、端口、隧道等中文术语到图谱实体的映射

## 评测维度

系统从四个维度评测查询质量：

1. **语法有效性** (syntax_validity): Cypher语法是否正确
2. **模式对齐** (schema_alignment): 是否使用正确的标签和关系
3. **结果正确性** (result_correctness): 结果是否与标准答案一致
4. **问题对齐** (question_alignment): 查询是否正确回答了问题

## 问题修复流程

1. **确定性分析**: 检查语法、模式、结果等确定性因素
2. **归因判断**: 识别问题来源 (生成逻辑/知识缺失/问题表达)
3. **对照实验**: 必要时进行不同条件下的实验
4. **修复计划**: 针对不同服务生成具体的修复建议

## 故障排除

### 服务启动失败

1. 检查端口是否被占用
2. 确认Python依赖已安装: `pip install -r requirements.txt`
3. 检查数据目录权限

### 服务间通信失败

1. 确认所有服务都已启动
2. 检查服务URL配置
3. 查看服务日志

### 查询生成失败

1. 检查TuGraph连接配置
2. 确认图谱数据存在
3. 查看知识包配置

## 开发指南

### 添加新的知识包

1. 在 `shared/knowledge.py` 中定义新的知识包
2. 更新知识标签选择逻辑
3. 重新启动服务

### 自定义评测规则

1. 修改 `shared/evaluation.py` 中的评测函数
2. 更新评测维度和标准
3. 重新启动测试服务

### 扩展修复策略

1. 在 `services/repair_service/app/service.py` 中添加新的分析方法
2. 更新修复计划生成逻辑
3. 重新启动修复服务

## 许可证

本项目采用MIT许可证。