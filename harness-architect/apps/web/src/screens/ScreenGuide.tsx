import type { ReactNode } from "react";
import type { View } from "../components/AppShell";
import { Badge, Button, Card, Kbd, PageHeader } from "../lib/ui";

/**
 * 사용가이드 — 처음 오신 분을 위한 화면별 안내.
 * 각 화면이 무엇을 하는지 + 실제 앱을 캡처한 스크린샷(/public/guide/*.png).
 */
export default function ScreenGuide({
  setView,
  onNewHarness,
}: {
  setView: (v: View) => void;
  onNewHarness: () => void;
}) {
  return (
    <div className="mx-auto max-w-5xl space-y-12 pb-16">
      {/* ── Hero ── */}
      <section>
        <PageHeader
          title="사용가이드"
          subtitle="처음 오셨나요? 각 화면이 무엇을 하고, 어떤 순서로 쓰면 되는지 5분이면 이해할 수 있어요."
        />
        <Card className="bg-gradient-to-br from-accent/10 to-surface">
          <p className="text-sm leading-relaxed text-fg/90">
            <b className="text-fg">Harness</b> 는 “무엇을 만들지”만 설명하면, 필요한 AI 에이전트 구성요소를{" "}
            <b className="text-fg">추천 → 검증 → 실행 가능한 harness.yaml</b> 로 만들어 주는 도구예요. 아키텍처를 직접 설계하지
            않아도 됩니다.
          </p>
          <div className="mt-4 flex flex-wrap gap-2">
            <Button onClick={() => onNewHarness()}>지금 만들어보기 →</Button>
            <Button variant="subtle" onClick={() => setView("catalog")}>
              카탈로그 둘러보기
            </Button>
          </div>
        </Card>
      </section>

      {/* ── 핵심 흐름 한눈에 ── */}
      <section>
        <h2 className="mb-3 text-sm font-semibold text-fg">핵심 흐름 한눈에</h2>
        <div className="flex flex-wrap items-stretch gap-2">
          {FLOW.map((f, i) => (
            <div key={f.title} className="flex items-stretch gap-2">
              <div className="flex min-w-[128px] flex-1 flex-col rounded-xl border border-line bg-surface p-3">
                <span className="text-[10px] font-medium uppercase tracking-wide text-accent">{f.tag}</span>
                <span className="mt-0.5 text-sm font-semibold text-fg">{f.title}</span>
                <span className="mt-1 text-xs leading-snug text-muted">{f.desc}</span>
              </div>
              {i < FLOW.length - 1 && (
                <span className="grid place-items-center text-muted" aria-hidden>
                  →
                </span>
              )}
            </div>
          ))}
        </div>
        <p className="mt-2 text-xs text-muted">
          만든 결과는 <b className="text-fg">하네스</b> 화면에 저장되고, <b className="text-fg">카탈로그</b> 에서 구성요소를
          언제든 둘러볼 수 있어요.
        </p>
      </section>

      {/* ── 1. 생성 ── */}
      <Section n={1} tag="Create" title="생성 — 4단계 마법사" onGo={() => onNewHarness()} goLabel="생성으로 가기">
        <p className="mb-6 text-sm leading-relaxed text-muted">
          왼쪽 메뉴 <NavRef>생성</NavRef> 을 누르면 시작해요. 화면 오른쪽 위에{" "}
          <Badge className="bg-surface-2 text-muted">1 설명</Badge> <Badge className="bg-surface-2 text-muted">2 추천</Badge>{" "}
          <Badge className="bg-surface-2 text-muted">3 검증</Badge> <Badge className="bg-surface-2 text-muted">4 yaml</Badge>{" "}
          단계가 보이고, 순서대로 진행됩니다.
        </p>

        <div className="space-y-8">
          <Step
            n="1"
            title="설명 — 만들려는 걸 그냥 적기"
            features={[
              "만들고 싶은 걸 자연어로 입력합니다 (예: “PR을 자동 리뷰하는 봇”).",
              "아래 예시 칩을 누르면 문장이 자동으로 채워져요.",
              "“추천 받기 →” 를 누르면 필요한 능력을 자동으로 뽑아냅니다.",
            ]}
            src="/guide/01-create-describe.png"
            caption="설명을 입력하고 예시 칩으로 빠르게 시작 — ‘추천 받기 →’ 로 다음 단계."
            label="생성 · 1단계 설명"
          />
          <Step
            n="2"
            title="추천 — 필요한 구성요소 고르기"
            features={[
              "추출된 요구 능력이 상단에 배지로 표시됩니다.",
              "MCP · Skill · Context · Hook 타입별로 추천 카드가 나와요. 카드를 눌러 선택/해제.",
              "오른쪽 “선택 요약” 에서 컨텍스트 예산(8,000토큰)·추가 도구 수를 실시간 확인.",
              "충돌·배타 그룹·인증 필요 항목은 배지로 경고해 줍니다.",
            ]}
            src="/guide/02-create-recommend.png"
            caption="추천 카드를 골라 담으면 오른쪽 요약에 예산 게이지가 실시간으로 채워집니다."
            label="생성 · 2단계 추천"
          />
          <Step
            n="3"
            title="검증 — 문제 없는지 자동 점검"
            features={[
              "참조·충돌 / 의존성(requires) 충족 / 비용 예산 / 인증·권한 4가지를 검사.",
              "상단 배너로 통과·경고·오류를 한 줄로 요약해 줘요.",
              "부족한 의존성(gap)이 있으면 “구성요소 추천 →” 로 돌아가 바로 보완.",
              "오류가 0건이어야 다음 단계로 확정할 수 있습니다.",
            ]}
            src="/guide/03-create-validate.png"
            caption="4가지 검사를 모두 통과하면 초록 배너 — ‘확정 → harness.yaml 생성’ 이 열립니다."
            label="생성 · 3단계 검증"
          />
          <Step
            n="4"
            title="harness.yaml — 실행 가능한 산출물"
            features={[
              "검증을 통과하면 선언적 harness.yaml 이 생성됩니다. “복사” 로 바로 가져가기.",
              "저장하면 하네스 화면과 VSCode 확장에 실시간으로 나타나요.",
              "Eject: claude-code 등 런타임별 네이티브 설정 파일 트리로 방출합니다.",
            ]}
            src="/guide/04-create-yaml.png"
            caption="생성된 harness.yaml 과 eject 패널 — 런타임(claude-code·cursor)별 설정으로 방출."
            label="생성 · 4단계 yaml"
          />
        </div>
      </Section>

      {/* ── 2. 카탈로그 ── */}
      <Section n={2} tag="Catalog" title="카탈로그 — 구성요소 저장소" onGo={() => setView("catalog")} goLabel="카탈로그 열기">
        <FeatureShot
          features={[
            "추천에 쓰이는 모든 구성요소를 직접 둘러보는 곳이에요.",
            "이름·요약·능력으로 검색하고, 타입(MCP/Skill/Context/Hook)으로 필터링.",
            "카드의 능력 태그를 누르면 그 능력으로 좁혀 볼 수 있어요.",
            "카드를 선택하면 오른쪽에 provides·requires·비용·인증·설정 스키마 상세가 떠요.",
            "“+ 신규 저작” 으로 빈 상태에서 새 하네스를 시작할 수도 있습니다.",
          ]}
          src="/guide/05-catalog.png"
          caption="타입 필터 + 검색으로 구성요소를 찾고, 카드를 누르면 오른쪽에 상세가 열립니다."
          label="카탈로그"
        />
      </Section>

      {/* ── 3. 하네스 ── */}
      <Section n={3} tag="Harnesses" title="하네스 — 저장 · 버전 · 팀 공유" onGo={() => setView("harnesses")} goLabel="하네스 열기">
        <FeatureShot
          features={[
            "현재 워크스페이스(개인/팀)에 저장된 하네스 목록입니다.",
            "실시간 동기화(SSE) — 웹과 VSCode 확장 양쪽에 즉시 반영돼요.",
            "“열기” 를 누르면 버전 히스토리와 버전 간 변경점(diff)을 볼 수 있어요.",
            "“+ 새 팀” 으로 팀을 만들고 멤버를 초대(뷰어·에디터·오너 역할)할 수 있습니다.",
            "워크스페이스 전환은 사이드바 맨 위 스위처에서 개인 ↔ 팀으로.",
          ]}
          src="/guide/06-harnesses.png"
          caption="저장된 하네스(버전 배지)와 내 팀 · 멤버 역할이 한 화면에 — 실시간으로 동기화됩니다."
          label="하네스"
        />
      </Section>

      {/* ── 4. 설정 ── */}
      <Section n={4} tag="Settings" title="설정 — 계정 · 토큰 · 키" onGo={() => setView("settings")} goLabel="설정 열기">
        <FeatureShot
          features={[
            "내 계정 정보와 소속 팀 수를 확인해요.",
            "API 토큰 재발급 — 기존 토큰은 즉시 무효화되고, 다른 기기·확장은 재로그인해야 합니다.",
            "LLM 키(Anthropic·Voyage)는 배포 환경변수로만 설정 — 화면에선 상태만 보이고 “연동 확인” 으로 검사.",
            "로그아웃하면 이 브라우저에 남은 이전 사용자 흔적을 모두 제거합니다.",
          ]}
          src="/guide/07-settings.png"
          caption="계정 · API 토큰 · LLM 키(품질 모드) 상태를 한곳에서 관리합니다."
          label="설정"
        />
      </Section>

      {/* ── 5. 어디서나 쓰는 단축 ── */}
      <Section n={5} tag="Everywhere" title="어디서나 쓰는 단축">
        <FeatureShot
          features={[
            <>
              <Kbd>⌘K</Kbd> 커맨드 팔레트 — 섹션 이동 · 새 하네스 · 테마 전환 · 카탈로그/하네스 검색을 한 곳에서.
            </>,
            "워크스페이스 스위처 — 사이드바 상단에서 개인 ↔ 팀 컨텍스트를 전역 전환.",
            "테마 토글 — 사이드바 좌하단 해/달 버튼으로 다크/라이트 전환.",
            "VSCode 확장 — 같은 계정으로 로그인하면 하네스가 실시간으로 동기화됩니다.",
          ]}
          src="/guide/08-palette.png"
          caption="어디서든 ⌘K 로 명령 팔레트를 열어 이동·검색·전환을 빠르게."
          label="⌘K 커맨드 팔레트"
        />
      </Section>

      {/* ── 마무리 CTA ── */}
      <section className="rounded-2xl border border-line bg-surface p-6 text-center">
        <p className="text-sm font-semibold text-fg">준비됐어요. 첫 하네스를 만들어 볼까요?</p>
        <p className="mx-auto mt-1 max-w-md text-xs text-muted">
          한 문장으로 시작해도 괜찮아요. 나머지는 추천·검증이 도와줍니다.
        </p>
        <div className="mt-4 flex justify-center gap-2">
          <Button onClick={() => onNewHarness()}>새 하네스 만들기 →</Button>
          <Button variant="subtle" onClick={() => setView("catalog")}>
            구성요소 먼저 보기
          </Button>
        </div>
      </section>
    </div>
  );
}

