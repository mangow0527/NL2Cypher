# Graph Cypher Generation Development IR

> 日期：2026-05-27
> 状态：开发 IR v1
> 适用分支：`cypher-generation-osi`
> IR 含义：Implementation Roadmap / Implementation Requirements

## 1. 目标

本文档把 Graph Semantic Model 驱动的 Cypher 生成整体架构拆成可开发、可验收、可测试的实施单元。

目标：

- 从当前 I/O stub 演进到完整的 graph-native Cypher generation pipeline。
- 当前默认目标数据库为 TuGraph，schema 事实来源是 `services/testing_agent/docs/reference/schema.json`。
- CGA 默认消费的 Graph Semantic Model 语料是 `services/cypher_generator_agent/tests/fixtures/tugraph_network_graph_model.yaml`。
- CGA 默认消费的静态 literal 语料是 `services/cypher_generator_agent/tests/fixtures/tugraph_value_index.json`，它不是在线 value-index 服务。
- 保持 cypher-generator-agent 不连接 TuGraph、不执行 Cypher 的边界。
- 让每个 IR 都能独立开发、独立测试、独立提交。
- 在引入 LLM 前，优先建立确定性底座、schema 契约、fixture 和自校验防线。
- 为后续 sprint plan、subagent task 或工程排期提供稳定输入。

非目标：

- 本 IR 不定义数据库执行、结果解释、空结果分析或 runtime repair。
- 本 IR 不要求一次实现所有 query shape；v1 可以按 MVP slice 逐步打开能力。
- 本 IR 不允许以 LLM 直接生成 Cypher 作为捷径。
- 本 IR 不覆盖 UI 或 runtime console 展示细节，只规定 trace 和输出字段。
- v1 不集成 value-index 服务。LiteralResolver 只消费随模型发布的静态 `value_index` 文件；这意味着 v1 上线后新写入的实体，例如新增设备 ID、新建服务名，必须等到下一次模型和 value index 发布后才能被识别。该约束需要在产品文档和用户引导中明确告知。

## 2. 当前起点

当前 `services/cypher_generator_agent` 只保留 I/O stub：

```text
services/cypher_generator_agent/
  app/api/main.py
  app/api/models.py
  app/api/service.py
  app/infrastructure/clients.py
  app/infrastructure/config.py
  tests/test_input_output_stub_contract.py
```

现有行为：

- `/api/v1/qa/questions` 接收 QA question，向 testing-agent 提交空 Cypher。
- `/api/v1/semantic/parse` 返回空 Cypher skeleton。
- `/api/v1/intents/recognize` 返回空 intent skeleton。
- trace schema 是 `cga_io_stub_v1`，`internal_flow` 为空。

开发约束：

- 早期实现必须保留当前 I/O contract，直到新 contract 有测试覆盖并和 testing-agent 对齐。
- 不能引入数据库连接配置。
- 不能提交运行时执行、EXPLAIN、dry-run、probe query 逻辑。
- 每个新增模块必须有独立单元测试，避免把 pipeline 全部堆进 `api/service.py`。

## 3. 建议代码分层

后续实现建议拆成以下目录。实际实现可以微调名称，但职责边界不应漂移。

```text
services/cypher_generator_agent/app/
  api/
    main.py                         # FastAPI endpoints，只做 request/response 适配
    models.py                       # API-level Pydantic models
    service.py                      # Workflow orchestration thin layer

  core/
    pipeline.py                     # CGA generation pipeline orchestration
    result.py                       # generated / clarification / unsupported / failed result models
    errors.py                       # stable error codes and severity

  semantic_model/
    model.py                        # GraphSemanticModel, VertexDefinition, EdgeDefinition, PropertyDefinition
    loader.py                       # load model, checksum, validator orchestration
    validator.py                    # model-level structural validation
    registry.py                     # lookup APIs for vertex/edge/property/metric/path_pattern
    fixture_loader.py               # tests and local fixture support

  decomposition/
    models.py                       # question_decomposition_v1
    decomposer.py                   # LLM-backed or deterministic decomposer interface
    prompt.py                       # structured prompt templates
    coverage_terms.py               # substantive/stopword/modality/time/unparsed classification helpers

  retrieval/
    index.py                        # graph semantic indices
    retriever.py                    # candidate retrieval by vertex/edge/property/metric/path_pattern
    scoring.py                      # match_type, score, evidence normalization

  literals/
    models.py                       # literal_resolver_request_v1 / result_v1
    resolver.py                     # exact, synonym, typed, fuzzy, value index resolution pipeline
    value_index.py                  # local value index and cache abstraction
    typed_parser.py                 # datetime, numeric, capacity, percentage parsing

  understanding/
    models.py                       # grounded LLM structured output schema
    llm_client.py                   # LLM provider protocol
    grounded_understanding.py       # bounded candidate selection

  binding/
    models.py                       # binding plan models
    binder.py                       # LLM output -> stable binding plan

  validation/
    semantic_validator.py           # coverage, endpoint, direction, owner, metric, DSL support
    coverage.py                     # coverage report builder

  dsl/
    models.py                       # restricted_query_dsl_v1
    builder.py                      # binding plan -> DSL
    parser.py                       # DSL JSON Schema / AST normalization
    ast.py                          # normalized AST models

  compiler/
    compiler.py                     # AST -> Cypher
    templates.py                    # query shape templates
    projection.py                   # RETURN/order/limit shaping helpers

  cypher_validation/
    models.py                       # cypher_self_validation_request_v1/result_v1
    parser.py                       # openCypher parser adapter
    readonly.py                     # read-only whitelist and forbidden clause checks
    schema_reference.py             # label/edge/property/type checks
    shape.py                        # DSL projection and final RETURN consistency
    dialect.py                      # TuGraph static subset allowlist
    validator.py                    # public CypherSelfValidator facade

  repair/
    models.py                       # repair_controller_input_v1 / decision_v1
    fingerprint.py                  # canonical state + sha256
    controller.py                   # repair / ask_user / unsupported / failed decisions
    notices.py                      # assumption -> user-visible notice rendering

  observability/
    trace.py                        # cga_graph_trace_v1 builder
    stages.py                       # stage constants and helpers
    metrics.py                      # metric naming and count granularity

  infrastructure/
    clients.py                      # outbound testing-agent and future LLM client adapters
    config.py                       # settings, no DB config
```

`understanding/` 和 `binding/` 的拆分是初始建议，不是硬性边界。IR-09 启动前必须做一次边界复核：如果 grounded understanding 输出到 binding plan 只是字段重命名和类型规范化，应合并为 `binding/binder.py`，减少一层 1:1 模块；只有当 LLM 输出需要保留原始候选选择、置信证据、schema retry 证据，并且 binding plan 需要承担独立的稳定领域模型时，才保留两层。

