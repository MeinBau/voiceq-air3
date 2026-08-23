"""Context Memory / 작전상황일지 상태 관리 (세션 중에는 st.session_state, 필요 시 JSON 파일 영속화)."""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

import streamlit as st

from modules import llm_engine as engine
from modules import map_icons as mi
from modules import map_renderer as mr
from modules import playbook as pb
from modules import sources

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
CONTEXT_MEMORY_PATH = DATA_DIR / "context_memory.json"
OPERATION_LOG_PATH = DATA_DIR / "operation_log.json"


def init_session_state() -> None:
    defaults = {
        "context_memory_summary": "",
        "user_corrections": [],
        "utterance_log": [],
        "cop_layout": [],
        "situation_board": [],
        "operation_log": [],
        "map_markers": [],
        "latency_history": [],
        "display_latency_history": [],
        "dropped_sources": [],
        "situation_type": "",
        "situation_reason": "",
        "situation_unmatched": "",
        "provider": engine.configured_provider(),
        "selected_model": engine.default_model_for(engine.configured_provider()),
        "model_options": [],
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def apply_fast_result(result_data: dict, utterance: str = "") -> None:
    """표출 경로 결과 — 상황 유형을 받아 플레이북으로 화면을 구성한다.

    LLM은 상황 유형 분류만 한다. 어떤 화면을 어느 순서로 띄울지는 운용자가 만든
    플레이북이 결정하고, "해당 지역 CCTV" 같은 위치 기반 슬롯은 이번 발언 텍스트를
    코드가 직접 읽어(playbook.resolve_slot) 방위·시설명이 겹치는 카메라를 고른다 —
    모델이 좌표나 화면 이름을 지어낼 여지가 없다.
    """
    situation = result_data.get("situation") or {}
    raw_type = str(situation.get("type", "") or "").strip()

    matched = pb.find_situation(raw_type)
    resolved_name = matched["name"] if matched else "기타 상황"

    layout, unresolved = pb.build_layout(resolved_name, utterance)
    st.session_state.cop_layout = layout
    st.session_state.dropped_sources = unresolved
    st.session_state.situation_type = resolved_name
    st.session_state.situation_reason = str(situation.get("reason", "") or "")
    st.session_state.situation_unmatched = raw_type if not matched else ""

    icon_label = str((matched or {}).get("icon", "") or "").strip()
    if icon_label:
        _auto_place_marker(icon_label, utterance)


def _auto_place_marker(icon_label: str, utterance: str) -> None:
    """상황 유형에 연결된 프리셋 아이콘을, 발언에 언급된 시설 위치에 자동으로 놓는다.

    같은 아이콘이 이미 떠 있으면 새로 만들지 않고 위치만 갱신한다 — 발언마다 같은
    상황의 아이콘이 계속 쌓이지 않고, 하나의 아이콘이 최신 상황 위치로 옮겨가게
    하기 위해서다. 발언에 시설명이 없으면 아무 것도 하지 않는다 — 모르는 위치를
    지도에 억지로 찍지 않는다(map_renderer.py와 같은 원칙). 실무자는 '전장상황도
    조작' 탭에서 이 자동 위치를 정밀하게 조정만 하면 된다.
    """
    preset = mi.find_preset(icon_label)
    if not preset:
        return
    locations = sources.mentioned_locations(utterance)
    if not locations:
        return
    pos = mr.facility_center(locations[0])
    if not pos:
        return

    marker = {
        "x": pos[0], "y": pos[1],
        "emoji": preset["emoji"], "color": preset["color"], "label": preset["label"],
        "facility": locations[0], "timestamp": time.strftime("%H:%M:%S"),
    }
    markers = st.session_state.map_markers
    existing = next((m for m in markers if m.get("label") == preset["label"]), None)
    if existing:
        existing.update(marker)
    else:
        markers.append(marker)


def apply_full_result(result_data: dict, speaker: str = "", timestamp: str = "") -> None:
    """기록 경로 결과 — 누적 요약, 상황판, 작전상황일지를 갱신한다."""
    st.session_state.context_memory_summary = result_data.get("context_memory", "")
    st.session_state.situation_board = sorted(
        result_data.get("situation_board", []), key=lambda x: x.get("rank", 99)
    )

    _merge_operation_log_entry(result_data.get("operation_log_entry") or {}, speaker, timestamp)


_EVENT_ID_RE = re.compile(r"^(?:사태|사건|상황|이벤트|event)\s*[-_]?\s*(\d+)$", re.IGNORECASE)


def _normalize_event_id(raw: object) -> str:
    """사태 ID 표기 흔들림을 흡수한다.

    모델이 "사태1" 대신 "사건2", "상황 3", "event-1" 같은 변형을 내는 경우가 있다.
    그대로 두면 같은 사태인데도 매칭에 실패해 새 사태가 생긴다. 번호가 같으면
    같은 사태로 본다.
    """
    text = str(raw or "").strip()
    if not text:
        return ""
    match = _EVENT_ID_RE.match(text)
    return f"사태{int(match.group(1))}" if match else text


def _merge_operation_log_entry(entry: dict, speaker: str, timestamp: str) -> None:
    """LLM이 낸 일지 항목을 기존 사태에 병합하거나, 없으면 새 사태로 추가한다.

    event_id가 이미 존재하는 사태와 일치하면 그 사태의 타임라인에 이어 붙인다.
    발언 하나가 곧 사태 하나가 되지 않도록 하는 것이 이 함수의 핵심이다.
    """
    event_id = _normalize_event_id(entry.get("event_id", ""))
    title = str(entry.get("title", "") or "").strip()
    detail = str(entry.get("detail", "") or "").strip()

    # 특기할 내용이 없는 단순 잡담은 일지에 기록하지 않는다.
    if not detail and not title:
        return

    log = st.session_state.operation_log
    existing = next((e for e in log if e.get("event_id") == event_id), None) if event_id else None

    if existing is not None:
        if detail:
            existing["entries"].append(
                {"timestamp": timestamp, "speaker": speaker, "detail": detail}
            )
        # 상황이 전개되면 모델이 제목을 갱신할 수 있다. 빈 문자열이면 기존 제목을 유지한다.
        if title:
            existing["title"] = title
        return

    log.append(
        {
            "event_id": event_id or f"사태{len(log) + 1}",
            "title": title or detail,
            "entries": (
                [{"timestamp": timestamp, "speaker": speaker, "detail": detail}] if detail else []
            ),
        }
    )


def add_manual_correction(correction_text: str) -> None:
    st.session_state.user_corrections.append(correction_text)


def persist_to_disk() -> None:
    """데모 간 영속성이 필요할 때 로컬 JSON으로 저장 (선택 사항)."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CONTEXT_MEMORY_PATH.write_text(
        json.dumps(
            {
                "summary": st.session_state.get("context_memory_summary", ""),
                "user_corrections": st.session_state.get("user_corrections", []),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    OPERATION_LOG_PATH.write_text(
        json.dumps(st.session_state.get("operation_log", []), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
