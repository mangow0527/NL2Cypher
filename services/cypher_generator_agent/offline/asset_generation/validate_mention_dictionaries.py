from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import yaml


DICTIONARY_FILES: dict[str, set[str]] = {
    "business_objects.yaml": {"schema_table", "ontology_class"},
    "attributes.yaml": {"parent_object", "column", "value_type", "belongs_to_hint"},
    "attribute_values.yaml": {"constrains_field", "raw_value"},
    "relation_predicates.yaml": {"domain", "range", "join_path", "is_symmetric"},
    "operation_intents.yaml": {"intent"},
    "synonyms.yaml": {"members", "applied_to"},
}
REQUIRED_FIELDS = {"canonical_id", "mention_type", "surface_forms", "description"}


class DictionaryValidationError(ValueError):
    """Raised when mention dictionary assets do not match schema or contract."""


def validate_dictionaries(*, schema_path: Path, dict_dir: Path) -> dict[str, Any]:
    schema = _load_schema(schema_path)
    vertex_properties = _vertex_properties(schema)
    edge_constraints = _edge_constraints(schema)
    errors: list[str] = []
    canonical_ids: dict[str, str] = {}
    entries_by_file: dict[str, list[dict[str, Any]]] = {}

    for filename, extra_fields in DICTIONARY_FILES.items():
        path = dict_dir / filename
        payload = _load_yaml_mapping(path, errors)
        entries = payload.get("entries")
        if not isinstance(entries, list) or not entries:
            errors.append(f"{filename}: entries must be a non-empty list")
            entries = []
        entries_by_file[filename] = entries
        for index, entry in enumerate(entries, start=1):
            if not isinstance(entry, dict):
                errors.append(f"{filename}:{index}: entry must be a mapping")
                continue
            _validate_common_entry(filename, index, entry, extra_fields, canonical_ids, errors)

    _validate_business_objects(entries_by_file["business_objects.yaml"], vertex_properties, errors)
    _validate_attributes(entries_by_file["attributes.yaml"], vertex_properties, errors)
    _validate_attribute_values(entries_by_file["attribute_values.yaml"], vertex_properties, errors)
    _validate_relations(entries_by_file["relation_predicates.yaml"], edge_constraints, errors)
    _validate_synonyms(entries_by_file["synonyms.yaml"], canonical_ids, errors)
    _validate_uncertain(dict_dir / "uncertain.yaml", errors)

    if errors:
        raise DictionaryValidationError("\n".join(errors))
    return {
        "files_checked": len(DICTIONARY_FILES) + 1,
        "canonical_id_count": len(canonical_ids),
        "errors": [],
    }


def _validate_common_entry(
    filename: str,
    index: int,
    entry: dict[str, Any],
    extra_fields: set[str],
    canonical_ids: dict[str, str],
    errors: list[str],
) -> None:
    missing = (REQUIRED_FIELDS | extra_fields) - set(entry)
    if missing:
        errors.append(f"{filename}:{index}: missing fields {sorted(missing)}")
    canonical_id = entry.get("canonical_id")
    if not isinstance(canonical_id, str) or not canonical_id:
        errors.append(f"{filename}:{index}: canonical_id must be a non-empty string")
        return
    previous = canonical_ids.get(canonical_id)
    if previous is not None:
        errors.append(f"{filename}:{index}: duplicate canonical_id {canonical_id!r}; first seen at {previous}")
    canonical_ids[canonical_id] = f"{filename}:{index}"
    surface_forms = entry.get("surface_forms")
    if not isinstance(surface_forms, list) or not surface_forms or not all(isinstance(item, str) and item for item in surface_forms):
        errors.append(f"{filename}:{index}: surface_forms must be a non-empty list of strings")
    if not isinstance(entry.get("description"), str) or not entry["description"]:
        errors.append(f"{filename}:{index}: description must be a non-empty string")
    if filename == "business_objects.yaml" and not canonical_id[:1].isupper():
        errors.append(f"{filename}:{index}: object canonical_id must use PascalCase: {canonical_id}")
    if filename == "attributes.yaml" and "." not in canonical_id:
        errors.append(f"{filename}:{index}: attribute canonical_id must use Object.field: {canonical_id}")
    if filename == "relation_predicates.yaml" and not canonical_id.startswith("REL_"):
        errors.append(f"{filename}:{index}: relation canonical_id must start with REL_: {canonical_id}")
    if filename == "operation_intents.yaml" and not canonical_id.startswith("OP_"):
        errors.append(f"{filename}:{index}: operation canonical_id must start with OP_: {canonical_id}")
    if filename == "attribute_values.yaml" and "." not in canonical_id:
        errors.append(f"{filename}:{index}: value canonical_id must use EnumName.VALUE: {canonical_id}")


def _validate_business_objects(
    entries: list[dict[str, Any]],
    vertex_properties: dict[str, dict[str, dict[str, Any]]],
    errors: list[str],
) -> None:
    for entry in entries:
        schema_table = entry.get("schema_table")
        if schema_table not in vertex_properties:
            errors.append(f"business_objects.yaml: schema_table {schema_table!r} is not a vertex label")


