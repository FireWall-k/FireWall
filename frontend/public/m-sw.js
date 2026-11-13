// 사업주 화면(/manager) 도움 알림 서비스 워커(contract §5.2). scope는 '/manager'이라 근로자 화면(/worker)은 이 워커가 맡지 않는다.
// push와 notificationclick만 다룬다. fetch 처리기는 두지 않는다(화면·API 요청을 가로채거나 캐시하지 않음).
// 알림 글에 근로자 이름을 넣지 않는다(잠금 화면에 보일 수 있음): 서버가 '도움 요청이 있어요'만 보낸다.
self.addEventListener("install", () => {
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(self.clients.claim());
});

self.addEventListener("push", (event) => {
  let data = {};
  try {
    data = event.data ? event.data.json() : {};
  } catch {
    data = {};
  }
  const title = typeof data.title === "string" && data.title ? data.title : "잡카드";
  const body = typeof data.body === "string" && data.body ? data.body : "도움 요청이 있어요";
  const url = typeof data.url === "string" && data.url.startsWith("/manager") ? data.url : "/manager#help";
  event.waitUntil(
    self.registration.showNotification(title, {
      body,
      tag: "jobcard-help",
      renotify: true,
      data: { url },
    }),
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = (event.notification.data && event.notification.data.url) || "/manager#help";
  event.waitUntil(
    (async () => {
      const list = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
      for (const c of list) {
        const path = new URL(c.url).pathname;
        if (path === "/manager" || path.startsWith("/manager/")) {
          await c.focus();
          if ("navigate" in c) await c.navigate(url).catch(() => undefined);
          return;
        }
      }
      await self.clients.openWindow(url);
    })(),
  );
});
