import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, render, renderHook, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { ApiError } from "../../src/apiErrors";
import { workplace } from "./workers.fixtures";

// 설정(tasks §7): 사업장 이름·코드 복사, 기기 연결 QR·주소, 근로자 화면 기본값, 호칭(미리보기·한글 1~6자), 알림, 계정.
const api = { getWorkplace: vi.fn(), updateWorkplace: vi.fn() };
vi.mock("../../src/manager/api/workers", () => ({
  getWorkplace: () => api.getWorkplace(),
  updateWorkplace: (p: unknown) => api.updateWorkplace(p),
}));

// (3-0 M11) '도움 알림 받기' 스위치는 상단 바와 같은 usePushToggle을 쓴다. 서버 호출만 가짜로 바꾼다.
const live = { getPushConfig: vi.fn(), savePushSubscription: vi.fn(), deletePushSubscription: vi.fn() };
vi.mock("../../src/manager/api/live", () => ({
  getPushConfig: () => live.getPushConfig(),
  savePushSubscription: (s: unknown) => live.savePushSubscription(s),
  deletePushSubscription: (e: unknown) => live.deletePushSubscription(e),
}));

import SettingsPage from "../../src/manager/settings/SettingsPage";
import { usePushToggle } from "../../src/manager/shell/pushToggle";
import { ToastProvider } from "../../src/components/ui";

const onLogout = vi.fn();
function renderPage() {
  return render(
    <ToastProvider>
      <MemoryRouter>
        <SettingsPage displayName="데모 사장님" onLogout={onLogout} />
      </MemoryRouter>
    </ToastProvider>,
  );
}