def _validate_attributes(
    entries: list[dict[str, Any]],
    vertex_properties: dict[str, dict[str, dict[str, Any]]],
    errors: list[str],
) -> None:
    for entry in entries:
        parent = entry.get("parent_object")
        column = entry.get("column")
        if parent not in vertex_properties:
            errors.append(f"attributes.yaml: parent_object {parent!r} is not a vertex label")
            continue
        if column not in vertex_properties[parent]:
            errors.append(f"attributes.yaml: {parent}.{column} is not in schema")
            continue
        actual_type = vertex_properties[parent][column].get("type")
        if entry.get("value_type") != actual_type:
            errors.append(
                f"attributes.yaml: {parent}.{column} value_type mismatch: "
                f"dictionary={entry.get('value_type')!r}, schema={actual_type!r}"
            )


def _validate_attribute_values(
    entries: list[dict[str, Any]],
    vertex_properties: dict[str, dict[str, dict[str, Any]]],
    errors: list[str],
) -> None:
    for entry in entries:
        field = entry.get("constrains_field")
        if not isinstance(field, str) or "." not in field:
            errors.append(f"attribute_values.yaml: constrains_field must be Object.field: {field!r}")
            continue
        parent, column = field.split(".", 1)
        if parent not in vertex_properties or column not in vertex_properties[parent]:
            errors.append(f"attribute_values.yaml: constrains_field {field!r} is not in schema")


def _validate_relations(
    entries: list[dict[str, Any]],
    edge_constraints: dict[str, set[tuple[str, str]]],
    errors: list[str],
) -> None:
    for entry in entries:
        join_path = entry.get("join_path")
        if not isinstance(join_path, list) or not join_path:
            errors.append(f"relation_predicates.yaml: {entry.get('canonical_id')} join_path must be non-empty")
            continue
        for step in join_path:
            if not isinstance(step, dict):
                errors.append(f"relation_predicates.yaml: {entry.get('canonical_id')} join step must be mapping")
                continue
            edge = step.get("edge")
            from_label = step.get("from")
            to_label = step.get("to")
            expected = (from_label, to_label)
            if edge not in edge_constraints:
                errors.append(f"relation_predicates.yaml: edge {edge!r} is not in schema")
                continue
            if expected not in edge_constraints[edge]:
                errors.append(f"relation_predicates.yaml: {edge} does not allow {from_label}->{to_label}")


def _validate_synonyms(entries: list[dict[str, Any]], canonical_ids: dict[str, str], errors: list[str]) -> None:
    known = set(canonical_ids)
    for entry in entries:
        for field_name in ("members", "applied_to"):
            value = entry.get(field_name)
            if not isinstance(value, list) or not value:
                errors.append(f"synonyms.yaml: {entry.get('canonical_id')} {field_name} must be non-empty list")
        for target in entry.get("applied_to", []) or []:
            if target not in known:
                errors.append(f"synonyms.yaml: applied_to target {target!r} is not a known canonical_id")


def _validate_uncertain(path: Path, errors: list[str]) -> None:
    payload = _load_yaml_mapping(path, errors)
    entries = payload.get("entries")
    if not isinstance(entries, list):
        errors.append("uncertain.yaml: entries must be a list")
        return
    for index, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict):
            errors.append(f"uncertain.yaml:{index}: entry must be a mapping")
            continue
        for field in ("candidate_id", "issue_type", "evidence", "judgement"):
            if field not in entry:
                errors.append(f"uncertain.yaml:{index}: missing {field}")
        if not isinstance(entry.get("evidence"), list) or not entry.get("evidence"):
            errors.append(f"uncertain.yaml:{index}: evidence must be a non-empty list")


def _load_schema(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise DictionaryValidationError(f"{path} must contain a schema list")
    return payload


def _load_yaml_mapping(path: Path, errors: list[str]) -> dict[str, Any]:
    if not path.exists():
        errors.append(f"{path}: file does not exist")
        return {}
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        errors.append(f"{path}: file must contain a mapping")
        return {}
    return payload


def _vertex_properties(schema: list[dict[str, Any]]) -> dict[str, dict[str, dict[str, Any]]]:
    result: dict[str, dict[str, dict[str, Any]]] = {}
    for item in schema:
        if item.get("type") != "VERTEX":
            continue
        result[str(item["label"])] = {str(prop["name"]): prop for prop in item.get("properties", [])}
    return result


def _edge_constraints(schema: list[dict[str, Any]]) -> dict[str, set[tuple[str, str]]]:
    result: dict[str, set[tuple[str, str]]] = {}
    for item in schema:
        if item.get("type") != "EDGE":
            continue
        result[str(item["label"])] = {tuple(pair) for pair in item.get("constraints", [])}
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate generated mention dictionaries against schema.json.")
    parser.add_argument("--schema", type=Path, required=True)
    parser.add_argument("--dict-dir", type=Path, required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        report = validate_dictionaries(schema_path=args.schema, dict_dir=args.dict_dir)
    except DictionaryValidationError as exc:
        if args.json:
            print(json.dumps({"accepted": False, "errors": str(exc).splitlines()}, ensure_ascii=False, indent=2))
        else:
            print(str(exc))
        raise SystemExit(1) from exc
    if args.json:
        print(json.dumps({"accepted": True, **report}, ensure_ascii=False, indent=2))
    else:
        print(f"validation_ok canonical_id_count={report['canonical_id_count']}")


if __name__ == "__main__":
    main()
