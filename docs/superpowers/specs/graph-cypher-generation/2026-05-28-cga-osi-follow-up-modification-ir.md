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
| MIR-004 | Slot-Authoritative Literal Candidate Filtering | 已远端验证，原始澄清失败点闭环 | `qa_c3e83dd7ad32` | P0 |
| MIR-005 | Decomposer Redundant Output Field Removal | 已远端验证，性能收益未完全达标 | decomposer completion token latency | P0 |

后续新增问题按 `MIR-006`、`MIR-007` 继续追加。

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
- `qa_c2508f2c0bac` 的参数传递问题已由 MIR-003 闭环；`qa_c3e83dd7ad32` 的 limit 数字误入 literal resolver 问题已由 MIR-004 闭环，剩余聚合/order/limit 生成能力待后续 MIR；IP owner/property 与多跳路径方向仍待后续 MIR。

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

### 6.4 闭环摘要

| 子 IR | 当前状态 | 关键结果 |
| --- | --- | --- |
| MIR-004.0 | 已完成 | 增加 `qa_c3e83dd7ad32` 回归，并加入 limit 数量与真实 filter 数字的对照测试。 |
| MIR-004.1 | 已完成 | prompt 强化 `literal_candidates` 只表示过滤/匹配值，结构控制词只听 slot。 |
| MIR-004.2 | 已完成 | pipeline 在 literal request 构造前按 slot 过滤结构词，`limit/order_by/group_by/path/projection` 不送 literal resolver。 |
| MIR-004.3 | 已完成 | trace 记录 `skipped_literal_candidates` 与 `skipped_literal_candidate_count`，运行中心可解释跳过原因。 |
| MIR-004.4 | 已完成 | slot-disambiguation 回归并入测试，覆盖结构槽位数字与 filter 数字不误伤。 |

实现口径：

- 下游判断一个词是否能进入 literal resolver 时，以 `substantive_terms[].slot` 为权威，而不是以值形态或 `literal_candidates` 数组归属为权威。
- `slot=filter/unknown` 的 literal candidate 保持原解析路径；结构槽位词被跳过并在 trace 中留痕。
- 运行中心字段说明补充了真实含义，详情页能展示阶段输入、跳过的 literal candidate 和相关 metric。

### 6.5 验证与边界

本地验证：

```text
PYTHONPATH=. pytest services/cypher_generator_agent/tests/integration/test_pipeline_mvp.py::test_qa_c3_limit_number_does_not_trigger_literal_clarification services/cypher_generator_agent/tests/integration/test_pipeline_mvp.py::test_structural_limit_literal_candidate_is_skipped_while_filter_literal_resolves services/cypher_generator_agent/tests/decomposition/test_term_classification.py::test_prompt_defines_literals_by_filter_role_not_control_slots -q
PYTHONPATH=. pytest tests/test_runtime_results_service_api.py -q
```

远端验证：

- 部署标识：`ba68344+mir004-runtime-center-20260529`
- 重跑记录：
  - `/home/mabingjie/apps/qa-agent/artifacts/experiment_runs/current8_after_mir004_direct_rerun_20260529T084801Z.json`
  - `/home/mabingjie/apps/qa-agent/artifacts/experiment_runs/current8_after_mir004_runtime_summary_20260529T084801Z.json`
- `qa_c3e83dd7ad32` 已从 `clarification_required` 推进为 `generated`。
- 最新 trace 中 `literal_resolver.input.skipped_literal_candidates=[{"raw":"3","slot":"limit","reason":"slot=limit"}]`，`skipped_literal_candidate_count=1`。

边界：

- MIR-004 闭环的是“结构控制词被误送 literal resolver 并触发澄清”的失败点。
- `qa_c3e83dd7ad32` 远端仍为 `final_verdict=fail / strict_check=fail`，因为生成 Cypher 只返回源节点网元 ID，没有表达 location 分组计数、按数量降序和 `LIMIT 3`。这属于 aggregate/group/order/limit 结构落地问题，应作为独立 MIR 处理。
- `literal_candidates` 仍是独立于 `substantive_terms` 的并列数组，schema 层仍可表达“同一词既是结构控制又是 literal”的矛盾。更根本的方向是把 literal 信息内嵌进 `substantive_terms`，但本 MIR 不做该破坏性 schema 重构。

