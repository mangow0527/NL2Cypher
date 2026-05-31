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
| MIR-002 | Decomposer Substantive Slot Hard Cut | 已吸收；性能方向不再单独决策 | decomposer latency / duplicate retrieval terms | P0 |
| MIR-003 | Executable Cypher Inline Output with Template Trace | 已远端闭环 | `qa_c2508f2c0bac` | P0 |
| MIR-004 | Slot-Authoritative Literal Candidate Filtering | 已闭环，剩余结构问题转 MIR-006 | `qa_c3e83dd7ad32` | P0 |
| MIR-005 | Decomposer Redundant Output Field Removal | 已闭环，性能继续优化另开 | decomposer completion token latency | P0 |
| MIR-006 | Structural Requirements and DSL Coverage Gate | 检测链路已闭环；结构补齐能力转 MIR-010 | `qa_526d49332ed1` / `qa_c3e83dd7ad32` / `qa_a5f4b0253af3` | P0 |
| MIR-007 | Coverage-Aware Deterministic Grounding and LLM Handoff | 由 MIR-010 取代；不单独实施 | `qa_526d49332ed1` / `qa_c3e83dd7ad32` / `qa_a5f4b0253af3` | P0 |
| MIR-008 | Grounded Understanding Compact Output Contract | 功能已随 MIR-010.6 接入；token / fallback 专项指标未闭环 | MIR-010 fallback output token / schema invalid | P0 |
| MIR-009 | Retrieval Structural Relevance Reranker | 已实施并远端部署；收窄边界需持续回归 | dirty top_candidates / structure-irrelevant candidate noise | P0 |
| MIR-010 | Deterministic Form Assembler Corpus and Main-Path Control Flow Refactor | 主控制流已远端部署；680 全量暴露复杂结构未闭环；MIR-010.8 指标未闭环 | 680-query shape analysis / MIR-007 multi-round LLM latency | P0 |
| MIR-011 | Literal Filter Binding and Static Index-Miss Pass-through | 已远端闭环；L2 literal 澄清归零 | L2 `Service_001` / `svc-mpls-vpn-1004` / `MPLS-VPN` / `延迟=23` 澄清 | P0 |
| MIR-012 | Named Path Pattern Projection Role Binding | 待实施；680 全量新增 P0 缺口 | `qa_fe30ff3300d3` | P0 |

后续新增问题按 `MIR-013`、`MIR-014` 继续追加。

未闭环 MIR 实施处置（2026-05-30）：

| MIR | 处置类别 | 实施顺序 | 理由 |
| --- | --- | --- | --- |
| MIR-002 | B：取代/吸收，不再单独落地 | 无需实施 | 代码侧 hard cut 已完成；后续性能方向由 MIR-005 的 prompt slimming 经验和 MIR-010 的确定性主路径接管，不再继续围绕 decomposer token 单独决策。 |
| MIR-007 | B：由 MIR-010 取代，不单独落地 | 无需实施；仅保留 MIR-010.5 明确保留的机制 | MIR-010 取消 deterministic <-> LLM 多轮 handoff，因此 MIR-007 的 fingerprint 控制、交替循环检测和多轮 repair 不应再作为主控制流实现。 |
| MIR-008 | C：功能已接入，指标未闭环 | MIR-010.6 single-shot fallback 内部；后续补 token / fallback 专项采样 | compact contract 已随 fallback 路径接入，但原目标中的 completion token 收益、fallback schema retry 率和专项远端样本尚未单独量化。 |
| MIR-009 | 已执行：直接落地 | MIR-010 前置 | retrieval reranker 已作为确定性拼装和 single-shot fallback 的候选收窄层接入，后续只持续验证边界。 |
| MIR-010 | A：主干已落地，复杂结构与指标未闭环 | 继续按 failure reason 小步补齐；MIR-012 先处理 path pattern role binding | 主路径控制流重构已落地并远端部署；L2 literal 澄清已由 MIR-011 收口；2026-05-30 已远端确认一批 `coverage_failure` / `compiler_shape_mismatch` 小缺口闭环（投影同义词、`vertex_full`、唯一 owner 推断、vertex lookup limit、低分 vertex 噪声防误伤）。但 2026-05-31 680 全量重跑显示复杂结构仍大量失败：`generated=317`、`generation_failed=336`、`clarification_required=16`、`service_failed=11`，其中 `semantic_contract_unaligned=11`。MIR-010.8 的 680 指标已开始沉淀，但结果证明主干之外的复杂结构未闭环。 |

推荐实施顺序（已按此完成主干落地）：`MIR-009 -> MIR-010 最小确定性闭环 -> MIR-010.4/.5 原子控制流切换与 MIR-007 退役 -> 修订/实施 MIR-008 fallback compact contract -> 扩展 MIR-010 F4/F6/F8`。

实施进展（2026-05-30）：

| MIR | 当前实施状态 | 验证 / 剩余边界 |
| --- | --- | --- |
| MIR-008 | 已并入 MIR-010.6 single-shot fallback 路径；wrapper 侧 schema-bound prompt 已收敛为 compact selection contract，operation hint hydrate 可兼容旧式字符串 projection/group_by/measures/sort/assumptions，schema invalid 失败不再被误报为 compiler_shape_mismatch。 | 本地 CGA 回归 `600 passed`；fallback 只调用一次、输出 DSL、过结构覆盖和 self-validation。未闭环：completion token 收益、fallback 命中样本 schema retry 率、fallback 专项远端样本。 |
| MIR-009 | 已落地独立 structural reranker，接在 retriever 之后，保持“收窄不裁决”边界。 | 作为 MIR-010 前置组件参与远端部署；仍需持续回归确认 SRC/DST、PATH_THROUGH 等结构相关 edge 不被提前裁掉。 |
| MIR-010 | 已完成第 1-4 波主干：taxonomy / direction mapper / F1-F6 形态拼装器、F6 grouped top-N DSL 扩展、主控制流切换、MIR-007 多轮 repair 退役、single-shot fallback、clarification / concede 路径；2026-05-30 已补齐 deterministic 主路径 projection term 覆盖防线，并补齐 fallback schema / hydrate 防线。随后继续小步闭环 L2 残缺：`服务名称/编号/服务ID/等级值/服务质量等级` 投影同义词、`详细信息/节点/全部属性信息` -> `vertex_full`、vertex lookup 唯一属性 owner 推断、vertex lookup `LIMIT`、低分 token 级 vertex 噪声不阻断 0-hop 收敛。 | 本地 CGA `615 passed`。远端 L2 去重 86 条上一轮重跑：`generated=63`、`generation_failed=23`、`clarification_required=0`；testing 状态 `passed=55`、`issue_ticket_created=31`。针对上一轮 8 条 L2 投影 / vertex lookup 残缺样本，远端 smoke `smoke_l2_projection_vertex_fix4_20260530T155847Z` 先确认 7/8 passed，随后 `qa_38392098b2fc` 经低分 vertex 噪声防误伤补丁在 `smoke_single_qa383_fix5_20260530T160229Z` 通过；该抽样问题集 8/8 闭环。2026-05-31 680 全量重跑 `run680_20260531T045441Z` 已完成：`generated=317`、`generation_failed=336`、`clarification_required=16`、`service_failed=11`。结论：控制流和 L2 literal 已闭环，但复杂路径、fallback schema、coverage、compiler shape 和 path pattern projection role binding 未闭环。 |
| MIR-011 | 已补齐 literal request 构造与 resolver pass-through 防线：hyphenated 类型值不再被 ID 快路径抢走；无 attachment 的数值 literal 可回看前置 filter 属性；明确 owner/property 的非枚举等值 literal 在静态索引 miss 时 raw pass-through。 | 本地 CGA `600 passed`。远端 L2 去重 86 条重跑后 `clarification_required=0`；典型样本 `qa_a1801a24cede` 生成 `WHERE svc.name = 'Service_001'` 并通过，`qa_78040ceec879` 生成 `WHERE svc.latency = 23.0` 并通过。 |

## 2. 总体修改原则

1. **LLM 只填空，不独自决定最终结构**：LLM 可以做自然语言拆解和候选内选择，但字段绑定、路径约束、coverage 校验、DSL 编译必须有工程防线。
2. **不静默吞语义**：用户问题中的实义词必须进入正确语义槽位；如果无法进入，应 repair、clarification 或 generation_failed。
3. **coverage 要按槽位判断**：不是“词被某个候选命中”就算覆盖，而是必须进入语义上正确的位置，例如 projection、filter、group_by、order_by、path、limit。
4. **builder/compiler 不猜业务意图**：下游只编译明确 DSL，不把模糊结构自动窄化成看似可运行的 Cypher。
5. **错误要在靠前阶段暴露**：如果 binding plan 已经丢失用户要求，semantic validator 应拦住，不应等到 testing-agent 比对 golden 才发现。
6. **每个修改项都要沉淀 regression**：修复必须配套可复跑的 fixture、单元测试或 golden matrix slice。
7. **优先加防线，谨慎加词表/闸门**：每个 MIR 都要审查是否引入手工维护的词表或特例闸门。能从 semantic model、registry、schema 或 trace 派生的规则，不允许在代码中再写一份平行词表。
8. **宁可认输，不静默猜测**：当候选、方向、路径或形态不能被唯一确定时，系统应退回 LLM 兜底、澄清或 generation_failed；不得用“最高分”“默认方向”“最短路径”等启发式猜一个可运行但未被证明正确的结构。

## 3. MIR-001 Projection Slot Coverage and No Silent ID Downgrade

状态：已严格闭环。

### 3.1 闭环摘要

触发样本：`qa_9cfa692813d5`。旧链路已识别“ID、名称、元素类型、服务质量等级、带宽、时延”六个返回字段，但 grounded/builder 把 projection 塌缩成裸 `Service`，最终静默降级为 `RETURN svc.id`。

本 MIR 已闭环的关键原则：**显式 projection 字段必须落成 property-level projection；builder/compiler 不得把模糊 vertex projection 静默窄化成 ID。**

关键结果：

- decomposer 输出槽位角色，projection/filter/path 等语义由下游按 slot 消费。
- projection 字段从 semantic model 与候选 evidence 派生，落成确定性 property projection。
- semantic validator 暴露 `projection_coverage_missing`，self-validation 保留 RETURN shape 防线。
- builder/compiler 禁止裸 vertex projection 静默降级为 ID。
- projection regression slice 已覆盖单点多字段、单跳终点多字段、filter + projection。

验证与边界：

- 本地 regression 和远端重跑证明 projection 不再塌缩。
- MIR-001 只处理 projection 覆盖和静默 ID 降级；参数内联由 MIR-003 闭环，limit literal 误澄清由 MIR-004 闭环，多跳/聚合结构覆盖由 MIR-006 检测、MIR-010 主路径重构承接。

## 4. MIR-002 Decomposer Substantive Slot Hard Cut

状态：代码侧已完成；原性能遗留项已由 MIR-005 / MIR-010 吸收，不再单独落地。

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

结论：第一条 query 的 output tokens 从 baseline `270` 降至 `246`，约 `8.9%`，未达到 `30-40%` 预期；耗时中位数仍约 `10.5s`，未进入 `4-5s` 目标区间。2026-05-30 处置结论：该性能问题不再作为 MIR-002 的独立遗留项推进；decomposer 输出压缩已由 MIR-005 做小步闭环，端到端延迟主方向改为 MIR-010 的确定性主路径与 single-shot fallback 控制流。

## 5. MIR-003 Executable Cypher Inline Output with Template Trace

状态：已远端闭环。

### 5.1 闭环摘要

触发样本：`qa_c2508f2c0bac`。CGA 已正确把“金牌”解析为 `Gold` 并落到 `Service.quality_of_service`，但对外输出仍是参数化模板，testing-agent 只执行 Cypher 字符串，导致 TuGraph 报 `Undefined parameter: $quality_of_service`。

本 MIR 已闭环的关键契约：**CGA 对外主输出必须是可直接执行的内联 Cypher；参数化模板和参数只作为 compiler 内部表示与 trace 观测产物。**

关键结果：

- compiler 输出拆分为 `cypher_template`、`parameters`、`parameter_sources`、`cypher_executable` 和对外主 `cypher`。
- 字面值内联统一走 literal inliner；来源不明或 unresolved literal 不允许内联。
- self-validation 校验最终 executable query，禁止残留 `$param`。
- trace 保留模板、参数和最终执行文本；运行中心可区分三者。
- 远端 smoke 已验证 `qa_c2508f2c0bac` 不再因参数占位符失败。

边界：

- MIR-003 只改变 Cypher 输出契约，不处理 Top-N、IP owner/property、多跳路径方向。
- `qa_c2508f2c0bac` 若仍出现 strict 口径差异，已不属于参数执行契约问题。

## 6. MIR-004 Slot-Authoritative Literal Candidate Filtering

### 6.1 闭环摘要（2026-05-29）

触发样本：`qa_c3e83dd7ad32`。题干中的 `返回前3名` 原本应表达 top-N limit，但旧链路把 `3` 同时作为 `slot=limit` 的结构词和 `literal_candidates` 中的 number literal，随后构造 literal request 并在 resolver 中查 `Tunnel.elem_type = 3`，最终错误转成 `clarification_required`。

本 MIR 已按原始失败点闭环：**slot 是词语义角色的唯一权威来源**。pipeline 构造 literal request 前会按 `substantive_terms[].slot` 做结构过滤；`limit/order_by/group_by/path/projection` 等结构槽位词不再送 literal resolver，`filter/unknown` 槽位的真实过滤值保持原解析路径。

关键结果：

- `literal_candidates` 的定义收紧为“过滤/匹配值”，结构控制词只属于对应 slot。
- literal request 构造前按 slot 过滤，不依赖“是不是数字”等值形态。
- trace 记录 `skipped_literal_candidates` 和跳过原因。
- regression 覆盖 limit 数字和真实 filter 数字对照，确保“返回前3名”的 `3` 被跳过，“带宽为3”的 `3` 仍可解析。
- 远端重跑中 `qa_c3e83dd7ad32` 已不再因 `3` literal 进入澄清。

### 6.2 边界

- MIR-004 闭环的是“结构控制词被误送 literal resolver 并触发澄清”的失败点，不代表 `qa_c3e83dd7ad32` 的完整语义已经通过。
- 该样本剩余失败是 location 分组计数、按数量降序和 `LIMIT 3` 没有落入 DSL/Cypher，已转入 MIR-006 的结构覆盖闸门处理。
- `literal_candidates` 仍是独立于 `substantive_terms` 的并列数组，schema 层仍可表达“同一词既是结构控制又是 literal”的矛盾。更根本的 literal 信息内嵌重构不在本 MIR 范围内，只有同族问题再次出现时再另开 MIR。

## 7. MIR-005 Decomposer Redundant Output Field Removal

### 7.1 闭环摘要（2026-05-29）

触发问题：`question_decomposer` 使用 `qwen3-32b` 时 completion token 偏高，端到端耗时约 `9s` 量级；在不换模型、不引入小模型和不改 schema version 的前提下，本 MIR 只处理可删除的冗余输出。

MIR-005 已按功能目标闭环：decomposer LLM 输出中的 `target_concepts`、`relation_phrases`、`stopword_terms` 已删除；`attached_to` 保持 optional，并在 prompt 中明确仅消歧需要时填写；`modality_terms`、`time_terms`、`unparsed_terms` 本轮保留。

关键结果：

- `target_concepts`、`relation_phrases`、`stopword_terms` 从 LLM schema/prompt/output 删除。
- retriever 与下游消费改为读取 `substantive_terms`、literal、原问题和既有工程信号。
- `attached_to` 仅在消歧需要时填写，避免无条件输出。
- `modality_terms`、`time_terms`、`unparsed_terms` 因仍有报告/coverage 消费，暂不删除。

验证结果：

- 本地：`PYTHONPATH=. pytest services/cypher_generator_agent/tests -q` -> `517 passed`；`PYTHONPATH=. pytest tests/test_runtime_results_service_api.py -q` -> `32 passed`。
- 轻量 LLM 采样：`查询所有服务使用的隧道，返回隧道的 ID、名称和带宽` 的 completion tokens 从 MIR-002.7 约 `246` 降到 `197`；`Gold 服务使用了哪些隧道` 从约 `251` 降到 `173`。
- 远端：部署标识 `9aee174+mir005-20260529`；8 条样本的 decomposer 输出字段均不再包含 `target_concepts/relation_phrases/stopword_terms`。
- 远端 8 样本 final verdict 从 MIR-004 后的 `pass=4/fail=3/pending=1` 变为 `pass=5/fail=2/pending=1`。该变化不代表路径语义问题完全解决，相关结构覆盖已进入 MIR-006。

结论：schema/prompt slimming 已闭环，旧三字段不再进入当前 decomposer 输出；性能收益存在但不均匀，未稳定达到约 `155 completion tokens` 的原目标。本 MIR 不继续追加压缩策略，后续若继续优化，应另开 MIR 处理 prompt/schema 体积、guided decoding 或架构级合并。

### 7.2 剩余风险 / 未来方向

- 在单模型 `qwen3-32b` 且 TPOT 固定的约束下，仅靠删除 decomposer 输出字段无法保证整条问数链路进入 `5s` 以内。
- 若继续追求延迟，应另开 MIR 评估 prompt/schema 进一步瘦身、provider guided decoding、decomposer 与 grounded_understanding 合并，或简单查询确定性快速路径。
- 本 MIR 不采用缩短 key 名、数组位置编码、slot 单字符化等有损压缩；除非团队接受可读性和维护性代价，否则不作为默认方向。

