export interface WikiPageNode {
  path: string;
  title?: string | null;
  token_count?: number;
  embed_status?: string;
  version?: number;
  updated_by?: string | null;
  updated_via?: string | null;
  updated_at?: string | null;
  content?: string;
}

const RELATIVE_UNITS: [Intl.RelativeTimeFormatUnit, number][] = [
  ['year', 31536000000],
  ['month', 2592000000],
  ['day', 86400000],
  ['hour', 3600000],
  ['minute', 60000],
];

export function formatRelativeTime(
  value: string | null | undefined,
  now: number = Date.now(),
): string | null {
  if (!value) return null;
  const then = new Date(value).getTime();
  if (Number.isNaN(then)) return null;
  const diffMs = now - then;
  const formatter = new Intl.RelativeTimeFormat('en', { numeric: 'auto' });
  for (const [unit, ms] of RELATIVE_UNITS) {
    if (Math.abs(diffMs) >= ms) {
      return formatter.format(-Math.round(diffMs / ms), unit);
    }
  }
  return formatter.format(0, 'second');
}

export function provenanceKey(
  via?: string | null,
  by?: string | null,
  currentUserSub?: string | null,
): 'you' | 'agent' | 'human' | 'unknown' {
  if (by && currentUserSub && by === currentUserSub) return 'you';
  if (via === 'agent') return 'agent';
  if (via === 'human') return 'human';
  return 'unknown';
}

export type SaveOutcome =
  | { status: 'saved'; page: WikiPageNode | null }
  | { status: 'conflict'; page: WikiPageNode | null }
  | { status: 'forbidden' }
  | { status: 'error' };

interface WikiSaveService {
  updateWikiPage: (
    sourceId: string,
    data: { path: string; content: string; expected_version?: number },
    token: string | null,
  ) => Promise<Response>;
  getWikiPage: (
    sourceId: string,
    path: string,
    token: string | null,
  ) => Promise<Response>;
}

export async function saveWikiPage(
  service: WikiSaveService,
  sourceId: string,
  path: string,
  draft: string,
  expectedVersion: number | undefined,
  token: string | null,
): Promise<SaveOutcome> {
  const response = await service.updateWikiPage(
    sourceId,
    { path, content: draft, expected_version: expectedVersion },
    token,
  );
  if (response.ok) {
    const data = await response.json();
    return { status: 'saved', page: data?.page ?? null };
  }
  if (response.status === 409) {
    const refreshed = await service.getWikiPage(sourceId, path, token);
    const data = await refreshed.json();
    return { status: 'conflict', page: data?.page ?? null };
  }
  if (response.status === 403) return { status: 'forbidden' };
  return { status: 'error' };
}