## 7. MIR-005 Decomposer Redundant Output Field Removal

### 7.1 背景

触发问题：`question_decomposer` 调用 `qwen3-32b` 的端到端耗时过高，交互式问数体验差。

实测数据（streaming）：

- TTFT 中位数约 `0.72s`。
- completion tokens 约 `246-283`。
- TPOT 中位数约 `32.5ms/token`。
- 端到端中位数约 `9.17s`。
- 偶发 TPOT 抖动到 `72ms/token`，端到端约 `22s`。
- `llm_call_count=1`，无 schema retry；瓶颈不在 TTFT，也不在重试。

硬约束：

1. **模型不可更换**：全链路只有一个 `qwen3-32b`。任何换模型、蒸馏、轻量分类器或小模型 decomposer 方向都不在本 MIR 范围内。
2. **唯一可动变量是 completion token 数**：端到端耗时近似为 `TTFT(0.72s) + completion_tokens * 32.5ms`。当前 completion 约 `250 tokens`，要降延迟只能减少 LLM 输出 token。

根因：completion token 偏高，其中包含可由 `substantive_terms` 推导的冗余字段（`target_concepts`、`relation_phrases`）、下游无实质消费的字段（`stopword_terms`），以及非必要时仍输出的 `attached_to`。

本 MIR 是 MIR-002 的延续。MIR-002 已把 slot 合并进 `substantive_terms`，每个实义词自带 `slot`。本 MIR 进一步利用该结构：删除可从 `substantive_terms` 推导出的冗余输出字段，把推导逻辑下沉到工程代码，而不是让 LLM 重复输出。

预期收益：completion token 从约 `250` 降到约 `155`，decomposer 端到端从约 `9s` 降到约 `5.5-6s`，且不损失下游可用信息。

### 7.2 成本链路

| 输出字段 | 冗余性质 | token 成本 |
| --- | --- | --- |
| `target_concepts` | `substantive_terms` 中名词性词的子集视图，内容完全重复。 | 词被输出第二遍。 |
| `relation_phrases` | `substantive_terms` 中 `slot=path` 词的子集视图，内容完全重复。 | 词被输出第二遍。 |
| `stopword_terms` | coverage 检查只关心 substantive 是否覆盖；stopword 是被忽略对象，`不出现=已忽略`，列出来再忽略对 coverage 等价。 | 整个数组的 token。 |
| `attached_to`（无条件输出） | 仅在该词修饰的概念不唯一、需要消歧时才有用；无歧义时冗余。 | 每个无需消歧的 entry 多一个字段。 |
| `modality_terms` / `unparsed_terms` | 实际触发率待测；若极低则常年空数组，并占用模型判断成本。 | 取决于触发率。 |

### 7.3 修改目标

- 删除可由 `substantive_terms` 推导的输出字段：`target_concepts`、`relation_phrases`；推导逻辑下沉到代码。
- 删除无实质下游消费的字段：`stopword_terms`；前提是消费审计确认没有真实消费方。
- `attached_to` 改为按需输出，仅在消歧需要时填写。
- 根据实测触发率决定是否删除 `modality_terms` / `unparsed_terms`。
- 删除字段的同时，删除 prompt 中对应的讲解段落和示例字段，减少模型判断负担和 input token。
- 目标：completion token 从约 `250` 降到约 `155`，端到端从约 `9s` 降到约 `5.5-6s`。

非目标：

- 不换模型，不引入蒸馏、轻量分类器或小模型 decomposer。
- 不改 `substantive_terms` 的结构；MIR-002 已定稿。
- 不采用缩短 key 名、数组位置编码、slot 单字符编码等有损压缩。本 MIR 只删冗余字段，不牺牲可读性和可维护性。
- 不改 `question_decomposition_v1` schema version。
- 不改 decomposition 之外的 LLM prompt。
- 不连接数据库，不执行 Cypher。

### 7.4 子 IR 总览

