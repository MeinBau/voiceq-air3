# CLAUDE.md — VOICE-CUE 해커톤 프로토타입 개발 가이드

이 문서는 Claude Code가 이 저장소에서 작업할 때 참고하는 프로젝트 컨텍스트입니다.
"제8회 공군 창의·혁신 아이디어 공모 해커톤" 기획서(작비스 / VOICE-CUE)를 기반으로 하되,
**해커톤 시연 가능한 프로토타입**을 목표로 범위를 재조정했습니다. 원 기획서를 그대로
구현하는 것이 목표가 아니라, 핵심 가치(발언 → 상황 인식 → 화면/기록 자동화)를 짧은 시간에
"보여줄 수 있는" 형태로 만드는 것이 목표입니다.

---

## 1. 프로젝트 한 줄 요약

전투지휘소 회의 발언(음성/텍스트)을 실시간으로 분석해서
① 작전상황일지를 자동 생성하고, ② 지금 봐야 할 화면 구성(COP 레이아웃)을 자동으로 결정해
Streamlit 대시보드에 Video Wall처럼 시현하는 프로토타입.

---

## 2. 원안 대비 단순화 결정사항 (중요)

해커톤 시간 제약을 고려해 아래와 같이 범위를 조정했습니다. 실제 개발 시 이 결정을 기본
전제로 삼고 진행하세요.

| 항목 | 원 기획서 | 프로토타입 단순화 |
|---|---|---|
| STT/화자분리 | 실시간 스트리밍 ASR + 화자분리 (GPU 8GB) | **OpenAI Whisper API** 또는 파일 업로드 후 배치 처리. 화자 구분은 발화 전 "화자 선택 드롭다운"으로 대체 가능 (실시간 diarization은 스트레치 목표) |
| 판단/생성 모델 | 한국어 특화 sLLM 파인튜닝(LoRA, 4bit) | **OpenRouter 무료 Qwen 모델(`qwen/qwen3-235b-a22b:free` 등, `:free` 접미사)** 을 프롬프트 엔지니어링 + Few-shot으로 대체. 비용 없이 데모 가능. 파인튜닝은 시간상 생략, "향후 확장" 섹션에 근거만 정리 |
| CCTV PTZ 제어 | YOLO + REST API로 실제 카메라 제어 (GPU 24GB) | **프로토타입에서 제외**. 대신 "CCTV #1 → #2 전환" 같은 판단 결과를 UI 텍스트/아이콘으로만 표시 (실제 하드웨어 연동 없이 로직만 시연) |
| 보안 격리 (Docker+Seccomp) | 코드 생성 후 격리 실행 | **프로토타입에서 제외**. Streamlit Cloud 배포 특성상 별도 코드 실행/격리 불필요. 데모에서는 "실제 운용 시 Docker+Seccomp 검증 단계 필요"로 구두 설명 |
| 화면 조작 (pywinauto) | 실제 GUI 자동화 | **Streamlit 컴포넌트 배치 시뮬레이션**으로 대체 (LLM이 낸 레이아웃 JSON → Streamlit columns/grid로 렌더링) |

즉, **핵심 로직(발언 로그 → MSEL 분류 → COP JSON → 상황판/일지 자동 생성 → Context Memory
갱신)만 실제로 동작**하게 만들고, 물리적 제어(PTZ, 실제 Video Wall, 보안 샌드박스)는
"이렇게 확장할 수 있다"를 보여주는 목업/설명으로 처리합니다.

---

## 3. 기술 스택

- **UI**: Streamlit (Streamlit Community Cloud 배포)
- **LLM**: OpenRouter 경유 무료 Qwen 모델 (기본값 `qwen/qwen3-235b-a22b:free`), `openai` Python SDK
  (OpenRouter가 OpenAI 호환 Chat Completions API를 제공하므로 `base_url`만 바꿔서 사용).
  비용 없이 데모 가능 — 무료 발급: https://openrouter.ai/keys
- **STT**: OpenAI Whisper API (`openai` SDK) — 또는 `faster-whisper` 로컬 처리 (Streamlit Cloud
  리소스 제한 고려 시 API 방식 권장)
- **상태 저장**: 세션 중에는 `st.session_state`, 데모 간 영속성이 필요하면 로컬 JSON 파일
  (`data/context_memory.json`, `data/operation_log.json`)
