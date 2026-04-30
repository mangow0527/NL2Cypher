# Repair Agent Contract Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring repair-agent implementation in line with `services/repair_agent/docs/repair-agent-design.md` by making diagnosis decisions explicit, removing stale contract paths, and separating prompt assembly from transport.

**Architecture:** Keep `RepairService` as orchestration, `RepairAnalyzer` as diagnosis normalization, `OpenAIChatCompletionRepairAnalyzer` as transport, and introduce a focused prompt builder module for LLM prompt assembly. Repair records should model real lifecycle states instead of pretending all persisted records are already applied.

**Tech Stack:** Python, FastAPI, Pydantic, pytest, httpx.

---

### Task 1: Repair Lifecycle State Semantics

**Files:**
- Modify: `services/repair_agent/app/models.py`
- Modify: `services/repair_agent/app/service.py`
- Modify: `tests/test_repair_agent_service_flow.py`
- Modify: `services/repair_agent/docs/repair-agent-design.md`

- [ ] **Step 1: Write failing tests**

Add tests asserting:
- apply failure persists `status="apply_failed"` and `applied=false`.
- success persists `status="applied"` only after knowledge-agent apply succeeds.

Run:

```bash
python -m pytest -q tests/test_repair_agent_service_flow.py::test_repair_service_persists_apply_failed_status_after_apply_failure tests/test_repair_agent_service_flow.py::test_repair_service_marks_record_applied_only_after_apply_success
```

Expected before implementation: failure because `RepairStatus` only accepts `applied` and service leaves failed records with misleading status.

- [ ] **Step 2: Implement lifecycle states**

Change `RepairStatus` to include:

```python
RepairStatus = Literal["analysis_pending", "apply_failed", "applied", "not_repairable"]
```

When analysis is saved before apply, set `status="analysis_pending"`, `applied=False`, `applied_at=""`.

When apply succeeds, set `status="applied"`, `applied=True`, and `applied_at`.

When apply raises, set `status="apply_failed"`, `applied=False`, save that record, then re-raise.

- [ ] **Step 3: Verify**

Run:

```bash
python -m pytest -q tests/test_repair_agent_service_flow.py
```

Expected: all service flow tests pass after updating expectations.

### Task 2: Explicit LLM Diagnosis Contract And Non-Repairable Decisions

**Files:**
- Modify: `services/repair_agent/app/analysis.py`
- Modify: `services/repair_agent/app/clients.py`
- Modify: `services/repair_agent/app/models.py`
- Modify: `services/repair_agent/app/service.py`
- Modify: `tests/test_repair_agent_analysis_llm_first.py`
- Modify: `tests/test_repair_agent_contract_and_retry.py`
- Modify: `tests/test_repair_agent_service_flow.py`
- Modify: `services/repair_agent/docs/repair-agent-design.md`

- [ ] **Step 1: Write failing tests**

Add tests asserting:
- LLM prompt requests `repairable` and `non_repairable_reason`.
- incomplete LLM diagnosis JSON is rejected instead of silently accepted.
- `repairable=false` skips knowledge-agent apply, persists `status="not_repairable"`, and returns a non-applied response.

Run:

```bash
python -m pytest -q tests/test_repair_agent_contract_and_retry.py::test_openai_chat_repair_analyzer_rejects_incomplete_diagnosis_schema tests/test_repair_agent_analysis_llm_first.py::test_repair_analyzer_preserves_non_repairable_decision tests/test_repair_agent_service_flow.py::test_repair_service_skips_apply_for_non_repairable_diagnosis
```

Expected before implementation: failures because incomplete diagnosis payloads are accepted and service always applies.

- [ ] **Step 2: Implement new diagnosis fields**

Extend `RepairAnalysisResult` with:

```python
repairable: bool = True
non_repairable_reason: str = ""
```

Require LLM JSON fields:

```text
repairable, non_repairable_reason, primary_knowledge_type, secondary_knowledge_types, confidence, suggestion, rationale
```

Delete the previous loose schema handling in `OpenAIChatCompletionRepairAnalyzer`.

For `repairable=false`, keep normalized knowledge types for audit but make `to_request()` invalid to call or have service avoid calling it.

