import React from 'react';
import { useTranslation } from 'react-i18next';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Switch } from '@/components/ui/switch';

import userService from '../../api/services/userService';
import {
  GuardrailAction,
  GuardrailCatalog,
  GuardrailCheckInfo,
  GuardrailControl,
  GuardrailsConfig,
  GuardrailStage,
} from '../types';

export const DEFAULT_GUARDRAILS: GuardrailsConfig = {
  enabled: false,
  // Detect-first is the supported rollout path: turn checks on, watch what
  // they would have done, then promote to enforcement.
  mode: 'monitor_only',
  fail_open: true,
  timeout_ms: 2000,
  block_message: "Sorry, I can't help with that request.",
  controls: [],
};

const STAGE_KEYS: Record<GuardrailStage, string> = {
  input: 'agents.form.guardrails.stages.input',
  retrieval: 'agents.form.guardrails.stages.retrieval',
  tool_result: 'agents.form.guardrails.stages.toolResult',
  output: 'agents.form.guardrails.stages.output',
};

const ACTION_KEYS: Record<GuardrailAction, string> = {
  flag: 'agents.form.guardrails.actions.flag',
  redact: 'agents.form.guardrails.actions.redact',
  block: 'agents.form.guardrails.actions.block',
};

const MODE_KEYS: Record<string, string> = {
  monitor_only: 'agents.form.guardrails.modes.monitorOnly',
  scan_all: 'agents.form.guardrails.modes.scanAll',
};

/** Checks the backend rejects until their settings are filled in. */
const REQUIRES_SETUP: Record<string, (s: Record<string, any>) => boolean> = {
  denylist: (s) => !(s.terms ?? []).length,
  url: (s) => !(s.allow_hosts ?? []).length && !(s.block_hosts ?? []).length,
  policy: (s) => String(s.policy ?? '').trim().length < 10,
  pii: (s) => !(s.entities ?? []).length,
};

export function controlNeedsSetup(control: GuardrailControl): boolean {
  const test = REQUIRES_SETUP[control.check];
  return test ? test(control.settings ?? {}) : false;
}

/**
 * True when saving would 400. The form gates Save on this so a single click on
 * a stage chip can't leave the whole agent — name, model and all — unsavable
 * behind an error naming an array index.
 */
export function guardrailsIncomplete(config?: GuardrailsConfig): boolean {
  if (!config?.enabled) return false;
  return config.controls.some(controlNeedsSetup);
}

function latencyLabel(ms: number): string {
  if (ms < 1000) return `~${ms}ms`;
  return `~${(ms / 1000).toFixed(ms % 1000 === 0 ? 0 : 1)}s`;
}

function key(check: string, stage: string): string {
  return `${check}:${stage}`;
}

type Props = {
  value?: GuardrailsConfig;
  onChange: (next: GuardrailsConfig) => void;
  token: string | null;
  disabled?: boolean;
};

