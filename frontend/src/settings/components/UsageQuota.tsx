import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';

import userService from '../../api/services/userService';
import { selectToken } from '../../preferences/preferenceSlice';

type Budget = { limit: number | null; used: number };
type Bucket = {
  bucket: string;
  tokens: Budget;
  cost: Budget;
  resets_at: string;
};

function Meter({
  label,
  budget,
  format,
}: {
  label: string;
  budget: Budget;
  format: (value: number) => string;
}) {
  const { t } = useTranslation();
  if (budget.limit === null) return null;
  const percent =
    budget.limit <= 0
      ? 100
      : Math.min(100, Math.max(0, (budget.used / budget.limit) * 100));
  const tone =
    percent >= 100
      ? 'bg-red-500'
      : percent >= 80
        ? 'bg-amber-500'
        : 'bg-[#7D54D1]';
  return (
    <div className="min-w-48 flex-1">
      <div className="flex items-baseline justify-between gap-3 text-sm">
        <span className="text-muted-foreground">{label}</span>
        <span className="text-foreground tabular-nums">
          {t('settings.analytics.quota.usedOf', {
            used: format(budget.used),
            limit: format(budget.limit),
          })}
        </span>
      </div>
      <div
        className="bg-muted mt-1 h-1.5 w-full overflow-hidden rounded-full"
        role="progressbar"
        aria-label={label}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(percent)}
      >
        <div
          className={`h-full rounded-full ${tone}`}
          style={{ width: `${percent}%` }}
        />
      </div>
    </div>
  );
}

/** The caller's usage against the quota an admin set; renders nothing when unlimited. */
export default function UsageQuota() {
  const { t, i18n } = useTranslation();
  const token = useSelector(selectToken);
  const [buckets, setBuckets] = useState<Bucket[]>([]);

  useEffect(() => {
    let cancelled = false;
    userService
      .getQuota(token)
      .then((res: Response) => (res.ok ? res.json() : null))
      .then((json: { buckets?: Bucket[] } | null) => {
        if (cancelled) return;
        setBuckets(json?.buckets ?? []);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [token]);

  if (buckets.length === 0) return null;

  const number = new Intl.NumberFormat(i18n.language);
  const usd = new Intl.NumberFormat(i18n.language, {
    style: 'currency',
    currency: 'USD',
  });
  const reset = new Date(buckets[0].resets_at);
  const resetsAt = Number.isNaN(reset.getTime())
    ? ''
    : new Intl.DateTimeFormat(i18n.language, {
        dateStyle: 'medium',
        timeStyle: 'short',
      }).format(reset);

  // A request must fit its own bucket and ``all``, so each limited one is shown.
  const scopeLabel = (name: string) =>
    name === 'direct' || name === 'agent'
      ? t(`settings.analytics.quota.scope.${name}`)
      : null;

  return (
    <div className="border-border mb-6 rounded-2xl border px-6 py-5">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="text-foreground font-bold">
          {t('settings.analytics.quota.title')}
        </p>
        {resetsAt ? (
          <p className="text-muted-foreground text-xs">
            {t('settings.analytics.quota.resets', { resetsAt })}
          </p>
        ) : null}
      </div>
      {buckets.map((bucket) => (
        <div key={bucket.bucket} className="mt-3">
          {scopeLabel(bucket.bucket) ? (
            <p className="text-muted-foreground mb-1 text-xs">
              {scopeLabel(bucket.bucket)}
            </p>
          ) : null}
          <div className="flex flex-wrap gap-6">
            <Meter
              label={t('settings.analytics.quota.tokens')}
              budget={bucket.tokens}
              format={(value) => number.format(value)}
            />
            <Meter
              label={t('settings.analytics.quota.cost')}
              budget={bucket.cost}
              format={(value) => usd.format(value)}
            />
          </div>
        </div>
      ))}
    </div>
  );
}
