import {
  CircleEllipsis,
  KeyRound,
  MessageSquare,
  Repeat,
  type LucideIcon,
} from 'lucide-react';
import { useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';

import { usagePercent } from '../../admin/quotaUtils';
import type {
  QuotaBucket,
  QuotaPartKind,
} from '../../api/services/payerService';
import { Card } from '../../components/ui/card';
import { Progress } from '../../components/ui/progress';
import { SectionHeader } from '../../components/ui/section-header';
import { usagePeriodOf, usagePeriodValues } from '../../payer/usagePeriod';
import { loadUsage, selectQuota } from '../../payer/usageSlice';
import { intlLocale } from '../../utils/dateTimeUtils';

const PART_ICONS: Record<QuotaPartKind, LucideIcon> = {
  chat: MessageSquare,
  schedule: Repeat,
  published: KeyRound,
  other: CircleEllipsis,
};

/**
 * The budget the meter shows: the limited one the person has used most of,
 * as the server picks the 80% notice's. Every request must fit it.
 */
function bindingBudget(
  buckets: QuotaBucket[],
): { bucket: QuotaBucket; budget: 'tokens' | 'cost' } | null {
  let best: { bucket: QuotaBucket; budget: 'tokens' | 'cost' } | null = null;
  let bestRatio = -1;
  for (const bucket of buckets) {
    for (const budget of ['tokens', 'cost'] as const) {
      const { limit, used } = bucket[budget];
      if (limit === null || limit === undefined) continue;
      const ratio = limit > 0 ? used / limit : 1;
      if (ratio > bestRatio) {
        bestRatio = ratio;
        best = { bucket, budget };
      }
    }
  }
  return best;
}

/**
 * Settings › Analytics: the person's allowance as one meter, and what it
 * went on this period (their chats, the schedules they set, the agents they
 * published, and Other). Nothing for an unlimited person.
 */
export default function UsageQuota() {
  const { t, i18n } = useTranslation();
  const dispatch = useDispatch();
  const quota = useSelector(selectQuota);

  // The page shows the numbers as of now, whatever the chat read earlier.
  useEffect(() => {
    dispatch(loadUsage({ force: true }) as never);
  }, [dispatch]);

  const binding = bindingBudget(quota?.buckets ?? []);
  if (!quota || !binding) return null;

  const language = i18n.language;
  const { bucket, budget } = binding;
  const limit = bucket[budget].limit ?? 0;
  const used = bucket[budget].used;
  const isCost = budget === 'cost';
  const format = isCost
    ? new Intl.NumberFormat(intlLocale(language), {
        style: 'currency',
        currency: 'USD',
      }).format
    : new Intl.NumberFormat(intlLocale(language)).format;
  const percent = usagePercent(used, limit);
  const tone =
    percent >= 100 ? 'destructive' : percent >= 80 ? 'warning' : 'default';
  const period = usagePeriodOf(quota.period);
  const { month, date, time } = usagePeriodValues(bucket.resets_at, language);
  const title =
    period === 'month'
      ? t('settings.analytics.quota.titleMonth', { month })
      : t(
          `settings.analytics.quota.title${period === 'week' ? 'Week' : 'Day'}`,
        );
  const resets =
    period === 'day'
      ? time && t('settings.analytics.quota.resetsAt', { time })
      : date && t('settings.analytics.quota.resetsOn', { date });
  const scope =
    bucket.bucket === 'direct' || bucket.bucket === 'agent'
      ? bucket.bucket
      : 'all';
  const allowance = t('settings.analytics.quota.allowance');
  const parts = (quota.parts ?? []).filter(
    (part) => part.kind !== 'other' || part.tokens > 0 || part.cost > 0,
  );

  return (
    <Card variant="subtle" padding="lg" className="mb-6">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        {/* A panel straight under the page's h1, like the charts below. */}
        <SectionHeader as="h2" size="xs" title={title} />
        {resets ? (
          <p className="text-muted-foreground text-xs">{resets}</p>
        ) : null}
      </div>
      <div className="divide-border divide-y">
        <div className="pb-3">
          <div className="flex items-baseline justify-between gap-3">
            <div className="min-w-0">
              <p className="text-foreground text-sm font-medium">{allowance}</p>
              <p className="text-muted-foreground text-xs">
                {t(`settings.analytics.quota.scope.${scope}`)}
              </p>
            </div>
            <p className="text-foreground shrink-0 text-sm whitespace-nowrap tabular-nums">
              {t('settings.analytics.quota.usedOf', {
                used: format(used),
                limit: format(limit),
                interpolation: { escapeValue: false },
              })}
            </p>
          </div>
          <Progress
            size="sm"
            variant={tone}
            value={percent}
            className="mt-2"
            aria-label={allowance}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={Math.round(percent)}
          />
        </div>
        {parts.map((part) => {
          const Icon = PART_ICONS[part.kind] ?? CircleEllipsis;
          return (
            <div
              key={part.kind}
              data-testid="usage-part"
              className="flex items-center gap-3 py-2.5"
            >
              <Icon
                className="text-muted-foreground size-4 shrink-0"
                aria-hidden="true"
              />
              <div className="min-w-0 flex-1">
                <p className="text-foreground text-sm">
                  {t(`settings.analytics.quota.parts.${part.kind}`)}
                </p>
                <p className="text-muted-foreground text-xs">
                  {t(`settings.analytics.quota.parts.${part.kind}Detail`)}
                </p>
              </div>
              <p className="text-foreground shrink-0 text-sm tabular-nums">
                {format(isCost ? part.cost : part.tokens)}
              </p>
            </div>
          );
        })}
      </div>
    </Card>
  );
}
