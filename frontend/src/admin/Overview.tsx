import { useEffect, useState } from 'react';
import { useSelector } from 'react-redux';
import { Link } from 'react-router-dom';

import adminService from '../api/services/adminService';
import { selectToken } from '../preferences/preferenceSlice';
import { Button } from '@/components/ui/button';
import { LoadingState } from '@/components/ui/loading-state';
import StatCard from '@/components/StatCard';
import { LoadError, fmtNumber } from './AdminUI';

function Section({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    // The shell puts the first group 32px under the title.
    <div className="mt-8 first:mt-0">
      <p className="text-muted-foreground mb-3 text-sm font-medium">{title}</p>
      {children}
    </div>
  );
}

export default function Overview() {
  const token = useSelector(selectToken);
  const [data, setData] = useState<any | null>(null);
  const [loading, setLoading] = useState(true);
  const [reloadKey, setReloadKey] = useState(0);

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
  }, [token, reloadKey]);

  if (loading) return <LoadingState fill="block" />;
  if (!data?.success)
    return (
      <LoadError
        message="Failed to load overview."
        onRetry={() => setReloadKey((k) => k + 1)}
      />
    );

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
          <StatCard
            label="Failed logins (7d)"
            value={fmtNumber(failed)}
            tone={failed > 0 ? 'destructive' : 'default'}
            valueTone={failed > 0 ? 'destructive' : undefined}
            sub={
              failed > 0 ? (
                <Button
                  variant="link"
                  size="inline"
                  asChild
                  // eslint-disable-next-line shadcn/no-restyle -- keeps the tile's destructive tone at hint size
                  className="text-destructive text-xs font-normal"
                >
                  <Link to="/admin/audit?event=oidc_login_denied">
                    View in Audit →
                  </Link>
                </Button>
              ) : (
                'No denied logins'
              )
            }
          />
        </div>
      </Section>
    </div>
  );
}
