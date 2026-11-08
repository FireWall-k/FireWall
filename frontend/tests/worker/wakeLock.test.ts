import { afterEach, describe, expect, it, vi } from "vitest";
import { acquireWakeLock, releaseWakeLock } from "../../src/worker/hooks/useWakeLock";

// 1차 검증: 요청이 답을 받기 전에 화면을 떠나면, 늦게 온 잠금을 아무도 놓지 않았다.
function install() {
  const release = vi.fn(() => Promise.resolve());
  let resolve!: () => void;
  const request = vi.fn(() => new Promise((r) => {
    resolve = () => r({ release, released: false, addEventListener: () => {} });
  }));
  Object.defineProperty(navigator, "wakeLock", { value: { request }, configurable: true });
  return { release, request, resolve: () => resolve() };
}

afterEach(() => {
  releaseWakeLock();
  delete (navigator as { wakeLock?: unknown }).wakeLock;
});

describe("화면 꺼짐 방지", () => {
  it("요청 중에 놓으면, 답이 온 뒤 바로 놓는다", async () => {
    const wl = install();
    const p = acquireWakeLock();
    releaseWakeLock();
    wl.resolve();
    await p;
    expect(wl.release).toHaveBeenCalledTimes(1);
  });

  it("요청 중에 놓지 않으면 잡고 있다가 놓을 때 놓는다", async () => {
    const wl = install();
    const p = acquireWakeLock();
    wl.resolve();
    await p;
    expect(wl.release).not.toHaveBeenCalled();
    releaseWakeLock();
    expect(wl.release).toHaveBeenCalledTimes(1);
  });
});
