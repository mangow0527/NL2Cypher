from __future__ import annotations

from pathlib import Path
import shutil

import pytest
import yaml

from tools.generate_mention_dictionaries import generate_dictionaries
from tools.validate_mention_dictionaries import DictionaryValidationError, validate_dictionaries


REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = REPO_ROOT / "services/testing_agent/docs/reference/schema.json"
RULES_PATH = (
    REPO_ROOT / "services/cypher_generator_agent/resources/offline/lexical_asset_generation/generation_rules.yaml"
)
DICT_DIR = REPO_ROOT / "services/cypher_generator_agent/resources/runtime/lexical"


def test_validate_current_mention_dictionaries_against_schema() -> None:
    report = validate_dictionaries(schema_path=SCHEMA_PATH, dict_dir=DICT_DIR)

    assert report["canonical_id_count"] >= 100
    assert report["files_checked"] == 6
    assert report["errors"] == []


def test_generate_dictionaries_from_schema_and_rules(tmp_path: Path) -> None:
    output_dir = tmp_path / "lexical"

    summary = generate_dictionaries(
        schema_path=SCHEMA_PATH,
        rules_path=RULES_PATH,
        output_dir=output_dir,
    )

    assert summary["files_written"] == 7
    assert summary["canonical_id_count"] == 128
    assert validate_dictionaries(schema_path=SCHEMA_PATH, dict_dir=output_dir)["errors"] == []
    assert _canonical_ids(output_dir) == _canonical_ids(DICT_DIR)

    objects = _entries_by_source(output_dir, "business_objects")
    assert objects["Service"]["schema_table"] == "Service"
    assert "业务" in objects["Service"]["surface_forms"]

    attributes = _entries_by_source(output_dir, "attributes")
    assert "NetworkElement.id" in attributes
    assert attributes["Tunnel.ietf_standard"]["column"] == "ietf_standard"
    assert "HAS_PORT.admin_status" not in attributes

    values = _entries_by_source(output_dir, "attribute_values")
    assert values["ServiceQuality.Gold"]["raw_value"] == "Gold"
    assert "金牌" in values["ServiceQuality.Gold"]["surface_forms"]

    relations = _entries_by_source(output_dir, "relation_predicates")
    assert relations["REL_TUNNEL_SRC"]["role"] == "source"
    assert relations["REL_TUNNEL_DST"]["role"] == "destination"
    assert relations["REL_TUNNEL_SRC"]["join_path"] == [
        {"edge": "TUNNEL_SRC", "from": "Tunnel", "to": "NetworkElement", "direction": "out"}
    ]
    assert "返回" not in _entries_by_source(output_dir, "operation_intents")["OP_QUERY"]["surface_forms"]
    assert "up" not in attributes["Port.status"]["surface_forms"]
    assert "ERO" not in relations["REL_PATH_THROUGH"]["surface_forms"]
    assert not (DICT_DIR / "generation_rules.yaml").exists()

    uncertain = yaml.safe_load((output_dir / "uncertain.yaml").read_text(encoding="utf-8"))
    assert any(item["candidate_id"] == "UNC_EdgeProperty_HAS_PORT_admin_status" for item in uncertain["entries"])


def test_validate_rejects_attribute_not_in_schema(tmp_path: Path) -> None:
    work_dir = tmp_path / "dicts"
    shutil.copytree(DICT_DIR, work_dir)
    attributes_path = work_dir / "dictionaries" / "attributes.yaml"
    payload = yaml.safe_load(attributes_path.read_text(encoding="utf-8"))
    attribute_entry = next(item for item in payload["entries"] if item.get("canonical_id") == "NetworkElement.id")
    attribute_entry["column"] = "not_in_schema"
    attributes_path.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")

    with pytest.raises(DictionaryValidationError, match="NetworkElement.not_in_schema"):
        validate_dictionaries(schema_path=SCHEMA_PATH, dict_dir=work_dir)


def _entries_by_id(path: Path) -> dict[str, dict[str, object]]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {item["canonical_id"]: item for item in payload["entries"]}


def _entries_by_source(dict_dir: Path, source: str) -> dict[str, dict[str, object]]:
    return _entries_by_id(dict_dir / "dictionaries" / f"{source}.yaml")


def _canonical_ids(dict_dir: Path) -> set[str]:
    ids: set[str] = set()
    for path in sorted((dict_dir / "dictionaries").glob("*.yaml")):
        ids.update(_entries_by_id(path))
    return ids
