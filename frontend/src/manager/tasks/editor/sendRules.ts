// 보내기 시트 규칙(contract §3.6) — 화면 파일과 떼어 단위 시험한다.
import type { Worker } from "../../../api";
import type { Recipients } from "../../api/types";

/** contract §3.6 미리 체크 규칙. 오늘 이미 다 한 사람은 빼고, 어떤 규칙으로 골랐는지도 돌려준다. */
export function precheck(r: Recipients, workers: Worker[]): { ids: Set<string>; fromLast: boolean } {
  const known = new Set(workers.map((w) => w.id));
  const notDone = (id: string) => known.has(id) && r.today_status[id] !== "done";
  const last = r.last_batch_worker_ids.filter(notDone);
  if (last.length) return { ids: new Set(last), fromLast: true };
  const wp = r.workplace_last_batch_worker_ids.filter(notDone);
  if (wp.length) return { ids: new Set(wp), fromLast: true };
  if (workers.length === 1 && notDone(workers[0].id)) return { ids: new Set([workers[0].id]), fromLast: false };
  return { ids: new Set(), fromLast: false };
}
