import Spinner from '../components/Spinner';

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
  if (!value) return '—';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString();
}

export function fmtDateShort(value?: string | null): string {
  if (!value) return '—';
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? String(value)
    : date.toLocaleDateString(undefined, {
        month: 'short',
        day: 'numeric',
        year: 'numeric',
      });
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

export function fmtCompact(n?: number | null): string {
  return new Intl.NumberFormat(undefined, {
    notation: 'compact',
    maximumFractionDigits: 1,
  }).format(n ?? 0);
}

// Humanized auth-event labels + semantic color tier, shared by the Audit feed
// and the user-detail modal so the same event reads identically everywhere.
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
  scim_activated: 'Activated (SCIM)',
};

export function eventLabel(event: string): string {
  return (
    EVENT_LABELS[event] ??
    event.replace(/_/g, ' ').replace(/^\w/, (c) => c.toUpperCase())
  );
}

export function eventTone(event: string): Tone {
  if (
    event === 'oidc_login_denied' ||
    event === 'admin_user_deactivated' ||
    event === 'scim_deactivated'
  )
    return 'danger';
  if (event === 'role_granted') return 'brand';
  if (event === 'role_revoked' || event === 'admin_sessions_revoked')
    return 'warning';
  return 'muted';
}

// 127.0.0.1 / ::1 are noise in dev — collapse to a muted "local" chip so real
// external IPs stand out in the audit feed.
export function isLoopback(ip?: string | null): boolean {
  return ip === '127.0.0.1' || ip === '::1' || ip === 'localhost';
}
