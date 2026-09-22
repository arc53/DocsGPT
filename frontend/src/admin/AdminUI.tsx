import Spinner from '../components/Spinner';
import { formatDateOnly, formatDateTime } from '../utils/dateTimeUtils';

export function Loading() {
  return (
    <div className="flex h-40 items-center justify-center">
      <Spinner />
    </div>
  );
}

export function LoadError({
  message = 'Failed to load.',
}: {
  message?: string;
}) {
  return <p className="text-muted-foreground mt-8 text-sm">{message}</p>;
}

export function StatCard({
  label,
  value,
  sub,
}: {
  label: string;
  value: React.ReactNode;
  sub?: string;
}) {
  return (
    <div className="border-border dark:border-border rounded-2xl border px-6 py-5">
      <p className="text-muted-foreground text-sm">{label}</p>
      <p className="text-foreground dark:text-foreground mt-1 text-2xl font-bold tabular-nums">
        {value}
      </p>
      {sub ? <p className="text-muted-foreground mt-1 text-xs">{sub}</p> : null}
    </div>
  );
}

type Tone = 'default' | 'success' | 'danger' | 'muted' | 'brand' | 'warning';

const TONES: Record<Tone, string> = {
  default: 'bg-muted text-foreground',
  success:
    'bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300',
  danger: 'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300',
  muted: 'bg-muted text-muted-foreground',
  // brand violet — matches the chart's --primary; used for the Admin role.
  brand:
    'bg-[#7D54D1]/15 text-[#7D54D1] dark:bg-violet-900/40 dark:text-violet-300',
  warning:
    'bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300',
};

