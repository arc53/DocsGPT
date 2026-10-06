import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useParams } from 'react-router-dom';

import monitorsService, {
  type DecisionResult,
} from '@/api/services/monitorsService';
import DocsGPTMark from '@/assets/logo-b.svg';
import DocsGPTMarkWhite from '@/assets/logo-w.svg';
import { Alert } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { EmptyState } from '@/components/ui/empty-state';
import { FormField } from '@/components/ui/form-field';
import { LoadingState } from '@/components/ui/loading-state';
import { SectionHeader } from '@/components/ui/section-header';
import { Textarea } from '@/components/ui/textarea';
import { useDarkTheme } from '@/hooks';
import { formatDateTime } from '@/utils/dateTimeUtils';

import type { ApprovalView } from './types';

type Load =
  | { state: 'loading' }
  | { state: 'missing' }
  | { state: 'error' }
  | { state: 'ok'; view: ApprovalView };

/** The default buttons are translated; options the agent wrote are shown as written. */
const DEFAULT_OPTIONS = new Set(['approve', 'reject']);

const variantFor = (option: string, index: number) => {
  const lowered = option.toLowerCase();
  if (lowered === 'reject') return 'destructive-outline' as const;
  return index === 0 ? ('default' as const) : ('outline' as const);
};

/**
 * The public page behind an approval link (`/approve/<token>`). Opening it
 * only reads the question: nothing is decided until a button is pressed,
 * which POSTs the decision (and the optional comment) once.
 */
export default function ApprovalPage() {
  const { t } = useTranslation();
  const { token = '' } = useParams<{ token: string }>();
  const [isDarkTheme] = useDarkTheme();
  const [load, setLoad] = useState<Load>({ state: 'loading' });
  const [comment, setComment] = useState('');
  const [pending, setPending] = useState<string | null>(null);
  const [outcome, setOutcome] = useState<DecisionResult | null>(null);

  const fetchView = useCallback(async () => {
    setLoad({ state: 'loading' });
    const result = await monitorsService.getApproval(token);
    setLoad(result.state === 'ok' ? result : { state: result.state });
  }, [token]);

  useEffect(() => {
    void fetchView();
  }, [fetchView]);

  const label = (option: string) =>
    DEFAULT_OPTIONS.has(option.toLowerCase())
      ? t(`approval.options.${option.toLowerCase()}`)
      : option;

  const decide = async (option: string) => {
    setPending(option);
    const result = await monitorsService.decideApproval(token, option, comment);
    setPending(null);
    setOutcome(result);
  };

  const shell = (children: React.ReactNode) => (
    <main className="bg-background flex min-h-dvh flex-col items-center px-4 py-10">
      <div className="flex w-full max-w-xl flex-col gap-6">
        <img
          src={isDarkTheme ? DocsGPTMarkWhite : DocsGPTMark}
          alt={t('approval.logoAlt')}
          className="h-10 w-auto self-start"
        />
        {children}
      </div>
    </main>
  );

  if (load.state === 'loading') return <LoadingState fill="screen" />;
  if (load.state === 'missing') {
    return shell(
      <EmptyState
        size="sm"
        illustration="none"
        title={t('approval.missingTitle')}
        description={t('approval.missingDescription')}
      />,
    );
  }
  if (load.state === 'error') {
    return shell(
      <EmptyState
        size="sm"
        illustration="none"
        tone="destructive"
        title={t('approval.loadError')}
        onRetry={() => void fetchView()}
      />,
    );
  }

  const { view } = load;
  const decided =
    outcome?.state === 'decided'
      ? outcome.decision
      : outcome?.state === 'already'
        ? (outcome.decision ?? view.decision)
        : view.decided
          ? view.decision
          : null;
  const open = !decided && view.waiting && outcome?.state !== 'missing';

  return shell(
    <Card variant="outline" padding="lg" className="gap-5">
      <SectionHeader
        as="h2"
        size="title"
        title={view.question || t('approval.untitled')}
      />
      {view.details && (
        <p
          className="text-foreground text-sm wrap-break-word whitespace-pre-wrap"
          data-testid="approval-details"
        >
          {view.details}
        </p>
      )}
      {decided ? (
        <Alert variant="success" role="status">
          {outcome?.state === 'decided'
            ? t('approval.thanks', {
                decision: label(decided),
                interpolation: { escapeValue: false },
              })
            : t('approval.alreadyDecided', {
                decision: label(decided),
                interpolation: { escapeValue: false },
              })}
        </Alert>
      ) : !open ? (
        <Alert variant="info" role="status">
          {t('approval.notWaiting')}
        </Alert>
      ) : (
        <div className="flex flex-col gap-5">
          {view.allow_comment && (
            <FormField label={t('approval.commentLabel')}>
              <Textarea
                value={comment}
                maxLength={2000}
                onChange={(event) => setComment(event.target.value)}
                placeholder={t('approval.commentPlaceholder')}
              />
            </FormField>
          )}
          {outcome?.state === 'limited' && (
            <Alert variant="warning">{t('approval.rateLimited')}</Alert>
          )}
          {(outcome?.state === 'error' || outcome?.state === 'invalid') && (
            <Alert variant="destructive">{t('approval.submitError')}</Alert>
          )}
          <div className="flex flex-wrap gap-2">
            {view.options.map((option, index) => (
              <Button
                key={option}
                type="button"
                shape="pill"
                variant={variantFor(option, index)}
                loading={pending === option}
                disabled={pending !== null}
                onClick={() => void decide(option)}
              >
                {label(option)}
              </Button>
            ))}
          </div>
          <p className="text-muted-foreground text-xs">
            {t('approval.onceOnly')}
            {view.expires_at && (
              <>
                {' '}
                {t('approval.expiresAt', {
                  date: formatDateTime(view.expires_at),
                })}
              </>
            )}
          </p>
        </div>
      )}
    </Card>,
  );
}
