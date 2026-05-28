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
| MIR-001 | Projection Slot Coverage and No Silent ID Downgrade | 已实施核心链路，本地验收通过；回归矩阵扩展待追加 | `qa_9cfa692813d5` | P0 |

后续新增问题按 `MIR-002`、`MIR-003` 继续追加。

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

| 子 IR | 名称 | 优先级 | 估算 | 角色 | 依赖 |
| --- | --- | --- | --- | --- | --- |
| MIR-001.0 | Regression Fixture and Baseline | P0 | S | QA/backend | 无 |
| MIR-001.1 | Question Decomposer Slot Role Annotation | P0 | M | LLM/backend | MIR-001.0 |
| MIR-001.2 | Projection Slot Resolver | P0 | M | backend | MIR-001.1 |
| MIR-001.3 | Projection Coverage Validator | P0 | M | backend | MIR-001.2 |
| MIR-001.4 | DSL Builder No Silent ID Downgrade | P0 | S | backend | MIR-001.3 |
| MIR-001.5 | Grounded Understanding Projection Contract | P1 | M | backend/LLM | MIR-001.2 |
| MIR-001.6 | Trace and Repair Contract for Projection Coverage | P1 | S | backend/infra | MIR-001.3 |
| MIR-001.7 | Self-Validation Shape Guard Extension | P2 | S | backend | MIR-001.4 |
| MIR-001.8 | Regression Matrix Integration | P0 | S | QA/infra | MIR-001.0 到 MIR-001.7 |

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

### MIR-001 Implementation Audit 2026-05-28

执行结论：核心链路已落地，并通过本地 CGA 全量测试；`MIR-001.8` 的专用 regression matrix 扩展仍作为后续追加项保留。

验证命令：

```bash
PYTHONPATH=. pytest services/cypher_generator_agent/tests -q
```

验证结果：

```text
475 passed in 3.43s
```

对照 IR：

| 子 IR | 状态 | 实现/证据 |
| --- | --- | --- |
| MIR-001.0 Regression Fixture and Baseline | 部分完成 | 已新增 `qa_9cfa692813d5` 形态的 integration regression，断言 DSL projection 和最终 Cypher；尚未把 3 个扩展样本并入 golden matrix。 |
| MIR-001.1 Question Decomposer Slot Role Annotation | 完成 | `question_decomposition_v1` 新增 `slot_terms`，prompt 增加“轴三：语义槽位”与示例；测试覆盖 projection/path slot。 |
| MIR-001.2 Projection Slot Resolver | 核心完成 | deterministic grounding 根据 `slot_terms`、候选集合和 semantic model property synonyms 生成 property-level projection；字段词映射从 semantic model 派生，补充了 `Service.quality_of_service` 的同义词。未新增独立 `projection_resolver.py` 文件，当前实现位于 pipeline helper。 |
| MIR-001.3 Projection Coverage Validator | 完成 | coverage schema 新增 slot coverage；validator 合并 plan projection 中的 `slot_terms`，缺失时返回 `projection_coverage_missing` / `repair_binding`。 |
| MIR-001.4 DSL Builder No Silent ID Downgrade | 完成 | builder 禁止裸 `semantic_type=vertex` projection；默认 ID 返回改为显式 property projection；DSL/AST/compiler 支持一等 `vertex_full`。 |
| MIR-001.5 Grounded Understanding Projection Contract | 部分完成 | boundary validator 支持 property projection 的 `owner/name` 形态；测试中的 grounded payload 已迁移到 property-level projection。Grounded schema 仍允许自由 dict，后续可继续收紧。 |
| MIR-001.6 Trace and Repair Contract | 部分完成 | semantic validator 的 projection coverage failure 可进入 repair；trace 中可见缺失项。尚未为 Runtime Center 单独补 projection coverage 展示用例。 |
| MIR-001.7 Self-Validation Shape Guard Extension | 完成已有能力确认 | compiler 对 DSL projection 产出 `expected_return_aliases`，self-validation shape 继续校验 RETURN alias；新增 `vertex_full` compiler case。 |
| MIR-001.8 Regression Matrix Integration | 待追加 | 现有全量测试通过，但未新增 golden matrix projection slice；后续应将 `qa_9cfa692813d5` 与同类多字段样本纳入统一 golden fixture。 |

实现边界：

- 本轮没有引入 raw Cypher fallback，也没有连接数据库。
- 没有在 resolver 中维护中文字段硬编码词表；需要的新同义词补在 semantic model YAML 中。
- 默认“无显式字段的 list 查询”仍保持既有 ID 口径，但实现上已从“裸 vertex 静默降级”改成“显式 id property projection”。是否改为 `vertex_full` 需要先审核 qa-agent/golden 口径。

## 4. 后续 MIR 模板

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

## 5. 审核结论与后续 MIR 检查

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
