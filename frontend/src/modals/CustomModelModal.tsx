import { Check } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';

import customModelsService from '../api/services/customModelsService';
import Spinner from '../components/Spinner';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';
import { ActiveState } from '../models/misc';
import { selectToken } from '../preferences/preferenceSlice';
import WrapperComponent from './WrapperModal';

import type { CreateCustomModelPayload, CustomModel } from '../models/types';

interface CustomModelModalProps {
  modalState: ActiveState;
  setModalState: (state: ActiveState) => void;
  model?: CustomModel | null;
  onSaved: (model: CustomModel) => void;
}

interface FormState {
  display_name: string;
  upstream_model_id: string;
  description: string;
  base_url: string;
  api_key: string;
  supports_tools: boolean;
  supports_structured_output: boolean;
  supports_images: boolean;
  context_window: number | '';
  enabled: boolean;
}

const DEFAULT_CONTEXT_WINDOW = 128000;
const MIN_CONTEXT_WINDOW = 1000;
const MAX_CONTEXT_WINDOW = 10_000_000;

const buildInitialFormState = (model?: CustomModel | null): FormState => {
  if (!model) {
    return {
      display_name: '',
      upstream_model_id: '',
      description: '',
      base_url: '',
      api_key: '',
      supports_tools: true,
      supports_structured_output: true,
      supports_images: false,
      context_window: DEFAULT_CONTEXT_WINDOW,
      enabled: true,
    };
  }
  const attachments = Array.isArray(model.capabilities?.attachments)
    ? model.capabilities.attachments
    : [];
  return {
    display_name: model.display_name || '',
    upstream_model_id: model.upstream_model_id || '',
    description: model.description || '',
    base_url: model.base_url || '',
    api_key: '',
    supports_tools: model.capabilities?.supports_tools ?? true,
    supports_structured_output:
      model.capabilities?.supports_structured_output ?? true,
    supports_images: attachments.includes('image'),
    context_window:
      model.capabilities?.context_window ?? DEFAULT_CONTEXT_WINDOW,
    enabled: model.enabled ?? true,
  };
};

