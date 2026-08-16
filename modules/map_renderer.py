"""전장 상황도 SVG 렌더링 — 위성사진 느낌의 기지 조감도.

base_map.serialize_for_llm() 과 "같은 상태"를 그린다. 한쪽만 고치면
사람과 AI가 다른 그림을 보게 되므로 항상 함께 수정할 것.

격자는 두 층으로 그린다.
    주격자 A~J / 1~7  — 자산·항적의 기준 좌표. LLM이 쓰는 것도 이것이다.
    보조격자 (주격자를 4등분) — 눈으로 위치를 가늠하기 위한 것. 데이터에는 쓰지 않는다.
"""

from __future__ import annotations

import hashlib
import html

import streamlit as st

from modules import base_map as bm

CELL = 78
MARGIN_LEFT = 30
MARGIN_TOP = 26
SUBDIV = 4  # 주격자 한 칸을 몇 등분해 보조격자를 그릴지

STATUS_COLOR = {
    "정상근무": "#3FBF8F", "이상없음보고": "#3FBF8F", "대기": "#3FBF8F",
    "경계강화": "#F4A261", "전개": "#F4A261", "재배치중": "#F4A261",
    "사격대기": "#E9C46A", "교전": "#E63946",
}
THREAT_COLOR = {"긴급": "#FF4D5A", "주의": "#F4A261", "관찰": "#4FC3A1"}
ALERT_COLOR = {
    "평시": "#3FBF8F", "관심": "#8AB17D", "주의": "#E9C46A",
    "경계": "#F4A261", "심각": "#E63946",
}

# 위성사진 느낌을 내기 위한 팔레트 (지표 · 포장 · 건물 지붕)
TERRAIN = "#2B3A2E"
TERRAIN_LIGHT = "#35472F"
ASPHALT = "#2E3236"
CONCRETE = "#4A4E52"
ROAD = "#3A3E42"

ROOF = {
    "hangar": "#5A6570", "tower": "#6B5E7A", "ops": "#4E5A66",
    "depot": "#6B5348", "living": "#55606B", "gate": "#4A5058",
    "radar": "#3F5A5E", "apron": CONCRETE, "taxiway": ASPHALT, "runway": ASPHALT,
}


def _esc(text: object) -> str:
    return html.escape(str(text), quote=True)


def _center(cell: str) -> tuple[float, float] | None:
    idx = bm.cell_to_index(cell)
    if idx is None:
        return None
    col, row = idx
    return MARGIN_LEFT + col * CELL + CELL / 2, MARGIN_TOP + row * CELL + CELL / 2


def _rect_for(cells: list[str]) -> tuple[float, float, float, float] | None:
    pts = [_center(c) for c in cells if bm.cell_to_index(c)]
    pts = [p for p in pts if p]
    if not pts:
        return None
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return (min(xs) - CELL / 2, min(ys) - CELL / 2,
            max(xs) - min(xs) + CELL, max(ys) - min(ys) + CELL)


def _jitter(seed: str, span: int) -> int:
    """같은 입력에는 항상 같은 값. 지형 얼룩을 흩뿌리되 새로고침해도 안 흔들리게."""
    return int(hashlib.md5(seed.encode()).hexdigest(), 16) % span