| 子 IR | 名称 | 开发状态 | 优先级 | 估算 | 角色 | 依赖 |
| --- | --- | --- | --- | --- | --- | --- |
| MIR-005.0 | Downstream Consumption Audit and Baseline | 已完成 | P0 | S | backend/QA | 无 |
| MIR-005.1 | Derive target_concepts / relation_phrases From substantive_terms | 已完成 | P0 | M | backend | MIR-005.0 |
| MIR-005.2 | Drop stopword_terms Output | 已完成 | P0 | S | backend | MIR-005.0 |
| MIR-005.3 | attached_to On-Demand Only | 已完成 | P1 | S | backend/LLM | MIR-005.0 |
| MIR-005.4 | modality / unparsed Trigger-Rate Decision | 已完成：保留 | P2 | XS | backend/QA | MIR-005.0 |
| MIR-005.5 | Prompt Slimming and Schema Update | 已完成 | P0 | S | backend/LLM | MIR-005.1 到 MIR-005.4 |
| MIR-005.6 | Latency Regression and Token Baseline | 已远端采样，收益未完全达标 | P0 | S | QA | MIR-005.1 到 MIR-005.5 |

推荐顺序：

```text
MIR-005.0 -> MIR-005.1 -> MIR-005.2 -> MIR-005.3 -> MIR-005.4 -> MIR-005.5 -> MIR-005.6
```

必须先做 `MIR-005.0 Downstream Consumption Audit and Baseline`。删字段前必须确认下游没有真实消费。如果某字段仍被读取，对应子 IR 要从“删除输出”改为“改为代码推导”，不能直接删。

### 7.5 闭环摘要（2026-05-29）

字段审计结论：

| 字段 | 当前处理 | 依据 |
| --- | --- | --- |
| `target_concepts` | 从 LLM schema/prompt/output 中删除，不做新推导字段。 | retriever 已改读 `substantive_terms`、literal、原问题和既有工程信号；不引入词性判断或额外 LLM。 |
| `relation_phrases` | 从 LLM schema/prompt/output 中删除；关系召回由 `substantive_terms(slot=path)` 与原问题承接。 | 当前真实消费点只有 retriever，已不再读取旧字段。 |
| `stopword_terms` | 从 decomposer 输出删除。 | coverage 不依赖 decomposer 的 stopword 列表计算遗漏词；coverage report 中的同名兼容字段仍可保留为报告结构。 |
| `attached_to` | 保持 optional，prompt 明确只在消歧需要时填写。 | 下游已有缺省兜底；不改 `SubstantiveTerm` 结构。 |
| `modality_terms` / `unparsed_terms` | 本轮保留。 | semantic validator 与 coverage 仍消费对应报告语义；没有足够 trace 数据支持删除。 |

实现状态：

- `question_decomposition_v1` 不再允许 `target_concepts`、`relation_phrases`、`stopword_terms`；旧字段若由 mock/遗留 payload 进入 pipeline，会在规范化阶段被剔除。
- prompt 和 OpenAI-compatible 简化契约已删除旧字段说明与示例输出。
- retriever 不再读取旧双轨字段。
- 本地验证：`PYTHONPATH=. pytest services/cypher_generator_agent/tests -q` -> `517 passed in 3.71s`；`PYTHONPATH=. pytest tests/test_runtime_results_service_api.py -q` -> `32 passed in 0.32s`。

轻量 LLM 采样（各 1 次，`qwen3-32b`，无 schema retry）：

| Query | prompt tokens | completion tokens | total tokens | decomposer 耗时 |
| --- | ---: | ---: | ---: | ---: |
| `查询所有服务使用的隧道，返回隧道的 ID、名称和带宽` | 2797 | 197 | 2994 | 7417 ms |
| `Gold 服务使用了哪些隧道` | 2789 | 173 | 2962 | 5649 ms |

远端验证：

- 部署标识：`9aee174+mir005-20260529`。
- 重跑记录：`current8_after_mir005_direct_rerun_20260529T092051Z.json`、`current8_after_mir005_runtime_summary_20260529T092206Z.json`。
- final verdict：`pass=5`，`fail=2`，`pending=1`；strict check：`pass=1`，`fail=6`，`not_run=1`。
- 8 条样本的 decomposer 输出字段均不再包含 `target_concepts/relation_phrases/stopword_terms`。
- 远端 completion tokens：`129-319`。多数样本落在 `196-244`，复杂 IP 样本为 `319`，性能收益存在但不均匀。

