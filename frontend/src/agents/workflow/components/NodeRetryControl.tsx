import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { FormField } from '@/components/ui/form-field';
import { Input } from '@/components/ui/input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { ToggleChip } from '@/components/ui/toggle-chip';

import type { RetryConfig, RetryOn } from '../../types/workflow';
import {
  formatBackoff,
  parseBackoff,
  RETRY_MAX_ATTEMPTS,
  RETRY_ON_CHOICES,
  withRetryField,
} from '../retryConfig';

// Radix Select takes no empty value; this one stands for "not set here".
const INHERIT = 'inherit';

const ATTEMPT_CHOICES = Array.from(
  { length: RETRY_MAX_ATTEMPTS },
  (_, index) => index + 1,
);

function sameList<T>(a: T[] | undefined, b: T[] | undefined): boolean {
  return (
    (a ?? []).length === (b ?? []).length &&
    (a ?? []).every((entry, index) => entry === b?.[index])
  );
}

interface NodeRetryControlProps {
  /** The policy set here; unset fields fall back to `inherited`. */
  value: RetryConfig | undefined;
  /** Receives the next policy, or undefined once it sets nothing. */
  onChange: (next: RetryConfig | undefined) => void;
  /** What each unset field runs with: the workflow's defaults, or built-in. */
  inherited: Required<RetryConfig>;
  /** Offer the failures to retry on (agent nodes and workflow defaults). */
  showOn?: boolean;
  labelSurface?: 'background' | 'card' | 'muted';
}

/**
 * Retry settings for a node or a workflow's defaults: how many attempts, the
 * delays between them and, for agents, which failures count. An unset field
 * shows the value it inherits.
 */
export default function NodeRetryControl({
  value,
  onChange,
  inherited,
  showOn = false,
  labelSurface = 'background',
}: NodeRetryControlProps) {
  const { t } = useTranslation();
  const [backoffText, setBackoffText] = useState(() =>
    formatBackoff(value?.backoff_seconds),
  );
  const [backoffError, setBackoffError] = useState<string>();

  // Undo, redo or another node's policy: show what the config now holds,
  // unless the field already reads as it.
  useEffect(() => {
    if (sameList(parseBackoff(backoffText).value, value?.backoff_seconds))
      return;
    setBackoffText(formatBackoff(value?.backoff_seconds));
    setBackoffError(undefined);
    // The field's own text is read, not followed.
  }, [value?.backoff_seconds]);

  const attempts = value?.max_attempts ?? inherited.max_attempts;
  const neverRetries = attempts <= 1;
  const retryOn = value?.on ?? inherited.on;

  const changeBackoff = (text: string) => {
    setBackoffText(text);
    const parsed = parseBackoff(text);
    setBackoffError(parsed.error);
    if (!parsed.error)
      onChange(withRetryField(value, 'backoff_seconds', parsed.value));
  };

  const toggleOn = (choice: RetryOn, on: boolean) => {
    const next = RETRY_ON_CHOICES.filter((entry) =>
      entry === choice ? on : retryOn.includes(entry),
    );
    // Retrying on nothing is what one attempt is for.
    if (next.length === 0) return;
    onChange(
      withRetryField(
        value,
        'on',
        sameList(next, inherited.on) ? undefined : next,
      ),
    );
  };

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-col gap-1.5">
        <div className="flex gap-3">
          <FormField
            labelSurface={labelSurface}
            label={t('agents.workflow.retry.attempts')}
            className="flex-1"
          >
            <Select
              value={
                value?.max_attempts === undefined
                  ? INHERIT
                  : String(value.max_attempts)
              }
              onValueChange={(next) =>
                onChange(
                  withRetryField(
                    value,
                    'max_attempts',
                    next === INHERIT ? undefined : Number(next),
                  ),
                )
              }
            >
              <SelectTrigger size="field" className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={INHERIT}>
                  {t('agents.workflow.retry.inherit', {
                    value: inherited.max_attempts,
                  })}
                </SelectItem>
                {ATTEMPT_CHOICES.map((count) => (
                  <SelectItem key={count} value={String(count)}>
                    {count === 1 ? t('agents.workflow.retry.noRetry') : count}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </FormField>
          <FormField
            labelSurface={labelSurface}
            label={t('agents.workflow.retry.backoff')}
            className="flex-1"
            disabled={neverRetries}
            error={backoffError ? t(backoffError) : undefined}
          >
            <Input
              type="text"
              inputMode="decimal"
              className="font-mono"
              value={backoffText}
              onChange={(e) => changeBackoff(e.target.value)}
              onBlur={() => {
                // Tidy the text, or drop an edit that never parsed.
                setBackoffText(formatBackoff(value?.backoff_seconds));
                setBackoffError(undefined);
              }}
            />
          </FormField>
        </div>
        <p className="text-muted-foreground text-xs">
          {neverRetries
            ? t('agents.workflow.retry.hintOff')
            : t('agents.workflow.retry.hint', {
                backoff: formatBackoff(
                  value?.backoff_seconds ?? inherited.backoff_seconds,
                ),
              })}
        </p>
      </div>
      {showOn && (
        <FormField
          float={false}
          label={t('agents.workflow.retry.on')}
          disabled={neverRetries}
        >
          <div className="flex flex-wrap gap-2">
            {RETRY_ON_CHOICES.map((choice) => (
              <ToggleChip
                key={choice}
                pressed={retryOn.includes(choice)}
                disabled={neverRetries}
                title={t(`agents.workflow.retry.onHint.${choice}`)}
                onPressedChange={(on) => toggleOn(choice, on)}
              >
                {t(`agents.workflow.retry.onChoice.${choice}`)}
              </ToggleChip>
            ))}
          </div>
        </FormField>
      )}
    </div>
  );
}