def build_map_svg(compact: bool = False) -> str:
    base = bm.load_base_map()
    grid = base["base"]["grid"]
    cols, rows = grid["cols"], grid["rows"]
    status = st.session_state.map_asset_status
    cells = st.session_state.map_asset_cell

    W = MARGIN_LEFT + len(cols) * CELL + 12
    H = MARGIN_TOP + rows * CELL + 12
    x0, y0 = MARGIN_LEFT, MARGIN_TOP
    x1, y1 = MARGIN_LEFT + len(cols) * CELL, MARGIN_TOP + rows * CELL

    p: list[str] = [
        f'<svg viewBox="0 0 {W} {H}" width="100%" xmlns="http://www.w3.org/2000/svg" '
        f'style="display:block; border-radius:6px; background:#11160F;">',
        "<defs>",
        # 지표 질감 — 옅은 얼룩 패턴
        '<pattern id="grass" width="26" height="26" patternUnits="userSpaceOnUse">'
        f'<rect width="26" height="26" fill="{TERRAIN}"/>'
        f'<circle cx="6" cy="7" r="7" fill="{TERRAIN_LIGHT}" opacity="0.5"/>'
        f'<circle cx="19" cy="18" r="5" fill="{TERRAIN_LIGHT}" opacity="0.35"/>'
        "</pattern>",
        # 포장면 질감
        '<pattern id="pave" width="14" height="14" patternUnits="userSpaceOnUse">'
        f'<rect width="14" height="14" fill="{ASPHALT}"/>'
        f'<rect width="7" height="7" fill="#33383C" opacity="0.5"/>'
        "</pattern>",
        # 건물 그림자
        '<filter id="bshadow" x="-30%" y="-30%" width="180%" height="180%">'
        '<feDropShadow dx="1.5" dy="2.5" stdDeviation="1.2" flood-color="#000" '
        'flood-opacity="0.55"/></filter>',
        "</defs>",
        f'<rect width="{W}" height="{H}" fill="#11160F"/>',
        f'<rect x="{x0}" y="{y0}" width="{x1 - x0}" height="{y1 - y0}" fill="url(#grass)"/>',
    ]

    # --- 수목·초지 얼룩 (지형감) ---
    for i in range(70):
        cx = x0 + _jitter(f"vx{i}", int(x1 - x0))
        cy = y0 + _jitter(f"vy{i}", int(y1 - y0))
        r = 5 + _jitter(f"vr{i}", 13)
        p.append(
            f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="#1F2E20" opacity="0.45"/>'
        )

    # --- 내부 도로망 ---
    ring = [(x0 + 26, y0 + 26), (x1 - 26, y0 + 26), (x1 - 26, y1 - 26), (x0 + 26, y1 - 26)]
    p.append(
        '<polygon points="' + " ".join(f"{a},{b}" for a, b in ring) + '" fill="none" '
        f'stroke="{ROAD}" stroke-width="7" stroke-linejoin="round"/>'
    )
    p.append(
        f'<line x1="{x0 + 26}" y1="{(y0 + y1) / 2}" x2="{x1 - 26}" y2="{(y0 + y1) / 2}" '
        f'stroke="{ROAD}" stroke-width="5"/>'
    )

    # --- 활주로 · 유도로 · 계류장 ---
    facilities = {f["id"]: f for f in base["facilities"]}

    apron = facilities.get("APN")
    if apron and (r := _rect_for(apron["cells"])):
        ax, ay, aw, ah = r
        p.append(
            f'<rect x="{ax + 4}" y="{ay + 8}" width="{aw - 8}" height="{ah - 16}" '
            f'fill="{CONCRETE}" stroke="#5B6066" stroke-width="1" rx="3"/>'
        )
        for i in range(6):
            sx = ax + 14 + i * ((aw - 28) / 6)
            p.append(
                f'<rect x="{sx}" y="{ay + 16}" width="{(aw - 28) / 6 - 6}" '
                f'height="{ah - 34}" fill="none" stroke="#C8B560" stroke-width="1" '
                f'stroke-dasharray="4 4" opacity="0.6"/>'
            )

    taxi = facilities.get("TWY")
    if taxi and (r := _rect_for(taxi["cells"])):
        tx, ty, tw, th = r
        p.append(
            f'<rect x="{tx}" y="{ty + th / 2 - 13}" width="{tw}" height="26" '
            f'fill="url(#pave)" stroke="#40454A" stroke-width="1"/>'
        )
        p.append(
            f'<line x1="{tx}" y1="{ty + th / 2}" x2="{tx + tw}" y2="{ty + th / 2}" '
            f'stroke="#C8B560" stroke-width="1.6" stroke-dasharray="9 7" opacity="0.85"/>'
        )

    rwy = facilities.get("RWY")
    if rwy and (r := _rect_for(rwy["cells"])):
        rx, ry, rw, rh = r
        top = ry + rh / 2 - 21
        p.append(
            f'<rect x="{rx - 6}" y="{top - 5}" width="{rw + 12}" height="52" '
            f'fill="{TERRAIN_LIGHT}" opacity="0.5" rx="2"/>'
        )
        p.append(
            f'<rect x="{rx}" y="{top}" width="{rw}" height="42" fill="url(#pave)" '
            f'stroke="#4A5055" stroke-width="1"/>'
        )
        # 중심선
        p.append(
            f'<line x1="{rx + 30}" y1="{top + 21}" x2="{rx + rw - 30}" y2="{top + 21}" '
            f'stroke="#E8EAEC" stroke-width="2" stroke-dasharray="16 12" opacity="0.85"/>'
        )
        # 양단 접지대 스트라이프
        for side in (rx + 6, rx + rw - 26):
            for k in range(4):
                p.append(
                    f'<rect x="{side}" y="{top + 5 + k * 9}" width="20" height="5" '
                    f'fill="#E8EAEC" opacity="0.8"/>'
                )
        p.append(
            f'<text x="{rx + 30}" y="{top + 25}" fill="#E8EAEC" font-size="12" '
            f'font-weight="700" font-family="monospace" opacity="0.9">27</text>'
        )
        p.append(
            f'<text x="{rx + rw - 46}" y="{top + 25}" fill="#E8EAEC" font-size="12" '
            f'font-weight="700" font-family="monospace" opacity="0.9">09</text>'
        )

    # --- 건물 ---
    for fac in base["facilities"]:
        if fac["id"] in ("RWY", "TWY", "APN"):
            continue
        r = _rect_for(fac["cells"])
        if not r:
            continue
        fx, fy, fw, fh = r
        roof = ROOF.get(fac["type"], "#4E5A66")
        pad = 17 if fw <= CELL else 12
        bx, by = fx + pad, fy + pad + 2
        bw, bh = fw - pad * 2, fh - pad * 2 - 4
        p.append(
            f'<rect x="{bx}" y="{by}" width="{bw}" height="{bh}" fill="{roof}" '
            f'stroke="#20262B" stroke-width="1" rx="2" filter="url(#bshadow)"/>'
        )
        # 지붕 능선 — 격납고는 아치형으로 구분
        if fac["type"] == "hangar":
            p.append(
                f'<path d="M{bx + 2},{by + bh - 3} Q{bx + bw / 2},{by - 2} '
                f'{bx + bw - 2},{by + bh - 3}" fill="none" stroke="#7C8794" '
                f'stroke-width="1.4" opacity="0.8"/>'
            )
        else:
            p.append(
                f'<line x1="{bx + 3}" y1="{by + bh / 2}" x2="{bx + bw - 3}" '
                f'y2="{by + bh / 2}" stroke="#20262B" stroke-width="1" opacity="0.6"/>'
            )
        if not compact:
            p.append(
                f'<text x="{fx + fw / 2}" y="{fy + 12}" fill="#D6DEE6" font-size="9" '
                f'text-anchor="middle" font-family="sans-serif" '
                f'style="paint-order:stroke; stroke:#0D1210; stroke-width:2.5px;">'
                f'{_esc(fac["name"])}</text>'
            )

    # --- 격자 (보조 → 주 순서로 겹쳐 그림) ---
    step = CELL / SUBDIV
    for i in range(len(cols) * SUBDIV + 1):
        x = x0 + i * step
        p.append(f'<line x1="{x}" y1="{y0}" x2="{x}" y2="{y1}" stroke="#8FB6A0" '
                 f'stroke-width="0.4" opacity="0.13"/>')
    for i in range(rows * SUBDIV + 1):
        y = y0 + i * step
        p.append(f'<line x1="{x0}" y1="{y}" x2="{x1}" y2="{y}" stroke="#8FB6A0" '
                 f'stroke-width="0.4" opacity="0.13"/>')
    for c in range(len(cols) + 1):
        x = x0 + c * CELL
        p.append(f'<line x1="{x}" y1="{y0}" x2="{x}" y2="{y1}" stroke="#9FD4B4" '
                 f'stroke-width="0.9" opacity="0.3"/>')
    for r_ in range(rows + 1):
        y = y0 + r_ * CELL
        p.append(f'<line x1="{x0}" y1="{y}" x2="{x1}" y2="{y}" stroke="#9FD4B4" '
                 f'stroke-width="0.9" opacity="0.3"/>')

    for c, label in enumerate(cols):
        p.append(
            f'<text x="{x0 + c * CELL + CELL / 2}" y="{y0 - 9}" fill="#7E9C8B" '
            f'font-size="11" text-anchor="middle" font-family="monospace">{label}</text>'
        )
    for r_ in range(rows):
        p.append(
            f'<text x="{x0 - 12}" y="{y0 + r_ * CELL + CELL / 2 + 4}" fill="#7E9C8B" '
            f'font-size="11" text-anchor="middle" font-family="monospace">{r_ + 1}</text>'
        )

    # --- 외곽 울타리 ---
    p.append(
        f'<rect x="{x0 + 5}" y="{y0 + 5}" width="{x1 - x0 - 10}" height="{y1 - y0 - 10}" '
        f'fill="none" stroke="#C9A227" stroke-width="1.8" stroke-dasharray="3 5" '
        f'opacity="0.75"/>'
    )

    # --- 대공 자산 사거리 ---
    for asset in base["air_defense"]:
        now = status.get(asset["id"], "대기")
        if now == "대기":
            continue
        pos = _center(cells.get(asset["id"], asset["cell"]))
        if not pos:
            continue
        color = STATUS_COLOR.get(now, "#F4A261")
        p.append(
            f'<circle cx="{pos[0]}" cy="{pos[1]}" r="{asset["range_cells"] * CELL}" '
            f'fill="{color}" fill-opacity="0.05" stroke="{color}" stroke-opacity="0.4" '
            f'stroke-width="1" stroke-dasharray="6 6"/>'
        )

    # --- 초소 ---
    for post in base["sentry_posts"]:
        pos = _center(cells.get(post["id"], post["cell"]))
        if not pos:
            continue
        color = STATUS_COLOR.get(status.get(post["id"], "정상근무"), "#3FBF8F")
        x, y = pos
        p.append(f'<circle cx="{x}" cy="{y}" r="8.5" fill="{color}" stroke="#0D1210" '
                 f'stroke-width="2"/>')
        p.append(f'<circle cx="{x}" cy="{y}" r="3" fill="#0D1210" opacity="0.55"/>')
        if not compact:
            p.append(
                f'<text x="{x}" y="{y + 21}" fill="#A9BCB0" font-size="8.5" '
                f'text-anchor="middle" font-family="monospace" '
                f'style="paint-order:stroke; stroke:#0D1210; stroke-width:2.5px;">'
                f'{_esc(post["id"])}</text>'
            )

    # --- 대공 자산 ---
    for asset in base["air_defense"]:
        pos = _center(cells.get(asset["id"], asset["cell"]))
        if not pos:
            continue
        color = STATUS_COLOR.get(status.get(asset["id"], "대기"), "#3FBF8F")
        x, y = pos
        if asset["kind"] == "대공포":
            p.append(f'<rect x="{x - 8}" y="{y - 8}" width="16" height="16" fill="{color}" '
                     f'stroke="#0D1210" stroke-width="2" rx="2"/>')
            p.append(f'<line x1="{x}" y1="{y}" x2="{x + 13}" y2="{y - 9}" '
                     f'stroke="{color}" stroke-width="2.5"/>')
        else:
            p.append(f'<polygon points="{x},{y - 10} {x + 10},{y} {x},{y + 10} '
                     f'{x - 10},{y}" fill="{color}" stroke="#0D1210" stroke-width="2"/>')
        if not compact:
            p.append(
                f'<text x="{x}" y="{y + 22}" fill="#A9BCB0" font-size="8.5" '
                f'text-anchor="middle" font-family="monospace" '
                f'style="paint-order:stroke; stroke:#0D1210; stroke-width:2.5px;">'
                f'{_esc(asset["id"])}</text>'
            )

    # --- 항적 ---
    for track in st.session_state.map_tracks:
        pos = _center(track["cell"])
        if not pos:
            continue
        color = THREAT_COLOR.get(track["threat"], "#F4A261")
        x, y = pos
        p.append(f'<circle cx="{x}" cy="{y}" r="19" fill="{color}" fill-opacity="0.12" '
                 f'stroke="{color}" stroke-width="1.5" stroke-opacity="0.8"/>')
        p.append(f'<circle cx="{x}" cy="{y}" r="26" fill="none" stroke="{color}" '
                 f'stroke-width="0.8" stroke-opacity="0.35"/>')
        p.append(f'<polygon points="{x},{y - 11} {x + 9},{y + 7} {x},{y + 3} '
                 f'{x - 9},{y + 7}" fill="{color}" stroke="#0D1210" stroke-width="1.2"/>')
        p.append(
            f'<text x="{x}" y="{y - 24}" fill="{color}" font-size="10.5" font-weight="700" '
            f'text-anchor="middle" font-family="sans-serif" '
            f'style="paint-order:stroke; stroke:#0D1210; stroke-width:3px;">'
            f'{_esc(track["label"])}</text>'
        )

    p.append("</svg>")
    return "".join(p)


