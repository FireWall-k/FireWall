import { describe, it, expect } from "vitest";
import { isSignedMediaUrl, mergeStepMedia } from "../src/media";

const step = (id: string, symbol_url: string | null, tts_audio_url: string | null = null) => ({
  id, order: 1, sentence: id, action_type: "move", symbol_source: "photo", needs_fallback: false,
  symbol_url, tts_audio_url,
});

describe("서명 URL 만료 대응(Phase 0.3)", () => {
  it("서명 URL만 만료 대상으로 본다(AAC 그림은 공개 자산)", () => {
    expect(isSignedMediaUrl("http://x/api/media/abc?exp=1&sig=s")).toBe(true);
    expect(isSignedMediaUrl("http://x/api/aac/images/cafe/CAFE_001.webp")).toBe(false);
    expect(isSignedMediaUrl(null)).toBe(false);
  });

  it("다시 받은 응답의 URL만 단계 id로 옮기고, 목록 순서·다른 필드는 그대로 둔다", () => {
    const current = [
      { assignment_id: "a1", steps: [step("s1", "old-1", "old-a"), step("s2", null)] },
      { assignment_id: "a2", steps: [step("s3", "old-3")] },
    ];
    // 다시 받은 오늘 목록에서는 a1이 완료돼 빠졌다 — 통째로 바꾸면 보던 직무 순번이 어긋난다.
    const fresh = [{ steps: [step("s3", "new-3")] }, { steps: [step("s1", "new-1", "new-a")] }];
    const merged = mergeStepMedia(current, fresh);
    expect(merged.map((c) => c.assignment_id)).toEqual(["a1", "a2"]);
    expect(merged[0].steps[0]).toMatchObject({ id: "s1", symbol_url: "new-1", tts_audio_url: "new-a" });
    expect(merged[0].steps[1].symbol_url).toBeNull();
    expect(merged[1].steps[0].symbol_url).toBe("new-3");
  });
});
