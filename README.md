# Text2Cypher 闭环系统

一个围绕 `id` 串联的自然语言问答闭环系统。仓库现已按“单仓内独立服务工程”重组，核心目录如下：

- `services/cypher_generator_agent/`
- `services/testing_agent/`
- `services/repair_agent/`
- `console/runtime_console/`
- `contracts/`

当前仓库内提供四个本地服务：

1. `cypher-generator-agent`（端口 `8000`）
   - 接收 `id + question`
   - 保留输入/输出链路，内部生成流程为空
   - 向 `testing-agent` 提交空 Cypher 和最小 I/O trace
2. `testing-agent`（端口 `8003`）
   - 接收 Golden Answer（标准答案）
   - 接收 `cypher-generator-agent` 提交的 Cypher 或生成失败报告
   - 负责执行 TuGraph
   - 完成评测并在失败时产出问题单
3. `repair-agent`（端口 `8002`）
   - 接收问题单
   - 判断失败是否属于 knowledge-agent 知识缺口
   - 产出知识修复建议并投递给 `knowledge-agent`
4. `runtime_results_service`（端口 `8001`）
   - 汇总 testing-agent 和 repair-agent 落盘证据
   - 提供运行中心单题回放接口和页面

`knowledge-agent` 和 `qa-agent` 是可选外部服务。`tools/run_all_local_services.sh` 会在
`KNOWLEDGE_AGENT_ROOT` 或 `QA_AGENT_ROOT` 配置存在时尝试启动它们；普通 `start.sh`
只启动本仓库内服务。

## 快速开始

```bash
./start.sh
./test.sh
./stop.sh
```

本地服务入口：

- cypher-generator-agent: [http://localhost:8000/health](http://localhost:8000/health)
- cypher-generator-agent status: [http://localhost:8000/api/v1/generator/status](http://localhost:8000/api/v1/generator/status)
- runtime results: [http://localhost:8001/console](http://localhost:8001/console)
- testing-agent: [http://localhost:8003/health](http://localhost:8003/health)
- repair-agent: [http://localhost:8002/console](http://localhost:8002/console)

## 当前工作流

1. `qa-agent` 向 `cypher-generator-agent` 提交 `id + question`
2. `cypher-generator-agent` 生成本轮 `generation_run_id`
4. `cypher-generator-agent` 把空 Cypher submission 和最小 I/O trace 提交给 `testing-agent`
5. `testing-agent` 执行 TuGraph，等待或合并对应的 Golden Answer
6. `testing-agent` 完成评测，失败时创建 `IssueTicket`
7. `repair-agent` 基于问题单生成 `KnowledgeRepairSuggestionRequest` 并尝试投递给 `knowledge-agent`

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

该接口不返回生成结果、生成状态或提示词快照。`cypher-generator-agent` 只负责把空生成结果和最小 I/O trace 提交给 `testing-agent`。
`POST /api/v1/semantic/parse` 和 `POST /api/v1/intents/recognize` 也只返回空骨架，便于调用方保持接口连通。

### testing-agent

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

提交生成结果给 `testing-agent`：

```bash
curl -X POST http://localhost:8003/api/v1/evaluations/submissions \
  -H "Content-Type: application/json" \
  -d '{
	    "id": "qa-001",
	    "question": "查询网络设备及其端口信息",
	    "generation_run_id": "run-001",
	    "generation_status": "generated",
	    "generated_cypher": "",
	    "input_prompt_snapshot": "{\"schema_version\":\"cga_io_stub_v1\",\"trace_id\":\"run-001\",\"input\":{\"id\":\"qa-001\",\"question\":\"查询网络设备及其端口信息\"},\"output\":{\"generated_cypher\":\"\"},\"internal_flow\":{}}"
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

### cypher-generator-agent 环境变量

- `CYPHER_GENERATOR_AGENT_HOST`
- `CYPHER_GENERATOR_AGENT_PORT`
- `CYPHER_GENERATOR_AGENT_TESTING_AGENT_URL`
- `CYPHER_GENERATOR_AGENT_REQUEST_TIMEOUT_SECONDS`
- 说明：该分支中 cypher-generator-agent 不读取知识包、RAG 或 LLM 配置。

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
- `REPAIR_SERVICE_KNOWLEDGE_AGENT_REPAIRS_APPLY_URL`
- `REPAIR_SERVICE_KNOWLEDGE_AGENT_REPAIRS_APPLY_CAPTURE_DIR`
- `REPAIR_SERVICE_KNOWLEDGE_AGENT_REPAIRS_APPLY_MAX_ATTEMPTS`
- `REPAIR_SERVICE_LLM_ENABLED`
- `REPAIR_SERVICE_LLM_BASE_URL`
- `REPAIR_SERVICE_LLM_API_KEY`
- `REPAIR_SERVICE_LLM_MODEL_NAME`
- 说明：该服务默认要求启用 LLM，缺少关键配置会直接启动失败。

## 维护说明

- `cypher-generator-agent` 不执行 TuGraph；执行职责由 `testing-agent` 承担。
- `cypher-generator-agent` 当前只保留输入/输出骨架，不包含自然语言理解、语义解析、Cypher 编译或 LLM 调用。
- 跨服务成功 submission 契约依赖 `id + question + generation_run_id + generation_status + generated_cypher + input_prompt_snapshot`。
- 非成功输出统一使用 `CgaGenerationNonSuccessReport`，覆盖 `clarification_required`、`generation_failed` 和 `service_failed`。
- `input_prompt_snapshot` 保存 `cga_io_stub_v1` 最小 I/O trace。
