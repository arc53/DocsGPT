import type {
  AccessTokenPolicy,
  AccessTokenScope,
} from '../api/services/patService';

const DAY_MS = 24 * 60 * 60 * 1000;

/** Lifetimes (in days) offered in the create form, before policy filtering. */
export const EXPIRY_PRESETS = [7, 30, 60, 90, 180, 365];
/** `expires_in_days` value the server reads as "never expires". */
export const NO_EXPIRY = 0;
/** Tokens expiring within this many days get a warning style. */
export const EXPIRY_WARNING_DAYS = 7;
/** Families `chat:run` acts on, so they may be restricted alongside it. */
const CHAT_FAMILIES = ['agents', 'sources'];

const UUID_REGEX =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** The server only accepts UUIDs in `resource_filter` (built-ins like `default` are not). */
export const isUuid = (value: unknown): value is string =>
  typeof value === 'string' && UUID_REGEX.test(value);

export const scopeFamily = (scope: string): string => scope.split(':')[0];
export const scopeAction = (scope: string): string => scope.split(':')[1] ?? '';

export interface ScopeGroup {
  family: string;
  scopes: AccessTokenScope[];
}

/** Group the server's scope catalog by family, keeping the server's order. */
export function groupScopesByFamily(catalog: AccessTokenScope[]): ScopeGroup[] {
  const groups: ScopeGroup[] = [];
  const byFamily = new Map<string, ScopeGroup>();
  catalog.forEach((scope) => {
    const family = scopeFamily(scope.name);
    let group = byFamily.get(family);
    if (!group) {
      group = { family, scopes: [] };
      byFamily.set(family, group);
      groups.push(group);
    }
    group.scopes.push(scope);
  });
  return groups;
}

/** `x:read` is implied (granted server-side) whenever `x:write` is selected. */
export function isScopeImplied(scope: string, selected: string[]): boolean {
  return (
    scopeAction(scope) === 'read' &&
    selected.includes(`${scopeFamily(scope)}:write`)
  );
}

/**
 * Scopes to send: the selection minus reads that a selected write already
 * implies, in catalog order. The raw selection is kept separately so
 * unticking write restores whatever read was before.
 */
export function scopesToSubmit(
  selected: string[],
  catalog: AccessTokenScope[],
): string[] {
  const chosen = new Set(selected);
  return catalog
    .map((scope) => scope.name)
    .filter((name) => chosen.has(name) && !isScopeImplied(name, selected));
}

/** Filterable families the selected scopes allow restricting, in policy order. */
export function eligibleFilterFamilies(
  selected: string[],
  filterableFamilies: string[],
): string[] {
  const families = new Set(selected.map(scopeFamily));
  const chat = families.has('chat');
  if (chat) CHAT_FAMILIES.forEach((f) => families.add(f));
  // Chat executes tools, which cannot be held to an allowlist, so the server
  // rejects a tools restriction on a token that also has chat:run.
  if (chat) families.delete('tools');
  return filterableFamilies.filter((family) => families.has(family));
}

/** Drop empty and ineligible families; `undefined` when nothing is restricted. */
export function buildResourceFilter(
  selection: Record<string, string[]>,
  eligibleFamilies: string[],
): Record<string, string[]> | undefined {
  const out: Record<string, string[]> = {};
  eligibleFamilies.forEach((family) => {
    const ids = selection[family];
    if (ids && ids.length > 0) out[family] = [...ids];
  });
  return Object.keys(out).length > 0 ? out : undefined;
}

export interface RestrictionCount {
  family: string;
  count: number;
}

/** Per-family counts of a token's `resource_filter`; empty means "all resources". */
export function restrictionCounts(
  resourceFilter: Record<string, string[]> | null | undefined,
): RestrictionCount[] {
  return Object.entries(resourceFilter ?? {})
    .filter(([, ids]) => Array.isArray(ids) && ids.length > 0)
    .map(([family, ids]) => ({ family, count: ids.length }));
}

type ExpiryPolicy = Pick<
  AccessTokenPolicy,
  'default_lifetime_days' | 'max_lifetime_days' | 'allow_non_expiring'
>;

/**
 * Lifetimes (days) to offer: presets within the server maximum, the server
 * default when it isn't a preset, and `NO_EXPIRY` last when allowed.
 */
