import React from 'react';
import { ChevronRight, Info, Lock, TriangleAlert } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import { Alert, AlertDescription } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { EmptyState } from '@/components/ui/empty-state';
import { FormField } from '@/components/ui/form-field';
import { Input } from '@/components/ui/input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { SectionHeader } from '@/components/ui/section-header';
import { SettingRow } from '@/components/ui/setting-row';
import { Switch } from '@/components/ui/switch';
import { Textarea } from '@/components/ui/textarea';
import { cn } from '@/lib/utils';

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
 *
 * Deliberately ignores `config.enabled`: the backend validates every control
 * whether or not guardrails are switched on, so gating on `enabled` here let
 * an incomplete control through the moment the user toggled guardrails off.
 */
export function guardrailsIncomplete(config?: GuardrailsConfig): boolean {
  if (!config) return false;
  return (config.controls ?? []).some(controlNeedsSetup);
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
  /** Why the controls are read-only, shown in place of a silent lockout. */
  disabledNotice?: string;
};

export default function GuardrailsSection({
  value,
  onChange,
  token,
  disabled = false,
  disabledNotice,
}: Props) {
  const { t } = useTranslation();
  const [expanded, setExpanded] = React.useState(false);
  const [catalog, setCatalog] = React.useState<GuardrailCatalog | null>(null);
  const [loadError, setLoadError] = React.useState<string | null>(null);
  const [openSettings, setOpenSettings] = React.useState<string | null>(null);
  // Bumped by Retry to re-run the catalog fetch below.
  const [reloadKey, setReloadKey] = React.useState(0);
  const enabledId = React.useId();
  const failOpenId = React.useId();

  const config = value ?? DEFAULT_GUARDRAILS;

  React.useEffect(() => {
    let cancelled = false;
    setLoadError(null);
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
  }, [token, t, reloadKey]);

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
      className="bg-card has-[[data-variant=section-toggle]:focus-visible]:ring-ring/50 rounded-2xl px-6 py-3 has-[[data-variant=section-toggle]:focus-visible]:ring-3 has-[[data-variant=section-toggle]:focus-visible]:ring-inset"
      data-testid="guardrails-section"
    >
      <div className="flex flex-wrap items-center gap-2">
        {/* The heading wraps the toggle: a button's children are
            presentational, so a heading inside it is lost to screen readers. */}
        <h2>
          <Button
            type="button"
            variant="section-toggle"
            size="sm"
            onClick={() => setExpanded(!expanded)}
            aria-expanded={expanded}
            className="-ml-3 w-fit justify-start"
            data-testid="guardrails-toggle"
          >
            <ChevronRight
              aria-hidden="true"
              className={cn(
                'transition-transform duration-200',
                expanded && 'rotate-90',
              )}
            />
            <span className="text-lg font-semibold">
              {t('agents.form.sections.guardrails')}
            </span>
          </Button>
        </h2>
        {config.enabled && (
          <Badge variant="success" data-testid="guardrails-active-badge">
            {t('agents.form.guardrails.activeCount', {
              count: config.controls.length + floorControls.size,
            })}
          </Badge>
        )}
        {incompleteCount > 0 && (
          <Badge
            variant="destructive"
            data-testid="guardrails-incomplete-badge"
          >
            {t('agents.form.guardrails.needsSetup', {
              count: incompleteCount,
            })}
          </Badge>
        )}
      </div>

      {expanded && (
        <div className="mt-3 pb-3">
          {loadError && (
            <EmptyState
              tone="destructive"
              size="sm"
              illustration="none"
              title={loadError}
              action={
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => setReloadKey((k) => k + 1)}
                >
                  {t('retry')}
                </Button>
              }
            />
          )}

          {disabled && disabledNotice && (
            <Alert
              role="status"
              className="mt-3"
              data-testid="guardrails-read-only"
            >
              <Lock aria-hidden="true" className="size-4" />
              <AlertDescription>{disabledNotice}</AlertDescription>
            </Alert>
          )}

          {instanceDisabled && (
            <Alert
              variant="warning"
              className="mt-3"
              data-testid="guardrails-instance-disabled"
            >
              <TriangleAlert aria-hidden="true" className="size-4" />
              <AlertDescription>
                {t('agents.form.guardrails.instanceDisabled')}
              </AlertDescription>
            </Alert>
          )}

          {floorControls.size > 0 && (
            <Alert variant="info" role="status" className="mt-3">
              <Info aria-hidden="true" className="size-4" />
              <AlertDescription>
                {t('agents.form.guardrails.floorNotice', {
                  count: floorControls.size,
                })}
              </AlertDescription>
            </Alert>
          )}

          <SettingRow
            className="mt-4"
            label={t('agents.form.guardrails.enable')}
            description={t('agents.form.guardrails.enableDescription')}
            htmlFor={enabledId}
          >
            <Switch
              id={enabledId}
              checked={config.enabled}
              disabled={disabled}
              data-testid="guardrails-enabled"
              onCheckedChange={(checked) => patch({ enabled: checked })}
            />
          </SettingRow>

          {config.enabled && (
            <>
              <div className="mt-5">
                <FormField
                  label={t('agents.form.guardrails.mode')}
                  hint={
                    config.mode === 'monitor_only'
                      ? t('agents.form.guardrails.monitorHint')
                      : undefined
                  }
                  disabled={disabled}
                >
                  <Select
                    value={config.mode}
                    onValueChange={(mode) =>
                      patch({ mode: mode as GuardrailsConfig['mode'] })
                    }
                    disabled={disabled}
                  >
                    <SelectTrigger
                      className="w-full"
                      size="field"
                      shape="pill"
                      data-testid="guardrails-mode"
                    >
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {(catalog?.modes ?? Object.keys(MODE_KEYS)).map(
                        (mode) => (
                          <SelectItem key={mode} value={mode}>
                            {t(MODE_KEYS[mode] ?? mode)}
                          </SelectItem>
                        ),
                      )}
                    </SelectContent>
                  </Select>
                </FormField>
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
                    <Card
                      key={key(control.check, control.stage)}
                      tone="destructive"
                      padding="sm"
                      className="flex-row items-center justify-between"
                      data-testid={`guardrail-orphan-${control.check}`}
                    >
                      <p className="text-xs">
                        {t('agents.form.guardrails.unknownCheck', {
                          check: control.check,
                        })}
                      </p>
                      <Button
                        type="button"
                        variant="ghost-destructive-on-accent"
                        size="xs"
                        disabled={disabled}
                        onClick={() =>
                          removeControl(control.check, control.stage)
                        }
                      >
                        {t('agents.form.guardrails.remove')}
                      </Button>
                    </Card>
                  ))}
                </div>
              </div>

              <FormField
                className="mt-6"
                label={t('agents.form.guardrails.blockMessage')}
                hint={t('agents.form.guardrails.blockMessageDescription')}
                disabled={disabled}
              >
                <Input
                  type="text"
                  value={config.block_message}
                  maxLength={500}
                  data-testid="guardrails-block-message"
                  onChange={(e) => patch({ block_message: e.target.value })}
                  shape="pill"
                />
              </FormField>

              <SettingRow
                className="mt-6"
                label={t('agents.form.guardrails.failOpen')}
                description={t('agents.form.guardrails.failOpenDescription')}
                htmlFor={failOpenId}
              >
                <Switch
                  id={failOpenId}
                  checked={config.fail_open}
                  disabled={disabled}
                  data-testid="guardrails-fail-open"
                  onCheckedChange={(checked) => patch({ fail_open: checked })}
                />
              </SettingRow>

              <FormField
                className="mt-5"
                label={t('agents.form.guardrails.timeout')}
                disabled={disabled}
              >
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
              </FormField>
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
      variant="filled"
      shape="pill"
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
    <Card padding="sm" data-testid={`guardrail-check-${info.name}`}>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <SectionHeader as="h4" size="xs" title={info.label} />
          <Badge
            variant="neutral"
            title={t('agents.form.guardrails.latencyHint')}
            data-testid={`guardrail-latency-${info.name}`}
          >
            {latencyLabel(info.latency_hint_ms)}
          </Badge>
          {unavailable && (
            <Badge variant="warning">
              {t('agents.form.guardrails.notConfigured')}
            </Badge>
          )}
        </div>
        <p className="text-muted-foreground mt-1 text-xs">{info.description}</p>
      </div>

      <div className="flex flex-wrap gap-2">
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
          const chip = (
            <Button
              key={stage}
              type="button"
              variant={on ? 'secondary' : 'ghost-muted'}
              size="xs"
              shape="pill"
              disabled={!canToggle}
              data-testid={`guardrail-stage-${info.name}-${stage}`}
              onClick={() => toggleControl(info, stage, !control)}
            >
              {t(STAGE_KEYS[stage] ?? stage)}
              {locked ? ' 🔒' : ''}
            </Button>
          );
          // A disabled Button takes no pointer events, so the locked chip's
          // hint lives on a wrapper that can still be hovered.
          return locked ? (
            <span
              key={stage}
              className="inline-flex"
              title={t('agents.form.guardrails.lockedByFloor')}
            >
              {chip}
            </span>
          ) : (
            chip
          );
        })}
      </div>

      {floorForCheck.map(([k, action]) => (
        <Alert
          key={`floor-${k}`}
          variant="info"
          role="note"
          data-testid={`guardrail-floor-${k}`}
        >
          <Info aria-hidden="true" className="size-4" />
          <AlertDescription>
            {t('agents.form.guardrails.floorControl', {
              stage: t(STAGE_KEYS[k.split(':')[1] as GuardrailStage] ?? ''),
              action: t(ACTION_KEYS[action] ?? action),
            })}
          </AlertDescription>
        </Alert>
      ))}

      {active.map((control) => {
        const needsSetup = controlNeedsSetup(control);
        const panelKey = key(control.check, control.stage);
        return (
          <div
            key={panelKey}
            className={cn(
              'rounded-lg px-3 py-2',
              needsSetup
                ? 'border-destructive/50 bg-destructive/10 border'
                : 'bg-muted',
            )}
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
                    size="sm"
                    shape="pill"
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
                    size="xs"
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
                  variant="ghost-destructive"
                  size="xs"
                  disabled={disabled}
                  data-testid={`guardrail-remove-${control.check}-${control.stage}`}
                  onClick={() => removeControl(control.check, control.stage)}
                >
                  {t('agents.form.guardrails.remove')}
                </Button>
              </div>
            </div>
            {needsSetup && (
              <p
                role="alert"
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
    </Card>
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
    <FormField label={label} labelSurface="muted" disabled={disabled}>
      <Textarea
        rows={2}
        size="sm"
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
        variant="filled"
      />
    </FormField>
  );

  return (
    <div className="border-border mt-3 flex flex-col gap-5 border-t pt-5">
      {control.check === 'pii' && (
        <div className="flex flex-wrap gap-2">
          {(catalog?.pii_entities ?? []).map((entity) => {
            const on = (s.entities ?? []).includes(entity);
            return (
              <Button
                key={entity}
                type="button"
                variant={on ? 'secondary' : 'ghost-muted'}
                size="xs"
                shape="pill"
                disabled={disabled}
                data-testid={`guardrail-pii-${entity}`}
                onClick={() =>
                  set({
                    entities: on
                      ? (s.entities ?? []).filter((e: string) => e !== entity)
                      : [...(s.entities ?? []), entity],
                  })
                }
              >
                {entity}
              </Button>
            );
          })}
          {(s.entities ?? []).length === 0 && (
            <p role="alert" className="text-destructive text-xs">
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
        <FormField
          label={t('agents.form.guardrails.policyText')}
          labelSurface="muted"
          disabled={disabled}
        >
          <Textarea
            rows={4}
            size="sm"
            value={s.policy ?? ''}
            data-testid="guardrail-policy-text"
            onChange={(e) => set({ policy: e.target.value })}
            variant="filled"
          />
        </FormField>
      )}

      {control.check === 'groundedness' && (
        <div className="grid grid-cols-2 gap-2">
          <FormField
            label={t('agents.form.guardrails.minOverlap')}
            labelSurface="muted"
            disabled={disabled}
          >
            <NumberField
              value={s.min_overlap ?? 0.3}
              min={0}
              max={1}
              step={0.1}
              fallback={0.3}
              disabled={disabled}
              onCommit={(min_overlap) => set({ min_overlap })}
            />
          </FormField>
          <FormField
            label={t('agents.form.guardrails.minWords')}
            labelSurface="muted"
            disabled={disabled}
          >
            <NumberField
              value={s.min_words ?? 25}
              min={1}
              max={1000}
              step={1}
              fallback={25}
              disabled={disabled}
              onCommit={(min_words) => set({ min_words })}
            />
          </FormField>
        </div>
      )}

      {control.check === 'policy' && (
        <FormField
          label={t('agents.form.guardrails.confidence')}
          hint={t('agents.form.guardrails.confidenceHint')}
          labelSurface="muted"
          disabled={disabled}
        >
          <NumberField
            value={s.confidence_threshold ?? 0.7}
            min={0}
            max={1}
            step={0.1}
            fallback={0.7}
            disabled={disabled}
            onCommit={(confidence_threshold) => set({ confidence_threshold })}
          />
        </FormField>
      )}
    </div>
  );
}