### 7.3 同族后续问题（转 MIR-008）

原 MIR-007 修复循环验证后的远端 8 样本重跑显示，`grounded_understanding` 暴露出与 MIR-005 同族的问题：LLM 被要求输出大量“可由工程代码查回、推导或计算”的字段，导致 completion token 偏高、schema retry 成本高，并在复杂结构样本中触发 `grounded_understanding_schema_invalid`。

这类问题与 MIR-005 的共同原则一致：**LLM 只输出它必须裁决的信息，复制、推导、coverage 计算和解释性文本下沉到工程代码。**

但 MIR-005 的实施范围已经闭环，且明确不改 `grounded_understanding_v1` schema、不动 decomposition 之外的 prompt。因此，grounded understanding 的 compact 输出契约不并入 MIR-005 已完成范围，单独进入 MIR-008；2026-05-30 后该 MIR 仅作为 MIR-010 single-shot fallback 的 compact 契约推进。

## 8. MIR-006 Structural Requirements and DSL Coverage Gate

状态：已实施。结构需求派生、DSL 覆盖闸门、trace 阶段和 repair context 回灌已落地；远端 8 样本重跑证明闸门能在 compile 前拦截结构覆盖不足的 DSL。当前未闭环的是“发现缺失结构之后如何补齐”：原先转 MIR-007 的多轮 repair 路径已被 MIR-010 取代，后续改为确定性形态拼装主路径与 single-shot fallback。

### 8.1 背景

触发样本：

| QA ID | 问题 | 当前生成 | 正确结果 | 当前判断 |
| --- | --- | --- | --- | --- |
| `qa_526d49332ed1` | 查询所有服务经过隧道穿过的网元的名称和厂商。 | `MATCH (tun:Tunnel)-[:PATH_THROUGH]->(ne:NetworkElement) RETURN ne.name AS network_element_name, ne.vendor AS network_element_vendor` | `MATCH (a:Service)-[:SERVICE_USES_TUNNEL]->(b:Tunnel)-[:PATH_THROUGH]->(c:NetworkElement) RETURN c.name, c.vendor` | 丢失 `Service -> Tunnel` 前缀路径约束；当前数据下行数碰巧一致，testing-agent 语义 verdict 曾判 pass，但 strict 失败。 |
| `qa_c3e83dd7ad32` | 统计服务使用的隧道源节点所在位置的网元数量，按数量降序排列，返回前3名。 | `MATCH (tun:Tunnel)-[:TUNNEL_SRC]->(ne:NetworkElement) RETURN ne.id AS network_element_id` | `MATCH (s:Service)-[:SERVICE_USES_TUNNEL]->(:Tunnel)-[:TUNNEL_SRC]->(ne:NetworkElement) WHERE ne.location IS NOT NULL RETURN ne.location AS location, count(*) AS cnt ORDER BY cnt DESC LIMIT 3` | MIR-004 已消除 limit 数字误澄清；剩余失败是路径约束、aggregate、group_by、order_by、limit 均未落入 DSL/Cypher。 |
| `qa_a5f4b0253af3` | 查询所有服务使用的隧道目的网元上的端口ID、名称和状态。 | `MATCH (tun:Tunnel)-[:TUNNEL_SRC]->(ne:NetworkElement) RETURN ne.id AS network_element_id` | `MATCH (a:Service)-[:SERVICE_USES_TUNNEL]->(:Tunnel)-[:TUNNEL_DST]->(:NetworkElement)-[:HAS_PORT]->(d:Port) RETURN d.id AS port_id, d.name AS port_name, d.status AS port_status` | 路径 hop 不足，终点对象错，projection 错；`TUNNEL_DST` 被选成 `TUNNEL_SRC` 的方向正确性不由本闸门直接保证。 |

这些样本的共同问题不是 alias 口径，也不是 literal owner/property 绑定，而是 CGA 生成了局部合法的 DSL/Cypher，却没有证明题干中已识别出的结构要求已经进入最终 DSL。现有 coverage 会把 `substantive_terms` 词命中候选视为覆盖，但不会校验它们是否落在正确结构位置，例如 path hop、aggregate、group_by、order_by、limit、projection。

关键设计决策：

1. `structural_requirements` 不是新的 LLM 输出字段，而是工程代码从现有 `question_decomposition_v1` 确定性派生的视图。
2. decomposer 仍保持领域无关，只输出 `intent_type`、`output_shape`、`substantive_terms[].slot`、`literal_candidates` 等表层信号；不让 decomposer 输出 edge 名、图 label、path pattern id、`TUNNEL_DST` 这类领域结构。
3. 覆盖闸门只校验结构存在性和数量充分性，不校验结构正确性。方向是否选成 `TUNNEL_DST`、measure 是否选对字段、group_by 的具体属性是否正确，不在本 MIR 的直接保证范围。

### 8.2 失效链路

| 层级 | 失效点 | 影响 |
| --- | --- | --- |
| question_decomposer | 只输出表层词和粗粒度 slot；有 `path/group_by/order_by/limit` 信号，但没有结构化 path chain、path direction、aggregate measure、sort target。 | 下游可以知道“题干要求某类结构”，但没有直接可校验的结构需求视图。 |
| structural requirements 缺失 | pipeline 没有把 decomposition 归整成可复用的 `requires_aggregate/requires_group_by/requires_limit/path_terms` 等需求合同。 | grounded_understanding 和 validator 只能消费零散词，不知道最终 DSL 需要满足哪些结构性最低要求。 |
| grounded_understanding | 可以选出局部高分候选，例如 `Tunnel -> NetworkElement`，但丢掉题干中的 `Service -> Tunnel` 或聚合/top-N 结构。 | 生成的 binding plan 局部合法，但语义覆盖不足。 |
| semantic_validator / coverage | 只校验已有 binding/DSL 的合法性和 projection coverage，不校验 decomposition 中的结构槽位是否进入 DSL。 | 错误继续流向 compiler，最终变成可执行但不等价的 Cypher。 |
| testing-agent verdict | 部分样本执行结果行数或语义 review 可能碰巧通过。 | `qa_526d49332ed1` 这类路径约束缺失有误判 pass 风险，testing 侧结构等价增强需另线处理。 |

### 8.3 修改目标

- 新增一个纯工程派生层：从现有 decomposition 输出确定性派生 `structural_requirements`，不经过 LLM，不改 `question_decomposition_v1` schema version。
- 在 decomposer prompt 中补充顺序契约：`substantive_terms` 应按词语在 `original_question` 中首次出现的顺序输出。
- 派生层不盲信 LLM 数组顺序；对 path terms 从 `original_question` 反查位置并排序，数组顺序只作为 fallback。
- 在 DSL 构建后、compile 前增加结构覆盖闸门，校验 `structural_requirements` 是否进入 DSL 的对应结构。
- 覆盖不全时进入 repair，向 grounded_understanding 回灌具体缺失项；repair 上限内仍补不齐再升级为 generation_failed 或既有失败路径，不直接 ask_user。
- trace 中记录 `structural_requirements`、覆盖结果、缺失项、path 顺序置信度和降级行为，便于运行中心排障。

非目标：

- 不让 decomposer LLM 输出新的 `structural_requirements` 字段。
- 不扩展 decomposer 为图领域理解器；不输出 edge 名、label、property 名、direction、path pattern id。
- 不校验 Cypher 字符串；闸门只读 DSL 结构。
- 不处理 alias 口径问题；alias 归 testing strict contract 或 compiler alias 规则另线处理。
- 不处理 literal owner/property 绑定；`qa_6494b2085699` 归 literal resolver 线另开 MIR。
- 不保证路径方向正确性、measure 字段正确性、sort target 正确性；这些需要 grounded_understanding 选择能力和 testing-agent 结构等价增强共同兜底。

### 8.4 子 IR 总览

| 子 IR | 名称 | 优先级 | 估算 | 角色 | 依赖 |
| --- | --- | --- | --- | --- | --- |
| MIR-006.0 | Baseline and Derivation Feasibility Audit | P0 | S | QA/backend | 无 |
| MIR-006.1 | Prompt Order Contract and Structural Requirements Derivation | P0 | M | backend/LLM | MIR-006.0 |
| MIR-006.2 | Requirements-to-DSL Mapping Rules | P0 | S | backend | MIR-006.1 |
| MIR-006.3 | DSL Structural Coverage Gate | P0 | M | backend | MIR-006.2 |
| MIR-006.4 | Missing Coverage Repair Feedback | P0 | S | backend | MIR-006.3 |
| MIR-006.5 | Regression Matrix and Boundary Tests | P0 | S | QA/backend | MIR-006.1 到 MIR-006.4 |

推荐顺序：

```text
MIR-006.0 -> MIR-006.1 -> MIR-006.2 -> MIR-006.3 -> MIR-006.4 -> MIR-006.5
```

### MIR-006.0 Baseline and Derivation Feasibility Audit

目标：确认现有 decomposition 信号可以派生哪些领域无关结构需求，并为触发样本标注闸门能抓到的范围。

建议文件：

```text
docs/experiments/2026-05-28-runtime-center-cga-job-analysis.md
services/cypher_generator_agent/app/decomposition/models.py
services/cypher_generator_agent/app/decomposition/prompt.py
services/cypher_generator_agent/app/core/pipeline.py
services/cypher_generator_agent/app/validation/coverage.py
services/cypher_generator_agent/tests/integration/test_pipeline_mvp.py
```

开发内容：

- 读取最新 trace，记录 `qa_526d49332ed1`、`qa_c3e83dd7ad32`、`qa_a5f4b0253af3` 的 decomposition、grounded_understanding、binding plan、DSL。
- 对每条触发样本区分“decomposition 已识别但 DSL 没落实”和“decomposition 本身没有结构真值”的部分：
  - `qa_c3e83dd7ad32`：`top_n/group_by/order_by/limit` 已有粗粒度 slot，闸门应能完全抓住结构缺失。
  - `qa_526d49332ed1`：path terms 足以提示 multi-hop 需求，闸门应能抓住 hop 数量不足，但不直接指出具体缺少 `Service -> Tunnel`。
  - `qa_a5f4b0253af3`：path terms 和 projection terms 足以提示 hop/projection 不足；`TUNNEL_DST` vs `TUNNEL_SRC` 的方向正确性不由本闸门直接保证。
- 明确 alias mismatch、literal owner/property、testing-agent 结构等价 verdict 不是本 MIR active 范围。
- 记录当前实现下这些样本为何未被 semantic_validator 拦截，作为验收对照。

验收：

- 三条触发样本都有“能抓 / 部分能抓 / 抓不住”的明确标注。
- 文档中写明方向正确性和具体 edge 正确性不是本闸门直接保证范围。
- 当前失败 trace 已固化为 baseline，后续可以对比闸门触发的缺失项。

### MIR-006.1 Prompt Order Contract and Structural Requirements Derivation

目标：新增确定性派生层，从现有 decomposition 输出得到 `structural_requirements`，并稳定 path terms 顺序。

建议文件：

```text
services/cypher_generator_agent/app/decomposition/prompt.py
services/cypher_generator_agent/app/core/pipeline.py
services/cypher_generator_agent/app/validation/coverage.py
services/cypher_generator_agent/app/observability/trace.py
services/cypher_generator_agent/tests/decomposition/test_term_classification.py
services/cypher_generator_agent/tests/validation/test_coverage.py
```

开发内容：

- prompt 增加顺序契约：`substantive_terms` 必须按词语在 `original_question` 中首次出现的顺序输出。
- 新增 `structural_requirements` 派生逻辑，输入为现有 decomposition，不调用 LLM，不引入图 schema 知识。
- 建议派生字段：
  - `requires_aggregate`：从 `intent_type=count|aggregate|top_n` 或聚合类 projection 词派生。
  - `requires_group_by`：存在 `slot=group_by` 时为 true。
  - `requires_order_by`：存在 `slot=order_by` 时为 true；可从“升序/降序/最多/最高/最少/最低”等表层词派生排序方向，但不派生 sort target。
  - `requires_limit`：存在 `slot=limit` 时为 true，并从 limit terms 中提取整数值；提取不到时记录 `value=null`。
  - `path_terms`：从 `slot=path` 派生，按原文位置排序，附带 `position` 与 `order_confidence`。
  - `projection_terms`：从 `slot=projection` 派生，继续服务于 MIR-001 的 projection coverage。
- 位置反查规则：
  - 使用 `substantive_terms[].text` 的原始表层文本去 `original_question` 中查找，不使用规范化后的替代文本。
  - 子串包含时优先处理更长 term；同一位置出现多个 term 时，按原文位置优先、term 长度降序、原数组顺序兜底，避免“服务”抢占“服务质量等级”的位置解释。
  - 同一词多次出现时默认取首次出现位置，并在文档和 trace 中记录这是已知近似。
  - 找不到位置时 fallback 到 `substantive_terms` 数组顺序，并标记 `order_confidence=low`。
- position/order 只用于 path terms 排序；aggregate、group_by、order_by、limit 使用存在性或值提取，不依赖位置。

验收：

- 不修改 `question_decomposition_v1` schema version。
- LLM raw output 不新增 `structural_requirements` 字段。
- prompt 中明确包含 substantive term 按原文顺序输出的契约。
- 派生层可输出 `qa_c3e83dd7ad32` 的 aggregate/group_by/order_by/limit 需求。
- 派生层可输出 `qa_526d49332ed1` 和 `qa_a5f4b0253af3` 的 ordered path terms；当位置不可验证时降级为 low confidence。
- 子串包含、重复词、找不到位置三个边界均有测试。

### MIR-006.2 Requirements-to-DSL Mapping Rules

目标：定义 `structural_requirements` 到 DSL 结构的映射检查规则，作为覆盖闸门的规格。

建议文件：

```text
services/cypher_generator_agent/app/dsl/models.py
services/cypher_generator_agent/app/dsl/parser.py
services/cypher_generator_agent/app/validation/semantic_validator.py
services/cypher_generator_agent/app/validation/coverage.py
services/cypher_generator_agent/tests/validation/test_coverage.py
```

开发内容：

| structural requirement | DSL 应有结构 | 说明 |
| --- | --- | --- |
| `requires_aggregate=true` | 至少一个 `aggregate` / `metric_aggregate` / 聚合 query shape | 只校验聚合结构存在，不校验 measure 字段是否语义正确。 |
| `requires_group_by=true` | aggregate 结构中的 `group_by` 非空 | 只校验存在性，不校验具体属性正确性。 |
| `requires_order_by=true` | DSL 中存在 sort / `order_by` 操作 | 如果从表层词可确定 asc/desc，则校验排序方向；不校验 sort target。 |
| `requires_limit.value=N` | DSL 中存在 `limit` 且值为 `N` | 若 value 提取不到，只校验存在 limit。 |
| `path_terms` 表示 multi-hop | DSL 中 hop 数量足够，或使用 named/variable path 结构 | 只校验数量充分性和顺序置信度，不校验 edge 名或 path direction。 |
| `projection_terms` | projection items 覆盖所需字段词 | 沿用并收敛 MIR-001 coverage，不引入 alias 校验。 |

- path 规则采用保守分级：
  - path terms 少且 `order_confidence=high` 时，允许 single-hop。
  - path terms 数量较多、包含多个 path action 或多个概念词时，要求 multi-hop DSL、named path 或 variable path。
  - `order_confidence=low` 时只做数量充分性检查，不做顺序检查，并在 trace 标记“顺序未验证”。

验收：

- 映射规则只依赖 `structural_requirements` 和 DSL，不读取 Cypher 字符串。
- 规则文档明确区分“结构存在性/数量充分性”和“具体语义正确性”。
- alias、literal owner/property、edge direction 正确性不进入规则。

### MIR-006.3 DSL Structural Coverage Gate

目标：在 DSL 构建后、compile 前执行结构覆盖闸门，提前拦截局部合法但结构覆盖不足的 DSL。

建议文件：

```text
services/cypher_generator_agent/app/core/pipeline.py
services/cypher_generator_agent/app/validation/semantic_validator.py
services/cypher_generator_agent/app/validation/models.py
services/cypher_generator_agent/app/repair/controller.py
services/cypher_generator_agent/app/observability/stages.py
services/cypher_generator_agent/tests/integration/test_pipeline_mvp.py
```

开发内容：

- 在 DSL builder 输出后、compiler 输入前调用结构覆盖闸门。
- 输入：`structural_requirements`、restricted DSL、必要的 coverage 上下文。
- 输出：结构覆盖报告，包含：
  - `covered_requirements`
  - `missing_requirements`
  - `path_order_confidence`
  - `degraded_checks`，例如 `path_order_not_verified`
  - `reason_code=structural_requirement_uncovered`
- 当存在 missing requirements 时，不进入 compiler。
- `order_confidence=low` 时 path 检查降级为数量充分性，不使用不可靠顺序触发顺序类错误。

验收：

- `qa_c3e83dd7ad32` 的当前 DSL 会因缺 aggregate/group_by/order_by/limit 被闸门拦截。
- `qa_526d49332ed1` 的当前 single-hop DSL 会因 multi-hop path coverage 不足被闸门拦截。
- `qa_a5f4b0253af3` 的当前 single-hop DSL 会因 path/projection 覆盖不足被闸门拦截；但测试不得声称闸门已直接校验 `TUNNEL_DST` 方向正确性。
- 已完整覆盖的简单 single-hop 查询不误报。

### MIR-006.4 Missing Coverage Repair Feedback

目标：结构覆盖不足时进入 repair，带具体缺失项回灌 grounded_understanding，而不是直接澄清用户。