测试建议：

```text
services/cypher_generator_agent/tests/
  fixtures/
    network_topology_graph_model.yaml
    value_index.json
    questions.yaml
  semantic_model/
  decomposition/
  retrieval/
  literals/
  binding/
  validation/
  dsl/
  compiler/
  cypher_validation/
  repair/
  observability/
  integration/
```

## 4. 开发原则

1. 确定性优先：model loader、registry、DSL parser、compiler、self-validation 必须先于 LLM 主路径完成。
2. LLM 输出必须结构化：所有 LLM stage 都要 JSON Schema 校验，失败只允许有限重试。
3. 不静默吞语义：`substantive_terms.uncovered` 和 `unparsed_terms.unresolved` 不能生成 Cypher。
4. 不绕过 DSL：`unsupported_query_shape` 不允许 fallback 到 raw Cypher。
5. 不连接数据库：CGA 内没有 TuGraph client，没有 live lookup，没有 EXPLAIN。
6. trace 是一等产物：每个 IR 都必须补对应 stage trace 或明确不产生 stage。
7. fixture 先行：每个例子都应能被 `network_topology_graph_model.yaml` 和 value index 校验。
8. 小步提交：每个 IR 完成后提交一次，避免跨层大爆炸。

## 4.1 估算与角色标签

估算用于 sprint planning，不是承诺工时：

| 估算 | 含义 |
| --- | --- |
| XS | 0.5-1 天，局部模型、契约或测试 |
| S | 1-3 天，单一模块或薄集成 |
| M | 3-6 天，多个文件和较完整测试 |
| L | 1-2 周，跨模块功能或复杂校验 |
| XL | 2 周以上，需要拆分或 spike |

角色标签：

| 角色 | 主要职责 |
| --- | --- |
| backend | Python service、Pydantic model、pipeline、compiler、validator |
| LLM | prompt、structured output、schema retry、候选约束 |
| infra | 配置、CI、testing-agent 对接、trace/metrics、发布边界 |
| QA | fixture、golden tests、回归矩阵 |

本 IR 的 sprint 容量估算默认团队规模为 2-3 名 backend、0.5 名 LLM、0.5 名 infra、0.5 名 QA。团队规模不同，需要按关键路径和角色可用性调整 sprint 承诺，不应机械照搬每个 sprint 的 IR 数量。

## 5. MVP 分层

### MVP-0：确定性底座

目标：不接 LLM，也能加载模型、校验模板、解析 DSL、编译和自校验简单查询。

包含：

- IR-00 Project Contract Baseline
- IR-01 Graph Model Fixture
- IR-02 Graph Model Loader / Registry
- IR-03a Cypher Self-Validation MVP
- IR-04 Restricted DSL Models / Parser
- IR-05 Cypher Compiler MVP
- IR-06 Observability Skeleton

### MVP-1：无 LLM 的端到端 happy path

目标：用测试中的 mock decomposition / mock understanding 跑通 `Service -> Tunnel` 和 `tunnel_full_path`。

包含：

- IR-07 LiteralResolver MVP
- IR-08 Candidate Retriever MVP
- IR-09 Semantic Binder MVP
- IR-10 Semantic Validator MVP
- IR-11 DSL Builder MVP
- IR-12 Pipeline Orchestrator MVP
- SP-01 LLM Feasibility Spike

### MVP-2：LLM 受控接入

目标：接入 Question Decomposer 和 Grounded Understanding，但每一步都有 schema、候选边界和 repair。

包含：

- IR-13 Question Decomposer
- IR-14 Grounded LLM Understanding
- IR-15 Repair / Clarification Controller
- IR-16 Full Trace and Testing-Agent Contract

### MVP-3：查询形态扩展

目标：逐步支持 v1 DSL 的完整子集。

包含：

- IR-03b Cypher Self-Validation Full
- IR-17 Variable Path Traversal
- IR-18 Metric / Ad Hoc Aggregate
- IR-19 Top-N and Two-Step Aggregate
- IR-20 Golden Test Regression Matrix

## 6. IR 详细清单

### IR-00 Project Contract Baseline

目标：为 graph-native generation pipeline 建立稳定入口、结果状态和错误码，不破坏当前 I/O stub。

依赖：无。
估算：S。
角色：backend、infra。

建议文件：

- 修改 `services/cypher_generator_agent/app/api/models.py`
- 修改 `services/cypher_generator_agent/app/api/service.py`
- 新建 `services/cypher_generator_agent/app/core/result.py`
- 新建 `services/cypher_generator_agent/app/core/errors.py`
- 测试 `services/cypher_generator_agent/tests/integration/test_api_contract.py`

输入：

- `QAQuestionRequest(id, question)`
- `SemanticParseRequest(id?, question, generation_run_id?)`

输出状态：

- `generated`
- `clarification_required`
- `unsupported_query_shape`
- `generation_failed`
- `service_failed`

开发内容：

- 定义 `GenerationOutput`，包含 `status`、`cypher`、`dsl`、`trace`、`clarification`、`failure`、`user_visible_notices`。
- 兼容当前 testing-agent submission contract：generated 时提交 `GeneratedCypherSubmissionRequest`，非成功时提交 `CgaGenerationNonSuccessReport`。
- 将现有 `submitted_to_testing` 作为 API 内部提交状态，和 generation final status 分开。
- 扩展 failure reason：`cypher_syntax_invalid`、`cypher_readonly_violation`、`cypher_schema_reference_invalid`、`compiler_shape_mismatch`、`target_dialect_static_error`、`unsupported_query_shape`、`coverage_failure`、`literal_unresolved`、`repair_binding_oscillation`。

验收：

- 现有 I/O stub 测试继续通过。
- `/api/v1/semantic/parse` 能返回 graph trace skeleton，但不要求生成真实 Cypher。
- 非成功状态的 response 不包含空 Cypher 冒充成功。
- 没有数据库配置项。

测试样例：

- `generation_failed` 必须有 failure reason。
- `clarification_required` 必须有 clarification。
- `unsupported_query_shape` 必须有 unsupported reason 或 suggested rewrites。
- `generated` 必须有 non-empty Cypher、DSL 和 trace。

### IR-01 Graph Model Fixture

目标：建立一份真实可测的 network topology graph semantic model fixture 和 Golden Test Set v1，作为所有后续测试的共同事实来源。

依赖：IR-00 可并行。
估算：M。
角色：QA、backend。

建议文件：