export default function GuardrailsSection({
  value,
  onChange,
  token,
  disabled = false,
}: Props) {
  const { t } = useTranslation();
  const [expanded, setExpanded] = React.useState(false);
  const [catalog, setCatalog] = React.useState<GuardrailCatalog | null>(null);
  const [loadError, setLoadError] = React.useState<string | null>(null);
  const [openSettings, setOpenSettings] = React.useState<string | null>(null);

  const config = value ?? DEFAULT_GUARDRAILS;

  React.useEffect(() => {
    let cancelled = false;
    userService
      .getGuardrailCatalog(token)
      .then((res) => res.json())
      .then((data) => {
        if (cancelled) return;
        if (data?.success) setCatalog(data as GuardrailCatalog);
        else setLoadError(t('agents.form.guardrails.loadError'));
      })
      .catch(() => {
        if (!cancelled) setLoadError(t('agents.form.guardrails.loadError'));
      });
    return () => {
      cancelled = true;
    };
  }, [token, t]);

  /** Floor-imposed controls, so the UI can show them as active and locked. */
  const floorControls = React.useMemo(() => {
    const map = new Map<string, GuardrailAction>();
    catalog?.floor?.controls?.forEach((c) =>
      map.set(key(c.check, c.stage), c.action),
    );
    return map;
  }, [catalog]);

  const patch = (next: Partial<GuardrailsConfig>) =>
    onChange({ ...config, ...next });

  const controlFor = (check: string, stage: GuardrailStage) =>
    config.controls.find((c) => c.check === check && c.stage === stage);

  const toggleControl = (
    info: GuardrailCheckInfo,
    stage: GuardrailStage,
    on: boolean,
  ) => {
    if (!on) {
      patch({
        controls: config.controls.filter(
          (c) => !(c.check === info.name && c.stage === stage),
        ),
      });
      return;
    }
    if (controlFor(info.name, stage)) return;
    const settings = defaultSettingsFor(info, catalog);
    patch({
      controls: [
        ...config.controls,
        { check: info.name, stage, action: 'flag', enabled: true, settings },
      ],
    });
    // Open the panel straight away for checks that can't save unconfigured,
    // rather than letting the user find out on Publish.
    if (REQUIRES_SETUP[info.name]?.(settings)) {
      setOpenSettings(key(info.name, stage));
    }
  };

  const updateControl = (
    check: string,
    stage: GuardrailStage,
    next: Partial<GuardrailControl>,
  ) =>
    patch({
      controls: config.controls.map((c) =>
        c.check === check && c.stage === stage ? { ...c, ...next } : c,
      ),
    });

  const removeControl = (check: string, stage: string) =>
    patch({
      controls: config.controls.filter(
        (c) => !(c.check === check && c.stage === stage),
      ),
    });

  const checks = catalog?.checks ?? [];
  const knownChecks = new Set(checks.map((c) => c.name));
  // A control whose check is missing from the catalog would otherwise be
  // invisible here while still being submitted.
  const orphanControls = config.controls.filter(
    (c) => !knownChecks.has(c.check),
  );
  const incompleteCount = config.controls.filter(controlNeedsSetup).length;
  const instanceDisabled = catalog !== null && catalog.enabled === false;

  return (
    <div
      className="bg-card rounded-2xl px-6 py-3"
      data-testid="guardrails-section"
    >
      <Button
        type="button"
        variant="ghost"
        onClick={() => setExpanded(!expanded)}
        className="h-auto w-full justify-between px-0 py-0 text-left hover:bg-transparent"
        data-testid="guardrails-toggle"
      >
        <div className="flex flex-wrap items-center gap-3">
          <h2 className="text-lg font-semibold">
            {t('agents.form.sections.guardrails')}
          </h2>
          {config.enabled && (
            <span
              className="rounded-full bg-emerald-100 px-2 py-0.5 text-xs font-medium text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300"
              data-testid="guardrails-active-badge"
            >
              {t('agents.form.guardrails.activeCount', {
                count: config.controls.length + floorControls.size,
              })}
            </span>
          )}
          {incompleteCount > 0 && (
            <span
              className="bg-destructive/10 text-destructive rounded-full px-2 py-0.5 text-xs font-medium"
              data-testid="guardrails-incomplete-badge"
            >
              {t('agents.form.guardrails.needsSetup', {
                count: incompleteCount,
              })}
            </span>
          )}
        </div>
        <div className="ml-4 flex items-center">
          <svg
            className={`size-5 transform transition-transform duration-200 ${
              expanded ? 'rotate-180' : ''
            }`}
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M19 9l-7 7-7-7"
            />
          </svg>
        </div>
      </Button>

      {expanded && (
        <div className="mt-3 pb-3">
          <p className="text-xs text-gray-600 dark:text-gray-400">
            {t('agents.form.guardrails.intro')}
          </p>

          {loadError && (
            <p className="text-destructive mt-3 text-xs">{loadError}</p>
          )}

          {instanceDisabled && (
            <p
              className="mt-3 rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-800 dark:bg-amber-900/30 dark:text-amber-300"
              data-testid="guardrails-instance-disabled"
            >
              {t('agents.form.guardrails.instanceDisabled')}
            </p>
          )}

          {floorControls.size > 0 && (
            <p className="mt-3 rounded-lg bg-blue-50 px-3 py-2 text-xs text-blue-800 dark:bg-blue-900/30 dark:text-blue-300">
              {t('agents.form.guardrails.floorNotice', {
                count: floorControls.size,
              })}
            </p>
          )}

          <div className="mt-4 flex items-center justify-between gap-4">
            <div className="min-w-0 flex-1">
              <h3 className="text-sm font-medium">
                {t('agents.form.guardrails.enable')}
              </h3>
              <p className="mt-1 text-xs text-gray-600 dark:text-gray-400">
                {t('agents.form.guardrails.enableDescription')}
              </p>
            </div>
            <Switch
              className="shrink-0"
              checked={config.enabled}
              disabled={disabled}
              data-testid="guardrails-enabled"
              onCheckedChange={(checked) => patch({ enabled: checked })}
            />
          </div>

          {config.enabled && (
            <>
              <div className="mt-5">
                <label className="mb-2 block text-sm font-medium">
                  {t('agents.form.guardrails.mode')}
                </label>
                <Select
                  value={config.mode}
                  onValueChange={(mode) =>
                    patch({ mode: mode as GuardrailsConfig['mode'] })
                  }
                  disabled={disabled}
                >
                  <SelectTrigger
                    className="w-full rounded-3xl px-5 py-3 text-sm"
                    size="lg"
                    data-testid="guardrails-mode"
                  >
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {(catalog?.modes ?? Object.keys(MODE_KEYS)).map((mode) => (
                      <SelectItem key={mode} value={mode}>
                        {t(MODE_KEYS[mode] ?? mode)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                {config.mode === 'monitor_only' && (
                  <p className="mt-2 text-xs text-amber-700 dark:text-amber-400">
                    {t('agents.form.guardrails.monitorHint')}
                  </p>
                )}
              </div>

              <div className="mt-5">
                <p className="mb-3 text-sm font-medium">
                  {t('agents.form.guardrails.checks')}
                </p>
                <div className="flex flex-col gap-3">
                  {checks.map((info) => (
                    <CheckCard
                      key={info.name}
                      info={info}
                      catalog={catalog}
                      config={config}
                      floorControls={floorControls}
                      disabled={disabled}
                      openSettings={openSettings}
                      setOpenSettings={setOpenSettings}
                      controlFor={controlFor}
                      toggleControl={toggleControl}
                      updateControl={updateControl}
                      removeControl={removeControl}
                    />
                  ))}
                  {orphanControls.map((control) => (
                    <div
                      key={key(control.check, control.stage)}
                      className="border-destructive/40 flex items-center justify-between gap-3 rounded-xl border px-4 py-3"
                      data-testid={`guardrail-orphan-${control.check}`}
                    >
                      <p className="text-xs">
                        {t('agents.form.guardrails.unknownCheck', {
                          check: control.check,
                        })}
                      </p>
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        disabled={disabled}
                        className="text-destructive h-auto px-2 py-1 text-xs"
                        onClick={() =>
                          removeControl(control.check, control.stage)
                        }
                      >
                        {t('agents.form.guardrails.remove')}
                      </Button>
                    </div>
                  ))}
                </div>
              </div>

              <div className="mt-6">
                <label className="mb-2 block text-sm font-medium">
                  {t('agents.form.guardrails.blockMessage')}
                </label>
                <Input
                  type="text"
                  value={config.block_message}
                  maxLength={500}
                  disabled={disabled}
                  data-testid="guardrails-block-message"
                  onChange={(e) => patch({ block_message: e.target.value })}
                  className="bg-card h-auto rounded-3xl px-5 py-3 text-sm md:text-sm"
                />
                <p className="mt-1 text-xs text-gray-600 dark:text-gray-400">
                  {t('agents.form.guardrails.blockMessageDescription')}
                </p>
              </div>

              <div className="mt-6 flex items-center justify-between gap-4">
                <div className="min-w-0 flex-1">
                  <h3 className="text-sm font-medium">
                    {t('agents.form.guardrails.failOpen')}
                  </h3>
                  <p className="mt-1 text-xs text-gray-600 dark:text-gray-400">
                    {t('agents.form.guardrails.failOpenDescription')}
                  </p>
                </div>
                <Switch
                  className="shrink-0"
                  checked={config.fail_open}
                  disabled={disabled}
                  data-testid="guardrails-fail-open"
                  onCheckedChange={(checked) => patch({ fail_open: checked })}
                />
              </div>

              <div className="mt-4">
                <label className="mb-2 block text-sm font-medium">
                  {t('agents.form.guardrails.timeout')}
                </label>
                <NumberField
                  value={config.timeout_ms}
                  min={100}
                  max={60000}
                  step={100}
                  fallback={2000}
                  disabled={disabled}
                  testId="guardrails-timeout"
                  onCommit={(timeout_ms) => patch({ timeout_ms })}
                />
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}

/**
 * Number input that stays clearable while typing and clamps on blur, so the
 * min/max are enforced rather than decorative.
 */
function NumberField({
  value,
  min,
  max,
  step,
  fallback,
  disabled,
  testId,
  onCommit,
}: {
  value: number;
  min: number;
  max: number;
  step: number;
  fallback: number;
  disabled?: boolean;
  testId?: string;
  onCommit: (next: number) => void;
}) {
  const [draft, setDraft] = React.useState(String(value));
  React.useEffect(() => setDraft(String(value)), [value]);

  return (
    <Input
      type="number"
      min={min}
      max={max}
      step={step}
      value={draft}
      disabled={disabled}
      data-testid={testId}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={() => {
        const parsed = Number(draft);
        const next =
          draft.trim() === '' || !Number.isFinite(parsed)
            ? fallback
            : Math.min(max, Math.max(min, parsed));
        setDraft(String(next));
        onCommit(next);
      }}
      className="bg-card h-auto rounded-3xl px-5 py-3 text-sm md:text-sm"
    />
  );
}

function defaultSettingsFor(
  info: GuardrailCheckInfo,
  catalog: GuardrailCatalog | null,
): Record<string, any> {
  switch (info.name) {
    case 'pii':
      return { entities: catalog?.default_pii_entities ?? ['EMAIL'] };
    case 'denylist':
      return { terms: [], match: 'word', case_sensitive: false };
    case 'url':
      return { allow_hosts: [], block_hosts: [] };
    case 'policy':
      return { policy: '', confidence_threshold: 0.7 };
    case 'groundedness':
      return { min_overlap: 0.3, min_words: 25, require_retrieval: true };
    default:
      return {};
  }
}

type CardProps = {
  info: GuardrailCheckInfo;
  catalog: GuardrailCatalog | null;
  config: GuardrailsConfig;
  floorControls: Map<string, GuardrailAction>;
  disabled: boolean;
  openSettings: string | null;
  setOpenSettings: (v: string | null) => void;
  controlFor: (
    check: string,
    stage: GuardrailStage,
  ) => GuardrailControl | undefined;
  toggleControl: (
    info: GuardrailCheckInfo,
    stage: GuardrailStage,
    on: boolean,
  ) => void;
  updateControl: (
    check: string,
    stage: GuardrailStage,
    next: Partial<GuardrailControl>,
  ) => void;
  removeControl: (check: string, stage: string) => void;
};

function CheckCard({
  info,
  catalog,
  config,
  floorControls,
  disabled,
  openSettings,
  setOpenSettings,
  controlFor,
  toggleControl,
  updateControl,
  removeControl,
}: CardProps) {
  const { t } = useTranslation();
  const active = config.controls.filter((c) => c.check === info.name);
  const unavailable = !info.available;
  const floorForCheck = Array.from(floorControls.entries()).filter(([k]) =>
    k.startsWith(`${info.name}:`),
  );

  return (
    <div
      className="rounded-xl border border-gray-200 px-4 py-3 dark:border-gray-700"
      data-testid={`guardrail-check-${info.name}`}
    >
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <h4 className="text-sm font-medium">{info.label}</h4>
          <span
            className="rounded-full bg-gray-100 px-2 py-0.5 text-[11px] font-medium text-gray-700 dark:bg-gray-800 dark:text-gray-300"
            title={t('agents.form.guardrails.latencyHint')}
            data-testid={`guardrail-latency-${info.name}`}
          >
            {latencyLabel(info.latency_hint_ms)}
          </span>
          {unavailable && (
            <span className="rounded-full bg-amber-100 px-2 py-0.5 text-[11px] font-medium text-amber-800 dark:bg-amber-900/40 dark:text-amber-300">
              {t('agents.form.guardrails.notConfigured')}
            </span>
          )}
        </div>
        <p className="mt-1 text-xs text-gray-600 dark:text-gray-400">
          {info.description}
        </p>
      </div>

      <div className="mt-3 flex flex-wrap gap-2">
        {info.stages.map((stage) => {
          const control = controlFor(info.name, stage);
          const floorAction = floorControls.get(key(info.name, stage));
          // A floor control is enforced at runtime whether or not the agent
          // declares it, so it must not render as an unselected chip.
          const on = Boolean(control) || Boolean(floorAction);
          const locked = Boolean(floorAction);
          // An unavailable check can still be *removed* — otherwise rotating
          // out a credential strands a control that can never be cleared.
          const canToggle =
            !disabled && !locked && (Boolean(control) || !unavailable);
          return (
            <button
              key={stage}
              type="button"
              disabled={!canToggle}
              data-testid={`guardrail-stage-${info.name}-${stage}`}
              onClick={() => toggleControl(info, stage, !control)}
              className={`rounded-full border px-3 py-1 text-xs transition-colors ${
                on
                  ? 'border-violets-are-blue bg-violets-are-blue/10 text-violets-are-blue'
                  : 'border-gray-300 text-gray-600 dark:border-gray-600 dark:text-gray-400'
              } ${!canToggle ? 'cursor-not-allowed opacity-60' : ''}`}
              title={
                locked ? t('agents.form.guardrails.lockedByFloor') : undefined
              }
            >
              {t(STAGE_KEYS[stage] ?? stage)}
              {locked ? ' 🔒' : ''}
            </button>
          );
        })}
      </div>

      {floorForCheck.map(([k, action]) => (
        <div
          key={`floor-${k}`}
          className="mt-3 rounded-lg bg-blue-50 px-3 py-2 text-xs text-blue-800 dark:bg-blue-900/30 dark:text-blue-300"
          data-testid={`guardrail-floor-${k}`}
        >
          {t('agents.form.guardrails.floorControl', {
            stage: t(STAGE_KEYS[k.split(':')[1] as GuardrailStage] ?? ''),
            action: t(ACTION_KEYS[action] ?? action),
          })}
        </div>
      ))}

      {active.map((control) => {
        const needsSetup = controlNeedsSetup(control);
        const panelKey = key(control.check, control.stage);
        return (
          <div
            key={panelKey}
            className={`mt-3 rounded-lg px-3 py-2 ${
              needsSetup
                ? 'border-destructive/50 bg-destructive/5 border'
                : 'bg-gray-50 dark:bg-gray-900/40'
            }`}
          >
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="text-xs font-medium">
                {t(STAGE_KEYS[control.stage] ?? control.stage)}
              </span>
              <div className="flex items-center gap-2">
                <Select
                  value={control.action}
                  disabled={disabled}
                  onValueChange={(action) =>
                    updateControl(control.check, control.stage, {
                      action: action as GuardrailAction,
                    })
                  }
                >
                  <SelectTrigger
                    className="h-auto rounded-full px-3 py-1 text-xs"
                    data-testid={`guardrail-action-${control.check}-${control.stage}`}
                  >
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {(catalog?.actions_by_stage?.[control.stage] ?? ['flag'])
                      .filter(
                        (action) =>
                          action !== 'redact' || info.supports_redaction,
                      )
                      .map((action) => (
                        <SelectItem key={action} value={action}>
                          {t(ACTION_KEYS[action] ?? action)}
                        </SelectItem>
                      ))}
                  </SelectContent>
                </Select>
                {hasSettings(info.name) && (
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    className="h-auto px-2 py-1 text-xs"
                    data-testid={`guardrail-configure-${control.check}-${control.stage}`}
                    onClick={() =>
                      setOpenSettings(
                        openSettings === panelKey ? null : panelKey,
                      )
                    }
                  >
                    {t('agents.form.guardrails.configure')}
                  </Button>
                )}
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  disabled={disabled}
                  className="text-destructive h-auto px-2 py-1 text-xs"
                  data-testid={`guardrail-remove-${control.check}-${control.stage}`}
                  onClick={() => removeControl(control.check, control.stage)}
                >
                  {t('agents.form.guardrails.remove')}
                </Button>
              </div>
            </div>
            {needsSetup && (
              <p
                className="text-destructive mt-1 text-xs"
                data-testid={`guardrail-needs-setup-${control.check}-${control.stage}`}
              >
                {t('agents.form.guardrails.setupRequired')}
              </p>
            )}
            {openSettings === panelKey && (
              <CheckSettings
                control={control}
                catalog={catalog}
                disabled={disabled}
                onChange={(settings) =>
                  updateControl(control.check, control.stage, { settings })
                }
              />
            )}
          </div>
        );
      })}
    </div>
  );
}

function hasSettings(check: string): boolean {
  return ['pii', 'denylist', 'url', 'policy', 'groundedness'].includes(check);
}

function CheckSettings({
  control,
  catalog,
  disabled,
  onChange,
}: {
  control: GuardrailControl;
  catalog: GuardrailCatalog | null;
  disabled: boolean;
  onChange: (settings: Record<string, any>) => void;
}) {
  const { t } = useTranslation();
  const s = control.settings ?? {};
  const set = (next: Record<string, any>) => onChange({ ...s, ...next });

  const listField = (fieldKey: string, label: string, placeholder: string) => (
    <div className="mt-2">
      <label className="mb-1 block text-xs font-medium">{label}</label>
      <textarea
        rows={2}
        disabled={disabled}
        data-testid={`guardrail-setting-${control.check}-${fieldKey}`}
        value={(s[fieldKey] ?? []).join('\n')}
        placeholder={placeholder}
        onChange={(e) =>
          set({
            [fieldKey]: e.target.value
              .split('\n')
              .map((v) => v.trim())
              .filter(Boolean),
          })
        }
        className="bg-card w-full rounded-xl border border-gray-200 px-3 py-2 text-xs dark:border-gray-700"
      />
    </div>
  );

  return (
    <div className="mt-3 border-t border-gray-200 pt-3 dark:border-gray-700">
      {control.check === 'pii' && (
        <div className="flex flex-wrap gap-2">
          {(catalog?.pii_entities ?? []).map((entity) => {
            const on = (s.entities ?? []).includes(entity);
            return (
              <button
                key={entity}
                type="button"
                disabled={disabled}
                data-testid={`guardrail-pii-${entity}`}
                onClick={() =>
                  set({
                    entities: on
                      ? (s.entities ?? []).filter((e: string) => e !== entity)
                      : [...(s.entities ?? []), entity],
                  })
                }
                className={`rounded-full border px-2 py-0.5 text-[11px] ${
                  on
                    ? 'border-violets-are-blue bg-violets-are-blue/10 text-violets-are-blue'
                    : 'border-gray-300 text-gray-600 dark:border-gray-600 dark:text-gray-400'
                }`}
              >
                {entity}
              </button>
            );
          })}
          {(s.entities ?? []).length === 0 && (
            <p className="text-destructive text-xs">
              {t('agents.form.guardrails.pickAtLeastOne')}
            </p>
          )}
        </div>
      )}

      {control.check === 'denylist' &&
        listField(
          'terms',
          t('agents.form.guardrails.terms'),
          t('agents.form.guardrails.termsPlaceholder'),
        )}

      {control.check === 'url' && (
        <>
          {listField(
            'allow_hosts',
            t('agents.form.guardrails.allowHosts'),
            'docs.example.com',
          )}
          {listField(
            'block_hosts',
            t('agents.form.guardrails.blockHosts'),
            'pastebin.com',
          )}
        </>
      )}

      {control.check === 'policy' && (
        <div className="mt-2">
          <label className="mb-1 block text-xs font-medium">
            {t('agents.form.guardrails.policyText')}
          </label>
          <textarea
            rows={4}
            value={s.policy ?? ''}
            disabled={disabled}
            data-testid="guardrail-policy-text"
            onChange={(e) => set({ policy: e.target.value })}
            className="bg-card w-full rounded-xl border border-gray-200 px-3 py-2 text-xs dark:border-gray-700"
          />
        </div>
      )}

      {control.check === 'groundedness' && (
        <div className="mt-2 grid grid-cols-2 gap-2">
          <div>
            <label className="mb-1 block text-xs font-medium">
              {t('agents.form.guardrails.minOverlap')}
            </label>
            <NumberField
              value={s.min_overlap ?? 0.3}
              min={0}
              max={1}
              step={0.1}
              fallback={0.3}
              disabled={disabled}
              onCommit={(min_overlap) => set({ min_overlap })}
            />
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium">
              {t('agents.form.guardrails.minWords')}
            </label>
            <NumberField
              value={s.min_words ?? 25}
              min={1}
              max={1000}
              step={1}
              fallback={25}
              disabled={disabled}
              onCommit={(min_words) => set({ min_words })}
            />
          </div>
        </div>
      )}

      {control.check === 'policy' && (
        <div className="mt-2">
          <label className="mb-1 block text-xs font-medium">
            {t('agents.form.guardrails.confidence')}
          </label>
          <NumberField
            value={s.confidence_threshold ?? 0.7}
            min={0}
            max={1}
            step={0.1}
            fallback={0.7}
            disabled={disabled}
            onCommit={(confidence_threshold) => set({ confidence_threshold })}
          />
          <p className="mt-1 text-[11px] text-gray-500">
            {t('agents.form.guardrails.confidenceHint')}
          </p>
        </div>
      )}
    </div>
  );
}
