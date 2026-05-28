# 2026-05-28 CGA Runtime Center Job Analysis

## Context

- Deployed revision: `60b446e`
- Remote services:
  - CGA: `118.196.92.128:8000`
  - Runtime Center: `118.196.92.128:8001`
- Semantic model reported by traces: `network_schema_v10`
- Runtime data source: current Runtime Center data after the 8-sample job dispatched from the qa-agent pool.
- Source job: `job_76a8e9d22f60`
- Dispatch run: `dispatch_20260528T085013Z`
- Scope of this note: observation and diagnosis only. No code changes are included in this document.

## Data Snapshot

| Artifact | Count |
|---|---:|
| Golden cases | 8 |
| Submissions | 5 |
| Submission attempts | 5 |
| Generation failures | 3 |
| Issue tickets | 3 |
| Repair analyses on disk | 3 |

## Job-Level Result

| QA ID | Difficulty | Question | Generation Status | Runtime Stage | Verdict | Main Observation |
|---|---|---|---|---|---|---|
| `qa_76e37da317b4` | L4 | 统计系统中一共有多少个服务。 | `generated` | `done` | `pass` | Count query passed. |
| `qa_c2508f2c0bac` | L2 | 查询服务质量等级为金牌的所有服务的ID、名称和带宽。 | `generated` | `evaluation` | `pending` | CGA resolved `金牌 -> Gold`, but generated Cypher used a parameter not passed to testing-agent, and projection kept only service ID. |
| `qa_a5f4b0253af3` | L7 | 查询所有服务使用的隧道目的网元上的端口ID、名称和状态。 | `generated` | `knowledge_repair` | `fail` | Complex path was reduced to `Tunnel -> NetworkElement` through `TUNNEL_SRC`; service, destination side, port hop, and requested port fields were lost. |
| `qa_c80a82efe561` | L3 | 查询所有服务使用的隧道，返回隧道的 ID、名称和带宽。 | `generated` | `knowledge_repair` | `fail` | Correct service-to-tunnel edge was selected, but projection kept only tunnel ID and dropped name/bandwidth. |
| `qa_526d49332ed1` | L5 | 查询所有服务经过隧道穿过的网元的名称和厂商。 | `clarification_required` | `query_generation` | `pending` | `所有` was incorrectly treated as a literal for `Service.elem_type`, causing a false clarification. |
| `qa_6494b2085699` | L8 | 查询经过IP地址为10.0.0.4的网元的服务的ID、类型、隧道总数及匹配网元数量。 | `clarification_required` | `query_generation` | `pending` | `10.0.0.4` should bind to `NetworkElement.ip_address`, but resolver expected `Tunnel.id`, then asked a generic clarification. |
| `qa_c3e83dd7ad32` | L6 | 统计服务使用的隧道源节点所在位置的网元数量，按数量降序排列，返回前3名。 | `clarification_required` | `query_generation` | `pending` | `前3` was treated as a literal for `NetworkElement.location`; it should be a Top-N limit/order expression. |
| `qa_9cfa692813d5` | L1 | 查询所有服务的ID、名称、元素类型、服务质量等级、带宽和时延。 | `generated` | `knowledge_repair` | `fail` | Simple vertex lookup generated only `svc.id AS service_id`, dropping five requested properties. |

## Main Problems Found

### 1. Projection Intent Is Not Preserved

Several questions explicitly request multiple fields, but the generated DSL and Cypher only return an ID field.

Evidence:

- `qa_9cfa692813d5`
  - Asked for: ID, name, elem type, quality of service, bandwidth, latency.
  - Generated: `RETURN svc.id AS service_id`.
- `qa_c80a82efe561`
  - Asked for tunnel ID, name, bandwidth.
  - Generated: `RETURN tun.id AS tunnel_id`.
- `qa_c2508f2c0bac`
  - Asked for service ID, name, bandwidth.
  - Generated: `RETURN svc.id AS service_id`.

The trace shows coverage as complete in these cases even when projection fields are missing. This means the current coverage check is too coarse: it can mark terms such as `名称`, `带宽`, `时延` as covered without proving that they are present in the final DSL projection or Cypher `RETURN`.

Impact:

- The generated query can look syntactically valid and pass self-validation, but still answer a narrower question than the user asked.
- This is a high-risk "looks right but is wrong" failure mode.

### 2. Parameter Propagation Is Broken Between CGA and Testing

`qa_c2508f2c0bac` is the clearest example.

CGA compiler output:

```cypher
MATCH (svc:Service)
WHERE svc.quality_of_service = $quality_of_service
RETURN svc.id AS service_id
```

Compiler parameters:

```json
{"quality_of_service": "Gold"}
```

Testing-agent execution error:

```text
CypherException: Undefined parameter: $quality_of_service
```

The literal resolver did its job: `金牌` resolved to `Gold` with `match_type=value_synonym`. The failure happened after compilation because the testing side appears to execute only the Cypher text and not the parameter map.

Impact:

- Parameterized generated Cypher cannot be reliably evaluated.
- Runtime Center may show a generated query, while the downstream execution path fails for integration reasons.

### 3. Control Words Are Still Entering Literal Resolution

The new decomposer prompt reduces ambiguity, but runtime data shows the pipeline still needs deterministic guards after the LLM output.

Evidence:

