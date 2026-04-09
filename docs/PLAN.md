# 新版 Text2Cypher 闭环系统架构规划

## Summary

系统按 `id` 这一个主键串联，形成 5 个角色：

- `QA生成服务`：外部服务，负责发送 `Q` 和 `A`
- `查询语句生成服务`：接收 `id + question`，加载知识包，生成 Cypher，执行 TuGraph 查询，并把结果发给测试服务
- `测试服务`：先存 `A`，再等待查询语句生成服务的结果，二者齐全后做评测，产出问题单
- `问题修复服务`：接收问题单，判断问题更可能来自知识不足、问题表达不清，还是查询生成本身，并产出修复计划
- `知识运营服务`：外部服务，接收知识相关修复计划，后续提供知识包

推荐当前阶段的轻量存储方案：

- 每个服务各自使用本地 `SQLite` 落盘
- 不做共享数据库
- 外部 QA 服务通过可被其他电脑访问的 `REST` 端口直接推送数据
- 服务监听 `0.0.0.0`

默认假设：

- `问题修复服务` 作为我们系统内的第三个独立 Python 服务来设计
- `知识运营服务` 和 `QA生成服务` 当前只定义接口契约，不在本轮实现
- `QA生成服务` 会主动向两个服务分别 `POST`
- `查询语句生成服务` 不等待任何外部响应，完成一轮生成和查询后即结束
- `测试服务` 在缺少 `A` 时进入等待状态，直到收到对应 `id` 的标准答案

## Key Design

### 1. 服务责任边界

#### QA生成服务（外部）
职责：

- 发送 `id + question` 给查询语句生成服务
- 发送 `id + cypher + answer + difficulty` 给测试服务
- 后续接收“问题质量修复计划”

它不负责：

- 执行 TuGraph
- 评估查询质量
- 直接修复 Cypher

#### 查询语句生成服务（内部）
职责：

- 接收 `id + question`
- 存储问题记录
- 加载知识包
- 记录本次实际加载的知识标签列表
- 生成 Cypher
- 执行 TuGraph 查询
- 存储本次生成和执行事实
- 将 `id + question + generated_cypher + execution_result + knowledge_tags` 发给测试服务

它不负责：

- 判断最终质量是否合格
- 判断问题来源归属
- 生成修复计划

#### 测试服务（内部）
职责：

- 接收并存储 QA 标准答案 `A`
- 接收并存储查询语句生成服务提交的执行结果
- 当 `A` 和“实际产物”都齐全时触发评测
- 基于问题、标准 Cypher、标准答案、实际 Cypher、实际结果做质量评估
- 产出结构化问题单
- 把问题单发给问题修复服务

它不负责：

- 执行 TuGraph
- 直接修改任何服务的行为

#### 问题修复服务（内部）
职责：

- 接收问题单
- 做根因分析和责任归属判断
- 必要时执行“对照实验”辅助判断
- 生成面向不同服务的修复计划
- 将修复计划发给：
  - 查询语句生成服务
  - QA生成服务
  - 知识运营服务

它不直接：

- 改写查询语句生成服务的实时答案
- 改写 QA 标准答案
- 改写知识包内容

#### 知识运营服务（外部）
职责：

- 接收知识不足类修复计划
- 后续输出新的知识包或知识版本

### 2. 推荐的问题分析工作流

你的初步设想总体是合理的，但不建议把“强模型重新生成一版 Cypher 并查询”当作唯一判断依据。  
原因：

- 大模型结果有随机性
- 强模型也可能利用隐式常识“蒙对”
- 单次对照实验不够稳定，容易误判责任来源

推荐改成两层工作流：

#### 第一层：规则化证据判断
问题修复服务先基于问题单做确定性检查：

- 实际 Cypher 是否语法错误
- 是否使用了不存在的标签或关系
- 实际结果是否为空或明显偏离标准答案
- 实际 Cypher 和标准 Cypher 的结构差异
- 问题是否缺少约束、实体不清、范围不明
- 本次知识标签列表是否已经覆盖问题涉及的关键概念

这一步先做初步归因：

- `generator_logic_issue`
- `knowledge_gap_issue`
- `qa_question_issue`
- `mixed_issue`
- `unknown`

#### 第二层：对照实验辅助判断
只有在第一层不能明确判断时，再启用强模型辅助实验：

