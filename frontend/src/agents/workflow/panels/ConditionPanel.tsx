import { Plus, Trash2 } from 'lucide-react';
import { Trans, useTranslation } from 'react-i18next';

import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { FormField } from '@/components/ui/form-field';
import { IconButton } from '@/components/ui/icon-button';
import { Input } from '@/components/ui/input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { SectionHeader } from '@/components/ui/section-header';
import { Textarea } from '@/components/ui/textarea';
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';

import { type Edge, type Node } from 'reactflow';

import {
  ConditionCase,
  type ConditionMode,
  type RetryConfig,
} from '../../types/workflow';
import NodeRetryControl from '../components/NodeRetryControl';
import PromptTextArea from '../components/PromptTextArea';
import { effectiveRetry } from '../retryConfig';
import { buildSimpleCel, parseSimpleCel } from '../simpleCel';
import {
  getNextConditionHandle,
  NO_ESCAPE,
  normalizeConditionCases,
} from '../workflowHelpers';
import { type NodePanelBodyProps } from './types';

interface ConditionPanelProps extends NodePanelBodyProps {
  /** Drop the edges leaving the node from a removed case's handle. */
  onRemoveBranch: (sourceHandle: string) => void;
  /** The graph, for the variables an AI decision's input can read. */
  nodes: Node[];
  edges: Edge[];
  /** The workflow's retry defaults, which the node's own retry falls back to. */
  retryDefaults?: RetryConfig | null;
}

/**
 * Settings for an If / Else node: Simple, Advanced or AI mode, then one row
 * box per case (If, Else if, …, or an AI decision's branches) and an add
 * button.
 */