export function expiryOptions(policy: ExpiryPolicy): number[] {
  const max = policy.max_lifetime_days;
  const days = new Set(EXPIRY_PRESETS.filter((d) => d <= max));
  const fallback = policy.default_lifetime_days;
  if (fallback > 0 && fallback <= max) days.add(fallback);
  // Never leave the select empty (e.g. max below the smallest preset).
  if (days.size === 0 && max > 0) days.add(max);
  const options = Array.from(days).sort((a, b) => a - b);
  if (policy.allow_non_expiring) options.push(NO_EXPIRY);
  return options;
}

/** The option preselected in the form: the server default, clamped to what's offered. */
export function defaultExpiry(policy: ExpiryPolicy): number {
  const options = expiryOptions(policy);
  if (options.includes(policy.default_lifetime_days)) {
    return policy.default_lifetime_days;
  }
  const finite = options.filter((d) => d !== NO_EXPIRY);
  return finite.length > 0 ? finite[finite.length - 1] : NO_EXPIRY;
}

/**
 * Lifetime to preselect when regenerating: what the token was last issued
 * with, when the policy still offers it; otherwise the policy default.
 */
export function renewalExpiry(
  item: {
    created_at: string | null;
    regenerated_at?: string | null;
    expires_at: string | null;
  },
  policy: ExpiryPolicy,
): number {
  const options = expiryOptions(policy);
  if (!item.expires_at) {
    return options.includes(NO_EXPIRY) ? NO_EXPIRY : defaultExpiry(policy);
  }
  const issued = Date.parse(item.regenerated_at || item.created_at || '');
  const expires = Date.parse(item.expires_at);
  if (Number.isNaN(issued) || Number.isNaN(expires)) {
    return defaultExpiry(policy);
  }
  const days = Math.round((expires - issued) / DAY_MS);
  return options.includes(days) ? days : defaultExpiry(policy);
}

export type ExpiryStatus = 'never' | 'expired' | 'expiringSoon' | 'ok';

export function expiryStatus(
  expiresAt: string | null | undefined,
  now: number = Date.now(),
): ExpiryStatus {
  if (!expiresAt) return 'never';
  const at = Date.parse(expiresAt);
  if (Number.isNaN(at)) return 'ok';
  if (at <= now) return 'expired';
  if (at - now <= EXPIRY_WARNING_DAYS * DAY_MS) return 'expiringSoon';
  return 'ok';
}

/** Tokens that count against `max_per_user`: the server ignores expired ones. */
export function countLiveTokens(
  tokens: { expires_at: string | null }[],
  now: number = Date.now(),
): number {
  return tokens.filter((tk) => expiryStatus(tk.expires_at, now) !== 'expired')
    .length;
}

export interface ResourceOption {
  value: string;
  label: string;
}

/** Families the create form can offer a picker for (workflows have no list endpoint). */
export const PICKER_FAMILIES = ['agents', 'sources', 'prompts', 'tools'];

/**
 * Turn a list-endpoint payload into picker options: only the caller's own
 * items (not team-shared or built-in ones) with ids the server will accept.
 */
export function toResourceOptions(
  family: string,
  payload: unknown,
): ResourceOption[] {
  const envelope = payload as { tools?: unknown } | null;
  const rows: unknown[] = Array.isArray(payload)
    ? payload
    : family === 'tools' && Array.isArray(envelope?.tools)
      ? envelope.tools
      : [];
  return (rows as (Record<string, unknown> | null)[])
    .filter(
      (row): row is Record<string, unknown> =>
        !!row &&
        isUuid(row.id) &&
        row.ownership !== 'team' &&
        !(
          family === 'prompts' &&
          (row.type === 'public' || row.type === 'team')
        ),
    )
    .map((row) => ({
      value: row.id as string,
      label: String(row.customName || row.displayName || row.name || row.id),
    }))
    .sort((a, b) => a.label.localeCompare(b.label));
}

/**
 * i18next HTML-escapes interpolated values by default, which turns a date like
 * 26/09/2026 into `26&#x2F;09&#x2F;2026` and mangles token names containing
 * `&` or `'`. React already escapes on render, so opt out for those values
 * (same approach as utils/streamingStatusUtils.ts).
 */
export const NO_ESCAPE = { interpolation: { escapeValue: false } } as const;
