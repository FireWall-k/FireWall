// '도움 알림 받기' 스위치(contract §5.2 웹 푸시). 상단 바 사용자 메뉴와 설정 화면(3-0 M11)이 같이 쓴다.
// 켜면: 서버 공개 키 확인 → 서비스 워커(/m-sw.js, scope /manager) 등록 → 알림 권한 → 구독 → 서버에 저장.
// 끄면: 구독을 풀고 서버에서 지운다. 서버에 키가 없거나 브라우저가 웹 푸시를 못 하면 스위치를 숨긴다.
// 근로자 화면(/worker)에는 서비스 워커를 두지 않는다(scope가 /manager이고, 이 스위치를 켤 때만 등록한다).
// 한 곳에서 켜고 끄면 다른 곳(메뉴 ↔ 설정)의 스위치도 바로 같은 상태가 된다(창 이벤트 PUSH_CHANGED).
import { useCallback, useEffect, useState } from "react";
import { deletePushSubscription, getPushConfig, savePushSubscription } from "../api/live";
import { pushToggle as copy } from "../copy";

export const SW_URL = "/m-sw.js";
export const SW_SCOPE = "/manager";

export type PushToggleResult = "on" | "off" | "denied" | "failed";

/** 켜짐/꺼짐이 바뀌면 보내는 창 이벤트(detail: 켜짐 여부). */
export const PUSH_CHANGED = "jobcard:push-changed";

function announce(on: boolean) {
  window.dispatchEvent(new CustomEvent<boolean>(PUSH_CHANGED, { detail: on }));
}

/** 켜기·끄기 결과를 토스트로 보일 문장. */
export function pushToast(r: PushToggleResult): { tone: "success" | "info" | "error"; message: string } {
  if (r === "on") return { tone: "success", message: copy.turnedOn };
  if (r === "off") return { tone: "info", message: copy.turnedOff };
  if (r === "denied") return { tone: "error", message: copy.denied };
  return { tone: "error", message: copy.failed };
}

function supported(): boolean {
  return (
    typeof window !== "undefined" &&
    "serviceWorker" in navigator &&
    "PushManager" in window &&
    typeof Notification !== "undefined"
  );
}

/** VAPID 공개 키(base64url) → applicationServerKey. */
export function keyToBytes(base64url: string): Uint8Array<ArrayBuffer> {
  const pad = "=".repeat((4 - (base64url.length % 4)) % 4);
  const raw = atob((base64url + pad).replace(/-/g, "+").replace(/_/g, "/"));
  const out = new Uint8Array(new ArrayBuffer(raw.length));
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
  return out;
}

async function currentSubscription(): Promise<PushSubscription | null> {
  const reg = await navigator.serviceWorker.getRegistration(SW_SCOPE);
  return reg ? reg.pushManager.getSubscription() : null;
}

export function usePushToggle() {
  const [available, setAvailable] = useState(false);
  const [publicKey, setPublicKey] = useState<string | null>(null);
  const [on, setOn] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!supported()) return;
    let alive = true;
    getPushConfig()
      .then(async (c) => {
        if (!alive || !c.enabled || !c.public_key) return;
        setPublicKey(c.public_key);
        setAvailable(true);
        const sub = await currentSubscription().catch(() => null);
        if (alive) setOn(!!sub && Notification.permission === "granted");
      })
      .catch(() => {
        /* 키 확인이 안 되면 스위치를 보이지 않는다 */
      });
    return () => {
      alive = false;
    };
  }, []);

  useEffect(() => {
    const onChanged = (e: Event) => setOn(!!(e as CustomEvent<boolean>).detail);
    window.addEventListener(PUSH_CHANGED, onChanged);
    return () => window.removeEventListener(PUSH_CHANGED, onChanged);
  }, []);

  const toggle = useCallback(async (): Promise<PushToggleResult> => {
    if (!publicKey || busy) return "failed";
    setBusy(true);
    try {
      if (on) {
        const sub = await currentSubscription();
        if (sub) {
          await deletePushSubscription(sub.endpoint).catch(() => undefined);
          await sub.unsubscribe().catch(() => false);
        }
        setOn(false);
        announce(false);
        return "off";
      }
      const perm = await Notification.requestPermission();
      if (perm !== "granted") return "denied";
      await navigator.serviceWorker.register(SW_URL, { scope: SW_SCOPE });
      const reg = await navigator.serviceWorker.ready;
      const sub =
        (await reg.pushManager.getSubscription()) ??
        (await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: keyToBytes(publicKey) }));
      const j = sub.toJSON();
      if (!j.endpoint || !j.keys?.p256dh || !j.keys?.auth) return "failed";
      await savePushSubscription({ endpoint: j.endpoint, keys: { p256dh: j.keys.p256dh, auth: j.keys.auth } });
      setOn(true);
      announce(true);
      return "on";
    } catch {
      return "failed";
    } finally {
      setBusy(false);
    }
  }, [publicKey, busy, on]);

  return { available, on, busy, toggle };
}