- `qa_526d49332ed1`
  - `所有` was emitted as a literal candidate attached to `服务`.
  - Literal resolver tried to resolve it against `Service.elem_type`.
  - Final clarification: `我没有确定“所有”对应的值，请选择或补充。`
- `qa_c3e83dd7ad32`
  - `前3` was emitted as a literal candidate.
  - Literal resolver tried to resolve it against `NetworkElement.location`.
  - Final clarification: `我没有确定“前3”对应的值，请选择或补充。`

Expected behavior:

- `所有` should behave as a universal quantifier or stop/control word, not as a field value.
- `前3` should become a Top-N limit/order expression, not a literal bound to a data property.

Impact:

- Valid questions are blocked with false clarifications.
- Clarification UX becomes confusing because the user is asked to choose values for words that are not values.

### 4. Complex Path Binding Degrades Into Simpler Wrong Paths

`qa_a5f4b0253af3` asks:

```text
查询所有服务使用的隧道目的网元上的端口ID、名称和状态。
```

Expected path:

```cypher
(Service)-[:SERVICE_USES_TUNNEL]->(Tunnel)-[:TUNNEL_DST]->(NetworkElement)-[:HAS_PORT]->(Port)
```

Generated path:

```cypher
(Tunnel)-[:TUNNEL_SRC]->(NetworkElement)
```

The binding skipped:

- `Service`
- `SERVICE_USES_TUNNEL`
- destination side `TUNNEL_DST`
- `HAS_PORT`
- `Port`
- requested port fields `id/name/status`

Impact:

- Multi-hop requests can be collapsed into a locally plausible but semantically wrong single-hop traversal.
- Current semantic validation did not catch that the requested target concept was `Port`, while the final projection returned a `NetworkElement`.

### 5. IP Address Binding Chooses the Wrong Owner and Property

`qa_6494b2085699` contains:

```text
IP地址为10.0.0.4的网元
```

Expected binding:

```text
NetworkElement.ip_address = "10.0.0.4"
```

Observed resolver expectation:

```text
Tunnel.id
```

The final clarification was generic:

```text
我没有确定“10.0.0.4”对应的值，请选择或补充。
```

Impact:

- The system asks the user for clarification even though the user gave a specific literal and a specific field phrase.
- The clarification hides the useful diagnostic: the system failed to bind `IP地址` to `NetworkElement.ip_address`.

### 6. Clarification Payload Is More Structured Than Before, But Still Not Helpful Enough

The Runtime Center now displays structured clarification fields such as:

- `source_stage`
- `reason_code`
- `validation_errors`
- `unresolved_items`
- `no_option_reason`

However, the actual user-facing question is still generic. In the current run, all three clarifications say essentially "I did not determine the value for X", without explaining:

- which semantic field was expected,
- why no candidates were available,
- whether the issue is unsupported query shape, missing value index, or wrong literal classification,
- whether the user can choose from alternatives.

Impact:

- The trace is useful to developers, but not yet useful enough for an end user.
- False clarifications become harder to diagnose from the UI alone.

### 7. Runtime Center State Has Inconsistencies

Two inconsistencies are visible in the current data:

1. `qa_c2508f2c0bac` has testing execution failure (`Undefined parameter`) but Runtime Center summary still shows `final_verdict=pending` and no issue ticket.
2. There are three repair analysis files on disk, all with `status=apply_failed`, but Runtime Center detail still says `未读取到 repair-agent 诊断记录` for failed tasks that have issue tickets.

Impact:

- Operators cannot fully trust the stage badge/status alone.
- The repair loop may have run, but the Runtime Center does not link the analysis back into the displayed task detail.

## Positive Signals

- Service deployment is healthy on both `8000` and `8001`.
- The question decomposer now returns Chinese prompt-driven structured output with visible LLM prompt and raw response in trace.
- Literal synonym resolution worked for `金牌 -> Gold`.
- Self-validation caught no syntax/read-only/schema issues in generated queries.
- Simple aggregate count query passed end to end.

## Recommended Follow-Up Work

1. Add deterministic post-processing after decomposer output:
   - Remove universal quantifiers such as `所有` from `literal_candidates`.
   - Convert Top-N phrases such as `前3` into order/limit intent, not literal resolution.
2. Strengthen projection coverage:
   - Every requested field term must map to a DSL projection item or a known aggregate output.
   - Coverage should fail if `名称`, `带宽`, `时延`, `状态` are absent from final projection.
3. Fix parameter contract:
   - Either pass `parameters` from CGA to testing-agent, or compile safe literal values into the execution form used by testing.
4. Improve path binding validation:
   - Validate that final traversal covers all requested target concepts and relation phrases.
   - Reject or clarify when a multi-hop path collapses to a single-hop path that drops requested concepts.
5. Improve literal owner/property binding:
   - `IP地址` should strongly prefer `NetworkElement.ip_address`.
   - If value lookup misses, clarification should say the expected field and lack of indexed value.
6. Fix Runtime Center repair linkage:
   - Existing repair analyses on disk should be linked to the corresponding issue ticket in task detail.
7. Add regression cases for this exact job:
   - `所有` must not trigger literal clarification.
   - `前3` must become `LIMIT 3`.
   - service/tunnel projection fields must be preserved.
   - IP address should bind to `NetworkElement.ip_address`.
   - parameterized Cypher must include its parameter map in the testing submission.
