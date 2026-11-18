import { Check } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';

import customModelsService from '../api/services/customModelsService';
import { Alert, AlertDescription } from '../components/ui/alert';
import { Button } from '../components/ui/button';
import { FormField } from '../components/ui/form-field';
import { Input } from '../components/ui/input';
import { SectionHeader } from '../components/ui/section-header';
import { ToggleChip } from '../components/ui/toggle-chip';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '../components/ui/select';
import {
  customModelErrorCode,
  customModelErrorMessage,
  customModelRequestError,
} from '../models/customModelErrors';
import { ActiveState } from '../models/misc';
import { selectToken } from '../preferences/preferenceSlice';
import { Modal, ModalActions } from '../components/ui/modal';

import type {
  CreateCustomModelPayload,
  CustomModel,
  CustomModelCapabilities,
  CustomModelOwner,
  ModelApiFlavor,
  ReasoningEffort,
  ToolResultImages,
} from '../models/types';

interface CustomModelModalProps {
  modalState: ActiveState;
  setModalState: (state: ActiveState) => void;
  model?: CustomModel | null;
  onSaved: (model: CustomModel) => void;
  /**
   * Whose a new model is: `team` adds it (and tests it) for the current
   * team. An edit goes by the model itself.
   */
  owner?: CustomModelOwner;
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
  tool_result_images: ToolResultImages | 'default';
  enabled: boolean;
}

const DEFAULT_CONTEXT_WINDOW = 128000;
const MIN_CONTEXT_WINDOW = 1000;
const MAX_CONTEXT_WINDOW = 10_000_000;

export const buildInitialFormState = (
  model?: CustomModel | null,
): FormState => {
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
      tool_result_images: 'default',
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
    // A flag missing from a saved model is off in the model registry
    // (docsgpt/core/model_registry.py); show it the same way here.
    supports_tools: model.capabilities?.supports_tools ?? false,
    supports_structured_output:
      model.capabilities?.supports_structured_output ?? false,
    supports_images: attachments.includes('image'),
    context_window:
      model.capabilities?.context_window ?? DEFAULT_CONTEXT_WINDOW,
    api_flavor: model.capabilities?.api_flavor ?? 'chat_completions',
    reasoning_effort: model.capabilities?.reasoning_effort ?? 'default',
    tool_result_images: model.capabilities?.tool_result_images ?? 'default',
    enabled: model.enabled ?? true,
  };
};

/**
 * The origin (scheme, host, port) of a URL, or '' while it doesn't parse.
 * The saved key is sent only to the origin it was saved for, as the server
 * rules: another one needs the key typed again.
 */
function originOf(url: string): string {
  try {
    return new URL(url.trim()).origin.toLowerCase();
  } catch {
    return '';
  }
}

// The refusal of a save or test that moved the model to another host
// without its key.
const NEW_HOST_CODE = 'api_key_required_for_new_host';

export default function CustomModelModal({
  modalState,
  setModalState,
  model,
  onSaved,
  owner,
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

  // A saved model whose address moves to another host needs its key typed
  // again; the saved one stays only on the same host.
  const newOrigin = originOf(formData.base_url);
  const hostChanged =
    isEditMode && !!newOrigin && newOrigin !== originOf(model?.base_url ?? '');
  const keyRequired = !isEditMode || hostChanged;
  const keyMissing = keyRequired && !formData.api_key.trim();

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
    if (keyMissing) {
      newErrors.api_key = hostChanged
        ? t('settings.customModels.errors.apiKeyNewHost')
        : t('settings.customModels.errors.apiKeyRequired');
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
    if (formData.supports_images && formData.tool_result_images !== 'default') {
      capabilities.tool_result_images = formData.tool_result_images;
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
        : await customModelsService.createCustomModel(
            owner === 'team' ? { ...payload, owner } : payload,
            token,
          );
      onSaved(saved);
      closeModal();
    } catch (err) {
      // A refusal code reads in the app's words; a sentence (an unsafe
      // URL) is the server's.
      const message = customModelRequestError(
        t,
        err,
        t('settings.customModels.errors.saveFailed'),
      );
      const refusal = (err as { payload?: unknown } | null)?.payload;
      const mapped =
        customModelErrorCode(refusal) === NEW_HOST_CODE
          ? { field: 'api_key', message }
          : mapErrorToField(message);
      setErrors((prev) => ({ ...prev, [mapped.field]: mapped.message }));
    } finally {
      setSaving(false);
    }
  };

  // Edit mode allows a blank api_key on the same host (the by-id endpoint
  // falls back to the stored one).
  const trimmedBaseUrl = formData.base_url.trim();
  const trimmedApiKey = formData.api_key.trim();
  const trimmedUpstreamId = formData.upstream_model_id.trim();
  const canTest = !!(trimmedBaseUrl && trimmedUpstreamId) && !keyMissing;
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
                ...(owner === 'team' && { owner }),
              },
              token,
            );
      if (result.ok) {
        setTestResult({
          ok: true,
          message: t('settings.customModels.testSuccess'),
        });
      } else {
        const message = customModelErrorMessage(
          t,
          { error: result.error, code: result.code },
          { fallback: t('settings.customModels.errors.testFailed') },
        );
        setTestResult({ ok: false, message });
        const mapped =
          result.code === NEW_HOST_CODE
            ? { field: 'api_key', message }
            : mapErrorToField(message);
        if (mapped.field === 'api_key') {
          setErrors((prev) => ({ ...prev, api_key: message }));
        } else if (mapped.field === 'base_url_remote') {
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
          disabled={hostChanged && keyMissing}
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
            required={keyRequired}
            hint={
              hostChanged
                ? t('settings.customModels.hints.apiKeyNewHost')
                : isEditMode
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
                isEditMode && !hostChanged
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
            {formData.supports_images && (
              <FormField
                label={t('settings.customModels.capabilities.toolImages')}
              >
                <Select
                  value={formData.tool_result_images}
                  onValueChange={(value) =>
                    handleChange(
                      'tool_result_images',
                      value as ToolResultImages | 'default',
                    )
                  }
                >
                  <SelectTrigger size="field" className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {(['default', 'native', 'follow_up'] as const).map(
                      (mode) => (
                        <SelectItem key={mode} value={mode}>
                          {t(
                            `settings.customModels.capabilities.toolImagesModes.${mode}`,
                          )}
                        </SelectItem>
                      ),
                    )}
                  </SelectContent>
                </Select>
              </FormField>
            )}
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
            <AlertDescription>{testResult.message}</AlertDescription>
          </Alert>
        )}

        {errors.general && (
          <Alert variant="destructive">
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
    <ToggleChip size="sm" pressed={active} onPressedChange={onClick}>
      {active && (
        <Check aria-hidden="true" className="size-3.5" strokeWidth={2.5} />
      )}
      {label}
    </ToggleChip>
  );
}
