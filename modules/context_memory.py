"""Context Memory / 작전상황일지 상태 관리 (세션 중에는 st.session_state, 필요 시 JSON 파일 영속화)."""

from __future__ import annotations

import json
from pathlib import Path

import streamlit as st

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
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def apply_llm_result(result_data: dict) -> None:
    st.session_state.context_memory_summary = result_data.get("context_memory", "")
    st.session_state.cop_layout = sorted(
        result_data.get("cop_layout", []), key=lambda x: x.get("priority", 99)
    )
    st.session_state.situation_board = sorted(
        result_data.get("situation_board", []), key=lambda x: x.get("rank", 99)
    )

    entry = result_data.get("operation_log_entry", {})
    if entry.get("title"):
        st.session_state.operation_log.append(entry)


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