建议文件：

```text
services/cypher_generator_agent/app/repair/controller.py
services/cypher_generator_agent/app/repair/models.py
services/cypher_generator_agent/app/understanding/prompt.py
services/cypher_generator_agent/app/core/pipeline.py
services/cypher_generator_agent/tests/integration/test_pipeline_mvp.py
services/cypher_generator_agent/tests/repair/test_fingerprint.py
```

开发内容：

- 将 `structural_requirement_uncovered` 归类为 repairable semantic error。
- repair context 中包含缺失项，例如：
  - `missing_aggregate`
  - `missing_group_by`
  - `missing_order_by`
  - `missing_limit`
  - `path_hop_insufficient`
  - `projection_terms_uncovered`
- grounded_understanding prompt 在 repair_context 存在时，要求优先补齐缺失结构，仍只能从 top_candidates 中选择，不得发明候选。
- 复用现有 repair 上限和震荡检测；超过上限后升级为 generation_failed 或既有失败路径，不向用户询问“是否需要 group_by”这类用户无法回答的问题。

验收：

- 结构覆盖缺失不会走 `clarification_required`。
- repair prompt / trace 能看到具体 missing requirements。
- repair 上限和震荡检测对结构覆盖错误生效。
- 无候选可补齐时，最终失败原因能明确指向 `structural_requirement_uncovered` 或其派生原因。

### MIR-006.5 Regression Matrix and Boundary Tests

目标：将结构覆盖闸门纳入回归，覆盖触发样本、防误伤样本和位置反查边界。

建议文件：

```text
services/cypher_generator_agent/tests/integration/test_pipeline_mvp.py
services/cypher_generator_agent/tests/validation/test_coverage.py
services/cypher_generator_agent/tests/decomposition/test_term_classification.py
services/cypher_generator_agent/tests/fixtures/golden_questions.yaml
docs/experiments/2026-05-28-runtime-center-cga-job-analysis.md
```

开发内容：

- 增加触发样本回归：
  - `qa_c3e83dd7ad32`：当前错误 DSL 必须被闸门拦截，修复后应包含 aggregate/group_by/order_by/limit。
  - `qa_526d49332ed1`：当前 single-hop DSL 必须被 path coverage 拦截。
  - `qa_a5f4b0253af3`：当前 single-hop + 错终点 projection 必须被 path/projection coverage 拦截；方向正确性保留为后续 testing-agent 结构等价线。
- 增加防误伤对照：
  - 一个完整 single-hop traversal，不应因 path terms 被误判 multi-hop。
  - 一个基础 count 查询，应通过 aggregate 结构检查。
  - 一个普通多字段 projection 查询，应沿用 MIR-001 coverage，不受 alias 影响。
- 增加边界测试：
  - 子串包含：`服务` / `服务质量等级`、`网元` / `网元数量`。
  - 同词多次出现：默认取首次位置并记录近似。
  - term 找不到原文位置：fallback 数组顺序，`order_confidence=low`。
  - `order_confidence=low` 时 path 检查只校验数量，不校验顺序。

验收：

- 结构覆盖 slice 可独立运行。
- 三条触发样本的当前错误结构均能在 compile 前暴露。
- 防误伤样本不新增 false positive。
- 所有边界规则都有单测覆盖。

### 8.5 实施结果与远端验证

闭环部分：

- `structural_requirements` 由工程代码从现有 decomposition 确定性派生，未新增 LLM 输出字段，未修改 `question_decomposition_v1` schema version。
- decomposer prompt 已增加 substantive terms 按原文顺序输出的契约；派生层按 `original_question` 反查 path term 位置，并在位置不可验证时降级。
- pipeline 已在 `dsl_builder` / `dsl_parser` 后、`cypher_compiler` 前增加 `dsl_structural_coverage_gate`。
- 结构覆盖缺失会生成 `structural_coverage_missing` repairable issue，不进入 compiler，不直接 ask_user。
- grounded understanding repair prompt 已增加 `structural_repair_guidance`，对 aggregate/group_by/order_by/limit/path/projection 缺失给出显式补齐指令，仍约束只能从 `top_candidates` 选择，不得发明 schema 对象。
- 本地验证：`PYTHONPATH=. pytest -q && git diff --check` -> `684 passed, 2 warnings`。

远端部署与重跑：

- 首次结构闸门部署标识：`627f8a1+mir006-20260529`。
- repair prompt 补齐部署标识：`627f8a1+mir006-repair-20260529`。
- 重跑时间：2026-05-29 20:59-21:01 左右（Asia/Shanghai）。
- 8 条 question 全部提交成功，HTTP `204`。
- 汇总：`pass=4`，`fail=3`，`pending=1`；生成状态为 `generated=4`、`generation_failed=3`、`clarification_required=1`。

| QA ID | MIR-006 后状态 | 证据 | 判断 |
| --- | --- | --- | --- |
| `qa_526d49332ed1` | `generation_failed / repair_binding_oscillation` | trace 顺序为 `dsl_structural_coverage_gate failed -> repair_controller repair_with_llm -> grounded_understanding attempt=2 with repair_context -> dsl_structural_coverage_gate failed -> repair_controller generation_failed`。 | 闸门已拦截路径覆盖不足；repair 未能补出完整 multi-hop path。 |
| `qa_c3e83dd7ad32` | `generation_failed / repair_binding_oscillation` | 已不再因 `3` literal 澄清；结构闸门拦截 aggregate/group_by/order_by/limit 缺失，repair 后仍失败。 | 发现能力已闭环，top-N 聚合补齐能力未闭环。 |
| `qa_a5f4b0253af3` | `generation_failed / repair_binding_oscillation` | 结构闸门拦截 hop/projection 覆盖不足，repair 后仍失败。 | 闸门能抓覆盖不足，但多跳路径和方向词补齐未收敛。 |
| `qa_6494b2085699` | `clarification_required` | literal resolver 后 repair controller 决策 `ask_user`，澄清 `10.0.0.4`。 | 仍是 literal owner/property 绑定问题，不属于 MIR-006。 |
| 其余 4 条 | `generated / final_verdict=pass` | `qa_76e37da317b4`、`qa_9cfa692813d5`、`qa_c2508f2c0bac`、`qa_c80a82efe561` 均通过。 | 结构闸门没有误伤基础 count、projection、枚举 literal 和单跳 traversal 样本。 |

当前结论：

- MIR-006 已把风险从“静默生成错误 Cypher”推进为“结构覆盖不足时 CGA 内部失败并留下 trace”。这是本 MIR 的主要闭环。
- 仍未解决的是 grounded_understanding 在收到具体 missing requirements 后如何稳定补出新结构。后续应另开或追加一个聚焦“结构补齐选择能力”的 MIR，而不是继续扩大覆盖闸门。

### 8.6 剩余风险 / 未来方向

- 本 MIR 不保证路径方向正确性。`qa_a5f4b0253af3` 中 `TUNNEL_DST` 被选成 `TUNNEL_SRC` 的问题，本闸门最多通过 hop/projection 覆盖不足触发 repair，不能直接证明方向错。方向正确性需要 grounded_understanding 选择能力和 testing-agent 结构等价 verdict 增强另线处理。
- 本 MIR 不解决 alias strict mismatch。`qa_9cfa692813d5`、`qa_c80a82efe561`、`qa_c2508f2c0bac` 的 strict failure 应单独判断 alias 是否属于输出契约，再决定修 compiler alias 规则或放宽 strict_check。
- 本 MIR 不解决 literal owner/property 绑定。`qa_6494b2085699` 应另开 literal owner 绑定 MIR，优先消费 `attached_to` 与 owner 线索定位 expected property。
- path term 的位置反查使用首次出现位置处理重复词，这是已知近似。若后续出现同词多次且代表不同 path 角色的高频样本，再考虑更强的 span 对齐或 phrase segmentation。
- testing-agent final verdict 曾把路径约束缺失样本判为 pass，说明下游仍需结构等价比对。该问题不阻塞本 MIR，但应作为独立 testing-agent 改造线记录。
- 当前 repair 仍可能在结构缺失上产生 A -> B -> A 式震荡。下一步需要增强结构补齐能力本身，例如 top-N 聚合 shape 选择、多跳 path pattern/binding 选择、方向词到 edge 的选择，而不是只增强错误检测。

## 9. MIR-007 Coverage-Aware Deterministic Grounding and LLM Handoff

状态：由 MIR-010 取代，不再单独实施。

处置结论（2026-05-30）：本 MIR 保留为震荡问题的历史诊断和反例设计，但不作为后续实现入口。MIR-010 已把主控制流从“deterministic <-> LLM 多轮 handoff / repair loop”改为“确定性形态拼装主路径 -> LLM single-shot fallback -> 澄清或认输”。因此，本 MIR 中服务于多轮 handoff 的 fingerprint-aware handoff、missing requirements 交替循环检测、repair 场景反复调用 grounded understanding 等机制退役；仅保留 self-validation、structural coverage gate、明确 failure reason、fingerprint 诊断等由 MIR-006 / MIR-010 继续使用的防线。

若后续实施时发现 MIR-010 覆盖不了某类结构补齐问题，应新增 MIR 或修订 MIR-010，而不是回到 MIR-007 的多轮修复循环。

### 9.1 背景

MIR-006 已把结构覆盖不足从“静默生成错误 Cypher”推进为“compile 前失败并进入 repair”，但三条触发样本在 repair 后仍以 `repair_binding_oscillation` 退出：

| QA ID | 题干要求 | 当前重复结构 | 正确方向 |
| --- | --- | --- | --- |
| `qa_526d49332ed1` | 服务经过隧道穿过的网元，返回网元名称和厂商。 | `Tunnel -[:PATH_THROUGH]-> NetworkElement` 单跳。 | `Service -[:SERVICE_USES_TUNNEL]-> Tunnel -[:PATH_THROUGH]-> NetworkElement`。 |
| `qa_c3e83dd7ad32` | 服务使用的隧道源节点位置，按位置计数、按数量降序、返回前 3。 | `Tunnel -[:TUNNEL_SRC]-> NetworkElement` 单跳，返回 `ne.id`。 | `Service -> Tunnel -> NetworkElement`，`GROUP BY location`，`count(*)`，`ORDER BY cnt DESC`，`LIMIT 3`。 |
| `qa_a5f4b0253af3` | 服务使用的隧道目的网元上的端口 ID、名称、状态。 | `Tunnel -[:TUNNEL_SRC]-> NetworkElement` 单跳，返回 `ne.id`。 | `Service -> Tunnel -[:TUNNEL_DST]-> NetworkElement -[:HAS_PORT]-> Port`，返回 Port 字段。 |

trace 证据显示：第二轮 grounded understanding 虽然带着 `repair_context` 进入，但 `llm_call_count=0`，因为 `_select_grounded_understanding()` 先执行 deterministic grounding，并再次返回同一个 `single_hop` plan。结构闸门再次失败后，repair controller 发现 binding fingerprint 重复，于是判定 `repair_binding_oscillation`。

一句话核心：**MIR-006 已经能发现结构缺失，但 deterministic grounding 当前仍拥有无条件优先权；它能力不足时会抢先返回同一个简单结构，导致 LLM 修复没有真正接管。**

### 9.2 失效链路

| 层级 | 失效点 | 影响 |
| --- | --- | --- |
| deterministic grounding | 只支持 count、单跳、单点 lookup 等简单结构，但在 repair 场景仍优先返回。 | 多跳、top-N 聚合、projection 补齐无法生成。 |
| 选择策略 | deterministic plan 未先和 `structural_requirements` 做覆盖预检。 | 一个明显缺 aggregate/group_by/order_by/limit/path hop 的 plan 仍能短路 LLM。 |
| repair 交接 | 有 `repair_context` 时，deterministic 不要求补齐 missing requirements。 | repair 指令没有改变输出结构。 |
| fingerprint 防线 | 重复 fingerprint 只在 repair controller 末端暴露。 | 系统先浪费一轮 repair，再以震荡失败退出。 |
| LLM 修复通道 | deterministic 返回非空后不调用 `GroundedUnderstandingSelector`。 | LLM 没有机会根据缺失项重新选择 multi-hop/top-N 结构。 |

### 9.3 修改目标

- 将 deterministic grounding 定位为**确定性拼装器**，只在结构需求可覆盖、候选唯一、fingerprint 有变化时返回。
- 增加 coverage-aware gating：deterministic 输出必须先覆盖 `structural_requirements`，否则让位给 LLM。
- 增加 repair-aware gating：存在 `repair_context` 时，deterministic 必须补齐本轮 missing requirements；不能补齐就不得返回。
- 增加 fingerprint-aware handoff：如果 deterministic plan 与上一轮 binding/dsl fingerprint 等价，直接交给 LLM，避免已知震荡。
- 只补有限、可验证的 deterministic 能力：唯一多跳路径、唯一 top-N 聚合骨架、唯一 projection completion。
- 保留 LLM 作为语义裁决者：路径方向、候选歧义、group_by/sort target 多选、候选缺失等情况由 LLM repair 或最终失败处理。

非目标：

- 不把 deterministic grounding 扩展成完整语义推理器。
- 不禁用 deterministic grounding；简单、确定、覆盖完整的查询仍走快速路径。
- 不改 decomposer schema version，不让 decomposer 输出图领域结构。
- 不解决 alias strict mismatch、literal owner/property 绑定、testing-agent 结构等价 verdict；这些仍属独立 MIR 线。
- 不引入 raw Cypher fallback，不绕过 DSL/binding/validator。

### 9.4 子 IR 总览

| 子 IR | 名称 | 优先级 | 估算 | 角色 | 依赖 |
| --- | --- | --- | --- | --- | --- |
| MIR-007.0 | Oscillation Baseline and Decision Contract | P0 | S | QA/backend | MIR-006 |
| MIR-007.1 | Coverage/Fingerprint-Aware Grounding Policy | P0 | M | backend | MIR-007.0 |
| MIR-007.2 | Narrow Deterministic Structure Builders | P0 | M | backend | MIR-007.1 |
| MIR-007.3 | LLM Handoff for Ambiguous or Uncovered Repairs | P0 | S | backend/LLM | MIR-007.1 |
| MIR-007.4 | Trace for Grounding Decision and Handoff | P1 | XS | backend/infra | MIR-007.1 |
| MIR-007.5 | Regression Matrix for Oscillation Breakage | P0 | S | QA/backend | MIR-007.1 到 MIR-007.4 |

推荐顺序：

```text
MIR-007.0 -> MIR-007.1 -> MIR-007.2 -> MIR-007.3 -> MIR-007.4 -> MIR-007.5
```

### MIR-007.0 Oscillation Baseline and Decision Contract

目标：固化 MIR-006 后的震荡证据，并明确 deterministic grounding 的职责边界。

建议文件：

```text
docs/experiments/2026-05-28-runtime-center-cga-job-analysis.md
services/cypher_generator_agent/app/core/pipeline.py
services/cypher_generator_agent/app/repair/fingerprint.py
services/cypher_generator_agent/tests/integration/test_pipeline_mvp.py
```

开发内容：

- 固化三条震荡样本的 baseline trace：第一轮错误 plan、结构闸门 missing requirements、第二轮是否调用 LLM、重复 fingerprint。
- 明确 MIR-006 / MIR-007 边界：`structural_requirements` 派生层和结构覆盖闸门校验逻辑由 MIR-006 提供。MIR-007 复用它们，不修改派生规则、不修改闸门校验规则；改动范围限定在 `_select_grounded_understanding()` 的选择策略、deterministic builders 的能力边界，以及 deterministic -> LLM 的 handoff。
- 记录当前 deterministic grounding 支持范围：count/scalar aggregate、best single edge、single vertex lookup。
- 定义 fingerprint 粒度：plan/dsl fingerprint 计算 DSL 的**结构骨架**，包括 path hop 的序列长度和 label 序列、aggregate/group_by/order_by/limit 这几类 op 的存在性，以及 projection 字段集合；不纳入具体 edge 方向（例如 `TUNNEL_SRC` vs `TUNNEL_DST`）、不纳入 group_by 绑定的具体属性、不纳入 sort target 的具体列。fingerprint 的职责是判断结构骨架有没有变化、有没有进展，不判断结构内容是否正确；方向和属性正确性归 grounded understanding 语义选择质量与 testing-agent 结构等价 verdict 线。
- 增加 missing-requirements 交替循环检测：除 plan fingerprint 外，repair controller 还要追踪每轮结构闸门报告的 missing requirements 集合。若连续若干轮呈交替/循环态，例如轮 1 缺 A、轮 2 缺 B、轮 3 又缺 A，即使 plan fingerprint 每轮不同，也判定为 requirements 无法同时满足的震荡。
  - 该失败原因标注为 `repair_requirements_unsatisfiable`（或现有命名体系中等价的语义错误码），明确指向 requirements 互斥或候选不足。
  - 这道检测复用现有 repair controller 的轮次记录，不新建独立循环。
- 明确 deterministic grounding 的新返回条件：
  - 结构覆盖完整。
  - repair 场景下补齐了本轮 missing requirements。
  - plan fingerprint 不重复。
  - 候选选择无歧义。
- 明确 handoff 条件：上述任一条件不满足，就交给 LLM selector 或按既有失败路径退出。

验收：