- 实验 A：相同问题 + 相同知识标签，强模型重新生成 Cypher
- 实验 B：相同问题 + 扩展知识包，强模型重新生成 Cypher
- 实验 C：问题轻度澄清后 + 相同知识，强模型重新生成 Cypher

判断逻辑：

- A 成功而原结果失败：更像查询生成服务能力或 prompt 问题
- B 成功而 A 失败：更像知识包不足
- C 成功而 A 失败：更像 QA 问题表达不够清晰
- 全部失败：更可能是 QA 标准、图谱数据、或评测定义有问题

结论：

- 强模型对照实验适合做“二级证据”，不适合做唯一裁决者

### 3. 知识包设计

当前先不用真实知识运营服务，但要把结构先定好。  
推荐知识包结构：

- `package_id`
- `version`
- `graph_name`
- `summary`
- `schema_facts`
  - 合法节点标签
  - 合法边标签
  - 关键属性
- `business_terms`
  - 业务术语到图谱实体的映射
- `query_patterns`
  - 常见问题到 Cypher 模板的映射
- `constraints`
  - 禁止使用的标签、边、属性
  - 常见错误提示
- `knowledge_tags`
  - 用于本次加载记录的标签列表

查询语句生成服务在工作时要保存：

- `id`
- `knowledge_package_version`
- `loaded_knowledge_tags`

后续问题修复服务就能基于这些标签判断“知识是否已覆盖关键概念”。

## Public Interfaces / Data Shapes

### 1. QA生成服务 -> 查询语句生成服务

推荐接口：

- `POST /api/v1/qa/questions`

请求体：

```json
{
  "id": "string",
  "question": "string"
}
```

行为：

- 以 `id` 为主键落盘
- 同 `id` 同内容重复发送按幂等处理
- 同 `id` 不同内容返回冲突
- 接收成功后立即触发生成工作流

### 2. QA生成服务 -> 测试服务

推荐接口：

- `POST /api/v1/qa/goldens`

请求体：

```json
{
  "id": "string",
  "cypher": "string",
  "answer": {},
  "difficulty": "L1|L2|L3|L4|L5|L6|L7|L8"
}
```

行为：

- 以 `id` 为主键落盘
- 不需要 `question`
- 仅存标准答案侧数据
- 若该 `id` 的实际结果已到达，则立即触发评测

### 3. 查询语句生成服务 -> 测试服务

推荐接口：

- `POST /api/v1/evaluations/submissions`

请求体：

```json
{
  "id": "string",
  "question": "string",
  "generated_cypher": "string",
  "execution": {
    "success": true,
    "rows": [],
    "row_count": 0,
    "error_message": null,
    "elapsed_ms": 0
  },
  "knowledge_context": {
    "package_id": "default-network-schema",
    "version": "v1",
    "loaded_knowledge_tags": ["network_element", "port", "has_port"]
  }
}
```

行为：

- 落盘保存
- 若该 `id` 的标准答案 `A` 已存在，则立即触发评测
- 若 `A` 未到达，则进入 `waiting_for_golden` 状态

### 4. 测试服务 -> 问题修复服务

内部对象建议定义为 `IssueTicket`：

```json
{
  "ticket_id": "string",
  "id": "string",
  "difficulty": "L1|L2|L3|L4|L5|L6|L7|L8",
  "question": "string",
  "expected": {
    "cypher": "string",
    "answer": {}
  },
  "actual": {
    "generated_cypher": "string",
    "execution": {
      "success": true,
      "rows": [],
      "row_count": 0,
      "error_message": null,
      "elapsed_ms": 0
    }
  },
  "knowledge_context": {
    "package_id": "string",
    "version": "string",
    "loaded_knowledge_tags": []
  },
  "evaluation": {
    "verdict": "pass|fail|partial_fail",
    "dimensions": {
      "syntax_validity": "pass|fail",
      "schema_alignment": "pass|fail",
      "result_correctness": "pass|fail",
      "question_alignment": "pass|fail"
    },
    "symptom": "string",
    "evidence": []
  }
}
```

### 5. 问题修复服务输出对象

内部对象建议定义为 `RepairPlan`：

