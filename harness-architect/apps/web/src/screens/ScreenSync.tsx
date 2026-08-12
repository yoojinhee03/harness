import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api, subscribeHarnessEvents } from "../api/client";
import { Button, Card } from "../lib/ui";

/**
 * 동기화 화면 — 공유 백엔드 저장소의 하네스 목록. VSCode 확장의 '내 하네스' 뷰와 같은 데이터를
 * 본다. SSE 로 확장/다른 웹의 변경을 실시간 반영(양방향 동기화).
 */
export default function ScreenSync() {
  const qc = useQueryClient();
  const { data: list = [], isError } = useQuery({
    queryKey: ["harnesses"],
    queryFn: api.listHarnesses,
  });
  const [openId, setOpenId] = useState<string | null>(null);
  const { data: doc } = useQuery({
    queryKey: ["harness", openId],
    queryFn: () => api.getHarness(openId as string),
    enabled: openId !== null,
  });

  // SSE 구독 — 어떤 변경이든 목록/상세를 무효화해 다시 그린다(라이브).
  useEffect(() => {
    return subscribeHarnessEvents(() => {
      qc.invalidateQueries({ queryKey: ["harnesses"] });
      qc.invalidateQueries({ queryKey: ["harness"] });
    });
  }, [qc]);

  async function del(id: string) {
    await api.deleteHarness(id);
    if (openId === id) setOpenId(null);
    qc.invalidateQueries({ queryKey: ["harnesses"] });
  }

  return (
    <div className="mx-auto max-w-3xl">
      <div className="mb-5 flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold text-slate-900">동기화</h2>
          <p className="text-sm text-slate-500">
            공유 저장소의 하네스 — <span className="font-medium text-slate-700">VSCode 확장과 실시간 동기화</span>.
            웹에서 저장하면 확장에, 확장에서 저장하면 여기에 즉시 나타납니다.
          </p>
        </div>
        <span className="inline-flex items-center gap-1.5 text-xs text-slate-500">
          <span className="inline-block h-2 w-2 rounded-full bg-ok" /> 라이브(SSE)
        </span>
      </div>

      {isError && (
        <Card className="mb-3 border-warn/40 bg-warn/5">
          <p className="text-sm text-slate-600">
            백엔드에 연결되지 않았습니다. API 서버(<code>/harnesses</code>)가 떠 있는지 확인하세요.
          </p>
        </Card>
      )}

      {list.length === 0 ? (
        <Card>
          <p className="text-sm text-slate-500">
            저장된 하네스가 없습니다. 생성 흐름의 <b>harness.yaml</b> 단계에서 저장하거나, VSCode 확장에서
            "공유 저장소에 저장"하면 여기에 나타납니다.
          </p>
        </Card>
      ) : (
        <div className="space-y-3">
          {list.map((h) => (
            <Card key={h.id} className="flex items-center justify-between">
              <div className="min-w-0">
                <div className="font-medium text-slate-900">{h.name || h.id}</div>
                <div className="mt-1 flex flex-wrap items-center gap-1.5 text-xs text-slate-500">
                  <code className="rounded bg-slate-100 px-1.5 py-0.5">{h.id}</code>
                  {h.updated_at && (
                    <>
                      <span className="text-slate-300">·</span>
                      <span>{new Date(h.updated_at).toLocaleString("ko-KR")}</span>
                    </>
                  )}
                  {h.description && <span className="truncate text-slate-400">— {h.description}</span>}
                </div>
              </div>
              <div className="flex shrink-0 gap-2">
                <Button variant="ghost" onClick={() => setOpenId(openId === h.id ? null : h.id)}>
                  {openId === h.id ? "닫기" : "열기"}
                </Button>
                <button
                  className="rounded-lg px-2 text-slate-400 hover:text-err"
                  onClick={() => del(h.id)}
                  title="삭제"
                >
                  ✕
                </button>
              </div>
            </Card>
          ))}
        </div>
      )}

      {openId && doc && (
        <Card className="mt-4">
          <div className="mb-2 flex items-center justify-between">
            <span className="text-sm font-medium text-slate-700">{doc.name || doc.id} · harness.yaml</span>
            <button
              className="text-xs text-slate-500 hover:text-slate-900"
              onClick={() => navigator.clipboard?.writeText(doc.yaml)}
            >
              복사
            </button>
          </div>
          <pre className="max-h-96 overflow-auto rounded-lg bg-slate-900 p-3 text-xs leading-relaxed text-slate-100">
            {doc.yaml}
          </pre>
        </Card>
      )}
    </div>
  );
}