结论：MIR-005 的 schema/prompt slimming 已闭环，completion tokens 较 MIR-002.7 有下降，但未稳定达到约 `155 tokens` 的目标。本轮不追加新的压缩策略；后续若继续优化，应另开 MIR 处理 prompt/schema 体积或 provider guided decoding。

### MIR-005.0 Downstream Consumption Audit and Baseline

目标：在删字段前，精确审计 `target_concepts`、`relation_phrases`、`stopword_terms`、`modality_terms`、`unparsed_terms` 的所有下游消费点；建立当前 completion token 和端到端耗时基线。

建议文件：

```text
docs/experiments/2026-05-28-runtime-center-cga-job-analysis.md
services/cypher_generator_agent/app/decomposition/models.py
services/cypher_generator_agent/app/core/pipeline.py
services/cypher_generator_agent/app/retrieval/retriever.py
services/cypher_generator_agent/app/validation/semantic_validator.py
services/cypher_generator_agent/app/understanding/prompt.py
console/runtime_console/ui/detail.js
```

开发内容：

- 全仓库扫描这五个字段名，列出每一处读取它们的代码，包括 retriever、validator、pipeline、understanding prompt、运行中心等。
- 对每个字段标注：有真实消费 / 只是被序列化进 prompt / 完全无消费。
- 对 `stopword_terms` 的审计不止记录“哪里读了它”，还要判定“读取后它的语义作用”；特别是 coverage 是否把它当作减项参与遗漏词计算。区分“只是读取”和“作为计算输入参与结果”。
- 对每个待删字段给出结论：可直接删 / 需改为代码推导 / 暂不可删。
- 记录当前基线：至少两条代表 query 的 `completion_tokens`、TTFT、TPOT、端到端耗时和 retry count。
- 建立 decomposer 准确率基线，与 token / 延迟基线并列：
  - 选取一组覆盖各类 slot 的代表样本，建议 `10-15` 条，覆盖 projection、filter、group_by、order_by、limit、path，包含多字段投影、filter literal、limit 数字、需消歧 `attached_to` 等典型情形。
  - 记录改动前每条样本的 slot 标注是否正确、literal 识别是否正确、projection 覆盖是否正确、path 关系识别是否正确。
  - 基线必须可复跑，固化为测试 fixture 或脚本。

验收：

- 产出明确的“字段 -> 消费点”清单。
- 每个待删字段都有可执行结论，且结论基于消费审计，不基于猜测。
- 基线数据记录在案，可供 MIR-005.6 对照。
- 准确率基线已建立并固化，覆盖样本数和各类 slot 分布已记录。

### MIR-005.1 Derive target_concepts / relation_phrases From substantive_terms

目标：让 LLM 不再输出 `target_concepts` 和 `relation_phrases`；`relation_phrases` 确定由代码推导，`target_concepts` 按 MIR-005.0 审计结论决定删除、推导或标记待决。

建议文件：

```text
services/cypher_generator_agent/app/decomposition/models.py
services/cypher_generator_agent/app/core/pipeline.py
services/cypher_generator_agent/app/retrieval/retriever.py
services/cypher_generator_agent/tests/retrieval/test_candidate_retriever.py
services/cypher_generator_agent/tests/integration/test_pipeline_mvp.py
```

开发内容：

- `relation_phrases` —— 确定走推导：
  - 从 LLM 输出 schema 中移除 `relation_phrases`。
  - 推导规则：`relation_phrases = substantive_terms` 中 `slot=path` 的词。
  - 所有当前读取 `relation_phrases` 的下游改为读取推导结果。
- `target_concepts` —— 先看 MIR-005.0 审计结论，按结论分支：
  - 若审计结论为“无真实下游消费”（只被序列化进 prompt 或完全无人读）：直接从 LLM 输出 schema 中删除，不做推导。这是首选情况。
  - 若审计结论为“有真实下游消费”（例如被 retriever 当召回词）：
    - 先评估能否仅用现有工程信号推导出等价的 `target_concepts`，包括 `slot`、已有候选 evidence、已存在的非 LLM 信号。
    - 如果能用现有信号推导：实现推导，下游改读推导结果。
    - 如果推导需要引入新组件，例如分词器、词性标注库、额外 LLM 调用：停止，不在 MIR-005.1 内实现。把该情况标记为需要单独讨论的待决项，写入 MIR 剩余风险或单独待决条目，等待用户决策。
