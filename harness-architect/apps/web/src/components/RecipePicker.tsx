import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, type RecipeMeta } from "../api/client";
import { useToast } from "../lib/toast";
import { Button, Card, codeBlock, Modal, Spinner } from "../lib/ui";

/**
 * 레시피로 시작 (Phase 9-3) — 콜드스타트("무엇부터 골라야 하나")를 없앤다.
 *
 * 레시피는 카탈로그 위의 큐레이션이라 새 컴포넌트를 만들지 않는다. 정답이 아니라 시작점이므로,
 * 저장한 뒤 하네스 상세에서 고쳐 쓰는 흐름을 전제로 한다.
 */
export function RecipePicker({ scope, onClose }: { scope: string; onClose: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [picked, setPicked] = useState<string | null>(null);

  const list = useQuery({ queryKey: ["recipes"], queryFn: api.recipes });
  const detail = useQuery({
    queryKey: ["recipe", picked],
    queryFn: () => api.recipe(picked as string),
    enabled: picked !== null,
  });

  const save = useMutation({
    mutationFn: () => {
      const d = detail.data;
      if (!d) throw new Error("레시피를 불러오는 중입니다");
      const id = String((d.config as { metadata?: { id?: string } }).metadata?.id ?? d.meta.name);
      return api.putHarness(id, scope, { name: d.meta.title, description: d.meta.description, yaml: d.yaml });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["harnesses"] });
      toast("레시피로 하네스를 만들었습니다 — 팀에 맞게 고쳐 쓰세요", "success");
      onClose();
    },
    onError: (e: Error) => toast(e.message || "저장에 실패했습니다", "error"),
  });

  const recipes: RecipeMeta[] = list.data ?? [];

  return (
    <Modal title="레시피로 시작" onClose={onClose}>
      <p className="text-sm text-muted">
        검증된 조합으로 하네스를 만듭니다. 정답이 아니라 <b className="text-fg">시작점</b>이니 만든 뒤 고쳐
        쓰세요.
      </p>

      {list.isLoading && (
        <div className="mt-3 flex justify-center py-4">
          <Spinner />
        </div>
      )}
      {list.isError && <p className="mt-3 text-xs text-warn">레시피를 불러오지 못했습니다.</p>}
      {!list.isLoading && recipes.length === 0 && (
        <p className="mt-3 text-xs text-muted">사용 가능한 레시피가 없습니다.</p>
      )}

      <div className="mt-3 space-y-2">
        {recipes.map((r) => {
          const open = picked === r.name;
          return (
            <Card key={r.name} className={open ? "border-accent/50" : ""}>
              <button className="w-full text-left" onClick={() => setPicked(open ? null : r.name)}>
                <div className="font-medium text-fg">{r.title}</div>
                <div className="mt-0.5 text-xs text-muted">{r.description}</div>
              </button>
              {r.use_when.length > 0 && (
                <ul className="mt-1.5 space-y-0.5">
                  {r.use_when.map((w) => (
                    <li key={w} className="text-xs text-muted">
                      · {w}
                    </li>
                  ))}
                </ul>
              )}
              {open && (
                <div className="mt-2">
                  {detail.isLoading ? (
                    <div className="flex justify-center py-2">
                      <Spinner />
                    </div>
                  ) : detail.data ? (
                    <>
                      <pre className={`${codeBlock} max-h-56 overflow-auto`}>{detail.data.yaml}</pre>
                      <div className="mt-2 flex justify-end">
                        <Button onClick={() => save.mutate()} disabled={save.isPending}>
                          {save.isPending ? <Spinner /> : "이 레시피로 만들기"}
                        </Button>
                      </div>
                    </>
                  ) : (
                    <p className="text-xs text-warn">레시피 내용을 불러오지 못했습니다.</p>
                  )}
                </div>
              )}
            </Card>
          );
        })}
      </div>
    </Modal>
  );
}
