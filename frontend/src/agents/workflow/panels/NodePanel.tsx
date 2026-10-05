import { Copy, Trash2 } from 'lucide-react';
import { Fragment, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { type Node } from 'reactflow';

import { ActionMenu } from '@/components/ui/dropdown-menu';
import { FormField } from '@/components/ui/form-field';
import { Input } from '@/components/ui/input';
import { PanelBody, PanelHeader, SidePanel } from '@/components/ui/side-panel';
import { cn } from '@/lib/utils';

import CopyButton from '../../../components/CopyButton';
import { NODE_META, nodeToneClass, type WorkflowNodeType } from '../nodeTones';

interface NodePanelProps {
  /** The node being edited. */
  node: Node;
  onClose: () => void;
  onDuplicate: () => void;
  onDelete: () => void;
  /** Merge fields into the node's data (used by the title field). */
  onUpdate: (data: Record<string, unknown>) => void;
  /** The type's own settings (AgentPanel, ConditionPanel, …). */
  children?: ReactNode;
}

// Start and End have fixed names and no settings of their own.
const FIXED_TYPES = new Set(['start', 'end']);

const FIXED_HINT_KEYS: Record<string, string> = {
  start: 'agents.workflow.nodes.startHint',
  end: 'agents.workflow.nodes.endHint',
};

/**
 * A node's settings, docked beside the canvas (DESIGN.md "Side panels"): the
 * type's tile, the node's title, its type and id, a ⋯ menu (Duplicate,
 * Delete node; none for Start), Expand and close, then the one scrolling body.
 * Its host is the builder's `relative flex` row.
 */
export default function NodePanel({
  node,
  onClose,
  onDuplicate,
  onDelete,
  onUpdate,
  children,
}: NodePanelProps) {
  const { t } = useTranslation();
  const meta = NODE_META[node.type as WorkflowNodeType];
  const Icon = meta?.icon;
  const typeLabel = meta ? t(meta.labelKey) : (node.type ?? '');
  const fixed = FIXED_TYPES.has(node.type ?? '');
  const title = fixed
    ? typeLabel
    : node.data.title || node.data.label || typeLabel;

  return (
    <SidePanel
      variant="docked"
      expandable="workflow-node"
      open
      onOpenChange={(open) => !open && onClose()}
    >
      {/* Keyed per node, so switching nodes resets the type's fields but
          doesn't replay the panel's entrance. */}
      <Fragment key={node.id}>
        <PanelHeader
          title={title}
          leading={
            <span
              className={cn(
                'flex size-8 shrink-0 items-center justify-center rounded-md',
                nodeToneClass(node.type),
              )}
            >
              {Icon && <Icon className="size-4" aria-hidden="true" />}
            </span>
          }
          description={
            <span className="flex min-w-0 items-center gap-1">
              <span className="shrink-0">{typeLabel}</span>
              <span aria-hidden="true">·</span>
              <span className="truncate font-mono text-xs" title={node.id}>
                {node.id}
              </span>
              <CopyButton
                textToCopy={node.id}
                size="xs"
                copyLabel={t('agents.workflow.builder.copyNodeId')}
                side="bottom"
              />
            </span>
          }
          actions={
            node.type !== 'start' ? (
              <ActionMenu
                size="toolbar"
                triggerLabel={t('agents.workflow.builder.nodeActions')}
                options={[
                  {
                    label: t('agents.workflow.builder.duplicateNode'),
                    icon: Copy,
                    onClick: onDuplicate,
                  },
                  {
                    label: t('agents.workflow.builder.deleteNode'),
                    icon: Trash2,
                    variant: 'destructive',
                    onClick: onDelete,
                  },
                ]}
              />
            ) : null
          }
        />
        <PanelBody>
          {fixed ? (
            <p className="text-muted-foreground text-sm">
              {t(FIXED_HINT_KEYS[node.type ?? ''])}
            </p>
          ) : (
            <FormField
              label={t('agents.workflow.builder.title')}
              labelSurface="background"
            >
              <Input
                type="text"
                value={node.data.title || node.data.label || ''}
                onChange={(e) =>
                  onUpdate({ title: e.target.value, label: e.target.value })
                }
                placeholder={t('agents.workflow.builder.titlePlaceholder')}
              />
            </FormField>
          )}
          {children}
        </PanelBody>
      </Fragment>
    </SidePanel>
  );
}