export default function ConditionPanel({
  node,
  onUpdate,
  onRemoveBranch,
  nodes,
  edges,
  retryDefaults = null,
}: ConditionPanelProps) {
  const { t } = useTranslation();
  const config = node.data.config || {};
  const mode: ConditionMode =
    config.mode === 'advanced' || config.mode === 'ai' ? config.mode : 'simple';
  const isAi = mode === 'ai';
  const cases: ConditionCase[] = config.cases || [];

  const updateConfig = (patch: Record<string, unknown>) =>
    onUpdate({ config: { ...(node.data.config || {}), ...patch } });

  const updateCase = (idx: number, patch: Partial<ConditionCase>) => {
    const next = [...cases];
    next[idx] = { ...next[idx], ...patch };
    updateConfig({ cases: next });
  };

  const removeCase = (idx: number) => {
    const next = normalizeConditionCases([...cases]);
    const removedHandle = next[idx]?.sourceHandle;
    next.splice(idx, 1);
    updateConfig({ cases: next });
    if (removedHandle) onRemoveBranch(removedHandle);
  };

  const addCase = () => {
    const next = normalizeConditionCases([...cases]);
    next.push({
      name: '',
      expression: '',
      sourceHandle: getNextConditionHandle(next),
    });
    updateConfig({ cases: next });
  };

  return (
    <div className="flex flex-col gap-5">
      <p className="text-muted-foreground text-sm">
        {isAi
          ? t('agents.workflow.builder.aiIntro')
          : t('agents.workflow.builder.conditionIntro')}
      </p>
      <ToggleGroup
        type="single"
        size="xs"
        fill
        value={mode}
        onValueChange={(next) => next && updateConfig({ mode: next })}
        aria-label={t('agents.workflow.builder.conditionMode')}
      >
        <ToggleGroupItem value="simple">
          {t('agents.workflow.builder.modeSimple')}
        </ToggleGroupItem>
        <ToggleGroupItem value="advanced">
          {t('agents.workflow.builder.modeAdvanced')}
        </ToggleGroupItem>
        <ToggleGroupItem value="ai">
          {t('agents.workflow.builder.modeAi')}
        </ToggleGroupItem>
      </ToggleGroup>

      {isAi && (
        <>
          <PromptTextArea
            label={t('agents.workflow.builder.aiInput')}
            labelSurface="background"
            value={config.prompt_template || ''}
            onChange={(value) => updateConfig({ prompt_template: value })}
            nodes={nodes}
            edges={edges}
            selectedNodeId={node.id}
            rows={2}
            placeholder={t('agents.workflow.builder.aiInputPlaceholder', {
              ...NO_ESCAPE,
              example: '{{ agent.query }}',
            })}
          />
          <FormField
            label={t('agents.workflow.builder.aiInstructions')}
            labelSurface="background"
          >
            <Textarea
              value={config.instructions || ''}
              onChange={(e) => updateConfig({ instructions: e.target.value })}
              rows={2}
              placeholder={t(
                'agents.workflow.builder.aiInstructionsPlaceholder',
              )}
            />
          </FormField>
        </>
      )}

      {cases.map((c, idx) => {
        const parsed = parseSimpleCel(c.expression);
        return (
          <Card
            key={c.sourceHandle}
            variant="subtle"
            padding="sm"
            className="gap-4"
          >
            <div className="flex items-center gap-2">
              <span
                aria-hidden="true"
                className="bg-warning size-2 shrink-0 rounded-full"
              />
              <SectionHeader
                as="h4"
                size="xs"
                className="flex-1"
                title={
                  isAi
                    ? t('agents.workflow.nodes.branch', { index: idx + 1 })
                    : idx === 0
                      ? t('agents.workflow.nodes.if')
                      : t('agents.workflow.nodes.elseIf')
                }
              />
              {cases.length > 1 && (
                <IconButton
                  variant="ghost-destructive"
                  size="icon-xs"
                  label={
                    isAi
                      ? t('agents.workflow.removeBranch', { index: idx + 1 })
                      : t('agents.workflow.removeCondition', {
                          index: idx + 1,
                        })
                  }
                  icon={Trash2}
                  onClick={() => removeCase(idx)}
                />
              )}
            </div>
            <FormField
              label={t('agents.workflow.builder.branchName')}
              labelSurface="background"
            >
              <Input
                type="text"
                value={c.name || ''}
                onChange={(e) => updateCase(idx, { name: e.target.value })}
                placeholder={
                  isAi
                    ? t('agents.workflow.builder.branchNamePlaceholder')
                    : t('agents.workflow.builder.caseNamePlaceholder')
                }
              />
            </FormField>
            {isAi ? (
              <FormField
                label={t('agents.workflow.builder.branchDescription')}
                labelSurface="background"
              >
                <Textarea
                  value={c.description || ''}
                  onChange={(e) =>
                    updateCase(idx, { description: e.target.value })
                  }
                  rows={2}
                  placeholder={t(
                    'agents.workflow.builder.branchDescriptionPlaceholder',
                  )}
                />
              </FormField>
            ) : mode === 'simple' ? (
              <>
                <FormField
                  label={t('agents.workflow.builder.variable')}
                  labelSurface="background"
                >
                  <Input
                    type="text"
                    className="font-mono"
                    value={parsed.variable}
                    onChange={(e) =>
                      updateCase(idx, {
                        expression: buildSimpleCel(
                          e.target.value,
                          parsed.operator,
                          parsed.value,
                        ),
                      })
                    }
                    placeholder={t(
                      'agents.workflow.builder.variablePlaceholder',
                    )}
                  />
                </FormField>
                <div className="flex gap-2">
                  <FormField
                    label={t('agents.workflow.builder.operator')}
                    labelSurface="background"
                    className="w-32 shrink-0"
                  >
                    <Select
                      value={parsed.operator}
                      onValueChange={(op) =>
                        updateCase(idx, {
                          expression: buildSimpleCel(
                            parsed.variable,
                            op,
                            parsed.value,
                          ),
                        })
                      }
                    >
                      <SelectTrigger size="field" className="w-full">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="==">=</SelectItem>
                        <SelectItem value="!=">!=</SelectItem>
                        <SelectItem value=">">&gt;</SelectItem>
                        <SelectItem value="<">&lt;</SelectItem>
                        <SelectItem value=">=">&gt;=</SelectItem>
                        <SelectItem value="<=">&lt;=</SelectItem>
                        <SelectItem value="contains">
                          {t('agents.workflow.builder.opContains')}
                        </SelectItem>
                        <SelectItem value="startsWith">
                          {t('agents.workflow.builder.opStartsWith')}
                        </SelectItem>
                      </SelectContent>
                    </Select>
                  </FormField>
                  <FormField
                    label={t('agents.workflow.builder.value')}
                    labelSurface="background"
                    className="min-w-0 flex-1"
                  >
                    <Input
                      type="text"
                      value={parsed.value}
                      onChange={(e) =>
                        updateCase(idx, {
                          expression: buildSimpleCel(
                            parsed.variable,
                            parsed.operator,
                            e.target.value,
                          ),
                        })
                      }
                      placeholder={t(
                        'agents.workflow.builder.valuePlaceholder',
                      )}
                    />
                  </FormField>
                </div>
              </>
            ) : (
              <FormField
                label={t('agents.workflow.conditionRow', { index: idx + 1 })}
                labelSurface="background"
                hint={
                  <>
                    <Trans
                      i18nKey="agents.workflow.builder.celHint"
                      components={{ code: <code /> }}
                      values={{ braced: '{{query}}' }}
                    />{' '}
                    <Button variant="link" size="text" asChild>
                      <a
                        href="https://cel.dev/"
                        target="_blank"
                        rel="noreferrer"
                      >
                        {t('agents.workflow.builder.learnMore')}
                      </a>
                    </Button>
                  </>
                }
              >
                <Textarea
                  value={c.expression}
                  onChange={(e) =>
                    updateCase(idx, { expression: e.target.value })
                  }
                  rows={2}
                  placeholder={t(
                    'agents.workflow.builder.conditionPlaceholder',
                  )}
                />
              </FormField>
            )}
          </Card>
        );
      })}

      <Button
        type="button"
        variant="outline"
        size="sm"
        shape="pill"
        onClick={addCase}
        className="self-start"
      >
        <Plus />
        {isAi
          ? t('agents.workflow.builder.addBranch')
          : t('agents.workflow.builder.addCondition')}
      </Button>

      {isAi && (
        <>
          <FormField
            label={t('agents.workflow.builder.outputVariable')}
            labelSurface="background"
            hint={t('agents.workflow.builder.aiOutputHint')}
          >
            <Input
              type="text"
              value={config.output_variable || ''}
              onChange={(e) =>
                updateConfig({ output_variable: e.target.value })
              }
              placeholder={t(
                'agents.workflow.builder.outputVariablePlaceholder',
              )}
            />
          </FormField>
          <FormField
            label={t('agents.workflow.builder.minConfidence')}
            labelSurface="background"
            hint={t('agents.workflow.builder.minConfidenceHint')}
          >
            <Input
              type="number"
              min={0}
              max={1}
              step={0.05}
              value={config.min_confidence ?? ''}
              onChange={(e) =>
                updateConfig({
                  min_confidence:
                    e.target.value === '' ? undefined : Number(e.target.value),
                })
              }
              placeholder="0"
            />
          </FormField>
          <NodeRetryControl
            key={node.id}
            value={config.retry}
            onChange={(retry) => updateConfig({ retry })}
            inherited={effectiveRetry(undefined, retryDefaults)}
          />
        </>
      )}
    </div>
  );
}
