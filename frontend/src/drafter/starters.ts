import { FileSearch, Globe, LifeBuoy, type LucideIcon } from 'lucide-react';

/**
 * The drafter's starting points, offered by the prompt drawer and the agent
 * build alike. Each recipe has a brief per id (`STARTERS` in
 * prompt_recipe.py and agent_recipe.py); the rows read
 * `drafter.starters.<id>.title` and `.description`.
 */
export type DrafterStarter = 'website' | 'helpdesk' | 'research';

export const DRAFTER_STARTERS: { key: DrafterStarter; Icon: LucideIcon }[] = [
  { key: 'website', Icon: Globe },
  { key: 'helpdesk', Icon: LifeBuoy },
  { key: 'research', Icon: FileSearch },
];
