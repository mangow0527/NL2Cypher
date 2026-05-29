# CGA OSI Follow-up Modification IR

> 日期：2026-05-28
> 状态：持续维护 IR v0
> 适用分支：`cypher-generation-osi`
> IR 含义：Implementation Roadmap / Implementation Requirements

## 1. 文档定位

本文档不是某一个 bug 的单点修复方案，而是 CGA OSI 重写后持续记录后续修改的实施 IR。

使用方式：

- 每发现一类系统性问题，新增一个 `MIR-*` 修改项。
- 待审核或待实施 MIR 保留完整背景、失效链路、修改范围、建议文件、验收标准和测试要求。
- 已实现并闭环的 MIR 压缩为闭环摘要，只保留背景、目标、关键结果、验证和剩余边界。
- 同一类问题可以持续追加观察、修复阶段、回归结果和剩余风险。
- 不在本文档中直接贴实现代码；实现前先由用户审核 MIR。
- 本文档只记录 CGA 生成链路、语义层、DSL、validator、compiler、trace、testing-agent contract 等工程修改，不记录 UI 样式微调。

当前已记录修改项：

| MIR | 名称 | 状态 | 触发样本 | 优先级 |
| --- | --- | --- | --- | --- |
| MIR-001 | Projection Slot Coverage and No Silent ID Downgrade | 已严格闭环 | `qa_9cfa692813d5` | P0 |
| MIR-002 | Decomposer Substantive Slot Hard Cut | 代码已完成，性能验收未达标，待再决策 | decomposer latency / duplicate retrieval terms | P0 |
| MIR-003 | Executable Cypher Inline Output with Template Trace | 已远端闭环 | `qa_c2508f2c0bac` | P0 |
| MIR-004 | Slot-Authoritative Literal Candidate Filtering | 待审核 | `qa_c3e83dd7ad32` | P0 |

后续新增问题按 `MIR-005`、`MIR-006` 继续追加。

## 2. 总体修改原则

1. **LLM 只填空，不独自决定最终结构**：LLM 可以做自然语言拆解和候选内选择，但字段绑定、路径约束、coverage 校验、DSL 编译必须有工程防线。
2. **不静默吞语义**：用户问题中的实义词必须进入正确语义槽位；如果无法进入，应 repair、clarification 或 generation_failed。
3. **coverage 要按槽位判断**：不是“词被某个候选命中”就算覆盖，而是必须进入语义上正确的位置，例如 projection、filter、group_by、order_by、path、limit。
4. **builder/compiler 不猜业务意图**：下游只编译明确 DSL，不把模糊结构自动窄化成看似可运行的 Cypher。
5. **错误要在靠前阶段暴露**：如果 binding plan 已经丢失用户要求，semantic validator 应拦住，不应等到 testing-agent 比对 golden 才发现。
6. **每个修改项都要沉淀 regression**：修复必须配套可复跑的 fixture、单元测试或 golden matrix slice。
7. **优先加防线，谨慎加词表/闸门**：每个 MIR 都要审查是否引入手工维护的词表或特例闸门。能从 semantic model、registry、schema 或 trace 派生的规则，不允许在代码中再写一份平行词表。

## 3. MIR-001 Projection Slot Coverage and No Silent ID Downgrade

状态：已严格闭环。

### 3.1 背景

触发样本：

```text
qa_9cfa692813d5
查询所有服务的ID、名称、元素类型、服务质量等级、带宽和时延。
```

期望语义是返回 `Service.id/name/elem_type/quality_of_service/bandwidth/latency` 六个字段。旧版本只生成：

```text
MATCH (svc:Service) RETURN svc.id AS service_id
```

核心现象：decomposer 已识别多个返回字段，但后续 grounded/builder 链路把它塌缩成裸 `Service` vertex projection，最终又被 builder 静默降级成 ID。

### 3.2 失效链路

