# VOICE-CUE 파인튜닝 (기획서 3-나 1단계 / 4-다)

기획서가 "1단계 기반 구축"으로 요구한 **모의 데이터셋 구축·라벨링 + 폐쇄망용 sLLM
파인튜닝**을 이 디렉터리에서 다룬다. 앱 실행에는 전혀 관여하지 않으며,
`requirements.txt`(앱)와 `requirements-train.txt`(학습)는 분리돼 있다.

## 1. 기획서 요구사항 대응표

| 기획서 항목 | 요구 | 구현 | 상태 |
|---|---|---|---|
| 3-나 1단계 | 학습 데이터 500건 이상 | `gen_dataset.py` | ✅ **1,527건** 생성 |
| 4-다① 데이터 구축 | 화자·MSEL·중요도·COP JSON 라벨, JSONL | `gen_dataset.py` + `scenario_bank.py` | ✅ 4종 라벨 전부 |
| 4-다① 제약조건 | "항상 띄워야 하는 화면" 등 복합 명령문 | `scenario_bank.CONSTRAINT_TURNS` | ✅ 6종, 보정 규칙 누적까지 |
| 4-다② 모델 학습 | Qwen2.5 / Llama-3, LoRA | `train_lora.py` (QLoRA) + `kaggle_train.ipynb`/`colab_train.ipynb` | ✅ Kaggle T4 x2에서 1.5B 1에폭 완주 (33분) |
| 4-다③ 평가 | Keyword Accuracy + BLEU/ROUGE | `evaluate.py` | ✅ 자기검증 통과 |
| 3-라 4개 품질지표 | 표출지연/상위배치/편차/일지정확도 | `evaluate.py` | ✅ 3개 자동 측정 (③은 아래 참고) |
| 3-다 성능 | 4bit 양자화 2~4GB | Qwen2.5-3B nf4 ≈ 2GB | ✅ 기본값으로 채택 |

## 2. 핵심 설계 결정 — LLM은 COP JSON을 직접 출력하지 않는다

기획서 4-다①은 "화면 구성(COP) JSON 정답을 라벨링"한다고 적혀 있지만, 이 저장소는
이미 **화면 배치를 LLM이 아니라 운용자 플레이북(`data/cop_playbook.json`)이 결정**하도록
설계돼 있다 (`CLAUDE.md` 11절: 폐쇄 카탈로그를 거치지 않는 변경 금지).

그래서 학습 타깃을 이렇게 나눴다.

| | 학습 타깃 | 비고 |
|---|---|---|
| FAST | `situation.type` / `reason` | 상황 유형 분류만 |
| FULL | `context_memory`, `situation_board`, `operation_log_entry` | 기록 3종 |
| COP JSON | **학습 타깃 아님** | 상황 유형 → `playbook.build_layout()`으로 결정론적 파생 |

COP 정답 레이아웃은 `turns_*.jsonl`의 `cop_reference`에 함께 저장되어 **평가 지표 ②의
정답**으로 쓰인다. 모델이 `source_id`를 지어낼 수 없으므로 존재하지 않는 화면을 띄우는
사고가 원천 차단되고, 기획서 3-라②의 "전문가 정답 레이아웃 대비 일치율 90% 이상"은
"상황 유형을 맞혔는가" 하나로 좁혀진다.

프롬프트는 `modules/prompts.py`의 `build_fast_turn`/`build_full_turn`을 **그대로 호출**해
만든다. 문자열을 복제하지 않으므로 런타임 프롬프트가 바뀌면 학습 데이터도 자동으로 따라간다.

## 3. 실행 순서

```bash
# ① 데이터 구축 (GPU 불필요, 수 초)
python finetune/gen_dataset.py                 # 기본: 220 시나리오, seed 20260829

# ② 데이터 점검 (GPU·torch 불필요)
python finetune/train_lora.py --dry-run

# ③ 평가 하네스 자기검증 (GPU 불필요) — 전 지표 100%가 나와야 정상
python finetune/evaluate.py --backend gold
python finetune/evaluate.py --backend perturb --noise 0.3   # 지표가 실제로 하락하는지

# ④ 학습 (GPU 필요 — 끊김 없이 돌리려면 finetune/kaggle_train.ipynb, 상세는 6절.
#    Colab은 finetune/colab_train.ipynb, 상세는 5절)
pip install -r finetune/requirements-train.txt
python finetune/train_lora.py

# ⑤ 튜닝 모델 평가
python finetune/evaluate.py --backend hf \
    --model Qwen/Qwen2.5-3B-Instruct --adapter finetune/out/adapter

# ⑥ 폐쇄망 서빙용 병합
python finetune/train_lora.py --merge finetune/out/merged
```

