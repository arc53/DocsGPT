import React from 'react';
import { useTranslation } from 'react-i18next';

import ViewOnlyNotice from '@/components/ViewOnlyNotice';
import { cn } from '@/lib/utils';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Collapsible, CollapsibleTrigger } from '@/components/ui/collapsible';
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
import { ToggleChip } from '@/components/ui/toggle-chip';

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

export const STAGE_KEYS: Record<GuardrailStage, string> = {
  input: 'agents.form.guardrails.stages.input',
  retrieval: 'agents.form.guardrails.stages.retrieval',
  tool_result: 'agents.form.guardrails.stages.toolResult',
  attachment: 'agents.form.guardrails.stages.attachment',
  output: 'agents.form.guardrails.stages.output',
};

/** The order stage chips read in: the turn's own order, not the catalog's alphabetical one. */
const STAGE_ORDER: GuardrailStage[] = [
  'input',
  'retrieval',
  'tool_result',
  'attachment',
  'output',
];

/**
 * Stages whose text is a list of items (retrieved documents, attached files):
 * an item-level check scores each one, so `block` withholds that item alone.
 */
const ITEM_STAGES = new Set<GuardrailStage>(['retrieval', 'attachment']);

export const ACTION_KEYS: Record<GuardrailAction, string> = {
  flag: 'agents.form.guardrails.actions.flag',
  redact: 'agents.form.guardrails.actions.redact',
  block: 'agents.form.guardrails.actions.block',
};

const MODE_KEYS: Record<string, string> = {
  monitor_only: 'agents.form.guardrails.modes.monitorOnly',
  scan_all: 'agents.form.guardrails.modes.scanAll',
};

/** Checks the operator switches on as a whole (the decision model): not offered while off. */
const HIDDEN_WHILE_UNAVAILABLE = new Set(['injection_model']);

/** The prompt-injection model's thresholds a new control starts with. */
const INJECTION_THRESHOLD = 0.9;
const INJECTION_FLAG_THRESHOLD = 0.5;

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

/**
 * The guardrail catalog (GET /api/guardrails/catalog): the checks, stages
 * and actions this instance offers, and the controls its floor claims.
 * `retry` fetches it again after a failure.
 */
export function useGuardrailCatalog(token: string | null) {
  const { t } = useTranslation();
  const [catalog, setCatalog] = React.useState<GuardrailCatalog | null>(null);
  const [loadError, setLoadError] = React.useState<string | null>(null);
  // Bumped by Retry to re-run the fetch below.
  const [reloadKey, setReloadKey] = React.useState(0);

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

  const retry = React.useCallback(() => setReloadKey((k) => k + 1), []);
  return { catalog, loadError, retry };
}

/** Floor-imposed controls by `check:stage`, so the UI can show them as active and locked. */
function floorControlsOf(
  catalog: GuardrailCatalog | null,
): Map<string, GuardrailAction> {
  const map = new Map<string, GuardrailAction>();
  catalog?.floor?.controls?.forEach((c) =>
    map.set(key(c.check, c.stage), c.action),
  );
  return map;
}

type Props = {
  value?: GuardrailsConfig;
  onChange: (next: GuardrailsConfig) => void;
  token: string | null;
  /**
   * The caller's role can't change the policy: the controls still show its
   * state, disabled, under the shared view-only notice.
   */
  disabled?: boolean;
};

