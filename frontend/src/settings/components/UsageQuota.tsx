import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';

import { usagePercent } from '../../admin/quotaUtils';
import userService from '../../api/services/userService';
import { Card } from '../../components/ui/card';
import { SectionHeader } from '../../components/ui/section-header';
import { Progress } from '../../components/ui/progress';
import { selectToken } from '../../preferences/preferenceSlice';
import { formatDateTime } from '../../utils/dateTimeUtils';

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
  const percent = usagePercent(budget.used, budget.limit);
  const tone =
    percent >= 100 ? 'destructive' : percent >= 80 ? 'warning' : 'default';
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
      <Progress
        size="sm"
        variant={tone}
        value={percent}
        className="mt-1"
        aria-label={label}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(percent)}
      />
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
    : formatDateTime(buckets[0].resets_at);

  // A request must fit its own bucket and ``all``, so each limited one is shown.
  const scopeLabel = (name: string) =>
    name === 'direct' || name === 'agent'
      ? t(`settings.analytics.quota.scope.${name}`)
      : null;

  return (
    <Card variant="subtle" padding="lg" className="mb-6">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <SectionHeader
          as="h3"
          size="xs"
          title={t('settings.analytics.quota.title')}
        />
        {resetsAt ? (
          <p className="text-muted-foreground text-xs">
            {t('settings.analytics.quota.resets', { resetsAt })}
          </p>
        ) : null}
      </div>
      {buckets.map((bucket) => (
        <div key={bucket.bucket}>
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
    </Card>
  );
}