- baseline 能解释 `repair_binding_oscillation` 从哪里开始。
- 文档和测试 fixture 明确区分“deterministic 能力不足”和“LLM repair 失败”。
- decision contract 中 fingerprint 粒度有明确定义，且明确不含方向和属性正确性。
- “补东墙拆西墙”式交替震荡（每轮 plan fingerprint 不同但 missing requirements 交替）能被 `repair_requirements_unsatisfiable` 捕获，不会耗满 repair 上限才以笼统震荡退出。
- 失败原因能区分 deterministic 短路、plan 骨架重复、requirements 交替不可满足三种情况。
- 后续实现不能再让同一 deterministic plan 在 repair 场景中无条件短路 LLM。

### MIR-007.1 Coverage/Fingerprint-Aware Grounding Policy

目标：改造 `_select_grounded_understanding()` 的选择策略，让 deterministic grounding 不再拥有无条件优先权。

建议文件：

```text
services/cypher_generator_agent/app/core/pipeline.py
services/cypher_generator_agent/app/validation/structural_requirements.py
services/cypher_generator_agent/app/repair/fingerprint.py
services/cypher_generator_agent/tests/integration/test_pipeline_mvp.py
```

开发内容：

- coverage 预检消费的 `structural_requirements` 必须是 MIR-006 已实现并验证的派生结果；MIR-007 不重新派生、不引入新的 requirements 判定逻辑，避免 006 和 007 两处派生逻辑漂移。
- 若发现 MIR-006 的派生结果在简单查询上误判，例如把单跳误判为多跳、或因 projection 词多误判覆盖不足，属于 MIR-006 派生层问题，应回到 MIR-006 线修正，不在 MIR-007 中加补偿逻辑绕过。
- 在 deterministic plan 返回前执行轻量结构覆盖预检，至少检查：
  - `requires_aggregate`
  - `requires_group_by`
  - `requires_order_by`
  - `requires_limit`
  - `min_path_hops`
  - `projection_terms`
- 有 `repair_context` 时，预检必须额外确认本轮 missing requirements 被补齐。
  - “补齐”是存在性层面的判定：本轮缺的结构槽位现在有了对应 op，例如缺 group_by 时现在存在 group_by op，缺 path hop 时现在 hop 数达到 `min_path_hops`。
  - 预检不判定正确性：不验证 group_by 绑定属性是否正确、sort target 是否为正确列、path 的具体 edge 或方向是否正确。
  - 因此可能存在所有结构槽位都存在、闸门放行，但某个槽位具体内容错误的残留情况；该情况不由本 MIR 兜底。
- 若 deterministic plan 与上一轮 binding/dsl fingerprint 等价，视为无进展，直接 handoff 给 LLM。grounding 层使用的 fingerprint 函数必须与 repair controller 震荡检测使用同一个实现，即 `services/cypher_generator_agent/app/repair/fingerprint.py` 中的实现，不另起一套；MIR-007.0 定义的 fingerprint 粒度同时作用于这两处。
- deterministic 无法证明覆盖时，不生成失败，而是返回“让位”信号，由 `_select_grounded_understanding()` 调用 LLM selector。

验收：

- `qa_c3e83dd7ad32` 中单跳 `Tunnel -> NetworkElement` 不能在缺 aggregate/group_by/order_by/limit 时短路 LLM。
- `qa_526d49332ed1` 中单跳 plan 不能在 `min_path_hops` 不满足时短路 LLM。
- repair 场景中重复 fingerprint 不再消耗一轮结构闸门后才暴露。
- 简单 count、简单 single-hop、简单 vertex lookup 在覆盖完整时仍可走 deterministic 快速路径。

### MIR-007.2 Narrow Deterministic Structure Builders

目标：只补确定、可枚举、可验证的 deterministic 结构拼装能力，避免把 deterministic 做成语义裁决器。

建议文件：

```text
services/cypher_generator_agent/app/core/pipeline.py
services/cypher_generator_agent/app/binding/models.py
services/cypher_generator_agent/app/dsl/builder.py
services/cypher_generator_agent/tests/validation/test_structural_requirements.py
services/cypher_generator_agent/tests/integration/test_pipeline_mvp.py
```

开发内容：

- 多跳路径 builder：
  - 仅当候选图中存在唯一清晰路径，且 hop 数满足 `min_path_hops` 时构造。
  - 若存在多条可行路径、方向词需要语义裁决、或缺关键 vertex/edge，交给 LLM。
- top-N 聚合 builder：
  - 仅当 `requires_aggregate + group_by + order_by + limit` 明确，且 group_by 属性、sort target、projection/measure 能唯一确定时构造。
  - 若 group_by 属性或 sort target 多候选，交给 LLM。
- projection completion：
  - 仅当 projection term 到 property 绑定唯一时补齐。
  - 多 owner、多属性同名或候选缺失时交给 LLM。
- builder 返回时附带覆盖说明，供 MIR-007.1 做预检和 trace 记录。

验收：

- 唯一多跳路径样本可由 deterministic 构造完整 path。
- 唯一 top-N 聚合样本可由 deterministic 构造 aggregate/group_by/sort/limit 骨架。
- `qa_a5f4b0253af3` 若缺 `Port/HAS_PORT` 候选或存在 `TUNNEL_SRC/TUNNEL_DST` 语义裁决，不得由 deterministic 强行猜测。
- ambiguous candidate 场景必须 handoff LLM，不允许选择“看起来最高分”的结构继续短路。

### MIR-007.3 LLM Handoff for Ambiguous or Uncovered Repairs

目标：让 LLM 真正接管 deterministic 无法覆盖的 repair 场景，而不是被 deterministic 短路。

建议文件：

```text
services/cypher_generator_agent/app/core/pipeline.py
services/cypher_generator_agent/app/understanding/grounded_understanding.py
services/cypher_generator_agent/app/understanding/prompt.py
services/cypher_generator_agent/tests/understanding/test_prompt.py
services/cypher_generator_agent/tests/integration/test_pipeline_mvp.py
```

开发内容：

- 当 deterministic handoff 时，调用 `GroundedUnderstandingSelector`，并携带：
  - `structural_requirements`
  - `repair_context`
  - previous fingerprint / previous query shape
  - deterministic handoff reason
- prompt 要求 LLM 优先补齐 missing requirements，并避免返回与 previous fingerprint 等价的 plan。
- LLM 仍只能从 top_candidates 中选择，不得发明 schema 对象。
- LLM 也无法补齐时，保留现有 repair 上限和 generation_failed 路径。

验收：

- 三条震荡样本的 repair 第二轮应实际调用 LLM，trace 中 `llm_call_count` 不再为 0。
- 如果 LLM 返回同构 plan，repair controller 仍能判定震荡；但失败原因应显示 LLM 已接管而非 deterministic 短路。
- 无候选可补齐时，最终失败原因应指向候选不足或结构无法覆盖，而不是无信息的重复单跳。

### MIR-007.4 Trace for Grounding Decision and Handoff

目标：trace 能解释每次 grounded understanding 是由 deterministic 还是 LLM 产生，以及为什么 handoff。

建议文件：

```text
services/cypher_generator_agent/app/observability/stages.py
services/cypher_generator_agent/app/core/pipeline.py
services/cypher_generator_agent/app/api/service.py
```

开发内容：

- 在 grounded understanding stage 记录：
  - `grounding_source=deterministic|llm`
  - `deterministic_decision=returned|handoff`
  - `handoff_reasons`
  - `coverage_precheck`
  - `fingerprint_changed`
  - `repair_context_present`
- 保持运行中心只展示必要摘要，详细证据留在任务详情页。

验收：

- 看到 `repair_binding_oscillation` 时，可以判断震荡来自 deterministic 短路、LLM 同构返回、候选不足，还是 repair 上限。
- `qa_c3e83dd7ad32` 的 trace 能解释为什么单跳 plan 被 handoff。

### MIR-007.5 Regression Matrix for Oscillation Breakage

目标：将 deterministic coverage-aware handoff 纳入回归，防止结构修复再次被简单 deterministic plan 短路。

建议文件：

```text
services/cypher_generator_agent/tests/integration/test_pipeline_mvp.py
services/cypher_generator_agent/tests/validation/test_structural_requirements.py
services/cypher_generator_agent/tests/understanding/test_prompt.py
docs/experiments/2026-05-28-runtime-center-cga-job-analysis.md
```

开发内容：

- 三条触发样本作为 repair/handoff 回归：
  - `qa_526d49332ed1`：单跳不满足 `min_path_hops` 时必须 handoff LLM 或构造完整多跳。
  - `qa_c3e83dd7ad32`：缺 aggregate/group_by/order_by/limit 时必须 handoff LLM 或构造完整 top-N。
  - `qa_a5f4b0253af3`：候选不足或方向语义不确定时不得 deterministic 猜测。
- 防误伤样本：
  - 简单 single-hop 查询仍走 deterministic。
  - 简单 count 查询仍走 deterministic aggregate。
  - 已完整覆盖的 projection 查询不触发 handoff。
  - 含多个 path 词但实际为单跳的查询，不得因 path 词多被误判为需要多跳而 handoff。
  - projection 词多但 owner 唯一的查询，不得因字段多被误判覆盖不足而 handoff。
- 断言 trace 中的 source/handoff reason，而不仅断言最终 Cypher。

验收：

- repair 第二轮不再被相同 deterministic fingerprint 短路。
- deterministic 快速路径仍覆盖简单查询。
- 上述两个防误伤对照样本的 trace 应为 `grounding_source=deterministic`、`deterministic_decision=returned`，未发生不必要 handoff。
- ambiguous/候选不足场景交由 LLM 或明确失败，不静默猜结构。

### 9.5 剩余风险 / 未来方向

- MIR-007 解决的是“结构补齐选择权和 LLM 交接”问题，不保证 LLM 一定能补对所有复杂路径。若 top candidates 本身缺 `Port/HAS_PORT` 或关键属性，正确策略是明确失败或触发 retrieval 侧 MIR。
- 结构覆盖闸门和 coverage-aware gating 只保证结构槽位存在且数量充分，不保证槽位内容正确。group_by 属性、sort target、edge 方向等具体内容正确性，落到 grounded understanding 的语义选择质量和 testing-agent 结构等价 verdict 线，与方向词正确性并列，不在本 MIR 保证范围。
- 方向词到具体 edge 的正确性仍不是 deterministic 的职责。若 LLM 也持续选错 `TUNNEL_SRC/TUNNEL_DST`，应另开 grounded understanding 方向词选择或 testing-agent 结构等价 verdict MIR。
- 如果 top-N 聚合需要复杂 measure 推导、二阶段聚合或子查询，本 MIR 只要求唯一简单 top-N 骨架；复杂聚合另开 DSL/query-shape MIR。
- 本 MIR 实施后，应更新实验文档记录三条震荡样本是“补齐成功”“LLM 接管后仍失败”还是“候选不足明确失败”，不能只看 final pass/fail。

## 10. MIR-008 Grounded Understanding Compact Output Contract

状态：已按 MIR-010 修订作用域，并随 MIR-010.6 single-shot fallback 路径实施；fallback compact contract、hydrate 和 failure path 已本地闭环；不再按原 MIR-007 多轮 handoff 背景直接实施。未闭环项是原性能目标：completion token 收益、schema retry 率和 fallback 专项远端样本尚未单独量化。

处置结论（2026-05-30）：本 MIR 的 compact contract 仍有价值，但作用域从“服务 MIR-007 的多轮 grounded repair”收缩为“服务 MIR-010.6 的 LLM single-shot fallback”。MIR-010 主路径命中的查询不应进入 grounded understanding compact selector；只有确定性形态拼装无法唯一覆盖、需要 LLM 兜底时，才适用本 MIR。

依赖顺序：MIR-008 的 compact contract 依赖候选质量和 MIR-010 fallback 契约。MIR-009 Retrieval Structural Relevance Reranker 应先于或同步于 MIR-008 实施；MIR-010.6 的 single-shot fallback 输入/输出契约也必须先确认。若候选仍包含大量结构无关噪声，LLM 只输出 `candidate_id` 会放大对候选质量的依赖，让选错更隐蔽。稳妥顺序是先通过 MIR-009 收窄结构无关候选，再把 MIR-008 作为 MIR-010.6 fallback prompt / schema 的 compact 化实现。

### 10.1 背景

触发问题：原 MIR-007 多轮 handoff 方案验证中，结构覆盖不足样本已经能从 deterministic handoff 到 LLM，但 grounded understanding 阶段仍在复杂样本上失败。MIR-010 取消该多轮 handoff 后，这个问题不再发生在主路径 repair loop，而会集中发生在 single-shot fallback 路径。

远端重跑证据：

- 部署标识：`627f8a1+mir007-20260529215609`。
- `qa_526d49332ed1`、`qa_c3e83dd7ad32`、`qa_a5f4b0253af3` 均出现 `coverage_precheck_failed -> grounding_source=llm`，说明 MIR-007 的 handoff 生效。
- 三条样本的 grounded understanding 阶段均执行了 3 次 LLM 调用，但最终为 `grounded_understanding_schema_invalid`。
- trace 中可见 LLM 输出具有一定语义选择能力，例如能选出 `SERVICE_USES_TUNNEL`、`TUNNEL_DST`、`Port.id/name/status` 等候选，但输出形态不满足当前 schema：`projection` 被输出为字符串数组，`assumptions` 被输出为字符串数组，`selected_bindings` 仍被要求复制完整 semantic 字段。
- 由于 failure 被包成普通 dict 后继续进入 binder，后续空 binding plan 又触发 `compiler_shape_mismatch`，掩盖了真正失败点。

一句话核心：fallback LLM 不应被当成“完整语义对象序列化器”，而应是“候选内选择器 / DSL 兜底生成器”。如果要求它复制可查字段、复述 coverage、输出 rationale 和完整 operation dict，会导致 completion token 高、schema retry 成本高，并让本可用的候选选择因为输出形态错误而失败。

### 10.2 失效链路

| 层级 | 失效点 | 影响 |
| --- | --- | --- |
| prompt / schema | 要求 LLM 输出完整 `grounded_understanding_v1`，包括可由 `candidate_id` 查回的 `semantic_type/semantic_id/semantic_name/owner`、解释性 `rationale`、`coverage` 以及完整 `projection/group_by/measures/sort` dict。 | 输出 token 重；LLM 容易输出语义正确但形态不合规的 JSON。 |
| schema retry | qwen3-32b 连续多轮输出字符串 projection / assumptions 等不合规形态。 | repair 样本在 grounded understanding 阶段耗费 3 次 LLM 调用后仍失败。 |
| hydrate 缺失 | 工程代码没有把 `candidate_id` 作为唯一锚点回填候选详情，也没有把 coverage 计算从 LLM 输出中剥离。 | LLM 被迫复制和计算工程可完成的信息。 |
| failure path | `GroundedUnderstandingFailure` 被 `_with_grounding_decision()` 转成普通 dict，后续未被 `_output_from_grounded_outcome()` 识别。 | 真正的 `grounded_understanding_schema_invalid` 被后续 `compiler_shape_mismatch` 掩盖。 |

### 10.3 修改目标

确立 MIR-005 同族原则在 grounded understanding 阶段的落地：

> LLM 只输出它必须裁决的信息；复制、查回、coverage 计算、解释性文本和可推导 operation 由工程代码完成。

具体目标：

- 新增 grounded understanding 的 compact LLM response contract，让 LLM 输出最小选择结果，而不是完整 hydrated 语义对象。
- 将 compact contract 限定在 MIR-010 single-shot fallback 内部使用；确定性主路径命中时不触发本 MIR 的 LLM selection。
- 保持下游消费的 hydrated `grounded_understanding_v1` / binder payload 稳定；compact response 只作为 selector 内部契约，不直接暴露给下游。
- `selected_bindings` 的 LLM 输出最小化为 `role + candidate_id + direction?`；`semantic_type/semantic_id/semantic_name/owner` 由候选索引按 `candidate_id` 回填。
- `coverage` 不再由 LLM 输出，由 decomposition coverage / structural_requirements / hydrated binding 结果在工程侧计算或沿用。
- 删除 LLM 输出中的 `rationale`；可解释性从 candidate evidence、score、trace decision 和 selected candidate_id 还原。
- 审计 `filters/projection/group_by/measures/sort/assumptions`：能从 selected bindings、literal resolver、structural requirements 和候选索引推导的下沉；必须由 LLM 裁决的部分只输出 candidate_id 引用和最小 operation hint。
- 修正 grounded understanding failure path，确保 schema invalid 直接以 `grounded_understanding_schema_invalid` 退出或进入既有 repair/failure 机制，不再误报为 compiler shape mismatch。
- 建立 token / retry / 质量回归基线，确认 output token 和 retry 下降时不牺牲候选选择准确率。

非目标：

- 不更换模型，不引入小模型，不依赖 provider guided decoding。
- 不优先裁剪 top_candidates 输入 metadata；本 MIR 优先解决 output token 和 schema invalid。
- 不把 decomposer 与 grounded understanding 合并。
- 不解决 alias 口径、literal owner 绑定、testing-agent 结构等价 verdict。
- 不保证 edge 方向、group_by 属性、sort target 一定正确；本 MIR 只保证 compact 选择契约和 hydrate 链路可靠，具体语义选择质量仍由后续 grounded/verdict 线继续承接。

### 10.4 子 IR 总览

| 子 IR | 名称 | 优先级 | 估算 | 角色 | 依赖 |
| --- | --- | --- | --- | --- | --- |
| MIR-008.0 | Consumption Audit and Fallback Baseline | P0 | S | backend/QA | MIR-009 / MIR-010.6 范围确认 |
| MIR-008.1 | Compact LLM Selection Contract | P0 | M | backend/LLM | .0 |
| MIR-008.2 | Candidate Hydration and Derived Coverage | P0 | M | backend | .1 |
| MIR-008.3 | Prompt Slimming and Failure-Path Fix | P0 | S | backend/LLM | .1 / .2 |
| MIR-008.4 | Regression and Latency Matrix | P0 | S | QA/infra | .0 到 .3 |

