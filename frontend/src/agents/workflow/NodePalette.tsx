import { type DragEvent } from 'react';
import { useTranslation } from 'react-i18next';

import { SectionHeader } from '@/components/ui/section-header';
import { cn, focusRing } from '@/lib/utils';

import { NODE_META, nodeToneClass, type WorkflowNodeType } from './nodeTones';

interface PaletteEntry {
  type: WorkflowNodeType;
  group: 'core' | 'logic';
  hintKey?: string;
}

const PALETTE: PaletteEntry[] = [
  { type: 'agent', group: 'core' },
  { type: 'end', group: 'core' },
  { type: 'note', group: 'core' },
  {
    type: 'state',
    group: 'logic',
    hintKey: 'agents.workflow.builder.setStateHint',
  },
  {
    type: 'condition',
    group: 'logic',
    hintKey: 'agents.workflow.builder.conditionHint',
  },
  { type: 'code', group: 'logic', hintKey: 'agents.workflow.builder.codeHint' },
];

const GROUPS: { group: PaletteEntry['group']; titleKey: string }[] = [
  { group: 'core', titleKey: 'agents.workflow.builder.coreNodes' },
  { group: 'logic', titleKey: 'agents.workflow.builder.logicNodes' },
];

interface NodePaletteItemProps {
  entry: PaletteEntry;
  onAdd: (nodeType: WorkflowNodeType) => void;
  onDragStart: (e: DragEvent, nodeType: string) => void;
}

/**
 * A palette pill: drag it onto the canvas, or click (or press Enter) to add
 * the node without dragging.
 *
 * Args:
 *   entry: The palette entry to render.
 *   onAdd: Adds a node of the entry's type beside the selection.
 *   onDragStart: Starts dragging a node of the entry's type onto the canvas.
 */
function NodePaletteItem({ entry, onAdd, onDragStart }: NodePaletteItemProps) {
  const { t } = useTranslation();
  const { icon: Icon, labelKey } = NODE_META[entry.type];
  const label = (
    <span className="text-foreground text-sm font-medium">{t(labelKey)}</span>
  );
  return (
    <button
      type="button"
      draggable
      onDragStart={(e) => onDragStart(e, entry.type)}
      onClick={() => onAdd(entry.type)}
      className={cn(
        'border-border bg-card hover:bg-accent flex cursor-grab items-center gap-3 rounded-full border px-4 py-2.5 text-left transition-colors outline-none',
        focusRing,
      )}
    >
      <span
        className={cn(
          'flex size-8 shrink-0 items-center justify-center rounded-md',
          nodeToneClass(entry.type),
        )}
      >
        <Icon className="size-4.5" aria-hidden="true" />
      </span>
      {entry.hintKey ? (
        <span className="flex flex-col">
          {label}
          <span className="text-muted-foreground text-xs">
            {t(entry.hintKey)}
          </span>
        </span>
      ) : (
        label
      )}
    </button>
  );
}

interface NodePaletteProps {
  /** Adds a node of the given type without dragging (click or Enter). */
  onAdd: (nodeType: WorkflowNodeType) => void;
  /** Starts dragging a node of the given type onto the canvas. */
  onDragStart: (e: DragEvent, nodeType: string) => void;
}

/** The builder's left rail of node types, grouped Core and Logic. */
export default function NodePalette({ onAdd, onDragStart }: NodePaletteProps) {
  const { t } = useTranslation();
  return (
    <div className="border-border bg-background flex w-64 shrink-0 flex-col gap-6 overflow-y-auto border-r p-4">
      {GROUPS.map(({ group, titleKey }) => (
        <div key={group} className="flex flex-col gap-3">
          <SectionHeader as="h3" size="sm" title={t(titleKey)} />
          <div className="flex flex-col gap-2">
            {PALETTE.filter((entry) => entry.group === group).map((entry) => (
              <NodePaletteItem
                key={entry.type}
                entry={entry}
                onAdd={onAdd}
                onDragStart={onDragStart}
              />
            ))}
          </div>
        </div>
      ))}
      <p className="text-muted-foreground text-xs">
        {t('agents.workflow.builder.paletteHint')}
      </p>
    </div>
  );
}
