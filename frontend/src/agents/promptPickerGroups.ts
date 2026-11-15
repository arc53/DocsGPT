import type { ComboboxGroup, ComboboxOption } from '@/components/ui/combobox';

import {
  type FiledItem,
  folderTrailOf,
  type HolderFolder,
  splitByHolderFolder,
} from '../components/pickerScope';
import type { Prompt } from '../models/misc';
import type { AccessFields } from '../utils/accessUtils';

/** A prompt as the agent builder's picker lists it. */
export type PickerPrompt = Prompt &
  FiledItem &
  Pick<AccessFields, 'origin' | 'workspace'>;

/** The Prompt picker's kinds (the Prompts page's sections), All first. */
export const PROMPT_KINDS = ['all', 'included', 'yours', 'shared'] as const;
export type PromptKind = (typeof PROMPT_KINDS)[number];

/**
 * Where a prompt goes: a preset is `included`; the workspace's own (the
 * caller's in Personal, the team's in a team) is `yours`; one shared with
 * the caller is `shared`. Read from `origin`, else from the older `type`.
 */
export function promptKindOf(prompt: PickerPrompt): Exclude<PromptKind, 'all'> {
  if (prompt.type === 'public') return 'included';
  if (prompt.origin === 'own' || prompt.origin === 'team') return 'yours';
  if (prompt.origin === 'shared') return 'shared';
  return prompt.type === 'team' ? 'shared' : 'yours';
}

/** Whether a prompt is of a kind; `all` keeps every one. */
export const promptOfKind = (kind: PromptKind, prompt: PickerPrompt): boolean =>
  kind === 'all' || promptKindOf(prompt) === kind;

type PromptGroupsInput = {
  /** The prompts the kind track lets through. */
  prompts: PickerPrompt[];
  /** A kind's heading. */
  headingOf: (kind: Exclude<PromptKind, 'all'>) => string;
  /** A row's line (a preset's purpose, the start of the text). */
  lineOf: (prompt: PickerPrompt) => string | undefined;
  /** The agent's folder: its prompts lead, then other folders'. */
  holderFolder?: HolderFolder | null;
  /** The heading of the prompts filed in other folders. */
  otherFoldersHeading: string;
  /** A search is typed: the kinds' groups only, each line led by its folder. */
  searching: boolean;
};

/**
 * The Prompt picker's groups. Opened from an agent filed in a folder (and
 * no search typed), that folder's prompts lead under its heading, then the
 * prompts filed in other folders (each line led by its folder), then the
 * rest by kind as the Prompts page has them. A search matches a prompt's
 * folder and names it.
 *
 * Args:
 *   input: The prompts, the headings, each row's line, the holder's folder
 *     and whether a search is typed.
 *
 * Returns:
 *   The non-empty groups, in order.
 */
export function promptPickerGroups({
  prompts,
  headingOf,
  lineOf,
  holderFolder,
  otherFoldersHeading,
  searching,
}: PromptGroupsInput): ComboboxGroup[] {
  const option = (prompt: PickerPrompt, showTrail: boolean): ComboboxOption => {
    const trail = folderTrailOf(prompt);
    return {
      value: prompt.id,
      label: prompt.name,
      description:
        [showTrail ? trail : null, lineOf(prompt)]
          .filter(Boolean)
          .join(' · ') || undefined,
      keywords: trail ? [trail] : undefined,
    };
  };
  const split = splitByHolderFolder(
    prompts,
    searching ? null : holderFolder?.id,
  );
  const byKind = PROMPT_KINDS.filter((kind) => kind !== 'all').map((kind) => ({
    heading: headingOf(kind),
    options: split.rest
      .filter((prompt) => promptKindOf(prompt) === kind)
      .map((prompt) => option(prompt, searching)),
  }));
  return [
    {
      heading: holderFolder?.heading ?? '',
      options: split.holder.map((prompt) => option(prompt, false)),
    },
    {
      heading: otherFoldersHeading,
      options: split.filed.map((prompt) => option(prompt, true)),
    },
    ...byKind,
  ].filter((group) => group.options.length > 0);
}