### MIR-008.0 Consumption Audit and Fallback Baseline

目标：确认 single-shot fallback / grounded understanding 输出字段的真实消费方，建立修改前 token、retry、失败原因和生成质量基线。

建议文件：

`services/cypher_generator_agent/app/understanding/models.py`
`services/cypher_generator_agent/app/understanding/grounded_understanding.py`
`services/cypher_generator_agent/app/understanding/prompt.py`
`services/cypher_generator_agent/app/binding/binder.py`
`services/cypher_generator_agent/app/core/pipeline.py`
`services/cypher_generator_agent/tests/understanding/`

开发内容：

- 审计 `selected_bindings` 中 `semantic_type/semantic_id/semantic_name/owner/confidence/rationale` 的消费路径，区分“下游真正需要”和“可由 candidate_id 查回”。
- 审计 `coverage`、`filters`、`projection`、`group_by`、`measures`、`sort`、`assumptions` 的消费路径，标注哪些可由工程侧推导，哪些必须保留为 LLM 裁决。
- 记录原 MIR-007 后三条 handoff 样本作为 fallback 压测样本的 grounded understanding token usage、LLM call count、schema retry count、最终失败原因。
- 记录 MIR-010 确定性主路径样本不触发本 compact selector 的 baseline。

验收：

- 每个待删或下沉字段都有明确消费结论。
- baseline 能区分 input token、completion token、retry 次数和最终 failure reason。
- 明确哪些字段从 LLM 输出删除，哪些字段改为 operation hint，哪些字段仍保留。

### MIR-008.1 Compact LLM Selection Contract

目标：把 LLM response 从完整 hydrated `grounded_understanding_v1` 改为 selector 内部 compact contract，减少输出字段和 schema 失败面。

建议文件：

`services/cypher_generator_agent/app/understanding/models.py`
`services/cypher_generator_agent/app/understanding/grounded_understanding.py`
`services/cypher_generator_agent/tests/understanding/test_grounded_schema.py`

开发内容：

- 新增 selector 内部 compact response 模型，例如 `grounded_selection_v1`。该模型只承载 LLM 决策，不作为下游稳定通信契约。
- compact binding 最小字段为：
  - `role`
  - `candidate_id`
  - `direction`（仅 edge/path 方向需要时填写）
- 不允许 LLM 输出 `semantic_type/semantic_id/semantic_name/owner/rationale/coverage`。
- `ambiguities` 和 `unsupported` 保留，但只要求最小可诊断信息。
- 对 `projection/group_by/measures/sort/filters` 使用 candidate_id 引用或最小 operation hint；禁止要求 LLM 复制完整 property dict。具体保留范围以 .0 消费审计为准。
- `selected_literals` 默认由 literal resolver 结果回填；只有需要 LLM 在多个已解析 literal 中选择子集时，才允许输出最小引用。

验收：

- compact schema 中不存在 `rationale`、`coverage` 以及可由候选查回的 semantic 复制字段。
- 下游仍接收 hydrated `grounded_understanding_v1` 或 binder payload，外部契约不因 compact schema 直接破坏。
- 旧的字符串 projection / assumptions 形态不再导致 compact selection 语义被整体判 invalid；若仍 invalid，应停在 grounded understanding failure，不进入 binder。

### MIR-008.2 Candidate Hydration and Derived Coverage

目标：在工程侧把 compact selection hydrate 成现有 binder 可消费结构，并把 coverage 从 LLM 输出中剥离。

建议文件：

`services/cypher_generator_agent/app/understanding/grounded_understanding.py`
`services/cypher_generator_agent/app/understanding/models.py`
`services/cypher_generator_agent/app/validation/coverage.py`
`services/cypher_generator_agent/app/binding/binder.py`

开发内容：

- 基于 `top_candidates` 建立 `candidate_id -> SemanticCandidate` 索引。
- 对每个 compact binding，按 `candidate_id` 回填 `semantic_type/semantic_id/semantic_name/owner`，再生成 hydrated binding。
- 由 literal resolver 结果和 selected property candidate 回填 filter/literal binding，避免 LLM 复制 resolver 输出。
- 对 projection/group_by/measures/sort 的最小 operation hint 做 normalize，生成 binder 当前接受的 dict 结构。
- `coverage` 由 decomposition coverage、structural requirements 和 hydrated output 在工程侧合成；不信任也不要求 LLM 复述 coverage。
- 保留 candidate boundary validation，但校验锚点改为 compact `candidate_id` 和 hydrate 结果一致性。

验收：

- LLM 只给 `candidate_id` 时，binder 仍能得到完整 vertex/edge/property/metric/path pattern binding。
- projection/group_by/measures/sort 的 hydrated 输出仍通过现有 binder 和 DSL builder。
- coverage 缺失不再造成 LLM schema invalid；coverage 相关失败仍由 semantic/structural validator 负责。

### MIR-008.3 Prompt Slimming and Failure-Path Fix

目标：让 prompt 与 compact contract 对齐，并修正 grounded understanding failure 被后续误包装的问题。

建议文件：

`services/cypher_generator_agent/app/understanding/prompt.py`
`services/cypher_generator_agent/app/core/pipeline.py`
`services/cypher_generator_agent/tests/understanding/test_prompt.py`
`services/cypher_generator_agent/tests/integration/test_pipeline_mvp.py`

开发内容：

- prompt 删除“原样复制 semantic_type/semantic_id/semantic_name/owner”的要求。
- prompt 明确禁止输出 `rationale` 和 `coverage`，只输出 compact selection schema。
- repair_context 仍保留 structural missing requirements，但要求 LLM 以 candidate_id/operation hint 补齐结构，不输出完整 hydrated 对象。
- 修正 `_with_grounding_decision()` / `_output_from_grounded_outcome()` 的 failure path：`GroundedUnderstandingFailure` 必须保持可识别，schema invalid 不得继续进入 binder。
- grounded understanding schema invalid 的最终 failure reason 应保留为 `grounded_understanding_schema_invalid`，不得被空 binding 的 `compiler_shape_mismatch` 覆盖。

验收：

- prompt 文本不再要求复制可查字段、不再要求 LLM 输出 coverage/rationale。
- 模拟 `GroundedUnderstandingFailure` 时 pipeline 直接返回 grounded failure，不进入 semantic binder / dsl builder。
- trace 中能同时看到 grounding decision 和真实 grounded failure reason。

### MIR-008.4 Regression and Latency Matrix

目标：沉淀 compact contract 的正确性、性能和防误伤回归。

建议文件：

`services/cypher_generator_agent/tests/understanding/`
`services/cypher_generator_agent/tests/integration/`
`tests/test_verify_communication_contract.py`
实验记录文档

开发内容：

- 增加 compact response -> hydrated grounded understanding -> binder plan 的单元测试。
- 增加 projection/group_by/measures/sort 的 candidate_id hint hydration 测试。
- 增加旧失败形态回归：LLM 语义选择可用但 projection/assumptions 输出不符合旧 schema 时，不再误报 compiler shape mismatch。
- 复跑三条原 MIR-007 handoff 样本，作为 MIR-010 fallback 压测样本记录 LLM call count、schema retry count、completion tokens 和 final verdict。
- 复跑 MIR-010 确定性主路径样本，确认未因 compact contract 引入额外 LLM 调用。

验收：

- grounded understanding 的 completion token 在相同样本上较 MIR-007 baseline 显著下降，目标为中位数至少降低 40%；若 provider 波动导致未达标，必须记录原因和实测 token。
- `grounded_understanding_schema_invalid` 中由 projection/assumptions 字符串形态导致的失败消除。
- 失败原因不再被空 binding 的 `compiler_shape_mismatch` 掩盖。
- 8 条样本远端重跑结果写入实验文档，至少区分 pass、generation_failed、clarification_required 和真实 failure reason。

### 10.5 剩余风险 / 未来方向

- MIR-010 会显著降低本 MIR 在主路径上的触发频率；本 MIR 主要优化 fallback 路径的单次 LLM 输出成本和 schema 稳定性，不再试图解决主路径结构补齐。
- MIR-009 的 retrieval 结构相关性收窄会减少 fallback LLM 选择负担，可能让部分原本需要 LLM 的样本一次选对，从而降低本 MIR 要面对的 schema retry 和候选选择压力；两者应配套评估。
- compact contract 降低的是输出复杂度和 schema 失败面，不保证 LLM 选择的 edge 方向、group_by 属性、sort target 一定正确；这些仍需 grounded 选择质量和 testing-agent 结构等价 verdict 继续增强。
- 若 top_candidates 中缺少必要 vertex/edge/property，compact contract 只能让失败更早、更清楚，不能凭空补候选。
- 如果 operation hint 仍过重，应继续把 projection/group_by/sort/measure 的更多推导下沉到 deterministic builder，但这需要逐项消费审计后再做。
- input candidate metadata 暂不作为本 MIR 优先目标；若 TTFT 或 prompt token 后续成为主要瓶颈，再另开 candidate payload slimming MIR。

## 11. MIR-009 Retrieval Structural Relevance Reranker

状态：已实施并远端部署；仍需用回归持续守住“收窄不裁决”边界。

实施摘要（2026-05-30）：

- 新增独立 structural reranker 层，retriever 词面召回逻辑保持不变。
- reranker 消费 `structural_requirements` 和本次召回得到的 vertex 上下文，对 owner / from-to vertex 结构外候选降权或在安全边界内剔除。
- 保留结构相关 edge 候选，不提前裁决 `TUNNEL_SRC` / `TUNNEL_DST` / `PATH_THROUGH` 等方向或具体 edge。
- reranker 决策进入 trace，便于确认候选因何 boosted / demoted / dropped。
- 本 MIR 已作为 MIR-010 主路径和 fallback 的前置候选收窄层参与远端 40 样本验证。

剩余边界：

- reranker 只能改善候选干净程度，不替代方向、路径和属性的语义选择。
- 若 vertex 候选缺失或 structural requirements 派生不足，reranker 只能降级，不能凭空补全候选。

### 11.1 首要原则：收窄不裁决

Retrieval 做“结构相关性收窄”，绝不做“路径裁决”。

允许做的事：

- 对明显与当前查询 vertex 集合不相关的候选降权或剔除。例如对 Service / Tunnel / NetworkElement 查询，把 owner 为 Fiber / Protocol / Port 的 property 候选降权或剔除。
- 把结构相关性作为 score 的一个因子，对候选重排序。

禁止做的事：

- 不判断该用哪条 edge、哪个方向，例如 `PATH_THROUGH` vs `TUNNEL_DST`、`TUNNEL_SRC` vs `TUNNEL_DST`。所有沾着查询 vertex 集合的 edge 候选必须全部保留，方向和具体 edge 的选择留给 grounded understanding。
- 不按精确路径把候选裁死。`structural_requirements` 是确定性派生视图，可能有偏差；按它精确过滤会造成不可逆的信息损失。

两条收窄铁律：

1. **只到 vertex 集合层面**：收窄依据是候选的 owner / from-to vertex 是否在当前查询涉及的 vertex 类型集合内，不下探到 edge 方向、具体属性正确性等需要语义裁决的层面。
2. **降权为主、剔除为辅**：明显不相关的候选可剔除；相关性存疑的候选只降权。保留结构相关性分数作为 score 因子，而不是硬性 include / exclude 开关。retrieval 过滤不可逆，降权给下游留挽回机会，剔除没有。

### 11.2 背景

触发问题：grounded understanding 阶段在复杂样本上要从约 30 个候选里做较重的语义选择，候选里有大量高度相似、仅靠 owner 区分的项。例如多个 owner 不同的 `name`、`elem_type`、metric 候选同时进入 top candidates，其中不少与当前查询结构无关。对于一个 Service -> Tunnel -> NetworkElement 查询，召回里仍可能包含 Fiber.name、Protocol.name、Port.name 等结构外候选。

已确诊根因：当前 `candidate_retrieval` 是纯文本 / 同义词 / 描述匹配召回，不消费 `structural_requirements`，不判断候选是否在查询涉及的路径或 vertex 集合上。

代码现状证据：

- pipeline 在 decomposer 后直接调用 `CandidateRetriever(registry).retrieve(decomposition)`，没有传 `structural_requirements`、path hint、required hops 或 query_shape。
- `structural_requirements` 已经在 decomposition payload 中派生，但 retriever 没有读取。
- retriever 先 `_extract_search_terms(decomposition)`，读取 `literal_candidates`、`substantive_terms`、`entities`、`relations`、`keywords`、`original_question` 等词面信号，不读取 `structural_requirements`。
- scorer 只做 exact / synonym / text contains / token match，固定分 `1.0 / 0.92 / 0.72 / 0.64`，没有路径合法性、hop 连通性、from/to vertex 约束参与打分或过滤。

一句话核心：retrieval 召回“词面相关候选”，不召回“结构可用候选”。候选没有先按当前查询结构收窄，导致 LLM 被迫在一大锅词面相关但结构无关的候选里做重选择。这也放大了 MIR-008 compact contract 的风险：LLM 只输出 candidate_id 后，候选越脏，选错越隐蔽。

### 11.3 设计决策

本 MIR 已拍板两个设计决策，不再列备选方案。

决策 A：采用“共现软过滤”，不采用“两阶段召回”。

- 从本次召回结果中提取 vertex 候选集合。
- property / edge / metric 候选的 owner / from-to vertex 如果在本次 vertex 候选集合里出现过，则加权；没有出现则降权。
- 不做精确的“表层词 -> vertex 类型”硬映射，用召回结果自身做相对排序。
- 不引入第二次召回，避免增加延迟和复杂度。

决策 B：新增独立 structural reranker 层，不改 retriever 内部 scorer。

- retriever 保持“纯词面召回”的单一职责不动。
- reranker 位于 retriever 之后，消费 `structural_requirements` 和本次召回的 vertex 集合，做结构相关性重排序、噪声降权和必要剔除。
- 结构相关性作为独立薄层，可独立测试、独立调参、独立 trace。
- 不把结构相关性塞进 `DeterministicCandidateScorer`，避免让词面召回和结构收窄耦合。

### 11.4 修改目标

- 新增独立 structural reranker 层，消费 `structural_requirements` 和本次召回的 vertex 候选集合，对 `top_candidates` 做结构相关性重排序。
- 使用共现软过滤：候选 owner / from-to vertex 在召回 vertex 集合内则加权，不在则降权。
- 明显不相关候选（owner 完全在 vertex 集合外且无路径连接可能）可剔除；存疑候选只降权。
- 所有沾着查询 vertex 集合的 edge 候选全部保留，不做方向或 edge 裁决。
- retriever 的词面召回逻辑和 scorer 固定分不变。
- 收窄后交给 grounded understanding 的候选更干净、更可区分，降低 LLM 选择负担和选错风险。
- 保留 trace：记录每个候选的结构相关性分数、降权或剔除决策、依据的 vertex 集合，便于排查 reranker 误伤。

非目标：

- 不做路径裁决、不做 edge 方向选择、不做精确路径过滤。
- 不改 retriever 的词面召回逻辑和 scorer 固定分。
- 不引入第二次召回。
- 不裁剪 `top_candidates` input metadata。
- 不解决 grounded understanding 的输出压缩；该问题由 MIR-008 承接。
- 不连数据库、不执行 Cypher。

### 11.5 子 IR 总览

| 子 IR | 名称 | 优先级 | 估算 | 角色 | 依赖 |
| --- | --- | --- | --- | --- | --- |
| MIR-009.0 | Baseline and Reranker Boundary Contract | P0 | S | backend/QA | 无 |
| MIR-009.1 | Structural Reranker Layer with Co-occurrence Soft Filtering | P0 | M | backend | .0 |
| MIR-009.2 | Demote-not-Drop Policy and Edge Preservation | P0 | S | backend | .1 |
| MIR-009.3 | Trace for Reranker Decisions | P1 | S | backend/infra | .1 / .2 |
| MIR-009.4 | Regression Matrix | P0 | S | QA/infra | .0 到 .3 |

### MIR-009.0 Baseline and Reranker Boundary Contract

目标：固化当前“脏候选”证据，并把 reranker 红线写成可测试契约。

建议文件：

`services/cypher_generator_agent/app/retrieval/retriever.py`
`services/cypher_generator_agent/app/retrieval/models.py`
`services/cypher_generator_agent/tests/retrieval/`
实验记录文档

开发内容：

- 用 Service -> Tunnel -> NetworkElement 类查询记录当前召回候选数、结构无关候选数量、同名 property owner 分布，例如多个 `name` / `elem_type` 候选。
- 建立“收窄前候选数 / 结构无关候选占比 / 关键相关候选是否存在”的 baseline。
- 明确 reranker 边界契约：收窄不裁决、只到 vertex 集合、降权为主、剔除为辅。
- 将 `SERVICE_USES_TUNNEL`、`PATH_THROUGH`、`TUNNEL_SRC`、`TUNNEL_DST` 等结构相关 edge 纳入防误伤 baseline。

验收：

- baseline 能展示结构无关 property / metric / edge 噪声。
- 测试或实验记录中明确哪些候选是结构相关、哪些是结构无关、哪些是存疑只能降权。
- 红线契约能被 regression 断言，而不是只停留在文档描述。

### MIR-009.1 Structural Reranker Layer with Co-occurrence Soft Filtering

目标：新增 retriever 之后的独立 reranker，用共现软过滤对候选做结构相关性重排序。

