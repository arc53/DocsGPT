// Persisted dismissal lists for SSE-driven toasts. Without persistence
// the next page's backlog replay re-fires the events and pops the
// toast back. TTL matches the backend's stream retention.

export interface DismissedEntry {
  id: string;
  at: number;
}

export function loadDismissed(key: string, ttlMs: number): DismissedEntry[] {
  if (typeof localStorage === 'undefined') return [];
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    const cutoff = Date.now() - ttlMs;
    return parsed.filter(
      (e): e is DismissedEntry =>
        !!e &&
        typeof e === 'object' &&
        typeof (e as DismissedEntry).id === 'string' &&
        typeof (e as DismissedEntry).at === 'number' &&
        (e as DismissedEntry).at >= cutoff,
    );
  } catch {
    return [];
  }
}

export function saveDismissed(key: string, list: DismissedEntry[]): void {
  if (typeof localStorage === 'undefined') return;
  try {
    localStorage.setItem(key, JSON.stringify(list));
  } catch {
    // Best-effort: ignore quota / private-mode errors.
  }
}

export function isDismissed(list: DismissedEntry[], id: string): boolean {
  return list.some((e) => e.id === id);
}
