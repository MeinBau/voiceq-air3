"""가상 비행단 배치도 — 사람과 AI가 "같은 격자"를 보기 위한 공유 좌표계.

핵심 설계 의도:
    좌표를 픽셀이 아니라 군용 격자(A1~J7)로 표현하는 이유는, LLM이 "북서방"
    같은 방향 표현과 "가장 가까운 CCTV"를 같은 좌표계로 연결할 수 있게 하기
    위해서다. 지도 자체는 항상 고정된 배치도이며, 그 위에 표시되는 것은
    "지금 화면(COP)에 떠 있는 CCTV가 어디를 보고 있는지"뿐이다. 항적·경보수준·
    자산 가동상태처럼 LLM이 매번 판단해서 지도에 찍어야 하는 상태는 두지 않는다
    — 정확한 물리적 위치를 모르는 상태로 억지로 좌표를 만들어내는 문제를
    원천적으로 없애기 위함이다.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

BASE_MAP_PATH = Path(__file__).resolve().parent.parent / "data" / "base_map.json"


@lru_cache(maxsize=1)
def load_base_map() -> dict:
    return json.loads(BASE_MAP_PATH.read_text(encoding="utf-8"))


def cell_to_index(cell: str) -> tuple[int, int] | None:
    """'C4' -> (col_index=2, row_index=3). 잘못된 값이면 None."""
    if not cell or len(cell) < 2:
        return None
    base = load_base_map()
    cols = base["base"]["grid"]["cols"]
    col_char = cell[0].upper()
    if col_char not in cols:
        return None
    try:
        row = int(cell[1:])
    except ValueError:
        return None
    if not (1 <= row <= base["base"]["grid"]["rows"]):
        return None
    return cols.index(col_char), row - 1


def cell_distance(cell_a: str, cell_b: str) -> float | None:
    """두 격자 간 거리(칸 단위). 가장 가까운 CCTV를 고르는 데 쓴다."""
    a, b = cell_to_index(cell_a), cell_to_index(cell_b)
    if a is None or b is None:
        return None
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


def static_context_for_llm() -> str:
    """LLM이 focus_cell(방향)을 판단할 때 참고할 고정 배치도 요약.

    상황에 따라 바뀌는 상태가 없으므로 매번 같은 텍스트다. 발언에 나온 시설명·
    방위를 실제 격자로 옮길 수 있도록 시설 위치만 알려준다.
    """
    base = load_base_map()
    grid = base["base"]["grid"]

    facility_text = " | ".join(
        f"{f['name']} {'-'.join(f['cells']) if len(f['cells']) > 1 else f['cells'][0]}"
        for f in base["facilities"]
    )

    return (
        f"[기지 배치도] {base['base']['name']} — 격자 A1~{grid['cols'][-1]}{grid['rows']}, "
        f"1칸 {grid['cell_meters']}m\n"
        f"주요시설: {facility_text}"
    )