- 不恢复 MIR-002 已删除的独立 `slot_terms` 或其它双轨结构。
- 严禁为了推导 `target_concepts` 而引入新的词性判断逻辑或额外 LLM 调用。

验收：

- LLM `raw_output` 中不再出现 `relation_phrases`。
- `relation_phrases` 推导值与改前 LLM 输出在代表样本上等价；retriever 召回不回归。
- `target_concepts` 的处理与 MIR-005.0 审计结论一致：无消费则已删除；有消费且可用现有信号推导则推导值等价；有消费但需新组件则已标记为待决，未擅自实现。
- 全程未引入任何新的词性判断逻辑或额外 LLM 调用。

### MIR-005.2 Drop stopword_terms Output

目标：停止输出 `stopword_terms`，前提是 MIR-005.0 确认无真实消费方。

建议文件：

```text
services/cypher_generator_agent/app/decomposition/models.py
services/cypher_generator_agent/app/decomposition/prompt.py
services/cypher_generator_agent/tests/decomposition/test_term_classification.py
services/cypher_generator_agent/tests/validation/test_coverage.py
```

开发内容：

- 前置验证（删除前必做）：确认当前 coverage 实现是否把 `stopword_terms` 作为减项或任何形式的计算输入使用，而不仅是“读取了这个字段”。
  - 若 coverage 仅遍历 `substantive_terms` 校验覆盖、完全不引用 `stopword_terms` 做减法：可安全删除。
  - 若 coverage 把 `stopword_terms` 当作减项参与“遗漏词”计算：删除前必须先解耦这个依赖，改成 coverage 只基于 `substantive_terms` 判定，不依赖 stopword 列表，然后才能删除 `stopword_terms`。
- 若 MIR-005.0 确认 `stopword_terms` 无真实消费方：从 schema 和 prompt 中删除该字段及其讲解。
- 确认 coverage 逻辑：被忽略的词不出现在任何 bucket 即等于被忽略；coverage 只校验 substantive 覆盖，不依赖 stopword 列表。
- 若 MIR-005.0 发现仍有消费方，则本子 IR 改为“保留但评估替代方案”，并在 MIR 记录消费方和保留原因。

验收：

- LLM 不再输出 `stopword_terms`。
- coverage 校验行为不回归，被忽略词仍被正确忽略。
- 删除 `stopword_terms` 后，对含大量 stopword 的问题，例如“麻烦帮我查一下所有的防火墙”，coverage 校验不误报，stopword 仍被正确忽略而非被当成未覆盖实义词。
- 若保留该字段，必须有消费审计证据说明原因。

### MIR-005.3 attached_to On-Demand Only

目标：`attached_to` 仅在需要消歧时输出，无歧义时省略。

建议文件：

```text
services/cypher_generator_agent/app/decomposition/prompt.py
services/cypher_generator_agent/app/decomposition/models.py
services/cypher_generator_agent/app/core/pipeline.py
services/cypher_generator_agent/tests/decomposition/test_term_classification.py
services/cypher_generator_agent/tests/integration/test_pipeline_mvp.py
```

开发内容：

- prompt 明确：`attached_to` 只在该词修饰的概念不唯一、需要消歧时才填；无歧义时省略。
- 如果 `attached_to` 已是 optional，则优先只改 prompt 和测试；不改 `SubstantiveTerm` 结构。
- 下游消费 `attached_to` 处确认能容忍其缺省，并有默认 owner / selected vertex 兜底行为。

验收：

- 无歧义样本中的 path 词和单 owner projection 词不输出 `attached_to`。
- 需消歧样本，例如“时延”可能归属多个对象时，仍输出 `attached_to`。
- 下游在 `attached_to` 缺省时行为正确，不发生 projection owner 回归。

### MIR-005.4 modality / unparsed Trigger-Rate Decision

目标：基于实测触发率决定是否删除 `modality_terms` / `unparsed_terms`。

建议文件：

```text
docs/experiments/2026-05-28-runtime-center-cga-job-analysis.md
services/cypher_generator_agent/app/decomposition/models.py
services/cypher_generator_agent/app/decomposition/prompt.py
```

开发内容：