/** The agent form's Guardrails panel: a section toggle over `GuardrailsEditor`. */
export default function GuardrailsSection({
  value,
  onChange,
  token,
  disabled = false,
}: Props) {
  const { t } = useTranslation();
  const [expanded, setExpanded] = React.useState(false);
  const bodyId = React.useId();
  const { catalog, loadError, retry } = useGuardrailCatalog(token);

  const config = value ?? DEFAULT_GUARDRAILS;
  const floorCount = floorControlsOf(catalog).size;
  const incompleteCount = config.controls.filter(controlNeedsSetup).length;

  return (
    <Card
      variant="subtle"
      padding="lg"
      className="gap-5"
      data-testid="guardrails-section"
    >
      {/* The card's gap-5 sits inside the body, so it folds away with it. */}
      <div>
        <div className="flex flex-wrap items-center gap-2">
          {/* The heading wraps the toggle: a button's children are
            presentational, so a heading inside it is lost to screen readers. */}
          <h2>
            <CollapsibleTrigger
              look="section"
              open={expanded}
              onOpenChange={setExpanded}
              controls={bodyId}
              data-testid="guardrails-toggle"
            >
              {t('agents.form.sections.guardrails')}
            </CollapsibleTrigger>
          </h2>
          {config.enabled && (
            <Badge variant="success" data-testid="guardrails-active-badge">
              {t('agents.form.guardrails.activeCount', {
                count: config.controls.length + floorCount,
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

        <Collapsible open={expanded} id={bodyId}>
          <GuardrailsEditor
            className="pt-5"
            value={value}
            onChange={onChange}
            catalog={catalog}
            loadError={loadError}
            onRetry={retry}
            disabled={disabled}
          />
        </Collapsible>
      </div>
    </Card>
  );
}

type EditorProps = {
  value?: GuardrailsConfig;
  onChange: (next: GuardrailsConfig) => void;
  /** From `useGuardrailCatalog`; null while it loads. */
  catalog: GuardrailCatalog | null;
  loadError?: string | null;
  onRetry?: () => void;
  disabled?: boolean;
  /**
   * Whether the instance floor's controls show as locked. Off where the floor
   * itself is edited (Admin › Guardrails).
   */
  showFloor?: boolean;
  /** The on/off row's title and description, where the config is not one agent's. */
  enableLabel?: string;
  enableDescription?: string;
  /** Layout only. */
  className?: string;
};

/**
 * A guardrails config's controls: the on/off switch, the mode, a card per
 * check with its stages, actions and settings, the block message, fail-open
 * and the timeout. The agent form wraps it in its Guardrails panel; Admin ›
 * Guardrails (the floor) and Admin › Defaults (new agents) use it as it is.
 * Fields sit on the page background (`labelSurface="background"`).
 */
export function GuardrailsEditor({
  value,
  onChange,
  catalog,
  loadError = null,
  onRetry,
  disabled = false,
  showFloor = true,
  enableLabel,
  enableDescription,
  className,
}: EditorProps) {
  const { t } = useTranslation();
  const [openSettings, setOpenSettings] = React.useState<string | null>(null);
  const enabledId = React.useId();
  const failOpenId = React.useId();

  const config = value ?? DEFAULT_GUARDRAILS;

  const floorControls = React.useMemo(
    () => (showFloor ? floorControlsOf(catalog) : new Map()),
    [catalog, showFloor],
  );

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

  const used = new Set([
    ...config.controls.map((c) => c.check),
    ...Array.from(floorControls.keys()).map((k) => k.split(':')[0]),
  ]);
  // The decision model's check while the operator has the model off is left
  // out, unless a control already uses it: that one stays so it can be
  // removed. Other unavailable checks show, marked, since their setup is the
  // instance's configuration.
  const checks = (catalog?.checks ?? []).filter(
    (info) =>
      info.available ||
      !HIDDEN_WHILE_UNAVAILABLE.has(info.name) ||
      used.has(info.name),
  );
  const knownChecks = new Set((catalog?.checks ?? []).map((c) => c.name));
  // A control whose check is missing from the catalog would otherwise be
  // invisible here while still being submitted.
  const orphanControls = catalog
    ? config.controls.filter((c) => !knownChecks.has(c.check))
    : [];
  const instanceDisabled = catalog !== null && catalog.enabled === false;

  return (
    <div className={cn('flex flex-col gap-5', className)}>
      {loadError && (
        <EmptyState
          tone="destructive"
          size="sm"
          illustration="none"
          title={loadError}
          onRetry={onRetry}
        />
      )}

      {disabled && <ViewOnlyNotice data-testid="guardrails-read-only" />}

      {instanceDisabled && (
        <Alert variant="warning" data-testid="guardrails-instance-disabled">
          <AlertDescription>
            {t('agents.form.guardrails.instanceDisabled')}
          </AlertDescription>
        </Alert>
      )}

      {floorControls.size > 0 && (
        <Alert variant="info" role="status">
          <AlertDescription>
            {t('agents.form.guardrails.floorNotice', {
              count: floorControls.size,
            })}
          </AlertDescription>
        </Alert>
      )}

      <SettingRow
        label={enableLabel ?? t('agents.form.guardrails.enable')}
        description={
          enableDescription ?? t('agents.form.guardrails.enableDescription')
        }
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
          <FormField
            labelSurface="background"
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
          </FormField>

          <div>
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
                    onClick={() => removeControl(control.check, control.stage)}
                  >
                    {t('agents.form.guardrails.remove')}
                  </Button>
                </Card>
              ))}
            </div>
          </div>

          <FormField
            labelSurface="background"
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
            />
          </FormField>

          <SettingRow
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
            labelSurface="background"
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
  variant = 'filled',
  onCommit,
}: {
  value: number;
  min: number;
  max: number;
  step: number;
  fallback: number;
  disabled?: boolean;
  testId?: string;
  /** `default` inside a guardrail stage panel (transparent, on the page). */
  variant?: 'default' | 'filled';
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
      variant={variant}
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
    case 'injection_model':
      return {
        threshold: INJECTION_THRESHOLD,
        flag_threshold: INJECTION_FLAG_THRESHOLD,
      };
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
    <Card
      variant="subtle"
      padding="sm"
      data-testid={`guardrail-check-${info.name}`}
    >
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
        {orderedStages(info.stages).map((stage) => {
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
          // A locked chip is aria-disabled, not disabled, so it keeps full
          // colour and its hint shows on hover.
          return (
            <ToggleChip
              key={stage}
              pressed={on}
              locked={locked}
              disabled={!locked && !canToggle}
              title={
                locked ? t('agents.form.guardrails.lockedByFloor') : undefined
              }
              data-testid={`guardrail-stage-${info.name}-${stage}`}
              onPressedChange={() => toggleControl(info, stage, !control)}
            >
              {t(STAGE_KEYS[stage] ?? stage)}
            </ToggleChip>
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
        const perItem =
          Boolean(info.item_level) && ITEM_STAGES.has(control.stage);
        return (
          <Card
            key={panelKey}
            variant="subtle"
            padding="sm"
            tone={needsSetup ? 'destructive' : 'default'}
            className="gap-0"
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
            {perItem && (
              <p
                className="text-muted-foreground mt-1 text-xs"
                data-testid={`guardrail-item-level-${control.check}-${control.stage}`}
              >
                {t('agents.form.guardrails.itemLevelHint')}
              </p>
            )}
            {control.check === 'injection_model' && (
              <InjectionThresholds
                control={control}
                disabled={disabled}
                onChange={(settings) =>
                  updateControl(control.check, control.stage, { settings })
                }
              />
            )}
            {openSettings === panelKey && (
              <CheckSettings
                control={control}
                onTint={needsSetup}
                catalog={catalog}
                disabled={disabled}
                onChange={(settings) =>
                  updateControl(control.check, control.stage, { settings })
                }
              />
            )}
          </Card>
        );
      })}
    </Card>
  );
}

/** `stages` in the turn's order (`STAGE_ORDER`), unknown ones last. */
function orderedStages(stages: GuardrailStage[]): GuardrailStage[] {
  const rank = (stage: GuardrailStage) => {
    const at = STAGE_ORDER.indexOf(stage);
    return at === -1 ? STAGE_ORDER.length : at;
  };
  return [...stages].sort((a, b) => rank(a) - rank(b));
}

/**
 * The prompt-injection model's two thresholds, under Advanced: from
 * `flag_threshold` a text is flagged and recorded, from `threshold` the
 * control's action applies. The flag threshold never passes the action one:
 * lowering the action threshold pulls it down with it.
 */
function InjectionThresholds({
  control,
  disabled,
  onChange,
}: {
  control: GuardrailControl;
  disabled: boolean;
  onChange: (settings: Record<string, any>) => void;
}) {
  const { t } = useTranslation();
  const [open, setOpen] = React.useState(false);
  const bodyId = React.useId();
  const s = control.settings ?? {};
  const threshold = Number(s.threshold ?? INJECTION_THRESHOLD);
  const flagThreshold = Math.min(
    threshold,
    Number(s.flag_threshold ?? INJECTION_FLAG_THRESHOLD),
  );
  const testId = `guardrail-thresholds-${control.check}-${control.stage}`;

  return (
    <div className="mt-2 flex flex-col">
      <CollapsibleTrigger
        open={open}
        onOpenChange={setOpen}
        controls={bodyId}
        chevron="sm"
        data-testid={`${testId}-toggle`}
      >
        {t('agents.form.guardrails.advanced')}
      </CollapsibleTrigger>
      <Collapsible open={open} id={bodyId}>
        <div className="grid grid-cols-1 gap-5 pt-3 sm:grid-cols-2">
          <FormField
            label={t('agents.form.guardrails.threshold')}
            hint={t('agents.form.guardrails.thresholdHint')}
            labelSurface="background"
            disabled={disabled}
          >
            <NumberField
              value={threshold}
              min={0}
              max={1}
              step={0.05}
              fallback={INJECTION_THRESHOLD}
              disabled={disabled}
              variant="default"
              testId={`${testId}-threshold`}
              onCommit={(next) =>
                onChange({
                  ...s,
                  threshold: next,
                  flag_threshold: Math.min(flagThreshold, next),
                })
              }
            />
          </FormField>
          <FormField
            label={t('agents.form.guardrails.flagThreshold')}
            hint={t('agents.form.guardrails.flagThresholdHint')}
            labelSurface="background"
            disabled={disabled}
          >
            <NumberField
              value={flagThreshold}
              min={0}
              max={threshold}
              step={0.05}
              fallback={Math.min(INJECTION_FLAG_THRESHOLD, threshold)}
              disabled={disabled}
              variant="default"
              testId={`${testId}-flag`}
              onCommit={(next) =>
                onChange({ ...s, threshold, flag_threshold: next })
              }
            />
          </FormField>
        </div>
      </Collapsible>
    </div>
  );
}

function hasSettings(check: string): boolean {
  return ['pii', 'denylist', 'url', 'policy', 'groundedness'].includes(check);
}

function CheckSettings({
  control,
  onTint,
  catalog,
  disabled,
  onChange,
}: {
  control: GuardrailControl;
  /**
   * On the needs-setup panel's red soft fill, which no label surface matches:
   * labels sit above the fields instead of floating on a notch.
   */
  onTint: boolean;
  catalog: GuardrailCatalog | null;
  disabled: boolean;
  onChange: (settings: Record<string, any>) => void;
}) {
  const { t } = useTranslation();
  const s = control.settings ?? {};
  const set = (next: Record<string, any>) => onChange({ ...s, ...next });

  const listField = (fieldKey: string, label: string, placeholder: string) => (
    <FormField
      label={label}
      labelSurface="background"
      float={!onTint}
      disabled={disabled}
    >
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
              <ToggleChip
                key={entity}
                pressed={on}
                disabled={disabled}
                data-testid={`guardrail-pii-${entity}`}
                onPressedChange={() =>
                  set({
                    entities: on
                      ? (s.entities ?? []).filter((e: string) => e !== entity)
                      : [...(s.entities ?? []), entity],
                  })
                }
              >
                {entity}
              </ToggleChip>
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
          labelSurface="background"
          float={!onTint}
          disabled={disabled}
        >
          <Textarea
            rows={4}
            size="sm"
            value={s.policy ?? ''}
            data-testid="guardrail-policy-text"
            onChange={(e) => set({ policy: e.target.value })}
          />
        </FormField>
      )}

      {control.check === 'groundedness' && (
        <div className="grid grid-cols-2 gap-2">
          <FormField
            label={t('agents.form.guardrails.minOverlap')}
            labelSurface="background"
            float={!onTint}
            disabled={disabled}
          >
            <NumberField
              value={s.min_overlap ?? 0.3}
              min={0}
              max={1}
              step={0.1}
              fallback={0.3}
              disabled={disabled}
              variant="default"
              onCommit={(min_overlap) => set({ min_overlap })}
            />
          </FormField>
          <FormField
            label={t('agents.form.guardrails.minWords')}
            labelSurface="background"
            float={!onTint}
            disabled={disabled}
          >
            <NumberField
              value={s.min_words ?? 25}
              min={1}
              max={1000}
              step={1}
              fallback={25}
              disabled={disabled}
              variant="default"
              onCommit={(min_words) => set({ min_words })}
            />
          </FormField>
        </div>
      )}

      {control.check === 'policy' && (
        <FormField
          label={t('agents.form.guardrails.confidence')}
          hint={t('agents.form.guardrails.confidenceHint')}
          labelSurface="background"
          float={!onTint}
          disabled={disabled}
        >
          <NumberField
            value={s.confidence_threshold ?? 0.7}
            min={0}
            max={1}
            step={0.1}
            fallback={0.7}
            disabled={disabled}
            variant="default"
            onCommit={(confidence_threshold) => set({ confidence_threshold })}
          />
        </FormField>
      )}
    </div>
  );
}
