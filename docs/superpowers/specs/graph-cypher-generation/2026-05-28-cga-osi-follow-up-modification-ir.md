# CGA OSI Follow-up Modification IR

> 日期：2026-05-28
> 状态：持续维护 IR v0
> 适用分支：`cypher-generation-osi`
> IR 含义：Implementation Roadmap / Implementation Requirements

## 1. 文档定位

本文档不是某一个 bug 的单点修复方案，而是 CGA OSI 重写后持续记录后续修改的实施 IR。

使用方式：

- 每发现一类系统性问题，新增一个 `MIR-*` 修改项。
- 每个 `MIR` 都必须写清楚背景、失效链路、修改范围、建议文件、验收标准和测试要求。
- 同一类问题可以持续追加观察、修复阶段、回归结果和剩余风险。
- 不在本文档中直接贴实现代码；实现前先由用户审核 MIR。
- 本文档只记录 CGA 生成链路、语义层、DSL、validator、compiler、trace、testing-agent contract 等工程修改，不记录 UI 样式微调。

当前已记录修改项：

| MIR | 名称 | 状态 | 触发样本 | 优先级 |
| --- | --- | --- | --- | --- |
| MIR-001 | Projection Slot Coverage and No Silent ID Downgrade | 已严格闭环 | `qa_9cfa692813d5` | P0 |
| MIR-002 | Decomposer Substantive Slot Hard Cut | 代码已完成，性能验收未达标，待再决策 | decomposer latency / duplicate retrieval terms | P0 |
| MIR-003 | Executable Cypher Inline Output with Template Trace | 已远端闭环 | `qa_c2508f2c0bac` | P0 |

后续新增问题按 `MIR-004`、`MIR-005` 继续追加。

## 2. 总体修改原则

1. **LLM 只填空，不独自决定最终结构**：LLM 可以做自然语言拆解和候选内选择，但字段绑定、路径约束、coverage 校验、DSL 编译必须有工程防线。
2. **不静默吞语义**：用户问题中的实义词必须进入正确语义槽位；如果无法进入，应 repair、clarification 或 generation_failed。
3. **coverage 要按槽位判断**：不是“词被某个候选命中”就算覆盖，而是必须进入语义上正确的位置，例如 projection、filter、group_by、order_by、path、limit。
4. **builder/compiler 不猜业务意图**：下游只编译明确 DSL，不把模糊结构自动窄化成看似可运行的 Cypher。
5. **错误要在靠前阶段暴露**：如果 binding plan 已经丢失用户要求，semantic validator 应拦住，不应等到 testing-agent 比对 golden 才发现。
6. **每个修改项都要沉淀 regression**：修复必须配套可复跑的 fixture、单元测试或 golden matrix slice。
7. **优先加防线，谨慎加词表/闸门**：每个 MIR 都要审查是否引入手工维护的词表或特例闸门。能从 semantic model、registry、schema 或 trace 派生的规则，不允许在代码中再写一份平行词表。

## 3. MIR-001 Projection Slot Coverage and No Silent ID Downgrade

### 3.1 背景

触发样本：

```text
qa_9cfa692813d5
查询所有服务的ID、名称、元素类型、服务质量等级、带宽和时延。
```

期望语义：

```text
MATCH (svc:Service)
RETURN
  svc.id,
  svc.name,
  svc.elem_type,
  svc.quality_of_service,
  svc.bandwidth,
  svc.latency
```

实际生成：

```cypher
MATCH (svc:Service)
RETURN svc.id AS service_id
```

trace 现象：

```json
{
  "selected_vertices": ["Service"],
  "selected_properties": [],
  "projection": [{"semantic_type": "vertex", "name": "Service"}]
}
```

`question_decomposer` 已识别 `服务、ID、名称、元素类型、服务质量等级、带宽、时延`，但后续没有把这些字段词落成 property-level projection。

### 3.2 失效链路

| 层级 | 失效点 | 影响 |
| --- | --- | --- |
| 主因：grounded understanding | 多个返回字段被塌缩成一个裸 `Service` vertex projection。 | `selected_properties=[]`，字段信息从 binding plan 中消失。 |
| 防线 1：DSL builder | 裸 `vertex` projection 被静默编译成 id property。 | “返回节点/对象”被无依据窄化为“返回 ID”。 |
| 防线 2：semantic validator | 只检查已有 projection 合法，不检查用户要求字段是否进入 projection。 | projection coverage gap 没有被拦截。 |
| 防线 3：self-validation | 只检查 Cypher 静态合法性。 | `RETURN svc.id` 合法，因此继续放行。 |

### 3.3 修改目标

- 将显式返回字段落成确定性 property-level projection。
- 禁止 DSL builder 静默把模糊 vertex projection 降级成 ID。
- 在 semantic validator 中增加 projection coverage 防线。
- 将该问题沉淀为 regression fixture。
- 保持 CGA 不连接数据库、不执行 Cypher。

非目标：

- 不扩展新的复杂 query shape。
- 不要求一次解决所有路径、聚合、Top-N 问题。
- 不引入 raw Cypher fallback。

### 3.4 子 IR 总览

状态口径：

- `已完成`：代码、测试和主链路行为均已落地。
- `核心完成`：主链路行为已落地并有测试，但实现形态与 IR 建议文件或完整边界仍有差异。
- `部分完成`：已有基础能力，仍缺明确的 schema 收紧、运行中心展示或专门验收。
- `待追加`：尚未按 IR 做成独立工程交付。

| 子 IR | 名称 | 开发状态 | 优先级 | 估算 | 角色 | 依赖 |
| --- | --- | --- | --- | --- | --- | --- |
| MIR-001.0 | Regression Fixture and Baseline | 已完成 | P0 | S | QA/backend | 无 |
| MIR-001.1 | Question Decomposer Slot Role Annotation | 已完成 | P0 | M | LLM/backend | MIR-001.0 |
| MIR-001.2 | Projection Slot Resolver | 已完成 | P0 | M | backend | MIR-001.1 |
| MIR-001.3 | Projection Coverage Validator | 已完成 | P0 | M | backend | MIR-001.2 |
| MIR-001.4 | DSL Builder No Silent ID Downgrade | 已完成 | P0 | S | backend | MIR-001.3 |
| MIR-001.5 | Grounded Understanding Projection Contract | 已完成 | P1 | M | backend/LLM | MIR-001.2 |
| MIR-001.6 | Trace and Repair Contract for Projection Coverage | 已完成 | P1 | S | backend/infra | MIR-001.3 |
| MIR-001.7 | Self-Validation Shape Guard Extension | 已完成 | P2 | S | backend | MIR-001.4 |
| MIR-001.8 | Regression Matrix Integration | 已完成 | P0 | S | QA/infra | MIR-001.0 到 MIR-001.7 |

当前已开发完成项：

- `MIR-001.0`：已新增 `gq-031`、`gq-032`、`gq-033` 三条 projection slot golden case，并同步 `questions.yaml`。
- `MIR-001.1`：`question_decomposition_v1` 已新增 `slot_terms`，prompt 已加入语义槽位说明与示例。
- `MIR-001.2`：projection slot resolver 已落地在 pipeline helper 中，并从 semantic model property synonyms / property name / candidate evidence 派生字段映射；`attached_to` 支持通过 vertex synonyms 约束 owner。
- `MIR-001.3`：semantic validator 已支持 projection slot coverage，缺失时返回 `projection_coverage_missing`。
- `MIR-001.4`：DSL builder 已拒绝裸 vertex projection，默认 ID 已改为显式 property projection，DSL/AST/compiler 已支持 `vertex_full`。
- `MIR-001.5`：`grounded_understanding_v1` 已拒绝裸 `semantic_type=vertex` projection 和 edge/metric 等非 projection 类型；允许显式 `property` 与 `vertex_full`。
- `MIR-001.6`：trace 中已能定位 `projection_coverage_missing` 的 required/covered/uncovered；运行中心字段说明已补充 `slot_terms` 和返回字段覆盖缺失解释。
- `MIR-001.7`：compiler/self-validation 的 RETURN shape guard 已覆盖 DSL projection alias，新增 `vertex_full` 编译验证。
- `MIR-001.8`：projection regression slice 已并入统一 golden matrix；`gq-031/gq-032` 为 smoke，`gq-033` 为 full。

当前剩余边界：

