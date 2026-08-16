"""비행단 편제와 화자 영향력.

기획서 4-가① "발화자 구분을 통해 이후 판단에 발화자의 영향력(계급·직책)이 반영됨"을
실제로 구현하는 계층이다. 화자 이름만 넘기면 LLM은 그가 누구인지 모른다.
직책·계급·담당 분야·영향력 가중치를 함께 넘겨야 "비행단장의 격추 지시"와
"당직사관의 단순 전파"를 다르게 취급할 수 있다.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

ORG_PATH = Path(__file__).resolve().parent.parent / "data" / "organization.json"


@lru_cache(maxsize=1)
def load_org() -> dict:
    return json.loads(ORG_PATH.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def speakers() -> list[dict]:
    return load_org()["speakers"]


@lru_cache(maxsize=1)
def _by_title() -> dict[str, dict]:
    return {s["title"]: s for s in speakers()}


@lru_cache(maxsize=1)
def _unit_names() -> dict[str, str]:
    return {u["id"]: u["name"] for u in load_org()["units"]}


def speaker_titles() -> list[str]:
    """UI 드롭다운용. 영향력 높은 순으로 정렬한다."""
    return [s["title"] for s in sorted(speakers(), key=lambda x: -x["influence"])]


def lookup(title: str) -> dict | None:
    return _by_title().get(title)


def describe_speaker(title: str) -> str:
    """LLM 프롬프트에 넣을 화자 설명 한 줄."""
    info = lookup(title)
    if not info:
        return f"{title} (편제 미등록 화자, 영향력 0.5로 간주)"

    unit = _unit_names().get(info["unit"], info["unit"])
    domains = ", ".join(info["domain"])
    line = (
        f"{info['title']} ({info['rank']}, {unit}) · 담당분야: {domains} · "
        f"영향력 {info['influence']:.2f}"
    )
    if info.get("note"):
        line += f"\n  ※ {info['note']}"
    return line


def influence_of(title: str) -> float:
    info = lookup(title)
    return info["influence"] if info else 0.5


def org_tree_text() -> str:
    """편제를 계층 텍스트로. UI 표시용."""
    units = load_org()["units"]
    children: dict[str | None, list[dict]] = {}
    for unit in units:
        children.setdefault(unit["parent"], []).append(unit)

    lines: list[str] = []

    def walk(parent: str | None, depth: int) -> None:
        for unit in children.get(parent, []):
            lines.append(f"{'　' * depth}{'└ ' if depth else ''}{unit['name']} ({unit['cell']})")
            walk(unit["id"], depth + 1)

    walk(None, 0)
    return "\n".join(lines)