- [ ] **Step 3: Implement service skip path**

If `analysis.repairable is False`, persist a record with:

```python
status="not_repairable"
applied=False
knowledge_repair_request=None
knowledge_ops_response=None
```

Return a response with `status="not_repairable"`, `applied=False`.

- [ ] **Step 4: Verify**

Run:

```bash
python -m pytest -q tests/test_repair_agent_contract_and_retry.py tests/test_repair_agent_analysis_llm_first.py tests/test_repair_agent_service_flow.py
```

### Task 3: Extract Prompt Builder From OpenAI Transport

**Files:**
- Create: `services/repair_agent/app/prompting.py`
- Modify: `services/repair_agent/app/clients.py`
- Modify: `tests/test_repair_agent_contract_and_retry.py`
- Add or modify: `tests/test_repair_agent_prompting.py`

- [ ] **Step 1: Write failing tests**

Add tests for `build_repair_diagnosis_prompt()` that assert:
- It returns `(system_prompt, user_prompt)`.
- The user prompt contains `IssueTicketSummary`, `DiagnosisContext`, `诊断顺序`, `知识类型选择规则`, and `判断 prompt_evidence 的规则`.
- The user prompt does not include raw `"input_prompt_snapshot"`.
- Repeated prompt evidence lines are deduped.

Run:

```bash
python -m pytest -q tests/test_repair_agent_prompting.py
```

Expected before implementation: import failure because `prompting.py` does not exist.

- [ ] **Step 2: Move prompt helpers**

Move these responsibilities out of `clients.py` into `prompting.py`:
- compact prompt snapshot
- compact diagnosis context
- repair ticket summary payload
- system/user prompt template

Expose:

```python
def build_repair_diagnosis_prompt(context: dict[str, Any], ticket: IssueTicket | None = None) -> tuple[str, str]:
    ...
```

Keep `OpenAIChatCompletionRepairAnalyzer` responsible only for calling the LLM, retrying, logging, parsing JSON, and returning parsed diagnosis.

- [ ] **Step 3: Verify**

Run:

```bash
python -m pytest -q tests/test_repair_agent_prompting.py tests/test_repair_agent_contract_and_retry.py
```

### Task 4: Remove Stale Config And Documentation Drift

**Files:**
- Modify: `services/repair_agent/app/config.py`
- Modify: `services/repair_agent/docs/repair-agent-design.md`
- Modify: `services/repair_agent/README.md`
- Modify tests that assert service defaults if needed.

- [ ] **Step 1: Write failing tests**

Add tests asserting `Settings` exposes only repair-agent-owned fields.

Run:

```bash
python -m pytest -q tests/test_deployment_defaults.py
```

Expected before implementation: failure because the fields still exist.

- [ ] **Step 2: Remove stale fields**

Keep only repair-agent-owned settings:
- app name, host, port
- data dir
- knowledge-agent apply URL and capture dir
- request timeout
- repair LLM config and retry/concurrency settings

- [ ] **Step 3: Update docs**

Make `repair-agent-design.md` describe:
- explicit `not_repairable` status
- lifecycle states that match implementation
- strict LLM diagnosis JSON schema
- missing prompt snapshot as input validation failure if the required field is absent, or empty prompt evidence if the required field is present but empty

Expand `README.md` with the current one-paragraph contract and main endpoints.

- [ ] **Step 4: Verify**

Run:

```bash
python -m pytest -q tests/test_deployment_defaults.py tests/test_repair_agent_naming_cleanup.py
```

### Final Verification

Run:

```bash
python -m pytest -q tests/test_repair_agent_contract_and_retry.py tests/test_repair_agent_service_flow.py tests/test_repair_agent_analysis_llm_first.py tests/test_repair_agent_llm_first_diagnosis.py tests/test_repair_agent_naming_cleanup.py tests/test_repair_agent_prompting.py tests/test_deployment_defaults.py
python -m py_compile services/repair_agent/app/analysis.py services/repair_agent/app/clients.py services/repair_agent/app/config.py services/repair_agent/app/models.py services/repair_agent/app/prompting.py services/repair_agent/app/service.py
```
