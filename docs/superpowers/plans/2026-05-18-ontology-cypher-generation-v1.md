# Ontology Cypher Generation V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first isolated ontology-based NL2Cypher generation slice for the documented four-step flow.

**Architecture:** Add a new `services/cypher_generator_agent/app/ontology_generation/` package without replacing the existing semantic-view pipeline. The first slice loads current mention dictionaries, performs deterministic lexing and mention-aware intent/shape classification, plans the golden Service → Tunnel → source NetworkElement query, validates the logical plan, compiles TuGraph Cypher, and emits replay evidence.

**Tech Stack:** Python dataclasses, YAML assets, existing pytest layout, no runtime LLM dependency in the first deterministic golden path.

---

### Task 1: Golden Flow Contract Test

**Files:**
- Create: `services/cypher_generator_agent/tests/test_ontology_generation_pipeline.py`

- [x] **Step 1: Write the failing test**

```python
from services.cypher_generator_agent.app.ontology_generation import OntologyGenerationPipeline


def test_ontology_generation_pipeline_generates_golden_service_tunnel_source_ne_query() -> None:
    pipeline = OntologyGenerationPipeline.from_default_resources()

    result = pipeline.generate(
        "查询金牌服务经过的隧道及其源网元，返回隧道的IETF标准和源网元的IP地址",
        trace_id="trace-golden",
    )

    assert result.status == "generated"
    assert result.cypher == (
        "MATCH (s:Service)-[:SERVICE_USES_TUNNEL]->(t:Tunnel)-[:TUNNEL_SRC]->(ne:NetworkElement)\n"
        "WHERE s.quality_of_service = 'Gold'\n"
        "RETURN t.ietf_standard AS tunnel_ietf_standard, ne.ip_address AS source_ne_ip_address"
    )
    assert result.trace.trace_id == "trace-golden"
    assert result.trace.lexer.mentions
    assert result.trace.intent.intent.primary == "record_retrieval_query"
    assert result.trace.intent.intent.secondary == "related_record_query"
    assert [edge.relation for edge in result.logical_plan.edges] == [
        "REL_SERVICE_USES_TUNNEL",
        "REL_TUNNEL_SRC",
    ]
```

- [x] **Step 2: Run test to verify it fails**

Run: `pytest services/cypher_generator_agent/tests/test_ontology_generation_pipeline.py -q`

Expected: FAIL with missing module `ontology_generation`.

### Task 2: Implement Minimal Ontology Generation Package

**Files:**
- Create: `services/cypher_generator_agent/app/ontology_generation/__init__.py`
- Create: `services/cypher_generator_agent/app/ontology_generation/models.py`
- Create: `services/cypher_generator_agent/app/ontology_generation/assets.py`
- Create: `services/cypher_generator_agent/app/ontology_generation/lexer.py`
- Create: `services/cypher_generator_agent/app/ontology_generation/intent.py`
- Create: `services/cypher_generator_agent/app/ontology_generation/planner.py`
- Create: `services/cypher_generator_agent/app/ontology_generation/validator.py`
- Create: `services/cypher_generator_agent/app/ontology_generation/compiler.py`
- Create: `services/cypher_generator_agent/app/ontology_generation/pipeline.py`

- [x] **Step 1: Implement data models and asset loading**
- [x] **Step 2: Implement longest-match dictionary lexer**
- [x] **Step 3: Implement deterministic intent + initial shape classifier**
- [x] **Step 4: Implement the golden path logical planner**
- [x] **Step 5: Implement semantic validator and deterministic compiler**
- [x] **Step 6: Wire the pipeline and trace output**
- [x] **Step 7: Run the golden flow test**

### Task 3: Prompt Template Contract

**Files:**
- Test: `services/cypher_generator_agent/tests/test_ontology_generation_prompt_registry.py`
- Create: `services/cypher_generator_agent/app/ontology_generation/prompts.py`

- [x] **Step 1: Write failing tests for prompt rendering and output validation**
- [x] **Step 2: Implement prompt registry with current weak-model schemas**
- [x] **Step 3: Run prompt registry tests**

### Task 4: Regression Sweep

**Files:**
- Existing tests only

- [x] **Step 1: Run focused ontology tests**

Run: `pytest services/cypher_generator_agent/tests/test_ontology_generation_pipeline.py services/cypher_generator_agent/tests/test_ontology_generation_prompt_registry.py -q`

- [x] **Step 2: Run existing cypher-generator-agent tests**

Run: `pytest services/cypher_generator_agent/tests -q`

### Task 5: Natural Language Question Preprocessing Integration

**Files:**
- Modify: `services/cypher_generator_agent/app/ontology_generation/pipeline.py`
- Modify: `services/cypher_generator_agent/app/ontology_generation/models.py`
- Modify: `services/cypher_generator_agent/app/ontology_generation/lexer.py`
- Modify: `services/cypher_generator_agent/resources/mention_dictionaries/attributes.yaml`
- Test: `services/cypher_generator_agent/tests/test_ontology_generation_pipeline.py`

- [x] **Step 1: Write failing tests proving preprocessing is upstream of lexer**
- [x] **Step 2: Run tests and verify failure is missing preprocessing trace**
- [x] **Step 3: Call `preprocess_question()` before lexer and store preprocessing payload in trace**
- [x] **Step 4: Use `core_question` as lexer input**
- [x] **Step 5: Add `IP` abbreviation support for source/destination network-element IP projection**
- [x] **Step 6: Run focused ontology tests**
- [x] **Step 7: Run existing cypher-generator-agent tests**