- `MIR-001` 本身已闭环；`qa_c2508f2c0bac` 的参数传递问题后续已由 MIR-003 闭环。`qa_c3e83dd7ad32` 的 Top-N、`qa_6494b2085699` 的 IP owner/property 绑定、`qa_a5f4b0253af3` 的多跳路径仍属于后续 MIR，不纳入本项。
- projection slot resolver 当前保留在 pipeline helper 中，没有单独拆出 `projection_resolver.py`；这是实现组织形式差异，不影响本 MIR 的行为验收。

推荐顺序：

```text
MIR-001.0 -> MIR-001.1 -> MIR-001.2 -> MIR-001.3 -> MIR-001.4 -> MIR-001.5 -> MIR-001.6 -> MIR-001.7 -> MIR-001.8
```

如果只能先做一项，优先做 `MIR-001.3 Projection Coverage Validator`，因为它是通用防线，可以拦住整类“看起来合法但漏返回字段”的问题。`MIR-001.1` 是它的前置输入契约，不应省略。

### 3.5 已采纳的实施决策

1. `vertex_full` 作为 DSL v1 的一等 projection item 类型，而不是 builder 内部私有 normalized form。目标是消灭 `understanding -> builder` 之间的裸 `vertex` 歧义。
2. 默认 list 查询无显式字段时，倾向返回完整节点 `vertex_full`，不是 ID；但实施前必须审查 qa-agent golden 口径。如果现有 golden 将“查询所有服务”标成 `RETURN s.id`，需要先判断 golden 是否应调整，而不是让 CGA 迁就错误口径。
3. `projection_coverage_missing` 默认进入 repair loop，不直接 ask_user；repair 有上限和震荡检测，超过上限转 `generation_failed`。这是系统遗漏，不应让用户补救。
4. 多 owner 字段按两档处理：只有一个连通对象拥有该属性时自动绑定；多个连通对象拥有同名/同义属性时，如果题干含“各自/双方/两端”等词则展开为多个 projection，否则先进入 repair，repair 仍无法确定再 ask_user。禁止用“路径最近对象”静默猜测。
5. 当前 schema 仍保持 `grounded_understanding_v1` 和 `restricted_query_dsl_v1`。这些 schema 尚处于开发定稿阶段；除 CGA 当前开发链路外，暂未发现已上线消费方直接依赖旧 projection 形态。若实施前确认存在外部稳定消费方，再升 v2。
6. 字段词映射不得在 resolver 中硬编码平行词表，必须从 Graph Semantic Model registry 的 property name、`ai_context.synonyms`、description 和候选 evidence 派生。
7. projection/filter/group/sort 等槽位角色应由 question decomposer 在有完整句法上下文时标注，validator 只消费角色并校验最终 DSL，不在末端重新猜句法角色。

### MIR-001.0 Regression Fixture and Baseline

目标：把 `qa_9cfa692813d5` 和同类多字段投影样本固化为回归基线。

建议文件：

```text
services/cypher_generator_agent/tests/fixtures/golden_questions.yaml
services/cypher_generator_agent/tests/integration/test_golden_regression_matrix.py
services/cypher_generator_agent/tests/validation/test_projection_coverage.py
services/cypher_generator_agent/tests/dsl/test_builder_projection.py
```

开发内容：

- 将 `qa_9cfa692813d5` 纳入 active regression scope。
- 补至少 3 个同类多字段 projection case：
  - 单 vertex 多字段：`Service.id/name/elem_type/quality_of_service/bandwidth/latency`
  - 单跳终点多字段：`Tunnel.id/name/bandwidth`
  - 带过滤的多字段：`quality_of_service=Gold` 且返回 `Service.id/name/bandwidth`
- golden 断言必须检查 DSL projection，不只检查最终 Cypher 字符串。
- `qa_526d49332ed1`、`qa_c3e83dd7ad32`、`qa_6494b2085699` 暂不进入 projection coverage active assertion，避免 control term、Top-N、IP owner binding 等相邻问题污染 projection slice 的通过率。

验收：

- 当前实现下新增测试应能暴露 `projection.items` 不完整的问题。
- golden fixture 中每个多字段样本都明确列出 expected projection properties。
- 测试描述中区分“字段投影缺失”和“路径/过滤/执行失败”。

### MIR-001.1 Question Decomposer Slot Role Annotation

目标：在 question decomposition 阶段标注语义槽位角色，避免 validator 末端重新猜测“名称”到底是 projection 还是 filter。

建议文件：

```text
services/cypher_generator_agent/app/decomposition/models.py
services/cypher_generator_agent/app/decomposition/prompt.py
services/cypher_generator_agent/tests/decomposition/test_slot_role_annotation.py
services/cypher_generator_agent/tests/decomposition/test_term_classification.py
```

开发内容：

- 在 `question_decomposition_v1` 中增加槽位角色结构，建议形态：

```json
{
  "slot_terms": [
    {"text": "ID", "slot": "projection", "attached_to": "服务"},
    {"text": "名称", "slot": "projection", "attached_to": "服务"},
    {"text": "金牌", "slot": "filter", "attached_to": "服务质量等级"}
  ]
}
```

- `slot` 初始枚举：

```text
projection | filter | group_by | order_by | limit | path | unknown
```

- prompt 必须明确同词不同槽位的判定：
  - `查询服务的名称`：`名称` 是 projection。
  - `名称为 Service_002 的服务`：`名称` 是 filter property，`Service_002` 是 filter literal。
  - `按状态统计端口数量`：`状态` 是 group_by。
  - `按数量降序返回前3名`：`数量` 是 order_by，`前3` 是 limit。
- 保持覆盖轴和检索角色轴不变；`slot_terms` 是第三条“语义槽位轴”，不是替代 `target_concepts`。

验收：

- `qa_9cfa692813d5` 中 `ID/名称/元素类型/服务质量等级/带宽/时延` 均标为 `projection`。
- `名称为 Service_002 的服务` 中 `名称` 标为 `filter`，不是 projection。
- `按数量降序排列，返回前3名` 中 `数量` 标为 `order_by`，`前3` 标为 `limit`。
- `slot_terms` 缺失或冲突时不能让 validator 自行猜测；应进入 repair/schema retry。

### MIR-001.2 Projection Slot Resolver

目标：新增确定性的 projection slot 解析能力，把用户要求的字段词绑定成 property-level projection。

建议文件：

```text
services/cypher_generator_agent/app/binding/projection_resolver.py
services/cypher_generator_agent/app/binding/models.py
services/cypher_generator_agent/app/core/pipeline.py
services/cypher_generator_agent/tests/binding/test_projection_resolver.py
```

开发内容：

- 新增 `ProjectionResolver`，输入：
  - `QuestionDecomposition`
  - `CandidateRetrievalResult`
  - 已选 vertex / edge / path role
  - optional literal/filter context
- 输出 property-level projection items：

```json
[
  {"semantic_type": "property", "owner": "Service", "name": "id", "alias": "service_id"},
  {"semantic_type": "property", "owner": "Service", "name": "name", "alias": "service_name"}
]
```

- 解析规则：
  - 字段词只能从 semantic model registry 的 property name、`ai_context.synonyms`、description 和 candidate evidence 中选择。
  - resolver 禁止维护独立硬编码字段词表；如果需要补别名，应补到语义模型 YAML，而不是补到 resolver 代码。
  - 单 vertex 查询中，字段词默认绑定到唯一 vertex。
  - single-hop/path 查询中，字段词必须根据局部修饰词绑定到 source/end/path role，例如“隧道的名称”绑定到 `Tunnel.name`。
  - `ID/编号/名称/类型/元素类型/服务质量等级/带宽/时延/状态/厂商` 等字段词必须通过 registry synonym/evidence 命中，不能靠代码枚举。
  - 如果字段词可绑定到多个 owner 且上下文无法消歧，返回 ambiguity，不静默选择。
- `_deterministic_grounding_from_slots` 不再只从 filter 中提取 selected properties，应合并：

```text
filter_properties + projection_properties
```

验收：

- `qa_9cfa692813d5` 的 resolver 输出 6 个 `Service` property projection。
- `qa_c80a82efe561` 的 resolver 输出 3 个 `Tunnel` property projection。
- `qa_c2508f2c0bac` 的 resolver 同时保留 filter property `Service.quality_of_service` 和 projection properties `Service.id/name/bandwidth`。
- ambiguous owner 场景返回 structured ambiguity，不产生猜测 projection。
- 修改语义同义词时必须改 semantic model fixture，并有 registry/retriever 测试证明 resolver 从模型派生映射。

### MIR-001.3 Projection Coverage Validator

目标：在 semantic validator 中补 projection coverage 硬约束，作为通用防线。

建议文件：

