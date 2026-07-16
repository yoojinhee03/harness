import { useState } from "react";
import { loadSaved, removeHarness, type SavedHarness } from "../lib/store";
import { Button, Card, Chip } from "../lib/ui";

export default function ScreenF({
  onNew,
  onReopen,
}: {
  onNew: () => void;
  onReopen: (h: SavedHarness) => void;
}) {
  const [list, setList] = useState<SavedHarness[]>(() => loadSaved());

  return (
    <div className="mx-auto max-w-3xl">
      <div className="mb-5 flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold text-slate-900">대시보드</h2>
          <p className="text-sm text-slate-500">생성한 하네스 목록 — 재열기·복제의 허브.</p>
        </div>
        <Button onClick={onNew}>+ 새 하네스 만들기</Button>
      </div>

      {list.length === 0 ? (
        <Card>
          <p className="text-sm text-slate-500">
            아직 생성한 하네스가 없습니다. "새 하네스 만들기"로 시작하세요.
          </p>
        </Card>
      ) : (
        <div className="space-y-3">
          {list.map((h) => (
            <Card key={h.id} className="flex items-center justify-between">
              <div>
                <div className="font-medium text-slate-900">{h.name || h.id}</div>
                <div className="mt-1 flex flex-wrap items-center gap-1.5 text-xs text-slate-500">
                  <span>{new Date(h.createdAt).toLocaleString("ko-KR")}</span>
                  <span className="text-slate-300">·</span>
                  <span>{h.components.length}개 구성요소</span>
                  {h.components.slice(0, 4).map((c) => (
                    <Chip key={c.id}>{c.name}</Chip>
                  ))}
                </div>
              </div>
              <div className="flex shrink-0 gap-2">
                <Button variant="ghost" onClick={() => onReopen(h)}>
                  열기
                </Button>
                <button
                  className="rounded-lg px-2 text-slate-400 hover:text-err"
                  onClick={() => setList(removeHarness(h.id))}
                  title="삭제"
                >
                  ✕
                </button>
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