export function Pill({
  tone = 'default',
  children,
}: {
  tone?: Tone;
  children: React.ReactNode;
}) {
  return (
    <span
      className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${TONES[tone]}`}
    >
      {children}
    </span>
  );
}

export function fmtDate(value?: string | null): string {
  return value ? formatDateTime(value) : '—';
}

export function fmtDateShort(value?: string | null): string {
  return value ? formatDateOnly(value) : '—';
}

export function fmtRelative(value?: string | null): string {
  if (!value) return 'never';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  const sec = Math.round((Date.now() - date.getTime()) / 1000);
  if (sec < 60) return 'just now';
  const min = Math.round(sec / 60);
  if (min < 60) return `${min}m ago`;
  const hr = Math.round(min / 60);
  if (hr < 24) return `${hr}h ago`;
  const day = Math.round(hr / 24);
  if (day < 7) return `${day}d ago`;
  if (day < 30) return `${Math.round(day / 7)}w ago`;
  if (day < 365) return `${Math.round(day / 30)}mo ago`;
  return `${Math.round(day / 365)}y ago`;
}

export function fmtNumber(n?: number | null): string {
  return new Intl.NumberFormat().format(n ?? 0);
}

/**
 * USD, with enough precision that a fraction of a cent is not rendered as $0.
 * An instance on a cheap model can run whole days under a dollar, and "$0"
 * next to a cost quota reads as "nothing is being counted".
 */
export function fmtUsd(n?: number | null): string {
  const value = n ?? 0;
  const digits = value !== 0 && Math.abs(value) < 0.01 ? 4 : 2;
  return new Intl.NumberFormat(undefined, {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 2,
    maximumFractionDigits: digits,
  }).format(value);
}

/** Milliseconds as ms or s, or an em dash when nothing was measured. */
export function fmtMs(n?: number | null): string {
  if (n === null || n === undefined) return '—';
  return n < 1000 ? `${Math.round(n)}ms` : `${(n / 1000).toFixed(1)}s`;
}

export function fmtCompact(n?: number | null): string {
  return new Intl.NumberFormat(undefined, {
    notation: 'compact',
    maximumFractionDigits: 1,
  }).format(n ?? 0);
}

// Humanized event labels + semantic color tier, shared by the activity feed
// and the user-detail modal so the same event reads identically everywhere.
// Unknown names fall back to a title-cased form of the name itself, so an
// event added by a newer release is still legible here.
const EVENT_LABELS: Record<string, string> = {
  oidc_login: 'Login',
  oidc_login_denied: 'Login denied',
  oidc_refresh: 'Token refresh',
  backchannel_logout: 'Logout (SSO)',
  role_granted: 'Admin granted',
  role_revoked: 'Admin revoked',
  admin_user_deactivated: 'Deactivated',
  admin_user_activated: 'Activated',
  admin_sessions_revoked: 'Sessions revoked',
  scim_created: 'Provisioned',
  scim_deactivated: 'Deactivated (SCIM)',
  scim_reactivated: 'Activated (SCIM)',
  quota_policy_set: 'Quota set',
  quota_policy_deleted: 'Quota removed',
  pat_created: 'Token created',
  pat_revoked: 'Token revoked',
  pat_regenerated: 'Token regenerated',
  'team.create': 'Team created',
  'team.delete': 'Team deleted',
  'team.member_add': 'Member added',
  'team.member_role': 'Member role changed',
  'team.member_remove': 'Member removed',
  'team.share': 'Resource shared',
  'team.unshare': 'Resource unshared',
  'team.transfer_owner': 'Ownership transferred',
  'source.created': 'Source created',
  'source.deleted': 'Source deleted',
  'source.reingested': 'Source reingested',
  'agent.created': 'Agent created',
  'agent.updated': 'Agent updated',
  'agent.deleted': 'Agent deleted',
  'agent.key_regenerated': 'Agent key rotated',
  'conversation.deleted': 'Conversation deleted',
  'conversation.deleted_all': 'All conversations deleted',
  'device.run_command': 'Device command',
  'guardrail.input': 'Guardrail (input)',
  'guardrail.retrieval': 'Guardrail (retrieval)',
  'guardrail.tool_result': 'Guardrail (tool result)',
  'guardrail.output': 'Guardrail (output)',
};

export function eventLabel(event: string): string {
  const known = EVENT_LABELS[event];
  if (known) return known;
  // "source.reingested" -> "Source reingested"
  return event.replace(/[._]/g, ' ').replace(/^\w/, (c) => c.toUpperCase());
}

// Events that describe something being taken away or refused.
const DANGER_EVENTS = new Set([
  'oidc_login_denied',
  'admin_user_deactivated',
  'scim_deactivated',
  'source.deleted',
  'agent.deleted',
  'conversation.deleted',
  'conversation.deleted_all',
  'team.delete',
]);

const WARNING_EVENTS = new Set([
  'role_revoked',
  'admin_sessions_revoked',
  'pat_revoked',
  'agent.key_regenerated',
  'quota_policy_deleted',
  'team.member_remove',
  'team.unshare',
]);

export function eventTone(event: string): Tone {
  if (DANGER_EVENTS.has(event)) return 'danger';
  if (event === 'role_granted') return 'brand';
  if (WARNING_EVENTS.has(event)) return 'warning';
  return 'muted';
}

// Category facet colors. Mirrors docsgpt/audit_events.py.
const CATEGORY_TONES: Record<string, Tone> = {
  identity: 'default',
  access: 'brand',
  config: 'warning',
  data: 'success',
  device: 'warning',
  safety: 'danger',
  other: 'muted',
};

export function categoryTone(category: string): Tone {
  return CATEGORY_TONES[category] ?? 'muted';
}

// A guardrail "blocked" or a device "denied" is the row's headline, so it gets
// the same treatment as a dangerous event name.
const DANGER_OUTCOMES = new Set(['blocked', 'denied', 'error', 'failed']);

export function outcomeTone(outcome: string): Tone {
  if (DANGER_OUTCOMES.has(outcome)) return 'danger';
  if (outcome === 'allowed' || outcome === 'passed') return 'success';
  return 'muted';
}

// 127.0.0.1 / ::1 are noise in dev — collapse to a muted "local" chip so real
// external IPs stand out in the audit feed.
export function isLoopback(ip?: string | null): boolean {
  return ip === '127.0.0.1' || ip === '::1' || ip === 'localhost';
}