- 新建 `services/cypher_generator_agent/tests/fixtures/network_topology_graph_model.yaml`
- 新建 `services/cypher_generator_agent/tests/fixtures/value_index.json`
- 新建 `services/cypher_generator_agent/tests/fixtures/questions.yaml`
- 新建 `services/cypher_generator_agent/tests/fixtures/golden_questions.yaml`
- 测试 `services/cypher_generator_agent/tests/fixtures/test_fixture_consistency.py`

Fixture 必须包含：

- vertices：`NetworkElement`、`Tunnel`、`Service`、`Port`
- edges：`SERVICE_USES_TUNNEL`、`PATH_THROUGH`、`TUNNEL_SRC`、`TUNNEL_DST`、`HAS_PORT`
- properties：见 `Network Topology Vocabulary`
- metrics：`device_count`、`port_count`、`service_count`
- path_patterns：`tunnel_full_path`
- value synonyms：`firewall -> ["防火墙", "FW"]`、`GOLD -> ["Gold", "金牌"]`
- value index：`ne-0001`、`tun-mpls-001`、`svc-gold-001` 等稳定 ID

Golden Test Set v1 必须先建成 fixture，不等到 IR-20：

- 至少 26 个用例。
- 每条用例声明 `id`、`question`、`expected_status`、`primary_ir`、`expected_reason_code`。
- generated 用例可以先不填完整 expected Cypher，但必须声明将由哪个 IR 补齐 expected DSL/Cypher。
- non-success 用例必须从一开始声明 failure / clarification / unsupported 的原因。
- IR-05、IR-10、IR-15 等后续 IR 的验收必须引用这里的用例，而不是临时再写一套一次性问题。

开发内容：

- 将文档 vocabulary 转为可加载 YAML fixture。
- 编写 fixture consistency 测试，确保 edge endpoint、property owner、metric dimensions、path_pattern 参数一致。
- 建立 Golden Test Set v1 question corpus，覆盖单跳、path pattern、literal、coverage failure、unsupported query、repair oscillation、readonly violation、shape mismatch。
- 明确 `value_index.json` 是 v1 静态输入，不代表已实现 value-index 服务。

验收：

- fixture 中所有 `value_synonyms` key 都存在于 `valid_values`。
- fixture 中没有非 vocabulary 的服务隧道边短名。
- path_pattern `tunnel_full_path` 只使用 `PATH_THROUGH`，并返回 `device`、`hop`。
- golden question corpus 至少 26 条，每条都有 expected final status 和 primary IR。
- 新写入实体不在静态 `value_index.json` 时，测试应验证 LiteralResolver 后续返回 unresolved，而不是尝试 live lookup。

### IR-02 Graph Model Loader / Registry

目标：加载 Graph Semantic Model v1，校验结构，构建 graph semantic registry 和检索基础索引。

依赖：IR-01。
估算：M。
角色：backend。

建议文件：

- 新建 `app/semantic_model/model.py`
- 新建 `app/semantic_model/loader.py`
- 新建 `app/semantic_model/validator.py`
- 新建 `app/semantic_model/registry.py`
- 测试 `tests/semantic_model/test_loader.py`
- 测试 `tests/semantic_model/test_registry.py`

输入：

- YAML / dict graph semantic model。

输出：

- `GraphSemanticRegistry`
- `model_checksum`
- `GraphModelValidationResult`

开发内容：

- Pydantic model：`GraphSemanticModel`、`VertexDefinition`、`EdgeDefinition`、`PropertyDefinition`、`MetricDefinition`、`PathPatternDefinition`。
- structural validation：唯一性、edge endpoint、id_property、property owner、valid_values/value_synonyms、metric mutual exclusion。
- registry lookup API：
  - `get_vertex(name)`
  - `get_edge(name)`
  - `get_property(owner, name)`
  - `get_metric(name)`
  - `get_path_pattern(name)`
  - `edge_connects(edge_name, from_vertex, to_vertex, direction)`
  - `property_type(owner, property_name)`
- checksum：模型内容 canonical JSON 后 sha256。

验收：

- 合法 fixture 加载成功。
- unknown edge endpoint 拒绝加载。
- missing id_property 拒绝加载。
- invalid value_synonyms key 拒绝加载。
- registry lookup 对不存在对象返回 typed error，不抛裸 KeyError。

### IR-03a Cypher Self-Validation MVP

目标：实现 Sprint 0 可落地的 Cypher 静态校验最小防线，覆盖 syntax、readonly、最小 schema reference，足够支撑 IR-05 编译器 MVP。

依赖：IR-02。
估算：M。
角色：backend。

建议文件：

- 新建 `app/cypher_validation/models.py`
- 新建 `app/cypher_validation/parser.py`
- 新建 `app/cypher_validation/readonly.py`
- 新建 `app/cypher_validation/schema_reference.py`
- 新建 `app/cypher_validation/validator.py`
- 测试 `tests/cypher_validation/test_readonly.py`
- 测试 `tests/cypher_validation/test_schema_reference_mvp.py`

输入：

- `cypher_self_validation_request_v1`
- registry
- optional source kind：`compiled_query | path_pattern | metric_full_cypher`

输出：

- `cypher_self_validation_result_v1`

开发内容：

- syntax check MVP：优先接入现成 openCypher parser；如果选型未完成，先实现保守 clause tokenizer，只接受 v1 compiler 会生成的 `MATCH/WHERE/RETURN/WITH/ORDER BY/LIMIT` 子集，并把 parser adapter 接口固定下来。
- readonly check：白名单 `MATCH/WHERE/WITH/RETURN/ORDER BY/LIMIT/SKIP/UNWIND`；禁止 `CREATE/MERGE/SET/DELETE/DETACH DELETE/REMOVE/CALL/LOAD CSV/FOREACH`。
- 最小 schema reference：校验 node label 和 edge type 是否存在；校验 map literal 中的 property 是否属于已知 owner；校验简单 `var.property` 是否能回溯到当前 MATCH 里的 vertex/edge。
- 返回统一 failure code：`cypher_syntax_invalid`、`cypher_readonly_violation`、`cypher_schema_reference_invalid`。
- 为 IR-03b 预留 `shape`、`dialect`、`model_artifact` check slot，但 Sprint 0 不要求实现 full logic。

验收：

- `MATCH (ne:NetworkElement) RETURN ne.id AS id` 通过。
- `MATCH (ne:NetworkElement) SET ne.name = "x" RETURN ne` 返回 `cypher_readonly_violation`。
- `MATCH (x:UnknownLabel) RETURN x` 返回 `cypher_schema_reference_invalid`。
- `MATCH (ne:NetworkElement) RETURN ne.unknown_property AS x` 返回 `cypher_schema_reference_invalid`。
- 多语句或分号拼接被拒绝。

