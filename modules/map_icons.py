"""전장상황도 자동 배치용 프리셋 아이콘 — 운용자가 표에서 직접 추가/수정한다.

프리셋 하나는 (이름, 이모지, 색상)으로 이뤄진다. 어떤 상황 유형이 어떤 아이콘을
쓸지는 이 모듈이 아니라 cop_playbook.json의 situations[].icon이 정한다
(playbook.py 참고) — 화면 배치를 정답 플레이북이 결정하는 것과 같은 원리다.
"""

from __future__ import annotations

import json
from pathlib import Path

PRESETS_PATH = Path(__file__).resolve().parent.parent / "data" / "map_icon_presets.json"

_cache: dict | None = None


def load_presets(force: bool = False) -> list[dict]:
    global _cache
    if _cache is None or force:
        _cache = json.loads(PRESETS_PATH.read_text(encoding="utf-8"))
    return _cache["presets"]


def save_presets(presets: list[dict]) -> None:
    global _cache
    data = {"presets": presets}
    PRESETS_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    _cache = data


def find_preset(label: str) -> dict | None:
    return next((p for p in load_presets() if p.get("label") == label), None)


def to_table() -> list[dict]:
    """편집 화면에 쓸 표 형태."""
    return [
        {
            "이름": p.get("label", ""),
            "아이콘": p.get("emoji", ""),
            "색상": p.get("color", "#3D5A80"),
        }
        for p in load_presets()
    ]


def from_table(rows: list[dict]) -> list[dict]:
    """편집된 표를 프리셋 목록으로 되돌린다. 이름이 빈 행은 버린다."""
    presets = []
    for row in rows:
        label = str(row.get("이름", "") or "").strip()
        if not label:
            continue
        presets.append(
            {
                "label": label,
                "emoji": str(row.get("아이콘", "") or "").strip() or "📍",
                "color": str(row.get("색상", "") or "").strip() or "#3D5A80",
            }
        )
    return presets
