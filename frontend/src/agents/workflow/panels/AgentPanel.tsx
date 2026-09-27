import { ChevronRight } from 'lucide-react';
import { useId, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { type Edge, type Node } from 'reactflow';

import { Button } from '@/components/ui/button';
import { FormField } from '@/components/ui/form-field';
import { Input } from '@/components/ui/input';
import { MultiSelect } from '@/components/ui/multi-select';
import { SectionHeader } from '@/components/ui/section-header';
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { SettingRow, SettingRows } from '@/components/ui/setting-row';
import { Switch } from '@/components/ui/switch';
import { Textarea } from '@/components/ui/textarea';
import { cn } from '@/lib/utils';

import { getToolDisplayName } from '../../../utils/toolUtils';
import NodeDocumentsControl from '../components/NodeDocumentsControl';
import PromptTextArea from '../components/PromptTextArea';
import {
  DEFAULT_FILE_PASSING,
  FILE_PASSING_OPTIONS,
  FilePassing,
  normalizeFilePassing,
} from '../documentConfig';
import { NO_ESCAPE, schemaErrorText, type UserTool } from '../workflowHelpers';
import { type NodePanelBodyProps } from './types';

import type { Model } from '../../../models/types';

interface AgentPanelProps extends NodePanelBodyProps {
  nodes: Node[];
  edges: Edge[];
  availableModels: Model[];
  availableTools: UserTool[];
  sourceOptions: { value: string; label: string }[];
  /** Upstream file variables the agent can read. */
  documentOptions: { value: string; label: string }[];
  /** The structured-output schema as typed. */
  jsonSchemaText: string;
  /** The schema's validation fragment, or null. */
  jsonSchemaError: string | null;
  /** False when the picked model can't return structured output. */
  modelSupportsStructuredOutput: boolean;
  onJsonSchemaChange: (text: string) => void;
}

const SCHEMA_PLACEHOLDER = `{
  "type": "object",
  "properties": {
    "summary": { "type": "string" }
  },
  "required": ["summary"]
}`;

/**
 * Whether any advanced setting (documents, file passing, structured output)
 * differs from its default, so the disclosure opens on its own.
 *
 * Args:
 *   config: The agent node's config.
 *   jsonSchemaText: The schema as typed.
 *   jsonSchemaError: The schema's validation fragment, or null.
 *
 * Returns:
 *   True when the advanced settings should start open.
 */
export function hasAdvancedAgentSettings(
  config: Record<string, unknown> | undefined,
  jsonSchemaText: string,
  jsonSchemaError: string | null,
): boolean {
  const inputDocuments = config?.input_documents;
  return (
    (Array.isArray(inputDocuments) && inputDocuments.length > 0) ||
    normalizeFilePassing(config?.file_passing) !== DEFAULT_FILE_PASSING ||
    (config?.json_schema !== undefined && config?.json_schema !== null) ||
    jsonSchemaText.trim() !== '' ||
    Boolean(jsonSchemaError)
  );
}

/**
 * Settings for an AI Agent node, grouped Model, Prompt, Knowledge and Output
 * like classic Overview, with documents, file passing and structured output
 * under an Advanced settings disclosure.
 */
export default function AgentPanel({
  node,
  onUpdate,
  nodes,
  edges,
  availableModels,
  availableTools,
  sourceOptions,
  documentOptions,
  jsonSchemaText,
  jsonSchemaError,
  modelSupportsStructuredOutput,
  onJsonSchemaChange,
}: AgentPanelProps) {
  const { t } = useTranslation();
  const streamId = useId();
  const config = node.data.config || {};
  const [advancedOpen, setAdvancedOpen] = useState(() =>
    hasAdvancedAgentSettings(config, jsonSchemaText, jsonSchemaError),
  );

  const updateConfig = (patch: Record<string, unknown>) =>
    onUpdate({ config: { ...(node.data.config || {}), ...patch } });

  const builtinModels = availableModels.filter((m) => m.source !== 'user');
  const userModels = availableModels.filter((m) => m.source === 'user');
  const schemaInvalid = jsonSchemaText.trim() !== '' && jsonSchemaError;

  return (
    <div className="flex flex-col gap-6">
      <section className="flex flex-col gap-5">
        <SectionHeader
          as="h3"
          size="xs"
          title={t('agents.form.sections.model')}
        />
        <div className="flex flex-col gap-5">
          <FormField
            label={t('agents.workflow.builder.agentType')}
            labelSurface="background"
          >
            <Select
              value={config.agent_type || 'classic'}
              onValueChange={(value) => updateConfig({ agent_type: value })}
            >
              <SelectTrigger size="field" className="w-full">
                <SelectValue
                  placeholder={t(
                    'agents.workflow.builder.agentTypePlaceholder',
                  )}
                />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="classic">
                  {t('agents.form.agentTypes.classic')}
                </SelectItem>
                <SelectItem value="research">
                  {t('agents.form.agentTypes.research')}
                </SelectItem>
              </SelectContent>
            </Select>
          </FormField>
          <FormField
            label={t('agents.workflow.builder.model')}
            labelSurface="background"
          >
            <Select
              value={config.model_id || ''}
              onValueChange={(value) =>
                updateConfig({
                  model_id: value,
                  llm_name:
                    availableModels.find((m) => m.id === value)?.provider || '',
                })
              }
            >
              <SelectTrigger size="field" className="w-full">
                <SelectValue
                  placeholder={t('agents.workflow.builder.modelPlaceholder')}
                />
              </SelectTrigger>
              <SelectContent>
                {builtinModels.length > 0 && (
                  <SelectGroup>
                    <SelectLabel>
                      {t('settings.customModels.modelsGroup.builtin')}
                    </SelectLabel>
                    {builtinModels.map((model) => (
                      <SelectItem key={model.id} value={model.id}>
                        {model.display_name} · {model.provider}
                      </SelectItem>
                    ))}
                  </SelectGroup>
                )}
                {userModels.length > 0 && (
                  <SelectGroup>
                    <SelectLabel>
                      {t('settings.customModels.modelsGroup.user')}
                    </SelectLabel>
                    {userModels.map((model) => (
                      <SelectItem key={model.id} value={model.id}>
                        {model.display_name} · {model.provider}
                      </SelectItem>
                    ))}
                  </SelectGroup>
                )}
              </SelectContent>
            </Select>
          </FormField>
        </div>
      </section>

      <section className="flex flex-col gap-5">
        <SectionHeader
          as="h3"
          size="xs"
          title={t('agents.form.sections.prompt')}
        />
        <FormField
          label={t('agents.workflow.builder.systemPrompt')}
          labelSurface="background"
        >
          <Textarea
            value={config.system_prompt ?? ''}
            onChange={(e) => updateConfig({ system_prompt: e.target.value })}
            rows={3}
            placeholder={t('agents.workflow.builder.systemPromptPlaceholder')}
          />
        </FormField>
        <PromptTextArea
          label={t('agents.workflow.builder.promptTemplate')}
          labelSurface="background"
          value={config.prompt_template || ''}
          onChange={(val) => updateConfig({ prompt_template: val })}
          nodes={nodes}
          edges={edges}
          selectedNodeId={node.id}
          placeholder={t('agents.workflow.builder.promptTemplatePlaceholder', {
            ...NO_ESCAPE,
            example: '{{ agent.variable }}',
          })}
        />
      </section>

      <section className="flex flex-col gap-5">
        <SectionHeader
          as="h3"
          size="xs"
          title={t('agents.workflow.builder.knowledge')}
        />
        <FormField
          label={t('agents.workflow.builder.sources')}
          labelSurface="background"
        >
          <MultiSelect
            options={sourceOptions}
            selected={config.sources || []}
            onChange={(newSources) => updateConfig({ sources: newSources })}
            placeholder={t('agents.form.placeholders.selectSources')}
            searchPlaceholder={t('agents.form.sourcePopup.searchPlaceholder')}
            emptyText={t('agents.form.sourcePopup.noOptionsMessage')}
          />
        </FormField>
        <FormField
          label={t('agents.form.sections.tools')}
          labelSurface="background"
        >
          <MultiSelect
            options={availableTools.map((tool) => ({
              value: tool.id,
              label: getToolDisplayName(tool),
            }))}
            selected={config.tools || []}
            onChange={(newTools) => updateConfig({ tools: newTools })}
            placeholder={t('agents.form.placeholders.selectTools')}
            searchPlaceholder={t('agents.form.toolsPopup.searchPlaceholder')}
            emptyText={t('agents.form.toolsPopup.noOptionsMessage')}
          />
        </FormField>
      </section>

      <section className="flex flex-col gap-5">
        <SectionHeader
          as="h3"
          size="xs"
          title={t('agents.workflow.builder.output')}
        />
        <FormField
          label={t('agents.workflow.builder.outputVariable')}
          labelSurface="background"
        >
          <Input
            type="text"
            value={config.output_variable || ''}
            onChange={(e) => updateConfig({ output_variable: e.target.value })}
            placeholder={t('agents.workflow.builder.outputVariablePlaceholder')}
          />
        </FormField>
        <SettingRows>
          <SettingRow
            label={t('agents.workflow.builder.streamToUser')}
            description={t('agents.workflow.builder.streamToUserDescription')}
            htmlFor={streamId}
          >
            <Switch
              id={streamId}
              checked={config.stream_to_user ?? true}
              onCheckedChange={(checked) =>
                updateConfig({ stream_to_user: checked })
              }
            />
          </SettingRow>
        </SettingRows>
      </section>

      <div className="flex flex-col gap-5">
        <Button
          type="button"
          variant="link"
          size="sm"
          aria-expanded={advancedOpen}
          onClick={() => setAdvancedOpen((open) => !open)}
          className="-ml-3 w-fit justify-start"
        >
          <ChevronRight
            aria-hidden="true"
            className={cn(
              'transition-transform duration-200',
              advancedOpen && 'rotate-90',
            )}
          />
          {t('agents.workflow.builder.advancedSettings')}
        </Button>
        {advancedOpen && (
          <div className="flex flex-col gap-5">
            <NodeDocumentsControl
              key={node.id}
              value={config.input_documents ?? []}
              onChange={(nextInputDocuments) =>
                updateConfig({ input_documents: nextInputDocuments })
              }
              options={documentOptions}
              label={t('agents.workflow.builder.documents')}
              helpText={t('agents.workflow.builder.documentsHint')}
            />
            <FormField
              label={t('agents.workflow.builder.filePassing')}
              hint={t('agents.workflow.builder.filePassingHint')}
              labelSurface="background"
            >
              <Select
                value={normalizeFilePassing(config.file_passing)}
                onValueChange={(value) =>
                  updateConfig({ file_passing: value as FilePassing })
                }
              >
                <SelectTrigger size="field" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {FILE_PASSING_OPTIONS.map((option) => (
                    <SelectItem key={option.value} value={option.value}>
                      {t(`agents.workflow.filePassing.${option.value}`, {
                        defaultValue: option.label,
                      })}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </FormField>
            <FormField
              label={t('agents.workflow.builder.structuredOutput')}
              labelSurface="background"
              hint={
                [
                  !modelSupportsStructuredOutput
                    ? t('agents.workflow.builder.modelNoStructuredOutput')
                    : null,
                  jsonSchemaText.trim() !== '' && !jsonSchemaError
                    ? t('agents.workflow.builder.validSchema')
                    : null,
                ]
                  .filter(Boolean)
                  .join(' ') || undefined
              }
              error={
                schemaInvalid
                  ? t('agents.workflow.builder.invalidSchema', {
                      ...NO_ESCAPE,
                      error: schemaErrorText(t, jsonSchemaError),
                    })
                  : undefined
              }
            >
              <Textarea
                value={jsonSchemaText}
                onChange={(e) => onJsonSchemaChange(e.target.value)}
                className="font-mono"
                rows={4}
                placeholder={SCHEMA_PLACEHOLDER}
              />
            </FormField>
          </div>
        )}
      </div>
    </div>
  );
}
