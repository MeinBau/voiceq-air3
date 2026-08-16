"""가상 비행단 전장 상황도 — 사람과 AI가 "같은 그림"을 보기 위한 공유 상태 계층.

핵심 설계 의도:
    화면은 사람이 보고, 같은 상태를 텍스트로 직렬화한 것을 LLM이 본다.
    좌표를 픽셀이 아니라 군용 격자(A1~J7)로 표현하는 이유가 여기에 있다.
    LLM은 "무인기가 B2, 대공포가 C2, 사거리 4칸"을 읽고 교전 가능 여부를 추론할 수 있지만,
    픽셀 좌표로는 그런 공간 추론을 하지 못한다.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import streamlit as st

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
    """두 격자 간 거리(칸 단위). 사거리 판정용."""
    a, b = cell_to_index(cell_a), cell_to_index(cell_b)
    if a is None or b is None:
        return None
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


# ---------- 세션 상태 ----------


def init_map_state() -> None:
    base = load_base_map()
    if "map_alert_level" not in st.session_state:
        st.session_state.map_alert_level = "평시"
    if "map_tracks" not in st.session_state:
        st.session_state.map_tracks = []
    if "map_asset_status" not in st.session_state:
        st.session_state.map_asset_status = {
            **{p["id"]: p["default_status"] for p in base["sentry_posts"]},
            **{a["id"]: a["default_status"] for a in base["air_defense"]},
        }
    if "map_asset_cell" not in st.session_state:
        # 이동형 장비는 재배치될 수 있으므로 현재 위치를 따로 들고 간다.
        st.session_state.map_asset_cell = {
            **{p["id"]: p["cell"] for p in base["sentry_posts"]},
            **{a["id"]: a["cell"] for a in base["air_defense"]},
        }


def reset_map_state() -> None:
    for key in ("map_alert_level", "map_tracks", "map_asset_status", "map_asset_cell"):
        st.session_state.pop(key, None)
    init_map_state()


def apply_map_updates(updates: dict) -> None:
    """LLM이 낸 map_updates를 상태에 반영한다. 모르는 ID나 격자는 조용히 무시한다."""
    if not isinstance(updates, dict):
        return

    base = load_base_map()
    valid_ids = {p["id"] for p in base["sentry_posts"]} | {a["id"] for a in base["air_defense"]}

    alert = str(updates.get("alert_level", "") or "").strip()
    if alert in base["status_vocab"]["alert_level"]:
        st.session_state.map_alert_level = alert

    tracks = updates.get("tracks")
    if isinstance(tracks, list):
        cleaned = []
        for t in tracks:
            if not isinstance(t, dict):
                continue
            cell = str(t.get("cell", "") or "").strip().upper()
            if cell_to_index(cell) is None:
                continue  # 격자 밖이면 그릴 수 없다.
            cleaned.append(
                {
                    "id": str(t.get("id", "") or f"TRK-{len(cleaned) + 1:02d}"),
                    "label": str(t.get("label", "") or "미상"),
                    "cell": cell,
                    "kind": str(t.get("kind", "") or "미상"),
                    "threat": str(t.get("threat", "") or "관찰"),
                    "note": str(t.get("note", "") or ""),
                }
            )
        st.session_state.map_tracks = cleaned

    for item in updates.get("asset_status", []) or []:
        if not isinstance(item, dict):
            continue
        asset_id = str(item.get("id", "") or "").strip()
        if asset_id not in valid_ids:
            continue
        status = str(item.get("status", "") or "").strip()
        if status:
            st.session_state.map_asset_status[asset_id] = status
        cell = str(item.get("cell", "") or "").strip().upper()
        if cell and cell_to_index(cell) is not None:
            st.session_state.map_asset_cell[asset_id] = cell


# ---------- LLM 입력용 직렬화 ----------


def _nearby_facilities(cell: str, radius: float = 2.0, limit: int = 2) -> str:
    """해당 격자 주변의 주요 시설명. 초소가 무엇을 지키는지 모델에 알려주기 위한 것."""
    base = load_base_map()
    found = []
    for fac in base["facilities"]:
        if fac["type"] in ("runway", "taxiway"):
            continue  # 넓게 걸쳐 있어 변별력이 없다.
        best = min(
            (d for c in fac["cells"] if (d := cell_distance(cell, c)) is not None),
            default=None,
        )
        if best is not None and best <= radius:
            found.append((best, fac["name"]))
    found.sort()
    return ", ".join(name for _, name in found[:limit])


def serialize_for_llm() -> str:
    """현재 전장 상황도를 LLM이 읽을 압축 텍스트로 변환한다.

    사람이 보는 SVG와 완전히 같은 상태를 표현해야 한다. 둘이 어긋나면
    AI가 화면과 다른 판단을 내리게 된다.
    """
    base = load_base_map()
    grid = base["base"]["grid"]
    status = st.session_state.map_asset_status
    cells = st.session_state.map_asset_cell

    lines = [
        f"[기지 배치도] {base['base']['name']} — 격자 A1~{grid['cols'][-1]}{grid['rows']}, "
        f"1칸 {grid['cell_meters']}m",
    ]

    facility_text = " | ".join(
        f"{f['name']} {'-'.join(f['cells']) if len(f['cells']) > 1 else f['cells'][0]}"
        for f in base["facilities"]
    )
    lines.append(f"주요시설: {facility_text}")

    # 초소마다 담당 구역의 주요 시설을 함께 알려준다. 이게 없으면 모델이
    # "탄약고 경계 강화" 지시에 엉뚱한 방향의 초소를 지정한다.
    sentries = " / ".join(
        f"{p['id']} {p['name']} {cells.get(p['id'], p['cell'])} "
        f"{status.get(p['id'], '정상근무')}"
        + (f" [담당: {near}]" if (near := _nearby_facilities(cells.get(p['id'], p['cell']))) else "")
        for p in base["sentry_posts"]
    )
    lines.append(f"초소({len(base['sentry_posts'])}): {sentries}")

    for kind, label in (("대공포", "이동형 대공포"), ("휴대용유도탄", "휴대용 대공유도탄")):
        assets = [a for a in base["air_defense"] if a["kind"] == kind]
        text = " / ".join(
            f"{a['id']} {cells.get(a['id'], a['cell'])} {status.get(a['id'], '대기')} "
            f"사거리{a['range_cells']}칸"
            for a in assets
        )
        lines.append(f"{label}({len(assets)}): {text}")

    lines.append(f"현재 경보수준: {st.session_state.map_alert_level}")

    tracks = st.session_state.map_tracks
    if tracks:
        track_text = " / ".join(
            f"{t['id']} {t['label']}({t['kind']}) {t['cell']} 위협:{t['threat']}"
            + (f" {t['note']}" if t["note"] else "")
            for t in tracks
        )
    else:
        track_text = "(없음)"
    lines.append(f"현재 항적/접촉: {track_text}")

    return "\n".join(lines)


def engagement_report() -> list[str]:
    """현재 항적이 어느 대공 자산의 사거리 안에 있는지 계산한다.

    LLM 추론에 맡기지 않고 코드가 확정적으로 계산해서 프롬프트에 넣는다.
    거리 계산까지 모델에 시키면 틀리기도 하고 출력도 느려진다.
    """
    base = load_base_map()
    cells = st.session_state.map_asset_cell
    out = []
    for track in st.session_state.map_tracks:
        in_range = []
        for asset in base["air_defense"]:
            asset_cell = cells.get(asset["id"], asset["cell"])
            dist = cell_distance(track["cell"], asset_cell)
            if dist is not None and dist <= asset["range_cells"]:
                in_range.append(f"{asset['id']}({dist:.1f}칸)")
        out.append(
            f"{track['id']} {track['label']} @{track['cell']} → "
            + (f"교전가능: {', '.join(in_range)}" if in_range else "교전가능 자산 없음")
        )
    return out
