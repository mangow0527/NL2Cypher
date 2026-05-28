# CGA OSI 重写后运行中心实验问题清单

## 2026-05-28 8 样本 Job 运行中心结果

- 本轮样本来源：qa-agent 280 条样本池 `/home/mabingjie/apps/qa-agent/artifacts/experiment_pools/pool_20260520T111838Z.jsonl`
- 抽取 job：`job_76a8e9d22f60`，共 8 条 QA 样本
- 发送记录：`/home/mabingjie/apps/qa-agent/artifacts/experiment_runs/send_job_to_cga8000_testing8003_after_decomposer_schema_rewrite_20260528T085013Z.jsonl`
- 本轮运行服务：CGA `118.196.92.128:8000`，运行中心 `118.196.92.128:8001`，testing-agent `8003`
- 本轮生成数据对应 CGA 版本：`60b446e`；本文档提交后远端 `DEPLOYED_REVISION=2660ce3`，该提交只包含实验文档变更
- 语义模型：`network_schema_v10`
- 运行中心落盘数据：`goldens=8`，`submissions=5`，`submission_attempts=5`，`generation_failures=3`，`issue_tickets=3`，`repair_analyses=3`
- 最新结果：`passed=1`，`failed=3`，`generation_failed/clarification_required=3`，`pending=1`

本轮 8 条样本中，`qa_76e37da317b4` 已通过：`统计系统中一共有多少个服务。` 生成 `MATCH (svc:Service) RETURN count(svc.id) AS service_count`，testing-agent 执行结果与 golden 一致。

其余 7 条样本暴露出几个集中问题。下面的归类不是互斥集合，同一 QA 可能同时落入多个类别。

- 新问题：投影字段丢失（4）：`qa_9cfa692813d5`、`qa_c80a82efe561`、`qa_c2508f2c0bac`、`qa_a5f4b0253af3`。题干明确要求多个返回字段，但 DSL/Cypher 只保留 ID 或错误终点对象。
- 新问题：参数化 Cypher 与 testing-agent 契约不一致（1）：`qa_c2508f2c0bac`。CGA compiler 输出了 `parameters={"quality_of_service":"Gold"}`，testing-agent 执行时只拿到 Cypher 文本，报 `Undefined parameter: $quality_of_service`。
- 新问题：控制词/Top-N 被误送入 literal resolver（2）：`qa_526d49332ed1`、`qa_c3e83dd7ad32`。`所有` 被当成 `Service.elem_type` 的取值，`前3` 被当成 `NetworkElement.location` 的取值，导致合法问题被错误澄清。
- 新问题：字段短语到 owner/property 的绑定错误（1）：`qa_6494b2085699`。`IP地址为10.0.0.4的网元` 应绑定到 `NetworkElement.ip_address`，实际 resolver 期望 `Tunnel.id`。
- 新问题：多跳路径降级为局部单跳（1）：`qa_a5f4b0253af3`。期望 `Service -> Tunnel -> dst NetworkElement -> Port`，实际生成 `Tunnel -[:TUNNEL_SRC]-> NetworkElement`。
- 新问题：运行中心状态与落盘 repair 数据关联不完整（4）：`qa_c2508f2c0bac`、`qa_9cfa692813d5`、`qa_c80a82efe561`、`qa_a5f4b0253af3`。存在 testing 执行错误但 verdict 仍 pending、repair analysis 文件存在但详情页显示未读取到诊断记录的情况。

## 2026-05-28 待修问题明细

