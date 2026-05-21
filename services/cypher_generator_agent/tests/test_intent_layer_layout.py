import importlib.util
from pathlib import Path

from services.cypher_generator_agent.app.intent_layer import (
    EmbeddingIntentRecognizer,
    FallbackEmbeddingStore,
    IntentRecognitionResult,
    RagIntentEmbeddingStore,
    RuleBasedIntentRecognizer,
    get_hybrid_intent_recognizer,
)


ROOT = Path(__file__).resolve().parents[3]


def test_intent_layer_package_exports_recognition_components() -> None:
    assert RuleBasedIntentRecognizer.__name__ == "RuleBasedIntentRecognizer"
    assert EmbeddingIntentRecognizer.__name__ == "EmbeddingIntentRecognizer"
    assert RagIntentEmbeddingStore.__name__ == "RagIntentEmbeddingStore"
    assert FallbackEmbeddingStore.__name__ == "FallbackEmbeddingStore"
    assert callable(get_hybrid_intent_recognizer)


def test_legacy_intent_modules_and_docs_are_not_kept() -> None:
    assert importlib.util.find_spec("services.cypher_generator_agent.app.intent_recognition") is None
    assert importlib.util.find_spec("services.cypher_generator_agent.app.intent_evaluation") is None
    assert importlib.util.find_spec("services.cypher_generator_agent.app.intent_vector_store") is None
    assert not (ROOT / "services/cypher_generator_agent/docs/intent-classification.md").exists()
    assert not (ROOT / "services/cypher_generator_agent/docs/intent-recognition-stage-design.md").exists()


def test_legacy_semantic_view_pipeline_files_are_not_kept() -> None:
    legacy_modules = (
        "cypher_renderer",
        "graph_semantic_view",
        "knowledge_context",
        "knowledge_selection",
        "logical_planner",
        "parser",
        "preflight",
        "prompt_runtime",
        "semantic_alignment",
        "semantic_cypher_preflight",
        "semantic_pipeline",
        "semantic_query",
        "semantic_view_matching",
    )
    for module_name in legacy_modules:
        assert importlib.util.find_spec(f"services.cypher_generator_agent.app.{module_name}") is None

    legacy_paths = (
        "services/cypher_generator_agent/README.md",
        "services/cypher_generator_agent/docs/cypher-generator-agent-design.md",
        "services/cypher_generator_agent/docs/graph-semantic-view-design.md",
        "services/cypher_generator_agent/docs/semantic-view-design.md",
        "services/cypher_generator_agent/docs/semantic-view-disambiguation-todo.md",
        "services/cypher_generator_agent/resources/semantic_views/network_graph_semantic_view.yaml",
        "services/cypher_generator_agent/resources/semantic_views/network_graph_semantic_model.yaml",
    )
    for relative_path in legacy_paths:
        assert not (ROOT / relative_path).exists()
