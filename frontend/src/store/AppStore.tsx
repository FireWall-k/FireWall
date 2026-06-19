import React, { createContext, useContext, useState, useCallback } from "react";
import type { Task, Step, ActionType, Keyword } from "../types";
import { seedTasks, seedAssignments, seedDashboard } from "../mock/seed";

interface AppState {
  tasks: Task[];
  createTask: (rawInput: string) => Task;
  updateStep: (taskId: string, stepId: string, patch: Partial<Step>) => void;
  publishTask: (taskId: string) => void;
  getTask: (taskId: string) => Task | undefined;
}

const AppContext = createContext<AppState | null>(null);

let idCounter = 100;
const nextId = (prefix: string) => `${prefix}${idCounter++}`;

// 명세서 §3 AI 하네스를 흉내내는 목 분해 함수.
// 실제로는 POST /ai/decompose 가 LLM을 호출하지만, 데모에서는
// 간단한 규칙 기반으로 "그럴듯한" 단계 분해 결과를 생성한다.
function mockDecompose(rawInput: string): Step[] {
  const clauses = rawInput
    .replace(/주세요\.?$/, "")
    .replace(/\.$/, "")
    .split(/,|하고|한 뒤|한 후/)
    .map((s) => s.trim())
    .filter(Boolean);

  const guessAction = (text: string): ActionType => {
    if (/보|확인|살펴|점검/.test(text)) return "observe";
    if (/옮기|이동|가져가/.test(text)) return "move";
    if (/쌓|적재/.test(text)) return "stack";
    if (/넣|담/.test(text)) return "place";
    if (/들|집/.test(text)) return "pick";
    if (/확인되면|완료|체크/.test(text)) return "check";
    return "other";
  };

  const guessKeywords = (text: string): Keyword[] => {
    const nounMatch = text.match(/([가-힣]+(?:상자|부품|문서|구역|박스|제품))/);
    const verbMatch = text.match(/([가-힣]+(?:하다|해요|해주세요|봐요|옮겨요|쌓아요|넣어요))/);
    const kws: Keyword[] = [];
    if (nounMatch) kws.push({ term: nounMatch[1], pos: "noun" });
    if (verbMatch) kws.push({ term: verbMatch[1], pos: "verb" });
    if (kws.length === 0) kws.push({ term: text.slice(0, 6), pos: "noun" });
    return kws;
  };

  const toSimpleSentence = (text: string): string => {
    let s = text.trim();
    if (!/[.!?]$/.test(s)) {
      if (/요$/.test(s)) s += ".";
      else s += "해요.";
    }
    return s;
  };

  if (clauses.length === 0) {
    return [
      {
        id: nextId("s"),
        taskId: "",
        orderIndex: 1,
        sentence: toSimpleSentence(rawInput),
        keywords: guessKeywords(rawInput),
        actionType: "other",
        needsFallback: true,
        safetyFlags: ["unclear"],
      },
    ];
  }

  return clauses.map((clause, i) => {
    const actionType = guessAction(clause);
    const needsFallback = Math.random() < 0.25;
    return {
      id: nextId("s"),
      taskId: "",
      orderIndex: i + 1,
      sentence: toSimpleSentence(clause),
      keywords: guessKeywords(clause),
      actionType,
      symbol: needsFallback
        ? undefined
        : {
            id: nextId("sym"),
            source: Math.random() < 0.7 ? "ARASAAC" : "KAAC",
            imageUrl: "",
            label: clause.slice(0, 4),
            confidence: 0.7 + Math.random() * 0.25,
          },
      needsFallback,
      safetyFlags: /위험|조심|뜨거|날카/.test(clause) ? ["hazardous"] : [],
    };
  });
}

export const AppProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [tasks, setTasks] = useState<Task[]>(seedTasks);

  const createTask = useCallback((rawInput: string): Task => {
    const id = nextId("t");
    const steps = mockDecompose(rawInput).map((s) => ({ ...s, taskId: id }));
    const newTask: Task = {
      id,
      employerId: "e1",
      rawInput,
      title: rawInput.slice(0, 20) + (rawInput.length > 20 ? "…" : ""),
      status: "draft",
      createdAt: new Date().toISOString(),
      steps,
    };
    setTasks((prev) => [newTask, ...prev]);
    return newTask;
  }, []);

  const updateStep = useCallback((taskId: string, stepId: string, patch: Partial<Step>) => {
    setTasks((prev) =>
      prev.map((t) =>
        t.id !== taskId
          ? t
          : {
              ...t,
              status: t.status === "draft" ? "under_review" : t.status,
              steps: t.steps.map((s) => (s.id === stepId ? { ...s, ...patch } : s)),
            }
      )
    );
  }, []);

  const publishTask = useCallback((taskId: string) => {
    setTasks((prev) =>
      prev.map((t) => (t.id === taskId ? { ...t, status: "published" } : t))
    );
  }, []);

  const getTask = useCallback((taskId: string) => tasks.find((t) => t.id === taskId), [tasks]);

  return (
    <AppContext.Provider value={{ tasks, createTask, updateStep, publishTask, getTask }}>
      {children}
    </AppContext.Provider>
  );
};

export const useApp = (): AppState => {
  const ctx = useContext(AppContext);
  if (!ctx) throw new Error("useApp must be used within AppProvider");
  return ctx;
};

export { seedAssignments, seedDashboard };