```text
services/cypher_generator_agent/app/validation/semantic_validator.py
services/cypher_generator_agent/app/validation/coverage.py
services/cypher_generator_agent/app/core/errors.py
services/cypher_generator_agent/tests/validation/test_projection_coverage.py
```

开发内容：

- 定义 projection coverage input：
  - decomposition `slot_terms` 中 `slot=projection` 的字段词。
  - final binding plan / DSL projection。
- coverage 判定从“词被候选引用”升级为“词进入正确槽位”：

```text
字段词作为返回字段出现 -> 必须进入 projection
字段词作为过滤条件出现 -> 必须进入 filter
字段词作为分组维度出现 -> 必须进入 group_by
字段词作为排序依据出现 -> 必须进入 sort/order_by
```

- 本 MIR v1 先实现 projection slot；filter/group_by/order_by/limit/path 先预留结构并明确不在 validator 末端猜测槽位。
- 新增错误码：

```text
projection_coverage_missing
projection_slot_mismatch
projection_owner_ambiguous
```

验收：

- 如果 decomposition 要求 6 个字段但 projection 只有 `Service.id`，validator fail。
- 如果 projection 中包含全部字段，validator pass。
- 如果字段词只在 selected_properties 中出现但没有进入 DSL projection，validator fail。
- coverage error 会进入 repair / generation_failed，不会继续编译 Cypher。
- `projection_coverage_missing` 不产生 ask_user clarification，除非 repair loop 达到上限后仍存在多 owner 真歧义。

### MIR-001.4 DSL Builder No Silent ID Downgrade

目标：取消 DSL builder 对模糊 vertex projection 的静默 ID 降级。

建议文件：

```text
services/cypher_generator_agent/app/dsl/builder.py
services/cypher_generator_agent/app/dsl/models.py
services/cypher_generator_agent/app/dsl/parser.py
services/cypher_generator_agent/tests/dsl/test_builder_projection.py
```

开发内容：

- builder 接收 projection 时遵循：
  - property projection -> 编译成 property RETURN。
  - `vertex_full` -> 编译成完整节点 RETURN。
  - 模糊裸 vertex -> 抛出 `unsupported_projection_shape` 或 `ambiguous_projection`。
- 删除或限制当前“如果 projection 为空则补 ID”的行为：
  - 仅当 query shape 明确允许 default projection 且 decomposition 没有显式字段词时，才允许补 ID。
  - 一旦存在 projection coverage requirements，禁止默认补 ID。
- 对 detail query 保留显式整节点路径，不使用隐式 ID 降级。

验收：

- 喂入 `{semantic_type: "vertex", name: "Service"}` 的 projection，builder 不再生成 `Service.id`。
- 空 projection + 无显式字段需求的简单 list 可以按产品约定返回默认 ID。
- 默认 list 查询的产品口径先按 `vertex_full` 设计；如果 golden audit 证明现有标准要求 ID，需要在 fixture 审核项中单独记录原因。
- 空 projection + 有显式字段需求必须失败。
- `vertex_full` 能稳定编译成 `RETURN svc AS service` 或 DSL 中约定的整节点表达。

### MIR-001.5 Grounded Understanding Projection Contract

目标：收紧 grounded understanding 的 projection contract，避免“裸 vertex”表达混淆。

建议文件：

```text
services/cypher_generator_agent/app/understanding/models.py
services/cypher_generator_agent/app/understanding/prompt.py
services/cypher_generator_agent/app/understanding/grounded_understanding.py
services/cypher_generator_agent/tests/understanding/test_grounded_understanding_projection_contract.py
```

开发内容：

- 区分 projection item 类型：
  - `property`：明确返回某个 property。
  - `vertex_full`：明确返回整个节点。
  - 禁止模糊的裸 `vertex` projection 进入常规路径。
- grounded understanding prompt 增加 projection 落地规则：
  - 如果 decomposition 中存在具体字段词，必须输出 property-level projection。
  - 不能用单个 vertex 概括多个字段。
  - 只有用户明确说“详情/完整节点/节点信息”时才允许 `vertex_full`。
- few-shot 示例必须包含 `qa_9cfa692813d5` 这类多字段投影。
- LLM 输出违反 projection contract 时触发 schema retry；重试后仍失败则进入 `grounded_understanding_schema_invalid` 或 repair path。

验收：

- schema 不再接受 `{ "semantic_type": "vertex", "name": "Service" }` 作为模糊 projection。
- `vertex_full` 必须有明确 intent evidence，例如 `详情/信息/节点`。
- LLM fallback path 对多字段 projection 输出 property items。
- 现有 detail query 样本不被错误改成 property-only projection。

### MIR-001.6 Trace and Repair Contract for Projection Coverage

目标：让 projection coverage 失败在 trace、运行中心和 repair 输入中可诊断。

建议文件：

```text
services/cypher_generator_agent/app/observability/trace.py
services/cypher_generator_agent/app/observability/stages.py
services/cypher_generator_agent/app/repair/models.py
services/cypher_generator_agent/tests/observability/test_projection_coverage_trace.py
```

开发内容：

- 在 trace 的 `semantic_validator` stage 输出：

```json
{
  "coverage": {
    "projection": {
      "required_terms": ["ID", "名称", "带宽"],
      "covered_terms": ["ID"],
      "missing_terms": ["名称", "带宽"],
      "slot": "projection"
    }
  }
}
```

- repair controller 输入保留：
  - missing term
  - expected owner
  - candidate properties
  - final projection items
- user-visible clarification 不应把 projection coverage 缺失表达成“某个值未解析”。这是系统绑定缺失，优先进入 repair/generation_failed。
- repair prompt 应明确列出缺失 projection term 和候选 property，例如“漏了 名称/带宽/时延，请补为 property projection”。
- repair loop 使用既有上限和 oscillation 检测；超过上限转 `generation_failed`。

验收：

- `projection_coverage_missing` 在 trace 中能定位到 missing terms。
- Runtime Center 可显示该错误的阶段、原因码、缺失字段。
- repair-agent 能拿到足够上下文判断“缺 projection”，而不是误判为 literal 问题。

### MIR-001.7 Self-Validation Shape Guard Extension

目标：补充末端 shape guard，验证 Cypher RETURN aliases 与 DSL projection 一致；不承担自然语言 coverage 判断。

建议文件：

```text
services/cypher_generator_agent/app/cypher_validation/shape.py
services/cypher_generator_agent/tests/cypher_validation/test_shape_projection.py
```

开发内容：

- 确认 self-validation shape check 比较的是 DSL projection 和 compiler output：
  - RETURN alias 集合/顺序是否和 DSL expected aliases 一致。
  - 参数化 projection 不影响 alias check。
- 不在 self-validation 中直接读取 natural language terms，避免职责漂移。
- 如果 DSL projection 有 6 项，Cypher RETURN 只有 1 项，则 self-validation fail。

验收：

- DSL 6 projection -> Cypher 1 RETURN 的人工 case fail。
- DSL 1 projection -> Cypher 1 RETURN pass。
- self-validation 不误报 detail node return。

### MIR-001.8 Regression Matrix Integration

目标：把本 MIR 的测试纳入 regression matrix，防止后续 prompt / binder / builder 改动回归。

建议文件：

```text
services/cypher_generator_agent/tests/fixtures/golden_questions.yaml
services/cypher_generator_agent/tests/integration/test_golden_regression_matrix.py
docs/experiments/2026-05-28-runtime-center-cga-job-analysis.md
```

开发内容：

- 将本轮 8 样本中的以下 case 标记为 projection / slot coverage 回归：
  - `qa_9cfa692813d5`
  - `qa_c80a82efe561`
  - `qa_c2508f2c0bac`
  - `qa_a5f4b0253af3`
- 将以下样本保留在相邻 regression scope，但不强行并入 MIR-001：
  - `qa_526d49332ed1`：`所有` 属于 literal cleanup / control term。
  - `qa_c3e83dd7ad32`：`前3` 属于 top_n / limit slot。
  - `qa_6494b2085699`：`IP地址` 属于 property owner binding。
- 上述 3 条不能进入 projection coverage active assertion；若它们因相邻问题失败，不应影响 MIR-001 projection slice 通过率。
- CI 或本地 regression 命令必须能单独跑 projection coverage slice。

验收：

- projection coverage slice 可独立执行。
- `qa_9cfa692813d5` 修复后不能只靠最终 Cypher 字符串通过，必须 DSL projection 与 expected projection 同时通过。
- 新增 regression case 失败时，错误能指向 projection slot，而不是泛化 testing mismatch。

### MIR-001 Implementation Audit 2026-05-29