| 层级 | 失效点 | 影响 |
| --- | --- | --- |
| 主因：grounded understanding | 多个返回字段被塌缩成一个裸 `Service` vertex projection。 | `selected_properties=[]`，字段信息从 binding plan 中消失。 |
| 防线 1：DSL builder | 裸 `vertex` projection 被静默编译成 id property。 | “返回节点/对象”被无依据窄化为“返回 ID”。 |
| 防线 2：semantic validator | 只检查已有 projection 合法，不检查用户要求字段是否进入 projection。 | projection coverage gap 没有被拦截。 |
| 防线 3：self-validation | 只检查 Cypher 静态合法性。 | `RETURN svc.id` 合法，因此继续放行。 |

### 3.3 修改目标

- 显式返回字段必须落成确定性 property-level projection。
- DSL builder 禁止把模糊 vertex projection 静默降级成 ID。
- semantic validator 增加 projection coverage 防线，缺字段要在 CGA 内部暴露。
- projection 问题沉淀为 regression slice。
- 保持 CGA 不连接数据库、不执行 Cypher。

非目标：

- 不扩展新的复杂 query shape。
- 不要求一次解决所有路径、聚合、Top-N 问题。
- 不引入 raw Cypher fallback。

### 3.4 闭环摘要

| 子 IR | 当前状态 | 关键结果 |
| --- | --- | --- |
| MIR-001.0 | 已完成 | `gq-031/gq-032/gq-033` 覆盖单点多字段、单跳终点多字段、filter + projection。 |
| MIR-001.1 | 已完成 | decomposer 输出槽位角色，供下游按 projection/filter/path 等语义消费。 |
| MIR-001.2 | 已完成 | projection 字段从 semantic model 与候选 evidence 派生，落成 property-level projection。 |
| MIR-001.3 | 已完成 | semantic validator 可暴露 `projection_coverage_missing`。 |
| MIR-001.4 | 已完成 | builder/compiler 不再把裸 vertex projection 静默降级成 ID。 |
| MIR-001.5 | 已完成 | grounded schema 拒绝不明确的 projection 形态。 |
| MIR-001.6 | 已完成 | trace/运行中心能解释 projection coverage 缺口。 |
| MIR-001.7 | 已完成 | self-validation 保留 RETURN shape 防线。 |
| MIR-001.8 | 已完成 | projection slice 已并入 golden matrix。 |

验证与边界：

- 本地 regression 已覆盖 projection slice；最新全量验证为 `services/cypher_generator_agent/tests` 511 passed、`tests/test_runtime_results_service_api.py` 32 passed。
- 远端 MIR-001 strict 重跑证明 projection 不再塌缩；部分样本仍有 `strict_check=fail`，属于 testing/golden 口径或后续语义问题。
- `qa_c2508f2c0bac` 的参数传递问题已由 MIR-003 闭环；`qa_c3e83dd7ad32` 的 Top-N/limit 角色混淆已进入 MIR-004；IP owner/property 与多跳路径方向仍待后续 MIR。

## 4. MIR-002 Decomposer Substantive Slot Hard Cut

状态：代码侧已完成，性能验收未达标，待再决策。

### 4.1 背景

触发问题：`question_decomposer` 的 LLM 输出过长，`substantive_terms` 与 `slot_terms` 双轨表达同一批表层词，导致 token 重复、内部消费路径重复、retriever 搜索词重复。

基线摘要：

| Query | 版本 | input tokens | output tokens | 耗时 |
| --- | --- | ---: | ---: | ---: |
| `查询所有服务使用的隧道，返回隧道的 ID、名称和带宽` | 当前 baseline | 3095 | 270 | streaming 多次约 7.2-9.5s，生产路径曾见 12-14s |
| 同上 | 去 schema 但保留 slot 输出 | 约 2290 | 270 | 多数约 6.5-9.1s，收益有限 |
| 同上 | 省略 slot 输出 | 约 2518 | 162 | 约 4.6-5.0s，但语义不等价 |