### IR-03b Cypher Self-Validation Full

目标：补完完整 Cypher Self-Validation 规则，包括 compiler shape、target dialect、model artifact 加载期校验和更完整的 property type/operator 校验。

依赖：IR-03a、IR-04、IR-05。
估算：L。
角色：backend。

建议文件：

- 修改 `app/cypher_validation/parser.py`
- 修改 `app/cypher_validation/schema_reference.py`
- 新建 `app/cypher_validation/shape.py`
- 新建 `app/cypher_validation/dialect.py`
- 修改 `app/cypher_validation/validator.py`
- 修改 `app/semantic_model/loader.py`
- 测试 `tests/cypher_validation/test_shape.py`
- 测试 `tests/cypher_validation/test_dialect.py`
- 测试 `tests/cypher_validation/test_model_artifact_validation.py`

开发内容：

- shape check：RETURN alias 与 DSL projection 顺序一致；limit/order 不超过 DSL AST；最终 RETURN 不暴露 DSL 未声明列。
- dialect check：禁止 optional match、union、procedure、unbounded variable path、动态 label/type/property、未在 allowlist 的函数。
- schema reference full：校验 edge endpoint/direction、property type/operator compatibility、aggregate function/type compatibility。
- model artifact validation：`path_pattern.cypher` 和 `metric.full_cypher` 在 model loader 阶段调用 self-validation，并按 model checksum 缓存结果。
- parser adapter 选型定案：如果 Sprint 0 使用保守 tokenizer，本 IR 必须替换为 openCypher parser adapter 或给出保守 parser 的覆盖证明。

验收：

- DSL projection 为 `device, hop` 但 Cypher 返回 `ne` 时返回 `compiler_shape_mismatch`。
- `MATCH p=(a)-[*]->(b) RETURN p` 返回 `target_dialect_static_error`。
- path_pattern 模板含 `SET` 时模型加载失败。
- `avg(NetworkElement.name)` 这类 string property 数值聚合失败。
- `SERVICE_USES_TUNNEL` 方向或 endpoint 与 MATCH pattern 不一致时失败。

### IR-04 Restricted DSL Models / Parser

目标：实现 `restricted_query_dsl_v1` 的 Pydantic model、JSON Schema 校验和 AST 规范化。

依赖：IR-02。
估算：M。
角色：backend。

建议文件：

- 新建 `app/dsl/models.py`
- 新建 `app/dsl/ast.py`
- 新建 `app/dsl/parser.py`
- 测试 `tests/dsl/test_parser.py`
- 测试 `tests/dsl/test_operation_sequences.py`

输入：

- DSL dict / JSON。

输出：

- `RestrictedQueryAst`

开发内容：

- query_shape enum：`vertex_lookup`、`single_hop_traversal`、`variable_path_traversal`、`named_path_pattern`、`metric_aggregate`、`ad_hoc_aggregate`、`top_n`、`two_step_aggregate`。
- op enum：`traverse_edge`、`variable_path`、`use_path_pattern`、`metric_aggregate`、`aggregate`、`sort`、`limit`、`subquery`、`filter_subquery`。
- enforce op sequence grid。
- normalize references：role alias、target/property、projection source、sort source。
- reject raw Cypher attributes：`raw_cypher`、`cypher_fragment`、`where_text`。

验收：

- 单跳 DSL 解析成功。
- `named_path_pattern` DSL 引用 unknown path_pattern 失败。
- `two_step_aggregate` 中 nested subquery 失败。
- `top_n` 缺少 limit 失败。
- `dimension: ne.elem_type` 字符串简写失败。

### IR-05 Cypher Compiler MVP

目标：从 AST 模板化生成 v1 Cypher 子集，不允许 LLM 直接生成 Cypher。

依赖：IR-03a、IR-04。
估算：M。
角色：backend。

建议文件：

- 新建 `app/compiler/compiler.py`
- 新建 `app/compiler/templates.py`
- 新建 `app/compiler/projection.py`
- 测试 `tests/compiler/test_single_hop.py`
- 测试 `tests/compiler/test_named_path_pattern.py`
- 测试 `tests/compiler/test_readonly_output.py`

MVP 支持：

- `vertex_lookup`
- `single_hop_traversal`
- `named_path_pattern`

开发内容：

- 生成参数化 Cypher，不把 literal 直接拼进字符串。
- 编译后立即调用 Cypher Self-Validation。
- path_pattern 编译只实例化已校验模板和参数，不允许修改模板内部 Cypher。
- final RETURN alias 必须来自 DSL projection。

验收：

- Gold 服务使用隧道生成：

```cypher
MATCH (svc:Service)-[:SERVICE_USES_TUNNEL]->(tun:Tunnel)
WHERE svc.quality_of_service = $quality_of_service
RETURN tun.id AS tunnel_id
```

- `tunnel_full_path` 生成使用 fixture 中 path_pattern 模板。
- 编译输出包含 `parameters`，而不是把 `GOLD` 写死到 Cypher。
- compiler 输出全部通过 IR-03a 自校验；shape/dialect 深度校验在 IR-03b 补齐。

### IR-06 Observability Skeleton

目标：实现 `cga_graph_trace_v1` 的基础 trace builder，后续每个 stage 都能追加结构化证据。

依赖：IR-00。
估算：S。
角色：infra、backend。

建议文件：

- 新建 `app/observability/trace.py`
- 新建 `app/observability/stages.py`
- 新建 `app/observability/metrics.py`
- 测试 `tests/observability/test_trace_builder.py`

开发内容：

- trace 顶层：`trace_schema_version`、`trace_id`、`question_id`、`generation_run_id`、`source_question`、timestamps、`final_status`、semantic model info。
- stage model：`stage`、`status`、`duration_ms`、`input_ref`、`output_ref`、`metrics`、`errors`、`warnings`。
- 支持 artifact redaction placeholder，但 v1 可以全部 inline 小对象。
- final outputs：DSL、Cypher、clarification、user_visible_notices、failure。

验收：

- 每个 generated / failed / clarification output 都带 trace。
- trace stage enum 不允许自由字符串。
- final_status 与 API result status 一致。
- CGA trace 不记录数据库连接或执行结果。

### IR-07 LiteralResolver MVP

目标：独立实现字面值解析，不依赖 Candidate Retriever 内部策略，不连接数据库。

依赖：IR-01、IR-02、IR-06。
估算：M。
角色：backend。

建议文件：

- 新建 `app/literals/models.py`
- 新建 `app/literals/resolver.py`
- 新建 `app/literals/value_index.py`
- 新建 `app/literals/typed_parser.py`
- 测试 `tests/literals/test_enum_resolution.py`
- 测试 `tests/literals/test_id_resolution.py`
- 测试 `tests/literals/test_time_numeric_parse.py`

