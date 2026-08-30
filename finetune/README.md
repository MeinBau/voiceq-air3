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
| 4-다② 모델 학습 | Qwen2.5 / Llama-3, LoRA | `train_lora.py` (QLoRA) + `colab_train.ipynb` | ⏸ 스크립트·노트북 완성, 학습 미실행 |
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

# ④ 학습 (GPU 필요 — Colab은 finetune/colab_train.ipynb, 상세는 5절)
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

T4는 Turing(SM 75)이라 **bfloat16을 지원하지 않는다.** `train_lora.py`와 `evaluate.py`는
`torch.cuda.is_bf16_supported()`로 GPU를 보고 bf16/fp16을 고르므로 T4에서도 그대로 돌아간다.
이 분기가 없으면 학습이 시작도 못 하고 죽는다.

에폭마다 체크포인트를 남기고, 체크포인트가 있으면 자동으로 이어서 학습한다(무료 Colab 세션이
끊길 수 있으므로). 세션 종료 후에도 남기려면 노트북의 `USE_DRIVE = True`로 Drive에 저장한다.

| 모델 | 4bit 크기 | T4 1 에폭 | 2 에폭 | 3 에폭 |
|---|---|---|---|---|
| Qwen2.5-1.5B-Instruct | ~1.1GB | 약 1.2h | 약 2.4h | 약 3.6h |
| Qwen2.5-3B-Instruct | ~2.0GB | 약 2.4h | 약 4.8h | 약 7.2h |

기획서 3-다의 "4bit 2~4GB"에 정확히 맞는 것은 3B지만, 무료 T4에서 3에폭은 7시간이라 세션이
끊길 가능성이 높다. **1.5B/2에폭으로 파이프라인을 먼저 완주시키고, 최종 수치는 3B로** 다시
돌리는 순서를 권장한다(3B는 L4/A100 또는 Colab Pro).

## 6. 로컬에서는 학습할 수 없다

이 저장소가 있는 개발 PC의 GPU는 **GTX 970 (4GB, Compute Capability 5.2)** 이다.

- bitsandbytes의 4bit(nf4) 커널이 Turing/Ampere 이상을 요구한다 (CC 5.2 미지원)
- bf16 연산 미지원
- VRAM 4GB로는 3B 모델 QLoRA에 부족

따라서 학습은 아래 중 하나에서 수행한다. 데이터 구축·검증·평가 하네스는 GPU 없이
로컬에서 전부 돌아가므로, 학습만 옮기면 된다.

| 환경 | VRAM | 3B QLoRA 3 epoch 예상 |
|---|---|---|
| Colab T4 (무료) | 16GB | 가능하지만 약 7시간 — 세션 유지가 어렵다 (5절 참고) |
| Colab L4 / A100 | 24~40GB | 1~2시간 |
| 부대 내 GPU 서버 (기획서 3-다: 10~12GB) | 12GB | 가능 (batch 1 + grad_accum 16 권장) |

VRAM이 모자라면 `--model Qwen/Qwen2.5-1.5B-Instruct --batch-size 1 --grad-accum 16`.

## 7. 서빙 전환 — 코드 수정 없음

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

## 8. 알려진 한계

- **합성 데이터다.** 기획서 4-다①이 말한 "실제 회의록·작전상황일지"가 아니라
  `scenario_bank.py`의 템플릿에서 생성한 가상 시나리오다. 문장 다양성이 실제 회의보다
  좁으므로, 이 데이터만으로 학습한 모델은 템플릿 밖 표현에 약할 수 있다. 실데이터가
  확보되면 `scenario_bank.py`를 교체하고 `gen_dataset.py`는 그대로 쓰면 된다.
- **지표 ③(숙련도별 품질 편차)은 자동 측정 대상이 아니다.** 사람 운용자 두 집단의
  비교 실험이 필요하다. 다만 화면 배치가 플레이북 기반 결정론이라 모델 쪽 편차는
  구조적으로 0이며, 이것이 기획서가 말한 "숙련도와 무관한 일관성"의 근거다.
- **아직 학습을 돌리지 않았다.** 위 4절의 수치는 데이터셋·하네스 검증 결과이고,
  모델 성능 수치가 아니다. 학습 후 `evaluate.py --backend hf` 결과로 갱신할 것.
- 운영 중 누적되는 사용자 보정(`user_corrections`)을 재학습에 편입하는 경로
  (기획서 4-⑤ "유지보수 시")는 `CONSTRAINT_TURNS`로 형태만 모사했다. 실제 운영 로그를
  학습 데이터로 환류하는 파이프라인은 아직 없다.
