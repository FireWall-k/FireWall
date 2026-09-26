"""로그인 실패 횟수 제한 (표준 라이브러리만 사용, 프로세스 내 메모리).

왜 있나: 근로자 로그인은 접속 코드 하나로 되므로, 시도 횟수를 막지 않으면 코드를 차례로
넣어 보는 것만으로 다른 근로자 계정에 들어갈 수 있다(4자리면 1만 번).

지켜야 할 것:
- 성공은 세지 않는다. 실패만 세고, 창(window) 안의 실패가 한도를 넘으면 창이 풀릴 때까지 막는다.
- 한 작업장의 근로자들은 같은 IP(같은 와이파이)를 쓴다. IP 한도를 빡빡하게 잡으면 코드를
  잘못 누른 몇 명 때문에 작업장 전체가 막힌다 — 근로자 쪽 한도는 넉넉하게 둔다.
- 여러 프로세스(uvicorn --workers N)로 띄우면 프로세스마다 따로 센다. 단일 프로세스 운영을
  전제로 하며, 늘릴 때는 공유 저장소(Redis 등)로 바꿔야 한다.
"""
from __future__ import annotations

import os
import threading
import time
from collections import deque

from fastapi import HTTPException, Request


class LoginThrottle:
    def __init__(self, max_failures: int, window_sec: float) -> None:
        self.max_failures = max_failures
        self.window_sec = window_sec
        self._lock = threading.Lock()
        self._failures: dict[str, deque[float]] = {}

    def _prune(self, key: str, now: float) -> deque[float]:
        q = self._failures.setdefault(key, deque())
        while q and now - q[0] >= self.window_sec:
            q.popleft()
        if not q:
            self._failures.pop(key, None)
            return deque()
        return q

    def retry_after(self, key: str) -> int:
        """막혀 있으면 풀리기까지 남은 초, 아니면 0."""
        now = time.monotonic()
        with self._lock:
            q = self._prune(key, now)
            if len(q) < self.max_failures:
                return 0
            return max(1, int(self.window_sec - (now - q[0])) + 1)

    def fail(self, key: str) -> None:
        now = time.monotonic()
        with self._lock:
            q = self._prune(key, now)
            q.append(now)
            self._failures[key] = q

    def reset(self, key: str) -> None:
        with self._lock:
            self._failures.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._failures.clear()


# 사업주: 계정 하나에 대한 비밀번호 대입과, 한 IP에서의 여러 계정 대입을 모두 막는다.
employer_throttle = LoginThrottle(
    max_failures=int(os.getenv("LOGIN_MAX_FAILURES", "10")),
    window_sec=float(os.getenv("LOGIN_WINDOW_SEC", "900")),
)
# 근로자: IP 단위. 작업장 공용 IP를 고려해 넉넉하게(6자리 코드 기준 대입에 수년이 걸리는 수준).
worker_throttle = LoginThrottle(
    max_failures=int(os.getenv("WORKER_LOGIN_MAX_FAILURES", "30")),
    window_sec=float(os.getenv("WORKER_LOGIN_WINDOW_SEC", "600")),
)


def client_ip(request: Request) -> str:
    """요청자 IP. 리버스 프록시 뒤라면 TRUST_FORWARDED_FOR=1로 X-Forwarded-For를 믿는다.

    프록시 없이 이 값을 켜면 누구나 헤더로 IP를 바꿔 제한을 우회할 수 있다.
    """
    if os.getenv("TRUST_FORWARDED_FOR", "0") == "1":
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def ensure_not_blocked(throttle: LoginThrottle, *keys: str) -> None:
    wait = max((throttle.retry_after(k) for k in keys), default=0)
    if wait:
        raise HTTPException(
            status_code=429,
            detail=f"로그인 시도가 너무 많습니다. {max(1, wait // 60)}분 뒤에 다시 시도해 주세요.",
            headers={"Retry-After": str(wait)},
        )