def alert_badge_html() -> str:
    alert = st.session_state.map_alert_level
    color = ALERT_COLOR.get(alert, "#3FBF8F")
    base = bm.load_base_map()
    return (
        f'<div style="display:flex; align-items:center; gap:10px; margin-bottom:8px;">'
        f'<span style="background:{color}; color:#0B0F14; font-weight:800; '
        f'padding:3px 12px; border-radius:4px; font-size:0.85rem;">경보 {_esc(alert)}</span>'
        f'<span style="opacity:0.55; font-size:0.8rem;">{_esc(base["base"]["name"])} · '
        f'격자 1칸 {base["base"]["grid"]["cell_meters"]}m</span></div>'
    )


def render_map_details() -> None:
    """COP 화면 아래에 붙는 상세 정보 — 교전 판정과 자산 현황."""
    reports = bm.engagement_report()
    if reports:
        st.markdown("**교전 가능 판정** — 사거리 기반 자동 계산")
        for line in reports:
            st.caption(f"• {line}")

    with st.expander("자산 현황 상세"):
        base = bm.load_base_map()
        status = st.session_state.map_asset_status
        cells = st.session_state.map_asset_cell
        rows = [
            {"구분": "초소", "ID": x["id"], "명칭": x["name"],
             "위치": cells.get(x["id"], x["cell"]),
             "상태": status.get(x["id"], x["default_status"])}
            for x in base["sentry_posts"]
        ] + [
            {"구분": x["kind"], "ID": x["id"], "명칭": x["name"],
             "위치": cells.get(x["id"], x["cell"]),
             "상태": status.get(x["id"], x["default_status"])}
            for x in base["air_defense"]
        ]
        st.dataframe(rows, use_container_width=True, hide_index=True)
