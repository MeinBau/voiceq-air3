"""COP 레이아웃 JSON -> Streamlit Video Wall 그리드 렌더링."""

from __future__ import annotations

import hashlib
import html

import streamlit as st

from modules import map_renderer as mr
from modules import playbook as pb


def _esc(text: object) -> str:
    return html.escape(str(text), quote=True)

# 소스 이름 -> 플레이스홀더 색상 (실제 영상 피드 없이 색상 블록으로 시현)
_PALETTE = ["#264653", "#2A6F77", "#3D5A80", "#5C4D7D", "#7A4B6B", "#8A3033"]

POSITION_ORDER = ["좌측대형", "우측상단", "우측하단", "중앙"]


def _color_for(name: str) -> str:
    idx = int(hashlib.md5(name.encode("utf-8")).hexdigest(), 16) % len(_PALETTE)
    return _PALETTE[idx]


MAP_SOURCES = ("SYS-BASEMAP",)


def render_cop_wall(cop_layout: list[dict]) -> None:
    """2행 6열 Video Wall. 1순위는 좌측 2×2 대형 화면을 차지한다.

    전장 상황도는 별도 탭이 아니라 이 안에서 실제 SVG로 인라인 표출하며, 상황과
    무관하게 항상 1순위 자리에 고정된다. 지도 위에는 지금 화면에 떠 있는 CCTV의
    위치만 표시한다 — 지휘소 대형 화면을 그대로 옮겨온 모습이어야 하기 때문이다.
    """
    st.subheader("COP 화면 구성 — Video Wall 2×6")

    if not cop_layout:
        st.info("아직 화면 구성이 결정되지 않았습니다. 발언을 입력하면 자동으로 배치됩니다.")
        return

    panels = []
    for item in cop_layout[: pb.MAX_PANELS]:
        row, col, rspan, cspan = item.get("grid", (1, 1, 1, 1))
        panels.append(_panel_html(item, row, col, rspan, cspan, cop_layout))

    st.markdown(
        f'<div style="display:grid; grid-template-columns:repeat({pb.GRID_COLS}, 1fr); '
        f'grid-template-rows:repeat({pb.GRID_ROWS}, minmax(150px, auto)); gap:8px; '
        f'background:#05080B; padding:10px; border-radius:8px; '
        f'border:1px solid rgba(255,255,255,0.08);">' + "".join(panels) + "</div>",
        unsafe_allow_html=True,
    )


def _panel_html(
    item: dict, row: int, col: int, rspan: int, cspan: int, cop_layout: list[dict]
) -> str:
    source_id = item.get("source_id", "")
    name = item.get("name", source_id)
    priority = item.get("priority", "-")
    slot = item.get("slot", "")
    is_map = source_id in MAP_SOURCES

    header = (
        f'<div style="display:flex; justify-content:space-between; align-items:center; '
        f'gap:6px; padding:5px 8px; background:rgba(0,0,0,0.45); font-size:0.72rem;">'
        f'<span style="font-weight:700; color:#E6EDF3; overflow:hidden; '
        f'text-overflow:ellipsis; white-space:nowrap;">{priority}. {_esc(name)}</span>'
        f'<span style="font-family:monospace; opacity:0.5; white-space:nowrap;">'
        f"{_esc(source_id)}</span></div>"
    )

    if is_map:
        active = [x for x in cop_layout if x.get("source_id") not in MAP_SOURCES]
        body = (
            f'<div style="flex:1; padding:6px; overflow:hidden;">'
            f"{mr.build_map_svg(active, compact=(cspan < 2))}</div>"
        )
        bg = "#0B0F14"
    else:
        color = _color_for(source_id)
        body = (
            f'<div style="flex:1; display:flex; flex-direction:column; align-items:center; '
            f'justify-content:center; gap:5px; padding:8px; text-align:center;">'
            f'<div style="font-size:0.7rem; opacity:0.6;">격자 {_esc(item.get("cell", ""))}</div>'
            f'<div style="font-size:0.65rem; opacity:0.4;">실제 피드 연동 시 표출</div></div>'
        )
        bg = color

    footer = (
        f'<div style="padding:3px 8px; background:rgba(0,0,0,0.35); font-size:0.62rem; '
        f'opacity:0.55; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">'
        f"플레이북 슬롯: {_esc(slot)}</div>"
        if slot else ""
    )

    return (
        f'<div style="grid-row:{row} / span {rspan}; grid-column:{col} / span {cspan}; '
        f'background:{bg}; border:1px solid rgba(255,255,255,0.14); border-radius:6px; '
        f'overflow:hidden; display:flex; flex-direction:column; min-height:150px;">'
        f"{header}{body}{footer}</div>"
    )


def render_operation_log(operation_log: list[dict]) -> None:
    st.subheader("작전상황일지")
    if not operation_log:
        st.info("아직 기록된 사건이 없습니다.")
        return

    st.caption(f"진행 중인 사태 {len(operation_log)}건 — 같은 상황의 후속 보고는 하나의 사태로 묶입니다.")

    for i, event in enumerate(reversed(operation_log), start=1):
        entries = event.get("entries", [])
        header = f"[{event.get('event_id', f'사태{i}')}] {event.get('title', '')} · 기록 {len(entries)}건"
        with st.expander(header, expanded=(i == 1)):
            if not entries:
                st.caption("기록된 세부 내용이 없습니다.")
                continue
            for entry in entries:
                timestamp = entry.get("timestamp", "")
                speaker = entry.get("speaker", "")
                meta = " · ".join(x for x in (timestamp, speaker) if x)
                st.markdown(
                    f"<div style='border-left:3px solid #2A6F77; padding:2px 0 2px 12px; margin-bottom:10px;'>"
                    f"<div style='font-size:0.75rem; opacity:0.55;'>{meta}</div>"
                    f"<div>{entry.get('detail', '')}</div></div>",
                    unsafe_allow_html=True,
                )
