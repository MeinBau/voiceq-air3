"""조치(Action) 계층 — "판단"과 "실행"을 분리한다.

지금까지 이 앱은 판단 결과를 세션 상태에 직접 대입하고 다시 그리기만 했다. 그래서
두 가지가 불가능했다.

  ① 실패라는 개념이 없다. `st.session_state.cop_layout = layout` 은 실패할 수 없으므로,
     "화면을 띄우라고 했는데 안 떴다"를 표현할 방법이 없었다. 실제 Video Wall이나 PTZ
     카메라를 붙이면 실패는 일상이다(전원, 네트워크, 권한).
  ② 기획서 원안의 물리적 제어(PTZ, Video Wall 조작)를 붙일 자리가 없다. 판단 코드
     한복판에 하드웨어 호출을 끼워 넣는 것 말고는 방법이 없었다.

그래서 판단 결과를 "조치 목록"으로 만들고, 그 조치를 실제로 수행하는 주체(Actuator)를
따로 둔다. 지금 붙어 있는 구현체는 화면 표시용 하나뿐이고 PTZ는 미연동 스텁이지만,
부대에 실제 장비가 있으면 이 인터페이스를 구현한 클래스를 하나 더 꽂으면 된다 —
판단 코드는 손대지 않는다.

이 모듈은 streamlit에 의존하지 않는다. 실행 주체가 반드시 화면일 필요는 없기 때문이다
(폐쇄망 서버의 장비 제어 데몬, 테스트 하네스 등).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

# 조치 종류. 문자열로 두는 이유는 이 목록이 부대 장비 구성에 따라 늘어나기 때문이다 —
# Enum으로 고정하면 구현체를 추가할 때마다 이 모듈을 고쳐야 한다.
WALL_LAYOUT = "화면구성"      # 벽면에 이 화면들을 이 배치로 띄운다
CAMERA_AIM = "카메라지향"      # 해당 CCTV를 그 지점으로 지향한다(PTZ)


@dataclass(frozen=True)
class Action:
    """수행해야 할 조치 하나.

    reason은 로그와 화면에 그대로 나간다. 자동화가 무엇을 왜 했는지 운용자가 사후에
    따라갈 수 없으면 신뢰받지 못하기 때문에, 근거 없는 조치는 만들지 않는다.
    """

    kind: str
    payload: dict
    reason: str


@dataclass
class ActionResult:
    action: Action
    ok: bool
    detail: str
    latency_ms: float = 0.0
    # 수행 주체가 아직 없어서 넘어간 경우. 실패(ok=False)와 구분해야 한다 —
    # "장비가 없다"와 "장비가 있는데 실패했다"는 운용자에게 전혀 다른 정보다.
    skipped: bool = False


@runtime_checkable
class Actuator(Protocol):
    """조치를 실제로 수행하는 주체."""

    name: str

    def supports(self, kind: str) -> bool:
        ...

    def execute(self, action: Action) -> ActionResult:
        ...


class ActionBus:
    """조치를 수행 가능한 Actuator에게 넘긴다.

    한 종류를 여러 주체가 지원하면 먼저 등록된 쪽이 가져간다(실장비 구현체를 앞에
    등록하면 스텁을 자동으로 밀어낸다). 아무도 지원하지 않으면 skipped로 남긴다 —
    조용히 사라지지 않게 하는 것이 이 계층의 핵심이다.
    """

    def __init__(self, actuators: list[Actuator] | None = None) -> None:
        self.actuators: list[Actuator] = list(actuators or [])

    def register(self, actuator: Actuator) -> None:
        self.actuators.append(actuator)

    def dispatch(self, actions: list[Action]) -> list[ActionResult]:
        results: list[ActionResult] = []
        for action in actions:
            target = next((a for a in self.actuators if a.supports(action.kind)), None)
            if target is None:
                results.append(
                    ActionResult(
                        action=action,
                        ok=False,
                        skipped=True,
                        detail=f"'{action.kind}'을 수행할 장비가 연동되지 않았습니다.",
                    )
                )
                continue
            start = time.monotonic()
            try:
                result = target.execute(action)
            except Exception as e:  # noqa: BLE001 — 장비 오류로 회의 진행을 막지 않는다.
                result = ActionResult(
                    action=action, ok=False, detail=f"{target.name} 실행 중 오류: {e}"
                )
            if not result.latency_ms:
                result.latency_ms = (time.monotonic() - start) * 1000
            results.append(result)
        return results


# ---------------------------------------------------------------------
# 조치 도출 — 판단 결과에서 "무엇을 해야 하는지"를 뽑아낸다
# ---------------------------------------------------------------------

# 원격으로 지향(pan/tilt)할 수 있는 자산인지 판별한다.
#
# "카메라인가"(map_renderer.CAMERA_FEED_TYPES)와는 다른 질문이라 따로 둔다. 카탈로그
# 270건 중 카메라는 223건이지만, 그중 실제로 돌릴 수 있는 것은 훨씬 적다.
#   · PTZ 태그가 붙은 CCTV 6건 — 옥상 광역 카메라, 설명에 "360도 회전"
#   · 열상감시장비(TOD) 8건 — 방위를 지향하는 감시자산
# 나머지 고정 CCTV 200건에 "지향하라"고 보내면 받을 수 없는 명령이 되고, 실장비를
# 붙였을 때 전부 실패로 돌아온다. 처음에는 feed_type만 보고 223건을 전부 지향
# 대상으로 잡았는데, 그건 고정 카메라에 회전 명령을 내리는 것과 같았다.
#
# 바디캠(초병 착용)·조준경(사수 조준)은 사람이 향하는 것이라 원격 지향 대상이 아니다.
# 이동형(순찰차 탑재)도 제외한다 — 그건 카메라를 돌리는 게 아니라 차량을 이동시키는
# 것이고, 사람이 판단할 별개의 조치다.
AIMABLE_FEED_TYPES = {"열상"}
PTZ_TAG = "PTZ"


def is_aimable(source: dict) -> bool:
    return source.get("feed_type") in AIMABLE_FEED_TYPES or PTZ_TAG in source.get("tags", [])


def actions_for_layout(
    layout: list[dict], reason: str, catalog: dict[str, dict]
) -> list[Action]:
    """확정된 화면 배치에서 수행할 조치들을 만든다.

    배치 하나가 조치 하나로 끝나지 않는다는 점이 중요하다. "북서 CCTV를 띄운다"는
    결정은 실제 지휘소에서 ① 벽면에 그 화면을 올리고 ② 그 카메라를 그 지점으로
    지향하는, 서로 다른 장비에 대한 두 조치다. 지금까지는 ①만 존재했다.
    """
    if not layout:
        return []

    actions = [
        Action(
            kind=WALL_LAYOUT,
            payload={"panels": layout},
            reason=reason or "상황 판단에 따른 화면 구성",
        )
    ]

    for item in layout:
        entry = catalog.get(item.get("source_id", ""))
        if not entry or not is_aimable(entry):
            continue
        actions.append(
            Action(
                kind=CAMERA_AIM,
                payload={
                    "source_id": entry["id"],
                    "name": entry["name"],
                    "cell": entry.get("cell", ""),
                },
                reason=f"{item.get('priority', '-')}순위 화면으로 표출 중",
            )
        )
    return actions


# ---------------------------------------------------------------------
# 구현체
# ---------------------------------------------------------------------


@dataclass
class WallActuator:
    """벽면 표시 담당. 지금 프로토타입에서는 Streamlit 화면이 곧 벽면이다.

    실제 Video Wall 컨트롤러(기획서의 pywinauto 경로)를 붙일 때는 이 클래스를 대체하는
    구현체를 만들어 ActionBus 앞쪽에 등록하면 된다. 판단 코드는 바뀌지 않는다.
    """

    name: str = "Streamlit 화면"
    applied: list[dict] = field(default_factory=list)

    def supports(self, kind: str) -> bool:
        return kind == WALL_LAYOUT

    def execute(self, action: Action) -> ActionResult:
        panels = action.payload.get("panels") or []
        self.applied = panels
        return ActionResult(
            action=action, ok=True, detail=f"{len(panels)}개 화면을 벽면에 표출했습니다."
        )


@dataclass
class PtzStubActuator:
    """PTZ 카메라 지향 — 미연동 스텁.

    기획서 원안(YOLO + REST API로 실제 카메라 제어)의 자리다. 지금은 하드웨어가 없으므로
    수행하지 않고 "미연동"으로 남긴다. 성공했다고 보고하지 않는 것이 중요하다 —
    시연에서 실제로 카메라가 움직인다고 오해하게 만들면 안 된다.

    실장비를 붙일 때는 execute에서 카메라 REST API를 호출하고 응답으로 ok를 정하면 된다.
    """

    name: str = "PTZ 제어 (미연동)"

    def supports(self, kind: str) -> bool:
        return kind == CAMERA_AIM

    def execute(self, action: Action) -> ActionResult:
        return ActionResult(
            action=action,
            ok=False,
            skipped=True,
            detail=(
                f"{action.payload.get('name', '')} 지향 대상으로 선정됐으나 "
                "카메라 제어 장비가 연동되지 않아 수행하지 않았습니다."
            ),
        )


def build_default_bus() -> ActionBus:
    """프로토타입 기본 구성 — 화면은 실제로 바꾸고, 카메라 제어는 미연동으로 남긴다."""
    return ActionBus([WallActuator(), PtzStubActuator()])