`finetune/data/`와 `finetune/out/`은 `.gitignore` 처리돼 있다. 데이터는 시드가 고정된
결정론적 생성물이므로 커밋하지 않고 `--seed 20260829`로 언제든 동일하게 재생성한다.

## 4. 지금까지 실측한 결과

`gen_dataset.py` 기본값(220 시나리오, seed 20260829) 기준이다.

**데이터셋** — 시나리오 단위 + 상황 유형별 계층화 분할이라 같은 회의의 앞뒤 턴이
train/test에 흩어지지 않고, 11개 상황 유형이 모든 split에 존재한다.

| split | 시나리오 | 턴 | SFT 샘플 | 상황 유형 |
|---|---|---|---|---|
| train | 176 | 1,215 | 2,430 | 11 / 11 |
| valid | 22 | 133 | 266 | 11 / 11 |
| test | 22 | 179 | 358 | 11 / 11 |
| **합계** | **220** | **1,527** | **3,054** | |

일지 라벨 분포(train): 상황 242 · 조치 838 · 무시 135. "발언 하나 = 사태 하나가 아니다"를
학습시키는 것이 목적이므로 조치 비중이 높고, 잡담(무시)도 11% 포함돼 있다.

**토큰 길이** (Qwen2.5-3B-Instruct 실제 토크나이저)

| 경로 | median | p95 | max |
|---|---|---|---|
| FAST | 1,195 | 1,242 | 1,295 |
| FULL | 1,549 | 1,663 | 1,740 |

train+valid p99 = 1,681 → `--max-seq-len 2048`로 잘림 없음.

**few-shot 제거 효과** — 파인튜닝의 실익이 여기서 나온다. 학습 데이터에 few-shot 예시를
넣지 않으므로(`gen_dataset.py` 기본값), 튜닝 후에는 서빙 시에도 few-shot을 뺄 수 있다.

| 경로 | few-shot 포함 | 제거 | 입력 토큰 절감 |
|---|---|---|---|
| FAST | 1,486 | 1,188 | **20.1%** |
| FULL | 2,598 | 1,549 | **40.4%** |

기획서 3-다 "명령 생성 2초 이내"와 3-라① "표출 지연 5초 이내"에 직접 기여하는 수치다.

**첫 학습 완주 결과** — Kaggle T4 x2, DDP 2프로세스, Qwen2.5-1.5B-Instruct, 1에폭.

| 항목 | 값 |
|---|---|
| 스텝 | 152 (실효 배치 16 = 2 x 4 x 2GPU) |
| 소요 | **33분 11초** (11.6~12.2 s/it) |
| eval_loss | 0.0931 → **0.0844** |
| eval 토큰 정확도 | 0.978 → **0.980** |

같은 152스텝이 수정 전에는 5시간 50분 걸렸다(그마저 완주 못 하고 죽었다). 세 가지를 고쳐
약 11배 빨라진 것이다 — ① `torch.cuda.is_bf16_supported()`가 T4에서도 True를 돌려줘 가속
경로가 없는 에뮬레이션 bf16으로 돌던 것, ② `device_map="auto"`가 모델을 T4 두 장에 쪼개
얹어 층마다 GPU 간 전송이 생기던 것, ③ GPU 두 장을 데이터 병렬로 쓰지 않던 것.

**평가 하네스 검증**

| 백엔드 | 상황유형 정확도 | COP 완전일치 | COP 셀 일치율 | 일지 kind | 키워드 정확도 | 누락률 |
|---|---|---|---|---|---|---|
| `gold` (정답 그대로) | 100% | 100% | 100% | 100% | 100% | 0% |
| `perturb --noise 0.3` | 70.4% | 75.4% | 87.9% | 73.1% | 91.7% | 9.3% |

