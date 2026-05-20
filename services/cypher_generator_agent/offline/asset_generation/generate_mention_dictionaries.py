from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.cypher_generator_agent.offline.asset_generation.validate_mention_dictionaries import validate_dictionaries


OUTPUT_FILES = (
    "business_objects.yaml",
    "attributes.yaml",
    "attribute_values.yaml",
    "relation_predicates.yaml",
    "operation_intents.yaml",
    "synonyms.yaml",
    "uncertain.yaml",
)


def generate_dictionaries(*, schema_path: Path, rules_path: Path, output_dir: Path) -> dict[str, Any]:
    schema = _load_schema(schema_path)
    rules = _load_rules(rules_path)
    output_dir.mkdir(parents=True, exist_ok=True)

    documents = {
        "business_objects.yaml": _document(
            schema_path,
            "Business object mention dictionary for first-stage mention extraction.",
            _business_objects(schema, rules),
        ),
        "attributes.yaml": _document(
            schema_path,
            "Attribute mention dictionary for schema-backed object properties.",
            _attributes(schema, rules),
        ),
        "attribute_values.yaml": _document(
            schema_path,
            "Attribute value mention dictionary for enum-like values declared by schema comments.",
            _attribute_values(schema, rules),
        ),
        "relation_predicates.yaml": _document(
            schema_path,
            "Relation predicate mention dictionary for graph edges and join paths.",
            _relations(schema, rules),
        ),
        "operation_intents.yaml": _document(
            schema_path,
            "Operation intent mention dictionary for first-stage operation cue extraction.",
            list(rules.get("operation_intents", [])),
        ),
        "synonyms.yaml": _document(
            schema_path,
            "Scoped synonym groups for mention normalization.",
            list(rules.get("synonyms", [])),
        ),
        "uncertain.yaml": {
            "version": 1,
            "source_schema": _display_path(schema_path),
            "description": "Items that need human review before entering the primary mention dictionaries.",
            "entries": _uncertain_entries(schema, rules),
        },
    }
    for filename in OUTPUT_FILES:
        _write_yaml(output_dir / filename, documents[filename])
    validation = validate_dictionaries(schema_path=schema_path, dict_dir=output_dir)
    return {
        "output_dir": str(output_dir),
        "files_written": len(OUTPUT_FILES),
        "canonical_id_count": validation["canonical_id_count"],
    }


def _business_objects(schema: list[dict[str, Any]], rules: dict[str, Any]) -> list[dict[str, Any]]:
    overrides = rules.get("objects", {})
    entries: list[dict[str, Any]] = []
    for item in _vertices(schema):
        label = str(item["label"])
        override = overrides.get(label, {})
        surface_forms = _unique([label, *override.get("surface_forms", [])])
        entries.append(
            {
                "canonical_id": label,
                "mention_type": "business_object",
                "surface_forms": surface_forms,
                "description": override.get("description") or item.get("description") or f"{label} business object.",
                "schema_table": label,
                "ontology_class": override.get("ontology_class") or label,
            }
        )
    return entries


def _attributes(schema: list[dict[str, Any]], rules: dict[str, Any]) -> list[dict[str, Any]]:
    overrides = rules.get("attributes", {})
    objects = rules.get("objects", {})
    include_ids = set(rules.get("include_id_attributes", []))
    entries: list[dict[str, Any]] = []
    for item in _vertices(schema):
        label = str(item["label"])
        object_forms = objects.get(label, {}).get("surface_forms", [label])
        object_zh = object_forms[0] if object_forms else label
        for prop in item.get("properties", []):
            name = str(prop["name"])
            canonical_id = f"{label}.{name}"
            if name == item.get("primary") and canonical_id not in include_ids:
                continue
            override = overrides.get(canonical_id, {})
            field_forms = _field_surface_forms(label, object_zh, prop, override)
            entries.append(
                {
                    "canonical_id": canonical_id,
                    "mention_type": "attribute",
                    "surface_forms": field_forms,
                    "description": override.get("description") or prop.get("description") or f"{label}.{name} attribute.",
                    "parent_object": label,
                    "column": name,
                    "value_type": prop.get("type"),
                    "belongs_to_hint": override.get("belongs_to_hint") or [label],
                }
            )
    return entries


def _attribute_values(schema: list[dict[str, Any]], rules: dict[str, Any]) -> list[dict[str, Any]]:
    aliases = rules.get("attribute_value_aliases", {})
    entries: list[dict[str, Any]] = []
    for item in _vertices(schema):
        label = str(item["label"])
        for prop in item.get("properties", []):
            field = f"{label}.{prop['name']}"
            values = _enum_values_from_description(str(prop.get("description") or ""))
            values.extend(aliases.get(field, {}).keys())
            for value in _unique(values):
                alias_config = aliases.get(field, {}).get(value, {})
                enum_name = alias_config.get("enum_name") or f"{label}{_pascal(str(prop['name']))}"
                surface_forms = _unique([value, *alias_config.get("surface_forms", [])])
                entries.append(
                    {
                        "canonical_id": f"{enum_name}.{value}",
                        "mention_type": "attribute_value",
                        "surface_forms": surface_forms,
                        "description": alias_config.get("description") or f"{field} value {value}.",
                        "constrains_field": field,
                        "raw_value": value,
                    }
                )
    return entries