开发内容：

- 输入：`raw_literal`、`expected_vertex`、`expected_edge`、`expected_property`、`literal_kind_hint`。
- fixed resolution order：exact、value_synonym、typed_parse、fuzzy_text、embedding disabled by default、value_index_lookup。
- v1 只读取随模型发布的静态 `value_index.json` 或同等本地快照，不对接 value-index 服务。
- 高风险枚举不自动 fuzzy/embedding。
- ID 形态只允许 value index exact，不允许相近 ID 静默替换。
- alternatives 最多 3 个。

验收：

- “防火墙” + `NetworkElement.elem_type` -> `firewall`，match_type `value_synonym`。
- “ne-0001” + `NetworkElement.id` -> `ne-0001`，match_type `value_index_exact`。
- “ne-9999” 未在 value index 中 -> unresolved，不查数据库。
- “最近 7 天” -> typed time range 或 unresolved with clarification need，不能吞掉。

### IR-08 Candidate Retriever MVP

目标：基于 question decomposition 和 registry 召回语义候选，输出置信度、match_type 和 evidence。

依赖：IR-02、IR-06。
估算：S。
角色：backend。

建议文件：

- 新建 `app/retrieval/index.py`
- 新建 `app/retrieval/retriever.py`
- 新建 `app/retrieval/scoring.py`
- 测试 `tests/retrieval/test_candidate_retriever.py`

开发内容：

- vertex/edge/property/metric/path_pattern 召回。
- exact name、synonym、description token match。
- embedding 接口预留，但 MVP 可用 deterministic scorer。
- 返回候选时保留 `match_type=exact|synonym|text|embedding`、`score`、`evidence`。
- 不在 retriever 中自动纠错绑定；只提供候选。

验收：

- “服务” 召回 `Service`。
- “隧道” 召回 `Tunnel`。
- “用了” 召回 `SERVICE_USES_TUNNEL`。
- “经过” 召回 `PATH_THROUGH` 和 `tunnel_full_path`，并带不同 evidence。
- 候选分数接近时不自行选择。

### IR-09 Semantic Binder MVP

目标：把 grounded understanding 输出变成稳定 binding plan，供 semantic validator 和 DSL builder 使用。

依赖：IR-02、IR-07、IR-08。
估算：M。
角色：backend、LLM。

启动前复核：

- 对比 `understanding` 输出 schema 和 binding plan schema。
- 如果两者只是字段重命名和类型规范化，合并 `understanding/grounded_understanding.py` 与 `binding/binder.py` 的实现职责，只保留一个 binder 模块。
- 如果仍保留两层，必须在本 IR 中写清楚两层的不可替代职责，并为两层分别保留测试。

建议文件：

- 新建 `app/binding/models.py`
- 新建 `app/binding/binder.py`
- 测试 `tests/binding/test_binder.py`

开发内容：

- 定义 binding plan：query_shape、vertex_bindings、edge_bindings、property_bindings、literal_bindings、metric_bindings、path_pattern_bindings、filters、projection、sort、limit、assumptions。
- 拒绝 LLM 输出中不在候选或 registry 中的 name。
- 将 LiteralResolver result 绑定到 filter value。
- 保留 unresolved literal 和 alternatives。

验收：

- Gold 服务使用隧道问题能绑定 `Service`、`SERVICE_USES_TUNNEL`、`Tunnel`、`Service.quality_of_service=GOLD`。
- LLM 输出 `NetworkDevice` 但候选无此项时失败，不做魔法改名。
- fuzzy 高置信结果进入 assumptions。

### IR-10 Semantic Validator MVP

目标：校验 binding plan 的语义正确性和 DSL 支持度。

依赖：IR-09。
估算：M。
角色：backend。

建议文件：

- 新建 `app/validation/semantic_validator.py`
- 新建 `app/validation/coverage.py`
- 测试 `tests/validation/test_coverage.py`
- 测试 `tests/validation/test_edge_endpoint.py`
- 测试 `tests/validation/test_dsl_support.py`

开发内容：

- coverage：substantive uncovered、time unresolved、unparsed unresolved。
- edge endpoint/direction：`SERVICE_USES_TUNNEL` 不能连接 `Service -> NetworkElement`。
- property owner：`Service.quality_of_service` 不能挂到 `Tunnel`。
- metric dimensions：metric_aggregate 的 group_by 必须在 valid_dimensions。
- DSL support：unsupported query shape 返回错误而不是继续生成。

验收：

- edge endpoint mismatch 返回 repairable error。
- coverage missing “增长” 返回 non-repairable ask_user/generation_failed。
- unsupported shortest path 返回 `unsupported_query_shape`。
- modality “应该” warning-only，并产生 assumption。

### IR-11 DSL Builder MVP

目标：从已通过语义校验的 binding plan 生成 Restricted DSL。

依赖：IR-04、IR-10。
估算：S。
角色：backend。

建议文件：

- 新建 `app/dsl/builder.py`
- 测试 `tests/dsl/test_builder_single_hop.py`
- 测试 `tests/dsl/test_builder_named_path_pattern.py`

开发内容：

- 支持 `single_hop_traversal`。
- 支持 `named_path_pattern`。
- 将 filters、projection、assumptions 写入 DSL。
- DSL 生成后立即调用 DSL Parser，确保 builder 不输出非法 DSL。

验收：

- Gold 服务使用隧道生成符合 DSL §5 的结构。
- `tunnel_full_path` 生成符合 DSL §7 的结构。
- DSL 中不出现 raw Cypher 字段。

### IR-12 Pipeline Orchestrator MVP

目标：把确定性组件串成无 LLM happy path，用 mock decomposer / mock understanding 完成端到端生成。

依赖：IR-05、IR-06、IR-07、IR-08、IR-09、IR-10、IR-11。
估算：M。
角色：backend、infra。

建议文件：

- 新建 `app/core/pipeline.py`
- 修改 `app/api/service.py`
- 测试 `tests/integration/test_pipeline_mvp.py`

开发内容：

- Orchestrator stage 顺序：model registry -> mock decomposition -> candidate retrieval -> literal resolver -> mock understanding -> binder -> validator -> DSL builder -> parser -> compiler -> self-validation -> output。
- 每个 stage 写 trace。
- generated output 可先沿用现有 testing-agent submission contract，但 trace 允许是过渡结构。
- non-success output 可先提交 generation failure endpoint，但完整 trace contract 由 IR-16 替换和收口。

验收：

