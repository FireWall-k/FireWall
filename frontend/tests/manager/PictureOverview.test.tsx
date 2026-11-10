import { describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import PictureOverview from "../../src/manager/tasks/editor/PictureOverview";
import { step } from "./editorFixtures";

// 그림 한눈에 보기(명세 5.5, tasks §4.4): 그림은 바로(eager) 불러오고, 체크박스는 auto_high에만,
// [보이는 자동 그림 모두 맞아요]는 체크된 그림이 모두 decode된 뒤에만 켜진다. 0개 남으면 '모두 확인했어요 · [보내기]'.
const STEPS = [
  step("s1", 1, "앞치마를 입어요.", "confirmed"),
  step("s2", 2, "컵을 물에 넣어요.", "auto_high"),
  step("s3", 3, "컵을 닦아요.", "auto_high"),
  step("s4", 4, "컵을 엎어요.", "choose"),
  step("s5", 5, "손을 씻어요.", "none"),
];

function setup(steps = STEPS) {
  const props = { steps, onBack: vi.fn(), onOpenStep: vi.fn(), onConfirmAll: vi.fn().mockResolvedValue(undefined), onSend: vi.fn() };
  const utils = render(<PictureOverview {...props} />);
  return { ...utils, props };
}

/** jsdom에는 그림 그리기가 없다: 불러옴(load)과 decode()를 흉내 낸다. */
function load(stepId: string, decode: () => Promise<void> = () => Promise.resolve()) {
  const img = document.querySelector<HTMLImageElement>(`img[data-step-picture="${stepId}"]`)!;
  Object.defineProperty(img, "decode", { configurable: true, value: decode });
  fireEvent.load(img);
}

describe("그림 한눈에 보기", () => {
  it("모든 단계를 카드로, 그림은 eager로 불러온다", () => {
    setup();
    for (let n = 1; n <= 5; n++) expect(screen.getByTestId(`overview-card-${n}`)).toBeInTheDocument();
    const imgs = Array.from(document.querySelectorAll("img"));
    expect(imgs.length).toBe(4); // 그림 없음 단계는 그림이 없다
    for (const img of imgs) expect(img).toHaveAttribute("loading", "eager");
  });

  it("체크박스는 '✦ 자동 · 확인 필요' 단계에만 있다(골라 주세요·그림 없음·확인함은 없음)", () => {
    setup();
    expect(screen.getAllByRole("checkbox")).toHaveLength(2);
    expect(screen.getByRole("checkbox", { name: "2단계 그림이 맞아요" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "3단계 그림이 맞아요" })).toBeChecked();
    for (const n of [1, 4, 5]) expect(within(screen.getByTestId(`overview-card-${n}`)).queryByRole("checkbox")).toBeNull();
  });

  it("체크된 그림 하나가 늦게 그려지면 [모두 맞아요]는 꺼져 있다 — 다 그려진 뒤에 켜진다", async () => {
    const { props } = setup();
    const btn = screen.getByTestId("confirm-all");
    expect(btn).toHaveAccessibleName("보이는 자동 그림 모두 맞아요");
    expect(btn).toHaveAttribute("aria-disabled", "true");
    expect(screen.getByText("그림을 다 불러오면 누를 수 있어요")).toBeInTheDocument();
    await act(async () => load("s2"));
    let finish!: () => void;
    await act(async () => load("s3", () => new Promise<void>((r) => (finish = r))));
    expect(btn).toHaveAttribute("aria-disabled", "true");
    fireEvent.click(btn);
    expect(props.onConfirmAll).not.toHaveBeenCalled();
    await act(async () => finish());
    expect(btn).not.toHaveAttribute("aria-disabled");
    fireEvent.click(btn);
    expect(props.onConfirmAll).toHaveBeenCalledWith(["s2", "s3"]);
  });

  it("체크를 풀면 그 그림은 기다리지 않고, 확인 목록에서도 빠진다", async () => {
    const user = userEvent.setup();
    const { props } = setup();
    await act(async () => load("s2"));
    await user.click(screen.getByRole("checkbox", { name: "3단계 그림이 맞아요" }));
    const btn = screen.getByTestId("confirm-all");
    expect(btn).not.toHaveAttribute("aria-disabled");
    await user.click(btn);
    expect(props.onConfirmAll).toHaveBeenCalledWith(["s2"]);
  });

  it("카드를 누르면 그 단계로 간다", async () => {
    const user = userEvent.setup();
    const { props } = setup();
    await user.click(screen.getByRole("button", { name: /4단계 보기/ }));
    expect(props.onOpenStep).toHaveBeenCalledWith("s4");
  });

  it("확인할 것이 0개면 '모두 확인했어요 · [보내기]'", async () => {
    const user = userEvent.setup();
    const { props } = setup([step("s1", 1, "손을 씻어요.", "confirmed"), step("s2", 2, "컵을 닦아요.", "confirmed")]);
    expect(screen.getByRole("status")).toHaveTextContent("모두 확인했어요");
    expect(screen.queryByTestId("confirm-all")).toBeNull();
    await user.click(screen.getByRole("button", { name: "보내기" }));
    expect(props.onSend).toHaveBeenCalled();
  });
});
