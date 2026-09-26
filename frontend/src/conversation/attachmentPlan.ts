import type {
  AttachmentPlanEntry,
  AttachmentPlanStatus,
} from './conversationModels';

// Where each file of a turn ended up, as the backend planned it: read in
// full, read in part, left out but reachable through search, or not usable.

type AttachedFile = { id: string; fileName: string };

/** The plan entry for one attached file, matched by any id it went by. */
export function planEntryFor(
  plan: AttachmentPlanEntry[] | undefined,
  file: AttachedFile,
): AttachmentPlanEntry | undefined {
  if (!plan || !file?.id) return undefined;
  return plan.find(
    (entry) =>
      entry.id === file.id ||
      entry.upload_id === file.id ||
      (entry.aliases ?? []).includes(file.id),
  );
}

export type PlanSummary = {
  total: number;
  inFull: number;
  searchable: number;
  notIncluded: number;
};

/**
 * Counts for the files attached to one message. Returns null when every file
 * was read in full (or there is no plan), so nothing needs saying.
 */
export function summarizePlan(
  plan: AttachmentPlanEntry[] | undefined,
  files: AttachedFile[] | undefined,
): PlanSummary | null {
  if (!plan || !files || files.length === 0) return null;
  const seen = new Set<string>();
  const counts: PlanSummary = {
    total: 0,
    inFull: 0,
    searchable: 0,
    notIncluded: 0,
  };
  for (const file of files) {
    const entry = planEntryFor(plan, file);
    if (!entry || seen.has(entry.ref)) continue;
    seen.add(entry.ref);
    counts.total += 1;
    if (entry.status === 'inline') counts.inFull += 1;
    else if (entry.status === 'partial' || entry.status === 'tool')
      counts.searchable += 1;
    else counts.notIncluded += 1;
  }
  if (counts.total === 0 || counts.inFull === counts.total) return null;
  return counts;
}

const STATUSES: AttachmentPlanStatus[] = [
  'inline',
  'partial',
  'tool',
  'omitted',
  'unreadable',
];

/** Keep only well-formed entries from a server payload. */
export function parseAttachmentPlan(
  raw: unknown,
): AttachmentPlanEntry[] | undefined {
  if (!Array.isArray(raw)) return undefined;
  const entries = raw.filter(
    (entry): entry is AttachmentPlanEntry =>
      !!entry &&
      typeof entry === 'object' &&
      typeof (entry as AttachmentPlanEntry).ref === 'string' &&
      typeof (entry as AttachmentPlanEntry).id === 'string' &&
      STATUSES.includes((entry as AttachmentPlanEntry).status),
  );
  return entries.length > 0 ? entries : undefined;
}
