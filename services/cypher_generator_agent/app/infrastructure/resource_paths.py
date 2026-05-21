from __future__ import annotations

from pathlib import Path


SERVICE_ROOT = Path(__file__).resolve().parents[2]
RESOURCE_ROOT = SERVICE_ROOT / "resources"
RUNTIME_RESOURCE_ROOT = RESOURCE_ROOT / "runtime"
OFFLINE_RESOURCE_ROOT = RESOURCE_ROOT / "offline"

NATURAL_LANGUAGE_PREPROCESSING_RESOURCE_DIR = RUNTIME_RESOURCE_ROOT / "natural_language_preprocessing"
LEXICAL_RESOURCE_DIR = RUNTIME_RESOURCE_ROOT / "lexical"
INTENT_RESOURCE_DIR = RUNTIME_RESOURCE_ROOT / "intent"
ONTOLOGY_RESOURCE_DIR = RUNTIME_RESOURCE_ROOT / "ontology"
VALIDATION_RESOURCE_DIR = RUNTIME_RESOURCE_ROOT / "validation"
PHYSICAL_ORCHESTRATION_RESOURCE_DIR = RUNTIME_RESOURCE_ROOT / "physical_orchestration"
CLARIFICATION_RESOURCE_DIR = RUNTIME_RESOURCE_ROOT / "clarification"

OFFLINE_LEXICAL_ASSET_GENERATION_DIR = OFFLINE_RESOURCE_ROOT / "lexical_asset_generation"
OFFLINE_INTENT_EVALUATION_DIR = OFFLINE_RESOURCE_ROOT / "intent_evaluation"
OFFLINE_VECTOR_CORPUS_GENERATION_DIR = OFFLINE_RESOURCE_ROOT / "vector_corpus_generation"


def natural_language_preprocessing_dir() -> Path:
    return NATURAL_LANGUAGE_PREPROCESSING_RESOURCE_DIR


def lexical_mention_dictionaries_dir() -> Path:
    return LEXICAL_RESOURCE_DIR / "mention_dictionaries"


def ontology_resource_dir() -> Path:
    return ONTOLOGY_RESOURCE_DIR


def offline_lexical_generation_rules_path() -> Path:
    return OFFLINE_LEXICAL_ASSET_GENERATION_DIR / "generation_rules.yaml"


def offline_intent_eval_set_path() -> Path:
    return OFFLINE_INTENT_EVALUATION_DIR / "eval_set.jsonl"


def offline_mention_vector_corpus_path() -> Path:
    return OFFLINE_VECTOR_CORPUS_GENERATION_DIR / "mention_vector_corpus.jsonl"


def intent_taxonomy_path() -> Path:
    return INTENT_RESOURCE_DIR / "taxonomy.yaml"


def intent_rules_path() -> Path:
    return INTENT_RESOURCE_DIR / "rules.yaml"


def intent_embedding_corpus_path() -> Path:
    return INTENT_RESOURCE_DIR / "embedding_corpus.jsonl"


def intent_embedding_index_path() -> Path:
    return OFFLINE_INTENT_EVALUATION_DIR / "embedding_index.jsonl"


def intent_eval_set_path() -> Path:
    return offline_intent_eval_set_path()


def intent_llm_fewshots_path() -> Path:
    return INTENT_RESOURCE_DIR / "llm_fewshots.yaml"


def lexer_dictionary_priorities_path() -> Path:
    return LEXICAL_RESOURCE_DIR / "dictionary_priorities.yaml"


def lexer_signal_rules_path() -> Path:
    return LEXICAL_RESOURCE_DIR / "signal_rules.yaml"


def lexer_operators_path() -> Path:
    return LEXICAL_RESOURCE_DIR / "operators.yaml"


def lexer_quantifiers_path() -> Path:
    return LEXICAL_RESOURCE_DIR / "quantifiers.yaml"


def lexer_literal_patterns_path() -> Path:
    return LEXICAL_RESOURCE_DIR / "literal_patterns.yaml"


def lexer_mention_vector_corpus_path() -> Path:
    return offline_mention_vector_corpus_path()


def ontology_cypher_mapping_path() -> Path:
    return PHYSICAL_ORCHESTRATION_RESOURCE_DIR / "cypher_mapping.yaml"


def ontology_physical_graph_schema_path() -> Path:
    return PHYSICAL_ORCHESTRATION_RESOURCE_DIR / "physical_graph_schema.yaml"


def ontology_constraints_path() -> Path:
    return VALIDATION_RESOURCE_DIR / "constraints.yaml"


def ontology_domain_path() -> Path:
    return ONTOLOGY_RESOURCE_DIR / "domain_ontology.yaml"


def ontology_semantic_objects_path() -> Path:
    return ONTOLOGY_RESOURCE_DIR / "semantic_objects.yaml"
