"""조치 계층 검증 — 판단과 실행이 실제로 분리됐는지 확인한다.

핵심은 두 가지다.
  ① 실패·미연동이 조용히 사라지지 않는가 (지금까지는 표현할 방법 자체가 없었다)
  ② 판단 코드를 고치지 않고 실장비 구현체를 꽂을 수 있는가
"""

import sys

sys.path.insert(0, ".")

from modules import actions as acts  # noqa: E402
from modules import sources  # noqa: E402

catalog = sources.by_id()


def layout(*source_ids):
    out = []
    for i, sid in enumerate(source_ids, start=1):
        entry = catalog[sid]
        out.append({"source_id": sid, "name": entry["name"], "priority": i})
    return out


# ---- ① 배치 하나가 서로 다른 장비에 대한 여러 조치로 갈라지는가 ----
# 돌릴 수 있는 자산에만 지향 조치가 붙어야 한다.
#   TOD-N          열상감시장비  -> 지향 가능
#   CCTV-ROOF-TWR  PTZ 태그     -> 지향 가능
#   CCTV-RWY-01    고정 CCTV    -> 불가 (돌릴 수 없는 카메라에 회전 명령을 보내면 안 된다)
#   SYS-BASEMAP    시스템 화면   -> 카메라가 아님
acted = acts.actions_for_layout(
    layout("SYS-BASEMAP", "TOD-N", "CCTV-ROOF-TWR", "CCTV-RWY-01"), "무인기 식별", catalog
)
kinds = [a.kind for a in acted]
assert kinds.count(acts.WALL_LAYOUT) == 1, kinds
assert kinds.count(acts.CAMERA_AIM) == 2, kinds
aimed = {a.payload["source_id"] for a in acted if a.kind == acts.CAMERA_AIM}
assert aimed == {"TOD-N", "CCTV-ROOF-TWR"}, aimed
assert all(a.reason for a in acted), "근거 없는 조치가 있으면 안 된다"
print(f"[1] 화면 4개 -> 조치 {len(acted)}건 (벽면 1 + 지향 2, 고정 CCTV는 제외) (통과)")

# ---- ①-b 고정 카메라만 있는 배치는 지향 조치를 만들지 않는가 ----
fixed_only = acts.actions_for_layout(
    layout("SYS-BASEMAP", "CCTV-RWY-01", "CCTV-PERI-N01"), "점검", catalog
)
assert [a.kind for a in fixed_only] == [acts.WALL_LAYOUT], [a.kind for a in fixed_only]
print("[1-b] 고정 카메라뿐인 배치 -> 지향 조치 없음 (통과)")

# ---- ①-c 사람이 향하는 자산(바디캠·조준경)은 지향 대상이 아닌가 ----
human = acts.actions_for_layout(
    layout("SYS-BASEMAP", "CAM-GP-01-BODY", "SCOPE-AAA-01"), "점검", catalog
)
assert [a.kind for a in human] == [acts.WALL_LAYOUT], [a.kind for a in human]
print("[1-c] 바디캠·조준경 -> 지향 조치 없음 (통과)")

# ---- ② 미연동이 '성공'으로 둔갑하지 않는가 ----
bus = acts.build_default_bus()
results = bus.dispatch(acted)
wall = [r for r in results if r.action.kind == acts.WALL_LAYOUT][0]
aims = [r for r in results if r.action.kind == acts.CAMERA_AIM]
assert wall.ok and not wall.skipped, "화면 표출은 실제로 되는 조치다"
assert all((not r.ok) and r.skipped for r in aims), "PTZ는 미연동으로 남아야 한다"
assert all("연동되지 않아" in r.detail for r in aims)
print(f"[2] 화면=수행됨 / 지향 {len(aims)}건=미연동으로 구분 보고 (통과)")

# ---- ③ 아무도 지원하지 않는 조치가 조용히 사라지지 않는가 ----
orphan = acts.Action(kind="탄약고문잠금", payload={}, reason="테스트")
[res] = acts.ActionBus([acts.WallActuator()]).dispatch([orphan])
assert res.skipped and not res.ok
assert "연동되지 않았습니다" in res.detail
print("[3] 지원 주체 없는 조치도 결과로 남음 (통과)")

# ---- ④ 실장비 구현체를 앞에 꽂으면 스텁을 밀어내는가 (판단 코드 수정 없이) ----
class FakePtz:
    name = "부대 PTZ 컨트롤러"

    def __init__(self):
        self.moved = []

    def supports(self, kind):
        return kind == acts.CAMERA_AIM

    def execute(self, action):
        self.moved.append(action.payload["source_id"])
        return acts.ActionResult(action=action, ok=True, detail="지향 완료")


real = FakePtz()
bus2 = acts.ActionBus([acts.WallActuator(), real, acts.PtzStubActuator()])
results2 = bus2.dispatch(acted)
aims2 = [r for r in results2 if r.action.kind == acts.CAMERA_AIM]
assert all(r.ok and not r.skipped for r in aims2), "실장비가 등록되면 실제로 수행돼야 한다"
assert real.moved == ["TOD-N", "CCTV-ROOF-TWR"], real.moved
print("[4] 실장비 구현체 등록 -> 스텁 대체, 판단 코드 수정 없음 (통과)")

# ---- ⑤ 장비가 예외를 던져도 회의 진행을 막지 않는가 ----
class BrokenWall:
    name = "고장난 벽면"

    def supports(self, kind):
        return kind == acts.WALL_LAYOUT

    def execute(self, action):
        raise ConnectionError("컨트롤러 응답 없음")


[res] = acts.ActionBus([BrokenWall()]).dispatch([acted[0]])
assert not res.ok and not res.skipped, "예외는 실패지 미연동이 아니다"
assert "컨트롤러 응답 없음" in res.detail
print("[5] 장비 예외 -> 실패로 기록하고 계속 진행 (통과)")

# ---- ⑥ 빈 배치는 조치를 만들지 않는가 ----
assert acts.actions_for_layout([], "이유", catalog) == []
print("[6] 빈 배치 -> 조치 없음 (통과)")

print("\n전체 통과")
