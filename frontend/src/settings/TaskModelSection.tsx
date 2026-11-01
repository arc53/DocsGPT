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
import { EmptyState } from '../components/ui/empty-state';
import { SectionHeader } from '../components/ui/section-header';
import { Skeleton } from '../components/ui/skeleton';
import { resetDrafterConfigCache } from '../drafter/useDrafterConfig';
import { SettingRow, SettingRows } from '../components/ui/setting-row';
import type { Model } from '../models/types';
import { showActionToast } from '../notifications/actionToastSlice';
import { selectToken } from '../preferences/preferenceSlice';

type Loaded = {
  /** The caller's pick, else what runs without one ('' when unknown). */
  value: string;
  models: Model[];
};

/**
 * Settings › General › Models: the task model, which runs DocsGPT's own jobs
 * (the drafter, graph extraction, monitor checks) for this user. Saved to
 * the server on change; a failed save puts the previous pick back. A
 * skeleton row stands in while it loads and a load error with Retry when the
 * fetch fails; a server from before the task model hides the section.
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
  // Only the latest save may roll the pick back, to the last one saved.
  const saveSeq = React.useRef(0);
  const savedValue = React.useRef('');

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
        const known = (modelId: unknown): modelId is string =>
          typeof modelId === 'string' && models.some((m) => m.id === modelId);
        // With no pick, the model that runs anyway (the admin's,
        // TASK_MODEL_ID or the default) shows as selected.
        const picked = known(prefs.task_model_id)
          ? prefs.task_model_id
          : known(prefs.instance_task_model_id)
            ? prefs.instance_task_model_id
            : '';
        savedValue.current = picked;
        setLoaded({ value: picked, models });
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

  const change = async (next: string) => {
    if (next === loaded.value) return;
    setLoaded((current) => (current ? { ...current, value: next } : null));
    const seq = ++saveSeq.current;
    let saved = false;
    try {
      const response = await userService.updatePreferences(
        { task_model_id: next },
        token,
      );
      saved = !!response?.ok;
    } catch {
      saved = false;
    }
    if (saved) {
      savedValue.current = next;
      resetDrafterConfigCache();
    }
    if (saved || seq !== saveSeq.current) return;
    const previous = savedValue.current;
    setLoaded((current) => (current ? { ...current, value: previous } : null));
    dispatch(
      showActionToast({
        variant: 'destructive',
        message: t('settings.general.taskModelSaveFailed'),
      }),
    );
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
        >
          <Select value={loaded.value} onValueChange={change}>
            <SelectTrigger
              id={id}
              className="w-full sm:w-56"
              size="field"
              shape="pill"
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {builtin.length > 0 && (
                <SelectGroup>
                  <SelectLabel>
                    {t('settings.customModels.modelsGroup.builtin')}
                  </SelectLabel>
                  {builtin.map((model) => (
                    <SelectItem key={model.id} value={model.id}>
                      {model.display_name}
                    </SelectItem>
                  ))}
                </SelectGroup>
              )}
              {own.length > 0 && (
                <SelectGroup>
                  <SelectLabel>
                    {t('settings.customModels.modelsGroup.user')}
                  </SelectLabel>
                  {own.map((model) => (
                    <SelectItem key={model.id} value={model.id}>
                      {model.display_name}
                    </SelectItem>
                  ))}
                </SelectGroup>
              )}
            </SelectContent>
          </Select>
        </SettingRow>
      </SettingRows>
    </section>
  );
}
