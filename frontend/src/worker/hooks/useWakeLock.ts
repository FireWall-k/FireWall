// 화면 꺼짐 방지(명세 3.5·7.1 useWakeLock). 일하는 동안 휴대폰 화면이 꺼지면 근로자는 다시 켜고 번호를
// 넣어야 하는 줄 안다. [시작하기]를 누를 때 켜고, 다른 앱에 갔다 오면(visibilitychange) 다시 켜고,
// 직무 화면을 떠나면 끈다. 지원하지 않는 브라우저(iOS 옛 Safari 등)에서는 조용히 아무것도 하지 않는다.
import { useEffect } from "react";

interface Sentinel {
  release: () => Promise<void>;
  released?: boolean;
  addEventListener?: (type: "release", fn: () => void) => void;
}

interface WakeLockApi {
  request: (type: "screen") => Promise<Sentinel>;
}

let sentinel: Sentinel | null = null;
let pending: Promise<void> | null = null;

function api(): WakeLockApi | null {
  if (typeof navigator === "undefined") return null;
  const wl = (navigator as Navigator & { wakeLock?: WakeLockApi }).wakeLock;
  return wl && typeof wl.request === "function" ? wl : null;
}

/** 화면 꺼짐 방지를 켠다. 이미 켜져 있으면 그대로 둔다. */
export function acquireWakeLock(): Promise<void> {
  const wl = api();
  if (!wl) return Promise.resolve();
  if (sentinel && !sentinel.released) return Promise.resolve();
  if (typeof document !== "undefined" && document.visibilityState === "hidden") return Promise.resolve();
  if (pending) return pending;
  pending = wl
    .request("screen")
    .then((s) => {
      sentinel = s;
      s.addEventListener?.("release", () => {
        if (sentinel === s) sentinel = null;
      });
    })
    .catch(() => {
      /* 배터리 절약 모드 등으로 거절되면 무시 */
    })
    .finally(() => {
      pending = null;
    });
  return pending;
}

export function releaseWakeLock(): void {
  const s = sentinel;
  sentinel = null;
  s?.release().catch(() => {});
}

/** 켜 둔 화면에 있는 동안 꺼짐 방지를 유지한다(다른 앱에 갔다 오면 브라우저가 풀어 버리므로 다시 켠다). */
export function useWakeLock(enabled: boolean): void {
  useEffect(() => {
    if (!enabled) return;
    void acquireWakeLock();
    const onVisible = () => {
      if (document.visibilityState === "visible") void acquireWakeLock();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      document.removeEventListener("visibilitychange", onVisible);
      releaseWakeLock();
    };
  }, [enabled]);
}
