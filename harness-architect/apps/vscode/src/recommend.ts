import * as vscode from "vscode";
import type { HarnessServer } from "./mcp";
import { openStarter } from "./starter";

interface Recommendation {
  id: string;
  type: string;
  name: string;
  version: string;
  summary: string;
  score: number;
  reason: string;
  provides: string[];
  requires: string[];
  matched_capabilities: string[];
  context_tokens: number;
  added_tools: number;
  conflicts_with: string[];
  auth_required: boolean;
}

interface RecommendResult {
  description: string;
  requirements: string[];
  extraction_mode: string;
  ranking_mode: string;
  recommendations: Recommendation[];
  groups: Record<string, string[]>;
}

let panel: vscode.WebviewPanel | undefined;

export async function runRecommend(server: HarnessServer, extensionUri: vscode.Uri): Promise<void> {
  const seed = seedFromEditor();
  const description = await vscode.window.showInputBox({
    title: "하네스 추천 — 프로젝트를 한두 문장으로 설명하세요",
    placeHolder: "예: 파이썬 백엔드 코드 리뷰 봇. 깃헙 PR 을 읽고 컨벤션 위반을 코멘트한다.",
    value: seed,
    ignoreFocusOut: true,
  });
  if (!description) {
    return;
  }

  const result = (await vscode.window.withProgress(
    { location: vscode.ProgressLocation.Notification, title: "카탈로그에서 추천 중…" },
    () => server.call("recommend_harness", { description, top_k: 8 }),
  )) as RecommendResult;

  if (!panel) {
    panel = vscode.window.createWebviewPanel("harnessRecommend", "Harness 추천", vscode.ViewColumn.Beside, {
      enableScripts: true,
      localResourceRoots: [extensionUri],
      retainContextWhenHidden: true,
    });
    panel.onDidDispose(() => (panel = undefined));
    panel.webview.onDidReceiveMessage((msg) => onMessage(msg, () => lastResult));
  }
  lastResult = result;
  panel.title = "Harness 추천";
  panel.webview.html = render(result);
  panel.reveal(vscode.ViewColumn.Beside);
}

let lastResult: RecommendResult | undefined;

function seedFromEditor(): string {
  const ed = vscode.window.activeTextEditor;
  if (ed && !ed.selection.isEmpty) {
    return ed.document.getText(ed.selection).replace(/\s+/g, " ").trim().slice(0, 400);
  }
  return "";
}

async function onMessage(msg: any, getResult: () => RecommendResult | undefined): Promise<void> {
  const result = getResult();
  if (!result) {
    return;
  }
  if (msg?.type === "copyRef") {
    await vscode.env.clipboard.writeText(msg.ref);
    vscode.window.setStatusBarMessage(`복사됨: ${msg.ref}`, 3000);
  } else if (msg?.type === "createHarness") {
    const ids: string[] = msg.ids ?? result.recommendations.map((r) => r.id);
    const chosen = result.recommendations
      .filter((r) => ids.includes(r.id))
      .map((r) => ({ id: r.id, version: r.version, type: r.type, name: r.name }));
    await openStarter(result.description, chosen);
  }
}

