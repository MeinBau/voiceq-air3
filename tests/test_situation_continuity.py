"""화면이 사라지는 두 가지 상황을 재현하고 막혔는지 확인한다.

  ① 상황 단서가 없는 발언(잡담·화면배치 지시)에 모델이 아무 상황이나 찍으면
     진행 중이던 화면이 통째로 다른 상황으로 바뀌던 문제
  ② 두 사태가 같이 진행 중일 때 나중에 판정된 하나로 화면을 갈아치워
     나머지 사태가 화면에서 사라지던 문제
"""
import sys
import types

sys.path.insert(0, ".")


class FakeState(dict):
    """st.session_state 대역 — 속성/딕셔너리 접근을 모두 받는다."""
    def __getattr__(self, k):
        try:
            return self[k]
        except KeyError as e:
            raise AttributeError(k) from e

    def __setattr__(self, k, v):
        self[k] = v


fake_st = types.SimpleNamespace(session_state=FakeState(), secrets={})
sys.modules["streamlit"] = fake_st

from modules import context_memory as cm  # noqa: E402

cm.init_session_state()


def ids():
    return [x["source_id"] for x in fake_st.session_state.cop_layout]


def fast(kind, reason="테스트"):
    return {"situation": {"type": kind, "reason": reason}}


# ---- ① 상황 확정 후, 단서 없는 발언이 화면을 갈아엎지 않는가 ----
cm.apply_fast_result(fast("드론상황"), "북서방 상공에 무인기 2대 식별되었습니다.")
drone = ids()
assert drone, "드론상황 레이아웃이 비었다"
assert fake_st.session_state.active_situations == ["드론상황"]
print("[1] 드론상황 확정:", len(drone), "패널")

# 단장이 화면 배치 지시를 한다 — 모델이 "유지"를 낸 경우
cm.apply_fast_result(fast("유지", "화면 배치 지시"), "작전상황판은 우측에 계속 유지하십시오.")
assert ids() == drone, f"유지인데 화면이 바뀌었다:\n  before={drone}\n  after={ids()}"
assert fake_st.session_state.active_situations == ["드론상황"]
print("[2] '유지' 발언 -> 화면 그대로 (통과)")

# 모델이 플레이북에 없는 이름을 지어낸 경우 — 예전엔 '기타 상황'으로 화면이 날아갔다
cm.apply_fast_result(fast("갑작스러운 미상 상황"), "커피 좀 준비해 주시겠습니까?")
assert ids() == drone, f"지어낸 유형인데 화면이 바뀌었다: {ids()}"
print("[3] 플레이북에 없는 유형 -> 화면 그대로 (통과)")

# ---- ② 두 번째 사태가 생겨도 첫 번째가 화면에 남는가 ----
cm.apply_fast_result(
    fast("미상인원 기지침투"), "남측 취약지점에서 미상인원 침투가 확인되었습니다."
)
both = ids()
assert fake_st.session_state.active_situations == ["미상인원 기지침투", "드론상황"], \
    fake_st.session_state.active_situations

from modules import playbook as pb  # noqa: E402

drone_only, _ = pb.build_layout("드론상황", "북서방 상공에 무인기 2대 식별되었습니다.")
intr_only, _ = pb.build_layout("미상인원 기지침투", "남측 취약지점에서 미상인원 침투가 확인되었습니다.")
drone_ids = {x["source_id"] for x in drone_only}
intr_ids = {x["source_id"] for x in intr_only}
pinned = drone_ids & intr_ids          # 전장상황도처럼 양쪽 공통인 화면은 증거가 안 된다
drone_only_ids = drone_ids - pinned
intr_only_ids = intr_ids - pinned

assert drone_only_ids & set(both), \
    f"두 번째 사태가 오자 첫 사태 고유 화면이 전부 사라졌다: {both}"
assert intr_only_ids & set(both), \
    f"두 번째 사태 고유 화면이 안 떴다: {both}"
print(f"[4] 두 상황 동시 표출 -> {len(both)}패널, 양쪽 고유 화면 모두 존재 (통과)")

# 한 벽면이 감당할 수 있는 크기를 넘지 않는가
assert len(both) <= pb.panel_budget(), f"패널이 {len(both)}개로 예산({pb.panel_budget()})을 넘었다"
print(f"[5] 패널 수 {len(both)} <= 예산 {pb.panel_budget()} (통과)")

# ---- ③ 세 번째 사태가 오면 가장 오래된 것이 밀려나는가 ----
cm.apply_fast_result(fast("화생방 오염 상황"), "북측에서 화생방 오염이 탐지되었습니다.")
assert fake_st.session_state.active_situations == ["화생방 오염 상황", "미상인원 기지침투"], \
    fake_st.session_state.active_situations
print("[6] 세 번째 사태 -> 가장 오래된 상황이 밀려남 (통과)")

# ---- ④ 진행 중 상황이 없을 때는 '유지'가 와도 멈추지 않아야 한다 ----
fake_st.session_state.clear()
cm.init_session_state()
cm.apply_fast_result(fast("유지"), "커피 좀 주세요.")
assert fake_st.session_state.cop_layout == [], "세션 시작 직후에는 띄울 화면이 없어야 한다"
cm.apply_fast_result(fast("드론상황"), "북서방 무인기 식별")
assert ids(), "진행 중 상황이 없다가 새 상황이 오면 화면이 떠야 한다"
print("[7] 세션 시작 직후 '유지' -> 빈 화면 유지, 이후 새 상황은 정상 표출 (통과)")

print("\n전체 통과")
