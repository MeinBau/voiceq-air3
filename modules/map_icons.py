"""전장상황도 수동 배치용 프리셋 아이콘 — 운용자가 표에서 직접 추가/수정한다.

프리셋 하나는 (이름, 이모지, 색상, 발언 문구 템플릿)으로 이뤄진다. 배치 시
"발언 문구 템플릿"의 {facility}를 지도에서 계산한 최근접 시설명으로 채워
실제 발언과 똑같은 문장을 만든다 — 그래야 기존 발언 처리 파이프라인
(상황 분류 -> COP 레이아웃 -> 상황판 -> 작전상황일지)을 그대로 재사용할 수 있다.
"""

from __future__ import annotations

import json
from pathlib import Path

PRESETS_PATH = Path(__file__).resolve().parent.parent / "data" / "map_icon_presets.json"

_DEFAULT_PHRASE = "{facility} 인근에서 상황이 발생했습니다."

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


def to_table() -> list[dict]:
    """편집 화면에 쓸 표 형태."""
    return [
        {
            "이름": p.get("label", ""),
            "아이콘": p.get("emoji", ""),
            "색상": p.get("color", "#3D5A80"),
            "발언 문구 ({facility}가 최근접 시설명으로 치환됨)": p.get("phrase", ""),
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
        phrase = str(
            row.get("발언 문구 ({facility}가 최근접 시설명으로 치환됨)", "") or ""
        ).strip()
        presets.append(
            {
                "label": label,
                "emoji": str(row.get("아이콘", "") or "").strip() or "📍",
                "color": str(row.get("색상", "") or "").strip() or "#3D5A80",
                "phrase": phrase or f"{label} — {_DEFAULT_PHRASE}",
            }
        )
    return presets


def build_utterance(preset: dict, facility: str) -> str:
    """프리셋 문구 템플릿에 최근접 시설명을 채운다. 템플릿이 잘못됐어도 안전하게 처리."""
    template = preset.get("phrase") or _DEFAULT_PHRASE
    try:
        return template.format(facility=facility)
    except (KeyError, IndexError, ValueError):
        return f"{template} ({facility} 인근)"