function esc(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

function nonceStr(): string {
  let s = "";
  const chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789";
  for (let i = 0; i < 24; i++) {
    s += chars[Math.floor(Math.random() * chars.length)];
  }
  return s;
}

function render(r: RecommendResult): string {
  const nonce = nonceStr();
  // score 는 0~1 로 정규화돼 있지 않다(랭킹 점수). 배치 내 최대값 기준 상대 길이로 막대를 그린다.
  const maxScore = Math.max(1e-9, ...r.recommendations.map((x) => x.score));
  const cards = r.recommendations
    .map((rec) => {
      const pct = Math.round(Math.max(0, rec.score / maxScore) * 100);
      const flags = [
        rec.auth_required ? '<span class="flag auth">auth 필요</span>' : "",
        rec.conflicts_with.length ? `<span class="flag conflict">충돌: ${esc(rec.conflicts_with.join(", "))}</span>` : "",
      ]
        .filter(Boolean)
        .join(" ");
      const matched = rec.matched_capabilities.length
        ? `<div class="caps">충족: ${rec.matched_capabilities.map((c) => `<code>${esc(c)}</code>`).join(" ")}</div>`
        : "";
      return `
      <div class="card">
        <div class="card-head">
          <span class="type type-${esc(rec.type)}">${esc(rec.type)}</span>
          <span class="name">${esc(rec.name)}</span>
          <code class="ref">${esc(rec.id)}@${esc(rec.version)}</code>
          <button class="ghost" data-ref="${esc(rec.id)}@${esc(rec.version)}">복사</button>
        </div>
        <div class="score"><div class="bar"><i style="width:${pct}%"></i></div><span title="랭킹 점수">${rec.score.toFixed(2)}</span></div>
        <p class="reason">${esc(rec.reason || rec.summary)}</p>
        ${matched}
        <div class="meta">비용 ${rec.context_tokens} 토큰 · 도구 +${rec.added_tools} ${flags}</div>
      </div>`;
    })
    .join("\n");

  return /* html */ `<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'nonce-${nonce}';">
<style>
  body { font-family: var(--vscode-font-family); color: var(--vscode-foreground); padding: 0 4px 24px; }
  h2 { font-size: 15px; margin: 16px 0 4px; }
  .sub { color: var(--vscode-descriptionForeground); font-size: 12px; margin-bottom: 12px; }
  .reqs code, .caps code, code { background: var(--vscode-textCodeBlock-background); padding: 1px 5px; border-radius: 3px; font-size: 11px; }
  .toolbar { position: sticky; top: 0; background: var(--vscode-editor-background); padding: 10px 0; display: flex; gap: 8px; align-items: center; border-bottom: 1px solid var(--vscode-panel-border); z-index: 2; }
  button { font-family: inherit; font-size: 12px; border: none; border-radius: 4px; padding: 5px 10px; cursor: pointer; }
  button.primary { background: var(--vscode-button-background); color: var(--vscode-button-foreground); }
  button.primary:hover { background: var(--vscode-button-hoverBackground); }
  button.ghost { background: transparent; color: var(--vscode-textLink-foreground); border: 1px solid var(--vscode-panel-border); }
  .card { border: 1px solid var(--vscode-panel-border); border-radius: 6px; padding: 10px 12px; margin: 10px 0; }
  .card-head { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
  .name { font-weight: 600; }
  .ref { color: var(--vscode-descriptionForeground); }
  .card-head .ghost { margin-left: auto; }
  .type { font-size: 10px; text-transform: uppercase; letter-spacing: .04em; padding: 2px 6px; border-radius: 10px; background: var(--vscode-badge-background); color: var(--vscode-badge-foreground); }
  .score { display: flex; align-items: center; gap: 8px; margin: 8px 0 6px; }
  .bar { flex: 1; height: 6px; background: var(--vscode-panel-border); border-radius: 3px; overflow: hidden; }
  .bar i { display: block; height: 100%; background: var(--vscode-progressBar-background); }
  .score span { font-variant-numeric: tabular-nums; font-size: 11px; color: var(--vscode-descriptionForeground); width: 22px; text-align: right; }
  .reason { margin: 6px 0; font-size: 13px; }
  .caps { font-size: 11px; margin: 4px 0; }
  .meta { font-size: 11px; color: var(--vscode-descriptionForeground); margin-top: 6px; }
  .flag { margin-left: 8px; padding: 1px 6px; border-radius: 3px; }
  .flag.auth { background: rgba(255,180,0,.18); color: var(--vscode-editorWarning-foreground); }
  .flag.conflict { background: rgba(255,80,80,.18); color: var(--vscode-editorError-foreground); }
</style>
</head>
<body>
  <div class="toolbar">
    <button class="primary" id="create">harness.yaml 스타터 생성</button>
    <span class="sub" style="margin:0">${r.recommendations.length}개 추천 · 랭킹 ${esc(r.ranking_mode)} · 추출 ${esc(r.extraction_mode)}</span>
  </div>
  <h2>요구 능력</h2>
  <div class="reqs sub">${r.requirements.length ? r.requirements.map((q) => `<code>${esc(q)}</code>`).join(" ") : "— (추출된 요구 능력 없음)"}</div>
  <h2>추천 구성요소</h2>
  ${cards || '<p class="sub">추천 결과가 없습니다. 설명을 더 구체적으로 작성해 보세요.</p>'}
  <script nonce="${nonce}">
    const vscode = acquireVsCodeApi();
    document.getElementById('create')?.addEventListener('click', () => vscode.postMessage({ type: 'createHarness' }));
    for (const b of document.querySelectorAll('button.ghost')) {
      b.addEventListener('click', () => vscode.postMessage({ type: 'copyRef', ref: b.getAttribute('data-ref') }));
    }
  </script>
</body>
</html>`;
}
