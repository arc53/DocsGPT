import React from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';

import modelService from '../api/services/modelService';
import userService from '../api/services/userService';
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue,
} from '../components/ui/select';
import { Alert, AlertDescription } from '../components/ui/alert';
import { EmptyState } from '../components/ui/empty-state';
import { SectionHeader } from '../components/ui/section-header';
import { Skeleton } from '../components/ui/skeleton';
import { resetDrafterConfigCache } from '../drafter/useDrafterConfig';
import { SettingRow, SettingRows } from '../components/ui/setting-row';
import type { Model } from '../models/types';
import { showActionToast } from '../notifications/actionToastSlice';
import { selectToken } from '../preferences/preferenceSlice';

/** The Select value of "Use instance default": no pick of the user's own (saved as null). */
const INSTANCE_DEFAULT = '__instance__';
/**
 * A stored pick that can't run (a disabled or deleted model): the instance
 * default runs meanwhile, and the stored one again if it comes back. No
 * option shows it, so picking any one, Use instance default included,
 * replaces it.
 */
const UNAVAILABLE = '__unavailable__';

type Loaded = {
  /** The caller's pick, `UNAVAILABLE`, else `INSTANCE_DEFAULT`. */
  value: string;
  models: Model[];
  /** What runs without a pick: the admin's, TASK_MODEL_ID or the default model; null when none can. */
  instanceModelId: string | null;
  /**
   * The model whose provider refused its key on the user's last task
   * (`task_model_error`, code `model_auth`); null when none did.
   */
  refusedModelId: string | null;
};

/** The model a `task_model_error` names, when it is a refused key. */
const refusedModel = (error: unknown): string | null => {
  if (!error || typeof error !== 'object') return null;
  const { model_id: modelId, code } = error as {
    model_id?: unknown;
    code?: unknown;
  };
  return code === 'model_auth' && typeof modelId === 'string' && modelId
    ? modelId
    : null;
};

/**
 * Settings › General › Models: the task model, which runs DocsGPT's own jobs
 * (the drafter, graph extraction, monitor checks) for this user. "Use
 * instance default" (the first option, picked while the user has none)
 * follows whatever the admin sets; a named model is the user's own pick.
 * A stored pick that can no longer run shows no option and a note saying
 * the instance default runs; picking any option replaces it. A model whose
 * provider refused its key on the user's last task (`task_model_error`) is
 * marked "· key refused" in the list, still pickable since an admin can fix
 * the key, and while it is the one that runs a warning says so.
 * The trigger grows with its value up to 320px, then ends in "…".
 * Saved to the server on change, one save at a time: a pick made while one
 * is in flight waits, and only the latest such pick goes out. A failed save
 * puts the last saved pick back. A skeleton row stands in while it loads and
 * a load error with Retry when the fetch fails; a server from before the
 * task model hides the section.
 */
