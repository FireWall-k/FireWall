// 오프라인 기록 대기열(명세 3.5·7.1, contract §6.3). 단계 완료 기록은 서버에 닿을 때까지 기기에 쌓아 둔다 —
// 현장 와이파이가 끊겨도 일은 계속하고, 기록은 하나도 잃지 않는다.
// - 저장: localStorage `jobcard_outbox_v1:{workerId}`. 근로자마다 따로 둬서 다른 근로자 토큰으로 보내지 않는다.
// - 항목 키: assignment_id + step_id. 같은 단계를 다시 끝내면([이전] 뒤 [다 했어요]) 마지막 것만 남긴다.
// - 항목마다 client_event_id: 서버가 같은 기록을 두 번 세지 않게 한다(재전송 = 200 duplicate).
// - 응답 처리(§6.3): 2xx → 지움 / 400·404·422 → 버림(다시 보내도 안 됨) / 401 → 남기고 멈춤(다시 들어오기) /
//   429·5xx·네트워크 → 남기고 멈춤(다음에 다시).
// localStorage가 막힌 기기(사생활 보호 모드)에서도 화면은 동작한다: 그때는 메모리에만 둔다.
import { ApiError, AuthError } from "../apiErrors";
import { newId, type LogBody } from "./workerApi";

export interface OutboxItem extends LogBody {
  key: string;
}

export type OutboxSend = (body: LogBody) => Promise<unknown>;

export interface FlushResult {
  sent: number;
  dropped: number;
  remaining: number;
  /** 401을 받아 멈췄다(다시 들어와야 보낼 수 있다). */
  expired: boolean;
  /** 네트워크·서버 문제로 멈췄다(다음에 다시 보낸다). */
  failed: boolean;
}

export const OUTBOX_PREFIX = "jobcard_outbox_v1:";

export function outboxKey(assignmentId: string, stepId: string): string {
  return `${assignmentId}:${stepId}`;
}

function storage(): Storage | null {
  try {
    return typeof localStorage === "undefined" ? null : localStorage;
  } catch {
    return null;
  }
}

function isAuth(e: unknown): boolean {
  return e instanceof AuthError || (e instanceof ApiError && e.status === 401);
}

/** 다시 보내도 결과가 같은(버려야 하는) 오류인지. */
function isPermanent(e: unknown): boolean {
  return e instanceof ApiError && (e.status === 400 || e.status === 404 || e.status === 422);
}

type PutInput = Omit<LogBody, "client_event_id" | "client_completed_at"> &
  Partial<Pick<LogBody, "client_event_id" | "client_completed_at">>;

export class Outbox {
  readonly workerId: string;
  private items: OutboxItem[] = [];
  private listeners = new Set<() => void>();
  private flushing: Promise<FlushResult> | null = null;

  constructor(workerId: string) {
    this.workerId = workerId;
    this.items = this.load();
  }

  private get storageKey() {
    return `${OUTBOX_PREFIX}${this.workerId}`;
  }

  private load(): OutboxItem[] {
    try {
      const raw = storage()?.getItem(this.storageKey);
      const parsed: unknown = raw ? JSON.parse(raw) : [];
      if (!Array.isArray(parsed)) return [];
      return parsed.filter((x): x is OutboxItem => !!x && typeof x === "object" && typeof (x as OutboxItem).key === "string");
    } catch {
      return [];
    }
  }

  private save() {
    try {
      const s = storage();
      if (s) {
        if (this.items.length === 0) s.removeItem(this.storageKey);
        else s.setItem(this.storageKey, JSON.stringify(this.items));
      }
    } catch {
      /* 저장 못 해도 메모리에는 남아 있다(이 화면을 닫기 전까지는 보낸다) */
    }
    this.listeners.forEach((fn) => fn());
  }

  list(): readonly OutboxItem[] {
    return this.items;
  }

  get size(): number {
    return this.items.length;
  }

  subscribe(fn: () => void): () => void {
    this.listeners.add(fn);
    return () => {
      this.listeners.delete(fn);
    };
  }

  /** 기록을 넣는다. 같은 단계의 예전 기록은 지우고 새 기록을 맨 뒤에 둔다(마지막 것만 남김). */
  put(body: PutInput): OutboxItem {
    const item: OutboxItem = {
      ...body,
      client_event_id: body.client_event_id ?? newId(),
      client_completed_at: body.client_completed_at ?? new Date().toISOString(),
      key: outboxKey(body.assignment_id, body.step_id),
    };
    this.items = [...this.items.filter((x) => x.key !== item.key), item];
    this.save();
    return item;
  }

  /** 보낸 기록을 지운다. 보내는 사이 같은 단계가 새로 들어왔으면(다른 event id) 새 것은 남긴다. */
  private remove(item: OutboxItem) {
    const before = this.items.length;
    this.items = this.items.filter((x) => x.client_event_id !== item.client_event_id);
    if (this.items.length !== before) this.save();
  }

  /** 대기열을 앞에서부터 보낸다. 이미 보내는 중이면 그 결과를 같이 기다린다(두 번 보내지 않음). */
  flush(send: OutboxSend): Promise<FlushResult> {
    if (this.flushing) return this.flushing;
    const run = async (): Promise<FlushResult> => {
      const result: FlushResult = { sent: 0, dropped: 0, remaining: 0, expired: false, failed: false };
      for (const item of [...this.items]) {
        // 보내기 전에 같은 단계의 새 기록으로 바뀌었으면 건너뛴다(새 기록은 뒤에 있다).
        if (!this.items.some((x) => x.client_event_id === item.client_event_id)) continue;
        // eslint-disable-next-line @typescript-eslint/no-unused-vars
        const { key, ...body } = item;
        try {
          await send(body);
          this.remove(item);
          result.sent += 1;
        } catch (e) {
          if (isAuth(e)) {
            result.expired = true;
            break;
          }
          if (isPermanent(e)) {
            this.remove(item);
            result.dropped += 1;
            continue;
          }
          // 네트워크·429·5xx·모르는 오류: 남겨 두고 다음 기회에(online 이벤트, 30초마다).
          result.failed = true;
          break;
        }
      }
      result.remaining = this.items.length;
      return result;
    };
    this.flushing = run().finally(() => {
      this.flushing = null;
    });
    return this.flushing;
  }
}

// 근로자마다 하나만 만든다(홈·단계 화면·완료 화면이 같은 대기열을 본다).
const registry = new Map<string, Outbox>();

export function getOutbox(workerId: string): Outbox {
  let box = registry.get(workerId);
  if (!box) {
    box = new Outbox(workerId);
    registry.set(workerId, box);
  }
  return box;
}

/** 테스트용: 만들어 둔 대기열을 잊는다(localStorage는 건드리지 않는다). */
export function resetOutboxRegistry() {
  registry.clear();
}