关键结论：独立 `slot_terms` 是主要可控重复输出源；本 MIR 只做 schema/prompt/pipeline hard cut，不切换 provider guided decoding。

### 4.2 失效链路

| 层级 | 失效点 | 影响 |
| --- | --- | --- |
| Decomposer schema | `substantive_terms` 和 `slot_terms` 双字段表示同一批实义词。 | LLM 输出重复 text 和 JSON 对象结构，增加 output tokens。 |
| Prompt | 三轴说明要求同词在多个数组重复出现。 | 增加模型决策负担和输出长度。 |
| Pipeline | projection resolver / coverage seed 直接读取 `slot_terms`。 | 下游依赖旧双轨结构。 |
| Retriever | 同时读取 `substantive_terms` 和 `slot_terms` 作为 search terms。 | 同词重复检索，可能造成召回排序权重虚高。 |
| Validation | projection coverage 依赖 slot coverage 输入。 | 需要迁移为从 `substantive_terms[].slot` 派生 required projection terms。 |

### 4.3 修改目标

- 将 `QuestionDecomposition` 中的 `substantive_terms: list[str]` 与 `slot_terms: list[SlotTerm]` 合并为 `substantive_terms: list[SubstantiveTerm]`。
- `SubstantiveTerm` 携带 `text`、`slot`、optional `attached_to`。
- 删除独立 `SlotTerm` 类和 `QuestionDecomposition.slot_terms` 字段。
- LLM 输出和内部表示统一使用新结构，执行 hard cut，不保留旧字段、派生属性、兼容分支或 feature flag。
- 修复 retriever 同词重复搜索问题：search terms 只从 `substantive_terms[].text` 提取。
- 保持 `question_decomposition_v1` 不升版；本项视为开发期 schema 定稿修正。

非目标：

- 不切换 vLLM / DashScope guided JSON。
- 不删除 `modality_terms` / `unparsed_terms`。
- 不改 `grounded_understanding_v1` schema。
- 不动 decomposition 之外的 LLM prompt。
- 不引入 raw Cypher fallback 或数据库执行。

### 4.4 闭环摘要

| 子 IR | 当前状态 | 关键结果 |
| --- | --- | --- |
| MIR-002.0 | 部分完成 | 保留 baseline 摘要；缺少完整改前三次原始记录。 |
| MIR-002.1 | 已完成 | decomposition model 已迁移到 `SubstantiveTerm` 对象数组。 |
| MIR-002.2 | 已完成 | prompt 已使用对象数组，不再要求独立 `slot_terms` 输出。 |
| MIR-002.3 | 已完成 | pipeline 从 `substantive_terms[].slot` 消费 projection/filter/path 等槽位。 |
| MIR-002.4 | 已完成 | retriever search terms 不再因同词不同 slot 重复。 |
| MIR-002.5 | 已完成 | coverage/validator 已按新结构迁移。 |
| MIR-002.6 | 已完成 | decomposition、retrieval、validation、integration 测试已更新。 |
| MIR-002.7 | 已完成，未达性能目标 | 已补做两条 query 各 3 次采样。 |

实现口径：

- CGA app/tests 中不再消费 decomposition `slot_terms` 字段。
- coverage report 内部如果保留 slot coverage 命名，含义是 coverage 结构，不是 decomposition 输出字段。
- 本 MIR 不保留旧结构兼容分支，不做 schema version 升级。

### 4.5 性能验收现状

| Query | input tokens 中位数 | output tokens 中位数 | decomposer 耗时中位数 | retry count |
| --- | ---: | ---: | ---: | ---: |
| `查询所有服务使用的隧道，返回隧道的 ID、名称和带宽` | 2836 | 246 | 10540 ms | 0 |
| `Gold 服务使用了哪些隧道` | 2828 | 251 | 9846 ms | 0 |