`gold`에서 전 지표 100%가 나오므로 지표 계산식 자체는 정상이고, `perturb`에서 유의미하게
하락하므로 오류를 실제로 잡아낸다. `perturb`에서 COP 완전일치(75.4%)가 상황유형
정확도(70.4%)보다 높은 것은 정상이다 — 여러 상황 유형이 "해당 지역 cctv" 슬롯만 갖고 있어
유형을 틀려도 같은 레이아웃이 나오는 경우가 있기 때문이다. 셀 일치율이 더 높은 것도 같은
이유이며, 1순위 대형 화면(4칸)은 대부분의 유형에서 공통이라 유형을 틀려도 그 칸은 맞는다.

## 5. Colab에서 학습하기

`finetune/colab_train.ipynb`를 Colab에 올리고 **런타임 유형을 T4 GPU**로 바꾼 뒤 위에서부터 실행하면
데이터 생성 → 사전 점검 → 베이스라인 측정 → 학습 → 튜닝 후 비교까지 한 번에 진행된다.

T4는 Turing(SM 75)이라 bf16 텐서코어가 없다. 여기서 **`torch.cuda.is_bf16_supported()`를
쓰면 안 된다** — 이 함수는 `including_emulation` 기본값이 True라 T4에서도 True를 돌려주고,
그러면 가속 경로 없는 에뮬레이션 bf16으로 떨어져 몇 배 느려진다(실측: 135초/스텝).
`train_lora.py`와 `evaluate.py`는 연산 능력을 직접 보고 8.0 미만이면 fp16을 쓴다.

`--save-steps` 주기(기본 25스텝)마다 체크포인트를 남기고, 체크포인트가 있으면 자동으로
이어서 학습한다. 세션 종료 후에도 남기려면 노트북의 `USE_DRIVE = True`로 Drive에 저장한다.

| 모델 | 4bit 크기 | GPU 1장 1에폭 | GPU 2장(DDP) 1에폭 |
|---|---|---|---|
| Qwen2.5-1.5B-Instruct | ~1.1GB | 약 1h | **33분 (Kaggle T4 x2 실측)** |
| Qwen2.5-3B-Instruct | ~2.0GB | 약 2h | 약 1h (추정) |

Colab은 T4를 한 장만 주므로 위 표의 왼쪽 열에 해당한다. 두 장을 주는 Kaggle이 더 빠르다.
기획서 3-다의 "4bit 2~4GB"에 정확히 맞는 것은 3B이므로, 1.5B로 파이프라인을 완주시킨 뒤
최종 수치는 3B로 다시 돌리는 순서를 권장한다.

**Colab은 인터랙티브 세션이 브라우저 연결에 묶여 있어 자주 끊긴다.** Pro+의 "백그라운드
실행"도 2026년 기준 불안정하다는 신고가 많아([참고](https://github.com/googlecolab/colabtools/issues/5950))
믿고 쓰기 어렵다. 끊김 없이 돌리고 싶으면 아래 6절의 Kaggle 경로를 쓴다.

## 6. Kaggle에서 학습하기 — 진짜로 끊김 없이 돌리려면

`finetune/kaggle_train.ipynb`를 쓴다. Colab과 달리 Kaggle은 "Save Version → Save & Run All
(Commit)"을 누르면 그 시점 노트북이 **별도 머신에서 완전히 분리되어** 처음부터 끝까지 자동
실행된다. 브라우저를 닫아도, 컴퓨터를 꺼도 계속 돈다 — Colab의 세션-연결 모델과 근본적으로
다르다.

무료 할당량은 주당 약 30 GPU시간, 세션(커밋 실행 포함)당 최대 약 12시간, GPU는 P100(16GB) 또는
T4×2 중 선택. 시작 전 노트북 우측 Settings 패널에서 **Accelerator를 GPU로, Internet을 On으로**
바꿔야 한다(둘 다 기본값은 꺼짐/None).

쓰는 법: 1~5번 셀(GPU 확인 → 설치 → 설정 → 데이터 생성 → 사전 점검)을 먼저 인터랙티브하게
돌려 문제없는지 확인한 뒤, **Save Version → Save & Run All (Commit)**으로 나머지(베이스라인 →
학습 → 평가 → 병합)를 백그라운드로 넘긴다. Google Drive 마운트 같은 게 필요 없다 —
`/kaggle/working` 아래에 저장한 것은 커밋이 끝나면 그 버전의 Output 탭에서 그대로 받는다.