| QA ID | 具体问题 | 修复方案 |
| --- | --- | --- |
| `qa_9cfa692813d5`（待修） | `查询所有服务的ID、名称、元素类型、服务质量等级、带宽和时延。` 的 golden 需要返回 `id/name/elem_type/quality_of_service/bandwidth/latency` 六个字段；CGA trace 中 decomposer 已抽到这些字段词，但 grounded understanding 的 `selected_properties=[]`，DSL projection 最终只有 `service_id`，生成 `MATCH (svc:Service) RETURN svc.id AS service_id`。coverage 却显示 substantive terms 全覆盖，说明当前覆盖校验没有约束“字段词必须进入最终 projection”。 | 在 grounded understanding 或 DSL builder 前增加投影收集器：题干中的字段型 `target_concepts` 必须解析成同 owner 的 property projection；若字段词未进入 DSL `projection.items`，semantic validator 应报 projection coverage 缺失，不能继续编译。coverage 统计要从“词被候选命中”升级为“词被最终 DSL 使用”。 |
| `qa_c80a82efe561`（待修） | `查询所有服务使用的隧道，返回隧道的 ID、名称和带宽。` 正确选中了 `Service -[:SERVICE_USES_TUNNEL]-> Tunnel`，但只返回 `tun.id AS tunnel_id`，漏掉 `tun.name` 和 `tun.bandwidth`。testing-agent 执行成功但 strict check 失败，原因是返回字段和值不一致。 | 对 single-hop traversal 增加终点对象字段投影规则：当题干中出现“返回隧道的 ID、名称和带宽”时，应把字段绑定到路径终点 `Tunnel`，生成 `Tunnel.id/name/bandwidth` 三个 projection。DSL builder 不能在 projection 为空或只含 vertex 时默认只补 ID。 |
| `qa_c2508f2c0bac`（待修） | `查询服务质量等级为金牌的所有服务的ID、名称和带宽。` 中 literal resolver 正确把 `金牌` 解析为 `Gold`，compiler 输出 `WHERE svc.quality_of_service = $quality_of_service` 和参数 `{"quality_of_service":"Gold"}`；testing-agent 执行时报 `Undefined parameter: $quality_of_service`。同时 projection 只返回 `service_id`，漏掉 `name/bandwidth`。运行中心 summary 仍显示 `final_verdict=pending`，没有形成 issue ticket。 | 分两层修：1）CGA 到 testing-agent 的 submission contract 必须携带 `parameters`，testing-agent 执行 TuGraph 时传入参数；如果 testing 暂不支持参数，则 CGA 的 testing submission 需要提供已内联的只读执行版本。2）投影修复同上，`ID/名称/带宽` 必须全部进入 DSL projection。3）testing execution error 应进入明确 failed/ticket 状态，不能长期 pending。 |
| `qa_526d49332ed1`（待修） | `查询所有服务经过隧道穿过的网元的名称和厂商。` 中 decomposer 把 `所有` 放进 `literal_candidates=[{"text":"所有","attached_to":"服务"}]`，literal resolver 尝试解析为 `Service.elem_type`，最终返回澄清：`我没有确定“所有”对应的值，请选择或补充。` 这是误澄清，因为“所有”不是数据取值。 | 在 decomposer 后增加确定性清洗：`所有/全部/任意/每个` 等全称量词不得进入 literal resolver，应作为 stop/control term 或查询范围修饰。即使 LLM 误填 literal_candidates，工程代码也要剔除这类候选。该题随后应进入 path query 生成，至少不能因 `所有` 澄清。 |
| `qa_c3e83dd7ad32`（待修） | `统计服务使用的隧道源节点所在位置的网元数量，按数量降序排列，返回前3名。` 中 decomposer 把 `前3` 作为 literal candidate，resolver 试图解析为 `NetworkElement.location` 的取值，导致澄清：`我没有确定“前3”对应的值，请选择或补充。` 实际上 `前3` 是 Top-N/limit 结构。 | 在 decomposer schema 或后处理层显式表达排序与 limit：`前3/前 3 名/top 3/最多 3 个` 应转换为 `limit=3`，`按数量降序排列` 应转换为 `ORDER BY count DESC`。literal resolver 只处理字段过滤值，不处理排序/limit 控制词。该类问题需要进入 aggregate/group/order/limit DSL，而不是 clarification。 |
| `qa_6494b2085699`（待修） | `查询经过IP地址为10.0.0.4的网元的服务的ID、类型、隧道总数及匹配网元数量。` 中 decomposer 输出 `literal_candidates=[{"text":"10.0.0.4","kind_hint":"id","attached_to":"IP地址"}]`，但 resolver 期望字段变成 `Tunnel.id`，最后澄清 `10.0.0.4` 未解析。golden 明确应为 `NetworkElement.ip_address = '10.0.0.4'`。 | owner/property 绑定要优先消费字段短语：`IP地址` 应强匹配 `NetworkElement.ip_address`，且“的网元”提供 owner 约束。literal resolver 输入不应只根据当前主路径候选猜 owner；需要把 `attached_to=IP地址` 先解析成 property，再由 property owner 反推 vertex。若 value index miss，也应提示“未在 NetworkElement.ip_address 中找到 10.0.0.4”，而不是泛化为“对应的值”。 |
| `qa_a5f4b0253af3`（待修） | `查询所有服务使用的隧道目的网元上的端口ID、名称和状态。` 的 golden 路径是 `Service -[:SERVICE_USES_TUNNEL]-> Tunnel -[:TUNNEL_DST]-> NetworkElement -[:HAS_PORT]-> Port`；实际 generated Cypher 为 `MATCH (tun:Tunnel)-[:TUNNEL_SRC]->(ne:NetworkElement) RETURN ne.id AS network_element_id`。服务、使用关系、目的网元、端口 hop、端口字段全部丢失。 | path binding 需要做“题干概念覆盖到最终路径”的强校验：最终 DSL path 必须包含 `Service/Tunnel/NetworkElement/Port` 和 `SERVICE_USES_TUNNEL/TUNNEL_DST/HAS_PORT`，否则应回到 repair/unsupported，而不是生成局部单跳。方向词“目的网元”必须绑定 `TUNNEL_DST`，不能选 `TUNNEL_SRC`。投影应返回 `Port.id/name/status`。 |
| `qa_9cfa692813d5`, `qa_c80a82efe561`, `qa_a5f4b0253af3`（待修） | 三条 failed 样本均有 issue ticket，并且远端 `/home/mabingjie/nl2cypher/data/repair_service/analyses` 下存在对应 `analysis-ticket-...json`，状态为 `apply_failed`；但运行中心详情页仍显示 `未读取到 repair-agent 诊断记录`。 | 运行中心读取 repair 数据时需要按 `ticket_id` 或 `question_id + attempt` 关联 `analysis-ticket-*.json`，并展示 `apply_failed`、repair prompt/raw output、knowledge apply 状态。否则操作员看到的是“未记录”，无法判断 repair-agent 是否已经处理过。 |
| `qa_c2508f2c0bac`（待确认） | testing-agent 已经返回执行错误 `Undefined parameter: $quality_of_service`，但运行中心 summary 中 `final_verdict=pending`，stage 仍停在 evaluation/knowledge_repair pending，没有 issue ticket。 | testing execution error 应有明确状态机出口：语法/执行错误类 failure 应进入 failed 并生成 ticket，或至少在运行中心标成 evaluation failed。pending 只适合异步任务尚未完成，不应表示已经有确定错误的样本。 |

## 2026-05-28 本轮可沉淀的回归集合

建议把本轮 8 条样本作为 OSI 重写后第一批小型回归集合，覆盖以下能力点：

- `qa_76e37da317b4`：基础 count 聚合，应保持通过。
- `qa_9cfa692813d5`：单点 vertex lookup 多字段投影。
- `qa_c80a82efe561`：单跳 traversal 的终点多字段投影。
- `qa_c2508f2c0bac`：枚举同义词 literal 解析、参数传递、多字段投影。
- `qa_526d49332ed1`：`所有` 不应触发 literal 澄清。
- `qa_c3e83dd7ad32`：Top-N/排序/limit 结构不能进入 literal resolver。
- `qa_6494b2085699`：字段短语 `IP地址` 到 `NetworkElement.ip_address` 的绑定。
- `qa_a5f4b0253af3`：服务-隧道-目的网元-端口多跳路径和终点字段投影。
