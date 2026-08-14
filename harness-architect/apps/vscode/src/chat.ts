// 챗 참가자 @harness — Copilot Chat 패널에서 프로젝트를 설명하면 카탈로그 근거로 추천한다.
// 그라운딩은 MCP 서버(recommend_harness), 표현·벤치마크 이유는 사용자의 Copilot 모델(request.model).
import * as vscode from "vscode";
import type { HarnessServer } from "./mcp";
import type { StarterComponent } from "./starter";

interface Rec {
  id: string;
  type: string;
  name: string;
  version: string;
  summary: string;
  score: number;
  reason: string;
  conflicts_with: string[];
  auth_required: boolean;
}

interface RecommendResult {
  description: string;
  requirements: string[];
  ranking_mode: string;
  recommendations: Rec[];
}

export function registerChat(
  context: vscode.ExtensionContext,
  getServer: () => HarnessServer,
): void {
  const handler: vscode.ChatRequestHandler = async (request, _ctx, stream, token) => {
    const description = request.prompt.trim();
    if (!description) {
      stream.markdown(
        "프로젝트를 한두 문장으로 설명해 주세요.\n\n예: `@harness 오전 9시마다 국내 주식 추천해주는 앱`",
      );
      return {};
    }

    stream.progress("카탈로그에서 근거 찾는 중…");
    let result: RecommendResult;
    try {
      result = (await getServer().call("recommend_harness", {
        description,
        top_k: 8,
      })) as RecommendResult;
    } catch (e) {
      stream.markdown(`⚠️ 추천 서버 오류: ${e instanceof Error ? e.message : String(e)}`);
      return {};
    }

    const recs = result.recommendations ?? [];
    if (recs.length === 0) {
      stream.markdown("카탈로그에서 맞는 컴포넌트를 못 찾았습니다. 설명을 더 구체적으로 해보세요.");
      return {};
    }

    if (result.requirements?.length) {
      stream.markdown(`**요구 능력**: ${result.requirements.map((r) => `\`${r}\``).join(", ")}\n\n`);
    }

    // 표현: 모델이 있으면 벤치마크 이유를 스트리밍(그라운딩 고정), 없으면 서버 reason 렌더.
    if (request.model) {
      await streamModelExplanation(request.model, description, recs, stream, token);
    } else {
      renderServerReasons(recs, stream);
    }

    // 권위 있는 그라운딩 — 정확한 ref(모델 표현과 무관하게 이 목록이 사실).
    stream.markdown("\n**추천 구성 (정확한 ref):**\n");
    for (const r of recs) {
      const flags = [
        r.auth_required ? "🔑 auth" : "",
        r.conflicts_with.length ? `⚠︎ 충돌:${r.conflicts_with.join(",")}` : "",
      ]
        .filter(Boolean)
        .join(" ");
      stream.markdown(`- \`${r.id}@${r.version}\` · ${r.type} · ${r.name}${flags ? ` — ${flags}` : ""}\n`);
    }

    const comps: StarterComponent[] = recs.map((r) => ({
      id: r.id,
      version: r.version,
      type: r.type,
      name: r.name,
    }));
    stream.button({
      command: "harness.createStarter",
      title: "harness.yaml 스타터 생성",
      arguments: [description, comps],
    });
    return {};
  };

  const participant = vscode.chat.createChatParticipant("harness.architect", handler);
  participant.iconPath = vscode.Uri.joinPath(context.extensionUri, "media", "harness.svg");
  participant.followupProvider = {
    provideFollowups() {
      return [
        { prompt: "이 중 MCP만 추려서 다시", label: "MCP만" },
        { prompt: "알림은 슬랙 말고 이메일로", label: "알림 방식 바꾸기" },
        { prompt: "더 간단하게, 꼭 필요한 것만", label: "최소 구성" },
      ];
    },
  };
  context.subscriptions.push(participant);
}

function renderServerReasons(recs: Rec[], stream: vscode.ChatResponseStream): void {
  for (const r of recs) {
    stream.markdown(`- **${r.name}** \`${r.id}@${r.version}\` — ${r.reason || r.summary}\n`);
  }
}

async function streamModelExplanation(
  model: vscode.LanguageModelChat,
  description: string,
  recs: Rec[],
  stream: vscode.ChatResponseStream,
  token: vscode.CancellationToken,
): Promise<void> {
  const grounded = recs.slice(0, 8).map((r) => ({
    id: r.id,
    version: r.version,
    type: r.type,
    name: r.name,
    summary: r.summary,
    reason: r.reason,
  }));
  const instruction = [
    "너는 하네스(에이전트 스캐폴딩) 구성 조언자다.",
    "아래 '고정 추천'에 있는 컴포넌트만 사용하고, 목록에 없는 것을 새로 지어내지 마라.",
    "각 컴포넌트를 왜 골랐는지 유명 서비스에 빗대 한 줄씩 설명하라(예: 실시간 웹 그라운딩은 Perplexity처럼).",
    "마지막에 harness.yaml 로 조립하면 된다고 한 문장으로 안내하라. 간결한 마크다운 불릿으로.",
  ].join(" ");
  const prompt = `사용자 설명: ${description}\n\n고정 추천(JSON):\n${JSON.stringify(grounded, null, 2)}`;
  try {
    const resp = await model.sendRequest(
      [vscode.LanguageModelChatMessage.User(`${instruction}\n\n${prompt}`)],
      {},
      token,
    );
    for await (const chunk of resp.text) {
      stream.markdown(chunk);
    }
    stream.markdown("\n");
  } catch {
    // 모델 호출 실패(권한 없음·취소 등) → 서버 reason 으로 폴백.
    renderServerReasons(recs, stream);
  }
}
