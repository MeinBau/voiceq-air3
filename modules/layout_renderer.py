"""COP 레이아웃 JSON -> Streamlit Video Wall 그리드 렌더링, 상황판 카드 UI."""

from __future__ import annotations

import hashlib

import streamlit as st

# 소스 이름 -> 플레이스홀더 색상 (실제 영상 피드 없이 색상 블록으로 시현)
_PALETTE = ["#264653", "#2A6F77", "#3D5A80", "#5C4D7D", "#7A4B6B", "#8A3033"]

URGENCY_COLOR = {
    "긴급": "#E63946",
    "주의": "#F4A261",
    "관찰": "#2A9D8F",
}

POSITION_ORDER = ["좌측대형", "우측상단", "우측하단", "중앙"]


def _color_for(name: str) -> str:
    idx = int(hashlib.md5(name.encode("utf-8")).hexdigest(), 16) % len(_PALETTE)
    return _PALETTE[idx]


def render_cop_wall(cop_layout: list[dict]) -> None:
    st.subheader("🖥️ COP 화면 구성 (Video Wall)")
    if not cop_layout:
        st.info("아직 화면 구성이 결정되지 않았습니다. 발언을 입력하면 자동으로 배치됩니다.")
        return

    by_position: dict[str, list[dict]] = {}
    for item in cop_layout:
        by_position.setdefault(item.get("position", "중앙"), []).append(item)

    left_col, right_col = st.columns([2, 1])

    with left_col:
        for item in by_position.get("좌측대형", []):
            _render_block(item, height=380)

    with right_col:
        for item in by_position.get("우측상단", []):
            _render_block(item, height=180)
        for item in by_position.get("우측하단", []):
            _render_block(item, height=180)

    for item in by_position.get("중앙", []):
        _render_block(item, height=200)


def _render_block(item: dict, height: int) -> None:
    color = _color_for(item.get("source", ""))
    priority = item.get("priority", "-")
    st.markdown(
        f"""
        <div style="background:{color}; border-radius:8px; height:{height}px;
                    display:flex; flex-direction:column; align-items:center; justify-content:center;
                    margin-bottom:12px; border:1px solid rgba(255,255,255,0.15);">
            <div style="font-size:0.8rem; opacity:0.75;">우선순위 {priority}</div>
            <div style="font-size:1.3rem; font-weight:700; margin-top:4px;">{item.get('source', '')}</div>
            <div style="font-size:0.75rem; opacity:0.6; margin-top:6px;">▶ 실제 CCTV/드론 피드 연동 시 여기 표출</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_situation_board(situation_board: list[dict]) -> None:
    st.subheader("📋 상황판 (우선순위)")
    if not situation_board:
        st.info("현재 등록된 상황이 없습니다.")
        return

    for card in situation_board:
        urgency = card.get("urgency", "관찰")
        color = URGENCY_COLOR.get(urgency, "#2A9D8F")
        st.markdown(
            f"""
            <div style="border-left: 6px solid {color}; background:#141A21; border-radius:6px;
                        padding:10px 14px; margin-bottom:8px;">
                <span style="background:{color}; color:#0B0F14; font-weight:700; font-size:0.75rem;
                             padding:2px 8px; border-radius:4px;">{urgency}</span>
                <span style="margin-left:10px; font-size:0.85rem; opacity:0.6;">#{card.get('rank', '-')}</span>
                <div style="font-size:1.05rem; margin-top:6px;">{card.get('event', '')}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def render_operation_log(operation_log: list[dict]) -> None:
    st.subheader("📖 작전상황일지")
    if not operation_log:
        st.info("아직 기록된 사건이 없습니다.")
        return

    for i, entry in enumerate(reversed(operation_log), start=1):
        with st.expander(f"[{entry.get('event_id', f'사태{i}')}] {entry.get('title', '')}", expanded=(i == 1)):
            st.write(entry.get("detail", ""))
