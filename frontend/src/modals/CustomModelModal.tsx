import { Check, CircleAlert, CircleCheck } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';

import customModelsService from '../api/services/customModelsService';
import { Alert, AlertDescription } from '../components/ui/alert';
import { Button } from '../components/ui/button';
import { FormField } from '../components/ui/form-field';
import { Input } from '../components/ui/input';
import { SectionHeader } from '../components/ui/section-header';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '../components/ui/select';
import { ActiveState } from '../models/misc';
import { selectToken } from '../preferences/preferenceSlice';
import { Modal, ModalActions } from '../components/ui/modal';

import type {
  CreateCustomModelPayload,
  CustomModel,
  CustomModelCapabilities,
  ModelApiFlavor,
  ReasoningEffort,
} from '../models/types';

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
  api_flavor: ModelApiFlavor;
  reasoning_effort: ReasoningEffort | 'default';
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
      api_flavor: 'chat_completions',
      reasoning_effort: 'default',
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
    api_flavor: model.capabilities?.api_flavor ?? 'chat_completions',
    reasoning_effort: model.capabilities?.reasoning_effort ?? 'default',
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
    const capabilities: CustomModelCapabilities = {
      supports_tools: formData.supports_tools,
      supports_structured_output: formData.supports_structured_output,
      attachments: formData.supports_images ? ['image'] : [],
      context_window: ctxValue,
      api_flavor: formData.api_flavor,
    };
    if (formData.reasoning_effort !== 'default') {
      capabilities.reasoning_effort = formData.reasoning_effort;
    }
    const payload: CreateCustomModelPayload = {
      upstream_model_id: formData.upstream_model_id.trim(),
      display_name: formData.display_name.trim(),
      description: formData.description.trim(),
      base_url: formData.base_url.trim(),
      capabilities,
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
  const handleTest = async () => {
    if (!canTest) return;
    setTesting(true);
    setTestResult(null);
    try {
      const capabilities = {
        api_flavor: formData.api_flavor,
      };
      const result =
        isEditMode && model?.id
          ? await customModelsService.testCustomModel(model.id, token, {
              base_url: trimmedBaseUrl,
              api_key: trimmedApiKey,
              upstream_model_id: trimmedUpstreamId,
              capabilities,
            })
          : await customModelsService.testCustomModelPayload(
              {
                base_url: trimmedBaseUrl,
                api_key: trimmedApiKey,
                upstream_model_id: trimmedUpstreamId,
                capabilities,
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

  return (
    <Modal
      open={modalState === 'ACTIVE'}
      onOpenChange={(o) => !o && closeModal()}
      title={
        isEditMode
          ? t('settings.customModels.editTitle')
          : t('settings.customModels.addTitle')
      }
      description={t('settings.customModels.modalSubtitle')}
      size="lg"
      mobileVariant="sheet"
      footer={
        <ModalActions
          footerStart={
            <Button
              type="button"
              variant="outline"
              onClick={handleTest}
              disabled={!canTest || saving}
              loading={testing}
              size="lg"
              shape="pill"
            >
              {t('settings.customModels.testConnection')}
            </Button>
          }
          cancelLabel={t('cancel')}
          onCancel={closeModal}
          cancelProps={{ disabled: saving }}
          submitLabel={t('settings.customModels.save')}
          onSubmit={handleSave}
          pending={saving}
        />
      }
    >
      <div className="flex flex-col gap-5">
        {/* Row 1: Display name + Model ID side-by-side */}
        <div className="grid grid-cols-1 gap-x-4 gap-y-5 sm:grid-cols-2">
          <FormField
            label={t('settings.customModels.fields.displayName')}
            required
            error={errors.display_name}
          >
            <Input
              type="text"
              value={formData.display_name}
              onChange={(e) => handleChange('display_name', e.target.value)}
              placeholder={t('settings.customModels.placeholders.displayName')}
            />
          </FormField>

          <FormField
            label={t('settings.customModels.fields.modelId')}
            required
            error={errors.upstream_model_id}
          >
            <Input
              type="text"
              value={formData.upstream_model_id}
              onChange={(e) =>
                handleChange('upstream_model_id', e.target.value)
              }
              placeholder={t('settings.customModels.placeholders.modelId')}
            />
          </FormField>
        </div>

        {/* Row 2: Base URL + API key side-by-side */}
        <div className="grid grid-cols-1 gap-x-4 gap-y-5 sm:grid-cols-2">
          <FormField
            label={t('settings.customModels.fields.baseUrl')}
            required
            error={
              [errors.base_url, errors.base_url_remote]
                .filter(Boolean)
                .join(' ') || undefined
            }
          >
            <Input
              type="url"
              autoComplete="off"
              autoCorrect="off"
              autoCapitalize="off"
              spellCheck={false}
              value={formData.base_url}
              onChange={(e) => handleChange('base_url', e.target.value)}
              placeholder={t('settings.customModels.placeholders.baseUrl')}
            />
          </FormField>

          <FormField
            label={t('settings.customModels.fields.apiKey')}
            required={!isEditMode}
            hint={
              isEditMode
                ? t('settings.customModels.hints.apiKeyEdit')
                : undefined
            }
            error={errors.api_key}
          >
            <Input
              type="text"
              autoComplete="off"
              autoCorrect="off"
              autoCapitalize="off"
              spellCheck={false}
              value={formData.api_key}
              onChange={(e) => handleChange('api_key', e.target.value)}
              placeholder={
                isEditMode
                  ? t('settings.customModels.placeholders.apiKeyEdit')
                  : t('settings.customModels.placeholders.apiKey')
              }
            />
          </FormField>
        </div>

        {/* Row 3: Description (full width, optional) */}
        <FormField label={t('settings.customModels.fields.description')}>
          <Input
            type="text"
            value={formData.description}
            onChange={(e) => handleChange('description', e.target.value)}
            placeholder={t('settings.customModels.placeholders.description')}
          />
        </FormField>

        {/* Row 4: Capabilities — flat (no border), fields grid then chips */}
        <div className="flex flex-col gap-5">
          <SectionHeader
            as="h3"
            size="xs"
            title={t('settings.customModels.capabilities.title')}
          />
          <div className="grid grid-cols-1 gap-x-4 gap-y-5 sm:grid-cols-2">
            <FormField
              label={t('settings.customModels.capabilities.apiFlavor')}
            >
              <Select
                value={formData.api_flavor}
                onValueChange={(value) =>
                  handleChange('api_flavor', value as ModelApiFlavor)
                }
              >
                <SelectTrigger size="field" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="chat_completions">
                    {t(
                      'settings.customModels.capabilities.apiFlavors.chatCompletions',
                    )}
                  </SelectItem>
                  <SelectItem value="responses">
                    {t(
                      'settings.customModels.capabilities.apiFlavors.responses',
                    )}
                  </SelectItem>
                </SelectContent>
              </Select>
            </FormField>
            <FormField
              label={t('settings.customModels.capabilities.reasoningEffort')}
            >
              <Select
                value={formData.reasoning_effort}
                onValueChange={(value) =>
                  handleChange(
                    'reasoning_effort',
                    value as ReasoningEffort | 'default',
                  )
                }
              >
                <SelectTrigger size="field" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="default">
                    {t(
                      'settings.customModels.capabilities.reasoningEfforts.default',
                    )}
                  </SelectItem>
                  {(
                    [
                      'none',
                      'minimal',
                      'low',
                      'medium',
                      'high',
                      'xhigh',
                    ] as ReasoningEffort[]
                  ).map((effort) => (
                    <SelectItem key={effort} value={effort}>
                      {effort}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </FormField>
            <FormField
              label={t('settings.customModels.capabilities.contextWindowShort')}
              error={errors.context_window}
            >
              <Input
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
              />
            </FormField>
          </div>
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
        </div>

        {testResult && (
          <Alert variant={testResult.ok ? 'success' : 'destructive'}>
            {testResult.ok ? (
              <CircleCheck className="size-4" aria-hidden="true" />
            ) : (
              <CircleAlert className="size-4" aria-hidden="true" />
            )}
            <AlertDescription>{testResult.message}</AlertDescription>
          </Alert>
        )}

        {errors.general && (
          <Alert variant="destructive">
            <CircleAlert className="size-4" aria-hidden="true" />
            <AlertDescription>{errors.general}</AlertDescription>
          </Alert>
        )}
      </div>
    </Modal>
  );
}

interface CapabilityChipProps {
  label: string;
  active: boolean;
  onClick: () => void;
}

export function CapabilityChip({
  label,
  active,
  onClick,
}: CapabilityChipProps) {
  return (
    <Button
      type="button"
      variant={active ? 'secondary' : 'ghost-muted'}
      size="sm"
      shape="pill"
      role="switch"
      aria-checked={active}
      onClick={onClick}
    >
      {active && <Check className="size-3.5" strokeWidth={2.5} />}
      {label}
    </Button>
  );
}