结论：第一条 query 的 output tokens 从 baseline `270` 降至 `246`，约 `8.9%`，未达到 `30-40%` 预期；耗时中位数仍约 `10.5s`，未进入 `4-5s` 目标区间。后续应先决策是否切换 provider guided decoding、缩短 prompt schema、或调整模型/服务端参数。

## 5. MIR-003 Executable Cypher Inline Output with Template Trace

状态：已远端闭环。

### 5.1 背景

触发样本：

```text
qa_c2508f2c0bac
查询服务质量等级为金牌的所有服务的ID、名称和带宽。
```

CGA 修复前已经能把“金牌”解析成 `Gold`，并正确落到 `Service.quality_of_service` filter；实际失败发生在 testing-agent 执行 TuGraph 时：

```text
state = tugraph_execution_failed
error = CypherException: Undefined parameter: $quality_of_service
```

修复前主输出仍是参数化模板：

```cypher
MATCH (svc:Service)
WHERE svc.quality_of_service = $quality_of_service
RETURN svc.id AS service_id, svc.name AS service_name, svc.bandwidth AS service_bandwidth
```

当时对外执行链路只消费 `generated_cypher` 字符串，不消费 `parameters` 字典。本 MIR 明确 v1 产品契约：CGA 对外主 Cypher 必须可直接执行；参数化模板和参数只作为 compiler 内部表示与 trace 观测产物。

### 5.2 失效链路

| 层级 | 失效点 | 影响 |
| --- | --- | --- |
| compiler 输出契约 | 修复前 `CypherCompilationResult.cypher` 是参数化模板。 | 对外 `generated_cypher` 中仍含 `$quality_of_service`。 |
| trace 观测 | trace 只有 `cypher` 和 `parameters`，没有区分模板和可执行文本。 | 人和工具容易误以为 `cypher` 可直接执行。 |
| self-validation | 修复前校验参数化模板的只读、schema、shape，但不校验最终执行文本是否仍含 `$param`。 | 不完整的执行产物可通过 CGA 自校验。 |
| testing-agent contract | testing-agent 只执行 Cypher 文本，不传 parameters。 | TuGraph 报 `Undefined parameter`，样本无法进入结果评测。 |

### 5.3 修改目标

- CGA 对外 `GenerationOutput.cypher` / submission `generated_cypher` 输出可直接执行的内联 Cypher。
- compiler 内部继续先生成 `cypher_template + parameters`。
- compiler 对 `cypher_template` 做参数内联，生成 `cypher_executable`。
- trace 中同时记录 `cypher_template`、`parameters`、`cypher_executable`。
- self-validation 校验最终 `cypher_executable`，并禁止执行文本中残留 `$param`。
- 不要求 testing-agent 改造参数传递契约。

非目标：

- 不在本 MIR 中改 Top-N、IP owner/property 绑定、多跳路径方向等问题。
- 不引入 raw Cypher fallback。
- 不在本 MIR 中切换到 runtime service 的参数化执行协议。

### 5.4 闭环摘要

| 子 IR | 当前状态 | 关键结果 |
| --- | --- | --- |
| MIR-003.0 | 已完成 | filter + projection 回归要求主输出为内联 Cypher，trace 保留模板和参数。 |
| MIR-003.1 | 已完成 | compiler 输出拆为 template、parameters、parameter_sources、executable、主 cypher。 |
| MIR-003.2 | 已完成 | 字面值内联统一走 literal inliner。 |
| MIR-003.3 | 已完成 | compiler 拒绝来源不明或 unresolved literal 内联。 |
| MIR-003.4 | 已完成 | self-validation 禁止最终 executable query 残留 `$param`。 |
| MIR-003.5 | 已完成 | 运行中心区分最终执行 Cypher、模板和参数。 |
| MIR-003.6 | 已完成 | 远端 smoke 已验证参数占位符失败消除。 |

### 5.5 验证与边界

远端烟测：

