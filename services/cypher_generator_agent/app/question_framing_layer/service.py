from __future__ import annotations

import re
from typing import Any, Protocol

from .models import QuestionAtom, QuestionFramingRole, QuestionFramingTrace, normalize_question_framing_role


class CompletionClient(Protocol):
    def complete(self, prompt: str) -> str:
        ...


_RETRIEVAL_PLAN_VERSION = "question_framing_retrieval_plan_v1"

_GENERIC_CONNECTOR_TERMS: tuple[str, ...] = (
    "连接关系",
    "对应",
    "相关",
    "关联",
    "连接",
    "关系",
    "之间",
    "双方",
    "各自",
)

_PATH_ACTION_TERMS: tuple[str, ...] = (
    "使用的",
    "使用",
    "经过的",
    "经过",
    "连接到",
    "连接的",
    "连接",
    "关联到",
    "关联的",
    "关联",
    "对应的",
    "对应",
    "包含的",
    "包含",
)

_PATH_LEADING_NOISE_TERMS: tuple[str, ...] = (
    "及其",
    "其",
)

_PATH_RETURN_MARKER_TERMS: tuple[str, ...] = (
    "并返回",
    "返回",
    "输出",
    "列出",
    "展示",
)

_ATTRIBUTE_HINT_TERMS: tuple[str, ...] = (
    "IETF标准",
    "元素类型",
    "节点详情",
    "延迟值",
    "ID",
    "Id",
    "id",
    "名称",
    "名字",
    "属性",
    "状态",
    "类型",
    "地址",
    "IP",
    "ip",
    "位置",
    "标准",
    "服务质量",
    "延迟",
    "时延",
    "带宽",
)


QUESTION_FRAMING_PROMPT_TEMPLATE = """请把下面的问题拆成几个原子性小问题，并标明每个小问题在整个问题里负责什么。
我们最终会把问题转换成图数据库 Cypher 查询，所以你只需要帮助理解问题结构。
不要生成查询语句，不要使用数据库字段名，不要解释原因。

角色只能使用下面这些：
- 找什么对象
- 用什么条件筛选
- 通过什么关系继续找
- 最后返回什么
- 是否涉及统计、排序或时间
- 不确定

要求：
1. 每个原子小问题只表达一个查询动作。
2. 原子小问题必须尽量使用原问题里的连续短语，不要用“该对象”“这些服务”等指代词替换原词。
3. 不要补充原问题没有的信息。
4. 一个原子小问题可以有多个角色，用“ + ”连接。
5. 如果问题很简单，也可以只拆成一个原子小问题。
6. 如果不确定某个片段的作用，角色写“不确定”。
7. “A 与 B 之间的连接/关系/关联/连接关系”表示两类对象之间的关系路径，标为“通过什么关系继续找”，不要把“连接/关系/之间”拆成要返回的对象或字段。
8. “通过什么关系继续找”只描述从一个对象到另一个对象的路径动作和对象短语。
9. 如果一个片段同时包含“关系动作”和“最终要展示的字段”，要拆开，不要合成一个原子问题。
10. 出现“返回/并返回/输出/列出”后面的内容，优先标为“最后返回什么”，不要继续并入 RELATION_PATH。

输出格式必须是：
原子问题：
1. xxx ｜ 角色
2. xxx ｜ 角色

示例1：
问题：查询名称为 Service_002 的服务的 ID、名称和服务质量
原子问题：
1. 名称为 Service_002 的服务 ｜ 找什么对象 + 用什么条件筛选
2. ID、名称和服务质量 ｜ 最后返回什么

示例2：
问题：查询金牌服务经过的隧道及其源网元，返回隧道的IETF标准和源网元的IP地址
原子问题：
1. 金牌服务 ｜ 找什么对象 + 用什么条件筛选
2. 经过的隧道及其源网元 ｜ 通过什么关系继续找
3. 隧道的IETF标准和源网元的IP地址 ｜ 最后返回什么

示例3：
问题：查询所有服务与隧道之间的连接关系，并返回双方的元素类型
原子问题：
1. 所有服务与隧道之间的连接关系 ｜ 找什么对象 + 通过什么关系继续找
2. 双方的元素类型 ｜ 最后返回什么

反例修正：
问题：查询对象A的名称及其使用的对象B的名称和标准
不要这样拆：
1. 对象A的名称及其使用的对象B的名称和标准 ｜ 通过什么关系继续找
应该这样拆：
1. 对象A的名称 ｜ 最后返回什么
2. 使用的对象B ｜ 通过什么关系继续找
3. 对象B的名称和标准 ｜ 最后返回什么

问题：{question}
原子问题：
"""


