import type { TFunction } from 'i18next';

import type { CustomModel, CustomModelAction, ModelSource } from './types';

type ModelLike = {
  owner?: CustomModel['owner'];
  source?: ModelSource;
  allowed_actions?: CustomModel['allowed_actions'];
  created_by?: CustomModel['created_by'];
};

const noEscape = { interpolation: { escapeValue: false } };

/**
 * Whether a team owns the model: `owner: 'team'` on a custom model row,
 * `source: 'team'` on a row of `/api/models` (the pickers' list).
 */
export const isTeamModel = (model: ModelLike | null | undefined): boolean =>
  model?.owner === 'team' || model?.source === 'team';

/**
 * Whether the caller may do `action` with a custom model, as the server
 * said (`allowed_actions`). A row without the field is the caller's own from
 * a server that predates team models, so everything is allowed; a team row
 * without it allows nothing.
 *
 * Args:
 *   model: The custom model payload.
 *   action: `view`, `use` or `manage`.
 *
 * Returns:
 *   True when the caller may.
 */
export function modelCan(
  model: ModelLike | null | undefined,
  action: CustomModelAction,
): boolean {
  if (!model) return false;
  if (Array.isArray(model.allowed_actions))
    return model.allowed_actions.includes(action);
  return !isTeamModel(model);
}

/**
 * "Added by Lena" (or "Added by you") for a team's model; empty for a
 * person's own or when nobody is on record.
 *
 * Args:
 *   t: The translate function.
 *   model: The custom model payload.
 *   me: The reader's user id, when known.
 *
 * Returns:
 *   The line, or an empty string.
 */
export function addedByText(
  t: TFunction,
  model: ModelLike | null | undefined,
  me?: string | null,
): string {
  const person = model?.created_by;
  if (!isTeamModel(model) || !person) return '';
  if (me && person.user_id === me)
    return t('settings.customModels.team.addedByYou');
  return t('settings.customModels.team.addedBy', {
    name: person.label || person.user_id,
    ...noEscape,
  });
}