建议文件：

`services/cypher_generator_agent/app/retrieval/reranker.py`
`services/cypher_generator_agent/app/retrieval/models.py`
`services/cypher_generator_agent/app/core/pipeline.py`
`services/cypher_generator_agent/app/validation/structural_requirements.py`
`services/cypher_generator_agent/tests/retrieval/`

开发内容：

- 新增 structural reranker 模块，输入为 `CandidateRetrievalResult` 和 `StructuralRequirements`。
- 从本次召回候选中提取 vertex 候选集合，作为共现软过滤的结构上下文。
- 对 property 候选：owner 在 vertex 集合内则加权；owner 明确不在集合且无连接可能则降权或按策略剔除。
- 对 edge 候选：from/to vertex 任一端或两端沾 vertex 集合则保留并加权；完全不沾边则降权。
- 对 metric / path_pattern：若 metadata 的 valid dimensions、pattern 或参数与 vertex 集合有共现则加权；存疑只降权，不剔除。
- reranker 输出新的候选顺序，并保留原始 lexical score 与新增 structural relevance score。

验收：

- retriever 原始词面召回结果不变；reranker 只在之后调整排序或按策略剔除。
- 对 Service -> Tunnel -> NetworkElement 查询，相关 vertex / edge / property 排名提升，Fiber / Protocol / Port owner 的 property 排名下降。
- reranker 不做 edge 方向选择，不把 `TUNNEL_SRC` / `TUNNEL_DST` 二选一。

### MIR-009.2 Demote-not-Drop Policy and Edge Preservation

目标：把“降权为主、剔除为辅”和“edge 全保留”变成实现规则，防止 reranker 越权。

建议文件：

`services/cypher_generator_agent/app/retrieval/reranker.py`
`services/cypher_generator_agent/tests/retrieval/test_structural_reranker.py`

开发内容：

- 定义结构相关性等级，例如 `boosted`、`neutral`、`demoted`、`dropped`。
- 只有 owner 完全不在 vertex 集合、且从 semantic model registry 判断无路径连接可能的 property 才允许剔除。
- 存疑候选一律降权不剔除，例如 metric、path_pattern、owner 缺失或 structural_requirements 低置信时的候选。
- 所有沾着 vertex 集合的 edge 候选必须保留；即使多个 edge 竞争同一语义，也只重排序，不提前裁决。
- 若 vertex 集合为空或 order/结构上下文低置信，reranker 降级为只加 trace，不剔除。

验收：

- `SERVICE_USES_TUNNEL`、`PATH_THROUGH`、`TUNNEL_SRC`、`TUNNEL_DST` 在沾 vertex 集合时全部保留。
- 存疑候选不会被剔除。
- vertex 集合为空时，reranker 不会破坏原始召回的可用性。

### MIR-009.3 Trace for Reranker Decisions

目标：让 reranker 的每次降权和剔除都可解释，便于定位误伤。

建议文件：

`services/cypher_generator_agent/app/observability/stages.py`
`services/cypher_generator_agent/app/core/pipeline.py`
`services/cypher_generator_agent/tests/observability/`

开发内容：

- 在 candidate retrieval 之后记录 reranker stage 或在 retrieval stage output 中附加 reranker trace。
- trace 记录：
  - vertex 候选集合。
  - 每个候选的 lexical score、structural relevance score、final score。
  - 决策：boosted / neutral / demoted / dropped。
  - 决策依据：owner 命中、from/to vertex 命中、完全结构外、低置信降级等。
- 对 dropped 候选记录 drop reason，避免“候选凭空消失”。

验收：

- 运行中心 / trace 能看出某个候选为什么被降权或剔除。
- edge preservation 的证据能在 trace 中看到。
- reranker 误伤时可根据 trace 直接定位依据 vertex 集合和决策规则。

### MIR-009.4 Regression Matrix

目标：验证 reranker 确实收窄结构无关候选，同时不越界裁决路径。

建议文件：

`services/cypher_generator_agent/tests/retrieval/`
`services/cypher_generator_agent/tests/integration/`
实验记录文档

开发内容：

- 触发样本：Service -> Tunnel -> NetworkElement 类查询，验证 Fiber / Protocol / Port owner 的 `name` 等 property 候选被降权或剔除，NetworkElement.name 等相关候选保留。
- 防误伤对照：验证所有沾 vertex 集合的 edge 候选都保留，特别是 `SERVICE_USES_TUNNEL`、`PATH_THROUGH`、`TUNNEL_SRC`、`TUNNEL_DST`。
- 验证 reranker 后 top candidates 数量下降或噪声排名下降，但关键相关候选不丢失。
- 验证 grounded understanding 接收到的候选更干净，同时不因 reranker 提前裁掉方向候选。

验收：

- 结构无关候选占比或排名显著下降。
- 所有结构相关 edge 候选仍在 rerank 后 candidates 中。
- regression 显式断言“收窄不裁决”，特别是 SRC/DST 两个方向候选不能被 reranker 提前裁掉。

### 11.6 剩余风险 / 未来方向

- 共现软过滤依赖本次召回能召到足够 vertex 候选；如果 vertex 本身没被召回，reranker 只能降级，不能凭空恢复结构上下文。
- reranker 降低候选噪声，但不替代 grounded understanding 的语义选择；edge 方向、具体关系、属性正确性仍由后续语义选择和 verdict 线兜底。
- 如果后续发现 input token 或 TTFT 成为主要瓶颈，再另开 candidate payload slimming；本 MIR 不裁剪 metadata。
- 如果共现软过滤收益不足，也不得在本 MIR 内升级为两阶段召回、schema-aware path expansion 或精确路径过滤；必须另开设计并重新审核边界。

## 12. MIR-010 Deterministic Form Assembler Corpus and Main-Path Control Flow Refactor

状态：主控制流已实施到第 4 波并远端部署；控制流闭环，但复杂结构生成能力未闭环。2026-05-30 已补齐 deterministic 主路径的 projection term 覆盖防线，并补齐 fallback compact schema / hydrate 防线；随后通过 MIR-011 收口 L2 literal 澄清问题。2026-05-30 继续补齐 L2 残缺投影与 vertex lookup 小缺口，本地 CGA 回归 `615 passed`；远端针对上一轮 8 条 L2 投影 / vertex lookup 残缺样本已抽样闭环。2026-05-31 680 全量重跑显示，MIR-010 仍不能标记为能力闭环：复杂路径、fallback schema、coverage、compiler shape 和 path pattern projection role binding 仍是主失败来源。

实施摘要（2026-05-30）：

- 第 1 波已完成 reranker、query shape taxonomy、semantic-layer direction mapper、F1/F2/F3 0-hop assembler。
- 第 2 波已完成 assembler dispatch、确定性主路径 -> single-shot fallback -> clarification / generation_failed 的控制流切换，并退役 MIR-007 多轮 grounded repair。
- 第 3 波已完成 F4 路径投影、多跳扩展、single-shot fallback 契约和认输 / 澄清路径；F1/F2/F3 远端验证已从 LLM 路径降到秒级确定性路径。
- 第 4 波选择扩展 DSL 支持 F6 grouped top-N，并完成 F6 相关拼装与回归接线；F8 仅保留可模板化子形态，非唯一场景退 fallback。
- 旧远端随机 5 job / 40 样本验证：`pass=10`，`fail=24`，`pending=6`；pending 均为 `clarification_required`，不是后台未跑完。该结果已被后续 L2 literal 澄清修复局部刷新，不能再代表当前 L2 状态。
- 2026-05-30 projection 补齐增量：为 DSL projection item 增加 `projection_terms` 元数据；结构覆盖闸门按题干 projection term 逐项校验；F4/F5 若显式 projection 字段未解析完整，不再静默 fallback 为默认 ID；同名字段可按不同 `attached_to` 保留，例如“服务的时延”和“隧道的时延”不再被去重成单一服务字段。
- 2026-05-30 fallback schema 补齐增量：schema-bound prompt 改为 compact selection contract；hydrate 层兼容旧式字符串 operation hints；`GroundedUnderstandingFailure` 不再被转成普通 dict 后误入 binder，真实失败原因保留为 `grounded_understanding_schema_invalid`。
- 2026-05-30 L2 残缺投影 / vertex lookup 小步补齐：`服务名称`、`编号/服务ID`、`等级值`、`服务质量等级` 可作为 property projection surface；`详细信息/详情/完整信息/全部属性/所有属性/节点/全部属性信息` 可落成 `vertex_full` projection；fallback 只选属性但 owner 唯一时，binder 可推断 vertex lookup 目标；vertex lookup 支持 limit-only tail；literal owner 可从 `服务ID` 这类 owner+field surface 反推，但若存在高置信度其他 vertex 候选则不抢路径查询，低分 token 噪声（例如 limit 数字召回 `Port`）不阻断 0-hop 收敛。该批修复针对上一轮 L2 中的 `coverage_failure` 和 `compiler_shape_mismatch` 抽样根因，不引入新架构。
- 本地验证：`python -m pytest services/cypher_generator_agent/tests` -> `615 passed in 4.48s`。
- 远端 L2 验证：280 池与 400 池去重 L2 共 86 条，dispatch log 为 `/home/mabingjie/apps/qa-agent/artifacts/experiment_runs/dispatch_l2_after_literal_fix_20260530T092405Z.jsonl`；结果为 `generated=63`、`generation_failed=23`、`clarification_required=0`、`pending=0`，testing 状态为 `passed=55`、`issue_ticket_created=31`。
- 远端 L2 投影 / vertex lookup 抽样验证：`smoke_l2_projection_vertex_fix4_20260530T155847Z` 覆盖上一轮 8 条问题样本中的 7 条通过；剩余 `qa_38392098b2fc` 经 `smoke_single_qa383_fix5_20260530T160229Z` 单条复测通过，生成 `MATCH (svc:Service) WHERE svc.name = 'Service_003' RETURN svc AS service LIMIT 3`，testing verdict `pass`。
- 远端 680 全量验证（2026-05-31）：使用服务器 qa-agent 样本池 `/home/mabingjie/apps/qa-agent/artifacts/experiment_pools/merged_280_400_samples_20260530T021513Z.json`，run id `run680_20260531T045441Z`。CGA 生成状态汇总：`generated=317`、`generation_failed=336`、`clarification_required=16`、`service_failed=11`。失败原因分布：`semantic_match_rejected=86`、`coverage_failure=85`、`compiler_shape_mismatch=81`、`grounded_understanding_schema_invalid=54`、`metric_dimension_invalid=23`、`semantic_contract_unaligned=11`、`edge_endpoint_mismatch=6`、`binding_plan_incomplete=1`。该数据集是 680 构造训练/回归集，不等同于真实线上分布，但足以证明 MIR-010 的复杂结构能力尚未闭环。

当前边界：

- MIR-010 已解决“旧多轮 LLM repair 可能拖到 60s”的控制流问题，但尚未解决全部复杂语义正确性和 DSL 落位能力。
- L1 / L2 样本表现明显好于中高难度，说明确定性主路径对简单形态已生效。
- L2 literal 澄清已由 MIR-011 收口，不再作为当前 L2 主失败类型。
- 680 全量新增关键缺口：`qa_fe30ff3300d3` 暴露 `named_path_pattern + 多 owner projection` 在 DSL builder 中没有 owner -> path template role 映射，导致 `KeyError: 'Service'` 并被包装为 `service_failed / semantic_contract_unaligned`。这不是 testing-agent verdict 问题，而是 CGA builder 能力缺口，已拆出 MIR-012。

### 12.1 首要原则：确定性拼装，不启发式猜测

本 MIR 是一次主路径控制流重构，风险不在“规则不够多”，而在规则系统退化成早期 Step 0-5 式打地鼠。实施前必须先守住以下红线：

1. **只做确定性拼装，不做启发式猜测。** 对任一拼装器，若候选、路径、方向或形态有多个可行解释，答案必须是“退回兜底”，不能是“选一个看起来最好的”。禁止“取最高分”“取最短路径”“默认选 SRC”等猜测。
2. **拼装器按查询形态组织，不按样本组织。** 严禁为某个 `qa_xxx` 写专用拼装器。拼装器只能对应抽象 query shape，并处理该形态的所有实例。
3. **形态拼装器之间必须互斥。** 一个查询最多匹配一个拼装器。若两个拼装器都声称能处理，说明形态划分错误，应重新划分，不允许加优先级规则裁决。
4. **领域知识从语义层 registry 派生，不硬编码。** 拼装器只表达形态逻辑；vertex、edge、方向映射必须从 semantic model 的 path patterns、direction semantics 或 registry 派生。换 schema 只更新语义层，不改拼装器。

一句话原则：**确定则拼装，不确定则兜底或认输；系统宁可失败，也不静默猜一个可运行但未被证明正确的结构。**

### 12.2 背景

触发问题：MIR-007 引入 deterministic -> LLM handoff 后，修复阶段可能调用 LLM 多达 3 次。当前单模型 `qwen3-32b` 单次 grounded understanding 调用约 `20s`，一条查询最长会被拖到约 `60s`，对交互式问数不可接受。

MIR-007 的根因诊断是对的：deterministic grounding 能力不足时不应短路 LLM。但它仍把 LLM 放在“修复循环里的反复修复者”位置，依赖 fingerprint、missing requirements 交替检测等机制管理震荡。该设计能避免无限打转，但不能解决多轮 LLM 造成的延迟上限。

本 MIR 的设计转向：

```text
不再依赖 LLM 的多轮修复能力。
先建立覆盖多数查询形态的确定性拼装语料库作为主路径。
超出确定性能力时，给 LLM 充足信息走一次性兜底。
兜底仍不通过，则澄清或认输。
```

数据支撑来自 680 条真实标注查询与标准 Cypher 的形态分析。该 680 条是 L1-L8 八难度均衡构造的测试集，频次是人工均衡的，不代表真实线上频率；真实场景中简单查询占比通常更高，因此下表对确定性可行性的估计偏保守。

形态分布：

| 形态族 | 占比 | 确定性可拼装性 |
| --- | ---: | --- |
| F1 vertex 投影（0 跳） | 12.4% | 确定性 |
| F2 vertex + filter（0 跳） | 12.6% | 确定性 |
| F3 vertex 聚合（0 跳） | 12.5% | 确定性 |
| F4 路径投影（多跳） | 37.4% | 多数确定，取决方向映射 |
| F5 路径 + filter（多跳） | 0.1% | 多数确定 |
| F6 路径分组 top-N（多跳） | 12.5% | 多数确定，取决方向映射 |
| F8 两阶段聚合（多段 MATCH + WITH） | 12.5% | 部分确定，部分需兜底 |

方向映射分析覆盖 337 条方向敏感多跳查询：

- 题干方向词 -> edge 唯一正确映射占 `83.1%`：`源` -> `TUNNEL_SRC`、`目的/宿/到达` -> `TUNNEL_DST`、`经过/穿过/途经` -> `PATH_THROUGH` 高度规整。
- 无方向词需推断占 `13.6%`，多为单一方向 edge，没有 SRC / DST 真歧义。
- 真歧义（多方向词冲突或映射不一致）约 `3.3%`。

关键结论：

- 约 `78-80%` 查询可首轮纯确定性拼装，不调用 LLM。
- 约 `20%` 查询，包括 F8 复杂两阶段、方向真歧义和罕见形态，需要 LLM 单次兜底。
- F9 离群形态为 0，系统几乎不需要为了长尾保留多轮猜测式 repair。

### 12.3 控制流目标模型

本 MIR 用更简单的主路径控制流取代 MIR-007 的修复循环：

```text
自然语言问题
  -> decomposer + structural_requirements（沿用 MIR-005 / MIR-006）
  -> retrieval + structural reranker（沿用 MIR-009）
  -> 【确定性形态拼装主路径】
       匹配到形态拼装器 且 适用判定唯一
         -> 确定性拼装 DSL -> compile -> self-validation -> 完成（不调 LLM）
       未匹配 / 适用判定不唯一 / 方向真歧义
         -> 进入 LLM 单次兜底
  -> 【LLM 单次兜底】
       给 LLM structural_requirements、候选、形态提示和确定性失败原因
       -> 生成 DSL
       -> self-validation + 结构覆盖闸门
       通过 -> 完成
       不通过 -> 澄清或认输
  -> 【澄清 or 认输】
       缺指代或真歧义 -> clarification
       结构无法覆盖或候选不足 -> generation_failed
```

与 MIR-007 的本质区别：

- MIR-007 是“修复循环”：deterministic 与 LLM 反复 handoff，靠 fingerprint / missing requirements 交替检测管理震荡。
- MIR-010 取消“修复循环”概念：确定性拼装是主路径，LLM 是**单次兜底**，不进入多轮修复。
- MIR-007 的多轮 handoff、fingerprint 震荡检测、交替循环检测大部分退役或简化；保留的是 self-validation、结构覆盖闸门、trace 与明确失败原因。
- 新旧两套控制流不得并存；实施时必须明确 MIR-007 机制的保留/退役边界。

### 12.4 修改目标

- 建立确定性形态拼装语料库：按 680 条分析得到的 7-8 个形态族，每个形态族一个确定性拼装器。
- 将“方向词 -> edge”做成语义层 `direction_semantics` 驱动的确定性映射。映射唯一则拼装；多方向词冲突、无唯一映射或语境不足则退回兜底。
- 重构控制流为“确定性主路径 -> LLM 单次兜底 -> 澄清 / 认输”，取消 MIR-007 的多轮修复循环。
- 明确 MIR-007 机制保留/退役清单，避免两套控制流并存。
- 每个拼装器带确定性适用判定和唯一性门槛，不唯一立刻退回兜底。
- LLM 兜底产物仍过 self-validation 和结构覆盖闸门，不无条件信任。
- 沉淀形态覆盖率、确定性命中率、兜底触发率、认输率，作为系统能力边界的诚实度量。