class QuestionFramingService:
    def __init__(self, *, client: CompletionClient | None, enabled: bool = True) -> None:
        self._client = client
        self._enabled = enabled

    def run(self, question: str) -> QuestionFramingTrace:
        if not self._enabled:
            return QuestionFramingTrace.empty(question, reason="question_framing_disabled")
        if self._client is None:
            return QuestionFramingTrace.empty(question, reason="question_framing_llm_unavailable")
        prompt = QUESTION_FRAMING_PROMPT_TEMPLATE.format(question=question)
        try:
            raw_response = self._client.complete(prompt)
        except Exception as exc:  # pragma: no cover - defensive runtime degradation
            return QuestionFramingTrace.empty(question, reason=f"question_framing_llm_error:{type(exc).__name__}")
        return _parse_question_framing_response(question, raw_response)


def _parse_question_framing_response(question: str, raw_response: str) -> QuestionFramingTrace:
    atoms: list[QuestionAtom] = []
    diagnostics: list[str] = []
    for line in raw_response.splitlines():
        parsed = _parse_atom_line(line)
        if parsed is None:
            continue
        atom_text, raw_role_text = parsed
        roles = _parse_roles(raw_role_text)
        span = _find_atom_span(question, atom_text)
        if span is None:
            diagnostics.append(f"span_not_found:{atom_text}")
            span_start = None
            span_end = None
            confidence = 0.55
        else:
            span_start, span_end = span
            confidence = 0.9
        atoms.append(
            QuestionAtom(
                atom_id=f"QA{len(atoms) + 1}",
                text=atom_text,
                roles=roles,
                span_start=span_start,
                span_end=span_end,
                confidence=confidence,
                raw_role_text=raw_role_text,
            )
        )
    if not atoms:
        diagnostics.append("no_parseable_question_atoms")
    retrieval_plan = _build_retrieval_plan(question, tuple(atoms))
    return QuestionFramingTrace(
        question=question,
        raw_response=raw_response,
        atoms=tuple(atoms),
        retrieval_plan=retrieval_plan,
        diagnostics=tuple(diagnostics),
        enabled=bool(atoms),
    )


def _parse_atom_line(line: str) -> tuple[str, str] | None:
    stripped = line.strip()
    if not stripped or stripped == "原子问题：":
        return None
    match = re.match(r"^(?:[-*]|\d+[.)、])?\s*(?P<text>.+?)\s*[|｜]\s*(?P<roles>.+?)\s*$", stripped)
    if match is None:
        return None
    atom_text = match.group("text").strip(" 　。；;：:")
    raw_role_text = match.group("roles").strip(" 　。；;：:")
    if not atom_text or not raw_role_text:
        return None
    return atom_text, raw_role_text


def _parse_roles(raw_role_text: str) -> tuple[QuestionFramingRole, ...]:
    known_roles = _known_roles_in_text(raw_role_text)
    if known_roles:
        return known_roles
    parts = tuple(part for part in re.split(r"\s*(?:\+|、|,|，|/|和)\s*", raw_role_text) if part.strip())
    roles: list[QuestionFramingRole] = []
    for part in parts or (raw_role_text,):
        role = normalize_question_framing_role(part)
        if role not in roles:
            roles.append(role)
    if not roles:
        roles.append(QuestionFramingRole.UNKNOWN)
    if len(roles) > 1 and QuestionFramingRole.UNKNOWN in roles:
        roles = [role for role in roles if role is not QuestionFramingRole.UNKNOWN]
    return tuple(roles)


def _known_roles_in_text(raw_role_text: str) -> tuple[QuestionFramingRole, ...]:
    positions: list[tuple[int, QuestionFramingRole]] = []
    for role in QuestionFramingRole:
        label_index = raw_role_text.find(role.label)
        value_index = raw_role_text.find(role.value)
        indexes = [index for index in (label_index, value_index) if index >= 0]
        if indexes:
            positions.append((min(indexes), role))
    return tuple(role for _, role in sorted(positions, key=lambda item: item[0]))


def _find_atom_span(question: str, atom_text: str) -> tuple[int, int] | None:
    start = question.find(atom_text)
    if start >= 0:
        return (start, start + len(atom_text))
    compact_question = re.sub(r"\s+", "", question)
    compact_atom = re.sub(r"\s+", "", atom_text)
    compact_start = compact_question.find(compact_atom)
    if compact_start < 0:
        return _find_stripped_span(question, atom_text)
    mapping = _compact_index_mapping(question)
    if compact_start >= len(mapping):
        return _find_stripped_span(question, atom_text)
    compact_end = compact_start + len(compact_atom) - 1
    if compact_end >= len(mapping):
        return _find_stripped_span(question, atom_text)
    return (mapping[compact_start], mapping[compact_end] + 1)