- 部署标识：`2deb163+mir002-mir003-20260529153514`
- 发送 run：`dispatch_20260529T073559Z`
- 发送记录：`/home/mabingjie/apps/qa-agent/artifacts/experiment_runs/send_current8_to_cga8000_testing8003_after_mir003_inline_20260529T1536.jsonl`
- 8 条样本状态：`state=passed` 5 条，`issue_ticket_created` 1 条，`generation_failed/clarification_required` 2 条；严格比对 `strict_pass` 1 条，`strict_fail` 5 条。
- `qa_c2508f2c0bac`：`state=passed / verdict=pass / execution_success=true / strict_check=fail`；生成 Cypher 为内联版，已消除原 `Undefined parameter` 失败点。

本地验证：

```text
PYTHONPATH=. pytest services/cypher_generator_agent/tests -q
PYTHONPATH=. pytest tests/test_runtime_results_service_api.py -q
```

边界：

- MIR-003 只改变 Cypher 输出契约，不改 decomposition hard cut。
- MIR-003 没有处理 Top-N、IP owner/property、多跳路径方向等相邻问题。
- `qa_c2508f2c0bac` 剩余 `strict_check=fail` 属于返回字段/字段值口径差异，不再是参数执行契约问题。

## 6. MIR-004 Slot-Authoritative Literal Candidate Filtering

### 6.1 背景

触发样本：

```text
qa_c3e83dd7ad32
统计服务使用的隧道源节点所在位置的网元数量，按数量降序排列，返回前3名。
```

期望语义是聚合 + 排序 + limit：

```cypher
MATCH (s:Service)-[:SERVICE_USES_TUNNEL]->(:Tunnel)-[:TUNNEL_SRC]->(ne:NetworkElement)
WHERE ne.location IS NOT NULL
RETURN ne.location AS location, count(*) AS cnt
ORDER BY cnt DESC
LIMIT 3
```

实际行为：CGA 没有生成 Cypher，而是返回 `clarification_required`，向用户输出：

```text
我没有确定“3”对应的值，请选择或补充。
```

trace 证据显示，`question_decomposer` 一方面正确把“前”和“3”标成 `slot=limit`，另一方面又错误地把“3”放进 `literal_candidates`：

```json
{"text": "3", "kind_hint": "number", "attached_to": "数量"}
```

pipeline 看到 `literal_candidates` 后，构造了 literal request：

```json
{"raw_literal": "3", "expected_vertex": "Tunnel", "expected_property": "elem_type"}
```

`literal_resolver` 在 `Tunnel.elem_type` 的合法值中找不到 `3`，返回 `literal_value_index_miss`；`semantic_validator` 将其转成 `literal_unresolved`；`repair_controller` 决定 `ask_user`。

一句话核心：Top-N/limit 控制词里的数量被误当成 filter literal，导致一条本应正常聚合的查询退化成澄清。

本 bug 属于“语义槽位被搞混”的问题家族。此前 `slot_terms` 重复输出、projection 塌缩也暴露了相同根因：一个词的语义角色虽然被标注出来，但下游各阶段没有把 slot 当作唯一权威，而是从值形态、数组归属或候选分数反推角色，最终被非 slot 信号误导。

本 MIR 要确立的原则是：**slot 是一个词语义角色的唯一权威来源。** 一旦 decomposer 给一个词定了 slot，所有下游消费方都必须只按 slot 决定它能否进入 literal resolver、projection resolver、limit/order/group 等结构处理，不得再从值形态或数组归属反推语义角色。

### 6.2 失效链路

| 层级 | 失效点 | 影响 |
| --- | --- | --- |
| 主因：question_decomposer | “3”同时被标为 substantive `slot=limit`，又被放进 `literal_candidates`，两个角色矛盾。 | 下游收到自相矛盾的标注。 |
| 防线缺失：pipeline literal request 构造 | 看到 `literal_candidates` 里有“3”就构造 literal request，未检查该词的 slot 已是结构控制槽位。 | 把 limit 数量当成待解析的过滤值送进 resolver。 |
| literal_resolver | 在 `Tunnel.elem_type` 的合法值里找不到“3”。 | 返回 `literal_value_index_miss`；resolver 本身行为正确。 |
| semantic_validator -> repair_controller | 把 literal miss 升级为 unresolved，决策 `ask_user`。 | 一条可正常生成的查询退化为 `clarification_required`。 |

