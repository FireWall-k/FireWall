// 편집기 ?fix= 처리(2b-2): 코칭 카드·도움 띠가 붙인 fix로 그 단계의 창을 바로 열고, 한 번 쓰면 주소에서 지운다.
import { render, screen } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { fixAction, useFixParam } from "../../src/manager/tasks/editor/fixParam";

describe("fixAction", () => {
  it("picture는 그림 찾기, photo는 사진 올리기", () => {
    expect(fixAction("picture")).toEqual({ kind: "picker", mode: "search" });
    expect(fixAction("photo")).toEqual({ kind: "picker", mode: "photo" });
  });
  it("split·easy_words는 상세만 연다", () => {
    expect(fixAction("split")).toEqual({ kind: "detail" });
    expect(fixAction("easy_words")).toEqual({ kind: "detail" });
  });
  it("모르는 값·빈 값은 무시", () => {
    expect(fixAction("delete")).toBeNull();
    expect(fixAction("")).toBeNull();
    expect(fixAction(null)).toBeNull();
  });
});

function Probe(props: { ready: boolean; steps: string[]; onPicker: (id: string, mode: "search" | "photo") => void }) {
  useFixParam({ ready: props.ready, hasStep: (id) => props.steps.includes(id), onPicker: props.onPicker });
  const loc = useLocation();
  return <p data-testid="search">{loc.search}</p>;
}

function renderAt(url: string, props: Omit<Parameters<typeof Probe>[0], "onPicker">) {
  const onPicker = vi.fn();
  const view = render(
    <MemoryRouter initialEntries={[url]}>
      <Probe {...props} onPicker={onPicker} />
    </MemoryRouter>,
  );
  return { onPicker, view };
}

describe("useFixParam", () => {
  it("불러온 뒤 ?step=의 그림 찾기를 한 번 열고 fix만 지운다(step은 남김)", () => {
    const { onPicker } = renderAt("/m/tasks/t1?step=s2&fix=picture", { ready: true, steps: ["s1", "s2"] });
    expect(onPicker).toHaveBeenCalledTimes(1);
    expect(onPicker).toHaveBeenCalledWith("s2", "search");
    expect(screen.getByTestId("search").textContent).toBe("?step=s2");
  });

  it("fix=photo는 사진 올리기", () => {
    const { onPicker } = renderAt("/m/tasks/t1?step=s1&fix=photo", { ready: true, steps: ["s1"] });
    expect(onPicker).toHaveBeenCalledWith("s1", "photo");
  });

  it("아직 불러오기 전이면 기다린다(창도 안 열고 주소도 그대로)", () => {
    const { onPicker, view } = renderAt("/m/tasks/t1?step=s1&fix=picture", { ready: false, steps: [] });
    expect(onPicker).not.toHaveBeenCalled();
    expect(screen.getByTestId("search").textContent).toBe("?step=s1&fix=picture");
    view.rerender(
      <MemoryRouter initialEntries={["/m/tasks/t1?step=s1&fix=picture"]}>
        <Probe ready steps={["s1"]} onPicker={onPicker} />
      </MemoryRouter>,
    );
    expect(onPicker).toHaveBeenCalledWith("s1", "search");
  });

  it("직무에 없는 단계·step 없음·split은 창을 열지 않고 fix만 지운다", () => {
    for (const url of ["/m/tasks/t1?step=gone&fix=picture", "/m/tasks/t1?fix=picture", "/m/tasks/t1?step=s1&fix=split"]) {
      const { onPicker, view } = renderAt(url, { ready: true, steps: ["s1"] });
      expect(onPicker).not.toHaveBeenCalled();
      expect(screen.getByTestId("search").textContent).not.toContain("fix=");
      view.unmount();
    }
  });

  it("fix가 없으면 아무것도 하지 않는다", () => {
    const { onPicker } = renderAt("/m/tasks/t1?step=s1", { ready: true, steps: ["s1"] });
    expect(onPicker).not.toHaveBeenCalled();
    expect(screen.getByTestId("search").textContent).toBe("?step=s1");
  });
});
