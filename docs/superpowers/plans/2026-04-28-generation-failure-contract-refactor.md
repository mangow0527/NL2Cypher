# Generation Failure Contract Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Align cypher-generator-agent and testing-agent code with the approved contracts for replay evidence, generation failure reporting, and reliable testing-agent delivery.

**Architecture:** cypher-generator-agent remains the generator and does not become the formal evaluation store, but it must submit richer evidence and maintain a short-lived durable outbox when testing-agent delivery fails. testing-agent becomes the unified receiver for successful submissions and generation failure reports, persists generation evidence, evaluates generation failures as failed attempts, and emits repair tickets with enough evidence for replay.

**Tech Stack:** Python, FastAPI, Pydantic v2, JSON file repositories, pytest.

---

### Task 1: cypher-generator-agent contract fields and failure reports

**Files:**
- Modify: `services/cypher_generator_agent/app/models.py`
- Modify: `services/cypher_generator_agent/app/schemas.py`
- Modify: `services/cypher_generator_agent/app/service.py`
- Modify: `services/cypher_generator_agent/app/clients.py`
- Test: `tests/test_query_generation_service_workflow.py`
- Test: `tests/test_prompt_service_client_contract.py`
- Test: `tests/test_verify_communication_contract.py`

- [ ] **Step 1: Write failing tests for successful submission evidence**

Add or update tests so a successful generated submission contains:

```python
assert submitted_payload.last_llm_raw_output == "MATCH (n) RETURN n"
assert submitted_payload.generation_retry_count == 0
assert submitted_payload.generation_failure_reasons == []
```

For a success after one failed generation attempt:

```python
assert submitted_payload.generation_retry_count == 1
assert submitted_payload.generation_failure_reasons == ["wrapped_in_markdown"]
assert submitted_payload.last_llm_raw_output == "MATCH (n) RETURN n"
```

- [ ] **Step 2: Run tests and confirm RED**

Run:

```bash
pytest tests/test_query_generation_service_workflow.py tests/test_prompt_service_client_contract.py tests/test_verify_communication_contract.py -q
```

Expected: failures because `GeneratedCypherSubmissionRequest` has no new evidence fields.

- [ ] **Step 3: Implement successful submission contract**

Update `GeneratedCypherSubmissionRequest` in cypher-generator-agent to include:

```python
last_llm_raw_output: str
generation_retry_count: int = Field(default=0, ge=0)
generation_failure_reasons: list[GenerationFailureReason] = Field(default_factory=list)
```

In `CypherGeneratorAgentService.ingest_question()`, track:

```python
generation_failure_reasons: list[GenerationFailureReason] = []
last_llm_raw_output = ""
```

Append parser/preflight failure reasons before retrying. On success, submit the final raw output, retry count as `len(generation_failure_reasons)`, and the collected reason list.

- [ ] **Step 4: Write failing tests for generation failure report submission**

Add tests where all generation attempts fail. Expect the testing client to receive a `GenerationRunFailureReport` with:

```python
assert report.generation_status == "generation_failed"
assert report.failure_reason == "generation_retry_exhausted"
assert report.last_generation_failure_reason == "wrapped_in_markdown"
assert report.generation_retry_count == 2
assert report.generation_failure_reasons == ["wrapped_in_markdown", "wrapped_in_markdown", "wrapped_in_markdown"]
assert report.last_llm_raw_output
assert report.gate_passed is False
```

- [ ] **Step 5: Run tests and confirm RED**

Run:

```bash
pytest tests/test_query_generation_service_workflow.py -q
```

Expected: failure because there is no `GenerationRunFailureReport` model or submit path.

- [ ] **Step 6: Implement generation failure report**

Add `GenerationRunFailureReport` to cypher-generator-agent models and schemas. Extend the submitter protocol/client with:

```python
async def submit_generation_failure(self, payload: GenerationRunFailureReport) -> Dict[str, object]:
    ...
```

For generation retry exhaustion, construct the report and send it to testing-agent. Preserve the external `GenerationRunResult(generation_status="generation_failed")`.

- [ ] **Step 7: Run task tests and fix regressions**

Run:

```bash
pytest tests/test_query_generation_service_workflow.py tests/test_prompt_service_client_contract.py tests/test_verify_communication_contract.py -q
```

Expected: all pass.

---

### Task 2: cypher-generator-agent durable outbox for testing-agent delivery

**Files:**
- Create: `services/cypher_generator_agent/app/outbox.py`
- Modify: `services/cypher_generator_agent/app/config.py`
- Modify: `services/cypher_generator_agent/app/service.py`
- Modify: `services/cypher_generator_agent/app/clients.py`
- Modify: `services/cypher_generator_agent/app/main.py`
- Test: `tests/test_query_generation_service_workflow.py`

- [ ] **Step 1: Write failing tests for outbox persistence and deletion**

Add tests proving:

```python
# after sync submission attempts fail
assert outbox.list_pending()[0]["payload"]["id"] == "qa-001"

# after background resend gets {"accepted": True}
assert outbox.list_pending() == []
```

Also cover `dead_letter` for non-retryable 4xx.

- [ ] **Step 2: Run tests and confirm RED**

Run:

```bash
pytest tests/test_query_generation_service_workflow.py -q
```

Expected: failure because outbox does not exist.

