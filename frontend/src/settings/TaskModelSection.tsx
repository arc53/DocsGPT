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
import { SectionHeader } from '../components/ui/section-header';
import { resetDrafterConfigCache } from '../drafter/useDrafterConfig';
import { SettingRow, SettingRows } from '../components/ui/setting-row';
import type { Model } from '../models/types';
import { showActionToast } from '../notifications/actionToastSlice';
import { selectToken } from '../preferences/preferenceSlice';

/** The Select value for "no pick: use the instance's task model". */
export const INSTANCE_DEFAULT = '__instance__';

type Loaded = {
  /** The caller's pick, or INSTANCE_DEFAULT. */
  value: string;
  /** What runs without a pick: the admin's, TASK_MODEL_ID or the default. */
  instanceModelId: string | null;
  models: Model[];
};

/**
 * Settings > General > Models: the task model, which runs DocsGPT's own jobs
 * (the drafter, graph extraction, monitor checks) for this user. Saved to
 * the server on change; a failed save puts the previous pick back.
 */
export default function TaskModelSection() {
  const { t } = useTranslation();
  const dispatch = useDispatch();
  const token = useSelector(selectToken);
  const id = React.useId();
  const [loaded, setLoaded] = React.useState<Loaded | null>(null);
  // Only the latest save may roll the pick back, to the last one saved.
  const saveSeq = React.useRef(0);
  const savedValue = React.useRef(INSTANCE_DEFAULT);

  React.useEffect(() => {
    let cancelled = false;
    Promise.all([
      userService.getPreferences(token),
      modelService.getModels(token),
    ])
      .then(async ([prefsRes, modelsRes]) => {
        if (!prefsRes?.ok || !modelsRes?.ok) return;
        const prefs = await prefsRes.json();
        const data = await modelsRes.json();
        // A server from before the task model sends no such field.
        if (cancelled || !prefs || !('instance_task_model_id' in prefs)) return;
        const models = modelService.transformModels(data?.models || []);
        const picked =
          typeof prefs.task_model_id === 'string' &&
          models.some((m) => m.id === prefs.task_model_id)
            ? prefs.task_model_id
            : INSTANCE_DEFAULT;
        savedValue.current = picked;
        setLoaded({
          value: picked,
          instanceModelId: prefs.instance_task_model_id ?? null,
          models,
        });
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [token]);

  if (!loaded) return null;

  const builtin = loaded.models.filter((m) => m.source !== 'user');
  const own = loaded.models.filter((m) => m.source === 'user');
  const instanceName = loaded.models.find(
    (m) => m.id === loaded.instanceModelId,
  )?.display_name;
  const instanceLabel = instanceName
    ? t('settings.general.taskModelInstanceDefault', { model: instanceName })
    : t('settings.general.taskModelInstanceDefaultUnnamed');

  const change = async (next: string) => {
    if (next === loaded.value) return;
    setLoaded((current) => (current ? { ...current, value: next } : null));
    const seq = ++saveSeq.current;
    let saved = false;
    try {
      const response = await userService.updatePreferences(
        { task_model_id: next === INSTANCE_DEFAULT ? null : next },
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
              <SelectItem value={INSTANCE_DEFAULT}>{instanceLabel}</SelectItem>
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