T4 두 장이 잡히면 노트북이 자동으로 데이터 병렬(DDP)로 두 장을 다 쓴다. 실효 배치는 GPU
장수와 무관하게 16으로 유지된다.

## 7. 로컬에서는 학습할 수 없다

이 저장소가 있는 개발 PC의 GPU는 **GTX 970 (4GB, Compute Capability 5.2)** 이다.

- bitsandbytes의 4bit(nf4) 커널이 Turing/Ampere 이상을 요구한다 (CC 5.2 미지원)
- bf16 연산 미지원
- VRAM 4GB로는 3B 모델 QLoRA에 부족

따라서 학습은 아래 중 하나에서 수행한다. 데이터 구축·검증·평가 하네스는 GPU 없이
로컬에서 전부 돌아가므로, 학습만 옮기면 된다.

| 환경 | VRAM | 3B QLoRA 1 epoch 예상 |
|---|---|---|
| Kaggle T4 x2 (무료) | 16GB x2 | 약 1시간 — DDP로 두 장 사용 (권장) |
| Colab T4 (무료) | 16GB | 약 2시간 — 한 장뿐이고 세션 유지가 어렵다 |
| Colab L4 / A100 | 24~40GB | 30분 안팎 |
| 부대 내 GPU 서버 (기획서 3-다: 10~12GB) | 12GB | 가능 (batch 1 + grad_accum 16 권장) |

VRAM이 모자라면 `--model Qwen/Qwen2.5-1.5B-Instruct --batch-size 1 --grad-accum 16`.

## 8. 서빙 전환 — 코드 수정 없음

`merge`로 만든 통짜 가중치를 vLLM 또는 Ollama로 올린 뒤, 앱 사이드바에서 공급자를
**"로컬 서버 (Ollama / vLLM)"** 로 바꾸면 끝이다. `modules/llm_engine.py`의 `PROVIDERS`가
`base_url`만 갈아끼우도록 이미 설계돼 있어 코드 변경이 없다.

```bash
vllm serve finetune/out/merged --served-model-name voicecue-qwen2.5-3b --port 8000
python finetune/evaluate.py --backend openai \
    --base-url http://localhost:8000/v1 --model voicecue-qwen2.5-3b
```

베이스라인과 비교할 때는 **튜닝 전 모델에만 `--few-shot`을 켠다.** 튜닝 후에는 few-shot이
필요 없어지는 것 자체가 성과이므로, 양쪽에 똑같이 켜면 절감 효과가 측정되지 않는다.

## 9. 알려진 한계

- **합성 데이터다.** 기획서 4-다①이 말한 "실제 회의록·작전상황일지"가 아니라
  `scenario_bank.py`의 템플릿에서 생성한 가상 시나리오다. 문장 다양성이 실제 회의보다
  좁으므로, 이 데이터만으로 학습한 모델은 템플릿 밖 표현에 약할 수 있다. 실데이터가
  확보되면 `scenario_bank.py`를 교체하고 `gen_dataset.py`는 그대로 쓰면 된다.
- **지표 ③(숙련도별 품질 편차)은 자동 측정 대상이 아니다.** 사람 운용자 두 집단의
  비교 실험이 필요하다. 다만 화면 배치가 플레이북 기반 결정론이라 모델 쪽 편차는
  구조적으로 0이며, 이것이 기획서가 말한 "숙련도와 무관한 일관성"의 근거다.
- **학습은 완주했지만 튜닝 전/후 지표 비교는 아직이다.** 4절의 학습 곡선은 실측이지만,
  기획서 3-라의 4개 품질 지표를 튜닝 전후로 비교한 표는 아직 없다. 노트북 8번 셀이
  그 표를 출력하므로, 다음 실행 결과로 이 문서를 갱신할 것.
- 운영 중 누적되는 사용자 보정(`user_corrections`)을 재학습에 편입하는 경로
  (기획서 4-⑤ "유지보수 시")는 `CONSTRAINT_TURNS`로 형태만 모사했다. 실제 운영 로그를
  학습 데이터로 환류하는 파이프라인은 아직 없다.
