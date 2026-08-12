// 생성 마법사 드래프트 — 탭 이동·새로고침에도 진행 상태를 보존(localStorage).
const KEY = "harness.draft";

export function loadDraft<T>(): T | null {
  try {
    const raw = localStorage.getItem(KEY);
    return raw ? (JSON.parse(raw) as T) : null;
  } catch {
    return null;
  }
}

export function saveDraft(draft: unknown): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(draft));
  } catch {
    /* 용량 초과 등 — 조용히 무시 */
  }
}

export function clearDraft(): void {
  localStorage.removeItem(KEY);
}