非目标：

- 不做启发式猜测。
- 不为单个样本写专用拼装器。
- 不让 LLM 进入多轮修复。
- 不换模型、不引入小模型。
- 不要求覆盖所有复杂查询；超出能力时认输是允许的正确行为。
- 不连数据库；拼装器只使用 semantic model、registry、retrieval candidates、structural requirements 和 trace，不查库。

### 12.5 子 IR 总览

| 子 IR | 名称 | 优先级 | 估算 | 角色 | 依赖 |
| --- | --- | --- | --- | --- | --- |
| MIR-010.0 | Query Shape Taxonomy and Baseline | P0 | M | backend/QA | MIR-006 / MIR-009 |
| MIR-010.1 | Deterministic Direction Mapping from Semantic Layer | P0 | M | backend | .0 |
| MIR-010.2 | Form Assembler Library | P0 | L | backend | .0 / .1 |
| MIR-010.3 | Uniqueness Gate and Assembler Dispatch | P0 | M | backend | .2 |
| MIR-010.4 | Control Flow Refactor: Main Path -> Single LLM Fallback -> Concede | P0 | L | backend | .2 / .3 |
| MIR-010.5 | MIR-007 Mechanism Retirement Map | P0 | S | backend | .4 |
| MIR-010.6 | LLM Single-Shot Fallback Contract | P0 | M | backend/LLM | .4 |
| MIR-010.7 | Concede and Clarification Path | P1 | S | backend | .6 |
| MIR-010.8 | Coverage / Determinism / Fallback / Concede Metrics and Regression | P0 | M | QA/infra | .0 到 .7 |

推荐顺序：

```text
MIR-010.0 -> MIR-010.1 -> MIR-010.2 -> MIR-010.3 -> MIR-010.4 -> MIR-010.5 -> MIR-010.6 -> MIR-010.7 -> MIR-010.8
```

### MIR-010.0 Query Shape Taxonomy and Baseline

目标：把 680 条形态分析固化为正式 query shape taxonomy，并建立改造前后可对照的成功率、LLM 调用次数和耗时基线。

建议文件：

```text
docs/experiments/2026-05-28-runtime-center-cga-job-analysis.md
services/cypher_generator_agent/app/validation/structural_requirements.py
services/cypher_generator_agent/app/core/pipeline.py
services/cypher_generator_agent/tests/integration/test_pipeline_mvp.py
```

开发内容：

- 定义 F1 / F2 / F3 / F4 / F5 / F6 / F8 查询形态 taxonomy。
- 每个形态给出结构特征：hop 数、有无 filter、有无 aggregate、是否 group_by、是否 order_by / limit、是否多段 MATCH / WITH。
- 每个形态给出确定性可拼装性评级：确定性、多数确定、部分确定、需兜底。
- 用 680 条数据或代表性子集建立 baseline：当前每个形态的生成成功率、平均 / P95 LLM 调用次数、平均 / P95 耗时、失败原因。
- 明确数据前提：680 条是构造测试集，频次非真实线上频率；真实覆盖率预计更高，本数据偏保守。

验收：

- taxonomy 互斥，且覆盖数据中全部有效形态。
- 每个形态有明确结构定义和确定性评级。
- baseline 可复跑，可与 MIR-010 实施后对照。
- 没有按 `qa_id` 分类的样本专用形态。

### MIR-010.1 Deterministic Direction Mapping from Semantic Layer

目标：把方向词到 edge 的映射从 LLM 语义裁决中抽出，改为 semantic model / registry 驱动的确定性映射；唯一则拼装，不唯一则兜底。

建议文件：

```text
services/cypher_generator_agent/app/semantic_model/
services/cypher_generator_agent/app/retrieval/
services/cypher_generator_agent/app/validation/structural_requirements.py
services/cypher_generator_agent/tests/semantic_model/
services/cypher_generator_agent/tests/integration/test_pipeline_mvp.py
```

开发内容：

- 从语义层 `direction_semantics` 派生方向映射，例如源/起类方向词指向源边，目的/宿/到达/终类方向词指向目的边，经过/穿过/途经类方向词指向 through/path 边。
- 映射数据必须来自 semantic model / registry，不在拼装器或 pipeline 中硬编码平行词表。
- 若方向词与候选 edge 映射唯一，则标记为 deterministic direction binding。
- 若题干多方向词冲突、方向词映射到多个可行 edge、或无方向词且上下文不能唯一确定，则标记为 direction ambiguity，退回 LLM 兜底。
- 这一步同时部分偿还长期挂在 verdict 线上的“方向正确性”债：确定性方向映射覆盖的部分不再依赖 LLM 猜或 verdict 兜底。

验收：

- 规整方向词样本中，约 `83%` 类唯一映射能确定性命中。
- 多方向词冲突样本被判为歧义并退回兜底。
- 无方向词且存在 SRC / DST 真歧义时不默认选择。
- 测试中不得出现“默认选 SRC”“最高分 edge 胜出”等启发式行为。

### MIR-010.2 Form Assembler Library

目标：按 query shape 实现确定性 DSL 拼装器库，让主路径在形态和候选都唯一时直接产 DSL，复用现有 compile / validation 链路。

建议文件：

```text
services/cypher_generator_agent/app/dsl/
services/cypher_generator_agent/app/binding/
services/cypher_generator_agent/app/core/pipeline.py
services/cypher_generator_agent/app/semantic_model/
services/cypher_generator_agent/tests/dsl/
services/cypher_generator_agent/tests/integration/test_pipeline_mvp.py
```

开发内容：

- 为 F1 / F2 / F3 实现 0-hop 拼装器：
  - F1 vertex projection。
  - F2 vertex + filter。
  - F3 vertex aggregate / count。
- 为 F4 / F5 / F6 实现多跳拼装器：
  - F4 path projection。
  - F5 path + filter。
  - F6 path group-by top-N。
  - 多跳拼装依赖 MIR-010.1 的方向唯一映射。
- F8 两阶段聚合只实现可模板化子形态，例如同路径聚合两次、固定多段 MATCH + WITH；真复杂两阶段退回 LLM 兜底。
- 每个拼装器必须包含：
  - 形态匹配条件。
  - 从 semantic layer 读取领域知识的入口。
  - 唯一性门槛。
  - DSL 输出。
  - 无法确定时的 fallback reason。
- 拼装器只产 DSL，不直接产 Cypher，不绕过 DSL parser、compiler、self-validation。

验收：

- F1 / F2 / F3 可纯确定性拼装。
- F4 / F6 在方向映射唯一、路径候选唯一、projection / group_by 唯一时可确定性拼装。
- F8 的固定模式可模板化，非固定模式退回兜底。
- 多候选、歧义、候选缺失时拼装器返回 fallback，不猜测。
- 代码和测试中无按样本 ID 的专用分支。

### MIR-010.3 Uniqueness Gate and Assembler Dispatch

目标：实现 query shape -> 拼装器的互斥分派和唯一性门槛，确保确定性主路径只在“可证明唯一”时执行。

建议文件：

```text
services/cypher_generator_agent/app/core/pipeline.py
services/cypher_generator_agent/app/validation/structural_requirements.py
services/cypher_generator_agent/app/dsl/
services/cypher_generator_agent/tests/integration/test_pipeline_mvp.py
```

开发内容：

- 实现 shape classifier / assembler dispatch，输入为 structural requirements、retrieval candidates、semantic registry 派生信息。
- 一个查询最多匹配一个拼装器；若多个拼装器同时匹配，视为 taxonomy 错误或不确定，退回兜底，不用优先级规则裁决。
- 为每个拼装器执行唯一性门槛：
  - vertex / path / property / metric 候选唯一。
  - path pattern 唯一。
  - direction mapping 唯一。
  - projection / group_by / sort target / limit 结构可唯一落位。
- 不唯一时记录 fallback reason，例如 `shape_ambiguous`、`path_candidate_ambiguous`、`direction_ambiguous`、`group_by_target_ambiguous`。
- 分派决策进入 trace，供运行中心展示确定性命中或兜底原因。

验收：

- 互斥分派无重叠。
- 不唯一时退回兜底，不进入确定性拼装。
- 分派结果、命中拼装器、fallback reason 均可在 trace 中看到。
- 简单形态不会因新增 gate 被误退兜底。

### MIR-010.4 Control Flow Refactor: Main Path -> Single LLM Fallback -> Concede

目标：把 pipeline 的 grounding / repair 段重构为确定性主路径、LLM 单次兜底、澄清/认输三段控制流，取消 MIR-007 的多轮修复循环。

建议文件：

```text
services/cypher_generator_agent/app/core/pipeline.py
services/cypher_generator_agent/app/understanding/grounded_understanding.py
services/cypher_generator_agent/app/repair/controller.py
services/cypher_generator_agent/tests/integration/test_pipeline_mvp.py
```

开发内容：

- 在 retrieval + reranker 后先进入确定性 form assembler dispatch。
- 确定性命中后直接产 DSL，继续走 DSL parser、structural coverage gate、compiler、self-validation，不调用 grounded LLM。
- 确定性未命中、命中不唯一或方向真歧义时，进入 LLM single-shot fallback。
- LLM fallback 最多调用 1 次；不再用 repair controller 多轮回灌 grounded understanding。
- LLM fallback 通过 validation 后采纳；不通过进入 MIR-010.7 的澄清或认输路径。
- 保留现有错误报告和 trace 结构，但控制流不再表现为 deterministic <-> LLM 多轮震荡。

验收：

- F1 / F2 / F3 查询全程 `llm_call_count=0`。
- 方向映射唯一的 F4 / F6 查询也全程 `llm_call_count=0`。
- 兜底路径最多 `llm_call_count=1`。
- 不再出现同一 query 在 grounded understanding repair 中连续调用 2-3 次 LLM 的路径。

### MIR-010.5 MIR-007 Mechanism Retirement Map

目标：明确 MIR-007 中各机制在 MIR-010 控制流下的保留、退役或简化，避免新旧两套 repair 控制流并存。

建议文件：

```text
services/cypher_generator_agent/app/core/pipeline.py
services/cypher_generator_agent/app/repair/controller.py
services/cypher_generator_agent/app/repair/fingerprint.py
docs/superpowers/specs/graph-cypher-generation/2026-05-28-cga-osi-follow-up-modification-ir.md
```

开发内容：

- 明确退役：
  - deterministic <-> LLM 多轮 handoff。
  - repair 场景中反复调用 grounded understanding 的多轮修复。
  - 为多轮 handoff 服务的 fingerprint-aware handoff 作为主控制流条件。
  - missing requirements A/B/A 交替循环检测作为常规 repair 出口。
- 明确保留或简化：
  - fingerprint 可保留为 trace / regression 诊断工具，不再作为多轮 repair 的核心控制器。
  - structural coverage gate 保留，继续检查 deterministic 或 LLM fallback 产物。
  - self-validation 保留。
  - 明确 failure reason 保留，包括 direction ambiguity、shape ambiguity、candidate missing、coverage failure 等。
- 更新文档和测试命名，避免把 MIR-010 的单次 fallback 误称为 repair loop。

验收：

- 文档列清楚 MIR-007 各机制的去向。
- 代码中无并存的两套修复控制流。
- trace 能看出“确定性主路径命中 / 单次 LLM 兜底 / 澄清或认输”，而不是旧的多轮 handoff。

### MIR-010.6 LLM Single-Shot Fallback Contract

目标：把 LLM 从多轮修复者改为一次性兜底者，并限定它输出可验证 DSL，而不是裸 Cypher。

建议文件：

```text
services/cypher_generator_agent/app/understanding/prompt.py
services/cypher_generator_agent/app/understanding/models.py
services/cypher_generator_agent/app/core/pipeline.py
services/cypher_generator_agent/tests/understanding/
services/cypher_generator_agent/tests/integration/test_pipeline_mvp.py
```

开发内容：

- fallback prompt 输入包含：
  - `structural_requirements`。
  - rerank 后 candidates。
  - 确定性形态匹配结果。
  - 确定性失败原因，例如 direction ambiguous、shape not matched、group_by target ambiguous。
  - semantic model / registry 中必要的路径与方向说明。
- fallback 只调用一次，不进入多轮 repair。
- fallback 产物倾向为 DSL，复用现有 DSL parser、structural coverage gate、compiler、self-validation。
- fallback prompt / response 可复用经修订后的 MIR-008 compact contract，但该 contract 只服务本 single-shot fallback，不得重新引入 MIR-007 式多轮 grounded repair。
- 若 DSL 无法表达该问题，或 LLM 无法产出通过校验的 DSL，进入认输；不允许退回裸 Cypher 去赌。
- fallback 失败原因必须可解释，不能被后续 compiler shape mismatch 等二次错误掩盖。

已拍板的取舍：

- 用户已确认：LLM fallback 输出 DSL，不输出裸 Cypher。
- 理由：DSL 能复用结构覆盖、自校验和 compiler 防线；裸 Cypher 会绕开当前工程防线，违背“不猜测”原则。
- 若后续确有 DSL 表达力不足的 query shape，应优先扩展 DSL 或认输，而不是让 LLM 写自由 Cypher。

验收：

- fallback 最多 1 次 LLM 调用。
- fallback 产物通过完整校验才采纳。
- fallback schema invalid / coverage failed / self-validation failed 时进入澄清或认输，不再多轮修复。
- trace 记录 fallback 输入摘要、失败原因和校验结果。

### MIR-010.7 Concede and Clarification Path

目标：定义兜底失败后的可解释退出路径，允许系统诚实承认当前能力边界。

建议文件：

```text
services/cypher_generator_agent/app/core/pipeline.py
services/cypher_generator_agent/app/repair/controller.py
services/cypher_generator_agent/app/core/errors.py
services/cypher_generator_agent/tests/integration/test_pipeline_mvp.py
```

开发内容：

- 缺指代、真实语义歧义、方向词冲突且用户可回答时，走 clarification。
- 结构无法覆盖、候选不足、形态不支持、DSL 表达力不足或 LLM fallback 未通过校验时，走 `generation_failed`。
- failure reason 应区分：
  - `shape_not_supported`
  - `direction_ambiguous`
  - `candidate_missing`
  - `dsl_fallback_validation_failed`
  - `coverage_failure`
  - 以及现有错误码中可复用的等价原因。
- 用户可见信息应说明系统缺什么，而不是泛化成“生成失败”。
- 再次强调：系统宁可认输，不猜测。

验收：

- 澄清与认输触发条件明确。
- 失败原因能被 trace、testing-agent 和运行中心读到。
- 不发生静默猜测或 fallback 后继续多轮尝试。

### MIR-010.8 Coverage / Determinism / Fallback / Concede Metrics and Regression

目标：把新控制流的能力边界量化，建立形态级回归和性能验收。

建议文件：

```text
services/cypher_generator_agent/tests/integration/
services/cypher_generator_agent/tests/dsl/
services/cypher_generator_agent/tests/semantic_model/
tests/test_runtime_results_service_api.py
docs/experiments/2026-05-28-runtime-center-cga-job-analysis.md
```

开发内容：

- 沉淀四个指标：
  - 形态覆盖率：多少 query 能被 taxonomy 分类。
  - 确定性命中率：多少 query 不调用 LLM 完成。
  - 兜底触发率：多少 query 进入 LLM single-shot fallback。
  - 认输率：兜底后仍失败或澄清的比例。
- 回归覆盖：
  - 每个形态族的确定性拼装样本。
  - 方向映射唯一样本与方向歧义对照。
  - fallback 触发样本。
  - 防误伤样本：简单查询不误退兜底，歧义查询不误走确定性。
- 用 680 条做形态覆盖回归，至少记录每个形态的命中路径和 LLM call count。
- 运行中心应展示主路径类型：deterministic assembler / LLM fallback / clarification / generation_failed。

验收：

- 四个指标可在实验文档或 trace 中度量。
- 确定性命中查询 `llm_call_count=0`。
- 确定性命中查询延迟显著低于 fallback 路径。
- 形态回归 slice 可独立运行。
- 对 680 条数据，能输出形态分布、确定性命中率、fallback 触发率和认输率。

### 12.6 剩余风险 / 未来方向

- 本 MIR 体量大，属于控制流重构，不是单点补丁。实施时应按子 IR 小步推进，先落 taxonomy、方向映射和一两个 0-hop 拼装器，再扩大到多跳和 top-N。
- 数据集是均衡构造集，不代表真实线上频率；指标解释必须持续标注这一前提。
- 如果 semantic model 的 direction semantics 或 path patterns 不完整，拼装器必须退回兜底，不能补一份平行硬编码词表。
- F8 两阶段聚合仍可能需要更多 DSL 表达力；本 MIR 只模板化固定子形态，复杂 F8 认输或兜底是允许行为。
- MIR-008 和 MIR-009 仍有价值：retrieval 收窄降低 fallback 选择难度，compact contract 降低 fallback 输出 token；但 MIR-010 会减少它们在主路径上的触发频率。
- testing-agent 结构等价 verdict 仍是独立线；本 MIR 能降低方向错误进入结果的概率，但不替代下游 verdict 增强。

## 13. MIR-011 Literal Filter Binding and Static Index-Miss Pass-through

状态：已远端闭环。该 MIR 是对 MIR-006 剩余风险中“literal owner/property 绑定问题”的小步收口，不改变主控制流，不引入数据库查询，不扩大为新的架构调整。