### 6.3 修改目标

- 确立 **slot 是语义角色唯一权威** 原则：literal resolver、projection resolver、limit/order/group 等下游消费方必须按 slot 消费词，不得从值形态或数组归属反推角色。
- 结构控制词，即 `slot` 属于 `limit`、`order_by`、`group_by` 的词，不得进入 `literal_candidates`，从源头消除矛盾标注。
- pipeline 在构造 literal request 前，按 slot 做确定性结构过滤，作为工程兜底。
- 不误伤真正的 filter 值，例如“带宽为3的链路”中的“3”和“时延为100的隧道”中的“100”仍须正常作为 filter literal 解析。
- 将该问题沉淀为 regression fixture，并覆盖 limit 数量与真实 filter 值的对照。

非目标：

- 不引入基于值形态的特例规则；判定锚点只能是 slot。
- 不把修复写成针对“3”或单个样本的孤立补丁。
- 不在本 MIR 中重构 `literal_candidates` 的数据结构；该风险记录在本 MIR 末尾。
- 不改 `question_decomposition_v1` schema version。
- 保持 CGA 不连接数据库、不执行 Cypher。

### 6.4 子 IR 总览

| 子 IR | 名称 | 开发状态 | 优先级 | 估算 | 角色 | 依赖 |
| --- | --- | --- | --- | --- | --- | --- |
| MIR-004.0 | Regression Fixture and Baseline | 待审核 | P0 | S | QA/backend | 无 |
| MIR-004.1 | Decomposer literal_candidates Definition Tightening | 待审核 | P0 | S | backend/LLM | MIR-004.0 |
| MIR-004.2 | Pipeline Structural-Slot Filter Before Literal Request | 待审核 | P0 | S | backend | MIR-004.0 |
| MIR-004.3 | Trace for Skipped Literal Candidates | 待审核 | P1 | XS | backend/infra | MIR-004.2 |
| MIR-004.4 | Regression Matrix Integration | 待审核 | P0 | XS | QA/infra | MIR-004.0 到 MIR-004.3 |

推荐顺序：

```text
MIR-004.0 -> MIR-004.2 -> MIR-004.1 -> MIR-004.3 -> MIR-004.4
```

如果只能先做一项，优先做 `MIR-004.2 Pipeline Structural-Slot Filter Before Literal Request`，因为它是确定性工程防线，不依赖 LLM 输出完全正确，能拦住整类“结构控制词被当 literal”的问题。`MIR-004.1` 用于消除矛盾源，两者构成纵深防御，都应完成。

### MIR-004.0 Regression Fixture and Baseline

目标：把 `qa_c3e83dd7ad32` 和同类 top_n/limit 样本固化为回归基线，同时建立“filter 值”的防误伤对照样本。

建议文件：

```text
services/cypher_generator_agent/tests/fixtures/golden_questions.yaml
services/cypher_generator_agent/tests/decomposition/test_term_classification.py
services/cypher_generator_agent/tests/integration/test_golden_questions.py
services/cypher_generator_agent/tests/integration/test_pipeline_mvp.py
```

开发内容：

- 将 `qa_c3e83dd7ad32` 纳入 active regression scope。
- 补至少 2 个同类聚合查询，覆盖“返回前N名”“排名前N”“取前N个”等 limit 措辞。
- 必须补对照样本，覆盖“带宽为3的链路”“时延为100的隧道”这类值作为真实 filter 的查询，确保修复不会误伤它们。
- golden 断言要检查 DSL 结构、slot 归属、是否构造 literal request，不只检查最终 Cypher 字符串。
- 测试名称和断言说明应区分“limit 数量误判”和“真实 filter 值”。