执行结论：MIR-001 已严格闭环。projection slot 的输入标注、确定性属性落地、coverage validator、DSL no-downgrade、grounded schema contract、trace/运行中心说明、self-validation shape guard 和 golden regression slice 均已落地。

验证命令：

```bash
PYTHONPATH=. pytest services/cypher_generator_agent/tests -q
PYTHONPATH=. pytest services/cypher_generator_agent/tests/integration/test_golden_questions.py -q
PYTHONPATH=. pytest tests/test_runtime_results_service_api.py::test_runtime_results_detail_script_puts_cypher_comparison_in_overview -q
```

最近一次严格闭环验证结果：

```text
services/cypher_generator_agent/tests: 484 passed in 3.99s
tests/test_runtime_results_service_api.py: 32 passed in 0.29s
```

对照 IR：

| 子 IR | 状态 | 实现/证据 |
| --- | --- | --- |
| MIR-001.0 Regression Fixture and Baseline | 完成 | `golden_questions.yaml` / `questions.yaml` 已新增 `gq-031`、`gq-032`、`gq-033`，覆盖单点多字段、单跳终点多字段、filter + projection 区分。 |
| MIR-001.1 Question Decomposer Slot Role Annotation | 完成 | `question_decomposition_v1` 新增 `slot_terms`，prompt 增加“轴三：语义槽位”与示例；测试覆盖 projection/path slot。 |
| MIR-001.2 Projection Slot Resolver | 完成 | deterministic grounding 根据 `slot_terms`、候选集合和 semantic model property synonyms/name/evidence 生成 property-level projection；`attached_to` 可通过 vertex synonyms 约束 owner。实现位于 pipeline helper。 |
| MIR-001.3 Projection Coverage Validator | 完成 | coverage schema 新增 slot coverage；validator 合并 plan projection 中的 `slot_terms`，缺失时返回 `projection_coverage_missing` / `repair_binding`。 |
| MIR-001.4 DSL Builder No Silent ID Downgrade | 完成 | builder 禁止裸 `semantic_type=vertex` projection；默认 ID 返回改为显式 property projection；DSL/AST/compiler 支持一等 `vertex_full`。 |
| MIR-001.5 Grounded Understanding Projection Contract | 完成 | `GroundedUnderstanding.projection` validator 拒绝裸 vertex、edge/metric 等非 projection 类型；允许 property 与显式 vertex_full，并有 schema/boundary 测试。 |
| MIR-001.6 Trace and Repair Contract | 完成 | semantic validator 的 projection coverage failure 可进入 repair；trace 中可见 required/covered/uncovered；运行中心字段说明补充 `slot_terms` 和 `projection_coverage_missing`。 |
| MIR-001.7 Self-Validation Shape Guard Extension | 完成已有能力确认 | compiler 对 DSL projection 产出 `expected_return_aliases`，self-validation shape 继续校验 RETURN alias；新增 `vertex_full` compiler case。 |
| MIR-001.8 Regression Matrix Integration | 完成 | projection slice 已并入 golden matrix：`gq-031/gq-032` smoke，`gq-033` full；golden matrix 总数更新为 33。 |

实现边界：

- 本轮没有引入 raw Cypher fallback，也没有连接数据库。
- 没有在 resolver 中维护中文字段硬编码词表；需要的新同义词补在 semantic model YAML 中。
- 默认“无显式字段的 list 查询”仍保持既有 ID 口径，但实现上已从“裸 vertex 静默降级”改成“显式 id property projection”。是否改为 `vertex_full` 需要先审核 qa-agent/golden 口径。
- `qa_c2508f2c0bac` 的参数传递契约已由 MIR-003 闭环；Top-N、IP owner/property 绑定、多跳路径方向等后续问题另起 MIR，不阻塞 MIR-001 closure。

## 4. MIR-002 Decomposer Substantive Slot Hard Cut

### 4.1 背景

触发问题：

- `question_decomposer` 的 LLM 调用延迟偏高，交互链路难以稳定满足端到端 5 秒目标。
- 实测显示 TTFT 基本正常，主要瓶颈在输出 token 解码；独立 `slot_terms` 数组是最大重复输出来源。
- 当前 `substantive_terms: list[str]` 与 `slot_terms: list[SlotTerm]` 两个字段表达同一批表层词的不同视图，导致 LLM 输出重复、内部表示双轨、retriever 搜索词重复。

实测摘要：

| Query | 版本 | input tokens | output tokens | 耗时 |
| --- | --- | ---: | ---: | ---: |
| `查询所有服务使用的隧道，返回隧道的 ID、名称和带宽` | 当前 baseline | 3095 | 270 | streaming 多次约 7.2-9.5s，生产路径曾见 12-14s |
| 同上 | 去 schema 但保留 slot 输出 | 约 2290 | 270 | 多数约 6.5-9.1s，收益有限 |
| 同上 | 省略 slot 输出 | 约 2518 | 162 | 约 4.6-5.0s，但语义不等价 |

关键结论：

- `slot_terms` 造成的 70-110 个重复 output tokens 是主要可控成本。
- 当前 LLM 接口使用 `response_format={"type":"json_object"}`，不是 vLLM/DashScope schema-level `guided_json`；因此本 MIR 不删除 prompt 中的完整 JSON Schema。
- 切换 guided decoding 是后续独立 MIR，不与本项混做。

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
- `SubstantiveTerm` 携带：
  - `text`
  - `slot`
  - optional `attached_to`
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

### 4.4 Hard Cut 禁止项

实施时禁止：

- 保留 `slot_terms` 字段，即使标记 deprecated。
- 添加 `slot_terms` property 或 helper，从 `substantive_terms` 派生旧结构。
- 在 `_decomposition_payload` 或 normalizer 中把新结构翻译回旧结构。
- 同时支持 `substantive_terms: list[str]` 和 `substantive_terms: list[SubstantiveTerm]`。
- 新增 prompt 模板分支、schema feature flag 或兼容 fallback。
- 在注释、commit message 或文档中声明“暂时保留旧结构以兼容”。

coverage report 内部用于表达 projection required/covered/uncovered 的结构可以继续保留现有 coverage 命名；本 MIR 要删除的是 decomposition 输出与内部 decomposition payload 中的独立 `slot_terms` 表示。

### 4.5 子 IR 总览

| 子 IR | 名称 | 状态 | 优先级 | 估算 | 角色 | 依赖 |
| --- | --- | --- | --- | --- | --- | --- |
| MIR-002.0 | Baseline Latency and Token Capture | 部分完成 | P0 | S | QA/backend | 无 |
| MIR-002.1 | Decomposition Model Hard Cut | 已完成 | P0 | M | backend | MIR-002.0 |
| MIR-002.2 | Decomposition Prompt Hard Cut | 已完成 | P0 | M | LLM/backend | MIR-002.1 |
| MIR-002.3 | Pipeline Slot Consumers Migration | 已完成 | P0 | M | backend | MIR-002.1 |
| MIR-002.4 | Retriever Duplicate Search Term Removal | 已完成 | P0 | S | backend | MIR-002.1 |
| MIR-002.5 | Validation and Coverage Migration | 已完成 | P0 | S | backend | MIR-002.3 |
| MIR-002.6 | Test and Golden Smoke Update | 已完成 | P0 | M | QA/backend | MIR-002.1 到 MIR-002.5 |
| MIR-002.7 | Post-change Latency and Token Verification | 已完成，未达性能目标 | P0 | S | QA/backend | MIR-002.6 |

推荐顺序：

```text
MIR-002.0 -> MIR-002.1 -> MIR-002.2 -> MIR-002.3 -> MIR-002.4 -> MIR-002.5 -> MIR-002.6 -> MIR-002.7
```

### MIR-002.0 Baseline Latency and Token Capture

目标：保留本次 hard cut 前的可比基线，避免改后只凭体感判断性能收益。

建议文件：

```text
docs/experiments/2026-05-28-runtime-center-cga-job-analysis.md
```

开发内容：

- 记录以下两条 query 的改前 3 次数据：
  - `查询所有服务使用的隧道，返回隧道的 ID、名称和带宽`
  - `Gold 服务使用了哪些隧道`
- 每次记录：
  - LLM input tokens
  - LLM output tokens
  - decomposer 端到端耗时
  - 是否发生 schema retry

验收：

- 基线数据可与 MIR-002.7 的改后数据逐项对比。
- 若改前数据来自 streaming 测试，应注明它与生产非 streaming 路径的差异。

### MIR-002.1 Decomposition Model Hard Cut

