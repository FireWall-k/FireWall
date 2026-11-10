// 새 사업장 빈 상태(명세 5.2-6): 시작 점검표 3단계(근로자 추가 → 기기 연결 → 첫 직무 보내기), 단계마다 [바로 하기].
// 끝낸 단계는 '했어요'로 바뀐다. 셋 다 끝나면 홈은 이 점검표를 그리지 않는다(HomePage가 정한다).
import { Link } from "react-router-dom";
import { CircleCheck } from "lucide-react";
import { buttonClasses, cardClasses } from "../../components/ui";
import { cn } from "../../cn";
import { homeEmpty as copy } from "../copy";

export interface HomeEmptyProps {
  /** [근로자 추가, 기기 연결, 첫 직무 보내기] 끝냈는지. */
  done: [boolean, boolean, boolean];
}

const TARGETS = ["/m/workers", "/m/workers", "/m/tasks/new"] as const;

export default function HomeEmpty({ done }: HomeEmptyProps) {
  const next = done.findIndex((d) => !d);
  return (
    <section aria-labelledby="home-empty-title" data-testid="home-empty" className={cn(cardClasses, "flex flex-col gap-4 p-6")}>
      <div>
        <h2 id="home-empty-title" className="text-ui-lg font-bold text-ink-900">
          {copy.title}
        </h2>
        <p className="mt-1 text-ui-base text-ink-700">{copy.description}</p>
      </div>
      <ol className="flex flex-col gap-3">
        {copy.steps.map((s, i) => (
          <li key={s.title} className="flex flex-wrap items-center gap-3 rounded-control border border-paper-200 p-3">
            <span
              aria-hidden="true"
              className={cn(
                "flex size-8 shrink-0 items-center justify-center rounded-full text-ui-sm font-bold",
                done[i] ? "bg-ok-50 text-ok-700" : "bg-paper-100 text-ink-700",
              )}
            >
              {done[i] ? <CircleCheck size={18} strokeWidth={2} /> : i + 1}
            </span>
            <div className="min-w-0 flex-1">
              <p className="text-ui-base font-semibold text-ink-900">
                <span className="sr-only">{i + 1}. </span>
                {s.title}
              </p>
              <p className="text-ui-sm text-ink-700">{s.body}</p>
            </div>
            {done[i] ? (
              <span className="text-ui-sm font-semibold text-ok-700">{copy.done}</span>
            ) : (
              <Link
                to={TARGETS[i]}
                aria-label={copy.goLabel(s.title)}
                className={buttonClasses(i === next ? "primary" : "secondary", "md")}
              >
                {copy.go}
              </Link>
            )}
          </li>
        ))}
      </ol>
    </section>
  );
}
