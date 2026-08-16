"""VOICE-CUE (작비스) — 해커톤 프로토타입 메인 엔트리포인트.

발언(텍스트) -> OpenRouter 무료 Qwen 모델 구조화 분석 -> Context Memory 갱신 -> COP/상황판/작전상황일지 자동 표출.
"""

import csv
import io
import time

import streamlit as st

from modules import context_memory as cm
from modules import layout_renderer as lr
from modules import prompts
from modules.llm_engine import analyze_utterance

st.set_page_config(page_title="VOICE-CUE (작비스)", page_icon="🎙️", layout="wide")

cm.init_session_state()

SPEAKERS = ["기작과", "작전과장", "정보과장", "기상장교", "지휘관", "직접입력"]


def run_utterance(speaker: str, utterance: str) -> None:
    user_turn = prompts.build_user_turn(
        context_memory_summary=st.session_state.context_memory_summary,
        user_corrections=st.session_state.user_corrections,
        speaker=speaker,
        utterance=utterance,
    )
    try:
        result = analyze_utterance(
            system_prompt=prompts.SYSTEM_PROMPT,
            few_shot_messages=prompts.FEW_SHOT_MESSAGES,
            user_turn=user_turn,
        )
    except RuntimeError as e:
        st.error(f"LLM 호출 실패: {e}")
        return

    cm.apply_llm_result(result.data)
    st.session_state.utterance_log.append(
        {"speaker": speaker, "utterance": utterance, "timestamp": time.strftime("%H:%M:%S")}
    )
    st.session_state.latency_history.append(result.latency_seconds)


# ---------- 사이드바 ----------
with st.sidebar:
    st.title("🎙️ VOICE-CUE")
    st.caption("전투지휘소 발언 → 상황 인식 → 화면/기록 자동화 프로토타입")

    st.divider()
    st.subheader("발언 입력")
    speaker_choice = st.selectbox("화자", SPEAKERS)
    if speaker_choice == "직접입력":
        speaker_choice = st.text_input("화자명 직접 입력", value="")
    utterance_text = st.text_area("발언 내용", height=100, placeholder="예: 무인기 2대 식별되었습니다.")

    if st.button("▶ 발언 처리", type="primary", use_container_width=True):
        if not speaker_choice or not utterance_text.strip():
            st.warning("화자와 발언 내용을 입력하세요.")
        else:
            with st.spinner("분석 중..."):
                run_utterance(speaker_choice, utterance_text.strip())

    st.divider()
    st.subheader("🎬 시연 시나리오 자동 재생")
    if st.button("샘플 시나리오 재생 (ORE 훈련)", use_container_width=True):
        import json
        from pathlib import Path

        scenario_path = Path(__file__).parent / "data" / "sample_dialogues" / "scenario1.json"
        scenario = json.loads(scenario_path.read_text(encoding="utf-8"))
        progress = st.progress(0.0, text="시나리오 재생 중...")
        for i, turn in enumerate(scenario):
            with st.spinner(f"[{turn['speaker']}] {turn['utterance']}"):
                run_utterance(turn["speaker"], turn["utterance"])
            progress.progress((i + 1) / len(scenario), text=f"{i + 1}/{len(scenario)} 처리됨")
        st.success("시나리오 재생 완료")

    st.divider()
    st.subheader("✏️ 수동 보정")
    correction_text = st.text_input("판단 보정 사항 입력", placeholder="예: CCTV-3은 항상 좌측에 배치할 것")
    if st.button("보정 사항 반영", use_container_width=True):
        if correction_text.strip():
            cm.add_manual_correction(correction_text.strip())
            st.success("Context Memory에 반영되었습니다. 다음 발언부터 적용됩니다.")
        else:
            st.warning("보정 내용을 입력하세요.")

    if st.session_state.user_corrections:
        st.caption("적용 중인 보정 사항:")
        for c in st.session_state.user_corrections:
            st.caption(f"• {c}")

    st.divider()
    if st.session_state.latency_history:
        avg_latency = sum(st.session_state.latency_history) / len(st.session_state.latency_history)
        last_latency = st.session_state.latency_history[-1]
        st.metric("최근 응답 지연시간", f"{last_latency:.2f}초", help="발언 종료 → 화면 표출까지 목표 5초 이내")
        st.metric("평균 응답 지연시간", f"{avg_latency:.2f}초")


# ---------- 메인 화면 ----------
st.title("전투지휘소 상황판 — VOICE-CUE")

tab_wall, tab_board, tab_log, tab_memory = st.tabs(
    ["COP 화면 구성", "상황판", "작전상황일지", "Context Memory / 발언 이력"]
)

with tab_wall:
    lr.render_cop_wall(st.session_state.cop_layout)

with tab_board:
    lr.render_situation_board(st.session_state.situation_board)

with tab_log:
    lr.render_operation_log(st.session_state.operation_log)
    if st.session_state.operation_log:
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=["event_id", "title", "detail"])
        writer.writeheader()
        writer.writerows(st.session_state.operation_log)
        st.download_button(
            "📥 작전상황일지 CSV 다운로드",
            data=buffer.getvalue().encode("utf-8-sig"),
            file_name="operation_log.csv",
            mime="text/csv",
        )

with tab_memory:
    st.subheader("Context Memory (현재 누적 요약)")
    st.info(st.session_state.context_memory_summary or "아직 발언이 없습니다.")

    st.subheader("발언 이력")
    if st.session_state.utterance_log:
        for turn in reversed(st.session_state.utterance_log):
            st.markdown(f"**[{turn['timestamp']}] {turn['speaker']}**: {turn['utterance']}")
    else:
        st.caption("발언 이력이 없습니다.")

st.divider()
st.caption(
    "⚠️ 이 프로토타입의 모든 데이터는 가상 시나리오입니다. 실제 좌표/부대/작전 정보를 다루지 않습니다. "
    "CCTV PTZ 제어, 실시간 화자분리, 보안 격리 실행 등은 해커톤 시연 범위에서 제외되었으며 향후 확장 항목입니다."
)
