# LLM Retries And repair-agent Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add real retry behavior for testing-agent and repair-agent LLM calls, further shrink repair-agent payloads, and clean up the touched code without reintroducing fake fallback behavior.

**Architecture:** Keep retries close to the actual LLM HTTP boundaries so failures remain truthful while retries are observable. Reduce repair-agent latency by compacting request content instead of masking failures. Finish with focused refactors and repeated review passes over the touched modules and tests.

**Tech Stack:** Python, httpx, pytest, FastAPI service modules

---

### Task 1: Lock Retry And Payload Expectations With Tests

**Files:**
- Modify: `tests/test_testing_service_llm_eval.py`
- Modify: `tests/test_krss_contract_and_retry.py`

- [ ] Add failing tests for retryable `429`, `5xx`, and timeout behavior in `LLMEvaluationClient`
- [ ] Add failing tests for retryable `429`, `5xx`, and timeout behavior in `OpenAICompatibleKRSSAnalyzer`
- [ ] Add failing tests for richer repair-agent payload compaction expectations
- [ ] Run targeted pytest commands and confirm the new tests fail for the expected reasons

### Task 2: Implement Honest LLM Retry Logic

**Files:**
- Modify: `services/testing_agent/app/clients.py`
- Modify: `services/repair_agent/app/clients.py`

- [ ] Add bounded exponential-backoff retry helpers for retryable LLM failures
- [ ] Retry only truthful transient cases: timeout, transport errors, HTTP `429`, and HTTP `5xx`
- [ ] Keep non-retryable `4xx` failures immediate
- [ ] Preserve explicit logging for each attempt, final success, and final failure
- [ ] Run focused pytest commands and confirm the retry tests pass

### Task 3: Shrink repair-agent Request Payload Further

**Files:**
- Modify: `services/repair_agent/app/clients.py`
- Modify: `tests/test_krss_contract_and_retry.py`

- [ ] Tighten repair-agent ticket serialization to only the fields required for diagnosis
- [ ] Further compact prompt snapshots with dedupe/truncation rules that keep the most relevant context
- [ ] Log original versus compacted prompt sizes for remote verification
- [ ] Run focused pytest commands and confirm the payload-shrinking tests pass

### Task 4: Cleanup And Refactor The Touched LLM Code

**Files:**
- Modify: `services/testing_agent/app/clients.py`
- Modify: `services/repair_agent/app/clients.py`
- Modify: any adjacent tests only as needed

- [ ] Remove duplication in retry classification and logging helpers where it improves clarity
- [ ] Simplify naming and helper boundaries in the touched modules
- [ ] Keep code comments minimal and only where the retry rules are not obvious
- [ ] Run the full pytest suite and confirm all tests pass

### Task 5: Repeat Review And Remote Verification

**Files:**
- No new product files required

- [ ] Review the touched code once for redundancy and dead paths
- [ ] Review it a second time for readability and boundary clarity
- [ ] Review it a third time for test gaps and brittle behavior
- [ ] Deploy to the remote host and verify real logs show retries and compacted repair-agent prompt sizes
- [ ] Summarize the observed remote behavior, residual risks, and any remaining cleanup opportunities
