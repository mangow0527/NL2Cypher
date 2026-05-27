from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml
from pydantic import ValidationError

from .model import GraphSemanticModel
from .registry import GraphSemanticRegistry
from .validator import (
    GraphModelValidationError,
    GraphModelValidationIssue,
    GraphModelValidationResult,
    validate_graph_model,
)


@dataclass(frozen=True)
class GraphModelLoadResult:
    registry: GraphSemanticRegistry
    model_checksum: str
    validation_result: GraphModelValidationResult


def load_graph_semantic_model(source: str | Path | Mapping[str, Any]) -> GraphModelLoadResult:
    payload = _extract_model_payload(_load_source(source))
    try:
        model = GraphSemanticModel.model_validate(payload)
    except ValidationError as exc:
        raise GraphModelValidationError(_validation_result_from_pydantic(exc)) from exc

    validation_result = validate_graph_model(model)
    if not validation_result.is_valid:
        raise GraphModelValidationError(validation_result)

    return GraphModelLoadResult(
        registry=GraphSemanticRegistry(model),
        model_checksum=_model_checksum(model),
        validation_result=validation_result,
    )


def _load_source(source: str | Path | Mapping[str, Any]) -> Mapping[str, Any]:
    if isinstance(source, Mapping):
        return source
    path = Path(source)
    with path.open(encoding="utf-8") as file:
        document = yaml.safe_load(file)
    if not isinstance(document, Mapping):
        raise GraphModelValidationError(
            GraphModelValidationResult(
                is_valid=False,
                errors=[
                    GraphModelValidationIssue(
                        code="invalid_document",
                        message="graph semantic model document must be a mapping",
                        location="$",
                    )
                ],
            )
        )
    return document


def _extract_model_payload(document: Mapping[str, Any]) -> Mapping[str, Any]:
    semantic_model = document.get("semantic_model")
    if semantic_model is None:
        return document
    if not isinstance(semantic_model, list) or len(semantic_model) != 1:
        raise GraphModelValidationError(
            GraphModelValidationResult(
                is_valid=False,
                errors=[
                    GraphModelValidationIssue(
                        code="invalid_semantic_model_wrapper",
                        message="semantic_model wrapper must contain exactly one model",
                        location="semantic_model",
                    )
                ],
            )
        )
    model_payload = semantic_model[0]
    if not isinstance(model_payload, Mapping):
        raise GraphModelValidationError(
            GraphModelValidationResult(
                is_valid=False,
                errors=[
                    GraphModelValidationIssue(
                        code="invalid_semantic_model_wrapper",
                        message="semantic_model item must be a mapping",
                        location="semantic_model[0]",
                    )
                ],
            )
        )
    return model_payload


def _validation_result_from_pydantic(exc: ValidationError) -> GraphModelValidationResult:
    return GraphModelValidationResult(
        is_valid=False,
        errors=[
            GraphModelValidationIssue(
                code="model_parse_error",
                message=f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}",
                location=".".join(str(part) for part in error["loc"]),
            )
            for error in exc.errors()
        ],
    )


def _model_checksum(model: GraphSemanticModel) -> str:
    canonical_json = json.dumps(
        model.model_dump(mode="json", by_alias=True, exclude_none=True),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