目标：修改 decomposition Pydantic 模型，使 `substantive_terms` 成为携带 slot 的对象数组，并彻底删除 decomposition 层独立 `slot_terms`。

建议文件：

```text
services/cypher_generator_agent/app/decomposition/models.py
services/cypher_generator_agent/tests/decomposition/test_term_classification.py
services/cypher_generator_agent/tests/decomposition/test_schema_retry.py
```

开发内容：

- 新增 `SlotKind` 枚举：

```text
projection | filter | group_by | order_by | limit | path | unknown
```

- 新增 `SubstantiveTerm`：

```json
{"text": "名称", "slot": "projection", "attached_to": "服务"}
```

- 将 `QuestionDecomposition.substantive_terms` 从 `list[str]` 改为 `list[SubstantiveTerm]`。
- 删除 `SlotTerm` 类。
- 删除 `QuestionDecomposition.slot_terms` 字段。
- 保留 `target_concepts`、`relation_phrases`、`literal_candidates`，它们继续作为引用 `substantive_terms[].text` 的检索子视图。
- 保持 `question_decomposition_v1` 不变。

验收：

- `QuestionDecomposition.model_fields` 中不存在 `slot_terms`。
- `SubstantiveTerm` 能校验 `text/slot/attached_to`。
- 旧结构输入因为 extra field 或类型错误校验失败，不做兼容。

### MIR-002.2 Decomposition Prompt Hard Cut

目标：让 LLM 直接输出新结构，减少重复 JSON 对象和重复 text 字符串。

建议文件：

```text
services/cypher_generator_agent/app/decomposition/prompt.py
services/cypher_generator_agent/tests/infrastructure/test_llm_client.py
```

开发内容：

- 删除 prompt 中“二轴/三轴/同词出现在两处不是矛盾”一类说明。
- 删除独立 `slot_terms` 章节和示例字段。
- 将 `substantive_terms` 说明改成对象数组，每个对象包含 `text`、`slot`、optional `attached_to`。
- 更新 4 个 few-shot 示例：
  - 多字段 projection / path
  - literal + filter
  - time / modality / count
  - clarification
- 明确字段顺序，降低 JSON 输出不确定性。
- 保留完整 JSON Schema 文本，因为当前 provider 只有 `json_object` 模式，不做 schema-level guided decoding。

验收：

- `prompt.py` 中不出现 `slot_terms`。
- `prompt.py` 中不出现“轴三”“三轴”等旧结构术语。
- 4 个示例均使用 `substantive_terms` 对象数组。
- prompt 仍明确要求只返回 JSON、不返回 Markdown/Cypher。

### MIR-002.3 Pipeline Slot Consumers Migration

目标：将 pipeline 内 projection resolver、projection coverage seed/update 的 slot 来源全部改为 `substantive_terms[].slot`。

建议文件：

```text
services/cypher_generator_agent/app/core/pipeline.py
services/cypher_generator_agent/tests/integration/test_pipeline_mvp.py
services/cypher_generator_agent/tests/integration/test_golden_questions.py
```

开发内容：

- 所有当前从 decomposition `slot_terms` 读取 projection/filter/path 的 helper，改为遍历 `substantive_terms` 并按 `slot` 过滤。
- projection 属性解析使用 `SubstantiveTerm.text` 与 `attached_to`。
- projection coverage seed 使用 `slot == projection` 的 substantive term text 作为 required terms。
- coverage update 使用同一来源计算 covered/uncovered。
- 不新增“新结构转旧结构”的 normalizer。

验收：

- `pipeline.py` 中不再出现 decomposition `slot_terms` 读取。
- 多字段 projection case 能继续解析出 property-level projection。
- `attached_to` 仍能约束 projection owner。

### MIR-002.4 Retriever Duplicate Search Term Removal

目标：修复 retriever 同时读取 `substantive_terms` 和 `slot_terms` 导致的重复搜索词问题。

建议文件：

```text
services/cypher_generator_agent/app/retrieval/retriever.py
services/cypher_generator_agent/tests/retrieval/test_candidate_retriever.py
```

开发内容：

- search terms 只从 `substantive_terms[].text`、`target_concepts`、`relation_phrases`、`literal_candidates` 和原问题等非重复来源提取。
- 不再读取 decomposition `slot_terms`。
- 如果后续需要 slot-aware retrieval，source 也必须是 `substantive_terms` 中对应 `slot` 的对象，而不是恢复独立字段。
- 新增测试确认相同 text 不因 slot 视图重复进入 search term list。

验收：

- 同一个 text 在 retriever search terms 中只出现一次。
- 含 projection/path/filter slot 的 decomposition 仍能召回对应 vertex/edge/property 候选。

### MIR-002.5 Validation and Coverage Migration

目标：保持 projection coverage 防线，但其 required terms 来源改为新 decomposition 结构。

建议文件：

```text
services/cypher_generator_agent/app/validation/semantic_validator.py
services/cypher_generator_agent/app/validation/coverage.py
services/cypher_generator_agent/tests/validation/test_coverage.py
```

开发内容：

- `SemanticValidator` 继续消费 coverage report 中的 projection required/covered/uncovered。
- coverage report 的 required projection terms 由 pipeline 从 `substantive_terms[].slot == projection` 生成。
- plan projection 中保留用于 coverage merge 的 projection term evidence，但不得恢复 decomposition `slot_terms` 字段。
- 若 coverage schema 字段名仍为 `slot_terms.projection`，需在注释或文档中明确它属于 coverage report，不是 decomposition 输出字段。

验收：

- projection coverage missing 仍返回 `projection_coverage_missing`。
- coverage failure 仍能在 trace 中展示 required/covered/uncovered。
- 验证路径不依赖 decomposition `slot_terms`。

### MIR-002.6 Test and Golden Smoke Update

目标：更新旧 fixture 和单测，确保 hard cut 是全链路行为而非局部模型变更。

建议文件：

```text
services/cypher_generator_agent/tests/decomposition/test_term_classification.py
services/cypher_generator_agent/tests/decomposition/test_schema_retry.py
services/cypher_generator_agent/tests/retrieval/test_candidate_retriever.py
services/cypher_generator_agent/tests/validation/test_coverage.py
services/cypher_generator_agent/tests/integration/test_golden_questions.py
```

开发内容：

- 更新 decomposition fixture 中所有 `substantive_terms` 为对象数组。
- 删除 fixture 中所有 decomposition `slot_terms`。
- 新增结构性测试：
  - `QuestionDecomposition` 没有 `slot_terms` 字段。
  - `substantive_terms` entry 必须携带 slot。
- 更新 retriever 测试，覆盖 search terms 去重。
- 跑 golden smoke，重点覆盖：
  - 多字段 projection
  - filter + projection
  - 单跳 path

验收：

- decomposition、retrieval、validation、integration 相关单测通过。
- golden smoke 不因字段迁移发生 projection 丢失。
- `rg -n "slot_terms" services/cypher_generator_agent/app services/cypher_generator_agent/tests` 不命中 decomposition 输出、pipeline consumer 或 retriever consumer；若命中 coverage report，必须确认不是 decomposition 字段。

### MIR-002.7 Post-change Latency and Token Verification

目标：验证 hard cut 是否达到预期性能收益；如果偏差过大，停止继续优化并回报数据。

建议文件：

```text
docs/experiments/2026-05-28-runtime-center-cga-job-analysis.md
```

开发内容：

- 对以下两条 query 改后各跑 3 次：
  - `查询所有服务使用的隧道，返回隧道的 ID、名称和带宽`
  - `Gold 服务使用了哪些隧道`
- 每次记录：
  - LLM input tokens
  - LLM output tokens
  - decomposer 端到端耗时
  - retry count
- 与 MIR-002.0 的 baseline 对比。

验收：

- output tokens 预期下降 30-40%。
- decomposer 端到端耗时目标进入约 4-5 秒区间。
- 如果实测与预期偏差超过 30%，停止进一步优化，提交数据后再决策。

### MIR-002 Implementation Audit 2026-05-29

执行结论：MIR-002 的代码侧 hard cut 已完成。`QuestionDecomposition` 已从 `substantive_terms: list[str] + slot_terms: list[SlotTerm]` 迁移为 `substantive_terms: list[SubstantiveTerm]`，独立 decomposition `slot_terms` 字段已删除；prompt、pipeline、retriever、coverage 和测试均已按新结构迁移。

当前不能标记为“性能严格达标”的原因：`MIR-002.7 Post-change Latency and Token Verification` 已补做两条 query 各 3 次采样，但实测 output token 与耗时均未达到预期下降区间。因此本 MIR 当前总状态为：**代码已完成，性能验收未达标，待再决策**。

