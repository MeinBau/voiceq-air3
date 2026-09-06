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

실행: `streamlit run app.py` 로 띄운 뒤 사이드바에서 '시연 화면'을 고르거나,
      `streamlit run demo.py` 로 이 화면만 단독으로 띄운다.
"""

import time
from pathlib import Path

import streamlit as st

from modules import access
from modules import context_memory as cm
from modules import demo_rooms as dr
from modules import demo_scenario as dsc
from modules import demo_stage as ds
from modules import demo_theme as th
from modules import layout_renderer as lr
from modules import llm_engine as engine
from modules import organization as org
from modules import playbook as pb
from modules import prompts

st.set_page_config(page_title="VOICE-CUE 시연", layout="wide")

# 단독 실행으로 들어와도 관문을 지나치지 않게 한다. app.py가 이미 통과시켰으면
# 곧바로 돌아온다. 예전에는 시연 페이지에만 관문이 없어 외부 공개 시 구멍이었다.
access.require_password()

WALL_COLS, WALL_ROWS = pb.DEMO_GRID_COLS, pb.GRID_ROWS

cm.init_session_state()
st.session_state.setdefault("stage_speaker", "")
st.session_state.setdefault("stage_text", "")
st.session_state.setdefault("stage_voice", False)
# 다음에 재생할 대본 줄 번호. len(대본)이면 재생이 끝난 상태다.
st.session_state.setdefault("play_index", 0)
# 지금 재생 중인 시나리오와, 방금 재생한 턴의 녹음 파일 경로.
st.session_state.setdefault("scenario_id", dsc.SCENARIO_IDS[0])
st.session_state.setdefault("stage_audio", "")

SPEAKERS = org.speaker_titles()


def apply_turn(
    speaker: str,
    utterance: str,
    fast: dict | None,
    full: dict | None,
    display_latency: float | None = None,
    via_voice: bool = False,
) -> None:
    """판단 결과를 화면 상태에 반영한다.

    실시간 호출과 구운 결과 재생이 반드시 이 함수 하나를 거치게 해서, 발표에서 트는
    화면과 리허설에서 본 화면이 갈라지지 않게 한다.
    """
    st.session_state.stage_speaker = speaker
    st.session_state.stage_text = utterance
    st.session_state.stage_voice = via_voice

    timestamp = time.strftime("%H:%M:%S")
    if fast:
        cm.apply_fast_result(fast, utterance)
        if display_latency is not None:
            st.session_state.display_latency_history.append(display_latency)
    if full:
        cm.apply_full_result(
            full, speaker=speaker, timestamp=timestamp, utterance=utterance
        )
    st.session_state.utterance_log.append(
        {"speaker": speaker, "utterance": utterance, "timestamp": timestamp}
    )


def run_turn(speaker: str, utterance: str, via_voice: bool = False) -> dict | None:
    """실시간 LLM 호출. app.run_utterance와 같은 파이프라인이다.

    굽기가 그대로 재활용할 수 있도록 판단 결과를 담은 기록을 돌려준다. 호출이 실패하면
    None.
    """
    try:
        client_factory, model, extra_body = engine.get_runtime()
    except RuntimeError as e:
        st.error(f"LLM 호출 실패: {e}")
        return None

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

    fast = result.fast.data if result.fast else None
    full = result.full.data if result.full else None
    apply_turn(speaker, utterance, fast, full, result.display_latency, via_voice)
    for message in result.errors:
        st.warning(message)

    return {
        "speaker": speaker,
        "utterance": utterance,
        "fast": fast,
        "full": full,
        "display_latency": result.display_latency,
    }


def play_scripted_turn(scenario_id: str, index: int, use_baked: bool) -> None:
    """대본의 한 줄을 재생한다. 구운 결과가 있으면 LLM을 부르지 않는다.

    그 턴의 녹음 파일 경로를 상태에 남겨, 다음 그리기에서 사이드바가 틀어 준다.
    """
    turn = dsc.script(scenario_id)[index]
    if use_baked:
        baked_turn = (dsc.load_baked(scenario_id) or {})["turns"][index]
        apply_turn(
            baked_turn["speaker"],
            baked_turn["utterance"],
            baked_turn.get("fast"),
            baked_turn.get("full"),
            baked_turn.get("display_latency"),
        )
    else:
        run_turn(turn["speaker"], turn["utterance"])

    audio = dsc.audio_path(scenario_id, index)
    st.session_state.stage_audio = str(audio) if audio else ""


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
    st.caption("시나리오 재생")

    catalog = dsc.available()
    labels = {
        c["id"]: f"{c['name']}  ({c['turns']}턴{'·음성' if c['has_audio'] else ''})"
        for c in catalog
    }
    chosen = st.selectbox(
        "시나리오",
        [c["id"] for c in catalog],
        format_func=lambda i: labels[i],
        index=[c["id"] for c in catalog].index(st.session_state.scenario_id)
        if st.session_state.scenario_id in labels else 0,
    )
    if chosen != st.session_state.scenario_id:
        # 시나리오를 바꾸면 진행 위치와 재생 중인 녹음도 같이 되돌린다.
        st.session_state.scenario_id = chosen
        st.session_state.play_index = 0
        st.session_state.stage_audio = ""
        st.session_state.stage_auto = False
        st.rerun()

    scenario_id = st.session_state.scenario_id
    script = dsc.script(scenario_id)
    baked = dsc.load_baked(scenario_id)
    can_replay = dsc.matches_script(baked, scenario_id)
    # 구운 결과가 없거나 대본과 어긋나면 실시간 외에는 고를 것이 없다.
    sources = ["프리베이크", "실시간 LLM"] if can_replay else ["실시간 LLM"]
    source = st.selectbox("재생 소스", sources)
    # 자동 재생은 화면 맨 아래에서 돌기 때문에 이 선택을 상태로 넘겨야 한다.
    use_baked = source == "프리베이크"
    st.session_state.stage_use_baked = use_baked
    st.caption(dsc.describe(baked, scenario_id))

    idx = st.session_state.play_index
    done = idx >= len(script)
    st.progress(idx / len(script), text=f"{idx} / {len(script)} 발언")

    step_cols = st.columns(2)
    if step_cols[0].button("처음으로", use_container_width=True):
        st.session_state.play_index = 0
        st.session_state.stage_audio = ""
        st.session_state.stage_auto = False
        st.rerun()
    if step_cols[1].button(
        "다음 발언", type="primary", use_container_width=True, disabled=done
    ):
        with st.spinner(f"[{script[idx]['speaker']}] 처리 중…"):
            play_scripted_turn(scenario_id, idx, use_baked)
        st.session_state.play_index = idx + 1
        st.rerun()

    # 자동 재생은 화면 맨 아래에서 처리한다 — 이번 발언이 그려진 뒤에 쉬어야 관객이
    # 화면 변화를 볼 수 있기 때문이다.
    # key를 주지 않는다. key가 붙은 상태는 그 위젯이 만들어진 뒤로는 못 바꾸는데
    # (StreamlitWidgetAlreadyInstantiatedError), 재생이 끝났을 때와 굽기를 시작할 때
    # 코드가 자동 재생을 꺼야 하기 때문이다. 대신 value로 넣고 결과를 되돌려 저장한다.
    auto = st.toggle(
        "자동 재생", value=st.session_state.get("stage_auto", False), disabled=done
    )
    st.session_state.stage_auto = auto and not done
    # 슬라이더가 아니라 선택형이다. Streamlit 슬라이더의 채워진 트랙은 primaryColor를
    # 인라인 그라데이션으로 구워 넣어 이 페이지 팔레트로 못 바꾸고(값마다 달라진다),
    # 발표 중에는 드래그보다 클릭 한 번이 빠르다.
    st.selectbox(
        "발언 간격(초)", [1.0, 1.5, 2.0, 3.0, 5.0], index=2, key="stage_pause"
    )
    if st.session_state.get("stage_auto"):
        st.caption("자동 재생 중에는 간격만큼 화면이 멈춰 있어 조작이 늦게 먹습니다.")

    audio_file = st.session_state.get("stage_audio") or ""
    if audio_file and Path(audio_file).exists():
        # 녹음은 m4a(AAC)다. 크롬·사파리·엣지는 그대로 재생하지만, AAC를 빼고 빌드한
        # 일부 리눅스 크로미움에서는 소리가 안 난다 — 그 경우에도 자막과 화면은 그대로다.
        st.audio(Path(audio_file).read_bytes(), format="audio/mp4", autoplay=True)

    st.divider()
    st.caption("굽기 — 실시간 LLM으로 한 번 돌려 판단 결과를 저장")
    if st.button("시나리오 굽기", use_container_width=True):
        st.session_state.play_index = 0
        st.session_state.stage_auto = False
        entries: list[dict] = []
        bar = st.progress(0.0)
        for i, turn in enumerate(script):
            with st.spinner(f"[{turn['speaker']}] {turn['utterance'][:22]}…"):
                record = run_turn(turn["speaker"], turn["utterance"])
            if record is None:
                st.error(f"{i + 1}번째 발언에서 호출이 실패해 굽기를 중단했습니다.")
                break
            entries.append(record)
            bar.progress((i + 1) / len(script))
        else:
            path = dsc.save_baked(
                entries,
                model=str(st.session_state.get("selected_model", "")),
                baked_at=time.strftime("%Y-%m-%d %H:%M"),
                scenario_id=scenario_id,
            )
            st.success(f"저장했습니다 — {path.name}")
        st.session_state.play_index = len(entries)

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
                    "stage_speaker", "stage_text", "stage_voice", "play_index",
                    "stage_audio"):
            st.session_state.pop(key, None)
        cm.init_session_state()
        st.rerun()


# ---------- 무대 ----------
st.markdown(th.css(), unsafe_allow_html=True)

cur_speaker = st.session_state.stage_speaker or None
cur_text = st.session_state.stage_text or None

latencies = st.session_state.display_latency_history
# 8칸에 6패널을 넣으면 1순위가 2×2(4칸)를 못 받는다(4+5>8). 그러면 항상 1순위로
# 고정되는 전장상황도가 1행짜리 납작한 타일이 되어 격자 한 줄만 보인다. 벽면이
# 좁아진 만큼 화면 수를 줄여, 지도가 제 크기를 갖고 나머지도 안 잘리게 한다.
WALL_PANEL_CAP = 5

wall_layout = pb.retile(st.session_state.cop_layout[:WALL_PANEL_CAP], WALL_COLS)

st.markdown(
    ds.header_html(
        situation=st.session_state.situation_type,
        latency=latencies[-1] if latencies else None,
        panels=len(wall_layout),
        clock=time.strftime("%H:%M:%S"),
    ),
    unsafe_allow_html=True,
)

lr.render_cop_wall(
    wall_layout,
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

STAGE_HEIGHT = "31vh"

# 두 칸 모두 같은 높이의 구역 제목을 달아야 카드 위끝·아래끝이 나란히 맞는다.
BODY_HEIGHT = f"calc({STAGE_HEIGHT} - 21px)"

stage = st.columns([3, 2])
with stage[0]:
    st.markdown(
        ds.section_label("전투지휘소", f"{len(dr.occupants(dr.cp_room()['id']))}명 착석")
        + ds.cp_html(cur_speaker, height=BODY_HEIGHT),
        unsafe_allow_html=True,
    )
with stage[1]:
    st.markdown(
        ds.section_label("상황실", f"{len(dr.situation_rooms())}개소")
        + ds.rooms_grid_html(cur_speaker, height=BODY_HEIGHT),
        unsafe_allow_html=True,
    )

st.markdown(
    ds.subtitle_html(cur_speaker, cur_text, st.session_state.stage_voice),
    unsafe_allow_html=True,
)

# 자동 재생 — 이번 발언이 다 그려진 뒤에 쉬고, 다음 발언을 처리한 뒤 다시 그린다.
# 이 순서여야 관객이 발언마다 화면이 바뀌는 것을 볼 수 있다. 위쪽(사이드바)에서
# 처리하면 아직 그리지도 않은 화면을 두고 쉬게 된다.
if st.session_state.get("stage_auto"):
    scenario_id = st.session_state.scenario_id
    if st.session_state.play_index < len(dsc.script(scenario_id)):
        time.sleep(st.session_state.get("stage_pause", 2.0))
        next_index = st.session_state.play_index
        play_scripted_turn(
            scenario_id, next_index, st.session_state.get("stage_use_baked", False)
        )
        st.session_state.play_index = next_index + 1
        st.rerun()
