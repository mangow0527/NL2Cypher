# Text2Cypher 闭环系统

一个围绕 `id` 串联的自然语言问答闭环系统，当前包含四项核心能力：

1. `Cypher Generation Service`（Cypher 生成服务，端口 `8000`）
   - 接收 `id + question`
   - 主动向知识运营服务获取 `prompt`
   - 调用模型生成 Cypher
   - 保留 `id + prompt` 与原始输出快照
   - 将生成结果提交给测试服务
2. `Runtime Results Service`（运行结果中心，端口 `8001`）
   - 聚合来自 QA 生成服务的全部任务
   - 动态展示全流程阶段结果
   - 展示当前生成的 Cypher 与质量概括
3. `Repair Service`（修复服务，端口 `8002`）
   - 接收问题单
   - 做根因分析与对照实验
   - 产出修复计划
4. `Testing Service`（测试服务，端口 `8003`）
   - 接收 Golden Answer（标准答案）
   - 接收生成服务提交的 Cypher
   - 负责执行 TuGraph
   - 完成评测并在失败时产出问题单

当前 Cypher 生成服务的正式职责定义以
[Cypher_Generation_Service_Design.md](/Users/mangowmac/Desktop/code/NL2Cypher/docs/Cypher_Generation_Service_Design.md)
为准。

## 快速开始

```bash
./start.sh
./test.sh
./stop.sh
```

控制台入口：

- 生成服务: [http://localhost:8000/console](http://localhost:8000/console)
- 运行结果中心: [http://localhost:8001/console](http://localhost:8001/console)
- 修复服务: [http://localhost:8002/console](http://localhost:8002/console)
- 测试服务: [http://localhost:8003/health](http://localhost:8003/health)

## 当前工作流

1. 外部服务向生成服务提交 `id + question`
2. 生成服务向知识运营服务拉取当前可用 `prompt`
3. 生成服务调用模型生成 Cypher，并保留 `input_prompt_snapshot`
4. 生成服务把 `generated_cypher + generation evidence` 提交给测试服务
5. 测试服务执行 TuGraph，等待或合并对应的 Golden Answer
6. 测试服务完成评测，失败时创建 `IssueTicket`
7. 修复服务基于问题单生成 `RepairPlan`

## 主要接口

### 生成服务

提交问题：

```bash
curl -X POST http://localhost:8000/api/v1/qa/questions \
  -H "Content-Type: application/json" \
  -d '{
    "id": "qa-001",
    "question": "查询网络设备及其端口信息"
  }'
```

查询本轮生成结果：

```bash
curl http://localhost:8000/api/v1/questions/qa-001
```

查询本轮输入提示词快照：

```bash
curl http://localhost:8000/api/v1/questions/qa-001/prompt
```

### 测试服务

提交 Golden Answer：

```bash
curl -X POST http://localhost:8003/api/v1/qa/goldens \
  -H "Content-Type: application/json" \
  -d '{
    "id": "qa-001",
    "cypher": "MATCH (ne:NetworkElement)-[:HAS_PORT]->(p:Port) RETURN ne.name, p.name LIMIT 10",
    "answer": [{"device_name": "router-1", "port_name": "eth0"}],
    "difficulty": "L3"
  }'
```

提交生成结果给测试服务：

```bash
curl -X POST http://localhost:8003/api/v1/evaluations/submissions \
  -H "Content-Type: application/json" \
  -d '{
    "id": "qa-001",
    "question": "查询网络设备及其端口信息",
    "generation_run_id": "run-001",
    "generated_cypher": "MATCH (ne:NetworkElement)-[:HAS_PORT]->(p:Port) RETURN ne.name, p.name LIMIT 10",
    "parse_summary": "parsed_json",
    "guardrail_summary": "accepted",
    "raw_output_snapshot": "",
    "input_prompt_snapshot": "请只返回 cypher 字段"
  }'
```

查询评测状态：

```bash
curl http://localhost:8003/api/v1/evaluations/qa-001
```

查询问题单：

```bash
curl http://localhost:8003/api/v1/issues/{ticket_id}
```

## 配置说明

### 生成服务环境变量

- `QUERY_GENERATOR_HOST`
- `QUERY_GENERATOR_PORT`
- `QUERY_GENERATOR_TESTING_SERVICE_URL`
- `QUERY_GENERATOR_KNOWLEDGE_OPS_SERVICE_URL`
- `QUERY_GENERATOR_LLM_ENABLED`
- `QUERY_GENERATOR_LLM_PROVIDER`
- `QUERY_GENERATOR_LLM_BASE_URL`
- `QUERY_GENERATOR_LLM_API_KEY`
- `QUERY_GENERATOR_LLM_MODEL`
- 说明：该服务默认要求启用 LLM，缺少以上任一关键配置会直接启动失败，不再回退到启发式生成。

### 测试服务环境变量

- `TESTING_SERVICE_HOST`
- `TESTING_SERVICE_PORT`
- `TESTING_SERVICE_REPAIR_SERVICE_URL`
- `TESTING_SERVICE_TUGRAPH_URL`
- `TESTING_SERVICE_TUGRAPH_USERNAME`
- `TESTING_SERVICE_TUGRAPH_PASSWORD`
- `TESTING_SERVICE_TUGRAPH_GRAPH`
- `TESTING_SERVICE_MOCK_TUGRAPH`
- `TESTING_SERVICE_LLM_ENABLED`
- `TESTING_SERVICE_LLM_BASE_URL`
- `TESTING_SERVICE_LLM_API_KEY`
- `TESTING_SERVICE_LLM_MODEL`
- 说明：该服务默认要求启用 LLM，缺少关键配置会直接启动失败，不再静默保留规则评测结果。

### 修复服务环境变量

- `REPAIR_SERVICE_HOST`
- `REPAIR_SERVICE_PORT`
- `REPAIR_SERVICE_CGS_BASE_URL`
- `REPAIR_SERVICE_KNOWLEDGE_OPS_REPAIRS_APPLY_URL`
- `REPAIR_SERVICE_LLM_ENABLED`
- `REPAIR_SERVICE_LLM_BASE_URL`
- `REPAIR_SERVICE_LLM_API_KEY`
- `REPAIR_SERVICE_LLM_MODEL_NAME`
- 兼容旧变量：`REPAIR_SERVICE_LLM_MODEL`
- 说明：该服务默认要求启用 LLM，缺少关键配置会直接启动失败，不再回退到 deterministic KRSS 诊断。

## 维护说明

- 生成服务不执行 TuGraph；执行职责由测试服务承担。
- 生成服务输出的是“生成阶段处理状态”，不是最终业务评测结果。
- 根因分析依赖 `id + input_prompt_snapshot + raw_output_snapshot`，这些字段不得删除。
- 若文档与
  [Cypher_Generation_Service_Design.md](/Users/mangowmac/Desktop/code/NL2Cypher/docs/Cypher_Generation_Service_Design.md)
  冲突，以该设计文档为准。