核查证据：

```text
rg -n "slot_terms" services/cypher_generator_agent/app services/cypher_generator_agent/tests
```

结果为 `0`，说明 CGA app/tests 中已无 decomposition `slot_terms` 字段消费点。当前只在实验文档历史描述和运行中心断言中保留 `slot_terms` 字符串，属于历史记录或“不再展示旧字段”的 UI 测试，不是 CGA decomposition schema。

子项审计：

| 子 IR | 当前状态 | 证据 |
| --- | --- | --- |
| `MIR-002.0 Baseline Latency and Token Capture` | 部分完成 | MIR-002 背景中已有 baseline 摘要表，但未看到两条 query 各 3 次的原始记录。 |
| `MIR-002.1 Decomposition Model Hard Cut` | 完成 | `models.py` 已定义 `SlotKind` 和 `SubstantiveTerm`，`QuestionDecomposition.substantive_terms` 为对象数组；未定义 `SlotTerm` 或 `QuestionDecomposition.slot_terms`。 |
| `MIR-002.2 Decomposition Prompt Hard Cut` | 完成 | `prompt.py` 已要求 `substantive_terms` 对象携带 `text/slot/attached_to`；示例均使用对象数组；prompt 中不再出现 `slot_terms`、`轴三`、`三轴`。 |
| `MIR-002.3 Pipeline Slot Consumers Migration` | 完成 | `pipeline.py` 通过 `_substantive_terms_with_slot(decomposition, slot="projection")` 读取 projection/filter/path 等槽位，不再读取 decomposition `slot_terms`。 |
| `MIR-002.4 Retriever Duplicate Search Term Removal` | 完成 | `retriever.py` 的 search terms 来源不含 `slot_terms`；`test_search_terms_are_unique_by_text` 覆盖同 text 不因不同 slot 重复。 |
| `MIR-002.5 Validation and Coverage Migration` | 完成 | projection coverage seed/update 从 `substantive_terms[].slot == projection` 派生；`SemanticValidator` 继续消费 coverage report。 |
| `MIR-002.6 Test and Golden Smoke Update` | 完成 | decomposition/retrieval/validation/integration 测试均已更新为对象数组结构；结构性测试覆盖 substantive term slot。 |
| `MIR-002.7 Post-change Latency and Token Verification` | 已完成，未达性能目标 | 2026-05-29 采样两条 query 各 3 次，均 `retry_count=0`；结果已追加到实验文档。 |

MIR-002.7 采样结果摘要：

| Query | input tokens 中位数 | output tokens 中位数 | decomposer 耗时中位数 | retry count |
| --- | ---: | ---: | ---: | ---: |
| `查询所有服务使用的隧道，返回隧道的 ID、名称和带宽` | 2836 | 246 | 10540 ms | 0 |
| `Gold 服务使用了哪些隧道` | 2828 | 251 | 9846 ms | 0 |

与 MIR-002.0 baseline 的关键对比：第一条 query 的 output tokens 从 `270` 降至 `246`，约 `8.9%`，未达到 `30-40%` 预期；耗时中位数仍约 `10.5s`，未进入 `4-5s` 目标区间。按 MIR-002.7 规则，偏差超过 30% 时停止继续性能优化，先提交数据并等待后续策略决策。

## 5. MIR-003 Executable Cypher Inline Output with Template Trace

### 5.1 背景

触发样本：

```text
qa_c2508f2c0bac
查询服务质量等级为金牌的所有服务的ID、名称和带宽。
```

CGA 在 MIR-003 修复前的语义理解链路基本正确：

- `literal_resolver` 将“金牌”解析为标准值 `Gold`。
- DSL filter 正确落到 `Service.quality_of_service = Gold`。
- DSL projection 已补齐 `quality_of_service/id/name/bandwidth`。
- `cypher_self_validation` 通过。

当时的实际失败发生在 testing-agent 执行 TuGraph 时：

```text
state = tugraph_execution_failed
error = CypherException: Undefined parameter: $quality_of_service
```

修复前 compiler 输出：

```cypher
MATCH (svc:Service)
WHERE svc.quality_of_service = $quality_of_service
RETURN svc.quality_of_service AS service_quality_of_service,
       svc.id AS service_id,
       svc.name AS service_name,
       svc.bandwidth AS service_bandwidth
```

同时 trace 中有：

```json
{
  "parameters": {
    "quality_of_service": "Gold"
  }
}
```

当时对外执行链路只消费 `generated_cypher` 字符串，不消费 `parameters` 字典。本文档明确 v1 产品契约：**CGA 对外输出的主 Cypher 必须是可直接执行的内联 Cypher**；参数化 Cypher 仅作为 compiler 内部表示和 trace 观测产物保留。当前该契约已由 MIR-003 实现并远端验证。

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

### 5.4 子 IR 总览

| 子 IR | 名称 | 开发状态 | 优先级 | 估算 | 角色 | 依赖 |
| --- | --- | --- | --- | --- | --- | --- |
| MIR-003.0 | Regression Baseline for Parameterized Failure | 已完成 | P0 | S | QA/backend | 无 |
| MIR-003.1 | Compiler Output Contract Split | 已完成 | P0 | M | backend | MIR-003.0 |
| MIR-003.2 | Cypher Literal Inliner | 已完成 | P0 | M | backend | MIR-003.1 |
| MIR-003.3 | Parameter Source Legality Guard | 已完成 | P0 | M | backend | MIR-003.2 |
| MIR-003.4 | Self-Validation No Parameter Placeholder Check | 已完成 | P0 | S | backend | MIR-003.2 |
| MIR-003.5 | Trace and Runtime Center Contract Update | 已完成 | P1 | S | backend/frontend | MIR-003.1 到 MIR-003.4 |
| MIR-003.6 | End-to-End Remote Smoke | 已完成 | P0 | S | QA/backend | MIR-003.0 到 MIR-003.5 |

推荐顺序：

```text
MIR-003.0 -> MIR-003.1 -> MIR-003.2 -> MIR-003.3 -> MIR-003.4 -> MIR-003.5 -> MIR-003.6
```

如果只能先做一项，优先做 `MIR-003.2 Cypher Literal Inliner`，但它必须和 `MIR-003.4` 一起上线；否则仍可能把含 `$param` 的 Cypher 放出系统。

### 5.5 对已实现 IR 的影响评估

进入 MIR-003 实施前，已严格闭环的历史 IR 是 `MIR-001 Projection Slot Coverage and No Silent ID Downgrade`；`MIR-002` 代码侧已完成但性能验收未达标。MIR-003 已改变 compiler 对外 Cypher 文本，因此已影响 MIR-001 的部分回归测试和运行中心展示，但未改变 MIR-001 的核心语义防线。

| 已实现 IR | 影响结论 | 具体影响 | 必须保持不变的能力 |
| --- | --- | --- | --- |
| `MIR-001.0 Regression Fixture and Baseline` | 有测试资产影响 | `gq-033` 属于 filter + projection case，expected Cypher 已改为 `svc.quality_of_service = 'Gold'`。其他不含 filter 参数的 projection fixture 不受影响。 | 多字段 projection fixture 仍必须检查 DSL projection，不得只比对 Cypher 字符串。 |
| `MIR-001.1 Question Decomposer Slot Role Annotation` | 无直接影响 | MIR-003 不修改 decomposition schema、prompt 或 `slot_terms` / `substantive_terms` 语义。 | projection/filter slot 仍由 decomposer 提供，compiler 不重新解释自然语言。 |
| `MIR-001.2 Projection Slot Resolver` | 无直接影响 | MIR-003 不改变 property-level projection 落地逻辑。 | `ID/名称/带宽/时延` 等字段词仍必须落成 property projection。 |
| `MIR-001.3 Projection Coverage Validator` | 无直接影响 | coverage 仍在 DSL/semantic plan 层判断，不依赖 Cypher 是否参数化。 | `projection_coverage_missing` 仍必须在编译前拦截。 |
| `MIR-001.4 DSL Builder No Silent ID Downgrade` | 无直接影响 | DSL builder 不应因为内联 Cypher 改动恢复裸 vertex -> id 的静默降级。 | 裸 `vertex` projection 仍禁止；`vertex_full` 仍是一等 projection item。 |
| `MIR-001.5 Grounded Understanding Projection Contract` | 无直接影响 | grounded schema 不依赖 compiler 字面值表达。 | 仍拒绝裸 vertex、edge/metric 等非 projection 类型。 |
| `MIR-001.6 Trace and Repair Contract` | 有展示契约影响 | 运行中心字段说明需要补充 `cypher_template`、`parameters`、`cypher_executable`，并说明 `cypher_executable/generated_cypher` 才是 v1 执行产物。 | projection coverage 的 required/covered/uncovered 解释仍要保留。 |
| `MIR-001.7 Self-Validation Shape Guard Extension` | 有校验输入影响 | shape guard 仍使用 `expected_return_aliases`，但 self-validation 应校验 `cypher_executable`；不能继续只校验含 `$param` 的 template。 | RETURN alias shape check 仍必须运行，`vertex_full` 编译验证仍必须保留。 |
| `MIR-001.8 Regression Matrix Integration` | 有期望结果影响 | golden matrix 中所有 expected Cypher 若含 `$param`，都要迁移为内联字面值；同时新增断言 trace 中保留 template/parameters。 | `gq-031/gq-032/gq-033` 的 projection slice 仍应保留 smoke/full scope。 |

