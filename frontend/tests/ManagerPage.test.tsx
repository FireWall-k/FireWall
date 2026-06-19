import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import ManagerPage from "../src/pages/ManagerPage";

const createTask = vi.fn();
const uploadStepPhoto = vi.fn();
const removeStepPhoto = vi.fn();

vi.mock("../src/api", () => ({
  api: {
    createTask: (raw: string, ctx: unknown) => createTask(raw, ctx),
    uploadStepPhoto: (t: string, s: string, f: File) => uploadStepPhoto(t, s, f),
    removeStepPhoto: (t: string, s: string) => removeStepPhoto(t, s),
    searchArasaac: vi.fn(),
    publish: vi.fn(),
    assign: vi.fn(),
    updateStep: vi.fn(),
  },
}));

const baseStep = {
  id: "s1", order: 1, sentence: "상자를 옮기세요", action_type: "move",
  symbol_url: null as string | null, symbol_source: "fallback", needs_fallback: true,
  tts_audio_url: null as string | null,
};

beforeEach(() => {
  createTask.mockReset();
  uploadStepPhoto.mockReset();
  removeStepPhoto.mockReset();
  createTask.mockResolvedValue({ id: "task-1", title: "직무", status: "draft", steps: [baseStep] });
});

describe("ManagerPage 사진 업로드 (기능 5)", () => {
  it("단계에 사진을 올리면 uploadStepPhoto를 호출하고 상징이 사진으로 바뀐다", async () => {
    uploadStepPhoto.mockResolvedValue({
      ...baseStep, symbol_url: "http://localhost:8000/api/photos/x.png",
      symbol_source: "photo", needs_fallback: false,
    });

    render(<ManagerPage />);
    fireEvent.click(screen.getByText("단계로 나누기"));
    // 단계가 렌더되면 '사진 올리기' 라벨이 보인다(문장은 input value라 텍스트로 안 잡힘).
    await screen.findByText("사진 올리기");

    const fileInput = screen.getByLabelText("1단계 사진 업로드") as HTMLInputElement;
    const file = new File([new Uint8Array([0x89, 0x50, 0x4e, 0x47])], "p.png", { type: "image/png" });
    fireEvent.change(fileInput, { target: { files: [file] } });

    await waitFor(() => expect(uploadStepPhoto).toHaveBeenCalledWith("task-1", "s1", file));
    // 업로드 후 '사진 교체' + '되돌리기' 노출
    await screen.findByText("사진 교체");
    expect(screen.getByText("되돌리기")).toBeInTheDocument();
    expect(screen.getByText(/직접 등록한 사진/)).toBeInTheDocument();
  });

  it("'되돌리기'를 누르면 removeStepPhoto를 호출한다", async () => {
    createTask.mockResolvedValue({
      id: "task-1", title: "직무", status: "draft",
      steps: [{ ...baseStep, symbol_url: "http://localhost:8000/api/photos/x.png",
                symbol_source: "photo", needs_fallback: false }],
    });
    removeStepPhoto.mockResolvedValue({ ...baseStep });

    render(<ManagerPage />);
    fireEvent.click(screen.getByText("단계로 나누기"));
    await screen.findByText("되돌리기");
    fireEvent.click(screen.getByText("되돌리기"));
    await waitFor(() => expect(removeStepPhoto).toHaveBeenCalledWith("task-1", "s1"));
  });
});
