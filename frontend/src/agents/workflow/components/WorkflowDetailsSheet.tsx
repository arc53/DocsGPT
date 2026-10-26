import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { FormField } from '@/components/ui/form-field';
import { Input } from '@/components/ui/input';
import { SectionHeader } from '@/components/ui/section-header';
import { SettingRow, SettingRows } from '@/components/ui/setting-row';
import {
  PanelBody,
  PanelFooter,
  PanelHeader,
  SidePanel,
} from '@/components/ui/side-panel';
import { Switch } from '@/components/ui/switch';
import { Textarea } from '@/components/ui/textarea';

import { FileUpload } from '../../../components/FileUpload';
import { analyticsOf, isDefaultAnalytics } from '../../analyticsConfig';
import {
  type ModelWindow,
  isContextLimitInvalid,
  isHistoryLimitInvalid,
} from '../../contextLimit';
import ContextLimitRows from '../../components/ContextLimitRows';
import InsightsSettingsBody from '../../components/InsightsSettingsBody';
import type { AnalyticsConfig } from '../../types';

export interface WorkflowDetailsValues {
  name: string;
  description: string;
  allowPromptOverride: boolean;
  /** `config.analytics`; unset reads as the defaults. */
  analytics?: AnalyticsConfig;
  /** `config.context_window_limit`; null uses the model's whole window. */
  contextWindowLimit: number | null;
  /** `config.history_token_limit`; null summarizes only near the window. */
  historyTokenLimit: number | null;
}

/** What the Insights card needs from the builder. */
export interface WorkflowInsightsOptions {
  /** The server lets the decision model label conversations. */
  available: boolean;
  maxTopics: number;
  maxOverlapping: number;
  agentId?: string;
  token: string | null;
}

export interface WorkflowDetailsSave extends WorkflowDetailsValues {
  /** A newly picked avatar, or null to keep the current one. */
  imageFile: File | null;
}

interface WorkflowDetailsSheetProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** The builder's current values; the sheet edits a copy of them. */
  details: WorkflowDetailsValues;
  /** The saved avatar's URL, shown in the tile until a new one is picked. */
  currentImage: string;
  saving: boolean;
  /** Errors from the last save started here, shown at the top of the body. */
  errors: string[];
  /** The Insights card's server switch and limits; left out, no card. */
  insights?: WorkflowInsightsOptions;
  /** The caller may change policy (`edit_policy`): the context and history limits. */
  policyEditable?: boolean;
  /** The largest window of the workflow's models; a limit past it is noted. */
  modelWindow?: ModelWindow | null;
  onSave: (values: WorkflowDetailsSave) => void;
}

/**
 * The workflow's name, description, avatar, prompt-override and context-limit
 * settings and insights settings, in a modal side panel laid out like the classic agent's
 * Basics on a phone. The Insights card hides while the server has insights
 * off, unless the workflow already has settings of its own (as on Overview).
 *
 * The sheet edits a copy: Cancel, the X, Escape and the scrim drop the edits,
 * and Save hands them to the builder, which saves the workflow.
 *
 * Args:
 *   open: Whether the sheet is open.
 *   onOpenChange: Opens or closes the sheet.
 *   details: The values to start from each time it opens.
 *   currentImage: The saved avatar's URL.
 *   saving: Whether a save started here is running.
 *   errors: Errors from that save.
 *   insights: The Insights card's server switch and limits.
 *   policyEditable: Whether the context and history limits can be changed.
 *   modelWindow: The largest window of the workflow's models.
 *   onSave: Receives the edited values.
 */