/* ────────────────────────── 레이아웃 조각 ────────────────────────── */

const FLOW = [
  { tag: "1 · 설명", title: "설명", desc: "만들 걸 자연어로" },
  { tag: "2 · 추천", title: "추천", desc: "구성요소 고르기" },
  { tag: "3 · 검증", title: "검증", desc: "자동 점검" },
  { tag: "4 · yaml", title: "harness.yaml", desc: "실행 산출물" },
];

function Section({
  n,
  tag,
  title,
  children,
  onGo,
  goLabel,
}: {
  n: number;
  tag: string;
  title: string;
  children: ReactNode;
  onGo?: () => void;
  goLabel?: string;
}) {
  return (
    <section>
      <div className="mb-5 flex items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <span className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-accent text-sm font-semibold text-accent-fg">
            {n}
          </span>
          <div>
            <div className="text-[10px] font-medium uppercase tracking-wide text-accent">{tag}</div>
            <h2 className="text-[15px] font-semibold text-fg">{title}</h2>
          </div>
        </div>
        {onGo && (
          <Button variant="ghost" onClick={onGo}>
            {goLabel} →
          </Button>
        )}
      </div>
      {children}
    </section>
  );
}

/** 기능 목록(위) + 전체폭 스크린샷(아래). */
function FeatureShot({
  features,
  src,
  caption,
  label,
}: {
  features: ReactNode[];
  src: string;
  caption: string;
  label: string;
}) {
  return (
    <div className="space-y-4">
      <div className="grid gap-x-6 gap-y-2 sm:grid-cols-2">
        <FeatureList items={features} />
      </div>
      <Shot src={src} caption={caption} label={label} />
    </div>
  );
}

