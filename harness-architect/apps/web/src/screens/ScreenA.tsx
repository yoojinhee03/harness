import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { api, type RecommendResult } from "../api/client";
import { Button, Card } from "../lib/ui";

const EXAMPLES = [
  "PR 자동 리뷰 봇: 코드 리뷰 코멘트 자동화, 팀 코딩 컨벤션 준수, 보안 시크릿 스캔.",
  "이슈 분류 에이전트: 새 이슈를 읽고 라벨을 달고 담당자를 제안.",
  "문서 초안 작성기: 회의록을 받아 요약 문서를 생성하고 위키에 저장.",
];

export default function ScreenA({
  description,
  setDescription,
  onResult,
}: {
  description: string;
  setDescription: (v: string) => void;
  onResult: (r: RecommendResult) => void;
}) {
  const [local, setLocal] = useState(description);
  const mutation = useMutation({
    mutationFn: () => api.recommend(local, 8),
    onSuccess: (r) => {
      setDescription(local);
      onResult(r);
    },
  });

  return (
    <div className="mx-auto max-w-2xl">
      <Card>
        <h2 className="text-lg font-semibold text-slate-900">만들려는 걸 자연어로 설명해 주세요</h2>
        <p className="mt-1 text-sm text-slate-500">
          아키텍처를 직접 설계하지 않아도 됩니다 — 요구사항만 적으면 필요한 능력을 추출합니다.
        </p>
        <textarea
          className="mt-4 h-36 w-full resize-none rounded-lg border border-slate-300 p-3 text-sm focus:border-slate-500 focus:outline-none"
          placeholder="예: PR을 자동으로 리뷰하는 봇을 만들고 싶어요…"
          value={local}
          onChange={(e) => setLocal(e.target.value)}
        />
        <div className="mt-3 flex flex-wrap gap-2">
          {EXAMPLES.map((ex) => (
            <button
              key={ex}
              onClick={() => setLocal(ex)}
              className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-left text-xs text-slate-600 hover:bg-slate-100"
            >
              {ex.slice(0, 28)}…
            </button>
          ))}
        </div>
        {mutation.isError && (
          <p className="mt-3 text-sm text-err">추천 요청 실패 — 백엔드(:8000)가 떠 있는지 확인하세요.</p>
        )}
        <div className="mt-5 flex justify-end">
          <Button onClick={() => mutation.mutate()} disabled={!local.trim() || mutation.isPending}>
            {mutation.isPending ? "요구사항 추출 중…" : "추천 받기 →"}
          </Button>
        </div>
      </Card>
    </div>
  );
}