验收：

- 当前实现下，limit 样本的新增测试应能暴露“limit 词被送进 literal request / 退化为 clarification”的问题。
- 对照样本在当前实现下应已通过，修复后不得回归。
- 测试报告能清楚定位失败来自 slot/literal 角色混淆，而不是数据库执行或 strict check。

### MIR-004.1 Decomposer literal_candidates Definition Tightening

目标：从定义上排除结构控制词进入 `literal_candidates`，消除矛盾源，而不是加样本特例。

建议文件：

```text
services/cypher_generator_agent/app/decomposition/prompt.py
services/cypher_generator_agent/app/decomposition/models.py
services/cypher_generator_agent/tests/decomposition/test_term_classification.py
```

开发内容：

- 在 prompt 中强化 `literal_candidates` 的本质定义：只包含“作为过滤/匹配条件、限定某个概念属性取值”的字面值。
- 明确控制查询结构的数量、排序和分组词不属于 literal，只属于 `substantive_terms` 的对应 slot。
- 加对比反例：
  - “返回前3名”中的“3” -> `substantive_terms(slot=limit)`，不进 `literal_candidates`。
  - “带宽为3的链路”中的“3” -> `substantive_terms(slot=filter)`，并进入 `literal_candidates`。
- 明确判定锚点是 slot/语义角色，不是值形态。

验收：

- “返回前3名” -> “3”在 `substantive_terms(slot=limit)`，不在 `literal_candidates`。
- “带宽为3的链路” -> “3”在 `substantive_terms(slot=filter)`，并在 `literal_candidates`。
- “排名前5”“取前10个”等变体表现一致。
- prompt 和测试说明不得把规则写成基于值形态的过滤。

### MIR-004.2 Pipeline Structural-Slot Filter Before Literal Request

目标：在 pipeline 构造 literal request 之前，加确定性结构过滤，按 slot 决定一个 literal candidate 是否送入 resolver。

建议文件：

```text
services/cypher_generator_agent/app/core/pipeline.py
services/cypher_generator_agent/tests/integration/test_pipeline_mvp.py
services/cypher_generator_agent/tests/validation/test_coverage.py
```

开发内容：

- 对每个 `literal_candidate`，按 text 找到其在 `substantive_terms` 中对应词的 slot。
- 若 slot 属于 `limit`、`order_by`、`group_by`、`path`、`projection`，跳过，不构造 literal request；这些是结构或字段角色，不是待解析的数据值。
- 若 slot 属于 `filter` 或 `unknown`，保持现有 literal request 构造路径。
- 判定锚点是 slot，不是值形态；filter 槽位的值必须继续送解析。

验收：

- `slot=limit` 的词不构造 literal request。
- `slot=filter` 的词仍构造 literal request 并解析。
- `qa_c3e83dd7ad32` 不再因“3”触发 `literal_unresolved`。
- 新增测试证明 `limit/order_by/group_by/path/projection` 的结构词不会进入 literal resolver，而 filter 词不会被误跳过。

### MIR-004.3 Trace for Skipped Literal Candidates

目标：被跳过的 literal candidate 在 trace 中留痕，便于后续排障和运行中心解释。

建议文件：

```text
services/cypher_generator_agent/app/observability/trace.py
services/cypher_generator_agent/app/core/pipeline.py
console/runtime_console/ui/detail.js
tests/test_runtime_results_service_api.py
```

开发内容：

- 在 literal resolver 相关 stage 记录被跳过的 candidate 及原因，例如：

```json
{"raw": "3", "skipped": true, "reason": "slot=limit"}
```

- 运行中心可展示“因 slot=limit 未送 literal 解析”，避免用户看到 literal 消失却不知道原因。
- trace 记录只描述 slot-based filtering，不引入值形态规则说明。

