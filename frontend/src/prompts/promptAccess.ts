import type { Prompt } from '../models/misc';
import { can } from '../utils/accessUtils';

// Presets (`public`) carry no access fields and are never edited in place.

/** The built-in prompts' ids, which every instance has. */
export const PRESET_PROMPT_IDS: readonly string[] = [
  'default',
  'creative',
  'strict',
];

/** The built-in prompts as the prompt list holds them before it is read. */
export const presetPrompts = (): Prompt[] =>
  PRESET_PROMPT_IDS.map((id) => ({ name: id, id, type: 'public' }));

/** Whether the caller may change the prompt's name and text. */
export const canEditPrompt = (prompt: Prompt) =>
  prompt.type !== 'public' && can(prompt, 'edit');

/** Whether the caller may delete the prompt. */
export const canDeletePrompt = (prompt: Prompt) =>
  prompt.type !== 'public' && can(prompt, 'delete');

/** Whether the caller may share the prompt with a team. */
export const canSharePrompt = (prompt: Prompt) =>
  prompt.type !== 'public' && can(prompt, 'share');

/**
 * A copy's name that no listed prompt has: "Support copy", then "Support
 * copy 2" and on.
 *
 * Args:
 *   baseName: The copied prompt's name.
 *   prompts: The listed prompts.
 *
 * Returns:
 *   The first free name.
 */
export function copyName(baseName: string, prompts: Prompt[]): string {
  let candidate = `${baseName} copy`;
  let counter = 2;
  while (prompts.some((prompt) => prompt.name === candidate)) {
    candidate = `${baseName} copy ${counter}`;
    counter += 1;
  }
  return candidate;
}
