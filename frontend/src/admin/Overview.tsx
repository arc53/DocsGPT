import { useEffect, useState } from 'react';
import { useSelector } from 'react-redux';
import { Link } from 'react-router-dom';

import adminService from '../api/services/adminService';
import { selectToken } from '../preferences/preferenceSlice';
import { Loading, LoadError, StatCard, fmtNumber } from './AdminUI';

function Section({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div className="mt-8">
      <p className="text-muted-foreground mb-3 text-sm font-medium">{title}</p>
      {children}
    </div>
  );
}

export default function Overview() {
  const token = useSelector(selectToken);
  const [data, setData] = useState<any | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    adminService
      .getOverview(token)
      .then((res) => res.json())
      .then((json) => {
        if (!cancelled) {
          setData(json);
          setLoading(false);
        }
      })
      .catch(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [token]);

  if (loading) return <Loading />;
  if (!data?.success) return <LoadError message="Failed to load overview." />;

  const users = data.users ?? {};
  const failed = data.failed_logins_7d ?? 0;

  return (
    <div>
      <Section title="Users">
        <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
          <StatCard
            label="Total users"
            value={fmtNumber(users.total)}
            sub={`${fmtNumber(users.active)} active · ${fmtNumber(users.inactive)} inactive`}
          />
          <StatCard label="Admins" value={fmtNumber(data.admins)} />
          <StatCard
            label="New users (7d)"
            value={fmtNumber(data.new_users_7d)}
          />
          <StatCard
            label="Active users (30d)"
            value={fmtNumber(data.active_users_30d)}
          />
        </div>
      </Section>

      <Section title="Activity">
        <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
          <StatCard label="Agents" value={fmtNumber(data.agents)} />
          <StatCard label="Sources" value={fmtNumber(data.sources)} />
          <StatCard
            label="Conversations"
            value={fmtNumber(data.conversations)}
          />
          <StatCard label="Tokens (30d)" value={fmtNumber(data.tokens_30d)} />
        </div>
      </Section>

      <Section title="Security & access">
        <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
          <div
            className={`rounded-2xl border px-6 py-5 ${
              failed > 0
                ? 'border-red-300 bg-red-50 dark:border-red-900/50 dark:bg-red-950/30'
                : 'border-border'
            }`}
          >
            <p className="text-muted-foreground text-sm">Failed logins (7d)</p>
            <p
              className={`mt-1 text-2xl font-bold tabular-nums ${
                failed > 0
                  ? 'text-red-600 dark:text-red-400'
                  : 'text-foreground'
              }`}
            >
              {fmtNumber(failed)}
            </p>
            {failed > 0 ? (
              <Link
                to="/admin/audit?event=oidc_login_denied"
                className="mt-2 inline-block text-xs text-red-600 hover:underline dark:text-red-400"
              >
                View in Audit →
              </Link>
            ) : (
              <p className="text-muted-foreground mt-2 text-xs">
                No denied logins
              </p>
            )}
          </div>
        </div>
      </Section>
    </div>
  );
}