验收：

- trace 能看出“3 因 `slot=limit` 未送 literal 解析”。
- 对真实 filter 值，trace 仍展示正常 literal request 和 resolver 结果。
- 运行中心字段说明中能区分“跳过结构控制词”和“literal 解析失败”。

### MIR-004.4 Regression Matrix Integration

目标：纳入回归矩阵，防止后续 decomposer 或 pipeline 改动让 slot/literal 角色混淆回归。

建议文件：

```text
services/cypher_generator_agent/tests/fixtures/golden_questions.yaml
services/cypher_generator_agent/tests/integration/test_golden_regression_matrix.py
services/cypher_generator_agent/tests/integration/test_golden_questions.py
```

开发内容：

- 将 `qa_c3e83dd7ad32`、新增 limit 样本、filter 值对照样本标为 slot-disambiguation 回归 slice。
- 该 slice 应可独立执行，并覆盖 decomposer 输出、literal request 构造和最终 generation status。
- `qa_c3e83dd7ad32` 修复后的期望应包含 `ORDER BY ... DESC` 与 `LIMIT 3`，且不再 `clarification_required`。

验收：

- slot-disambiguation slice 可独立跑。
- `qa_c3e83dd7ad32` 修复后能生成带 `LIMIT 3` 的 Cypher，不再 clarification。
- filter 值对照样本不回归。

### 6.5 剩余风险 / 未来方向

`literal_candidates` 当前是独立于 `substantive_terms` 的并列数组，两者之间没有强制一致性约束，因此 LLM 可以把同一个词同时标成 `substantive_terms(slot=limit)` 和 `literal_candidates`，这个矛盾源在 schema 层是可表达的。

更根本的修复是把 literal 信息内嵌进 `substantive_terms`，类似 MIR-002 中对 `slot_terms` 的合并，使“一个词同时是结构控制又是 literal”在结构上无法表达。**本 MIR 不做此重构**，避免再次引入破坏性 schema 变更；如果后续再次出现 literal 与 slot 不一致的问题，再启动独立 MIR 处理该 schema 合并。

## 7. 后续 MIR 模板

新增修改项时按以下模板追加：

```markdown
## N. MIR-00X <Name>

### N.1 背景

- 触发样本：
- 期望行为：
- 实际行为：
- trace 证据：

### N.2 失效链路

| 层级 | 失效点 | 影响 |
| --- | --- | --- |

### N.3 修改目标

-

### N.4 子 IR 总览

| 子 IR | 名称 | 优先级 | 估算 | 角色 | 依赖 |
| --- | --- | --- | --- | --- | --- |

### MIR-00X.0 <Sub IR Name>

目标：

建议文件：

开发内容：

验收：
```

## 8. 审核结论与后续 MIR 检查

MIR-001 审核后的当前默认决策：

1. `vertex_full` 进入 DSL v1，作为一等 projection item。
2. 默认 list 查询倾向返回完整节点；实施前需要 audit golden 口径。
3. projection coverage failure 进入 repair loop；超过上限转 generation_failed，不直接 ask_user。
4. 多 owner 字段歧义不按最近对象静默选择；`各自/双方/两端` 展开为多个 projection，真歧义先 repair，仍不确定再 ask_user。
5. schema 暂不升版，保持 v1；实施前若发现外部稳定消费方依赖旧 projection 形态，再升 v2。
6. 字段词映射从 semantic model registry 派生，不在 resolver 中硬编码平行词表。
7. 槽位角色由 question decomposer 标注，validator 消费角色并校验最终 DSL。

每个后续 MIR 审核时必须额外回答：

1. 本 MIR 是加通用防线，还是加特例词表/闸门？
2. 如果引入词表或规则，是否能改为从 semantic model / registry / schema 派生？
3. 是否新增了对应的 slot coverage 或 trace evidence？
4. 是否有独立 regression slice，且不会被相邻问题污染通过率？