### 13.1 闭环摘要

触发范围：L2 大量 `clarification_required`，代表样本包括：

- `qa_a1801a24cede`：`查询名称为“Service_001”的服务的ID、名称、服务质量等级和带宽。`
- `qa_b4a89bcff37b`：`查询ID为'svc-mpls-vpn-1004'的服务的名称。`
- `qa_d54077843edf`：`查询网元类型为MPLS-VPN的服务的ID和网元类型。`
- `qa_78040ceec879`：`查询延迟等于23的服务名称、带宽和延迟。`

旧行为不是用户问题真实含糊，而是 literal 解析链路把明确等值过滤转成反问：

- `Service_001` / `Service_002` 等服务名称在 `Service.name` 或误绑 `Service.id` 后 unresolved。
- `svc-mpls-vpn-1000` 到 `svc-mpls-vpn-1004` 等服务 ID 因静态 value index miss 触发 `literal_value_index_miss`。
- `MPLS-VPN` 因 hyphenated value 形态被 ID 快路径抢走，误绑到 `Service.id`。
- `延迟=23` 在缺少 `attached_to` 时没有消费前置 filter 词“延迟”，误绑到 `Service.name`。

本 MIR 的闭环原则：

> 当 literal 的 owner / property 已经由 decomposition、retrieval candidate 和 filter property hint 唯一确定时，CGA 不应仅因为静态 value index 缺样本而反问；对非枚举等值过滤允许 raw literal pass-through。高风险枚举仍必须走 valid_values / synonym / index 校验，不能 pass-through 猜测。

关键结果：

- literal request 构造消费 filter property hint：
  - `类型为 MPLS-VPN` 绑定到 `Service.elem_type`，不会因连字符形态优先走 ID 快路径。
  - `延迟等于 23` 在 literal 无 `attached_to` 时回看前置 filter term，绑定到 `Service.latency`。
  - `名称为 Service_003` 优先绑定到 `Service.name`，不会因值形态像标识符而抢到 `Service.id`。
- literal resolver 增加 `literal_passthrough` match type：
  - 对明确 owner/property 的非枚举 string/id literal，value index miss 不再等价于 unresolved。
  - compiler 将 `literal_passthrough` 视为有证据的 resolved literal，可安全内联到 Cypher。
  - `value_index_miss` 仍保留在 trace 中，表达“静态索引未确认存在”，但不触发用户澄清。
- 高风险 enum 逻辑保持不变：未知枚举值仍可进入 clarification，不允许被 pass-through。

验证：

- 本地：`python -m pytest services/cypher_generator_agent/tests` -> `600 passed in 4.66s`。
- 远端：CGA、运行中心、testing-agent 均 health OK；repair-agent 未启动。
- 远端 L2 去重 86 条重跑：
  - dispatch log：`/home/mabingjie/apps/qa-agent/artifacts/experiment_runs/dispatch_l2_after_literal_fix_20260530T092405Z.jsonl`
  - 生成状态：`generated=63`、`generation_failed=23`、`clarification_required=0`、`pending=0`
  - testing 状态：`passed=55`、`issue_ticket_created=31`
  - 典型通过：`qa_a1801a24cede` 生成 `WHERE svc.name = 'Service_001'` 并通过；`qa_78040ceec879` 生成 `WHERE svc.latency = 23.0` 并通过。

剩余边界：

- `literal_passthrough` 不证明数据库中一定存在该值，只证明过滤槽位明确；真实存在性由执行结果和 testing-agent 判断。
- 本 MIR 不解决 L2 剩余 `coverage_failure`、`compiler_shape_mismatch`、`grounded_understanding_schema_invalid`、`semantic_match_rejected`。
- 若后续发现 pass-through 被用于高风险 enum、模糊 owner/property 或多候选场景，必须回退到 clarification 或另开 MIR，不得扩大为“所有 literal 都直通”。

## 14. 当前未闭环 MIR / 风险清单

| 项 | 所属 MIR | 当前证据 | 下一步 |
| --- | --- | --- | --- |
| fallback compact contract 性能收益未量化 | MIR-008 | 功能接入、本地 `600 passed`，但没有单独统计 fallback completion tokens、schema retry 率、端到端耗时。 | 选取 fallback 命中样本做 token / latency / schema retry 专项采样；若收益未达标，再决定是否继续压缩 prompt。 |
| MIR-010.8 四指标仍未达验收 | MIR-010 | 680 全量重跑 `run680_20260531T045441Z` 已完成，但只得到生成状态 / failure reason 分布：`generated=317`、`generation_failed=336`、`clarification_required=16`、`service_failed=11`。尚未按形态输出确定性命中率、fallback 触发率、认输率、延迟分布、留出集泛化。 | 补 680 结果的形态级聚合；把训练集自验证和留出泛化分开；按 deterministic / fallback / clarification / generation_failed 四类输出指标。 |
| `named_path_pattern + 多 owner projection` 服务失败 | MIR-012 / MIR-010.2 | `qa_fe30ff3300d3`：CGA 选中 `query_shape=named_path_pattern` 和 `tunnel_full_path`，projection 包含 `Service.elem_type`、`Tunnel.elem_type`、`NetworkElement.model`、`Port.elem_type`，但 binding plan 无 `vertex_bindings`；DSL builder 的 `role_by_owner={}`，处理 `Service.elem_type` 时抛 `KeyError: 'Service'`，最终 `service_failed / semantic_contract_unaligned`。 | 先落 MIR-012：为 path pattern 输出建立 owner -> role/alias 的确定性映射，或在无法映射时给出 `generation_failed / compiler_shape_mismatch`，不得再抛 service_failed。 |
| 680 中 `coverage_failure` 仍高 | MIR-010 / MIR-006 边界 | 680 全量有 `coverage_failure=85`。此前 L2 抽样修复过投影 surface 和 `vertex_full`，但 680 证明 coverage 问题远超 L2 小样本。 | 按 `projection_terms`、path hop、aggregate/group/order/limit 分类抽样，不扩大架构；每类只补通用派生或 DSL 落位规则。 |
| 680 中 `compiler_shape_mismatch` 仍高 | MIR-010 / DSL 表达力 | 680 全量有 `compiler_shape_mismatch=81`。说明 F6/F8、path pattern、fallback hydrate 或 DSL parser/compiler 表达仍存在系统缺口。 | 聚类 trace：区分 DSL 表达力缺口、assembler dispatch 误判、fallback hydrate 失败、compiler 不支持；每类单独小步修复。 |
| fallback schema / grounded 输出不稳定 | MIR-008 / MIR-010.6 | 680 全量有 `grounded_understanding_schema_invalid=54`，远高于 L2 86 条中的 1 条。compact contract 已接入，但并未在全量 fallback 上闭环。 | 拉取 schema invalid trace，统计字段级原因；先修 contract/hydrate 的最小共性问题，再重新采样 token 和 schema retry。 |
| semantic verdict / 语义等价失败较多 | testing-agent / verdict 线，非 CGA 主 MIR 闭环 | 680 全量有 `semantic_match_rejected=86`。其中可能混有 CGA 语义错误、alias/返回列口径、testing-agent 结构等价不足。 | 不混入 CGA 主路径；单独审 testing-agent verdict、alias 口径和结构等价规则。 |
| 澄清仍未归零 | MIR-011 / MIR-010.7 | 680 全量仍有 `clarification_required=16`。L2 literal 澄清已归零，但中高难度仍存在真实歧义或错误反问混杂。 | 分离真实澄清与误澄清；真实歧义保留，误澄清回到 literal owner/property、coverage 或 fallback 决策线。 |

## 15. MIR-012 Named Path Pattern Projection Role Binding

状态：待实施。该 MIR 是 2026-05-31 680 全量重跑暴露出的 P0 缺口，属于 MIR-010 的复杂路径 / path pattern DSL 落位能力残余，不是新架构调整。

### 15.1 背景

触发样本：`qa_fe30ff3300d3`

问题：

```text
查询业务经隧道到达网元下的端口，返回业务类型、隧道类型、网元型号及端口节点信息。
```

期望 Cypher：

```cypher
MATCH (a:Service)-[:SERVICE_USES_TUNNEL]->(b:Tunnel)-[:PATH_THROUGH]->(c:NetworkElement)-[:HAS_PORT]->(d:Port)
RETURN a.elem_type AS source, b.elem_type AS via1, c.model AS via2, d AS target
```

实际行为：

- CGA 没有生成 Cypher。
- testing-agent 收到 `generation_status=service_failed`。
- failure reason 为 `semantic_contract_unaligned`。
- trace final failure message 为 `"'Service'"`。

trace 证据：

- `question_decomposer` 成功，识别 path terms：`业务 / 经 / 隧道 / 到达 / 网元 / 下 / 端口`；projection terms：`业务类型 / 隧道类型 / 网元型号 / 端口节点信息`。
- `grounded_understanding` / `semantic_binder` 成功，得到：
  - `query_shape = named_path_pattern`
  - `selected_path_patterns = tunnel_full_path`
  - projection：
    - `Service.elem_type`
    - `Tunnel.elem_type`
    - `NetworkElement.model`
    - `Port.elem_type`
- binding plan 中没有 `vertex_bindings`。
- `dsl_builder` 进入 `_build_named_path_pattern()` 后，`role_by_owner` 为空；处理 `Service.elem_type` projection 时需要 `role_by_owner["Service"]`，触发 `KeyError: 'Service'`。

一句话核心：**path pattern 模板能表达多 hop 路径，但 DSL builder 没有把 path pattern 内部的 vertex owner 映射到模板变量 / projection target，导致多 owner projection 无法落位，并被错误包装成 service_failed。**

### 15.2 失效链路

| 层级 | 失效点 | 影响 |
| --- | --- | --- |
| grounded understanding / binder | 选择了 `named_path_pattern=tunnel_full_path`，并选择了跨 `Service/Tunnel/NetworkElement/Port` 的 projection，但没有提供这些 owner 在 path pattern 模板中的 role / alias。 | 下游只有“使用哪个 path pattern”和“要返回哪些 owner 属性”，缺少二者之间的连接。 |
| DSL builder | `_build_named_path_pattern()` 只建立 `primary_vertex` binding；当没有 primary vertex 时，`role_by_owner={}`。 | 多 owner projection 调用 `_projection_items()` 时无法确定 target。 |
| 错误处理 | `KeyError: 'Service'` 被包装为 `semantic_contract_unaligned / service_failed`。 | 这是 CGA 内部能力缺口，却被展示为服务失败，降低可诊断性。 |
| 回归覆盖 | 现有 named path pattern 测试只覆盖参数化模板或简单输出，没有覆盖 path pattern 内部多 owner projection。 | 本类问题未被单元测试拦住。 |

### 15.3 修改目标

- 为 `named_path_pattern` 的 projection 建立确定性 owner -> role / alias 映射。
- 映射来源必须从语义层 path pattern 模板、registry 或模板静态解析派生，不在 builder 中硬编码 `Service -> a`、`Tunnel -> b` 这类平行表。
- 支持 path pattern 内部多 owner projection，例如 `Service.elem_type`、`Tunnel.elem_type`、`NetworkElement.model`、`Port vertex_full` 同时返回。
- 如果 path pattern 模板无法唯一暴露某 owner 的变量 alias，应返回 `generation_failed / compiler_shape_mismatch` 或等价 DSL 表达失败，而不是抛 `service_failed`。
- 保留 MIR-010 红线：不按样本写分支，不猜 owner 对应哪个变量，不绕过 DSL 直接拼 Cypher。
- 沉淀 `qa_fe30ff3300d3` 和同类 multi-owner path projection 回归。

非目标：

- 不重写 path pattern 机制。
- 不把所有复杂路径都改成裸 Cypher fallback。
- 不解决 `semantic_match_rejected` verdict 口径。
- 不解决 path pattern 参数绑定以外的 literal resolver 问题。

### 15.4 子 IR 总览

| 子 IR | 名称 | 优先级 | 估算 | 角色 | 依赖 |
| --- | --- | --- | --- | --- | --- |
| MIR-012.0 | Baseline and Failing Regression | P0 | S | QA/backend | MIR-010 |
| MIR-012.1 | Path Pattern Output Role Map Derivation | P0 | M | backend | .0 |
| MIR-012.2 | Named Path Pattern Projection Builder | P0 | M | backend | .1 |
| MIR-012.3 | Failure Classification and Trace | P0 | S | backend/infra | .2 |
| MIR-012.4 | Regression Matrix | P0 | S | QA/backend | .0 到 .3 |

### MIR-012.0 Baseline and Failing Regression

目标：固化 `qa_fe30ff3300d3` 的失败链路，避免把内部 KeyError 当成服务失败长期隐藏。

建议文件：

```text
services/cypher_generator_agent/tests/dsl/
services/cypher_generator_agent/tests/integration/
docs/experiments/2026-05-28-runtime-center-cga-job-analysis.md
```

开发内容：

- 增加最小 binding plan fixture：`query_shape=named_path_pattern`、`path_pattern_bindings=[tunnel_full_path]`、projection 包含 `Service/Tunnel/NetworkElement/Port` 多 owner。
- 当前实现下应复现 `KeyError: 'Service'` 或等价 builder failure。
- 把 `qa_fe30ff3300d3` 加入回归样本。

验收：

- 修复前测试能稳定暴露 named path pattern projection target 缺失。
- trace 中能看出失败发生在 `dsl_builder`，而不是 testing-agent verdict。

### MIR-012.1 Path Pattern Output Role Map Derivation

目标：从 path pattern 模板 / semantic registry 派生 owner 到模板变量的映射。

建议文件：

```text
services/cypher_generator_agent/app/semantic_model/
services/cypher_generator_agent/app/dsl/
services/cypher_generator_agent/app/compiler/templates.py
```

开发内容：

- 静态解析 path pattern Cypher 模板中的 vertex alias 和 label，例如 `(a:Service)`、`(b:Tunnel)`、`(c:NetworkElement)`、`(d:Port)`。
- 生成 owner -> alias / role map，例如 `Service -> a`、`Tunnel -> b`、`NetworkElement -> c`、`Port -> d`。
- 如果同一 owner 在模板中出现多次且无法唯一确定，标记为 ambiguous，不进入确定性 projection builder。
- 该派生层只读取模板结构，不根据样本问题猜测。

验收：

- `tunnel_full_path` 可派生出四个 owner 的唯一 role。
- owner 重复或无法解析时不会猜测，会返回明确 failure。

### MIR-012.2 Named Path Pattern Projection Builder

目标：让 `_build_named_path_pattern()` 能消费 MIR-012.1 的 role map，把多 owner projection 落成 DSL projection item。

建议文件：

```text
services/cypher_generator_agent/app/dsl/builder.py
services/cypher_generator_agent/app/dsl/parser.py
services/cypher_generator_agent/app/compiler/compiler.py
```

开发内容：

- `_build_named_path_pattern()` 构造 `role_by_owner` 时合并 path pattern role map。
- projection item 的 `target` 指向 path pattern 内部 role / alias，而不是依赖 `vertex_bindings`。
- 对 `vertex_full` projection 也要支持 path pattern 内部 owner，例如 `Port` 节点整体返回。
- 不改变 path pattern 参数绑定语义；已有参数化 path pattern 用例不得回归。

验收：

- `Service.elem_type`、`Tunnel.elem_type`、`NetworkElement.model`、`Port vertex_full` 可同时落位。
- 生成 Cypher 仍通过现有 DSL parser / compiler / self-validation。
- 无样本 ID 分支，无裸 Cypher 旁路。

### MIR-012.3 Failure Classification and Trace

目标：无法派生 role map 或 projection 无法落位时，输出可诊断的 generation failure，而不是 service failure。

建议文件：

```text
services/cypher_generator_agent/app/core/errors.py
services/cypher_generator_agent/app/core/pipeline.py
services/cypher_generator_agent/app/observability/trace.py
```

开发内容：

- 捕获 named path pattern projection role 缺失，转为 `compiler_shape_mismatch` 或更精确的 existing failure reason。
- trace 记录：
  - path pattern name。
  - 派生出的 owner -> role map。
  - 未能落位的 projection owner/property。
- 保留 `service_failed` 给真正的依赖、配置、语义资产异常，不再用于普通 DSL 表达缺口。

验收：

- 不再出现 `KeyError: 'Service'` 这类裸异常。
- 如果无法唯一映射，运行中心能看到明确的 DSL 表达失败原因。

### MIR-012.4 Regression Matrix

目标：覆盖 named path pattern 的多 owner projection 及防误伤。

建议文件：

```text
services/cypher_generator_agent/tests/dsl/
services/cypher_generator_agent/tests/integration/
tests/test_runtime_results_service_api.py
```

开发内容：

- 正向样本：`qa_fe30ff3300d3`。
- 同类样本：Service -> Tunnel -> NetworkElement -> Port 路径，返回多个 owner 的属性或节点整体。
- 防误伤：
  - 只有 path pattern 参数、无多 owner projection 的旧用例不回归。
  - owner 重复或 role 不唯一时退 failure，不猜测。
  - path pattern edge/direction 选择仍不由本 MIR 裁决。

验收：

- `qa_fe30ff3300d3` 不再 `service_failed`。
- named path pattern 多 owner projection 至少能生成可评测 Cypher；是否语义等价交给 testing-agent verdict。
- 680 全量中 `semantic_contract_unaligned` 对应的 KeyError 类问题归零或显著下降。

## 16. 后续 MIR 模板

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

## 17. 审核结论与后续 MIR 检查

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