/** 웹 푸시를 할 수 있는 브라우저처럼 꾸민다(jsdom에는 서비스 워커·PushManager·Notification이 없다). */
const ENDPOINT = "https://fcm.googleapis.com/fcm/send/e2e";
function stubPushBrowser() {
  let current: { endpoint: string; toJSON: () => object; unsubscribe: () => Promise<boolean> } | null = null;
  const sub = {
    endpoint: ENDPOINT,
    toJSON: () => ({ endpoint: ENDPOINT, keys: { p256dh: "p256", auth: "auth" } }),
    unsubscribe: vi.fn(async () => {
      current = null;
      return true;
    }),
  };
  const reg = {
    pushManager: {
      getSubscription: vi.fn(async () => current),
      subscribe: vi.fn(async () => (current = sub)),
    },
  };
  vi.stubGlobal("PushManager", function PushManager() {});
  vi.stubGlobal("Notification", { permission: "default", requestPermission: vi.fn(async () => "granted") });
  Object.defineProperty(navigator, "serviceWorker", {
    configurable: true,
    value: {
      getRegistration: vi.fn(async () => (current ? reg : undefined)),
      register: vi.fn(async () => reg),
      ready: Promise.resolve(reg),
    },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
  delete (navigator as unknown as { serviceWorker?: unknown }).serviceWorker;
});

beforeEach(() => {
  live.getPushConfig.mockReset().mockResolvedValue({ enabled: true, public_key: "AQAB" });
  live.savePushSubscription.mockReset().mockResolvedValue({ ok: true });
  live.deletePushSubscription.mockReset().mockResolvedValue(undefined);
  api.getWorkplace.mockReset().mockResolvedValue(workplace());
  api.updateWorkplace.mockReset();
  onLogout.mockReset();
});

describe("설정", () => {
  it("사업장 코드·기기 연결 주소·QR이 보이고 PIN 칸은 없다", async () => {
    renderPage();
    expect(await screen.findByTestId("workplace-code")).toHaveTextContent("DEMO01");
    expect(screen.getByTestId("device-link")).toHaveTextContent("http://localhost:5173/worker?site=DEMO01");
    expect(screen.getByRole("img", { name: "기기 연결 주소" })).toBeInTheDocument();
    expect(screen.queryByText(/PIN|선생님 모드/)).toBeNull();
  });

  it("웹 푸시를 못 하는 브라우저면 '도움 알림 받기'는 꺼진 채 막혀 있고 켤 수 없다고 알린다", async () => {
    renderPage();
    await screen.findByTestId("workplace-code");
    const sw = screen.getByRole("switch", { name: "도움 알림 받기" });
    expect(sw).toBeDisabled();
    expect(sw).toHaveAttribute("aria-checked", "false");
    expect(sw).toHaveAccessibleDescription(/이 기기에서는 아직 도움 알림을 켤 수 없어요\./);
    expect(screen.queryByText(/다음 업데이트/)).toBeNull();
  });

  it("'도움 알림 받기'를 켜면 구독을 서버에 저장하고, 끄면 지운다(상단 바 메뉴 스위치와 같은 동작)", async () => {
    stubPushBrowser();
    const user = userEvent.setup();
    renderPage();
    const sw = await screen.findByRole("switch", { name: "도움 알림 받기" });
    await waitFor(() => expect(sw).toBeEnabled());
    expect(sw).toHaveAttribute("aria-checked", "false");
    expect(sw).not.toHaveAccessibleDescription(/켤 수 없어요/);

    await user.click(sw);
    await waitFor(() => expect(sw).toHaveAttribute("aria-checked", "true"));
    expect(live.savePushSubscription).toHaveBeenCalledWith({ endpoint: ENDPOINT, keys: { p256dh: "p256", auth: "auth" } });
    expect(await screen.findByText("도움 알림을 켰어요. 이 화면을 안 보고 있어도 알려 드려요.")).toBeInTheDocument();

    await user.click(sw);
    await waitFor(() => expect(sw).toHaveAttribute("aria-checked", "false"));
    expect(live.deletePushSubscription).toHaveBeenCalledWith(ENDPOINT);
    expect(await screen.findByText("도움 알림을 껐어요")).toBeInTheDocument();
  });

  it("알림 권한을 거절하면 꺼진 채로 두고 브라우저 설정을 안내한다", async () => {
    stubPushBrowser();
    (Notification as unknown as { requestPermission: () => Promise<string> }).requestPermission = vi.fn(async () => "denied");
    const user = userEvent.setup();
    renderPage();
    const sw = await screen.findByRole("switch", { name: "도움 알림 받기" });
    await waitFor(() => expect(sw).toBeEnabled());
    await user.click(sw);
    expect(await screen.findByText("브라우저가 알림을 막고 있어요. 브라우저 설정에서 알림을 허용해 주세요.")).toBeInTheDocument();
    expect(sw).toHaveAttribute("aria-checked", "false");
    expect(live.savePushSubscription).not.toHaveBeenCalled();
  });

  it("설정에서 켜면 다른 화면의 스위치(상단 바 메뉴)도 바로 켜짐이 된다", async () => {
    stubPushBrowser();
    const user = userEvent.setup();
    const menu = renderHook(() => usePushToggle());
    await waitFor(() => expect(menu.result.current.available).toBe(true));
    expect(menu.result.current.on).toBe(false);
    renderPage();
    const sw = await screen.findByRole("switch", { name: "도움 알림 받기" });
    await waitFor(() => expect(sw).toBeEnabled());
    await user.click(sw);
    await waitFor(() => expect(menu.result.current.on).toBe(true));
    await act(async () => {
      await menu.result.current.toggle();
    });
    expect(sw).toHaveAttribute("aria-checked", "false");
  });

  it("호칭 미리보기: 받침 없는 '코치'를 적으면 '코치를 불렀어요'·'코치가 확인했어요'로 바로 바뀐다", async () => {
    const user = userEvent.setup();
    renderPage();
    const input = await screen.findByLabelText(/^호칭/);
    const preview = screen.getByTestId("title-preview");
    expect(preview).toHaveTextContent("선생님을 불렀어요. 여기서 기다려요.");
    expect(preview).toHaveTextContent("선생님이 확인했어요");
    await user.clear(input);
    await user.type(input, "코치");
    expect(preview).toHaveTextContent("코치를 불렀어요. 여기서 기다려요.");
    expect(preview).toHaveTextContent("코치가 확인했어요");
    expect(preview).toHaveTextContent("코치께 번호를 물어봐요.");
    api.updateWorkplace.mockResolvedValue(workplace({ teacher_title: "코치" }));
    await user.click(screen.getByRole("button", { name: "호칭 저장하기" }));
    await waitFor(() => expect(api.updateWorkplace).toHaveBeenCalledWith({ teacher_title: "코치" }));
    expect(await screen.findByText("호칭을 저장했어요")).toBeInTheDocument();
  });

  it("호칭이 한글 1~6자가 아니면 서버에 보내지 않고 같은 문장을 보인다", async () => {
    const user = userEvent.setup();
    renderPage();
    const input = await screen.findByLabelText(/^호칭/);
    await user.clear(input);
    await user.type(input, "Coach");
    await user.click(screen.getByRole("button", { name: "호칭 저장하기" }));
    expect(screen.getByText("호칭은 한글 1~6자로 적어 주세요.")).toBeInTheDocument();
    expect(api.updateWorkplace).not.toHaveBeenCalled();
  });

  it("서버가 422를 주면 서버 문장을 칸 아래에", async () => {
    api.updateWorkplace.mockRejectedValue(new ApiError(422, "사업장 이름을 1~40자로 적어 주세요."));
    const user = userEvent.setup();
    renderPage();
    const input = await screen.findByLabelText("사업장 이름");
    await user.clear(input);
    await user.type(input, "새 이름");
    await user.click(screen.getByRole("button", { name: "이름 저장하기" }));
    expect(await screen.findByText("사업장 이름을 1~40자로 적어 주세요.")).toBeInTheDocument();
  });

  it("근로자 화면 기본값: 말 속도 0.8은 worker_defaults 그 키만 보낸다", async () => {
    api.updateWorkplace.mockImplementation(async (p: { worker_defaults: object }) =>
      workplace({ worker_defaults: { ...workplace().worker_defaults, ...p.worker_defaults } }),
    );
    const user = userEvent.setup();
    renderPage();
    const group = await screen.findByRole("group", { name: "말 속도" });
    await user.click(within(group).getByRole("radio", { name: "느리게 0.8" }));
    await waitFor(() => expect(api.updateWorkplace).toHaveBeenCalledWith({ worker_defaults: { tts_rate: 0.8 } }));
    expect(screen.getByText("새로 추가하는 근로자에게 이 값이 들어가요. 이미 있는 근로자는 바뀌지 않아요.")).toBeInTheDocument();
  });

  it("[인쇄용 카드 만들기]는 사업장 이름·QR·사업장 코드 카드를 연다", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.click(await screen.findByRole("button", { name: "인쇄용 카드 만들기" }));
    const card = screen.getByRole("dialog", { name: "기기 연결 카드" });
    expect(within(card).getByText("햇살카페")).toBeInTheDocument();
    expect(within(card).getByText("DEMO01")).toBeInTheDocument();
    expect(within(card).getByRole("img", { name: "기기 연결 QR 코드" })).toBeInTheDocument();
  });

  it("계정: 이름과 [로그아웃]", async () => {
    const user = userEvent.setup();
    renderPage();
    expect(await screen.findByText("데모 사장님")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "로그아웃" }));
    expect(onLogout).toHaveBeenCalled();
  });
});
