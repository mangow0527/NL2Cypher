# Cypher Generator Resource Boundary Design

## 1. Context

`cypher-generator-agent` currently keeps intent recognition, slot matching, business slot rules, and semantic layer assets together under:

```text
services/cypher_generator_agent/config/
```

The files are runtime domain assets rather than application settings. They also belong to different semantic layers:

- intent recognition assets decide the answer shape.
- slot matching assets extract low-level candidates from natural language.
- business slot schemas validate task completeness for accepted intents.
- semantic layer assets define the governed graph contract used for linking, validation, rendering, and preflight.

Keeping all of these files flat under `config/` makes the ownership boundary hard to see. The most problematic file is `slot_dictionary.yaml`, because it currently combines lexical synonyms, enum value aliases, parse patterns, default filter ownership, and entity-property ownership hints.

## 2. Goals

1. Make resource boundaries explicit in the filesystem.
2. Split mixed slot matching resources by responsibility.
3. Move default resource path discovery into a single code module.
4. Keep runtime behavior equivalent after the move.
5. Keep the change below a governance-layer refactor. No manifest, no dedicated asset CLI, and no new external service dependency in this phase.

## 3. Non-Goals

- Do not redesign intent taxonomy semantics.
- Do not change generated Cypher behavior.
- Do not remove semantic layer `synonyms` or `value_mappings` in this phase.
- Do not move or rename the TuGraph physical schema reference unless a later design handles shared schema ownership.
- Do not add asset governance workflows such as approvals, version registries, or standalone validation commands.

## 4. Target Directory Layout

Create a new resource root:

```text
services/cypher_generator_agent/resources/
  intent/
    taxonomy.yaml
    rules.yaml
    embedding_corpus.jsonl
    eval_set.jsonl
    llm_fewshots.yaml

  slots/
    lexicon.yaml
    value_aliases.yaml
    parse_patterns.yaml

  business/
    slot_schemas.yaml

  semantic/
    layer.yaml

  README.md
```

`config/` should stop being the default home for domain assets. It may remain for service configuration concepts if needed later, but current YAML/JSONL domain resources move to `resources/`.

## 5. File Responsibilities

### 5.1 Intent Resources

`resources/intent/taxonomy.yaml`

- Owns valid `primary_intent` and `secondary_intent` values.
- Owns human-readable intent descriptions and examples.
- May keep taxonomy-level metadata such as output schema and classification priority for now, because current recognizers and prompts already consume those concepts together.
- Must not contain graph schema labels, edge types, properties, or business slot completeness rules.

`resources/intent/rules.yaml`

- Owns first-stage high-confidence keyword rules.
- Each rule maps to an intent defined in taxonomy.
- Must not contain slot extraction rules or graph schema linking details.

`resources/intent/embedding_corpus.jsonl`

- Owns embedding-stage retrieval samples.
- Each line is a sample for one valid taxonomy intent.
- Must not contain evaluation-only expected fields.

`resources/intent/eval_set.jsonl`

- Owns intent-recognition evaluation cases.
- Each line has a question and expected intent labels.
- Must not be loaded by production request handling.

`resources/intent/llm_fewshots.yaml`

- Owns third-stage LLM intent fallback principles, ambiguity boundaries, and reasoning examples.
- Must not generate Cypher or define graph schema.

### 5.2 Slot Resources

`resources/slots/lexicon.yaml`

Owns lexical candidate recall:

```yaml
entities:
relationships:
properties:
metric_templates:
```

These are words or phrases used to find low-level candidates in the user question. They are not schema authority. The resulting candidates still need schema linking and semantic validation.

`resources/slots/value_aliases.yaml`

Owns enum or literal value normalization:

```yaml
values:
  quality_of_service:
    Gold: ["Gold", "gold", "金牌"]
```

This file answers: "When the user says X, which canonical value should the filter use?"

It should not contain entity-property ownership, sort words, or limit regexes.

`resources/slots/parse_patterns.yaml`

Owns deterministic parsing helpers:

```yaml
default_filter_entity:
entity_properties:
order:
group_by:
limit:
```

This file answers: "How should the slot matcher interpret matched words around filters, ordering, grouping, and limits?"

`entity_properties` remains here for now because the current `SlotMatcher` uses it for owner inference before semantic linking. It is not graph schema authority; the semantic layer remains the authority and tests must continue ensuring these hints do not reference fields outside the semantic layer.

### 5.3 Business Resources

`resources/business/slot_schemas.yaml`

- Owns intent-to-business-slot completeness requirements.
- Defines required slots, dependency metadata, priority, and follow-up questions.
- Must not define low-level synonyms or physical graph labels.

### 5.4 Semantic Resources

`resources/semantic/layer.yaml`

- Owns graph semantic contract used by schema linking, semantic validation, query building, rendering, and preflight.
- Defines entities, relationships, properties, metrics, path patterns, and value mappings.
- May keep `synonyms` and `value_mappings` for this phase as semantic contract metadata.
- Must remain aligned with the TuGraph physical schema reference and the knowledge directory schema used by semantic alignment.

The overlap between slot-side aliases and semantic-layer synonyms is intentional for now:

- slot resources optimize natural-language recall.
- semantic layer resources define governed schema concepts.

A later governance phase can decide whether aliases should have a single source of truth.

## 6. Code Design

Add a small resource path module:

```text
services/cypher_generator_agent/app/resource_paths.py
```

It should expose functions or constants such as:

```python
RESOURCE_ROOT
intent_taxonomy_path()
intent_rules_path()
intent_embedding_corpus_path()
intent_eval_set_path()
intent_llm_fewshots_path()
slot_lexicon_path()
slot_value_aliases_path()
slot_parse_patterns_path()
business_slot_schemas_path()
semantic_layer_path()
```

Default loaders should import this module instead of constructing paths with:

```python
Path(__file__).resolve().parents[1] / "config"
```

Affected modules:

- `intent_recognition.py`
- `prompt_runtime.py`
- `slot_matching.py`
- `business_slot_schema.py`
- `semantic_layer.py`
- `semantic_alignment.py`

Tools and tests that reference old paths should also switch to `resources/`.

## 7. Slot Resource Loading

`SlotMatcher.from_default_config()` should keep the public API name for compatibility, but internally it should load and merge the three split slot files:

```text
lexicon.yaml
value_aliases.yaml
parse_patterns.yaml
```

The merged in-memory dictionary should preserve the current shape expected by `SlotMatcher.__init__`:

```yaml
entities:
relationships:
properties:
values:
default_filter_entity:
entity_properties:
metric_templates:
order:
group_by:
limit:
```

This keeps `SemanticPipeline`, `BusinessSlotFiller`, and current tests from needing broad changes.

## 8. Migration Map

Move current files as follows:

| Current file | New file |
| --- | --- |
| `config/intent_taxonomy.yaml` | `resources/intent/taxonomy.yaml` |
| `config/intent_rules.yaml` | `resources/intent/rules.yaml` |
| `config/intent_embedding_corpus.jsonl` | `resources/intent/embedding_corpus.jsonl` |
| `config/intent_eval_set.jsonl` | `resources/intent/eval_set.jsonl` |
| `config/intent_llm_fewshots.yaml` | `resources/intent/llm_fewshots.yaml` |
| `config/business_slot_schemas.yaml` | `resources/business/slot_schemas.yaml` |
| `config/semantic_layer.yaml` | `resources/semantic/layer.yaml` |

Split `config/slot_dictionary.yaml` into:

| Current section | New file |
| --- | --- |
| `entities` | `resources/slots/lexicon.yaml` |
| `relationships` | `resources/slots/lexicon.yaml` |
| `properties` | `resources/slots/lexicon.yaml` |
| `metric_templates` | `resources/slots/lexicon.yaml` |
| `values` | `resources/slots/value_aliases.yaml` |
| `default_filter_entity` | `resources/slots/parse_patterns.yaml` |
| `entity_properties` | `resources/slots/parse_patterns.yaml` |
| `order` | `resources/slots/parse_patterns.yaml` |
| `group_by` | `resources/slots/parse_patterns.yaml` |
| `limit` | `resources/slots/parse_patterns.yaml` |

After migration, remove the old `config/*.yaml` and `config/*.jsonl` resource files so there is no double source of truth.

## 9. Documentation

Add `services/cypher_generator_agent/resources/README.md` describing:

- the four resource domains.
- each file's responsibility.
- what not to put in each file.
- the distinction between slot recall aliases and semantic-layer contract metadata.
- the fact that governance checks are intentionally out of scope for this phase.

Update existing docs that mention `config/` resource files:

- `services/cypher_generator_agent/docs/cypher-generator-agent-design.md`
- `docs/superpowers/specs/2026-05-07-nl2cypher-semantic-pipeline-design.md`
- `services/cypher_generator_agent/docs/intent-recognition-stage-status.md`
- relevant test or tool comments if they mention old paths.

## 10. Error Handling

Resource loading failures should remain explicit:

- missing YAML/JSONL files should fail fast in default loader paths.
- malformed YAML should continue surfacing as loader errors.
- unknown intent references should continue failing through existing recognizer validation.
- semantic layer physical schema mismatch should continue failing through semantic alignment.

Do not add fallback to old `config/` paths. A fallback would preserve ambiguity and create two possible resource roots.

## 11. Testing

Run focused tests that cover the moved resources and unchanged behavior:

```bash
python -m pytest -q \
  services/cypher_generator_agent/tests/test_intent_recognition.py \
  services/cypher_generator_agent/tests/test_slot_matching.py \
  services/cypher_generator_agent/tests/test_business_slot_schema.py \
  services/cypher_generator_agent/tests/test_semantic_layer.py \
  services/cypher_generator_agent/tests/test_schema_linking_and_validation.py \
  services/cypher_generator_agent/tests/test_semantic_pipeline.py \
  tests/test_query_generation_service_api.py
```

Also run tool-level checks if changed:

```bash
python -m pytest -q services/cypher_generator_agent/tests/test_intent_evaluation.py
```

## 12. Risks

Path churn is the main risk. Centralizing default paths in `resource_paths.py` keeps this controlled.

Duplicate aliases remain between slot resources and semantic layer. This is accepted in this phase because removing semantic-layer synonyms or value mappings would change the semantic contract surface and alignment behavior.

Some tests currently hard-code `services/cypher_generator_agent/config/...`. These need targeted updates to avoid stale references.

## 13. Acceptance Criteria

- Production default loaders read from `services/cypher_generator_agent/resources/`.
- Old domain resource files are no longer present under `config/`.
- `slot_dictionary.yaml` is split into three responsibility-focused files.
- Runtime generation behavior for existing semantic pipeline examples is unchanged.
- Documentation explains the resource boundaries clearly.
- Focused tests listed above pass.
