// 하네스 로컬 저장소 — 대시보드(F)의 데이터. 백엔드 영속화 전까지 localStorage 사용.
import type { Recommendation } from "../api/client";

const KEY = "harness.saved";

export interface SavedHarness {
  id: string;
  name: string;
  createdAt: number;
  yaml: string;
  components: Recommendation[]; // 재열기 시 선택 복원용
  permissions: Record<string, string>;
}

export function loadSaved(): SavedHarness[] {
  try {
    const raw = localStorage.getItem(KEY);
    return raw ? (JSON.parse(raw) as SavedHarness[]) : [];
  } catch {
    return [];
  }
}

export function saveHarness(h: SavedHarness): SavedHarness[] {
  const list = loadSaved().filter((x) => x.id !== h.id);
  list.unshift(h);
  localStorage.setItem(KEY, JSON.stringify(list));
  return list;
}

export function removeHarness(id: string): SavedHarness[] {
  const list = loadSaved().filter((x) => x.id !== id);
  localStorage.setItem(KEY, JSON.stringify(list));
  return list;
}