export default function CustomModelModal({
  modalState,
  setModalState,
  model,
  onSaved,
}: CustomModelModalProps) {
  const { t } = useTranslation();
  const token = useSelector(selectToken);
  const isEditMode = !!model?.id;

  const [formData, setFormData] = useState<FormState>(() =>
    buildInitialFormState(model),
  );
  const [errors, setErrors] = useState<{ [key: string]: string }>({});
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<{
    ok: boolean;
    message: string;
  } | null>(null);

  useEffect(() => {
    if (modalState === 'ACTIVE') {
      setFormData(buildInitialFormState(model));
      setErrors({});
      setTestResult(null);
      setSaving(false);
      setTesting(false);
    }
  }, [modalState, model]);

  const closeModal = () => {
    setModalState('INACTIVE');
  };

  const handleChange = <K extends keyof FormState>(
    name: K,
    value: FormState[K],
  ) => {
    setFormData((prev) => ({ ...prev, [name]: value }));
    if (errors[name as string] || errors.general) {
      setErrors((prev) => {
        const next = { ...prev };
        delete next[name as string];
        delete next.general;
        delete next.base_url_remote;
        return next;
      });
    }
    setTestResult(null);
  };

  const validate = (): boolean => {
    const newErrors: { [key: string]: string } = {};
    if (!formData.display_name.trim()) {
      newErrors.display_name = t(
        'settings.customModels.errors.displayNameRequired',
      );
    }
    if (!formData.upstream_model_id.trim()) {
      newErrors.upstream_model_id = t(
        'settings.customModels.errors.modelIdRequired',
      );
    }
    const trimmedUrl = formData.base_url.trim();
    if (!trimmedUrl) {
      newErrors.base_url = t('settings.customModels.errors.baseUrlRequired');
    } else if (!/^https?:\/\//i.test(trimmedUrl)) {
      newErrors.base_url = t('settings.customModels.errors.baseUrlScheme');
    } else {
      try {
        new URL(trimmedUrl);
      } catch {
        newErrors.base_url = t('settings.customModels.errors.baseUrlInvalid');
      }
    }
    if (!isEditMode && !formData.api_key.trim()) {
      newErrors.api_key = t('settings.customModels.errors.apiKeyRequired');
    }
    const ctxValue =
      formData.context_window === '' ? NaN : Number(formData.context_window);
    if (
      Number.isNaN(ctxValue) ||
      ctxValue < MIN_CONTEXT_WINDOW ||
      ctxValue > MAX_CONTEXT_WINDOW
    ) {
      newErrors.context_window = t(
        'settings.customModels.errors.contextWindowRange',
      );
    }

    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  };

  const buildPayload = (): CreateCustomModelPayload => {
    const ctxValue =
      formData.context_window === ''
        ? DEFAULT_CONTEXT_WINDOW
        : Number(formData.context_window);
    const payload: CreateCustomModelPayload = {
      upstream_model_id: formData.upstream_model_id.trim(),
      display_name: formData.display_name.trim(),
      description: formData.description.trim(),
      base_url: formData.base_url.trim(),
      capabilities: {
        supports_tools: formData.supports_tools,
        supports_structured_output: formData.supports_structured_output,
        attachments: formData.supports_images ? ['image'] : [],
        context_window: ctxValue,
      },
      enabled: formData.enabled,
    };
    if (formData.api_key.trim()) {
      payload.api_key = formData.api_key.trim();
    }
    return payload;
  };

  const mapErrorToField = (
    message: string,
  ): { field: string; message: string } => {
    const lower = message.toLowerCase();
    if (
      lower.includes('reachable') ||
      lower.includes('public internet') ||
      lower.includes('ssrf') ||
      lower.includes('url') ||
      lower.includes('host')
    ) {
      return { field: 'base_url_remote', message };
    }
    return { field: 'general', message };
  };

  const handleSave = async () => {
    if (!validate()) return;
    setSaving(true);
    setTestResult(null);
    try {
      const payload = buildPayload();
      const saved = isEditMode
        ? await customModelsService.updateCustomModel(model!.id, payload, token)
        : await customModelsService.createCustomModel(payload, token);
      onSaved(saved);
      closeModal();
    } catch (err) {
      const message =
        err instanceof Error
          ? err.message
          : t('settings.customModels.errors.saveFailed');
      const mapped = mapErrorToField(message);
      setErrors((prev) => ({ ...prev, [mapped.field]: mapped.message }));
    } finally {
      setSaving(false);
    }
  };

  // Edit mode allows blank api_key (by-id endpoint falls back to stored).
  const trimmedBaseUrl = formData.base_url.trim();
  const trimmedApiKey = formData.api_key.trim();
  const trimmedUpstreamId = formData.upstream_model_id.trim();
  const canTest = isEditMode
    ? !!(trimmedBaseUrl && trimmedUpstreamId)
    : !!(trimmedBaseUrl && trimmedApiKey && trimmedUpstreamId);
  const testDisabledHint = canTest
    ? undefined
    : t('settings.customModels.testHintNew');

  const handleTest = async () => {
    if (!canTest) return;
    setTesting(true);
    setTestResult(null);
    try {
      const result =
        isEditMode && model?.id
          ? await customModelsService.testCustomModel(model.id, token, {
              base_url: trimmedBaseUrl,
              api_key: trimmedApiKey,
              upstream_model_id: trimmedUpstreamId,
            })
          : await customModelsService.testCustomModelPayload(
              {
                base_url: trimmedBaseUrl,
                api_key: trimmedApiKey,
                upstream_model_id: trimmedUpstreamId,
              },
              token,
            );
      if (result.ok) {
        setTestResult({
          ok: true,
          message: t('settings.customModels.testSuccess'),
        });
      } else {
        const message =
          result.error || t('settings.customModels.errors.testFailed');
        setTestResult({ ok: false, message });
        const mapped = mapErrorToField(message);
        if (mapped.field === 'base_url_remote') {
          setErrors((prev) => ({ ...prev, base_url_remote: message }));
        }
      }
    } catch (err) {
      const message =
        err instanceof Error
          ? err.message
          : t('settings.customModels.errors.testFailed');
      setTestResult({ ok: false, message });
    } finally {
      setTesting(false);
    }
  };

  if (modalState !== 'ACTIVE') return null;

  return (
    <WrapperComponent
      close={closeModal}
      isPerformingTask={saving}
      className="max-w-[600px] md:w-[80vw] lg:w-[60vw]"
    >
      <div className="flex h-full flex-col">
        <div className="px-2 py-2">
          <h2 className="text-foreground dark:text-foreground text-xl font-semibold">
            {isEditMode
              ? t('settings.customModels.editTitle')
              : t('settings.customModels.addTitle')}
          </h2>
          <p className="text-muted-foreground mt-2 text-sm">
            {t('settings.customModels.modalSubtitle')}
          </p>
        </div>
        <div className="flex-1 px-2">
          <div className="flex flex-col gap-4 px-0.5 py-4">
            {/* Row 1: Display name + Model ID side-by-side */}
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="cm-display-name">
                  {t('settings.customModels.fields.displayName')}
                  <span className="text-red-500">*</span>
                </Label>
                <Input
                  id="cm-display-name"
                  type="text"
                  value={formData.display_name}
                  onChange={(e) => handleChange('display_name', e.target.value)}
                  placeholder={t(
                    'settings.customModels.placeholders.displayName',
                  )}
                  aria-invalid={!!errors.display_name || undefined}
                  className="rounded-xl"
                />
                {errors.display_name && (
                  <p className="text-destructive text-xs">
                    {errors.display_name}
                  </p>
                )}
              </div>

              <div className="flex flex-col gap-1.5">
                <Label htmlFor="cm-model-id">
                  {t('settings.customModels.fields.modelId')}
                  <span className="text-red-500">*</span>
                </Label>
                <Input
                  id="cm-model-id"
                  type="text"
                  value={formData.upstream_model_id}
                  onChange={(e) =>
                    handleChange('upstream_model_id', e.target.value)
                  }
                  placeholder={t('settings.customModels.placeholders.modelId')}
                  aria-invalid={!!errors.upstream_model_id || undefined}
                  className="rounded-xl"
                />
                {errors.upstream_model_id && (
                  <p className="text-destructive text-xs">
                    {errors.upstream_model_id}
                  </p>
                )}
              </div>
            </div>

            {/* Row 2: Base URL + API key side-by-side */}
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="cm-base-url">
                  {t('settings.customModels.fields.baseUrl')}
                  <span className="text-red-500">*</span>
                </Label>
                <Input
                  id="cm-base-url"
                  type="url"
                  value={formData.base_url}
                  onChange={(e) => handleChange('base_url', e.target.value)}
                  placeholder={t('settings.customModels.placeholders.baseUrl')}
                  aria-invalid={
                    !!errors.base_url || !!errors.base_url_remote || undefined
                  }
                  className="rounded-xl"
                />
                {errors.base_url && (
                  <p className="text-destructive text-xs">{errors.base_url}</p>
                )}
                {errors.base_url_remote && (
                  <p className="text-destructive text-xs">
                    {errors.base_url_remote}
                  </p>
                )}
              </div>

              <div className="flex flex-col gap-1.5">
                <Label htmlFor="cm-api-key">
                  {t('settings.customModels.fields.apiKey')}
                  {!isEditMode && <span className="text-red-500">*</span>}
                </Label>
                <Input
                  id="cm-api-key"
                  type="password"
                  autoComplete="new-password"
                  value={formData.api_key}
                  onChange={(e) => handleChange('api_key', e.target.value)}
                  placeholder={
                    isEditMode
                      ? t('settings.customModels.placeholders.apiKeyEdit')
                      : t('settings.customModels.placeholders.apiKey')
                  }
                  aria-invalid={!!errors.api_key || undefined}
                  className="rounded-xl"
                />
                {isEditMode && (
                  <p className="text-muted-foreground text-xs">
                    {t('settings.customModels.hints.apiKeyEdit')}
                  </p>
                )}
                {errors.api_key && (
                  <p className="text-destructive text-xs">{errors.api_key}</p>
                )}
              </div>
            </div>

            {/* Row 3: Description (full width, optional) */}
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="cm-description">
                {t('settings.customModels.fields.description')}
              </Label>
              <Input
                id="cm-description"
                type="text"
                value={formData.description}
                onChange={(e) => handleChange('description', e.target.value)}
                placeholder={t(
                  'settings.customModels.placeholders.description',
                )}
                className="rounded-xl"
              />
            </div>

            {/* Row 4: Capabilities — flat (no border), chips + inline ctx */}
            <div className="flex flex-col gap-2">
              <Label>{t('settings.customModels.capabilities.title')}</Label>
              <div className="flex flex-wrap gap-2">
                <CapabilityChip
                  label={t('settings.customModels.capabilities.chips.tools')}
                  active={formData.supports_tools}
                  onClick={() =>
                    handleChange('supports_tools', !formData.supports_tools)
                  }
                />
                <CapabilityChip
                  label={t(
                    'settings.customModels.capabilities.chips.structuredOutput',
                  )}
                  active={formData.supports_structured_output}
                  onClick={() =>
                    handleChange(
                      'supports_structured_output',
                      !formData.supports_structured_output,
                    )
                  }
                />
                <CapabilityChip
                  label={t('settings.customModels.capabilities.chips.images')}
                  active={formData.supports_images}
                  onClick={() =>
                    handleChange('supports_images', !formData.supports_images)
                  }
                />
              </div>
              <div className="mt-1 flex flex-col gap-1.5 sm:flex-row sm:items-center sm:gap-3">
                <Label
                  htmlFor="cm-context-window"
                  className="text-muted-foreground text-xs sm:mb-0"
                >
                  {t('settings.customModels.capabilities.contextWindowShort')}
                </Label>
                <Input
                  id="cm-context-window"
                  type="number"
                  value={formData.context_window}
                  min={MIN_CONTEXT_WINDOW}
                  max={MAX_CONTEXT_WINDOW}
                  step={1000}
                  onChange={(e) => {
                    const v = e.target.value;
                    if (v === '') {
                      handleChange('context_window', '');
                    } else {
                      const n = parseInt(v, 10);
                      if (!Number.isNaN(n)) {
                        handleChange('context_window', n);
                      }
                    }
                  }}
                  aria-invalid={!!errors.context_window || undefined}
                  className="w-full rounded-xl sm:w-40"
                />
                {errors.context_window && (
                  <p className="text-destructive text-xs">
                    {errors.context_window}
                  </p>
                )}
              </div>
            </div>

            {testResult && (
              <div
                className={`rounded-xl p-3 text-sm ${
                  testResult.ok
                    ? 'bg-green-50 text-green-700 dark:bg-green-900/40 dark:text-green-300'
                    : 'bg-red-50 text-red-700 dark:bg-red-900/40 dark:text-red-300'
                }`}
              >
                {testResult.message}
              </div>
            )}

            {errors.general && (
              <div className="rounded-xl bg-red-50 p-3 text-sm text-red-700 dark:bg-red-900/40 dark:text-red-300">
                {errors.general}
              </div>
            )}
          </div>
        </div>

        <div className="px-2 py-4">
          <div className="flex flex-col gap-3 sm:flex-row sm:justify-between">
            <button
              type="button"
              onClick={handleTest}
              disabled={!canTest || testing || saving}
              title={testDisabledHint}
              className="border-border dark:border-border dark:text-foreground hover:bg-accent dark:hover:bg-muted/50 w-full rounded-3xl border px-6 py-2 text-sm font-medium transition-all disabled:cursor-not-allowed disabled:opacity-50 sm:w-auto"
            >
              {testing ? (
                <div className="flex items-center justify-center">
                  <Spinner size="small" />
                  <span className="ml-2">
                    {t('settings.customModels.testing')}
                  </span>
                </div>
              ) : (
                t('settings.customModels.testConnection')
              )}
            </button>
            <div className="flex flex-col-reverse gap-3 sm:flex-row sm:gap-3">
              <button
                type="button"
                onClick={closeModal}
                disabled={saving}
                className="dark:text-foreground hover:bg-accent dark:hover:bg-muted/50 w-full cursor-pointer rounded-3xl px-6 py-2 text-sm font-medium disabled:opacity-50 sm:w-auto"
              >
                {t('cancel')}
              </button>
              <button
                type="button"
                onClick={handleSave}
                disabled={saving}
                className="bg-primary hover:bg-primary/90 w-full rounded-3xl px-6 py-2 text-sm font-medium text-white transition-all disabled:opacity-50 sm:w-auto"
              >
                {saving ? (
                  <div className="flex items-center justify-center">
                    <Spinner size="small" />
                    <span className="ml-2">
                      {t('settings.customModels.saving')}
                    </span>
                  </div>
                ) : (
                  t('settings.customModels.save')
                )}
              </button>
            </div>
          </div>
        </div>
      </div>
    </WrapperComponent>
  );
}

interface CapabilityChipProps {
  label: string;
  active: boolean;
  onClick: () => void;
}

function CapabilityChip({ label, active, onClick }: CapabilityChipProps) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={active}
      onClick={onClick}
      className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-sm transition-colors ${
        active
          ? 'border-emerald-500/50 bg-emerald-500/10 text-emerald-700 dark:border-emerald-400/40 dark:bg-emerald-400/10 dark:text-emerald-300'
          : 'border-border text-muted-foreground hover:bg-accent dark:hover:bg-muted/40'
      }`}
    >
      {active && <Check size={14} strokeWidth={2.5} />}
      {label}
    </button>
  );
}
