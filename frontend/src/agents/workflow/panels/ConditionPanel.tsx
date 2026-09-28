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

import { ConditionCase } from '../../types/workflow';
import { buildSimpleCel, parseSimpleCel } from '../simpleCel';
import {
  getNextConditionHandle,
  normalizeConditionCases,
} from '../workflowHelpers';
import { type NodePanelBodyProps } from './types';

interface ConditionPanelProps extends NodePanelBodyProps {
  /** Drop the edges leaving the node from a removed case's handle. */
  onRemoveBranch: (sourceHandle: string) => void;
}

type ConditionMode = 'simple' | 'advanced';

/**
 * Settings for an If / Else node: Simple or Advanced mode, then one row box
 * per case (If, Else if, …) and Add condition.
 */
export default function ConditionPanel({
  node,
  onUpdate,
  onRemoveBranch,
}: ConditionPanelProps) {
  const { t } = useTranslation();
  const config = node.data.config || {};
  const mode: ConditionMode =
    config.mode === 'advanced' ? 'advanced' : 'simple';
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
        {t('agents.workflow.builder.conditionIntro')}
      </p>
      {/* The track is a plain wrapper: ToggleGroup takes layout only. */}
      <div className="bg-muted rounded-full p-1">
        <ToggleGroup
          type="single"
          size="xs"
          value={mode}
          onValueChange={(next) => next && updateConfig({ mode: next })}
          aria-label={t('agents.workflow.builder.conditionMode')}
          className="flex-nowrap"
        >
          <ToggleGroupItem value="simple" className="flex-1">
            {t('agents.workflow.builder.modeSimple')}
          </ToggleGroupItem>
          <ToggleGroupItem value="advanced" className="flex-1">
            {t('agents.workflow.builder.modeAdvanced')}
          </ToggleGroupItem>
        </ToggleGroup>
      </div>

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
                  idx === 0
                    ? t('agents.workflow.nodes.if')
                    : t('agents.workflow.nodes.elseIf')
                }
              />
              {cases.length > 1 && (
                <IconButton
                  variant="ghost-destructive"
                  size="icon-xs"
                  label={t('agents.workflow.removeCondition', {
                    index: idx + 1,
                  })}
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
                placeholder={t('agents.workflow.builder.caseNamePlaceholder')}
              />
            </FormField>
            {mode === 'simple' ? (
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
                    <Button
                      variant="link"
                      size="inline"
                      asChild
                      // eslint-disable-next-line shadcn/no-restyle -- a link in a 12px hint keeps the sentence's size and weight
                      className="text-xs font-normal"
                    >
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
        {t('agents.workflow.builder.addCondition')}
      </Button>
    </div>
  );
}