- 统计近期生产 trace 中 `modality_terms` / `unparsed_terms` 非空的比例。
- 若非空比例 `< 5%`：从 schema 和 prompt 中删除，并记录“未来遇到 modality 类问题再加回”。
- 若非空比例 `>= 5%`：保留，并记录原因。
- 本决策必须基于 trace 数据，不基于主观判断。

验收：

- 有明确触发率数据支撑删/留决策。
- 决策结果写入 MIR 或实验记录。
- 若删除字段，prompt 和 schema 不再残留对应讲解；若保留字段，记录其继续存在的消费价值。

### MIR-005.5 Prompt Slimming and Schema Update

目标：随字段删除同步精简 prompt，删除被删字段的讲解段落和示例字段，减少 input token 和模型判断负担。

建议文件：

```text
services/cypher_generator_agent/app/decomposition/prompt.py
services/cypher_generator_agent/app/decomposition/models.py
services/cypher_generator_agent/app/infrastructure/llm_client.py
services/cypher_generator_agent/tests/decomposition/test_schema_retry.py
services/cypher_generator_agent/tests/decomposition/test_term_classification.py
```

开发内容：

- prompt 中删除 `target_concepts`、`relation_phrases`、`stopword_terms` 以及视 MIR-005.4 决策删除的 `modality_terms` / `unparsed_terms` 的讲解段落。
- 4 个示例的输出同步删除这些字段。
- JSON Schema 同步更新。
- 确认 prompt 仍清晰、示例仍自洽；不采用缩短 key 名、数组位置编码、slot 单字符等有损压缩。

验收：

- prompt 中无已删字段的残留讲解。
- 示例输出结构与新 schema 一致。
- decomposer 单测在新 prompt 下通过。
- prompt 字符数和 token 数较 MIR-005.0 baseline 有记录可比。

### MIR-005.6 Latency Regression and Token Baseline

目标：实测验证 token 和耗时收益，纳入回归。

建议文件：

```text
docs/experiments/2026-05-28-runtime-center-cga-job-analysis.md
services/cypher_generator_agent/tests/integration/test_pipeline_mvp.py
```

开发内容：

- 使用与 MIR-005.0 相同的代表 query，改后各跑多次。
- 每次记录 `completion_tokens`、TTFT、TPOT、端到端耗时、retry count 和 `llm_call_count`。
- 与 MIR-005.0 baseline 对照。
- 同时检查 decomposer 准确率，包括 slot 标注、literal 识别、projection coverage、path 关系识别。

验收：

- completion token 较基线下降，目标约 `250 -> 155`。
- decomposer 端到端中位数较基线下降，目标约 `9s -> 5.5-6s`。
- 用 MIR-005.0 固化的同一组准确率基线样本，逐条对照改动前后的 slot 标注、literal 识别、projection 覆盖、path 关系识别。
- 改动后每一项的正确数不得低于基线；若任一样本出现“基线正确、改后错误”的退化，记录为准确率回归，不得通过验收，需修复或回退相关改动。
- 准确率回归与延迟收益是两个独立的通过条件，必须同时满足：既要 token / 耗时达到目标，也要准确率不低于基线。任一不达标，本 MIR 不算完成。
- 若实测收益与目标偏差 `> 30%`，记录数据，不自行追加优化，等待用户决策。

### 7.5 剩余风险 / 未来方向

即使删光冗余字段，在单模型 `qwen3-32b` 且 TPOT 固定的硬约束下，decomposer 物理下限约 `4-5s`。整条问数链路如果仍包含 grounded_understanding 等其它 LLM 调用，整体进入 `5s` 以内可能无法仅靠 decomposer 输出瘦身实现。

后续若要进一步降低整体延迟，需要架构级权衡，例如将 decomposer 与 grounded_understanding 合并为单次 LLM 调用，或让简单查询走确定性快速路径。这些属于架构级变更，不在本 MIR 范围内。

另一个本次不采用的方向是有损压缩输出结构，例如缩短 key 名、数组位置编码、slot 单字符化。这类方案能再省少量 token，但牺牲可读性和可维护性；当前不做。仅当删冗余后仍无法满足延迟，且团队接受可读性代价时，再另行评估。

## 8. 后续 MIR 模板

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

## 9. 审核结论与后续 MIR 检查

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
