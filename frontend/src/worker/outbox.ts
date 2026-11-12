// 오프라인 기록 대기열(명세 3.5·7.1, contract §6.3). 단계 완료 기록은 서버에 닿을 때까지 기기에 쌓아 둔다 —
// 현장 와이파이가 끊겨도 일은 계속하고, 기록은 하나도 잃지 않는다.
// - 저장: localStorage `jobcard_outbox_v1:{workerId}`. 근로자마다 따로 둬서 다른 근로자 토큰으로 보내지 않는다.
// - 항목 키: assignment_id + step_id. 같은 단계를 다시 끝내면([이전] 뒤 [다 했어요]) 마지막 것만 남긴다.
// - 항목마다 client_event_id: 서버가 같은 기록을 두 번 세지 않게 한다(재전송 = 200 duplicate).
// - 응답 처리(§6.3): 2xx → 지움 / 400·404·422 → 버림(다시 보내도 안 됨) / 401 → 남기고 멈춤(다시 들어오기) /
//   429·5xx·네트워크 → 남기고 멈춤(다음에 다시).
// localStorage가 막힌 기기(사생활 보호 모드)에서도 화면은 동작한다: 그때는 메모리에만 둔다.
// - 같은 근로자의 탭이 둘이어도 서로 덮어쓰지 않는다: 바꾸기 전마다 저장된 목록을 다시 읽어 합친다(같은 단계는
//   더 나중 기록), storage 이벤트로 다른 탭의 변경을 받는다. 다른 탭이 이미 보낸 기록을 한 번 더 보낼 수는
//   있지만 서버가 client_event_id로 한 번만 센다(1차 검증: 탭 A의 기록이 탭 B 저장에 덮여 사라졌다).
// - 기록 칸은 그대로 실어 보낸다((2c) prev_count 포함, 옛 기록에 없으면 서버 기본 0).
// - 보내는 동안 새로 들어온 기록도 같은 보내기에서 이어서 보낸다(30초 타이머·숨은 탭을 기다리지 않게).
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

  /** 이 탭에서 보냈거나 버린 기록(다른 탭 저장본과 합칠 때 되살리지 않게). */
  private gone = new Set<string>();

  constructor(workerId: string) {
    this.workerId = workerId;
    this.items = this.load();
    if (typeof window !== "undefined") {
      window.addEventListener("storage", (e) => {
        if (e.key !== this.storageKey) return;
        this.sync();
        this.listeners.forEach((fn) => fn());
      });
    }
  }

  /** 저장된 목록(다른 탭이 쓴 것 포함)과 메모리 목록을 합친다. 같은 단계는 더 나중에 끝낸 기록 하나만. */
  private sync() {
    const merged = new Map<string, OutboxItem>();
    for (const x of [...this.load(), ...this.items]) {
      if (this.gone.has(x.client_event_id)) continue;
      const cur = merged.get(x.key);
      if (!cur || (x.client_completed_at ?? "") > (cur.client_completed_at ?? "")) merged.set(x.key, x);
    }
    this.items = [...merged.values()].sort((a, b) =>
      (a.client_completed_at ?? "").localeCompare(b.client_completed_at ?? ""));
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
    this.sync();
    for (const x of this.items) if (x.key === item.key) this.gone.add(x.client_event_id);
    this.items = [...this.items.filter((x) => x.key !== item.key), item];
    this.save();
    return item;
  }

  /** 보낸 기록을 지운다. 보내는 사이 같은 단계가 새로 들어왔으면(다른 event id) 새 것은 남긴다. */
  private remove(item: OutboxItem) {
    this.gone.add(item.client_event_id);
    this.sync();
    this.save();
  }

  /** 대기열을 앞에서부터 보낸다. 이미 보내는 중이면 그 결과를 같이 기다린다(두 번 보내지 않음). */
  flush(send: OutboxSend): Promise<FlushResult> {
    if (this.flushing) return this.flushing;
    const run = async (): Promise<FlushResult> => {
      const result: FlushResult = { sent: 0, dropped: 0, remaining: 0, expired: false, failed: false };
      this.sync();
      const tried = new Set<string>();
      // 앞에서부터 하나씩 보낸다. 보내는 동안 새로 들어온 기록(다음 단계 [다 했어요])도 이번 보내기에서 보낸다 —
      // 예전에는 시작할 때 목록을 복사해 두고 그것만 보내서, 새 기록은 30초 타이머(숨은 탭에서는 안 돎)를 기다렸다.
      for (;;) {
        const item = this.items.find((x) => !tried.has(x.client_event_id));
        if (!item) break;
        tried.add(item.client_event_id);
        // eslint-disable-next-line @typescript-eslint/no-unused-vars
        const { key, ...body } = item;
        try {
          // 보내는 순간의 기기 시각을 같이 싣는다(4차 검증). 서버는 (보낸 시각 - 끝낸 시각)으로 완료 순간을 서버 시계로
          // 옮겨, 기기 시계가 틀려도 그 뒤에 부른 도움 요청을 닫을지 바르게 정한다.
          await send({ ...body, client_sent_at: new Date().toISOString() });
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
      this.sync();
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