```json
{
  "plan_id": "string",
  "ticket_id": "string",
  "id": "string",
  "root_cause": "generator_logic_issue|knowledge_gap_issue|qa_question_issue|mixed_issue|unknown",
  "confidence": 0.0,
  "actions": [
    {
      "target_service": "query_generator_service|knowledge_ops_service|qa_generation_service",
      "action_type": "prompt_adjustment|knowledge_enrichment|question_rewrite|manual_review",
      "instruction": "string",
      "evidence": []
    }
  ]
}
```

## Evaluation Rules and Storage

### 1. 测试服务评测维度

测试服务的评测建议按 4 维执行：

- `syntax_validity`
  - 生成 Cypher 是否可执行
- `schema_alignment`
  - 使用的实体、关系、属性是否符合图谱 schema
- `result_correctness`
  - 实际结果是否与标准答案 `A.answer` 一致或足够接近
- `question_alignment`
  - 实际 Cypher 是否在语义上回答了 `Q`

难度 `difficulty` 的作用：

- 不直接决定 pass/fail
- 用于设置评测解释粒度、容错策略、以及后续抽样和报表分层
- 当前阶段按你已有的 `L1-L8` 标准原样存储

### 2. 当前阶段的存储方案

推荐：

- 查询语句生成服务：本地 `SQLite`
- 测试服务：本地 `SQLite`
- 问题修复服务：本地 `SQLite`

原因：

- 轻量
- 可落盘
- 业界常见
- 比纯内存安全
- 比直接文件 JSON 更适合主键查询、状态流转、幂等处理

推荐最小表设计：

#### 查询语句生成服务
- `qa_questions`
  - `id`, `question`, `status`, `received_at`
- `generation_runs`
  - `id`, `generated_cypher`, `execution_json`, `knowledge_context_json`, `finished_at`

#### 测试服务
- `qa_goldens`
  - `id`, `golden_cypher`, `golden_answer_json`, `difficulty`, `received_at`
- `evaluation_submissions`
  - `id`, `question`, `generated_cypher`, `execution_json`, `knowledge_context_json`, `status`
- `issue_tickets`
  - `ticket_id`, `id`, `ticket_json`, `created_at`

#### 问题修复服务
- `repair_plans`
  - `plan_id`, `ticket_id`, `id`, `root_cause`, `plan_json`, `created_at`

### 3. 状态机建议

#### 查询语句生成服务
- `received_question`
- `generating_cypher`
- `querying_tugraph`
- `submitted_for_evaluation`
- `completed`

#### 测试服务
- `received_golden_only`
- `received_submission_only`
- `waiting_for_golden`
- `ready_to_evaluate`
- `issue_ticket_created`
- `passed`

#### 问题修复服务
- `received_ticket`
- `analyzing`
- `counterfactual_checking`
- `repair_plan_created`
- `dispatched`

## Test Plan

### 核心场景

1. QA 服务先发 `Q`，生成服务完成后测试服务尚未收到 `A`
   - 测试服务进入 `waiting_for_golden`
   - `A` 到达后自动继续评测

2. QA 服务先发 `A`，之后才收到生成服务提交
   - 测试服务直接触发评测

3. 同一个 `id` 重复提交相同数据
   - 按幂等成功处理

4. 同一个 `id` 提交冲突数据
   - 返回冲突，不覆盖已有事实

5. 实际 Cypher 语法错误
   - 测试服务生成问题单
   - 问题修复服务优先归因到 `generator_logic_issue`

6. 实际 Cypher 可执行但结果与 `A.answer` 明显不符
   - 测试服务生成问题单
   - 问题修复服务结合知识标签和对照实验归因

7. QA 问题本身歧义较大
   - 对照实验中“问题澄清版”显著改善
   - 修复计划发给 QA 生成服务

8. 知识标签覆盖不足
   - 扩展知识包实验显著改善
   - 修复计划发给知识运营服务

## Assumptions

- `id` 是全系统唯一主键，并且不可变
- `difficulty` 采用你提供的 `L1-L8` 标准，不在本轮重新定义
- `QA生成服务` 和 `知识运营服务` 当前只做接口契约，不做实现
- `问题修复服务` 作为内部第三服务设计
- 当前阶段不引入共享数据库，使用每个服务本地 `SQLite`
- 外部访问采用固定 REST 端口并监听 `0.0.0.0`
- 强模型对照实验只作为辅助证据，不作为唯一归因依据
