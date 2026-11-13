// 새 직무와 편집기를 한 Route(/manager/tasks/:id, id="new"면 새 직무)에서 그린다(contract §2.2).
// 초안을 만들어 주소가 /manager/tasks/new → /manager/tasks/:id로 바뀌어도 이 부품은 다시 만들어지지 않고(같은 Route·같은 key),
// 방금 만든 초안을 편집기에 그대로 넘긴다(다시 불러오지 않음). 주소는 replace — 뒤로 가기는 새 직무 전 화면으로 간다.
// 넘긴 초안은 한 번만 쓴다(편집기가 받은 뒤 비운다). 남겨 두면 [+ 새 직무] → 뒤로 가기로 다시 만들어진 편집기가
// 만들 때의 옛 초안을 받아, 그동안 고친 문장·확인이 사라져 보였다(1회차 검증).
import { useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import type { EditorTask } from "../api/types";
import TaskEditorPage from "./editor/TaskEditorPage";
import NewTaskPage from "./new/NewTaskPage";

export default function TaskWorkspace() {
  const { id } = useParams();
  const { search } = useLocation();
  const navigate = useNavigate();
  const [created, setCreated] = useState<EditorTask | null>(null);
  const handOver = created && id === created.id ? created : null;

  if (!id || id === "new") {
    const example = new URLSearchParams(search).get("example") === "1";
    return (
      <NewTaskPage
        // 예시 화면에서 [+ 새 직무]로 빈 화면에 가면 새로 그린다(같은 주소로 다시 오면 그대로).
        key={search}
        example={example}
        onCreated={(t) => {
          setCreated(t);
          navigate(`/manager/tasks/${encodeURIComponent(t.id)}`, { replace: true });
        }}
      />
    );
  }
  return <TaskEditorPage key={id} taskId={id} initialTask={handOver} onInitialUsed={() => setCreated(null)} />;
}