- **의존성 관리**: `requirements.txt`
- **비밀키 관리**: `.streamlit/secrets.toml` (로컬), Streamlit Cloud 대시보드의 Secrets 설정 (배포)

---

## 4. 폴더 구조 (제안)

```
voice-cue/
├── app.py                     # Streamlit 메인 엔트리포인트
├── requirements.txt
├── .streamlit/
│   ├── config.toml            # 다크 테마 등 Video Wall 느낌 설정
│   └── secrets.toml           # (git에 커밋 금지) API 키
├── modules/
│   ├── stt.py                 # 음성 → 텍스트 + 화자 태깅
│   ├── llm_engine.py          # OpenRouter 무료 Qwen 모델 호출: MSEL 분류/COP 생성/일지 생성/Context Memory 갱신
│   ├── context_memory.py      # Context Memory 읽기/쓰기/압축 로직
│   ├── layout_renderer.py     # COP JSON → Streamlit 그리드 렌더링
│   └── prompts.py             # 시스템 프롬프트, few-shot 예시 모음
├── data/
│   ├── sample_dialogues/      # 시연용 샘플 발언 스크립트 (텍스트/오디오)
│   ├── context_memory.json    # 런타임 생성
│   └── operation_log.json     # 런타임 생성
└── CLAUDE.md
```

---

## 5. 데이터 모델

### 5.1 발언 로그 (STT 결과)
```json
{
  "log_id": "2026-08-14-001",
  "timestamp": "14:02:07",
  "speaker": "기작과",
  "utterance": "무인기 2대, 지상 차량 3대 식별되었습니다."
}
```

### 5.2 Context Memory (LLM이 매 턴 갱신)
- 이전 판단·요약 + 사용자 수동 보정 사항을 누적한 짧은 텍스트/JSON.
- 매 발언 처리 시 **가장 먼저** 갱신되고, 이후 ①②③ 산출물 생성의 입력으로 재사용.
```json
{
  "updated_at": "14:02:09",
  "summary": "무인기 2대·지상 차량 3대 식별, ORE 훈련 상황, 날씨 흐림",
  "user_corrections": []
}
```

### 5.3 LLM 산출물 (한 번의 호출에서 구조화된 JSON으로 동시 요청)
```json
{
  "context_memory": "...",
  "cop_layout": [
    {"source": "CCTV-1", "position": "좌측대형", "priority": 1},
    {"source": "드론추적맵", "position": "우측상단", "priority": 2}
  ],
  "situation_board": [
    {"rank": 1, "event": "무인기 침투", "urgency": "긴급"},
    {"rank": 2, "event": "지상 차량 접근", "urgency": "주의"}
  ],
  "operation_log_entry": {
    "event_id": "사태1",
    "title": "무인기 식별/대응개시",
    "detail": "..."
  }
}
```
→ OpenRouter 무료 Qwen 모델 호출 시, provider별로 strict tool-calling/structured output 지원이
들쭉날쭉하므로 `response_format={"type": "json_object"}` 지정과 함께 시스템 프롬프트에
"JSON 외 다른 텍스트를 출력하지 말 것"을 명시하고, 응답을 코드펜스 제거 후 `json.loads`로 파싱,
실패 시 재시도 로직을 넣습니다. (`modules/llm_engine.py` 참고)

---

## 6. 핵심 파이프라인 (구현 순서)

1. **발언 입력**: 텍스트 직접 입력(데모 편의상 기본) + 오디오 업로드(Whisper 연동, 스트레치)
2. **Context Memory 갱신 + 구조화 산출물 생성**: 위 5.3 스키마로 OpenRouter 무료 Qwen 모델 1회 호출
3. **화면 렌더링**: `cop_layout` JSON을 받아 Streamlit `st.columns`/`st.container`로 Video Wall
   그리드 시뮬레이션 (실제 CCTV 영상 없으면 플레이스홀더 이미지/색상 블록 사용)
4. **상황판**: `situation_board`를 우선순위 정렬된 카드 UI로 표시
5. **작전상황일지**: `operation_log_entry`를 누적 리스트로 표시, CSV/PDF 다운로드 버튼 제공
   (심사위원 데모 임팩트용)
