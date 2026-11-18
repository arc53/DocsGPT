import { TriangleAlert } from 'lucide-react';
import { useId } from 'react';
import { useTranslation } from 'react-i18next';

import { Input } from '@/components/ui/input';
import { SettingRow } from '@/components/ui/setting-row';
import { Switch } from '@/components/ui/switch';

import {
  MAX_CONTEXT_WINDOW_LIMIT,
  MIN_CONTEXT_WINDOW_LIMIT,
  MIN_HISTORY_TOKEN_LIMIT,
  type ModelWindow,
  contextLimitAboveWindow,
  defaultContextLimit,
  defaultHistoryLimit,
  historyLimitAboveWindow,
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

/** The text field under a limit's switch, with its range error or its no-effect note. */
function LimitInput({
  value,
  on,
  invalid,
  error,
  note,
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
  /** Shown when the value is valid but has no effect; null for none. */
  note: string | null;
  min: number;
  max: number;
  disabled: boolean;
  label: string;
  placeholder: string;
  onChange: (limit: number) => void;
}) {
  const errorId = useId();
  const noteId = useId();
  const shownNote = !invalid && on ? note : null;
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
        aria-describedby={invalid ? errorId : shownNote ? noteId : undefined}
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
      ) : shownNote ? (
        <p
          id={noteId}
          className="text-muted-foreground mt-1.5 flex items-start gap-1.5 text-xs"
        >
          <TriangleAlert
            className="text-warning mt-px size-3.5 shrink-0"
            aria-hidden
          />
          {shownNote}
        </p>
      ) : null}
    </>
  );
}

/**
 * The Context limit and History limit rows of an agent's Advanced settings,
 * each a Switch with its token field under it, like the usage limits. Off
 * saves null: the model's whole window, and summarizing only near it. The
 * history limit is held below the context limit; a limit past the window of
 * the agent's models is noted, not refused, since it is valid but has no
 * effect.
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
  const contextUsable = contextOn && !isContextLimitInvalid(contextLimit);
  const historyMax = historyLimitMax(contextLimit);

  const contextError = t('agents.form.advanced.limitRange', {
    min: MIN_CONTEXT_WINDOW_LIMIT,
    max: MAX_CONTEXT_WINDOW_LIMIT,
  });
  const historyError = contextUsable
    ? t('agents.form.advanced.historyLimitBelowContext', {
        min: MIN_HISTORY_TOKEN_LIMIT,
        limit: contextLimit,
      })
    : t('agents.form.advanced.limitRange', {
        min: MIN_HISTORY_TOKEN_LIMIT,
        max: MAX_CONTEXT_WINDOW_LIMIT,
      });
  const contextNote =
    window && contextLimitAboveWindow(contextLimit, window)
      ? t('agents.form.advanced.contextLimitAboveWindow', {
          model: window.name,
          limit: window.tokens,
        })
      : null;
  const historyNote =
    window && historyLimitAboveWindow(historyLimit, window)
      ? t('agents.form.advanced.historyLimitAboveWindow', {
          model: window.name,
          limit: window.tokens,
        })
      : null;

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
            invalid={isContextLimitInvalid(contextLimit)}
            error={contextError}
            note={contextNote}
            min={MIN_CONTEXT_WINDOW_LIMIT}
            max={MAX_CONTEXT_WINDOW_LIMIT}
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
            onContextLimitChange(checked ? defaultContextLimit(window) : null)
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
            invalid={isHistoryLimitInvalid(historyLimit, contextLimit)}
            error={historyError}
            note={historyNote}
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
              checked ? defaultHistoryLimit(contextLimit, window) : null,
            )
          }
        />
      </SettingRow>
    </>
  );
}
