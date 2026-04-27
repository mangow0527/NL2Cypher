# Testing Agent Rewrite Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rewrite `services/testing_agent/app` and its tests to match `services/testing_agent/docs/testing-agent-design.md`.

**Architecture:** Replace the old dimension-based evaluation flow with a document-aligned pipeline: pair golden/submission, grammar check, execution, strict compare, semantic review, summary assembly, issue-ticket dispatch, and improvement assessment. Keep FastAPI endpoints, data directory layout, and external service boundaries, but rebuild models, orchestration, persistence, and tests from the new contracts outward.

**Tech Stack:** FastAPI, Pydantic v2, httpx, pytest, file-based JSON persistence.

---

## Task groups

- [ ] Rebuild formal contracts and state models
- [ ] Rebuild persistence around new submission/attempt semantics
- [ ] Rebuild evaluation pipeline (grammar, execution, strict compare, semantic review, summary assembly)
- [ ] Rebuild service orchestration and API routes
- [ ] Rebuild testing-agent test suite around the new contracts
- [ ] Run targeted verification and fix remaining mismatches
