"""시연 페이지의 '무대' 렌더링 — 전투지휘소 회의실과 상황실 4개를 HTML로 그린다.

발언한 사람 위에 게임 NPC처럼 말풍선이 뜨고, 그 판단 결과로 위쪽 비디오월이 바뀌는
것을 한 화면에서 보여주기 위한 것이다. 색은 발표 자료에서 뽑은 modules/demo_theme의
토큰만 쓴다.

여기 있는 함수는 전부 문자열만 만들고 Streamlit을 부르지 않는다. 화면 없이 출력을
검사할 수 있어야 배치가 깨졌는지 확인하기 쉽기 때문이다. 실제 표출은 demo.py가 한다.

JS는 쓸 수 없다 — st.markdown이 <script>를 제거한다. 등장 효과는 전부 CSS
애니메이션(demo_theme.css의 @keyframes vc-pop)이다.
"""

from __future__ import annotations

import html

from modules import demo_rooms as dr
from modules import demo_theme as th
from modules import organization as org


def _esc(text: object) -> str:
    return html.escape(str(text), quote=True)


# 계급별 좌석 색. 영향력이 아니라 계급으로 칠한다 — 회의실을 봤을 때 누가 상급자인지가
# 먼저 읽혀야 하고, 영향력 수치는 화면에 드러내지 않는 내부 값이다.
_RANK_COLOR = {
    "준장": th.COLORS["accent_bright"],
    "대령": th.COLORS["accent"],
    "중령": th.COLORS["surface_hi"],
    "소령": th.COLORS["surface_hi"],
    "대위": th.COLORS["surface_hi"],
}


def _floating_bubble(text: str, align: str = "center") -> str:
    """좌석 위로 떠오르는 말풍선. 감싸는 쪽이 position:relative여야 한다.

    상석(단장·부단장)은 전투지휘소 카드의 오른쪽 끝에 앉아 있어서, 가운데 정렬로
    띄우면 말풍선이 옆 칸의 상황실 카드를 덮는다. align="right"로 카드 안쪽에 붙인다.
    """
    place = (
        "right:0; left:auto; transform:none;"
        if align == "right"
        else "left:50%; transform:translateX(-50%);"
    )
    return (
        f'<div class="vc-bubble" style="position:absolute; bottom:calc(100% + 9px); {place} '
        f'width:max-content; max-width:250px; z-index:5; '
        f'text-align:left;">{_esc(text)}</div>'
    )


def _inline_bubble(text: str) -> str:
    """카드 안에 자리를 차지하는 말풍선.

    상황실은 2×2 격자라 카드 위로 띄우면 윗줄 카드를 가린다. 꼬리 없이 카드
    안에서 펼쳐지게 한다.
    """
    return (
        f'<div class="vc-bubble is-inline" style="position:relative; margin:6px 0 2px; '
        f'text-align:left;">{_esc(text)}</div>'
    )


def seat_html(
    title: str, speaking_text: str | None = None, bubble_align: str = "center"
) -> str:
    """회의 테이블의 좌석 하나. 발언 중이면 말풍선과 함께 강조된다."""
    info = org.lookup(title) or {}
    rank = str(info.get("rank", ""))
    color = _RANK_COLOR.get(rank, th.COLORS["surface_hi"])

    if speaking_text:
        ring = (
            f"border:2px solid {th.COLORS['accent_bright']}; "
            f"box-shadow:0 0 14px rgba(79,209,255,0.55);"
        )
        name_color = th.COLORS["accent_bright"]
    else:
        ring = "border:2px solid rgba(213,221,232,0.22);"
        name_color = "rgba(255,255,255,0.72)"

    return (
        '<div style="position:relative; display:flex; flex-direction:column; '
        'align-items:center; gap:3px; width:72px;">'
        + (_floating_bubble(speaking_text, bubble_align) if speaking_text else "")
        + f'<div style="width:30px; height:30px; border-radius:50%; background:{color}; '
        f'{ring} display:flex; align-items:center; justify-content:center; '
        f'font-size:0.52rem; font-weight:700; color:#fff;">{_esc(rank)}</div>'
        + f'<div style="font-size:0.53rem; line-height:1.15; text-align:center; '
        f'color:{name_color}; word-break:keep-all;">{_esc(title)}</div>'
        "</div>"
    )


def _seat_row(titles: list[str], speaker: str | None, text: str | None) -> str:
    seats = "".join(
        seat_html(t, text if (speaker == t and text) else None) for t in titles
    )
    return (
        '<div style="display:flex; justify-content:center; gap:9px; flex-wrap:wrap;">'
        + seats
        + "</div>"
    )


