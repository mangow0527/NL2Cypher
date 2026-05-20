from __future__ import annotations

from pathlib import Path


SERVICE_ROOT = Path(__file__).resolve().parents[1]
RESOURCE_ROOT = SERVICE_ROOT / "resources"

INTENT_RESOURCE_DIR = RESOURCE_ROOT / "intent"
LEXER_RESOURCE_DIR = RESOURCE_ROOT / "lexer"
ONTOLOGY_RESOURCE_DIR = RESOURCE_ROOT / "ontology"


def intent_taxonomy_path() -> Path:
    return INTENT_RESOURCE_DIR / "taxonomy.yaml"


def intent_rules_path() -> Path:
    return INTENT_RESOURCE_DIR / "rules.yaml"


def intent_embedding_corpus_path() -> Path:
    return INTENT_RESOURCE_DIR / "embedding_corpus.jsonl"


def intent_embedding_index_path() -> Path:
    return INTENT_RESOURCE_DIR / "embedding_index.jsonl"


def intent_eval_set_path() -> Path:
    return INTENT_RESOURCE_DIR / "eval_set.jsonl"


def intent_llm_fewshots_path() -> Path:
    return INTENT_RESOURCE_DIR / "llm_fewshots.yaml"


def lexer_dictionary_priorities_path() -> Path:
    return LEXER_RESOURCE_DIR / "dictionary_priorities.yaml"


def lexer_mention_vector_corpus_path() -> Path:
    return LEXER_RESOURCE_DIR / "mention_vector_corpus.jsonl"


def ontology_cypher_mapping_path() -> Path:
    return ONTOLOGY_RESOURCE_DIR / "cypher_mapping.yaml"


def ontology_physical_graph_schema_path() -> Path:
    return ONTOLOGY_RESOURCE_DIR / "physical_graph_schema.yaml"


def ontology_constraints_path() -> Path:
    return ONTOLOGY_RESOURCE_DIR / "constraints.yaml"


def ontology_domain_path() -> Path:
    return ONTOLOGY_RESOURCE_DIR / "domain_ontology.yaml"


def ontology_semantic_objects_path() -> Path:
    return ONTOLOGY_RESOURCE_DIR / "semantic_objects.yaml"
