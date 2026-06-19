import type { Task, Worker, Assignment, PerformanceLog, DashboardSummary } from "../types";

// 명세서 §4-1 예시 응답을 기반으로 한 시드 데이터.
// 실제 백엔드 연동 전, 프론트 단독 데모를 위한 목 데이터.

export const seedWorkers: Worker[] = [
  { id: "w1", employerId: "e1", displayName: "민준" },
  { id: "w2", employerId: "e1", displayName: "지아" },
  { id: "w3", employerId: "e1", displayName: "서연" },
];

export const seedTasks: Task[] = [
  {
    id: "t1",
    employerId: "e1",
    rawInput:
      "택배 상자를 크기별로 분류하고, 큰 상자는 A구역, 작은 상자는 B구역에 5개씩 쌓아주세요.",
    title: "택배 상자 크기별 분류",
    status: "published",
    createdAt: "2026-06-15T09:00:00+09:00",
    steps: [
      {
        id: "s1",
        taskId: "t1",
        orderIndex: 1,
        sentence: "상자가 큰지 작은지 봐요.",
        keywords: [{ term: "상자", pos: "noun" }, { term: "보다", pos: "verb" }],
        actionType: "observe",
        symbol: { id: "sym1", source: "ARASAAC", imageUrl: "", label: "보기", confidence: 0.91 },
        needsFallback: false,
        safetyFlags: [],
      },
      {
        id: "s2",
        taskId: "t1",
        orderIndex: 2,
        sentence: "큰 상자는 A구역으로 옮겨요.",
        keywords: [{ term: "큰 상자", pos: "noun" }, { term: "옮기다", pos: "verb" }],
        actionType: "move",
        symbol: { id: "sym2", source: "ARASAAC", imageUrl: "", label: "옮기기", confidence: 0.88 },
        needsFallback: false,
        safetyFlags: [],
      },
      {
        id: "s3",
        taskId: "t1",
        orderIndex: 3,
        sentence: "작은 상자는 B구역으로 옮겨요.",
        keywords: [{ term: "작은 상자", pos: "noun" }, { term: "옮기다", pos: "verb" }],
        actionType: "move",
        symbol: { id: "sym3", source: "ARASAAC", imageUrl: "", label: "옮기기", confidence: 0.88 },
        needsFallback: false,
        safetyFlags: [],
      },
      {
        id: "s4",
        taskId: "t1",
        orderIndex: 4,
        sentence: "상자를 5개씩 쌓아요.",
        keywords: [{ term: "상자", pos: "noun" }, { term: "쌓다", pos: "verb" }],
        actionType: "stack",
        symbol: { id: "sym4", source: "KAAC", imageUrl: "", label: "쌓기", confidence: 0.79 },
        needsFallback: false,
        safetyFlags: [],
      },
    ],
  },
  {
    id: "t2",
    employerId: "e1",
    rawInput: "완성된 부품을 검사하고 불량품은 따로 빼주세요.",
    title: "부품 검사 및 분리",
    status: "under_review",
    createdAt: "2026-06-16T14:20:00+09:00",
    steps: [
      {
        id: "s5",
        taskId: "t2",
        orderIndex: 1,
        sentence: "부품을 하나씩 들어요.",
        keywords: [{ term: "부품", pos: "noun" }, { term: "들다", pos: "verb" }],
        actionType: "pick",
        symbol: { id: "sym5", source: "ARASAAC", imageUrl: "", label: "집기", confidence: 0.85 },
        needsFallback: false,
        safetyFlags: [],
      },
      {
        id: "s6",
        taskId: "t2",
        orderIndex: 2,
        sentence: "흠집이 있는지 살펴봐요.",
        keywords: [{ term: "흠집", pos: "noun" }, { term: "살펴보다", pos: "verb" }],
        actionType: "observe",
        needsFallback: true,
        safetyFlags: ["unclear"],
      },
      {
        id: "s7",
        taskId: "t2",
        orderIndex: 3,
        sentence: "괜찮으면 통과 상자에 넣어요.",
        keywords: [{ term: "통과 상자", pos: "noun" }, { term: "넣다", pos: "verb" }],
        actionType: "place",
        symbol: { id: "sym7", source: "ARASAAC", imageUrl: "", label: "넣기", confidence: 0.82 },
        needsFallback: false,
        safetyFlags: [],
      },
    ],
  },
  {
    id: "t3",
    employerId: "e1",
    rawInput: "사무실 문서를 스캔해서 폴더별로 정리해주세요.",
    title: "문서 스캔 및 폴더 정리",
    status: "draft",
    createdAt: "2026-06-17T08:10:00+09:00",
    steps: [
      {
        id: "s8",
        taskId: "t3",
        orderIndex: 1,
        sentence: "문서를 스캐너에 올려요.",
        keywords: [{ term: "문서", pos: "noun" }, { term: "올리다", pos: "verb" }],
        actionType: "place",
        symbol: { id: "sym8", source: "ARASAAC", imageUrl: "", label: "놓기", confidence: 0.74 },
        needsFallback: false,
        safetyFlags: [],
      },
      {
        id: "s9",
        taskId: "t3",
        orderIndex: 2,
        sentence: "스캔 버튼을 눌러요.",
        keywords: [{ term: "버튼", pos: "noun" }, { term: "누르다", pos: "verb" }],
        actionType: "other",
        needsFallback: true,
        safetyFlags: [],
      },
    ],
  },
];

export const seedAssignments: Assignment[] = [
  { id: "a1", taskId: "t1", workerId: "w1", assignedDate: "2026-06-17", status: "in_progress" },
  { id: "a2", taskId: "t1", workerId: "w2", assignedDate: "2026-06-17", status: "pending" },
];

export const seedPerformanceLogs: PerformanceLog[] = [
  { id: "p1", assignmentId: "a1", stepId: "s1", startedAt: "2026-06-17T09:00:00+09:00", completedAt: "2026-06-17T09:00:18+09:00", durationSec: 18, replayCount: 0, stuck: false },
  { id: "p2", assignmentId: "a1", stepId: "s2", startedAt: "2026-06-17T09:00:18+09:00", completedAt: "2026-06-17T09:01:40+09:00", durationSec: 82, replayCount: 2, stuck: true },
];

export const seedDashboard: DashboardSummary = {
  taskId: "t1",
  taskTitle: "택배 상자 크기별 분류",
  totalAssignments: 8,
  completedAssignments: 6,
  completionRate: 0.75,
  avgExplainTimeSavedMin: 12,
  steps: [
    { stepId: "s1", stepOrder: 1, sentence: "상자가 큰지 작은지 봐요.", avgDurationSec: 16, stuckCount: 0, replayCount: 2, completionRate: 1.0 },
    { stepId: "s2", stepOrder: 2, sentence: "큰 상자는 A구역으로 옮겨요.", avgDurationSec: 74, stuckCount: 3, replayCount: 11, completionRate: 0.88 },
    { stepId: "s3", stepOrder: 3, sentence: "작은 상자는 B구역으로 옮겨요.", avgDurationSec: 41, stuckCount: 1, replayCount: 4, completionRate: 0.95 },
    { stepId: "s4", stepOrder: 4, sentence: "상자를 5개씩 쌓아요.", avgDurationSec: 95, stuckCount: 4, replayCount: 14, completionRate: 0.81 },
  ],
};
