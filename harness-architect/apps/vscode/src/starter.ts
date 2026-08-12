import * as vscode from "vscode";

/** 스타터 harness.yaml 에 넣을 최소 컴포넌트 정보. */
export interface StarterComponent {
  id: string;
  version: string;
  type: string;
  name: string;
}

/** 추천 결과 → 검증 가능한 harness.yaml 스타터 텍스트. */
export function starterYaml(description: string, recs: StarterComponent[]): string {
  const lines: string[] = [];
  lines.push(`# ${description.replace(/\n/g, " ").slice(0, 100)}`);
  lines.push("metadata:");
  lines.push("  id: my-harness");
  lines.push('  name: "My Harness"');
  lines.push("model:");
  lines.push("  name: claude-sonnet-5");
  lines.push("components:");
  if (recs.length === 0) {
    lines.push("  [] # 추천 결과가 없습니다 — 설명을 더 구체적으로.");
  }
  for (const r of recs) {
    lines.push(`  - ref: ${r.id}@${r.version}   # ${r.type} · ${r.name}`);
  }
  return `${lines.join("\n")}\n`;
}

/** 스타터를 Untitled yaml 문서로 열어 준다(저장은 사용자 몫). */
export async function openStarter(description: string, recs: StarterComponent[]): Promise<void> {
  const doc = await vscode.workspace.openTextDocument({
    content: starterYaml(description, recs),
    language: "yaml",
  });
  await vscode.window.showTextDocument(doc, { preview: false });
}
