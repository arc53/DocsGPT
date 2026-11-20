import { FileSearch, Globe, LifeBuoy, type LucideIcon } from 'lucide-react';

import type { Question } from '../components/QuestionCards';

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

/**
 * What each starting point asks before Basics, the questions its brief has
 * the drafter ask first (agent_instructions.py `STARTERS`): shown at once,
 * without a turn. A question with no options takes a typed answer; the
 * wording is `drafter.starters.<id>.ask.<question>`.
 */
const STARTER_ASKS: Record<
  DrafterStarter,
  { id: string; multi: boolean; options: string[]; typed?: boolean }[]
> = {
  website: [{ id: 'company', multi: false, options: [], typed: true }],
  helpdesk: [
    { id: 'areas', multi: true, options: ['hr', 'it', 'policies', 'office'] },
  ],
  research: [
    {
      id: 'documents',
      multi: true,
      options: ['contracts', 'reports', 'papers', 'cases'],
    },
    { id: 'users', multi: false, options: ['me', 'team', 'clients'] },
  ],
};

/**
 * A starting point's first questions, in the UI language.
 *
 * Args:
 *   starter: The starting point.
 *   t: The translator.
 *
 * Returns:
 *   The questions, as the drafter's own rounds are shaped.
 */
export function starterQuestions(
  starter: DrafterStarter,
  t: (key: string) => string,
): Question[] {
  return STARTER_ASKS[starter].map(({ id, multi, options, typed }) => {
    const base = `drafter.starters.${starter}.ask.${id}`;
    return {
      id,
      text: t(`${base}.text`),
      note: null,
      multi,
      options: options.map((option) => ({
        id: option,
        label: t(`${base}.options.${option}`),
      })),
      ...(typed ? { placeholder: t(`${base}.placeholder`) } : {}),
    };
  });
}
