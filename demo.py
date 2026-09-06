"""VOICE-CUE 시연용 페이지 — 발언하는 사람과 그 결과로 바뀌는 벽면을 한 화면에.

본 앱(app.py)은 운용자가 쓰는 도구라 탭·설정·로그가 함께 있다. 이 페이지는 발표장에서
심사위원이 보는 화면이며, "누가 말했고" → "벽면이 어떻게 바뀌었는지" 두 가지만 남긴다.

  ┌──────────────────────────────────────────────┐
  │ 비디오월 2행 4열                                │
  ├───────────────────────────┬──────────────────┤
  │ 전투지휘소 (회의 테이블·좌석) │ 상황실 4개 (2×2)   │
  ├───────────────────────────┴──────────────────┤
  │ 자막 바 — 지금 발언 전문                        │
  └──────────────────────────────────────────────┘

화면 선택은 본 앱과 똑같은 경로(engine.analyze_turn → context_memory.apply_fast_result
→ playbook)를 그대로 탄다. 벽면이 2행 4열인 것만 다르며, 그것도 playbook.retile이
좌표만 다시 계산한다 — 선택 로직을 복제하면 두 화면의 판단이 갈라지기 때문이다.

실행: streamlit run demo.py
"""

import time

import streamlit as st

from modules import context_memory as cm
from modules import demo_rooms as dr
from modules import demo_stage as ds
from modules import demo_theme as th
from modules import layout_renderer as lr
from modules import llm_engine as engine
from modules import organization as org
from modules import playbook as pb
from modules import prompts

st.set_page_config(page_title="VOICE-CUE 시연", layout="wide")

WALL_COLS, WALL_ROWS = pb.DEMO_GRID_COLS, pb.GRID_ROWS

cm.init_session_state()
st.session_state.setdefault("stage_speaker", "")
st.session_state.setdefault("stage_text", "")
st.session_state.setdefault("stage_voice", False)

SPEAKERS = org.speaker_titles()


def run_turn(speaker: str, utterance: str, via_voice: bool = False) -> None:
    """발언 하나를 처리한다. 말풍선을 먼저 세우고, 판단 결과로 벽면을 바꾼다.

    app.run_utterance와 같은 파이프라인이다. 여기서는 시연에 쓰지 않는 것(수동 보정
    누적, 지연시간 이력)을 빼고 화면에 보이는 것만 남겼다.
    """
    st.session_state.stage_speaker = speaker
    st.session_state.stage_text = utterance
    st.session_state.stage_voice = via_voice

    try:
        client_factory, model, extra_body = engine.get_runtime()
    except RuntimeError as e:
        st.error(f"LLM 호출 실패: {e}")
        return

    summary = st.session_state.context_memory_summary
    result = engine.analyze_turn(
        client_factory=client_factory,
        model=model,
        fast_system=prompts.FAST_SYSTEM_PROMPT,
        fast_few_shot=prompts.FAST_FEW_SHOT_MESSAGES,
        fast_turn=prompts.build_fast_turn(
            context_memory_summary=summary,
            user_corrections=st.session_state.user_corrections,
            speaker_desc=org.describe_speaker(speaker),
            utterance=utterance,
            situation_list_text=pb.describe_for_llm(),
        ),
        full_system=prompts.FULL_SYSTEM_PROMPT,
        full_few_shot=prompts.FULL_FEW_SHOT_MESSAGES,
        full_turn=prompts.build_full_turn(
            context_memory_summary=summary,
            user_corrections=st.session_state.user_corrections,
            speaker_desc=org.describe_speaker(speaker),
            utterance=utterance,
            operation_log=st.session_state.operation_log,
        ),
        extra_body=extra_body,
    )

    timestamp = time.strftime("%H:%M:%S")
    if result.fast:
        cm.apply_fast_result(result.fast.data, utterance)
        st.session_state.display_latency_history.append(result.display_latency)
    if result.full:
        cm.apply_full_result(
            result.full.data, speaker=speaker, timestamp=timestamp, utterance=utterance
        )
    for message in result.errors:
        st.warning(message)
    st.session_state.utterance_log.append(
        {"speaker": speaker, "utterance": utterance, "timestamp": timestamp}
    )