export default function WorkflowDetailsSheet({
  open,
  onOpenChange,
  details,
  currentImage,
  saving,
  errors,
  insights,
  policyEditable = true,
  modelWindow = null,
  onSave,
}: WorkflowDetailsSheetProps) {
  const { t } = useTranslation();
  const withDefaults = (values: WorkflowDetailsValues) => ({
    ...values,
    analytics: analyticsOf(values.analytics),
  });
  const [draft, setDraft] = useState(() => withDefaults(details));
  const [imageFile, setImageFile] = useState<File | null>(null);

  // Start from the builder's values every time the sheet opens.
  useEffect(() => {
    if (!open) return;
    setDraft(withDefaults(details));
    setImageFile(null);
    // Only on open: later changes to `details` come from this sheet's own save.
  }, [open]);

  const dirty =
    imageFile !== null ||
    draft.name !== details.name ||
    draft.description !== details.description ||
    draft.allowPromptOverride !== details.allowPromptOverride ||
    JSON.stringify(draft.analytics) !==
      JSON.stringify(analyticsOf(details.analytics)) ||
    !Object.is(draft.contextWindowLimit, details.contextWindowLimit) ||
    !Object.is(draft.historyTokenLimit, details.historyTokenLimit);
  const contextLimitInvalid =
    isContextLimitInvalid(draft.contextWindowLimit) ||
    isHistoryLimitInvalid(draft.historyTokenLimit, draft.contextWindowLimit);
  const showInsights =
    insights !== undefined &&
    (insights.available || !isDefaultAnalytics(details.analytics));

  return (
    <SidePanel open={open} onOpenChange={onOpenChange}>
      <PanelHeader
        title={t('agents.workflow.builder.detailsTitle')}
        description={t('agents.workflow.builder.detailsDescription')}
      />
      <PanelBody>
        {errors.length > 0 && (
          <Alert variant="destructive">
            <AlertTitle>{t('agents.workflow.builder.unableSave')}</AlertTitle>
            <AlertDescription>
              <ul className="flex list-inside list-disc flex-col gap-1 wrap-break-word">
                {errors.map((error, index) => (
                  <li key={index}>{error}</li>
                ))}
              </ul>
            </AlertDescription>
          </Alert>
        )}
        <Card variant="subtle" padding="lg" className="gap-5">
          <SectionHeader
            as="h3"
            size="xs"
            title={t('agents.form.sections.basics')}
          />
          {/* The phone layout of classic Basics: the avatar beside Name,
                Description across the row. */}
          <div className="grid grid-cols-[auto_1fr] items-center gap-x-4 gap-y-5">
            <FileUpload
              showPreview
              size="tile"
              tileSize="fixed"
              currentImage={currentImage || undefined}
              onUpload={(files) => setImageFile(files[0] ?? null)}
              onRemove={() => setImageFile(null)}
              uploadText={t('agents.form.labels.avatar')}
            />
            <FormField
              labelSurface="background"
              label={t('agents.form.labels.name')}
            >
              <Input
                type="text"
                value={draft.name}
                placeholder={t(
                  'agents.workflow.builder.workflowNamePlaceholder',
                )}
                onChange={(e) => setDraft({ ...draft, name: e.target.value })}
              />
            </FormField>
            <FormField
              labelSurface="background"
              label={t('agents.form.labels.description')}
              className="col-span-2"
            >
              <Textarea
                className="h-32"
                placeholder={t(
                  'agents.workflow.builder.workflowDescriptionPlaceholder',
                )}
                value={draft.description}
                onChange={(e) =>
                  setDraft({ ...draft, description: e.target.value })
                }
              />
            </FormField>
          </div>
        </Card>
        <Card variant="subtle" padding="lg" className="gap-5">
          <SectionHeader
            as="h3"
            size="xs"
            title={t('agents.form.sections.advanced')}
          />
          <SettingRows>
            <ContextLimitRows
              contextLimit={draft.contextWindowLimit}
              historyLimit={draft.historyTokenLimit}
              window={modelWindow ?? null}
              disabled={!policyEditable}
              onContextLimitChange={(limit) =>
                setDraft((prev) => ({ ...prev, contextWindowLimit: limit }))
              }
              onHistoryLimitChange={(limit) =>
                setDraft((prev) => ({ ...prev, historyTokenLimit: limit }))
              }
            />
            <SettingRow
              label={t('agents.form.advanced.systemPromptOverride')}
              description={t(
                'agents.form.advanced.systemPromptOverrideDescription',
              )}
              htmlFor="workflow-system-prompt-override"
            >
              <Switch
                id="workflow-system-prompt-override"
                checked={draft.allowPromptOverride}
                onCheckedChange={(checked) =>
                  setDraft({ ...draft, allowPromptOverride: checked })
                }
              />
            </SettingRow>
          </SettingRows>
        </Card>
        {showInsights && (
          <Card variant="subtle" padding="lg" className="gap-5">
            <SectionHeader
              as="h3"
              size="xs"
              title={t('agents.form.sections.analytics')}
            />
            {!insights.available && (
              <Alert variant="info" role="note">
                <AlertDescription>
                  {t('agents.form.analytics.serverOff')}
                </AlertDescription>
              </Alert>
            )}
            <InsightsSettingsBody
              value={draft.analytics}
              onChange={(analytics) => setDraft({ ...draft, analytics })}
              agentId={insights.agentId}
              maxTopics={insights.maxTopics}
              maxOverlapping={insights.maxOverlapping}
              token={insights.token}
              // No agent-level sources: the topics are the owner's own list.
              topicSource="none"
              headingLevel="h4"
            />
          </Card>
        )}
      </PanelBody>
      <PanelFooter>
        <Button
          type="button"
          variant="ghost"
          size="lg"
          shape="pill"
          onClick={() => onOpenChange(false)}
        >
          {t('agents.form.buttons.cancel')}
        </Button>
        <Button
          type="button"
          size="lg"
          shape="pill"
          disabled={!dirty || contextLimitInvalid}
          loading={saving}
          onClick={() => onSave({ ...draft, imageFile })}
        >
          {t('agents.form.buttons.save')}
        </Button>
      </PanelFooter>
    </SidePanel>
  );
}
