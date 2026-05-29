# Cypher Generator Agent IR Closeout Status

> Date: 2026-05-28  
> Branch: `cypher-generation-osi`  
> Scope: `services/cypher_generator_agent` graph-native Cypher generation pipeline

## Summary

The v1 IR implementation is functionally closed for the local cypher-generator-agent pipeline. The agent now consumes a packaged TuGraph Graph Semantic Model YAML, resolves literals from a static value index, builds grounded bindings with deterministic slot grounding, validates semantics, emits a restricted DSL, compiles read-only TuGraph-oriented Cypher, runs static self-validation, and returns full trace payloads without connecting to TuGraph.

The live LLM smoke test has been executed against the configured OpenAI-compatible provider. API keys were environment-only inputs and must not be committed or recorded in trace/log fixtures. The architectural conclusion is that v1 should treat the LLM as a surface-slot filler; semantic grounding remains an engineering-owned step.

## Current Completion Matrix

| IR | Status | Evidence | Notes |
| --- | --- | --- | --- |
| IR-00 Project Contract Baseline | Done | API/output contract tests; no DB execution keys in CGA config | CGA remains generation-only and self-validation-only. |
| IR-01 Graph Model Fixture | Done | `tests/fixtures/golden_questions.yaml`; packaged TuGraph semantic artifact | Golden set has 33 questions, including MIR-001 projection-slot regression cases. |
| IR-02 Graph Model Loader / Registry | Done | `app/semantic_model/loader.py`, `registry.py`, validation tests | Supports OSI-style `semantic_model` wrapper. |
| IR-03a Cypher Self-Validation MVP | Done | syntax / readonly / schema reference tests | No database connection. |
| IR-03b Cypher Self-Validation Full | Done | shape, dialect, model artifact, variable-path bounds tests | Uses a conservative v1 parser adapter, not an ANTLR runtime dependency; path pattern and metric Cypher are load-time validated. |
| IR-04 Restricted DSL Models / Parser | Done | DSL parser and operation sequence tests | Raw Cypher escape hatch remains forbidden. |
| IR-05 Cypher Compiler MVP | Done | compiler tests for lookup, single hop, named path | Compiler emits read-only Cypher templates. |
| IR-06 Observability Skeleton | Done | trace/stage/metric tests | `cga_graph_trace_v1` used for final outputs. |
| IR-07 LiteralResolver MVP | Done | enum, ID, time/numeric tests | Uses packaged static `tugraph_value_index.json`; no live DB lookup. |
| IR-08 Candidate Retriever MVP | Done | retrieval tests | Candidates include confidence, match type, and evidence. |
| IR-09 Semantic Binder MVP | Done | binder tests | Binder converts deterministic or fallback grounded output into stable binding plan. |
| IR-10 Semantic Validator MVP | Done | coverage, endpoint, DSL support, aggregate tests | Coverage failures cannot silently generate Cypher. |
| IR-11 DSL Builder MVP | Done | builder tests across supported query shapes | Builds restricted DSL from validated binding plans. |
| IR-12 Pipeline Orchestrator MVP | Done | pipeline integration tests | End-to-end deterministic path works. |
| SP-01 LLM Feasibility Spike | Done (live smoke) | spike report, structured LLM client tests, 5-question provider smoke | v1 regular path uses LLM decomposition only; deterministic grounding prevents dependence on Grounded JSON shape. |
| IR-13 Question Decomposer | Done | schema retry and term classification tests | Real LLM path uses structured output. |
| IR-14 Grounded LLM Understanding | Done | grounded schema and candidate boundary tests | Kept as fallback/repair capability; regular path prefers deterministic grounding from semantic candidates and literal results. |
| IR-15 Repair / Clarification Controller | Done | decision matrix, fingerprint, assumption notice, pipeline repair-loop test | Multi-round LLM re-grounding is now connected for repairable semantic validator failures. |
| IR-16 Full Trace and Testing-Agent Contract | Done | API contract and testing-agent submission tests | Generated and non-success outputs carry trace snapshots. |
| IR-16.5 Performance Baseline | Done | baseline collector/writer tests | CI does not yet publish baseline artifacts; local artifact writer exists. |
| IR-17 Variable Path Traversal | Done | DSL/compiler/integration tests | Covers tunnels through devices. |
| IR-18 Metric / Ad Hoc Aggregate | Done | aggregate builder/compiler/integration tests | Covers metric and ad hoc group-by patterns. |
| IR-19 Top-N and Two-Step Aggregate | Done | top-n/two-step builder/compiler/integration tests | Covers nested aggregate path. |
| IR-20 Golden Test Regression Matrix | Done | `test_golden_questions.py`; `.github/workflows/cypher-generator-agent.yml` | All 33 questions are tracked; runtime fixtures cover every generated query shape plus MIR-001 projection-slot slice, and non-runtime failure cases are backed by RepairController contracts. |

## Acceptance Evidence

Fresh local verification command:

```bash
PYTHONPATH=. pytest services/cypher_generator_agent/tests -q
```

Latest verified result:

```text
484 passed in 3.99s
```

Golden regression entrypoints:

```bash
PYTHONPATH=. pytest services/cypher_generator_agent/tests/integration/test_golden_questions.py::test_smoke_golden_regression_case_matches_expected_contract -q
PYTHONPATH=. pytest services/cypher_generator_agent/tests/integration/test_golden_questions.py -q
```

Current golden matrix details:

- 33 declared questions (`gq-001` through `gq-033`).
- Runtime fixture coverage now includes `vertex_lookup`, `single_hop_traversal`, `named_path_pattern`, `variable_path_traversal`, `metric_aggregate`, `ad_hoc_aggregate`, `top_n`, `two_step_aggregate`, and the MIR-001 projection-slot slice (`gq-031` through `gq-033`).
- Non-runtime negative cases are checked through RepairController contract tests for ambiguity, unsupported shape, readonly, oscillation, compiler shape mismatch, missing path parameters, and duplicate literal ambiguity.

## Operational Follow-Ups

1. Decide whether CI should upload `reports/baseline_YYYYMMDD.json` artifacts, or keep performance baseline generation manual until v1.1.
2. Keep static value-index freshness documented: new TuGraph entities are visible only after the next semantic artifact release.
3. Keep provider smoke artifacts redacted: no API keys, Authorization headers, or full environment dumps.

## Explicit Boundaries

- CGA does not connect to TuGraph.
- CGA does not run `EXPLAIN`, dry-run, probe query, or execution query.
- DSL unsupported cases do not fallback to raw LLM-generated Cypher.
- LLM regular path only fills question decomposition slots; candidate selection, literal binding, traversal selection, aggregation, DSL, compiler, and self-validation are deterministic.
- API keys and provider secrets are environment-only inputs.
