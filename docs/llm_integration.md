# Query Generator LLM Integration

查询语句生成服务现在已经支持两种模式：

- `heuristic_fallback`
  - 默认模式
  - 不需要 API Key
  - 使用 `network_schema_v10` 的 schema-aware 启发式规则生成 Cypher
- `llm`
  - 需要配置真实大模型
  - 当前接入方式是 `OpenAI-compatible /chat/completions`

## 配置方式

在项目根目录 `.env` 中填写：

```env
QUERY_GENERATOR_LLM_ENABLED=true
QUERY_GENERATOR_LLM_PROVIDER=openai_compatible
QUERY_GENERATOR_LLM_BASE_URL=https://your-openai-compatible-endpoint/v1
QUERY_GENERATOR_LLM_API_KEY=your_api_key
QUERY_GENERATOR_LLM_MODEL=your_model_name
QUERY_GENERATOR_LLM_TEMPERATURE=0.1
```

## 请求格式

查询生成服务会向：

- `POST {QUERY_GENERATOR_LLM_BASE_URL}/chat/completions`

发送 OpenAI 兼容请求，核心字段包括：

```json
{
  "model": "your_model_name",
  "temperature": 0.1,
  "messages": [
    {"role": "system", "content": "..."},
    {"role": "user", "content": "..."}
  ]
}
```

## Prompt 设计

Prompt 中会携带：
- `network_schema_v10` 的完整 schema context
- 当前自然语言问题
- 调用方传入的 schema hint
- 当前 attempt 次数
- 历史反馈摘要

模型被要求：
- 只生成一个 TuGraph 可执行的 Cypher
- 只使用 schema 中真实存在的 label / property / edge
- 返回 JSON：

```json
{
  "cypher": "MATCH ...",
  "notes": "..."
}
```

## 自动回退

如果出现以下任一情况，服务会自动回退到启发式生成：
- `QUERY_GENERATOR_LLM_ENABLED=false`
- 缺少 `base_url`
- 缺少 `api_key`
- 缺少 `model`
- 调用 LLM 接口时报错

## 状态检查

可以查看当前生成器状态：

```bash
curl http://127.0.0.1:8000/api/v1/generator/status
```

返回示例：

```json
{
  "llm_enabled": false,
  "llm_provider": "openai_compatible",
  "llm_base_url": null,
  "llm_model": null,
  "llm_configured": false,
  "active_mode": "heuristic_fallback",
  "schema_context": "network_schema_v10"
}
```
