"""Context Memory / 작전상황일지 상태 관리 (세션 중에는 st.session_state, 필요 시 JSON 파일 영속화)."""

from __future__ import annotations

import json
import re
from pathlib import Path

import streamlit as st

from modules import base_map as bm
from modules import llm_engine as engine
from modules import playbook as pb

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
        "latency_history": [],
        "display_latency_history": [],
        "dropped_sources": [],
        "situation_type": "",
        "situation_focus": "",
        "situation_reason": "",
        "situation_unmatched": "",
        "provider": engine.configured_provider(),
        "selected_model": engine.default_model_for(engine.configured_provider()),
        "model_options": [],
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value
    bm.init_map_state()


def apply_fast_result(result_data: dict) -> None:
    """표출 경로 결과 — 상황 유형을 받아 플레이북으로 화면을 구성한다.

    LLM은 상황 유형과 "관련 CCTV를 고르기 위한 대략적 방향(focus_cell)"만 정한다.
    focus_cell은 사건의 정확한 물리적 위치가 아니라 방향 참고값이다. 어떤 화면을
    어느 순서로 띄울지는 운용자가 만든 플레이북이 결정하므로, 모델이 화면 이름을
    지어낼 여지가 없다.
    """
    bm.apply_map_updates(result_data.get("map_updates") or {})

    situation = result_data.get("situation") or {}
    raw_type = str(situation.get("type", "") or "").strip()
    focus_cell = str(situation.get("focus_cell", "") or "").strip().upper()
    if bm.cell_to_index(focus_cell) is None:
        focus_cell = "E4"  # 방향을 못 정하면 중앙 CCTV 클러스터를 기본값으로 쓴다.

    matched = pb.find_situation(raw_type)
    resolved_name = matched["name"] if matched else "기타 상황"

    layout, unresolved = pb.build_layout(resolved_name, focus_cell)
    st.session_state.cop_layout = layout
    st.session_state.dropped_sources = unresolved
    st.session_state.situation_type = resolved_name
    st.session_state.situation_focus = focus_cell
    st.session_state.situation_reason = str(situation.get("reason", "") or "")
    st.session_state.situation_unmatched = raw_type if not matched else ""


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
