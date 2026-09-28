import {
  Bot,
  CodeXml,
  Database,
  Flag,
  GitBranch,
  Play,
  StickyNote,
  type LucideIcon,
} from 'lucide-react';

/** The node types the builder draws. */
export type WorkflowNodeType =
  'start' | 'agent' | 'end' | 'note' | 'state' | 'condition' | 'code';

/** A node's colour role: the brand tint or one status tint. */
export type NodeTone = 'primary' | 'success' | 'warning' | 'info';

/**
 * One colour per node type, read by the palette, every canvas node and the
 * settings panel's header. Start and End share `success` as the two ends of
 * the flow; `destructive` is kept for errors, so End is never red.
 */
export const NODE_TONES: Record<WorkflowNodeType, NodeTone> = {
  start: 'success',
  agent: 'primary',
  end: 'success',
  note: 'warning',
  state: 'info',
  condition: 'warning',
  code: 'info',
};

// Whole class strings per tone so Tailwind sees them. Brand is the soft
// `secondary` fill (never bg-primary/10); status tones are the /10 fill.
export const TONE_CLASSES: Record<NodeTone, string> = {
  primary: 'bg-secondary text-secondary-foreground',
  success: 'bg-success/10 text-success',
  warning: 'bg-warning/10 text-warning',
  info: 'bg-info/10 text-info',
};

const NEUTRAL_TONE_CLASS = 'bg-muted-foreground/15 text-muted-foreground';

/**
 * The icon-square classes for a node type.
 *
 * Args:
 *   type: The node's type.
 *
 * Returns:
 *   The tone's fill and text classes, or a neutral tint for an unknown type.
 */
export function nodeToneClass(type: string | undefined): string {
  const tone = NODE_TONES[type as WorkflowNodeType];
  return tone ? TONE_CLASSES[tone] : NEUTRAL_TONE_CLASS;
}

/** Each node type's icon and its name's locale key. */
export const NODE_META: Record<
  WorkflowNodeType,
  { icon: LucideIcon; labelKey: string }
> = {
  start: { icon: Play, labelKey: 'agents.workflow.nodes.start' },
  agent: { icon: Bot, labelKey: 'agents.workflow.builder.aiAgent' },
  end: { icon: Flag, labelKey: 'agents.workflow.nodes.end' },
  note: { icon: StickyNote, labelKey: 'agents.workflow.nodes.note' },
  state: { icon: Database, labelKey: 'agents.workflow.nodes.setState' },
  condition: { icon: GitBranch, labelKey: 'agents.workflow.nodes.condition' },
  code: { icon: CodeXml, labelKey: 'agents.workflow.nodes.code' },
};