- fixture 问题 “Gold 服务使用了哪些隧道” 端到端生成 Cypher。
- fixture 问题 “隧道 tun-mpls-001 经过哪些设备” 端到端生成 path_pattern Cypher。
- coverage failure 不生成 Cypher。
- CGA 仍不连接数据库。

过渡说明：

- IR-12 的 testing-agent 集成是端到端 smoke path，不是最终 contract。
- IR-16 必须替换 IR-12 的过渡提交逻辑，使 generated 和 non-success 都统一使用 `cga_graph_trace_v1`。

### SP-01 LLM Feasibility Spike

目标：在完整 LLM 接入前，用 2-3 天验证 Question Decomposer 和 Grounded Understanding 的 prompt 可行性，避免 Sprint 3 才暴露 prompt/schema 风险。

依赖：IR-01，可与 IR-08 后续验证对齐。
估算：S，time-box 2-3 天。
角色：LLM、backend。

开发内容：

- 选定 v1 LLM provider 候选，例如 OpenAI、Anthropic 或自建模型。
- 用 Golden Test Set v1 中 5 个真实问题跑 Question Decomposer prompt。
- 用同一批问题和手工编排的候选集合跑 Grounded Understanding prompt；不要求真实 Candidate Retriever 已完成。
- 记录 schema failure rate、term classification accuracy、candidate invention rate、平均 token usage。
- 输出 spike report，不接入主 pipeline，不阻塞确定性底座开发。

验收：

- 5 个问题都有原始 prompt、模型输出、schema 校验结果。
- schema failure rate、classification miss、candidate invention 都有记录。
- 如果 candidate invention 或 schema failure 明显偏高，Sprint 3 前必须调整 prompt 或降级策略。

### IR-13 Question Decomposer

目标：接入真实 Question Decomposer，让自然语言先变成领域无关结构化问题。

依赖：IR-06、IR-12。
估算：M。
角色：LLM、backend。

建议文件：

- 新建 `app/decomposition/models.py`
- 新建 `app/decomposition/decomposer.py`
- 新建 `app/decomposition/prompt.py`
- 新建 `app/decomposition/coverage_terms.py`
- 测试 `tests/decomposition/test_term_classification.py`
- 测试 `tests/decomposition/test_schema_retry.py`

开发内容：

- 结构化输出 schema：`question_decomposition_v1`。
- 分类：substantive、stopword、modality、time、unparsed。
- schema violation 最多重试 2 次。
- 输入缺少指代对象时进入 Input Clarification Gate。
- LLM client 用 protocol，测试中使用 fake client。
- LLM provider 不可用时返回 `service_failed`，trace 中记录 provider、错误类型、重试次数；不降级为自由文本或 deterministic 猜测。

验收：

- “麻烦帮我查一下 Gold 服务” 中礼貌词进入 stopword。
- “大概有多少防火墙” 中“大概”进入 modality。
- “最近 down 的端口” 中“最近”进入 time。
- “收入增长情况” 中“增长”进入 substantive，不允许丢失。

### IR-14 Grounded LLM Understanding

目标：在候选集合内让 LLM 做受控语义选择，输出结构化 grounded understanding。

依赖：IR-08、IR-13。
估算：M。
角色：LLM、backend。

建议文件：

- 新建 `app/understanding/models.py`
- 新建 `app/understanding/llm_client.py`
- 新建 `app/understanding/grounded_understanding.py`
- 测试 `tests/understanding/test_grounded_schema.py`
- 测试 `tests/understanding/test_candidate_boundaries.py`

开发内容：

- 输入只包含 question decomposition、top candidates、literal resolver results。
- 输出必须引用 candidate id 或 registry name。
- schema invalid 最多重试 2 次。
- 输出引用不存在 candidate 时失败，交给 Repair Controller 或 generation_failed。
- LLM provider 不可用时返回 `service_failed`，并保留 candidate retrieval 和 literal resolver trace，方便复盘。

验收：

- LLM 选择 `SERVICE_USES_TUNNEL` 时 binder 成功。
- LLM 发明非 vocabulary 的服务隧道边短名时被拒绝。
- 多候选接近时保留 ambiguity，不强行决定。

### IR-15 Repair / Clarification Controller

目标：实现 repair loop、clarification、unsupported、generation_failed 决策。

依赖：IR-10、IR-14。
估算：M。
角色：backend、LLM。

建议文件：

- 新建 `app/repair/models.py`
- 新建 `app/repair/fingerprint.py`
- 新建 `app/repair/controller.py`
- 新建 `app/repair/notices.py`
- 测试 `tests/repair/test_decision_matrix.py`
- 测试 `tests/repair/test_fingerprint.py`
- 测试 `tests/repair/test_assumption_notices.py`

开发内容：

- max repair attempts = 3。
- canonical state fingerprint。
- oscillation detection：新 fingerprint 命中过去任一轮即停止。
- `continue_with_assumption` 输出 assumptions，notice 由模板派生。
- clarification 最多 3 个选项，单轮只问一个问题。
- unsupported 不走 raw Cypher。

验收：

- edge endpoint mismatch 进入 repair。
- A -> B -> A 震荡返回 `repair_binding_oscillation`。
- fuzzy literal 高置信继续，但派生 notice。
- ambiguous top2 gap < 0.10 反问用户。

### IR-16 Full Trace and Testing-Agent Contract

目标：将 IR-12 的过渡性 testing-agent 提交逻辑替换为完整 `cga_graph_trace_v1` contract，统一 generated 和 non-success 输出。

依赖：IR-06、IR-12、IR-15。
估算：M。
角色：infra、backend。

建议文件：

- 修改 `app/api/service.py`
- 修改 `app/infrastructure/clients.py` 如需补充 non-success path 测试
- 测试 `tests/integration/test_testing_agent_submission.py`
- 测试 `tests/observability/test_trace_contract.py`

开发内容：

- generated：提交 generated Cypher 和 trace JSON string。
- clarification：提交 non-success report，带 clarification 和 trace。
- unsupported：提交 non-success report，failure reason 或 status 清晰区分。
- generation_failed：提交 non-success report，带 self-validation / validator error。
- service_failed：只用于工程异常，例如 model unavailable 或 LLM provider failure。

验收：

- generated submission 的 `input_prompt_snapshot` 是 `cga_graph_trace_v1`。
- clarification 不包含 parsed Cypher。
- generation_failed 不包含 clarification。
- LLM provider failure 提交 `service_failed`，trace 中有 provider 异常 stage。
- testing-agent client retry 行为不吞掉最终失败。

### IR-16.5 Performance Baseline

目标：在完整 trace contract 后建立性能和 token 基线，不设 SLO，只拿到可比较的数据。

依赖：IR-16。
估算：S。
角色：infra、QA。

