import { Copy, Trash2, X } from 'lucide-react';
import { type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { type Node } from 'reactflow';

import { Badge } from '@/components/ui/badge';
import { ActionMenu } from '@/components/ui/dropdown-menu';
import { FormField } from '@/components/ui/form-field';
import { IconButton } from '@/components/ui/icon-button';
import { Input } from '@/components/ui/input';
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
 * The node settings column docked at the canvas's right edge: a header with
 * the type's icon, the node's title, its type and id, a ⋯ menu (Duplicate,
 * Delete node; none for Start) and close, then the one scrolling body.
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
    <aside className="bg-background border-border flex w-96 shrink-0 flex-col border-l">
      <header className="border-border flex items-start gap-3 border-b px-4 py-3">
        <span
          className={cn(
            'flex size-8 shrink-0 items-center justify-center rounded-md',
            nodeToneClass(node.type),
          )}
        >
          {Icon && <Icon className="size-4" aria-hidden="true" />}
        </span>
        <div className="flex min-w-0 flex-1 flex-col">
          <div className="flex min-w-0 items-center gap-2">
            <h2
              className="text-foreground truncate text-sm font-semibold"
              title={title}
            >
              {title}
            </h2>
            {title !== typeLabel && (
              <Badge variant="neutral">{typeLabel}</Badge>
            )}
          </div>
          <div className="flex min-w-0 items-center gap-1">
            <span
              className="text-muted-foreground truncate font-mono text-xs"
              title={node.id}
            >
              {node.id}
            </span>
            <CopyButton
              textToCopy={node.id}
              size="xs"
              copyLabel={t('agents.workflow.builder.copyNodeId')}
              side="bottom"
            />
          </div>
        </div>
        {node.type !== 'start' && (
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
        )}
        <IconButton
          variant="ghost-muted"
          size="icon-sm"
          side="bottom"
          onClick={onClose}
          label={t('agents.close')}
          icon={X}
        />
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="flex flex-col gap-6 p-4">
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
        </div>
      </div>
    </aside>
  );
}
