import { Plus, Trash2 } from 'lucide-react';
import { Trans, useTranslation } from 'react-i18next';

import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { FormField } from '@/components/ui/form-field';
import { IconButton } from '@/components/ui/icon-button';
import { Input } from '@/components/ui/input';
import { SectionHeader } from '@/components/ui/section-header';
import { Textarea } from '@/components/ui/textarea';

import { StateOperationConfig } from '../../types/workflow';
import { NO_ESCAPE } from '../workflowHelpers';
import { type NodePanelBodyProps } from './types';

/**
 * Settings for a Set State node: an intro that explains CEL once, then one
 * numbered row box per assignment (variable, then its CEL value).
 */
export default function StatePanel({ node, onUpdate }: NodePanelBodyProps) {
  const { t } = useTranslation();
  const operations: StateOperationConfig[] = node.data.config?.operations || [];

  const setOperations = (next: StateOperationConfig[]) =>
    onUpdate({ config: { ...(node.data.config || {}), operations: next } });

  const updateOperation = (
    idx: number,
    patch: Partial<StateOperationConfig>,
  ) => {
    const next = [...operations];
    next[idx] = { ...next[idx], ...patch };
    setOperations(next);
  };

  return (
    <div className="flex flex-col gap-5">
      <p className="text-muted-foreground text-sm">
        {t('agents.workflow.builder.stateIntro')}{' '}
        <Trans
          i18nKey="agents.workflow.builder.celHint"
          components={{ code: <code /> }}
          values={{ braced: '{{query}}' }}
        />{' '}
        <Button variant="link" size="inline" asChild>
          <a href="https://cel.dev/" target="_blank" rel="noreferrer">
            {t('agents.workflow.builder.learnMore')}
          </a>
        </Button>
      </p>

      {operations.map((op, idx) => (
        <Card key={idx} variant="subtle" padding="sm" className="gap-4">
          <div className="flex items-center gap-2">
            <SectionHeader
              as="h4"
              size="xs"
              className="flex-1"
              title={t('agents.workflow.builder.assignment', {
                index: idx + 1,
              })}
            />
            {operations.length > 1 && (
              <IconButton
                variant="ghost-destructive"
                size="icon-xs"
                label={t('agents.workflow.removeAssignment', {
                  index: idx + 1,
                })}
                icon={Trash2}
                onClick={() =>
                  setOperations(operations.filter((_, i) => i !== idx))
                }
              />
            )}
          </div>
          <FormField
            label={t('agents.workflow.builder.variable')}
            labelSurface="background"
          >
            <Input
              type="text"
              className="font-mono"
              value={op.target_variable}
              onChange={(e) =>
                updateOperation(idx, { target_variable: e.target.value })
              }
              placeholder={t('agents.workflow.builder.examplePlaceholder', {
                ...NO_ESCAPE,
                example: 'variable_name',
              })}
            />
          </FormField>
          <FormField
            label={t('agents.workflow.builder.valueCel')}
            labelSurface="background"
          >
            <Textarea
              className="font-mono"
              value={op.expression}
              onChange={(e) =>
                updateOperation(idx, { expression: e.target.value })
              }
              rows={2}
              placeholder={t('agents.workflow.builder.examplePlaceholder', {
                ...NO_ESCAPE,
                example: 'query',
              })}
            />
          </FormField>
        </Card>
      ))}

      <Button
        type="button"
        variant="outline"
        size="sm"
        shape="pill"
        onClick={() =>
          setOperations([
            ...operations,
            { expression: '', target_variable: '' },
          ])
        }
        className="self-start"
      >
        <Plus />
        {t('agents.workflow.builder.addAssignment')}
      </Button>
    </div>
  );
}
