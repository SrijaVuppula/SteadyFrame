// Checks started from this browser, newest first, so the sidebar can list them. Per-viewer
// convenience only: storage can be unavailable (private windows, blocked site data), and the
// page works the same without it.
export interface RecentCheck {
  jobId: string;
  label: string;
  policy: string;
  at: number;
  status?: string;
}

const KEY = 'steadyframe.recent';
const MAX = 8;

export function loadRecent(): RecentCheck[] {
  try {
    const v = JSON.parse(localStorage.getItem(KEY) ?? '[]') as RecentCheck[];
    return Array.isArray(v) ? v.slice(0, MAX) : [];
  } catch {
    return [];
  }
}

export function saveRecent(list: RecentCheck[]): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(list.slice(0, MAX)));
  } catch {
    // storage blocked: the list lives for this page view only
  }
}