def cp_html(
    speaker: str | None = None, text: str | None = None, height: str = "auto"
) -> str:
    """전투지휘소. 좌측 비디오 패널 + 상석 + 회의 테이블 위/아래 좌석 줄.

    height를 주면 그 높이를 채우도록 좌석 줄과 테이블이 세로로 벌어진다. 발표 화면을
    한 화면에 꽉 채우기 위한 것이다.
    """
    room = dr.cp_room()
    people = dr.occupants(room["id"])
    head = [t for t in dr.load().get("head_seats", []) if t in people]
    rest = [t for t in people if t not in head]
    half = (len(rest) + 1) // 2
    top, bottom = rest[:half], rest[half:]

    video_panel = (
        '<div style="width:26px; flex:none; border-radius:5px; '
        "background:repeating-linear-gradient(135deg, rgba(62,142,208,0.55) 0 4px, "
        'rgba(11,39,64,0.9) 4px 8px); border:1px solid rgba(213,221,232,0.25); '
        'display:flex; align-items:center; justify-content:center;">'
        '<div style="writing-mode:vertical-rl; font-size:0.55rem; letter-spacing:2px; '
        'color:rgba(255,255,255,0.85);">비디오 패널</div></div>'
    )

    table = (
        '<div style="border:1px solid rgba(213,221,232,0.3); border-radius:9px; '
        "background:linear-gradient(180deg, rgba(62,142,208,0.16), rgba(11,39,64,0.35)); "
        'min-height:46px; flex:0 1 auto; display:flex; align-items:center; justify-content:center; '
        'font-size:0.6rem; letter-spacing:3px; color:rgba(255,255,255,0.45);">회의 테이블</div>'
    )

    head_col = (
        '<div style="display:flex; flex-direction:column; justify-content:center; '
        'gap:8px; flex:none; padding-left:4px;">'
        + "".join(
            seat_html(t, text if (speaker == t and text) else None, bubble_align="right")
            for t in head
        )
        + "</div>"
    )

    return (
        f'<div class="vc-card" style="padding:11px 13px; height:{height}; '
        f'display:flex; flex-direction:column; box-sizing:border-box;">'
        f'<div style="font-size:0.72rem; font-weight:700; letter-spacing:1px; '
        f'color:{th.COLORS["accent_bright"]}; margin-bottom:9px; flex:none;">'
        f'{_esc(room["name"])}</div>'
        '<div style="flex:1; min-height:0; display:flex; gap:10px; align-items:stretch;">'
        + video_panel
        + '<div style="flex:1; display:flex; flex-direction:column; '
        'justify-content:space-around; padding-top:22px;">'
        + _seat_row(top, speaker, text)
        + table
        + _seat_row(bottom, speaker, text)
        + "</div>"
        + head_col
        + "</div></div>"
    )


def room_card_html(room: dict, speaker: str | None = None, text: str | None = None) -> str:
    """상황실 카드 하나. 그 방 사람이 발언하면 카드가 켜지고 말풍선이 뜬다."""
    people = dr.occupants(room["id"])
    active = bool(speaker and text and speaker in people)
    cls = "vc-card is-speaking" if active else "vc-card"

    if people:
        body = "".join(
            f'<span style="display:inline-block; font-size:0.55rem; padding:2px 6px; '
            f'margin:2px 3px 0 0; border-radius:9px; '
            f'background:{"rgba(79,209,255,0.28)" if t == speaker and active else "rgba(255,255,255,0.09)"}; '
            f'color:{"#fff" if t == speaker and active else "rgba(255,255,255,0.72)"};">'
            f"{_esc(t)}</span>"
            for t in people
        )
    else:
        # 화자가 배정되지 않은 방도 무엇을 담당하는지는 보여야 한다.
        body = "".join(
            f'<span style="display:inline-block; font-size:0.55rem; padding:2px 6px; '
            f'margin:2px 3px 0 0; border-radius:9px; border:1px dashed rgba(255,255,255,0.2); '
            f'color:rgba(255,255,255,0.4);">{_esc(name)}</span>'
            for name in dr.unit_badges(room["id"])
        )

    return (
        f'<div class="{cls}" style="padding:9px 10px; min-height:96px; overflow:auto; '
        f'display:flex; flex-direction:column; justify-content:center;">'
        + f'<div style="font-size:0.66rem; font-weight:700; '
        f'color:{th.COLORS["accent_bright"] if active else "rgba(255,255,255,0.86)"}; '
        f'margin-bottom:5px;">{_esc(room["name"])}</div>'
        + f'<div style="line-height:1.5;">{body}</div>'
        + (_inline_bubble(text) if active else "")
        + "</div>"
    )


def rooms_grid_html(
    speaker: str | None = None, text: str | None = None, height: str = "auto"
) -> str:
    """상황실 4개를 2×2로. height를 주면 네 칸이 그 높이를 고르게 나눠 갖는다."""
    cards = "".join(room_card_html(r, speaker, text) for r in dr.situation_rooms())
    return (
        '<div style="display:grid; grid-template-columns:repeat(2, 1fr); '
        f'grid-template-rows:repeat(2, 1fr); gap:8px; height:{height}; '
        'box-sizing:border-box;">' + cards + "</div>"
    )


def subtitle_html(speaker: str | None, text: str | None, via_voice: bool = False) -> str:
    """하단 자막 바. 지금 발언 전문을 크게 보여준다."""
    if not speaker or not text:
        return (
            '<div class="vc-card" style="padding:10px 14px; font-size:0.75rem; '
            'color:rgba(255,255,255,0.35);">발언 대기 중…</div>'
        )
    badge = (
        f'<span style="font-size:0.55rem; padding:2px 7px; border-radius:9px; '
        f'background:{th.COLORS["ok"]}; color:#fff; margin-left:7px;">음성인식</span>'
        if via_voice
        else ""
    )
    return (
        '<div class="vc-card" style="padding:10px 14px; display:flex; align-items:baseline; '
        f'gap:10px; border-color:{th.COLORS["accent_bright"]};">'
        f'<span style="font-size:0.72rem; font-weight:700; white-space:nowrap; '
        f'color:{th.COLORS["accent_bright"]};">{_esc(speaker)}</span>{badge}'
        f'<span style="font-size:0.95rem; line-height:1.4;">{_esc(text)}</span>'
        "</div>"
    )
