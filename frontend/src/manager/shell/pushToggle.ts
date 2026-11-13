// 상단 바 사용자 메뉴의 '도움 알림 받기' 스위치(contract §5.2 웹 푸시).
// 켜면: 서버 공개 키 확인 → 서비스 워커(/m-sw.js, scope /manager) 등록 → 알림 권한 → 구독 → 서버에 저장.
// 끄면: 구독을 풀고 서버에서 지운다. 서버에 키가 없거나 브라우저가 웹 푸시를 못 하면 스위치를 숨긴다.
// 근로자 화면(/worker)에는 서비스 워커를 두지 않는다(scope가 /manager이고, 이 스위치를 켤 때만 등록한다).
import { useCallback, useEffect, useState } from "react";
import { deletePushSubscription, getPushConfig, savePushSubscription } from "../api/live";

export const SW_URL = "/m-sw.js";
export const SW_SCOPE = "/manager";

export type PushToggleResult = "on" | "off" | "denied" | "failed";

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
      return "on";
    } catch {
      return "failed";
    } finally {
      setBusy(false);
    }
  }, [publicKey, busy, on]);

  return { available, on, busy, toggle };
}
