# 설리번 JOB CARD — 프론트엔드 프로토타입 (백엔드 없는 단독 데모)

`02_잡카드_기술_명세서` 기준으로 만든 React + TypeScript + Vite + Tailwind 프론트엔드입니다.
실제 백엔드/AI 하네스 없이, 명세서 §4 API 계약과 동일한 모양의 **목 데이터**로 전체 흐름을 데모합니다.

## 실행 방법

```bash
npm install
npm run dev
```

브라우저에서 `http://localhost:5173` 접속 → 자동으로 `/admin/tasks`로 이동합니다.

## 화면 구성

| 경로 | 화면 | 설명 |
|---|---|---|
| `/admin/tasks` | 사업주 직무 입력 · 검토 | 직무 텍스트 입력 → (목) AI 분해 → 단계별 검토/수정 → 게시 |
| `/admin/dashboard` | 수행 대시보드 | 단계별 평균 소요시간, 막힌 단계, 반복청취 집계 (recharts) |
| `/worker` 또는 `/worker/:taskId` | 근로자 카드 UI | 태블릿용 전체화면 카드. 그림+문장+TTS+완료 버튼만 |

사이드바 하단 "근로자 화면 미리보기" 링크로 새 탭에서 근로자 화면을 열어볼 수 있습니다.

## 명세서와의 대응 관계

- **데이터 모델** (`src/types/index.ts`) — 명세서 §2 ERD의 TASK/STEP/ASSIGNMENT/PERFORMANCE_LOG/SYMBOL_ASSET을 그대로 타입으로 옮김
- **AI 분해 목업** (`src/store/AppStore.tsx`의 `mockDecompose`) — 명세서 §3 LLM 입출력 스키마를 모사한 규칙 기반 분해. 실제로는 `POST /ai/decompose`가 LLM을 호출하는 자리
- **API 계약** (`src/mock/seed.ts`) — 명세서 §4-1 예시 응답(`{"data": ..., "error": null}`)과 동일한 필드 구조의 시드 데이터
- **접근성 요구사항** (`src/pages/WorkerCardPage.tsx`) — 명세서 §6 KWCAG 체크리스트를 구현:
  - 한 화면에 그림 1 + 문장 1 + 버튼만
  - 터치 영역 80px 이상 (완료 버튼 h-20 = 80px)
  - TTS 자동 1회 재생 (Web Speech API) + 다시 듣기 버튼 상시 노출
  - 시간 제한 없음 / 자동 넘김 없음 — 사용자가 "다 했어요"를 눌러야 다음 단계로
  - 완료 시 시각(체크 애니메이션) + 청각(TTS) 긍정 피드백

## 실제 백엔드 연동 시 바꿔야 할 부분

`src/store/AppStore.tsx`가 사실상 "가짜 백엔드"입니다. 실제 연동 시:

1. `mockDecompose()` → `POST /api/tasks` 호출로 교체 (백엔드가 AI 하네스 트리거)
2. `updateStep`, `publishTask` → 각각 `PATCH /api/tasks/{id}/steps/{stepId}`, `POST /api/tasks/{id}/publish` 호출로 교체
3. `seedDashboard` → `GET /api/dashboard/tasks/{id}` 응답으로 교체
4. 근로자 화면의 TTS는 현재 브라우저 Web Speech API를 쓰고 있음 — 실제로는 게시 시 백엔드가 미리 생성한 TTS 음성 파일(`step.ttsAudioUrl`)을 재생하도록 교체 필요
5. 상징 이미지는 현재 인라인 SVG 플레이스홀더(`src/components/Symbols.tsx`) — 실제로는 `step.symbol.imageUrl` (ARASAAC/KAAC) 또는 `fallbackImageUrl`을 렌더링

## 아직 안 만든 것 / 회의에서 정할 것

- 오프라인 캐싱 (명세서 §7) — 서비스 워커/IndexedDB 캐싱은 미구현
- 인증/권한 (JWT, 근로자 토큰) — 데모에는 로그인 없음
- 와이어프레임 단계를 건너뛰고 바로 컴포넌트로 만들었음 — 팀 회의에서 레이아웃에 대한 의견 받으면 빠르게 수정 가능