- [ ] **Step 3: Implement outbox repository**

Create a JSON-file outbox with:

```python
save(payload_type, payload, status="pending")
list_retryable(now)
mark_retrying(delivery_id, error)
delete(delivery_id)
mark_dead_letter(delivery_id, error)
```

Store records under a configurable `delivery_outbox_dir`, defaulting inside the cypher-generator-agent data directory.

- [ ] **Step 4: Wire client delivery behavior**

When synchronous delivery exhausts retryable failures, save the original payload into outbox and return service failure. When background delivery succeeds, delete the outbox record. Do not keep a `delivered` long-term record.

- [ ] **Step 5: Add startup resume**

On cypher-generator-agent startup, schedule retry of pending outbox records. Keep this small and deterministic; no new queue service.

- [ ] **Step 6: Run task tests**

Run:

```bash
pytest tests/test_query_generation_service_workflow.py -q
```

Expected: pass.

---

### Task 3: testing-agent generation failure endpoint and evaluation path

**Files:**
- Modify: `services/testing_agent/app/models.py`
- Modify: `services/testing_agent/app/schemas.py`
- Modify: `services/testing_agent/app/main.py`
- Modify: `services/testing_agent/app/repository.py`
- Modify: `services/testing_agent/app/service.py`
- Modify: `services/testing_agent/app/grammar.py`
- Test: `tests/test_testing_service_llm_eval.py`
- Test: `tests/test_testing_service_idempotency.py`
- Test: `tests/test_attempt_contract.py`

- [ ] **Step 1: Write failing tests for generation failure ingestion**

Add tests for `GenerationRunFailureReport(generation_status="generation_failed")`:

```python
receipt = await service.ingest_generation_failure(report)
assert receipt.accepted is True
attempt = repository.get_submission_attempt("qa-001", 1)
assert attempt["generation_status"] == "generation_failed"
assert attempt["generated_cypher"] == report.parsed_cypher or report.last_llm_raw_output
```

- [ ] **Step 2: Write failing tests for scoring generation failure attempts**

With a golden already present, ingest generation failure and assert:

```python
assert evaluation["verdict"] == "fail"
assert evaluation["primary_metrics"]["grammar"]["score"] == 0
assert evaluation["primary_metrics"]["execution_accuracy"]["reason"] == "grammar_failed"
assert evaluation["secondary_signals"]["gleu"]["score"] >= 0.0
assert evaluation["secondary_signals"]["jaro_winkler_similarity"]["score"] >= 0.0
assert issue_ticket["generation_evidence"]["last_llm_raw_output"] == report.last_llm_raw_output
```

- [ ] **Step 3: Run tests and confirm RED**

Run:

```bash
pytest tests/test_testing_service_llm_eval.py tests/test_testing_service_idempotency.py tests/test_attempt_contract.py -q
```

Expected: failures because the model, endpoint, repository, and evaluation path do not exist.

- [ ] **Step 4: Implement testing-agent models and endpoint**

Add `GenerationRunFailureReport` and expose:

```text
POST /api/v1/evaluations/generation-failures
```

For `service_failed`, persist a generation failure record without assigning formal `attempt_no`. For `generation_failed`, save a formal attempt.

- [ ] **Step 5: Implement candidate query evaluation**

For generation failed attempts:

```python
candidate_query_text = parsed_cypher or last_llm_raw_output or ""
grammar = GrammarMetric(score=0, parser_error=optional_parser_error, message=message_from_failure_reason)
execution = None
strict_check.status = "not_run"
semantic_check.status = "not_run"
secondary_signals = build_secondary_signals(generated_cypher=candidate_query_text, gold_cypher=golden["cypher"])
```

Generate an IssueTicket when verdict is fail.

- [ ] **Step 6: Preserve new evidence fields**

Extend `GenerationEvidence`, `SubmissionRecord`, repository matching, and issue ticket creation to include:

```python
last_llm_raw_output
generation_status
failure_reason
generation_retry_count
generation_failure_reasons
```

- [ ] **Step 7: Run task tests**

Run:

```bash
pytest tests/test_testing_service_llm_eval.py tests/test_testing_service_idempotency.py tests/test_attempt_contract.py -q
```

Expected: pass.

---

### Task 4: cross-service contract and regression suite

**Files:**
- Modify: `tests/test_verify_communication_contract.py`
- Modify: `tests/test_runtime_results_service_api.py` if runtime fixtures require new evidence fields
- Modify: any failing tests caused by stricter contracts

- [ ] **Step 1: Write contract tests for both payload types**

Assert cypher-generator-agent and testing-agent models accept the same successful submission shape and generation failure report shape.

- [ ] **Step 2: Run broad targeted tests**

Run:

```bash
pytest \
  tests/test_query_generation_service_workflow.py \
  tests/test_prompt_service_client_contract.py \
  tests/test_verify_communication_contract.py \
  tests/test_testing_service_llm_eval.py \
  tests/test_testing_service_idempotency.py \
  tests/test_attempt_contract.py \
  tests/test_runtime_results_service_api.py \
  -q
```

Expected: pass.

- [ ] **Step 3: Run final relevant suite**

Run:

```bash
pytest tests -q
```

Expected: pass, or report unrelated pre-existing failures with exact test names.
