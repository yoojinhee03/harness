import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { api, type AdoptResponse } from "../api/client";
import { useToast } from "../lib/toast";
import { Badge, Button, Card, codeBlock, Input, Modal, Spinner } from "../lib/ui";

/**
 * 기존 설정 가져오기(adopt) — 쓰던 `.claude/`·`.cursor/` 폴더를 편집 가능한 하네스로 되돌린다.
 *
 * 온보딩 진입점이다. 이게 없으면 신규 사용자는 맨바닥에서 시작하는 수밖에 없었다.
 * 변환은 `POST /adopt`(CLI `harness adopt` 와 같은 코어)가 하고, 여기선 파일 수집·확인·저장만 한다.
 */

/** 서버 `read_native_tree` 가 읽는 파일 집합의 미러 — 프로젝트 전체를 올리지 않기 위한 필터. */
const EXACT = new Set(["CLAUDE.md", ".mcp.json", ".claude/settings.json", ".cursor/mcp.json"]);
const SKILL_RE = /^\.claude\/skills\/[^/]+\/SKILL\.md$/;
const RULE_RE = /^\.cursor\/rules\/[^/]+\.mdc$/;

/** 개별 파일 상한 — 설정 파일이 이보다 크면 adopt 대상이 아니다(오선택 방어). */
const MAX_BYTES = 512 * 1024;

function isAdoptable(path: string): boolean {
  return EXACT.has(path) || SKILL_RE.test(path) || RULE_RE.test(path);
}

/** "myproject/.claude/settings.json" → ".claude/settings.json" (폴더 선택 시 루트 세그먼트 제거). */
function stripRoot(relPath: string): string {
  const i = relPath.indexOf("/");
  return i === -1 ? relPath : relPath.slice(i + 1);
}

async function collectFiles(list: FileList): Promise<Record<string, string>> {
  const out: Record<string, string> = {};
  for (const file of Array.from(list)) {
    const path = stripRoot(file.webkitRelativePath || file.name);
    if (!isAdoptable(path) || file.size > MAX_BYTES) continue;
    out[path] = await file.text();
  }
  return out;
}

export function AdoptImport({ scope, onClose }: { scope: string; onClose: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const dirRef = useRef<HTMLInputElement>(null);

  const [files, setFiles] = useState<Record<string, string>>({});
  const [scanned, setScanned] = useState(false);
  const [harnessId, setHarnessId] = useState("adopted");
  const [result, setResult] = useState<AdoptResponse | null>(null);

  // webkitdirectory 는 React 타입에 없어 ref 로 단다(폴더 통째 선택).
  useEffect(() => {
    dirRef.current?.setAttribute("webkitdirectory", "");
    dirRef.current?.setAttribute("directory", "");
  }, []);

  const paths = Object.keys(files).sort();

  const adopt = useMutation({
    mutationFn: () => api.adopt(files, harnessId.trim() || "adopted"),
    onSuccess: setResult,
    onError: (e: Error) => toast(e.message || "가져오기에 실패했습니다", "error"),
  });

  const save = useMutation({
    mutationFn: () => {
      if (!result) throw new Error("가져온 결과가 없습니다");
      const id = harnessId.trim() || "adopted";
      return api.putHarness(id, scope, { name: id, description: "기존 설정에서 가져옴", yaml: result.yaml });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["harnesses"] });
      toast("하네스로 저장했습니다", "success");
      onClose();
    },
    onError: (e: Error) => toast(e.message || "저장에 실패했습니다", "error"),
  });

  async function onPick(e: React.ChangeEvent<HTMLInputElement>) {
    const picked = e.target.files;
    if (!picked) return;
    setFiles(await collectFiles(picked));
    setScanned(true);
    setResult(null);
  }

  return (
    <Modal title="기존 설정 가져오기" onClose={onClose}>
      <p className="text-sm text-muted">
        쓰던 <code className="rounded bg-surface-2 px-1 py-0.5">.claude/</code> ·{" "}
        <code className="rounded bg-surface-2 px-1 py-0.5">.cursor/</code> 가 있는 프로젝트 폴더를 고르세요. 설정
        파일만 읽고 소스 코드는 보내지 않습니다.
      </p>

      <div className="mt-3">
        <input
          ref={dirRef}
          type="file"
          multiple
          onChange={onPick}
          className="block w-full text-sm text-muted file:mr-3 file:rounded-lg file:border-0 file:bg-surface-2 file:px-3 file:py-1.5 file:text-fg hover:file:bg-surface-3"
        />
      </div>

      {scanned && (
        <Card className="mt-3">
          {paths.length === 0 ? (
            <p className="text-sm text-warn">
              가져올 설정 파일을 못 찾았습니다. <code>CLAUDE.md</code> · <code>.mcp.json</code> ·{" "}
              <code>.claude/settings.json</code> · <code>.cursor/</code> 중 하나가 있는 폴더인지 확인하세요.
            </p>
          ) : (
            <>
              <div className="text-xs text-muted">읽은 설정 파일 {paths.length}개</div>
              <ul className="mt-1.5 space-y-0.5">
                {paths.map((p) => (
                  <li key={p} className="font-mono text-xs text-fg">
                    {p}
                  </li>
                ))}
              </ul>
            </>
          )}
        </Card>
      )}

      {paths.length > 0 && (
        <div className="mt-3 flex items-end gap-2">
          <label className="flex-1">
            <span className="mb-1 block text-xs text-muted">하네스 id</span>
            <Input value={harnessId} onChange={(e) => setHarnessId(e.target.value)} placeholder="adopted" />
          </label>
          <Button onClick={() => adopt.mutate()} disabled={adopt.isPending}>
            {adopt.isPending ? <Spinner /> : "가져오기"}
          </Button>
        </div>
      )}

      {result && <AdoptPreview result={result} onSave={() => save.mutate()} saving={save.isPending} />}
    </Modal>
  );
}

