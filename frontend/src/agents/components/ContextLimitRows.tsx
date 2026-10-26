import { useId } from 'react';
import { useTranslation } from 'react-i18next';

import { Input } from '@/components/ui/input';
import { SettingRow } from '@/components/ui/setting-row';
import { Switch } from '@/components/ui/switch';

import {
  DEFAULT_CONTEXT_WINDOW_LIMIT,
  DEFAULT_HISTORY_TOKEN_LIMIT,
  MIN_CONTEXT_WINDOW_LIMIT,
  MIN_HISTORY_TOKEN_LIMIT,
  type ModelWindow,
  contextLimitMax,
  historyLimitMax,
  isContextLimitInvalid,
  isHistoryLimitInvalid,
} from '../contextLimit';

type Limit = number | null | undefined;

interface ContextLimitRowsProps {
  /** `config.context_window_limit`; null is off. */
  contextLimit: Limit;
  /** `config.history_token_limit`; null is off. */
  historyLimit: Limit;
  /** The largest window of the agent's models; null while unknown. */
  window: ModelWindow | null;
  /** Read-only, for a caller without `edit_policy`. */
  disabled?: boolean;
  onContextLimitChange: (limit: number | null) => void;
  onHistoryLimitChange: (limit: number | null) => void;
}

/** The text field under a limit's switch, with its range error. */
function LimitInput({
  value,
  on,
  invalid,
  error,
  min,
  max,
  disabled,
  label,
  placeholder,
  onChange,
}: {
  value: Limit;
  on: boolean;
  invalid: boolean;
  error: string;
  min: number;
  max: number;
  disabled: boolean;
  label: string;
  placeholder: string;
  onChange: (limit: number) => void;
}) {
  const errorId = useId();
  return (
    <>
      <Input
        type="number"
        min={min}
        max={max}
        step={1000}
        // A switched-on field left empty holds NaN, so it reads as invalid.
        value={on && !Number.isNaN(value) ? (value ?? '') : ''}
        onChange={(e) => {
          const text = e.target.value.trim();
          onChange(text === '' ? Number.NaN : Number(text));
        }}
        disabled={!on || disabled}
        aria-label={label}
        aria-invalid={invalid || undefined}
        aria-describedby={invalid ? errorId : undefined}
        placeholder={placeholder}
      />
      {invalid ? (
        <p
          id={errorId}
          role="alert"
          className="text-destructive mt-1.5 text-xs"
        >
          {error}
        </p>
      ) : null}
    </>
  );
}

/**
 * The Context limit and History limit rows of an agent's Advanced settings,
 * each a Switch with its token field under it, like the usage limits. Off
 * saves null: the model's whole window, and summarizing only near it. The
 * context limit is held to the window of the agent's models, and the history
 * limit below the context limit.
 *
 * Render inside a `SettingRows`.
 */
export default function ContextLimitRows({
  contextLimit,
  historyLimit,
  window,
  disabled = false,
  onContextLimitChange,
  onHistoryLimitChange,
}: ContextLimitRowsProps) {
  const { t } = useTranslation();
  const contextSwitchId = useId();
  const historySwitchId = useId();

  const contextOn = contextLimit !== null && contextLimit !== undefined;
  const historyOn = historyLimit !== null && historyLimit !== undefined;
  const contextMax = contextLimitMax(window);
  const historyMax = historyLimitMax(contextLimit, window);
  const contextUsable =
    contextOn && !isContextLimitInvalid(contextLimit, window);

  const contextError = window
    ? t('agents.form.advanced.contextLimitRange', {
        min: MIN_CONTEXT_WINDOW_LIMIT,
        max: contextMax,
        model: window.name,
      })
    : t('agents.form.advanced.limitMin', {
        min: MIN_CONTEXT_WINDOW_LIMIT,
      });
  const historyError = contextUsable
    ? t('agents.form.advanced.historyLimitBelowContext', {
        min: MIN_HISTORY_TOKEN_LIMIT,
        limit: contextLimit,
      })
    : window
      ? t('agents.form.advanced.historyLimitBelowWindow', {
          min: MIN_HISTORY_TOKEN_LIMIT,
          limit: window.tokens,
          model: window.name,
        })
      : t('agents.form.advanced.limitMin', {
          min: MIN_HISTORY_TOKEN_LIMIT,
        });

  return (
    <>
      <SettingRow
        label={t('agents.form.advanced.contextLimit')}
        description={t('agents.form.advanced.contextLimitDescription')}
        htmlFor={contextSwitchId}
        after={
          <LimitInput
            value={contextLimit}
            on={contextOn}
            invalid={isContextLimitInvalid(contextLimit, window)}
            error={contextError}
            min={MIN_CONTEXT_WINDOW_LIMIT}
            max={contextMax}
            disabled={disabled}
            label={t('agents.form.advanced.contextLimitTokens')}
            placeholder={t('agents.form.placeholders.contextLimitDefault')}
            onChange={onContextLimitChange}
          />
        }
      >
        <Switch
          id={contextSwitchId}
          checked={contextOn}
          // A cost control, so policy (`edit_policy`) like the usage limits.
          disabled={disabled}
          onCheckedChange={(checked) =>
            onContextLimitChange(
              checked
                ? Math.min(DEFAULT_CONTEXT_WINDOW_LIMIT, contextMax)
                : null,
            )
          }
        />
      </SettingRow>
      <SettingRow
        label={t('agents.form.advanced.historyLimit')}
        description={t('agents.form.advanced.historyLimitDescription')}
        htmlFor={historySwitchId}
        after={
          <LimitInput
            value={historyLimit}
            on={historyOn}
            invalid={isHistoryLimitInvalid(historyLimit, contextLimit, window)}
            error={historyError}
            min={MIN_HISTORY_TOKEN_LIMIT}
            max={historyMax}
            disabled={disabled}
            label={t('agents.form.advanced.historyLimitTokens')}
            placeholder={t('agents.form.placeholders.historyLimitDefault')}
            onChange={onHistoryLimitChange}
          />
        }
      >
        <Switch
          id={historySwitchId}
          checked={historyOn}
          disabled={disabled}
          onCheckedChange={(checked) =>
            onHistoryLimitChange(
              checked
                ? Math.min(DEFAULT_HISTORY_TOKEN_LIMIT, historyMax)
                : null,
            )
          }
        />
      </SettingRow>
    </>
  );
}
