import { Gauge, Pause } from 'lucide-react';
import { useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector, useStore } from 'react-redux';
import { Link } from 'react-router-dom';

import {
  Alert,
  AlertAction,
  AlertDescription,
  AlertTitle,
} from '../components/ui/alert';
import { headingLocale } from '../utils/dateTimeUtils';
import type { OutsideAccessKind } from './types';
import { resetSentence, usagePeriodOf, usagePeriodValues } from './usagePeriod';
import {
  loadUsage,
  selectQuota,
  selectUsageNotice,
  selectUsagePaused,
  usageFocused,
  type UsageScope,
  type UsageState,
} from './usageSlice';

type RootLike = {
  usage?: UsageState;
  preference: { token: string | null };
};

const ACCESS_KEYS: Record<OutsideAccessKind, string> = {
  api_key: 'payer.common.access.apiKey',
  public_link: 'payer.common.access.publicLink',
  webhook: 'payer.common.access.webhook',
};

/**
 * Keeps the person's quota fresh while a composer is open: reads it when
 * first shown and when the signed-in person changes, and again on focus (the
 * slice throttles that to every 5 minutes).
 */
export function useUsageRefresh(): void {
  const dispatch = useDispatch();
  const store = useStore<RootLike>();
  const token = useSelector((state: RootLike) => state.preference.token);

  useEffect(() => {
    const { usage } = store.getState();
    if (!usage) return; // A store without the slice: nothing to keep fresh.
    if (usage.status === 'idle' || usage.loadedFor !== token)
      dispatch(loadUsage({ force: true }) as never);
  }, [token]);

  useEffect(() => {
    const onFocus = () => {
      if (document.visibilityState !== 'hidden') dispatch(usageFocused());
    };
    window.addEventListener('focus', onFocus);
    document.addEventListener('visibilitychange', onFocus);
    return () => {
      window.removeEventListener('focus', onFocus);
      document.removeEventListener('visibilitychange', onFocus);
    };
  }, [dispatch]);
}

/**
 * Whether the person has used up an allowance this chat spends from. The
 * composer doesn't send while it is; a refetch (reset, a raised limit,
 * focus) opens it again.
 *
 * Args:
 *   scope: `direct` for a chat without an agent, `agent` with one.
 */
export function useUsageStop(scope: UsageScope): boolean {
  return (
    useSelector((state: RootLike) => selectUsageNotice(state, scope))?.level ===
    'reached'
  );
}

type UsageNoticeProps = {
  /** Which allowance the chat spends from besides `all`. */
  scope: UsageScope;
};

/**
 * Above the chat composer: from 80% of an allowance a quiet line ("You've
 * used 80% of your allowance for November. It resets on 1 Dec."), and at
 * 100% the stop, which says what the allowance covers, when it resets, what
 * else of the person's has paused (their schedules, the agents they
 * published) and links to their usage. Nothing under 80% or when unlimited.
 */
export default function UsageNotice({ scope }: UsageNoticeProps) {
  const { t, i18n } = useTranslation();
  useUsageRefresh();
  const notice = useSelector((state: RootLike) =>
    selectUsageNotice(state, scope),
  );
  const quota = useSelector(selectQuota);
  const paused = useSelector(selectUsagePaused);
  if (!notice) return null;

  const language = i18n.language;
  const period = usagePeriodOf(quota?.period);
  const { month, date, time } = usagePeriodValues(notice.resets_at, language);
  const noEscape = { interpolation: { escapeValue: false } };

  if (notice.level === 'near') {
    const values =
      period === 'day'
        ? { percent: notice.percent, time }
        : period === 'week'
          ? { percent: notice.percent, date }
          : { percent: notice.percent, month, date };
    return (
      <p
        data-testid="usage-near"
        role="status"
        className="text-muted-foreground mb-2 flex items-start gap-1.5 px-2 text-xs"
      >
        <Gauge className="mt-0.5 size-3.5 shrink-0" aria-hidden="true" />
        <span>{t(`payer.notice.near.${period}`, values)}</span>
      </p>
    );
  }

  const covers =
    notice.bucket === 'direct' || notice.bucket === 'agent'
      ? notice.bucket
      : 'all';
  const list = new Intl.ListFormat(
    headingLocale(language === 'jp' ? 'ja' : language),
    { type: 'conjunction' },
  );
  const lines: string[] = [];
  if (paused?.schedules)
    lines.push(
      t('payer.notice.reached.schedules', { count: paused.schedules }),
    );
  for (const agent of paused?.published ?? []) {
    const access = list.format(
      agent.access
        .filter((kind) => kind in ACCESS_KEYS)
        .map((kind) => t(ACCESS_KEYS[kind])),
    );
    lines.push(
      t('payer.notice.reached.published', {
        name: agent.name,
        access,
        ...noEscape,
      }),
    );
  }

  return (
    <Alert variant="warning" data-testid="usage-reached" className="mb-3">
      <AlertTitle>
        {t(`payer.notice.reached.title.${period}`, { month })}
      </AlertTitle>
      <AlertDescription className="mt-1">
        <p>
          {t('payer.notice.reached.body', {
            covers: t(`payer.notice.reached.covers.${covers}`),
            resets: resetSentence(t, period, notice.resets_at, language),
            ...noEscape,
          })}
        </p>
        {lines.length > 0 ? (
          <ul className="mt-2 flex flex-col gap-1 text-xs">
            {lines.map((line) => (
              <li key={line} className="flex items-start gap-1.5">
                <Pause
                  className="mt-0.5 size-3.5 shrink-0"
                  aria-hidden="true"
                />
                <span>{line}</span>
              </li>
            ))}
          </ul>
        ) : null}
        <p className="mt-2">
          <AlertAction asChild>
            <Link to="/settings/analytics">
              {t('payer.notice.reached.seeUsage')}
            </Link>
          </AlertAction>
        </p>
      </AlertDescription>
    </Alert>
  );
}