6. **수동 보정 UI**: 사용자가 레이아웃을 잘못됐다고 판단하면 버튼으로 Context Memory에
   즉시 기입 → "실수 반복 방지" 시연 포인트

---

## 7. 개발 로드맵 (해커톤 시간 배분 제안)

| 단계 | 내용 | 우선순위 |
|---|---|---|
| 1 | Streamlit 뼈대 + 텍스트 입력 → OpenRouter 무료 Qwen 모델 호출 → JSON 파싱까지 최소 동작 | 필수 |
| 2 | COP 레이아웃 그리드 렌더링 (플레이스홀더 색상 블록) | 필수 |
| 3 | 상황판 + 작전상황일지 UI | 필수 |
| 4 | Context Memory 누적/표시 + 수동 보정 버튼 | 권장 |
| 5 | 샘플 시나리오(ORE 훈련, 무인기 2대·차량 3대) 자동 재생 데모 모드 | 권장 |
| 6 | Whisper 오디오 업로드 연동 | 선택 (시간 남으면) |
| 7 | 품질 지표(표출 지연시간 등) 대시보드에 실시간 표시 | 선택 (심사 지표 어필용) |

---

## 8. Streamlit Cloud 배포 체크리스트

- `requirements.txt`에 `streamlit`, `openai`(OpenRouter 호출용) 명시
- API 키는 절대 코드에 하드코딩하지 말고 `st.secrets["OPENROUTER_API_KEY"]`로 접근
  (무료 발급: https://openrouter.ai/keys, 이메일 가입만 하면 됨·결제수단 불필요)
- 로컬 개발 시 `.streamlit/secrets.toml`은 `.gitignore`에 반드시 추가
- Streamlit Cloud 배포 시 대시보드 > App settings > Secrets에 동일한 키·값 등록
- 리소스 제한(무료 티어 CPU/메모리) 고려 시 무거운 로컬 STT/화자분리 모델은 지양,
  API 기반 처리 권장

---

## 9. 시연 시나리오 (기획서 4-다 항 기반)

1. "ORE 훈련 중 무인기 2대, 지상 차량 3대 식별" 발언 입력
2. → Context Memory 갱신, COP 레이아웃 자동 생성(좌측 무인기 영상, 우측 차량 영상) 시연
3. → 상황판에 우선순위(무인기 침투 긴급 1순위) 표시
4. → 작전상황일지에 자동 기록됨을 보여줌
5. 후속 발언("날씨 흐림, 시야 제한") 입력 → Context Memory에 반영되어 이후 판단에 영향
   미치는 것을 시연 (복합 판단 능력 어필)
6. 심사위원에게 강조할 포인트: **"화면 구성 품질이 담당자 숙련도에 의존하지 않는다"**,
   **"발언 종료 → 화면 표출까지 목표 5초 이내"** (무료 Qwen 모델 응답속도 실측치로 대체 제시.
   무료 모델 특성상 지연이 클 수 있어 실측 후 목표치 조정 필요),
   **"LLM API 비용 없이 데모 가능"** (OpenRouter 무료 티어)

---

## 10. 향후 확장 아이디어 (원 기획서 유지, 프로토타입에는 미포함)

- 실시간 스트리밍 ASR + 화자분리 모델 온프레미스 전환
- 한국어 특화 sLLM(Qwen2.5 등) LoRA 파인튜닝으로 보안망 내 온프레미스 구동
- YOLO 기반 PTZ CCTV 자동 추적/전환
- Docker + Seccomp 기반 생성 코드 격리 실행 (Validation 단계)
- 타 지휘통제 환경(방공통제소, 재난상황실 등) 수평 확산

---

## 11. Claude Code 작업 시 유의사항

- 이 프로젝트는 군 작전 맥락의 데모이지만 **실제 민감 정보나 실제 좌표/영상 데이터는
  다루지 않음** — 모든 예시 데이터는 가상 시나리오로 생성
- LLM 응답은 반드시 JSON 파싱 실패에 대비한 예외처리 포함
- UI는 다크 테마 + 그리드 배치로 "Video Wall" 느낌을 내되, 과도한 커스텀 CSS보다는
  Streamlit 기본 컴포넌트 조합으로 안정성 우선
- 코드 변경 시마다 `streamlit run app.py`로 로컬 확인 후 커밋
