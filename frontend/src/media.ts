// 사진·음성 서명 URL 만료 대응 도우미 (Phase 0.3).
//
// 백엔드는 업로드 사진·TTS를 공개 경로로 내주지 않고, API 응답마다 짧은 수명의 서명 URL
// (/api/media/<id>?exp=&sig=)을 싣는다. <img>/<audio>는 Authorization 헤더를 못 보내기 때문이다.
// 근로자 화면은 하루 종일 켜 둘 수 있어, 처음 받은 URL이 중간에 만료된다(403). 그때 화면이 응답을
// 다시 조회해 새 URL로 바꿔 끼우면 된다 — 화면 상태(지금 보는 직무·단계)는 그대로 두고 URL만 바꾼다.
// api.ts와 분리한 이유: 화면 테스트들이 "../src/api"를 통째로 목으로 바꾸므로(workerCodes.ts와 같은 이유).
import { useCallback, useEffect, useRef } from "react";

interface MediaFields {
  id: string;
  symbol_url: string | null;
  tts_audio_url: string | null;
}

/** 만료되는 서명 URL인지. 자체 AAC 그림(/api/aac/images)은 공개 자산이라 다시 조회해도 바뀌지 않는다. */
export function isSignedMediaUrl(url: string | null | undefined): url is string {
  return !!url && url.includes("/api/media/");
}

/**
 * 다시 조회한 응답(fresh)의 사진·음성 URL만 지금 화면 데이터(current)에 옮긴다(단계 id로 맞춘다).
 *
 * 응답을 통째로 바꾸지 않는 이유: 오늘 할 일 목록은 완료한 직무가 빠지므로, 통째로 바꾸면 지금 보고 있는
 * 직무의 순번(cardIdx)이 다른 직무를 가리키게 된다. fresh에 없는 단계(그사이 지워진 단계)는 그대로 둔다.
 */
export function mergeStepMedia<S extends MediaFields, C extends { steps: S[] }>(
  current: C[],
  fresh: { steps: MediaFields[] }[],
): C[] {
  const byId = new Map<string, MediaFields>();
  fresh.forEach((c) => c.steps.forEach((s) => byId.set(s.id, s)));
  return current.map((c) => ({
    ...c,
    steps: c.steps.map((s) => {
      const f = byId.get(s.id);
      return f ? { ...s, symbol_url: f.symbol_url, tts_audio_url: f.tts_audio_url } : s;
    }),
  }));
}

/**
 * 서명 URL을 못 불러왔을 때(img onError, audio.play 실패) 부를 함수를 돌려준다. 그 URL로는 한 번만
 * refetch를 부른다 — 다시 받은 URL도 실패하면(파일이 지워짐 등) 같은 URL로 무한히 재조회하지 않는다.
 */
export function useMediaRefresh(refetch: () => Promise<void>): (url: string | null | undefined) => void {
  const tried = useRef(new Set<string>());
  const latest = useRef(refetch);
  useEffect(() => {
    latest.current = refetch;
  });
  return useCallback((url: string | null | undefined) => {
    if (!isSignedMediaUrl(url) || tried.current.has(url)) return;
    tried.current.add(url);
    latest.current().catch(() => {
      // 재조회 실패(오프라인 등)는 화면을 막지 않는다. 그림 없음 / 브라우저 음성으로 계속 진행한다.
    });
  }, []);
}
