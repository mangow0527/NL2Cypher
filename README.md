# Text2Cypher 闭环系统

一个围绕 `id` 串联的自然语言问答闭环系统。仓库现已按“单仓内独立服务工程”重组，核心目录如下：

- `services/query_generator_agent/`
- `services/testing_agent/`
- `services/repair_agent/`
- `console/runtime_console/`
- `contracts/`

当前明确五个服务名称：

1. `cypher-generator-agent`（端口 `8000`）
   - 接收 `id + question`
   - 主动向 `knowledge-agent` 获取 `prompt`
   - 调用模型生成 Cypher
   - 保留 `id + prompt` 与原始输出快照
   - 将生成结果提交给 `testing-agent`
2. `testing-agent`（端口 `8001`）
   - 接收 Golden Answer（标准答案）
   - 接收 `cypher-generator-agent` 提交的 Cypher
   - 负责执行 TuGraph
   - 完成评测并在失败时产出问题单
3. `repair-agent`（端口 `8002`）
   - 接收问题单
   - 做根因分析与对照实验
   - 产出修复计划
4. `knowledge-agent`（端口 `8010`）
   - 提供 Cypher 生成所需的知识上下文
   - 接收并应用知识修复建议
5. `qa-agent`（端口 `8020`）
   - 提供自然语言问题与黄金样本

当前 `cypher-generator-agent` 的正式职责定义以
[Cypher_Generation_Service_Design.md](/Users/mangowmac/Desktop/code/NL2Cypher/services/query_generator_agent/docs/Cypher_Generation_Service_Design.md)
为准。

## 快速开始

```bash
./start.sh
./test.sh
./stop.sh
```

控制台入口：

- cypher-generator-agent: [http://localhost:8000/console](http://localhost:8000/console)
- testing-agent: [http://localhost:8001/health](http://localhost:8001/health)
- repair-agent: [http://localhost:8002/console](http://localhost:8002/console)
- knowledge-agent: [http://localhost:8010/health](http://localhost:8010/health)
- qa-agent: [http://localhost:8020/health](http://localhost:8020/health)

## 当前工作流

1. `qa-agent` 向 `cypher-generator-agent` 提交 `id + question`
2. `cypher-generator-agent` 向 `knowledge-agent` 拉取当前可用 `prompt`
3. `cypher-generator-agent` 调用模型生成 Cypher，并保留 `input_prompt_snapshot`
4. `cypher-generator-agent` 把 `generated_cypher + generation evidence` 提交给 `testing-agent`
5. `testing-agent` 执行 TuGraph，等待或合并对应的 Golden Answer
6. `testing-agent` 完成评测，失败时创建 `IssueTicket`
7. `repair-agent` 基于问题单生成 `RepairPlan`

## 主要接口

### cypher-generator-agent

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

### testing-agent

提交 Golden Answer：

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

提交生成结果给 `testing-agent`：

```bash
curl -X POST http://localhost:8001/api/v1/evaluations/submissions \
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
curl http://localhost:8001/api/v1/evaluations/qa-001
```

查询问题单：

```bash
curl http://localhost:8001/api/v1/issues/{ticket_id}
```

## 配置说明

### cypher-generator-agent 环境变量

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

### testing-agent 环境变量

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

### repair-agent 环境变量

- `REPAIR_SERVICE_HOST`
- `REPAIR_SERVICE_PORT`
- `REPAIR_SERVICE_CGS_BASE_URL`
- `REPAIR_SERVICE_KNOWLEDGE_OPS_REPAIRS_APPLY_URL`
- `REPAIR_SERVICE_LLM_ENABLED`
- `REPAIR_SERVICE_LLM_BASE_URL`
- `REPAIR_SERVICE_LLM_API_KEY`
- `REPAIR_SERVICE_LLM_MODEL_NAME`
- 兼容旧变量：`REPAIR_SERVICE_LLM_MODEL`
- 说明：该服务默认要求启用 LLM，缺少关键配置会直接启动失败，不再回退到 deterministic repair-agent 诊断。

## 维护说明

- `cypher-generator-agent` 不执行 TuGraph；执行职责由 `testing-agent` 承担。
- `cypher-generator-agent` 输出的是“生成阶段处理状态”，不是最终业务评测结果。
- 根因分析依赖 `id + input_prompt_snapshot + raw_output_snapshot`，这些字段不得删除。
- 若文档与
  [Cypher_Generation_Service_Design.md](/Users/mangowmac/Desktop/code/NL2Cypher/services/query_generator_agent/docs/Cypher_Generation_Service_Design.md)
  冲突，以该设计文档为准。
