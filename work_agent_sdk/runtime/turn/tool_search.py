from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Awaitable, Callable
from typing import Any

import work_agent_sdk.strings.runtime as strings
from work_agent_sdk.core.messages import ToolResult
from work_agent_sdk.core.tool import Tool
from work_agent_sdk.models.deferred_tools import TOOL_SEARCH

DEFAULT_LIMIT = 8
MAX_LIMIT = 20
DESCRIPTION = strings.TOOL_SEARCH_DESCRIPTION
PARAMETERS = {
    "type": "object",
    "properties": {
        "query": {"type": "string", "description": strings.TOOL_SEARCH_QUERY},
        "limit": {
            "type": "integer",
            "description": strings.TOOL_SEARCH_LIMIT.format(default=DEFAULT_LIMIT, limit=MAX_LIMIT),
        },
    },
    "required": ["query"],
    "additionalProperties": False,
}

STOP_WORDS = {"a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "in", "is", "it", "of", "on",
              "or", "that", "the", "this", "to", "with"}  # fmt: skip
CJK = re.compile(r"[㐀-鿿豈-﫿]+")
WORD = re.compile(r"[a-z0-9]+")


def _stem(term: str) -> str:
    if len(term) > 4 and term.endswith("ies"):
        return term[:-3] + "y"
    if len(term) > 4 and re.search(r"(ches|shes|sses|xes|zes)$", term):
        return term[:-2]
    if len(term) > 3 and term.endswith("s") and not term.endswith("ss"):
        return term[:-1]
    return term


def tokenize(text: str) -> list[str]:
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
    text = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", text).lower()
    terms = [_stem(word) for word in WORD.findall(text) if word not in STOP_WORDS]
    for run in CJK.findall(text):
        terms += list(run)
        terms += [run[index : index + 2] for index in range(len(run) - 1)]

    return terms


def _schema_text(schema: Any, parts: list[str]) -> None:
    if not isinstance(schema, dict):
        return
    if isinstance(schema.get("description"), str):
        parts.append(schema["description"])

    for name, value in (schema.get("properties") or {}).items():
        parts.append(name)
        _schema_text(value, parts)

    _schema_text(schema.get("items"), parts)

    for key in ("anyOf", "oneOf", "allOf"):
        for variant in schema.get(key) or []:
            _schema_text(variant, parts)


def document(schema: dict[str, Any], source_name: str, source_description: str) -> str:
    name = schema["name"]
    parts = [name, name.replace("_", " "), schema.get("description") or ""]
    _schema_text(schema.get("parameters"), parts)
    parts += [source_name, source_description]
    return " ".join(part for part in parts if part and part.strip())


def rank(query: str, documents: list[tuple[str, str]], limit: int) -> list[str]:
    terms = list(dict.fromkeys(tokenize(query)))
    if not terms or not documents or limit <= 0:
        return []

    counts = [Counter(tokenize(text)) for _, text in documents]
    lengths = [sum(count.values()) for count in counts]
    average = sum(lengths) / len(documents) or 1
    idf = {}
    for term in terms:
        frequency = sum(1 for count in counts if term in count)
        idf[term] = math.log(1 + (len(documents) - frequency + 0.5) / (frequency + 0.5))

    scored = []
    for index, (name, _) in enumerate(documents):
        score = 0.0
        norm = 1.2 * (1 - 0.75 + 0.75 * lengths[index] / average)
        for term in terms:
            count = counts[index].get(term)
            if count:
                score += idf[term] * count * 2.2 / (count + norm)

        if score > 0:
            scored.append((score, index, name))

    scored.sort(key=lambda item: (-item[0], item[1]))
    return [name for _, _, name in scored[:limit]]


# 等待全部来源就绪，返回 [(来源名, 来源说明, [工具 schema]), ...] 及出现问题的来源
Candidates = Callable[[Any], Awaitable[tuple[list[tuple[str, str, list[dict[str, Any]]]], list[str]]]]


class ToolSearch(Tool):
    def __init__(self, candidates: Candidates) -> None:
        super().__init__(name=TOOL_SEARCH, description=DESCRIPTION, input_schema=PARAMETERS, parallel=True)
        self._candidates = candidates

    async def run(self, ctx: Any, args: dict[str, Any]) -> ToolResult:
        query = str(args.get("query") or "").strip()
        if not query:
            return ToolResult(error="query 不能为空", error_code="invalid_arguments")

        limit = max(1, min(int(args.get("limit") or DEFAULT_LIMIT), MAX_LIMIT))
        sources, problems = await self._candidates(ctx)
        documents: list[tuple[str, str]] = []
        found: dict[str, dict[str, Any]] = {}
        for name, description, schemas in sources:
            for schema in schemas:
                found[schema["name"]] = schema
                documents.append((schema["name"], document(schema, name, description)))

        names = rank(query, documents, limit)
        lines = []
        if names:
            lines.append(strings.TOOL_SEARCH_LOADED.format(count=len(names)))
            for name in names:
                summary = (found[name].get("description") or "").strip().splitlines()
                lines.append(strings.TOOL_SEARCH_ITEM.format(name=name, summary=summary[0] if summary else ""))
        else:
            lines.append(strings.TOOL_SEARCH_NONE)

        if problems or not names:
            listed = "、".join(name for name, _, _ in sources) or strings.TOOL_SEARCH_NO_SOURCES
            lines.append(strings.TOOL_SEARCH_SOURCES.format(sources=listed))
            lines += [f"- {problem}" for problem in problems]

        return ToolResult(text="\n".join(lines), loaded_tools=names)