# ---------- 조작 (발표 중에는 접어 둔다) ----------
with st.sidebar:
    st.title("시연 조작")

    speaker = st.selectbox("화자", SPEAKERS, key="stage_pick_speaker")
    room = dr.room_of(speaker)
    room_name = next(r["name"] for r in dr.rooms() if r["id"] == room)
    st.caption(f"{org.lookup(speaker)['rank'] if org.lookup(speaker) else ''} · {room_name}")

    text = st.text_area("발언", height=90, key="stage_pick_text")
    if st.button("발언 처리", type="primary", use_container_width=True):
        if text.strip():
            with st.spinner("분석 중..."):
                run_turn(speaker, text.strip())
            st.rerun()
        else:
            st.warning("발언 내용을 입력하세요.")

    st.divider()
    if st.button("샘플 시나리오 재생", use_container_width=True):
        import json
        from pathlib import Path

        turns = json.loads(
            (Path(__file__).parent / "data" / "sample_dialogues" / "scenario1.json")
            .read_text(encoding="utf-8")
        )
        bar = st.progress(0.0)
        for i, turn in enumerate(turns):
            with st.spinner(f"[{turn['speaker']}] {turn['utterance'][:24]}…"):
                run_turn(turn["speaker"], turn["utterance"])
            bar.progress((i + 1) / len(turns))
        st.rerun()

    st.divider()
    # 리허설용. LLM을 부르지 않고 플레이북만으로 벽면을 채워, 네트워크 없이 배치를
    # 확인하거나 발표 직전에 화면을 미리 세워 둘 때 쓴다.
    st.caption("리허설 — LLM 없이 벽면만 채우기")
    preview = st.selectbox("상황 유형", pb.situation_names(), key="stage_preview_pick")
    if st.button("이 상황으로 벽면 채우기", use_container_width=True):
        layout, _ = pb.build_layout(preview, st.session_state.stage_text or "")
        st.session_state.cop_layout = layout
        st.session_state.situation_type = preview
        st.rerun()

    if st.button("초기화", use_container_width=True):
        for key in ("cop_layout", "situation_board", "operation_log", "utterance_log",
                    "active_situations", "situation_type", "map_markers",
                    "stage_speaker", "stage_text", "stage_voice"):
            st.session_state.pop(key, None)
        cm.init_session_state()
        st.rerun()


# ---------- 무대 ----------
st.markdown(th.css(), unsafe_allow_html=True)

cur_speaker = st.session_state.stage_speaker or None
cur_text = st.session_state.stage_text or None

header = st.columns([4, 1])
header[0].markdown(
    f'<div style="font-size:1.15rem; font-weight:800; letter-spacing:2px; '
    f'color:{th.COLORS["accent_bright"]};">VOICE-CUE · 전투지휘소 상황판</div>',
    unsafe_allow_html=True,
)
if st.session_state.display_latency_history:
    header[1].metric("표출 지연", f"{st.session_state.display_latency_history[-1]:.1f}s")

# 8칸에 6패널을 넣으면 1순위가 2×2(4칸)를 못 받는다(4+5>8). 그러면 항상 1순위로
# 고정되는 전장상황도가 1행짜리 납작한 타일이 되어 격자 한 줄만 보인다. 벽면이
# 좁아진 만큼 화면 수를 줄여, 지도가 제 크기를 갖고 나머지도 안 잘리게 한다.
WALL_PANEL_CAP = 5

lr.render_cop_wall(
    pb.retile(st.session_state.cop_layout[:WALL_PANEL_CAP], WALL_COLS),
    st.session_state.situation_board,
    st.session_state.map_markers,
    cols=WALL_COLS,
    rows=WALL_ROWS,
    show_title=False,
    # 고정 높이 트랙. auto로 두면 지도 패널이 늘어나 상황실이 화면 밖으로 밀린다.
    # 한 화면(100vh)에 꽉 채우기 위한 세로 배분. 패널 자체의 min-height:150px보다
    # 작아지지 않게 max()로 묶는다.
    row_track="max(150px, 22vh)",
)

STAGE_HEIGHT = "32vh"

stage = st.columns([3, 2])
with stage[0]:
    st.markdown(ds.cp_html(cur_speaker, cur_text, height=STAGE_HEIGHT), unsafe_allow_html=True)
with stage[1]:
    # 상황실 제목이 차지하는 만큼 빼야 전투지휘소 카드와 아래끝이 맞는다.
    st.markdown(
        f'<div style="font-size:0.72rem; font-weight:700; letter-spacing:1px; '
        f'color:{th.COLORS["accent_bright"]}; margin:0 0 7px;">상황실</div>'
        + ds.rooms_grid_html(
            cur_speaker, cur_text, height=f"calc({STAGE_HEIGHT} - 25px)"
        ),
        unsafe_allow_html=True,
    )

st.markdown(
    ds.subtitle_html(cur_speaker, cur_text, st.session_state.stage_voice),
    unsafe_allow_html=True,
)