function AdoptPreview({ result, onSave, saving }: { result: AdoptResponse; onSave: () => void; saving: boolean }) {
  // adopt 는 '구조적으로 식별 가능한 것만' 복원한다. 못 붙인 것들을 숨기면 사용자가 손실을 모른 채
  // 저장하게 되므로 함께 보여준다(환각 대신 정직한 결핍 — gap 카드와 같은 원칙).
  const unresolved = [
    ...result.unknown_mcp.map((id) => ({ id, kind: "MCP" })),
    ...result.unknown_skills.map((id) => ({ id, kind: "스킬" })),
  ];

  return (
    <div className="mt-4 border-t border-line pt-3">
      <div className="flex flex-wrap items-center gap-1.5">
        <Badge className={result.ok ? "bg-ok/15 text-ok" : "bg-err/15 text-err"}>
          {result.ok ? "검증 통과" : "검증 실패"}
        </Badge>
        {result.errors > 0 && <Badge className="bg-err/15 text-err">에러 {result.errors}</Badge>}
        {result.warnings > 0 && <Badge className="bg-warn/15 text-warn">경고 {result.warnings}</Badge>}
        {result.gaps > 0 && <Badge className="bg-surface-2 text-muted">gap {result.gaps}</Badge>}
        {result.hooks.length > 0 && (
          <Badge className="bg-surface-2 text-muted">훅 {result.hooks.length}개 이벤트만 흡수</Badge>
        )}
      </div>

      {unresolved.length > 0 && (
        <Card className="mt-2.5 border-warn/40">
          <div className="text-xs font-medium text-fg">카탈로그에 없어 그대로 남긴 항목 {unresolved.length}개</div>
          <p className="mt-1 text-xs text-muted">
            비슷한 컴포넌트로 바꿔치지 않았습니다. 카탈로그에 추가하면 다음 가져오기부터 컴포넌트로 붙습니다.
          </p>
          <ul className="mt-1.5 space-y-0.5">
            {unresolved.map((u) => (
              <li key={`${u.kind}/${u.id}`} className="text-xs">
                <span className="text-muted">{u.kind}</span> <span className="font-mono text-fg">{u.id}</span>
              </li>
            ))}
          </ul>
        </Card>
      )}

      {result.notes.length > 0 && (
        <ul className="mt-2.5 space-y-1">
          {result.notes.map((n) => (
            <li key={n} className="text-xs text-muted">
              · {n}
            </li>
          ))}
        </ul>
      )}

      <pre className={`${codeBlock} mt-2.5 max-h-64 overflow-auto`}>{result.yaml}</pre>

      <div className="mt-3 flex justify-end">
        <Button onClick={onSave} disabled={saving}>
          {saving ? <Spinner /> : "하네스로 저장"}
        </Button>
      </div>
    </div>
  );
}