def _relations(schema: list[dict[str, Any]], rules: dict[str, Any]) -> list[dict[str, Any]]:
    overrides = rules.get("relations", {})
    entries: list[dict[str, Any]] = []
    for item in _edges(schema):
        edge = str(item["label"])
        override = overrides.get(edge, {})
        for constraint in item.get("constraints", []):
            domain, range_ = constraint
            role = override.get("role", _role_from_edge(edge))
            entry = {
                "canonical_id": f"REL_{edge}",
                "mention_type": "relation_predicate",
                "surface_forms": _unique([edge, edge.lower(), *override.get("surface_forms", [])]),
                "description": override.get("description") or item.get("description") or f"{edge} relation.",
                "domain": domain,
                "range": range_,
                "join_path": [{"edge": edge, "from": domain, "to": range_, "direction": "out"}],
                "is_symmetric": bool(override.get("is_symmetric", False)),
            }
            if role is not None:
                entry["role"] = role
            entries.append(entry)
    return entries


def _uncertain_entries(schema: list[dict[str, Any]], rules: dict[str, Any]) -> list[dict[str, Any]]:
    entries = list(rules.get("uncertain_entries", []))
    known = {entry.get("candidate_id") for entry in entries}
    for item in _edges(schema):
        edge = str(item["label"])
        for prop in item.get("properties", []):
            candidate_id = f"UNC_EdgeProperty_{edge}_{prop['name']}"
            if candidate_id in known:
                continue
            entries.append(
                {
                    "candidate_id": candidate_id,
                    "issue_type": "modeling_gap",
                    "evidence": [f"schema.json defines edge property {edge}.{prop['name']}."],
                    "judgement": "Review whether this edge property needs a dedicated relation-attribute dictionary.",
                }
            )
    return entries


def _document(schema_path: Path, description: str, entries: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "version": 1,
        "source_schema": _display_path(schema_path),
        "description": description,
        "entries": entries,
    }


def _field_surface_forms(label: str, object_zh: str, prop: dict[str, Any], override: dict[str, Any]) -> list[str]:
    name = str(prop["name"])
    field_zh = override.get("name_zh") or _PROPERTY_ZH.get(name)
    forms = [name]
    if field_zh:
        forms.extend([f"{object_zh}{field_zh}", field_zh])
    description = str(prop.get("description") or "")
    forms.extend(override.get("surface_forms", []))
    return _unique(forms)


def _enum_values_from_description(description: str) -> list[str]:
    if "|" not in description:
        return []
    if "pattern" in description.lower():
        return []
    return [item.strip() for item in description.split("|") if item.strip()]


def _role_from_edge(edge: str) -> str | None:
    if edge.endswith("_SRC"):
        return "source"
    if edge.endswith("_DST"):
        return "destination"
    if edge == "PATH_THROUGH":
        return "path_through"
    return None


def _vertices(schema: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [item for item in schema if item.get("type") == "VERTEX"]


def _edges(schema: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [item for item in schema if item.get("type") == "EDGE"]


def _load_schema(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"{path} must contain a schema list")
    return payload


def _load_rules(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a mapping")
    return payload


def _write_yaml(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")


def _unique(values: list[Any]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _split_pascal(value: str) -> str:
    chars: list[str] = []
    for index, char in enumerate(value):
        if index > 0 and char.isupper() and not value[index - 1].isupper():
            chars.append(" ")
        chars.append(char)
    return "".join(chars)


def _pascal(value: str) -> str:
    return "".join(part[:1].upper() + part[1:] for part in value.split("_") if part)


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(Path.cwd()))
    except ValueError:
        return str(path)


_PROPERTY_ZH = {
    "id": "ID",
    "ip_address": "IP地址",
    "location": "位置",
    "model": "型号",
    "name": "名称",
    "software_version": "软件版本",
    "elem_type": "类型",
    "vendor": "厂商",
    "ietf_category": "IETF分类",
    "standard": "标准",
    "version": "版本",
    "bandwidth": "带宽",
    "latency": "时延",
    "ietf_standard": "IETF标准",
    "quality_of_service": "服务质量",
    "speed": "速率",
    "mac_address": "MAC地址",
    "status": "状态",
    "vlan_id": "VLAN",
    "bandwidth_capacity": "带宽容量",
    "length": "长度",
    "wavelength": "波长",
    "mtu": "MTU",
    "admin_status": "管理状态",
    "protocol": "协议",
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate mention dictionaries from schema.json and fixed rules.")
    parser.add_argument("--schema", type=Path, required=True)
    parser.add_argument("--rules", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    summary = generate_dictionaries(schema_path=args.schema, rules_path=args.rules, output_dir=args.out)
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(f"files_written={summary['files_written']}")
        print(f"canonical_id_count={summary['canonical_id_count']}")
        print(f"output_dir={summary['output_dir']}")


if __name__ == "__main__":
    main()