已随 MIR-003 调整的旧断言/fixture：

```text
services/cypher_generator_agent/tests/fixtures/expected_cypher/gq-001.cypher
services/cypher_generator_agent/tests/fixtures/expected_cypher/gq-033.cypher
services/cypher_generator_agent/tests/compiler/test_single_hop.py
services/cypher_generator_agent/tests/compiler/test_vertex_lookup.py
services/cypher_generator_agent/tests/integration/test_pipeline_mvp.py
```

这些修改属于“输出表达迁移”，不是 MIR-001 语义回退。MIR-003 完成后已重新跑过；后续若继续修改 compiler contract，仍需重跑：

```text
PYTHONPATH=. pytest services/cypher_generator_agent/tests -q
PYTHONPATH=. pytest tests/test_runtime_results_service_api.py -q
```

`MIR-002 Decomposer Substantive Slot Hard Cut` 当前代码侧已完成，性能验收未达标，待再决策。MIR-003 没有改动 MIR-002 的 decomposition hard cut：未恢复 `slot_terms` 字段，也未让 retriever/pipeline 重新读取旧双轨结构；compiler contract 变化只影响 Cypher 输出层，即主输出使用 `cypher_executable`，trace 保留 `cypher_template + parameters`。

### MIR-003.0 Regression Baseline for Parameterized Failure

目标：把 `qa_c2508f2c0bac` 暴露出的参数化执行失败固化为回归基线。

建议文件：

```text
services/cypher_generator_agent/tests/fixtures/golden_questions.yaml
services/cypher_generator_agent/tests/fixtures/expected_cypher/*.cypher
services/cypher_generator_agent/tests/compiler/test_vertex_lookup.py
services/cypher_generator_agent/tests/integration/test_pipeline_mvp.py
```

开发内容：

- 新增或更新一条 filter + projection fixture，题干使用“金牌服务”或 `quality_of_service=Gold`。
- expected Cypher 必须包含内联字面值：

```cypher
WHERE svc.quality_of_service = 'Gold'
```

- expected Cypher 不允许包含：

```text
$quality_of_service
```

- integration 测试断言：
  - `output.cypher` 是可执行内联版。
  - `cypher_compiler` trace 中仍包含 `cypher_template` 和 `parameters`。
  - `cypher_self_validation` 校验的是 `cypher_executable`。

验收：

- 修复前旧实现下该测试应失败，因为 `output.cypher` 仍包含 `$quality_of_service`。
- 当前 MIR-003 实现已通过该测试。

### MIR-003.1 Compiler Output Contract Split

目标：将 compiler 输出拆成模板、参数、可执行 Cypher 三个明确字段。

建议文件：

```text
services/cypher_generator_agent/app/compiler/compiler.py
services/cypher_generator_agent/app/core/pipeline.py
services/cypher_generator_agent/app/api/models.py
services/cypher_generator_agent/app/core/result.py
services/cypher_generator_agent/tests/compiler/test_vertex_lookup.py
services/cypher_generator_agent/tests/integration/test_pipeline_mvp.py
```

开发内容：

- `compile_draft` 保持生成参数化模板和参数字典，但字段命名改清楚：

```text
cypher_template
parameters
expected_return_aliases
```

- `compile` 返回：

```text
cypher_template
parameters
cypher_executable
cypher
validation_result
```

- `cypher` 在 v1 中等同于 `cypher_executable`，作为对外主字段。
- trace 中 `cypher_compiler.output_ref.value` 至少包含：

```json
{
  "schema_version": "cypher_compilation_result_v1",
  "cypher_template": "MATCH ... WHERE svc.quality_of_service = $quality_of_service ...",
  "parameters": {"quality_of_service": "Gold"},
  "cypher_executable": "MATCH ... WHERE svc.quality_of_service = 'Gold' ...",
  "cypher": "MATCH ... WHERE svc.quality_of_service = 'Gold' ...",
  "expected_return_aliases": ["service_quality_of_service", "service_id", "service_name", "service_bandwidth"]
}
```

- 对外 `GenerationOutput.cypher` 和 API submission 的 `generated_cypher` 使用 `cypher_executable`。

验收：

- 任何 generated output 的主 `cypher` 字段不含 `$param`。
- trace 中三份产物都存在且命名明确。
- 旧读取 `parameters` 的内部测试仍可通过，但应改为读取 `cypher_template/parameters/cypher_executable` 的新契约。

### MIR-003.2 Cypher Literal Inliner

目标：新增独立的字面值内联函数，将参数字典安全转换为 Cypher 字面量文本并替换模板中的 `$param`。

建议文件：

```text
services/cypher_generator_agent/app/compiler/literals.py
services/cypher_generator_agent/app/compiler/compiler.py
services/cypher_generator_agent/tests/compiler/test_literal_inliner.py
```

开发内容：

