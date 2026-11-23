import { FileSearch, Globe, LifeBuoy, type LucideIcon } from 'lucide-react';

import type { Question } from '../components/QuestionCards';

/**
 * The drafter's starting points, offered by the prompt drawer and the agent
 * build alike. Each recipe has a brief per id (`STARTERS` in
 * prompt_recipe.py and agent_recipe.py); the rows read
 * `drafter.starters.<id>.title` and `.description`, the modal's chips
 * `.short`.
 */
export type DrafterStarter = 'website' | 'helpdesk' | 'research';

/** The kinds the Templates step filters by: `drafter.templates.categories.<id>`. */
export type TemplateCategory = 'customerSupport' | 'internal' | 'research';

export type DrafterStarterEntry = {
  key: DrafterStarter;
  Icon: LucideIcon;
  category: TemplateCategory;
};

export const DRAFTER_STARTERS: DrafterStarterEntry[] = [
  { key: 'website', Icon: Globe, category: 'customerSupport' },
  { key: 'helpdesk', Icon: LifeBuoy, category: 'internal' },
  { key: 'research', Icon: FileSearch, category: 'research' },
];

/** How many starting points the New agent modal and the drawer offer. */
export const FEATURED_STARTER_COUNT = 3;

/** The starting points the modal's chips and the drawer's first screen show. */
export const FEATURED_STARTERS = DRAFTER_STARTERS.slice(
  0,
  FEATURED_STARTER_COUNT,
);

/** Whether there are more than the featured ones, so "All templates" shows. */
export const HAS_MORE_STARTERS =
  DRAFTER_STARTERS.length > FEATURED_STARTER_COUNT;

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