def _compact_index_mapping(text: str) -> tuple[int, ...]:
    return tuple(index for index, char in enumerate(text) if not char.isspace())


def _find_stripped_span(question: str, atom_text: str) -> tuple[int, int] | None:
    stripped = re.sub(r"^(?:查询|查找|找出|找到|返回|列出|统计|筛选|限定)", "", atom_text).strip()
    stripped = re.sub(r"^(?:该|这些|所有|全部)", "", stripped).strip()
    stripped = re.sub(r"(?:是什么|有哪些|是多少)$", "", stripped).strip()
    if not stripped or stripped == atom_text:
        return None
    start = question.find(stripped)
    if start >= 0:
        return (start, start + len(stripped))
    return None


def _build_retrieval_plan(question: str, atoms: tuple[QuestionAtom, ...]) -> dict[str, Any]:
    plan_diagnostics: list[str] = []
    path_queries: list[dict[str, Any]] = []
    for path_index, path_atom in enumerate(atoms):
        if not path_atom.has_role(QuestionFramingRole.RELATION_PATH):
            continue
        source_atoms = tuple(atom for atom in atoms[:path_index] if atom.has_role(QuestionFramingRole.FIND_OBJECT))
        query_atoms = _dedupe_atoms((*source_atoms, path_atom))
        source_text, source_diagnostics = _sanitized_source_text(source_atoms)
        path_text, path_diagnostic = _sanitized_path_text(path_atom)
        plan_diagnostics.extend(source_diagnostics)
        if path_diagnostic is not None:
            plan_diagnostics.append(path_diagnostic)
        retrieval_text = _join_non_empty((source_text, path_text))
        path_queries.append(
            {
                "query_id": f"PQ{len(path_queries) + 1}",
                "atom_ids": [atom.atom_id for atom in query_atoms],
                "source_text": source_text,
                "path_text": path_text,
                "retrieval_text": retrieval_text,
                "roles": _roles_for_atoms(query_atoms),
                "grounding_spans": _spans_for_atoms(query_atoms),
                "generic_connectors": _generic_connectors_in_text(retrieval_text),
            }
        )
    if atoms and not path_queries:
        plan_diagnostics.append("no_relation_path_atoms")

    return_targets = tuple(atom for atom in atoms if atom.has_role(QuestionFramingRole.RETURN_CONTENT))
    metric_atoms = tuple(atom for atom in atoms if atom.has_role(QuestionFramingRole.AGG_SORT_TIME))
    attribute_atoms = tuple(atom for atom in return_targets if _looks_like_attribute_atom(atom.text))
    all_text = " ".join(atom.text for atom in atoms)
    return {
        "version": _RETRIEVAL_PLAN_VERSION,
        "question": question,
        "path_queries": path_queries,
        "return_targets": [_target_payload(atom) for atom in return_targets],
        "attribute_queries": [_target_payload(atom) for atom in attribute_atoms],
        "metric_queries": [_target_payload(atom) for atom in metric_atoms],
        "generic_connectors": _generic_connectors_in_text(all_text),
        "diagnostics": plan_diagnostics,
    }


def _dedupe_atoms(atoms: tuple[QuestionAtom, ...]) -> tuple[QuestionAtom, ...]:
    selected: list[QuestionAtom] = []
    seen: set[str] = set()
    for atom in atoms:
        if atom.atom_id in seen:
            continue
        selected.append(atom)
        seen.add(atom.atom_id)
    return tuple(selected)


def _join_atom_texts(atoms: tuple[QuestionAtom, ...]) -> str:
    return _join_non_empty(tuple(atom.text for atom in atoms))


def _join_non_empty(values: tuple[str, ...]) -> str:
    return " ".join(value.strip() for value in values if value and value.strip())


def _roles_for_atoms(atoms: tuple[QuestionAtom, ...]) -> list[str]:
    roles: list[str] = []
    for atom in atoms:
        for role in atom.roles:
            if role.value not in roles:
                roles.append(role.value)
    return roles


def _spans_for_atoms(atoms: tuple[QuestionAtom, ...]) -> list[list[int]]:
    return [list(atom.span) for atom in atoms if atom.span is not None]


