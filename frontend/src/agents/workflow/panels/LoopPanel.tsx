import { useTranslation } from 'react-i18next';

import { FormField } from '@/components/ui/form-field';
import { Input } from '@/components/ui/input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';

import { LoopNodeConfig } from '../../types/workflow';
import { isValidItemsPath, isValidItemVariable } from '../loopNodeConfig';
import { NO_ESCAPE } from '../workflowHelpers';
import { type NodePanelBodyProps } from './types';

function parsePositive(raw: string): number | undefined {
  const parsed = Number.parseInt(raw, 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : undefined;
}

/**
 * Settings for a Loop node: the state list it reads, the item's name inside
 * the body, how many items run at once, what a failed item does, and where
 * the results go.
 */
export default function LoopPanel({ node, onUpdate }: NodePanelBodyProps) {
  const { t } = useTranslation();
  const config: Partial<LoopNodeConfig> = node.data.config || {};
  const update = (patch: Partial<LoopNodeConfig>) =>
    onUpdate({ config: { ...config, ...patch } });

  const items = config.items ?? '';
  const itemVariable = config.item_variable ?? 'item';

  return (
    <div className="flex flex-col gap-5">
      <p className="text-muted-foreground text-sm">
        {t('agents.workflow.builder.loopIntro')}
      </p>
      <FormField
        labelSurface="background"
        label={t('agents.workflow.builder.loopItems')}
        hint={t('agents.workflow.builder.loopItemsHint')}
        error={
          items.trim() && !isValidItemsPath(items)
            ? t('agents.workflow.builder.loopItemsInvalid')
            : undefined
        }
      >
        <Input
          type="text"
          className="font-mono"
          value={items}
          onChange={(e) => update({ items: e.target.value })}
          placeholder={t('agents.workflow.builder.examplePlaceholder', {
            ...NO_ESCAPE,
            example: 'extracted.items',
          })}
        />
      </FormField>
      <FormField
        labelSurface="background"
        label={t('agents.workflow.builder.loopItemVariable')}
        hint={t('agents.workflow.builder.loopItemVariableHint', {
          ...NO_ESCAPE,
          example: `{{ ${itemVariable || 'item'} }}`,
        })}
        error={
          isValidItemVariable(itemVariable)
            ? undefined
            : t('agents.workflow.builder.loopItemVariableInvalid')
        }
      >
        <Input
          type="text"
          className="font-mono"
          value={itemVariable}
          onChange={(e) => update({ item_variable: e.target.value })}
        />
      </FormField>
      <div className="flex gap-3">
        <FormField
          labelSurface="background"
          label={t('agents.workflow.builder.loopConcurrency')}
          className="flex-1"
        >
          <Input
            type="number"
            min={1}
            value={config.concurrency ?? ''}
            onChange={(e) =>
              update({ concurrency: parsePositive(e.target.value) })
            }
          />
        </FormField>
        <FormField
          labelSurface="background"
          label={t('agents.workflow.builder.loopMaxItems')}
          className="flex-1"
        >
          <Input
            type="number"
            min={1}
            value={config.max_items ?? ''}
            onChange={(e) =>
              update({ max_items: parsePositive(e.target.value) })
            }
          />
        </FormField>
      </div>
      <FormField
        labelSurface="background"
        label={t('agents.workflow.builder.loopOnError')}
      >
        <Select
          value={config.on_item_error ?? 'fail'}
          onValueChange={(value) =>
            update({ on_item_error: value as LoopNodeConfig['on_item_error'] })
          }
        >
          <SelectTrigger size="field" className="w-full">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="fail">
              {t('agents.workflow.builder.loopOnErrorFail')}
            </SelectItem>
            <SelectItem value="skip">
              {t('agents.workflow.builder.loopOnErrorSkip')}
            </SelectItem>
            <SelectItem value="collect">
              {t('agents.workflow.builder.loopOnErrorCollect')}
            </SelectItem>
          </SelectContent>
        </Select>
      </FormField>
      <FormField
        labelSurface="background"
        label={t('agents.workflow.builder.outputVariable')}
        hint={t('agents.workflow.builder.loopOutputHint')}
      >
        <Input
          type="text"
          value={config.output_variable || ''}
          onChange={(e) => update({ output_variable: e.target.value })}
          placeholder={t('agents.workflow.builder.outputVariablePlaceholder')}
        />
      </FormField>
      <FormField
        labelSurface="background"
        label={t('agents.workflow.builder.loopResultVariable')}
        hint={t('agents.workflow.builder.loopResultVariableHint')}
      >
        <Input
          type="text"
          className="font-mono"
          value={config.result_variable || ''}
          onChange={(e) =>
            update({ result_variable: e.target.value || undefined })
          }
          placeholder={t('agents.workflow.builder.optional')}
        />
      </FormField>
    </div>
  );
}