export default function TaskModelSection() {
  const { t } = useTranslation();
  const dispatch = useDispatch();
  const token = useSelector(selectToken);
  const id = React.useId();
  const [loaded, setLoaded] = React.useState<Loaded | null>(null);
  const [failed, setFailed] = React.useState(false);
  // An older server has no task model: the section stays hidden.
  const [unsupported, setUnsupported] = React.useState(false);
  const [attempt, setAttempt] = React.useState(0);
  // What the server holds, as a Select value.
  const savedValue = React.useRef(INSTANCE_DEFAULT);
  // One save at a time; the latest pick made meanwhile waits here.
  const saving = React.useRef(false);
  const queued = React.useRef<string | null>(null);

  React.useEffect(() => {
    let cancelled = false;
    Promise.all([
      userService.getPreferences(token),
      modelService.getModels(token),
    ])
      .then(async ([prefsRes, modelsRes]) => {
        if (!prefsRes?.ok || !modelsRes?.ok) throw new Error('load failed');
        const prefs = await prefsRes.json();
        const data = await modelsRes.json();
        if (cancelled) return;
        // A server from before the task model sends no such field.
        if (!prefs || !('instance_task_model_id' in prefs)) {
          setUnsupported(true);
          return;
        }
        const models = modelService.transformModels(data?.models || []);
        const picked =
          typeof prefs.task_model_id === 'string' &&
          models.some((m) => m.id === prefs.task_model_id)
            ? prefs.task_model_id
            : prefs.task_model_unavailable === true
              ? UNAVAILABLE
              : INSTANCE_DEFAULT;
        const instanceModelId =
          typeof prefs.instance_task_model_id === 'string' &&
          prefs.instance_task_model_id
            ? prefs.instance_task_model_id
            : null;
        savedValue.current = picked;
        setLoaded({
          value: picked,
          models,
          instanceModelId,
          refusedModelId: refusedModel(prefs.task_model_error),
        });
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, [token, attempt]);

  if (unsupported) return null;
  if (!loaded) {
    return (
      <section className="flex flex-col gap-4">
        <SectionHeader title={t('settings.general.sections.models')} />
        {failed ? (
          <EmptyState
            size="sm"
            tone="destructive"
            illustration="none"
            title={t('settings.general.taskModelLoadError')}
            onRetry={() => {
              setFailed(false);
              setAttempt((n) => n + 1);
            }}
          />
        ) : (
          <div aria-busy="true" className="flex flex-col gap-2">
            <Skeleton className="h-4 w-28" />
            <Skeleton className="h-3 w-72 max-w-full" />
            <Skeleton className="mt-1 h-9.5 w-full rounded-full sm:w-56" />
          </div>
        )}
      </section>
    );
  }

  const builtin = loaded.models.filter((m) => m.source !== 'user');
  const own = loaded.models.filter((m) => m.source === 'user');
  const nameOf = (modelId: string) =>
    loaded.models.find((m) => m.id === modelId)?.display_name ?? modelId;
  const instanceModel = loaded.instanceModelId
    ? nameOf(loaded.instanceModelId)
    : null;
  const instanceLabel = instanceModel
    ? t('settings.general.taskModelInstanceDefault', { model: instanceModel })
    : t('settings.general.taskModelInstanceDefaultUnnamed');
  // The model that runs now: the pick, else the instance default.
  const running =
    loaded.value === INSTANCE_DEFAULT || loaded.value === UNAVAILABLE
      ? loaded.instanceModelId
      : loaded.value;
  const refused =
    loaded.refusedModelId !== null && running === loaded.refusedModelId
      ? nameOf(loaded.refusedModelId)
      : null;
  const pickedLabel =
    loaded.value === INSTANCE_DEFAULT
      ? instanceLabel
      : loaded.value === UNAVAILABLE
        ? undefined
        : nameOf(loaded.value);
  const renderItem = (model: Model) => (
    <SelectItem
      key={model.id}
      value={model.id}
      suffix={
        model.id === loaded.refusedModelId
          ? t('settings.general.taskModelFailedItem')
          : undefined
      }
    >
      <span className="truncate">{model.display_name}</span>
    </SelectItem>
  );

  const save = async (value: string): Promise<boolean> => {
    try {
      const response = await userService.updatePreferences(
        { task_model_id: value === INSTANCE_DEFAULT ? null : value },
        token,
      );
      return !!response?.ok;
    } catch {
      return false;
    }
  };

  // Saves `first`, then whatever was picked while it was in flight, until
  // nothing waits; only when the last save fails does the pick roll back.
  const flush = async (first: string) => {
    saving.current = true;
    let next: string | null = first;
    let failed = false;
    while (next !== null) {
      const value: string = next;
      queued.current = null;
      failed = false;
      if (value !== savedValue.current) {
        failed = !(await save(value));
        if (!failed) {
          savedValue.current = value;
          resetDrafterConfigCache();
        }
      }
      next = queued.current;
    }
    saving.current = false;
    if (!failed) return;
    const previous = savedValue.current;
    setLoaded((current) => (current ? { ...current, value: previous } : null));
    dispatch(
      showActionToast({
        variant: 'destructive',
        message: t('settings.general.taskModelSaveFailed'),
      }),
    );
  };

  const change = (next: string) => {
    if (next === loaded.value) return;
    setLoaded((current) => (current ? { ...current, value: next } : null));
    if (saving.current) {
      queued.current = next;
      return;
    }
    void flush(next);
  };

  return (
    <section className="flex flex-col gap-4">
      <SectionHeader title={t('settings.general.sections.models')} />
      <SettingRows>
        <SettingRow
          label={t('settings.general.taskModel')}
          description={t('settings.general.taskModelDescription')}
          htmlFor={id}
          stack
          after={
            loaded.value === UNAVAILABLE || refused ? (
              <Alert variant="warning">
                <AlertDescription>
                  {loaded.value === UNAVAILABLE
                    ? t('settings.general.taskModelUnavailable')
                    : t('settings.general.taskModelFailed', {
                        model: refused,
                        interpolation: { escapeValue: false },
                      })}
                </AlertDescription>
              </Alert>
            ) : undefined
          }
        >
          <Select
            value={loaded.value === UNAVAILABLE ? '' : loaded.value}
            onValueChange={change}
          >
            <SelectTrigger
              id={id}
              // Grows to its value, up to 384px (room for the instance
              // default's label with its model), then ends in "…" (the
              // whole name as its title).
              className="w-full sm:w-auto sm:max-w-96 sm:min-w-56"
              size="field"
              shape="pill"
              title={pickedLabel}
            >
              <SelectValue
                placeholder={t('settings.general.taskModelUnavailableValue')}
              />
            </SelectTrigger>
            <SelectContent fit>
              <SelectItem value={INSTANCE_DEFAULT}>
                <span className="truncate">{instanceLabel}</span>
              </SelectItem>
              {builtin.length > 0 && (
                <SelectGroup>
                  <SelectLabel>
                    {t('settings.customModels.modelsGroup.builtin')}
                  </SelectLabel>
                  {builtin.map(renderItem)}
                </SelectGroup>
              )}
              {own.length > 0 && (
                <SelectGroup>
                  <SelectLabel>
                    {t('settings.customModels.modelsGroup.user')}
                  </SelectLabel>
                  {own.map(renderItem)}
                </SelectGroup>
              )}
            </SelectContent>
          </Select>
        </SettingRow>
      </SettingRows>
    </section>
  );
}