建议文件：

- 新建 `services/cypher_generator_agent/tests/integration/test_performance_baseline.py`
- 新建 `services/cypher_generator_agent/tests/fixtures/performance_baseline_cases.yaml`
- 修改 `app/observability/metrics.py`

开发内容：

- 跑 Golden Test Set v1 的 generated 和 non-success 子集。
- 记录每个 stage latency、总 latency、LLM call count、schema retry count、token usage。
- 输出 baseline artifact 到 `reports/baseline_YYYYMMDD.json`；CI 可作为 artifact 保存，发布前由 infra/QA 手动对比关键指标变化。
- 不在此 IR 中做性能优化。

验收：

- baseline artifact 包含 p50/p95 latency、LLM call count、token usage。
- trace 中每个 stage 都有 duration。
- CI 可选择只跑小样本；完整 baseline 可作为 nightly 或手动任务。
- PR 不因 baseline 数值波动自动失败，除非后续单独定义 SLO。

### IR-17 Variable Path Traversal

目标：支持受限变长路径查询，例如“找出所有经过设备 ne-0001 的隧道”。

依赖：IR-12。
估算：M。
角色：backend。

建议文件：

- 修改 `app/dsl/models.py`
- 修改 `app/dsl/builder.py`
- 修改 `app/compiler/templates.py`
- 修改 `app/cypher_validation/dialect.py`
- 测试 `tests/integration/test_variable_path.py`

开发内容：

- DSL `variable_path` op。
- 必须要求 `allowed_edges` 非空。
- 必须要求 `max_hops` 有上界，默认不超过 8。
- compiler 输出有界 path。
- self-validation 拦截无上界 path。

验收：

- `max_hops=8` 通过。
- `max_hops=null` 或 `*1..` 被拒绝。
- through filter `NetworkElement.id=ne-0001` 正确进入 WHERE。

### IR-18 Metric / Ad Hoc Aggregate

目标：支持 metric_aggregate 和 ad_hoc_aggregate。

依赖：IR-12。
估算：M。
角色：backend。

建议文件：

- 修改 `app/dsl/models.py`
- 修改 `app/dsl/builder.py`
- 修改 `app/compiler/templates.py`
- 修改 `app/validation/semantic_validator.py`
- 测试 `tests/integration/test_aggregate.py`

开发内容：

- metric `device_count` by `NetworkElement.elem_type`。
- ad hoc count `Port.id` by `Port.status`。
- group_by 使用 `target + property`，不允许 `dimension: ne.elem_type` 简写。
- aggregate function/type compatibility。

验收：

- “全网有多少台防火墙” 使用 `device_count`。
- “按状态统计端口数量” 使用 ad hoc aggregate。
- `avg` 用在 string property 上失败。
- metric group_by 不在 valid_dimensions 失败。

### IR-19 Top-N and Two-Step Aggregate

目标：支持“端口最多的 5 台设备”这类先聚合再排序限制的查询。

依赖：IR-18。
估算：L。
角色：backend。

建议文件：

- 修改 `app/dsl/models.py`
- 修改 `app/dsl/parser.py`
- 修改 `app/compiler/templates.py`
- 修改 `app/repair/fingerprint.py`
- 测试 `tests/integration/test_two_step_aggregate.py`

开发内容：

- `top_n`：aggregate/metric_aggregate + sort + limit。
- `two_step_aggregate`：subquery + optional filter_subquery + sort + limit。
- subquery fingerprint 递归生成。
- compiler 输出受限 WITH 链路，不使用 raw nested Cypher。

验收：

- “端口最多的 5 台设备” 生成 count + order desc + limit 5。
- subquery 缺 measures 失败。
- subquery nested subquery 失败。
- fingerprint 能区分 port_count 和 service_count。

### IR-20 Golden Test Regression Matrix

目标：将 IR-01 到 IR-19 中已经使用的 golden test 用例集中到统一 regression matrix 和 CI 自动化中，防止后续 LLM 或 compiler 改动破坏边界。

依赖：IR-12 以后持续补充，最终依赖 IR-19。
估算：M。
角色：QA、backend、infra。

建议文件：

- 新建 `tests/integration/test_golden_questions.py`
- 修改 `tests/fixtures/golden_questions.yaml`
- 新建 `tests/fixtures/expected_dsl/`
- 新建 `tests/fixtures/expected_cypher/`

测试类别：

- happy path：single_hop、named_path_pattern、variable_path、metric_aggregate、ad_hoc_aggregate、top_n、two_step_aggregate。
- coverage failure：“增长”无 metric 时不能生成普通收入查询。
- ambiguity：“端口”多候选接近时必须 clarification。
- literal unresolved：新 ID 未同步 value index 时不能假装存在。
- readonly safety：path_pattern 模板含 SET 时模型加载失败。
- DSL unsupported：shortest path、OPTIONAL MATCH、graph algorithm 返回 unsupported。
- shape mismatch：compiler RETURN 多列/少列被 self-validation 拦截。

验收：

- golden question 每条都有 expected status。
- 每条 golden question 都标记覆盖的 IR、query_shape、expected reason 和是否进入 CI smoke subset。
- generated case 校验 DSL AST 和 Cypher 结构，不只做字符串包含。
- non-success case 校验 reason_code、clarification options 或 unsupported reason。
- IR-01 已建立的 26 个用例全部纳入矩阵；本 IR 不重新发明另一套测试语料。
- 每次新增 query shape 必须新增或更新 golden question，并在 matrix 中标明。

## 7. 推荐开发顺序

```text
Sprint 0:
  IR-00 Project Contract Baseline
  IR-01 Graph Model Fixture
  IR-02 Graph Model Loader / Registry
  IR-03a Cypher Self-Validation MVP

Sprint 1:
  IR-04 Restricted DSL Models / Parser
  IR-05 Cypher Compiler MVP
  IR-06 Observability Skeleton
  IR-07 LiteralResolver MVP
  SP-01 LLM Feasibility Spike

Sprint 2:
  IR-08 Candidate Retriever MVP
  IR-09 Semantic Binder MVP
  IR-10 Semantic Validator MVP
  IR-11 DSL Builder MVP
  IR-12 Pipeline Orchestrator MVP

Sprint 3:
  IR-13 Question Decomposer
  IR-14 Grounded LLM Understanding
  IR-15 Repair / Clarification Controller
  IR-16 Full Trace and Testing-Agent Contract
  IR-16.5 Performance Baseline

Sprint 4:
  IR-03b Cypher Self-Validation Full
  IR-17 Variable Path Traversal
  IR-18 Metric / Ad Hoc Aggregate
  IR-19 Top-N and Two-Step Aggregate
  IR-20 Golden Test Regression Matrix
```