def _target_payload(atom: QuestionAtom) -> dict[str, Any]:
    return {
        "atom_id": atom.atom_id,
        "text": atom.text,
        "retrieval_text": atom.text,
        "span": list(atom.span) if atom.span is not None else None,
        "roles": [role.value for role in atom.roles],
    }


def _looks_like_attribute_atom(text: str) -> bool:
    return any(term in text for term in _ATTRIBUTE_HINT_TERMS)


def _sanitized_source_text(atoms: tuple[QuestionAtom, ...]) -> tuple[str, list[str]]:
    texts: list[str] = []
    diagnostics: list[str] = []
    for atom in atoms:
        cleaned = _trim_return_attribute_from_source_text(atom.text)
        texts.append(cleaned)
        if cleaned != atom.text:
            diagnostics.append(f"source_text_trimmed_return_attribute:{atom.atom_id}:{atom.text}->{cleaned}")
    return _join_non_empty(tuple(texts)), diagnostics


def _sanitized_path_text(atom: QuestionAtom) -> tuple[str, str | None]:
    cleaned = _strip_return_marker_tail(atom.text)
    cleaned = _strip_path_leading_noise(cleaned)
    cleaned = _strip_attribute_prefix_before_path_action(cleaned)
    cleaned = _strip_path_leading_noise(cleaned)
    cleaned = _trim_return_attribute_tail(cleaned)
    cleaned = _strip_path_leading_noise(cleaned)
    if not cleaned:
        cleaned = atom.text
    if cleaned != atom.text:
        return cleaned, f"path_text_trimmed_return_attribute:{atom.atom_id}:{atom.text}->{cleaned}"
    return cleaned, None


def _trim_return_attribute_from_source_text(text: str) -> str:
    stripped = text.strip()
    for term in _attribute_terms_by_length():
        for suffix in (f"的{term}", term):
            if not stripped.endswith(suffix):
                continue
            prefix = stripped[: -len(suffix)].rstrip(" 的")
            if prefix:
                return prefix
    return stripped


def _strip_return_marker_tail(text: str) -> str:
    stripped = text.strip()
    indexes = [stripped.find(term) for term in _PATH_RETURN_MARKER_TERMS if stripped.find(term) > 0]
    if indexes:
        return stripped[: min(indexes)].strip(" ，,；;")
    return stripped


def _strip_path_leading_noise(text: str) -> str:
    stripped = text.strip()
    changed = True
    while changed:
        changed = False
        for term in _PATH_LEADING_NOISE_TERMS:
            if stripped.startswith(term):
                stripped = stripped[len(term) :].strip()
                changed = True
    return stripped


def _strip_attribute_prefix_before_path_action(text: str) -> str:
    earliest_action_index: int | None = None
    for term in _PATH_ACTION_TERMS:
        index = text.find(term)
        if index > 0 and (earliest_action_index is None or index < earliest_action_index):
            earliest_action_index = index
    if earliest_action_index is None:
        return text
    prefix = text[:earliest_action_index]
    if _looks_like_attribute_atom(prefix):
        return text[earliest_action_index:].strip()
    return text


def _trim_return_attribute_tail(text: str) -> str:
    if not _has_path_action(text):
        return text
    for match in _attribute_tail_pattern().finditer(text):
        candidate = text[: match.start()].rstrip(" 的")
        if candidate:
            return candidate
    return text


def _has_path_action(text: str) -> bool:
    return any(term in text for term in _PATH_ACTION_TERMS)


def _attribute_terms_by_length() -> tuple[str, ...]:
    return tuple(sorted(_ATTRIBUTE_HINT_TERMS, key=len, reverse=True))


def _attribute_tail_pattern() -> re.Pattern[str]:
    terms = "|".join(re.escape(term) for term in _attribute_terms_by_length())
    return re.compile(rf"(?:的)?(?:{terms})(?:[和及、,，].*)?$")


def _generic_connectors_in_text(text: str) -> list[str]:
    matches: list[tuple[int, int, str]] = []
    for term in _GENERIC_CONNECTOR_TERMS:
        for match in re.finditer(re.escape(term), text):
            matches.append((match.start(), match.end(), term))
    selected: list[tuple[int, int, str]] = []
    for start, end, term in sorted(matches, key=lambda item: (item[0], -(item[1] - item[0]), item[2])):
        if any(start >= selected_start and end <= selected_end for selected_start, selected_end, _ in selected):
            continue
        selected.append((start, end, term))
    connectors: list[str] = []
    for _, _, term in selected:
        if term not in connectors:
            connectors.append(term)
    return connectors
