import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Checkbox, Field, Input, Select, Switch, Textarea } from "../../src/components/ui";

describe("Field(보이는 라벨·도움말·오류)", () => {
  it("라벨이 입력칸과 연결되고 도움말은 설명으로 읽힌다", () => {
    render(
      <Field label="직무 이름" hint="1~40자로 적어 주세요">
        <Input />
      </Field>,
    );
    const input = screen.getByLabelText("직무 이름");
    expect(input).toHaveAccessibleDescription("1~40자로 적어 주세요");
    expect(input).not.toHaveAttribute("aria-invalid");
  });

  it("오류가 있으면 aria-invalid와 오류 문장이 설명으로 붙는다", () => {
    render(
      <Field label="직무 이름" hint="1~40자" error="제목을 1~40자로 적어 주세요.">
        <Input />
      </Field>,
    );
    const input = screen.getByLabelText("직무 이름");
    expect(input).toHaveAttribute("aria-invalid", "true");
    expect(input).toHaveAccessibleDescription("1~40자 제목을 1~40자로 적어 주세요.");
  });

  it("Textarea·Select도 같은 방식으로 연결된다, 비활성도 전해진다", () => {
    render(
      <>
        <Field label="메모">
          <Textarea />
        </Field>
        <Field label="언제" disabled>
          <Select>
            <option>오늘</option>
          </Select>
        </Field>
      </>,
    );
    expect(screen.getByLabelText("메모").tagName).toBe("TEXTAREA");
    expect(screen.getByLabelText("언제")).toBeDisabled();
  });

  it("Checkbox는 글자 라벨을 눌러도 바뀐다", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<Checkbox label="김민지 님" onChange={onChange} />);
    await user.click(screen.getByText("김민지 님"));
    expect(onChange).toHaveBeenCalledWith(true);
    expect(screen.getByRole("checkbox", { name: "김민지 님" })).toBeChecked();
  });

  it("Switch는 role=switch + aria-checked, 누르면 바뀐다", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<Switch label="소리 자동 재생" hint="단계가 바뀌면 문장을 읽어 줘요" checked={false} onChange={onChange} />);
    const sw = screen.getByRole("switch", { name: "소리 자동 재생" });
    expect(sw).toHaveAttribute("aria-checked", "false");
    expect(sw).toHaveAccessibleDescription("단계가 바뀌면 문장을 읽어 줘요");
    await user.click(sw);
    expect(onChange).toHaveBeenCalledWith(true);
  });
});
