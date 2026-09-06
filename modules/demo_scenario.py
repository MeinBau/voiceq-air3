"""시연 시나리오 재생 — 대본 읽기와 '구운' LLM 결과의 저장·복원.

발표장에서 무료 모델이 느려지거나 429를 뱉으면 시연이 그 자리에서 멈춘다. 그래서
리허설 때 시나리오를 한 번 실제로 돌려 FAST/FULL 판단 결과를 파일로 구워 두고
(save_baked), 발표에서는 그 결과를 그대로 재생한다(load_baked). 재생 경로는 실시간과
완전히 같은 함수(context_memory.apply_fast_result / apply_full_result)를 타므로,
구운 것과 실시간의 화면 결과가 갈라지지 않는다.

구운 파일은 대본이 바뀌면 못 쓴다 — 발언은 새 대본인데 판단은 옛 대본 것이 되기
때문이다. matches_script()로 발언 목록을 대조해서 걸러낸다.
"""

from __future__ import annotations

import json
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
SCRIPT_PATH = DATA_DIR / "sample_dialogues" / "scenario1.json"
BAKED_PATH = DATA_DIR / "sample_dialogues" / "scenario1.baked.json"


def script() -> list[dict]:
    """대본 — [{speaker, utterance}, ...]."""
    return json.loads(SCRIPT_PATH.read_text(encoding="utf-8"))


def load_baked() -> dict | None:
    """구운 결과. 없거나 읽을 수 없으면 None (실시간으로 돌리면 되므로 예외로 막지 않는다)."""
    if not BAKED_PATH.exists():
        return None
    try:
        return json.loads(BAKED_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def matches_script(baked: dict | None) -> bool:
    """구운 결과가 지금 대본과 같은 발언들인지. 다르면 재생하면 안 된다."""
    if not baked:
        return False
    baked_turns = baked.get("turns") or []
    current = script()
    if len(baked_turns) != len(current):
        return False
    return all(
        b.get("speaker") == c.get("speaker") and b.get("utterance") == c.get("utterance")
        for b, c in zip(baked_turns, current)
    )


def save_baked(turns: list[dict], model: str, baked_at: str) -> Path:
    """굽기 결과를 저장한다. turns는 speaker·utterance·fast·full·display_latency를 담는다."""
    BAKED_PATH.write_text(
        json.dumps(
            {
                "note": (
                    "리허설 때 실제 LLM으로 한 번 돌려 저장한 판단 결과. 발표장 네트워크"
                    " 사고에 대비한 재생용이며, demo.py의 '프리베이크' 재생 소스가 쓴다."
                ),
                "model": model,
                "baked_at": baked_at,
                "turns": turns,
            },
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
    return BAKED_PATH


def describe(baked: dict | None) -> str:
    """사이드바에 보여줄 한 줄 상태."""
    if not baked:
        return "구운 결과 없음 — 실시간으로만 재생됩니다."
    if not matches_script(baked):
        return "구운 결과가 지금 대본과 다릅니다 — 다시 구워야 합니다."
    return f"{baked.get('model', '?')} · {baked.get('baked_at', '?')}"
