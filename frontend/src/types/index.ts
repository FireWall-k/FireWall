// 02_잡카드_기술_명세서 §2 데이터 모델 기반 타입 정의

export type TaskStatus = "draft" | "under_review" | "published" | "archived";
export type ActionType = "observe" | "move" | "stack" | "pick" | "place" | "check" | "other";
export type SafetyFlag = "unclear" | "hazardous";
export type SymbolSource = "ARASAAC" | "KAAC" | "fallback";

export interface Keyword {
  term: string;
  pos: "noun" | "verb";
}

export interface SymbolAsset {
  id: string;
  source: SymbolSource;
  externalId?: string;
  imageUrl: string;
  label: string;
  confidence: number; // 0-1
}

export interface Step {
  id: string;
  taskId: string;
  orderIndex: number;
  sentence: string;
  keywords: Keyword[];
  actionType: ActionType;
  symbol?: SymbolAsset;
  fallbackImageUrl?: string;
  needsFallback: boolean;
  safetyFlags: SafetyFlag[];
  ttsAudioUrl?: string;
}

export interface Task {
  id: string;
  employerId: string;
  rawInput: string;
  title: string;
  status: TaskStatus;
  createdAt: string;
  steps: Step[];
}

export interface Worker {
  id: string;
  employerId: string;
  displayName: string;
  a11yPrefs?: {
    fontScale?: number;
    ttsSpeed?: number;
  };
}

export interface Assignment {
  id: string;
  taskId: string;
  workerId: string;
  assignedDate: string;
  status: "pending" | "in_progress" | "completed";
}

export interface PerformanceLog {
  id: string;
  assignmentId: string;
  stepId: string;
  startedAt: string;
  completedAt?: string;
  durationSec?: number;
  replayCount: number;
  stuck: boolean;
}

export interface DashboardStepAggregate {
  stepId: string;
  stepOrder: number;
  sentence: string;
  avgDurationSec: number;
  stuckCount: number;
  replayCount: number;
  completionRate: number;
}

export interface DashboardSummary {
  taskId: string;
  taskTitle: string;
  totalAssignments: number;
  completedAssignments: number;
  completionRate: number;
  avgExplainTimeSavedMin: number;
  steps: DashboardStepAggregate[];
}
