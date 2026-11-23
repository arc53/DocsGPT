import { useTranslation } from 'react-i18next';

import { FormField } from '@/components/ui/form-field';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';

import type { RetryConfig } from '../../types/workflow';
import NodeDocumentsControl from '../components/NodeDocumentsControl';
import StreamOutputField from '../components/StreamOutputField';
import NodeRetryControl from '../components/NodeRetryControl';
import { effectiveRetry } from '../retryConfig';
import { NO_ESCAPE, schemaErrorText } from '../workflowHelpers';
import { type NodePanelBodyProps } from './types';

interface CodePanelProps extends NodePanelBodyProps {
  /** Upstream file variables the code can take as inputs. */
  documentOptions: { value: string; label: string }[];
  /** The structured-output schema as typed. */
  jsonSchemaText: string;
  /** The schema's validation fragment, or null. */
  jsonSchemaError: string | null;
  onJsonSchemaChange: (text: string) => void;
  /** The workflow's retry defaults, which an unset retry field inherits. */
  retryDefaults?: RetryConfig | null;
}

/**
 * Settings for a Code node: code, inputs, output, schema and retries. A code
 * node retries only sandbox failures, so it has no choice of what to retry.
 */
export default function CodePanel({
  node: selectedNode,
  onUpdate: handleUpdateNodeData,
  documentOptions: selectedCodeDocumentOptions,
  jsonSchemaText: selectedCodeJsonSchemaText,
  jsonSchemaError: selectedCodeJsonSchemaError,
  onJsonSchemaChange: handleCodeJsonSchemaChange,
  retryDefaults = null,
}: CodePanelProps) {
  const { t } = useTranslation();
  return (
    <div className="flex flex-col gap-5">
      <p className="text-muted-foreground text-sm">
        {t('agents.workflow.builder.codeIntro')}
      </p>
      <FormField
        labelSurface="background"
        label={t('agents.workflow.nodes.code')}
      >
        <Textarea
          value={selectedNode.data.config?.code ?? ''}
          onChange={(e) =>
            handleUpdateNodeData({
              config: {
                ...(selectedNode.data.config || {}),
                code: e.target.value,
              },
            })
          }
          className="font-mono"
          rows={10}
          spellCheck={false}
          placeholder={t('agents.workflow.builder.examplePlaceholder', {
            ...NO_ESCAPE,
            example: 'print("hello world")',
          })}
        />
      </FormField>
      <NodeDocumentsControl
        key={selectedNode.id}
        value={selectedNode.data.config?.inputs ?? []}
        onChange={(nextInputs) =>
          handleUpdateNodeData({
            config: {
              ...(selectedNode.data.config || {}),
              inputs: nextInputs,
            },
          })
        }
        options={selectedCodeDocumentOptions}
        label={t('agents.workflow.builder.inputFiles')}
        helpText={t('agents.workflow.builder.inputFilesHint')}
      />
      <FormField
        labelSurface="background"
        label={t('agents.workflow.builder.outputVariable')}
      >
        <Input
          type="text"
          value={selectedNode.data.config?.output_variable || ''}
          onChange={(e) =>
            handleUpdateNodeData({
              config: {
                ...(selectedNode.data.config || {}),
                output_variable: e.target.value,
              },
            })
          }
          placeholder={t('agents.workflow.builder.outputVariablePlaceholder')}
        />
      </FormField>
      <FormField
        labelSurface="background"
        label={t('agents.workflow.builder.timeout')}
      >
        <Input
          type="number"
          min={1}
          value={selectedNode.data.config?.timeout ?? ''}
          onChange={(e) => {
            const raw = e.target.value;
            const parsed =
              raw.trim() === '' ? undefined : Number.parseInt(raw, 10);
            handleUpdateNodeData({
              config: {
                ...(selectedNode.data.config || {}),
                timeout:
                  parsed !== undefined && Number.isFinite(parsed)
                    ? parsed
                    : undefined,
              },
            });
          }}
          placeholder={t('agents.workflow.builder.optional')}
        />
      </FormField>
      <StreamOutputField
        value={selectedNode.data.config?.stream_output}
        onChange={(value) =>
          handleUpdateNodeData({
            config: {
              ...(selectedNode.data.config || {}),
              stream_output: value,
            },
          })
        }
      />
      <FormField
        labelSurface="background"
        label={t('agents.workflow.builder.structuredOutput')}
        hint={
          selectedCodeJsonSchemaText.trim() !== '' &&
          !selectedCodeJsonSchemaError
            ? t('agents.workflow.builder.validSchema')
            : undefined
        }
        error={
          selectedCodeJsonSchemaText.trim() !== '' &&
          selectedCodeJsonSchemaError
            ? t('agents.workflow.builder.invalidSchema', {
                ...NO_ESCAPE,
                error: schemaErrorText(t, selectedCodeJsonSchemaError),
              })
            : undefined
        }
      >
        <Textarea
          value={selectedCodeJsonSchemaText}
          onChange={(e) => handleCodeJsonSchemaChange(e.target.value)}
          className="font-mono"
          rows={6}
          placeholder={`{
  "type": "object",
  "properties": {
    "result": { "type": "string" }
  },
  "required": ["result"]
}`}
        />
      </FormField>
      <NodeRetryControl
        key={selectedNode.id}
        value={selectedNode.data.config?.retry}
        onChange={(retry) =>
          handleUpdateNodeData({
            config: { ...(selectedNode.data.config || {}), retry },
          })
        }
        inherited={effectiveRetry(undefined, retryDefaults)}
      />
    </div>
  );
}