- 新增 `escape_cypher_literal(value: object) -> str`。
- 类型规则：
  - `str`：单引号包围，内部 `'` 转义为 `\'`，内部 `\` 转义为 `\\`。
  - `int` / `float`：直接 `str(value)`，不加引号；`bool` 不得走 `int` 分支。
  - `bool`：输出 `true` / `false` 小写。
  - `None`：输出 `null`。
  - `datetime.date` / `datetime.datetime`：输出 TuGraph 可接受的 datetime/date 表达式；如果当前项目没有稳定约定，先 raise `NotImplementedError`，不得静默转字符串。
  - `list`：输出 `[item1, item2, ...]`，每个元素递归调用 `escape_cypher_literal`。
  - 其他类型：raise `NotImplementedError`。
- 新增 `inline_cypher_parameters(cypher_template: str, parameters: Mapping[str, object]) -> str`。
- `inline_cypher_parameters` 必须：
  - 找出模板中的 `$param`。
  - 校验模板参数集合与 `parameters` key 完全相等。
  - 用 `escape_cypher_literal` 替换每个 `$param`。
  - 替换后再次确认没有残留 `$param`。

单测必须覆盖：

- 普通字符串：`Gold -> 'Gold'`
- 中文字符串：`金牌 -> '金牌'`
- 单引号：`Tom's -> 'Tom\'s'`
- 反斜杠：`a\b -> 'a\\b'`
- 空字符串：`'' -> ''`
- 负数、0、浮点数
- 布尔：`true/false`
- `None -> null`
- 空列表、单元素列表、多元素列表
- 未支持类型 raise `NotImplementedError`
- 模板参数缺失、参数多余、内联后残留 `$param` 均 raise 明确异常

验收：

- compiler 不再手写任何 ad hoc 字符串拼接的参数替换。
- 所有 inline 行为都通过 `escape_cypher_literal`。

### MIR-003.3 Parameter Source Legality Guard

目标：防止未解析或来源不明的值被内联进最终 Cypher。

建议文件：

```text
services/cypher_generator_agent/app/compiler/compiler.py
services/cypher_generator_agent/app/dsl/ast.py
services/cypher_generator_agent/app/dsl/parser.py
services/cypher_generator_agent/tests/compiler/test_vertex_lookup.py
services/cypher_generator_agent/tests/compiler/test_named_path_pattern.py
```

开发内容：

- compiler 参数构建时不要只保存裸值；需要同时保存参数来源元信息，至少包含：

```json
{
  "name": "quality_of_service",
  "value": "Gold",
  "source": "dsl_filter",
  "resolver_match_type": "value_synonym",
  "resolved": true
}
```

- 对 DSL filter 参数，只有以下情况可内联：
  - `normalized` 不为空；或
  - `resolver_match_type` 属于明确允许集合，例如 `exact`、`value_synonym`、`text_exact`、`id_exact`、`manual_fixture`。
- 对 path pattern 参数，必须由 DSL parser / builder 证明来自已解析的 `ValueLiteral`，不能接受任意裸字符串。
- 若参数来源缺失、`resolver_match_type` 缺失且无法证明是静态 fixture，或值来自 unresolved literal，compiler 必须 raise `CypherCompilerError`。
- trace 中记录参数元信息时，不影响对外 API；对外只看 `generated_cypher`。

验收：

- 已 resolved 的 `金牌 -> Gold` 可以内联。
- unresolved literal 传入 compiler 时失败，不能生成 Cypher。
- path pattern 参数仍可编译，但必须通过参数集合和来源校验。

### MIR-003.4 Self-Validation No Parameter Placeholder Check

目标：让 self-validation 对最终执行文本增加“无参数占位符残留”防线。

建议文件：

```text
services/cypher_generator_agent/app/cypher_validation/models.py
services/cypher_generator_agent/app/cypher_validation/validator.py
services/cypher_generator_agent/tests/cypher_validation/test_validator_entrypoints.py
services/cypher_generator_agent/tests/cypher_validation/test_dialect.py
```

开发内容：

- 新增 failure code：

```text
cypher_parameter_placeholder_not_allowed
```

- `validate_generated_query` 对最终 `cypher_executable` 执行检查：
  - 如果出现 `$quality_of_service`、`$id` 等参数占位符，校验失败。
  - 错误 message 指明“generated executable Cypher must be inline and must not contain parameter placeholders”。
- 该检查只用于 generated executable query；model artifact/path_pattern 模板仍允许参数占位符，因为它们是模型模板，不是最终执行文本。

验收：

- `MATCH ... WHERE n.id = $id RETURN n` 在 generated_query 模式下失败。
- path pattern model artifact 模式不因模板参数失败，仍走已有 model artifact 校验。
- `qa_c2508f2c0bac` 的最终 self-validation 输入是内联 Cypher，因此通过。

### MIR-003.5 Trace and Runtime Center Contract Update

目标：让运行中心能看懂 compiler 的三份 Cypher 产物，并明确哪个是对外执行文本。

建议文件：

```text
console/runtime_console/ui/detail.js
tests/test_runtime_results_service_api.py
docs/experiments/2026-05-28-runtime-center-cga-job-analysis.md
```

开发内容：

- 运行中心 `cypher_compiler` 阶段字段说明新增：
  - `cypher_template`：compiler 内部参数化模板，不直接交给 testing-agent 执行。
  - `parameters`：模板参数字典，用于 trace 和未来切换，不是 v1 执行契约。
  - `cypher_executable`：内联后的可执行 Cypher，是 v1 对外主产物。
  - `cypher`：v1 中与 `cypher_executable` 相同，用于兼容主输出字段。
- 详情页如果同时存在 `cypher_template` 和 `cypher_executable`，应优先展示 `cypher_executable` 为“最终执行 Cypher”，模板和参数放在“编译中间产物”区域。
- 实验文档记录 `qa_c2508f2c0bac` 的失败闭环：失败点从 `tugraph_execution_failed` 迁移为可执行 Cypher 校验/评测阶段。

验收：

- 运行中心详情中用户能明确看到最终执行 Cypher 不含 `$param`。
- LLM prompt/raw output 展示不受影响。
- 字段说明不再把 `parameters` 描述成 testing-agent 必须消费的字段。

### MIR-003.6 End-to-End Remote Smoke

目标：完成本 MIR 的远端闭环验证。

建议文件：

```text
docs/experiments/2026-05-28-runtime-center-cga-job-analysis.md
```

开发内容：

- 部署当前 CGA 与运行中心到远端：
  - CGA：`118.196.92.128:8000`
  - 运行中心：`118.196.92.128:8001`
- 清理本轮 8 条样本旧数据。
- 重跑 `job_76a8e9d22f60`。
- 重点检查 `qa_c2508f2c0bac`：
  - `generated_cypher` 不含 `$quality_of_service`。
  - `generated_cypher` 含 `svc.quality_of_service = 'Gold'`。
  - 不再出现 `Undefined parameter: $quality_of_service`。
  - 若仍失败，失败阶段必须晚于 TuGraph parameter undefined，例如 strict mismatch 或 golden 差异。

验收：

- 本地测试：

```text
PYTHONPATH=. pytest services/cypher_generator_agent/tests -q
PYTHONPATH=. pytest tests/test_runtime_results_service_api.py -q
```

- 远端健康检查：

```text
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8001/health
```

- 实验文档写入本轮部署标识、run id、发送记录和 8 条结果表。

### MIR-003 Implementation Audit 2026-05-29

执行结论：MIR-003 已完成远端闭环。compiler 已将输出拆为 `cypher_template`、`parameters`、`parameter_sources`、`cypher_executable` 和对外主字段 `cypher`；v1 对外 `GenerationOutput.cypher` 使用内联后的可执行 Cypher，不再把 `$param` 占位符交给 testing-agent。

本地实现证据：

| 子 IR | 当前状态 | 证据 |
| --- | --- | --- |
| `MIR-003.0 Regression Baseline for Parameterized Failure` | 完成 | `gq-033` 与 `qa_c2508f2c0bac` 同类 filter + projection 回归已要求 `svc.quality_of_service = 'Gold'`，integration 测试断言主输出无 `$quality_of_service`，trace 保留模板和参数。 |
| `MIR-003.1 Compiler Output Contract Split` | 完成 | `CypherCompilationResult` 暴露 `cypher_template/parameters/parameter_sources/cypher_executable/cypher`；`cypher` 等同 `cypher_executable`。 |
| `MIR-003.2 Cypher Literal Inliner` | 完成 | 新增 `compiler/literals.py`，`test_literal_inliner.py` 覆盖字符串、中文、引号、反斜杠、数字、布尔、`None`、列表、日期时间和参数集合校验。 |
| `MIR-003.3 Parameter Source Legality Guard` | 完成 | compiler 对 unresolved literal 和缺少 resolution evidence 的裸 `raw` literal 均失败；`parameter_sources` 记录 `source/resolver_match_type/resolved`。 |
| `MIR-003.4 Self-Validation No Parameter Placeholder Check` | 完成 | `validate_generated_query` 新增 `cypher_parameter_placeholder_not_allowed`，只约束 generated executable query；model artifact/path pattern 模板仍允许参数占位符。 |
| `MIR-003.5 Trace and Runtime Center Contract Update` | 完成 | 运行中心详情说明区明确区分最终执行 Cypher、模板和参数；字段说明不再把 `parameters` 描述为 testing-agent 执行契约。 |
| `MIR-003.6 End-to-End Remote Smoke` | 完成 | 已部署 `2deb163+mir002-mir003-20260529153514` 到 `118.196.92.128:8000/8001`，清理并重跑 `job_76a8e9d22f60`；`qa_c2508f2c0bac` 的 `generated_cypher` 为内联版，执行成功且不再出现 `Undefined parameter: $quality_of_service`。 |

远端烟测结果：

- 部署标识：`2deb163+mir002-mir003-20260529153514`
- 发送 run：`dispatch_20260529T073559Z`
- 发送记录：`/home/mabingjie/apps/qa-agent/artifacts/experiment_runs/send_current8_to_cga8000_testing8003_after_mir003_inline_20260529T1536.jsonl`
- 健康检查：CGA `8000` 与运行中心 `8001` 均为 `ok`
- 8 条样本状态：`state=passed` 5 条，`issue_ticket_created` 1 条，`generation_failed/clarification_required` 2 条；严格比对 `strict_pass` 1 条，`strict_fail` 5 条。
- `qa_c2508f2c0bac`：`state=passed / verdict=pass / execution_success=true / strict_check=fail`；生成 Cypher 为 `MATCH (svc:Service) WHERE svc.quality_of_service = 'Gold' RETURN svc.id AS service_id, svc.name AS service_name, svc.bandwidth AS service_bandwidth`，已晚于并消除原 `Undefined parameter` 失败点。剩余 `strict_check=fail` 属于返回字段/字段值口径差异，不再是参数执行契约问题。

本地验证命令：

```text
PYTHONPATH=. pytest services/cypher_generator_agent/tests/compiler -q
PYTHONPATH=. pytest services/cypher_generator_agent/tests/integration/test_pipeline_mvp.py tests/test_runtime_results_service_api.py -q
```

## 6. 后续 MIR 模板

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

## 7. 审核结论与后续 MIR 检查

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