/** 생성 4단계의 각 스텝 — 번호 + 기능 + 전체폭 스크린샷. */
function Step({
  n,
  title,
  features,
  src,
  caption,
  label,
}: {
  n: string;
  title: string;
  features: ReactNode[];
  src: string;
  caption: string;
  label: string;
}) {
  return (
    <div className="space-y-4">
      <div>
        <div className="flex items-center gap-2">
          <span className="grid h-6 w-6 place-items-center rounded-full bg-accent/15 text-xs font-semibold text-accent">
            {n}
          </span>
          <h3 className="text-sm font-semibold text-fg">{title}</h3>
        </div>
        <div className="mt-3 grid gap-x-6 gap-y-2 sm:grid-cols-2">
          <FeatureList items={features} />
        </div>
      </div>
      <Shot src={src} caption={caption} label={label} />
    </div>
  );
}

function FeatureList({ items }: { items: ReactNode[] }) {
  return (
    <ul className="space-y-2">
      {items.map((it, i) => (
        <li key={i} className="flex gap-2 text-sm leading-relaxed text-fg/90">
          <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-accent" aria-hidden />
          <span>{it}</span>
        </li>
      ))}
    </ul>
  );
}

function NavRef({ children }: { children: ReactNode }) {
  return <span className="rounded-md bg-surface-2 px-1.5 py-0.5 text-xs font-medium text-fg">{children}</span>;
}

/** 브라우저 창 크롬으로 감싼 실제 스크린샷 + 캡션. */
function Shot({ src, caption, label }: { src: string; caption: string; label: string }) {
  return (
    <figure className="overflow-hidden rounded-xl border border-line bg-surface shadow-panel">
      <div className="flex items-center gap-1.5 border-b border-line bg-surface-2 px-3 py-2">
        <span className="h-2.5 w-2.5 rounded-full bg-err/50" />
        <span className="h-2.5 w-2.5 rounded-full bg-warn/50" />
        <span className="h-2.5 w-2.5 rounded-full bg-ok/50" />
        <span className="ml-2 truncate rounded-md bg-bg px-2 py-0.5 text-[10px] text-muted">{label}</span>
      </div>
      <img
        src={src}
        alt={caption}
        loading="lazy"
        className="block w-full border-b border-line"
        style={{ aspectRatio: "2560 / 1640" }}
      />
      <figcaption className="px-3 py-2 text-xs text-muted">{caption}</figcaption>
    </figure>
  );
}