顺序理由：

- Self-Validation 先做 MVP，再做 Full：Sprint 0 只要求能拦截写操作和未知 schema 引用，完整 shape/dialect/model artifact 校验放到 IR-03b，避免启动 sprint 过载。
- DSL/Compiler 提前实现，因为 LLM 接入前必须有确定性落点。
- LLM 在 Sprint 1 做 spike，Sprint 3 再正式接入；这样能提前暴露 prompt/schema 可行性风险。
- LLM 后置，避免一开始就把问题混成 prompt 调参。
- Golden Test Set v1 从 IR-01 开始存在；IR-20 只是把贯穿各 IR 的用例收束成 regression matrix 和 CI 自动化。

Sprint 0 容量边界：

- Sprint 0 的关键路径是 IR-01 -> IR-02 -> IR-03a。
- IR-03a 只做 MVP，不包含 shape、dialect、model artifact full validation。
- 如果团队只有 1 名后端工程师，Sprint 0 应只承诺 IR-00、IR-01、IR-02，IR-03a 作为 stretch。
- 如果 Sprint 固定为 2 周，不建议把 IR-03b 放入 Sprint 0。

Sprint 4 容量边界：

- Sprint 4 同时包含 IR-03b、IR-17、IR-18、IR-19、IR-20，是 v1 最重的 sprint。
- Sprint 4 启动前必须重新评估团队容量；如果只能保一个 query shape 扩展，应优先 IR-17 或 IR-18，而不是同时打开全部形态。
- 如果 Sprint 4 跑超时，IR-20 可以推到 v1.1，因为 Golden Test Set v1 已在 IR-01 建立，IR-20 主要是 regression matrix 和 CI 自动化收束。

## 8. 跨 IR 验收矩阵

| 架构要求 | 对应 IR |
| --- | --- |
| Graph Semantic Model 是单一事实来源 | IR-01、IR-02 |
| 不维护旧字段映射 | IR-02、IR-20 |
| CGA 不连接数据库 | IR-00、IR-07、IR-12、IR-16 |
| path_pattern 加载期自校验 | IR-03b、IR-05 |
| Question Decomposer 分类稳定 | IR-13、IR-20 |
| LiteralResolver 独立子系统 | IR-07 |
| Candidate Retriever 带置信度和 evidence | IR-08 |
| LLM 只能在候选内选择 | IR-14 |
| coverage failure 不静默生成 | IR-10、IR-15、IR-20 |
| DSL 不支持不 fallback raw Cypher | IR-04、IR-10、IR-15、IR-20 |
| Cypher 只读和方言静态校验 | IR-03a、IR-03b、IR-05、IR-20 |
| repair loop 有上限和震荡检测 | IR-15 |
| assumption notice 用户可见且可追踪 | IR-15、IR-16 |
| 完整 trace 可复盘 | IR-06、IR-16 |
| LLM 可行性提前验证 | SP-01、IR-13、IR-14 |
| 性能和 token 基线 | IR-16.5 |

## 9. Definition of Done

单个 IR 完成标准：

- 有对应模块或明确修改点。
- 有单元测试覆盖成功路径和至少一个失败路径。
- 有 trace 或明确说明该 IR 不产生 trace stage。
- 没有数据库连接。
- 没有 raw Cypher fallback。
- 没有新增旧术语 schema 字段。
- 通过对应局部测试和 `git diff --check`。
- 文档或 README 如需新增入口已同步。

整个 v1 完成标准：

- fixture 中所有 golden generated case 产出 DSL、Cypher、trace。
- fixture 中所有 non-success case 产出 clarification、unsupported 或 generation_failed，不产出假 Cypher。
- Cypher Self-Validation MVP 能拦截写操作和未知 schema 引用；Full 能拦截 shape mismatch、model artifact 写操作和禁用方言能力。
- Testing-agent 能接收 generated 与 non-success report。
- CGA 配置中没有 TuGraph URL、用户名、密码或执行 timeout。
- v1 文档和用户引导明确说明静态 value index 的新鲜度限制。
- Golden Test Regression Matrix 能按 smoke/full 两档运行。

## 10. 需要避免的实现偏差

- 把 LLM 接到 pipeline 前，先跳过 DSL/Compiler。
- 在 LiteralResolver cache miss 时直接查 TuGraph 或业务库。
- 把静态 `value_index.json` 偷换成隐式在线服务，却没有新增 service contract、限流、缓存和失败语义。
- 用字符串拼接生成 WHERE 条件。
- 在 DSL 不支持时添加 `raw_cypher` 字段。
- 把 `unparsed_terms` 当垃圾桶，导致 coverage failure 失真。
- 把 `user_visible_notices` 当 Controller 手写字段，而不是 assumptions 的派生展示。
- 只比较 Cypher 字符串，不比较 DSL AST 和 shape。
- 在 trace 里记录数据库执行结果或敏感连接信息。

## 10.5 Risk Register

| 风险 | 可能性 | 影响 | 主要缓解 |
| --- | --- | --- | --- |
| Sprint 0 关键路径超载 | 中 | 高 | Self-Validation 拆成 IR-03a/IR-03b；1 名后端时 IR-03a 作为 stretch |
| 静态 value index 新鲜度不足 | 高 | 中 | v1 明确只消费静态 `value_index`，产品文档提示新实体需等下一次发布 |
| LLM schema failure 或候选发明率过高 | 中 | 高 | Sprint 1 执行 SP-01，Sprint 3 前调整 prompt 或降级策略 |
| Self-Validation Full 工作量外溢 | 中 | 高 | Sprint 0 只做 MVP；IR-03b 单独估算为 L，并允许延后 query shape 扩展 |
| Sprint 4 容量过重 | 高 | 中 | Sprint 4 启动前重排，必要时把 IR-20 推到 v1.1 |
| Testing-agent trace contract 过渡期不一致 | 中 | 中 | IR-12 标记为过渡 smoke path，IR-16 专门收口完整 contract |

## 11. 后续计划文档拆分建议

本 IR 覆盖面较宽，正式进入编码时应拆成多个 implementation plan：

- `2026-05-27-cga-deterministic-foundation-plan.md`：IR-00 到 IR-06，包含 IR-03a，不包含 IR-03b。
- `2026-05-27-cga-semantic-binding-plan.md`：IR-07 到 IR-12。
- `2026-05-27-cga-llm-repair-plan.md`：SP-01、IR-13 到 IR-16.5。
- `2026-05-27-cga-query-shapes-plan.md`：IR-03b、IR-17 到 IR-20。

每份 plan 再按 TDD 步骤展开到具体文件、测试和提交点。
