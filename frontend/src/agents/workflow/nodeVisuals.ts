import {
  Bot,
  CodeXml,
  Database,
  Flag,
  GitBranch,
  type LucideIcon,
  Play,
  StickyNote,
} from 'lucide-react';

// Components, not elements: the preview's step list draws them at 12px, its
// minimap rows at 14px, and the chat's step rows at 16px.
export const NODE_ICONS: Record<string, LucideIcon> = {
  start: Play,
  agent: Bot,
  end: Flag,
  note: StickyNote,
  state: Database,
  condition: GitBranch,
  code: CodeXml,
};

export const NODE_COLORS: Record<string, string> = {
  start: 'text-success',
  agent: 'text-primary',
  end: 'text-destructive',
  note: 'text-warning',
  state: 'text-info',
  condition: 'text-warning',
  code: 'text-info',
};
