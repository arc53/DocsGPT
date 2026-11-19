import { isTeamModel } from './teamModels';
import type { ModelSource } from './types';

/** A model picker's three groups, in the order they show. */
export type ModelGroups<M> = {
  /** The instance's catalog. */
  builtin: M[];
  /** The team's custom models (`source: 'team'`, in a team workspace). */
  team: M[];
  /** The caller's own custom models. */
  user: M[];
};

/**
 * Splits a model list (`/api/models` or the owner's models) into the
 * catalog, the team's custom models and the caller's own, keeping each
 * group's order.
 *
 * Args:
 *   models: The models, each with its `source`.
 *
 * Returns:
 *   The three groups.
 */
export function groupModels<M extends { source?: ModelSource }>(
  models: readonly M[],
): ModelGroups<M> {
  const groups: ModelGroups<M> = { builtin: [], team: [], user: [] };
  models.forEach((model) => {
    if (isTeamModel(model)) groups.team.push(model);
    else if (model.source === 'user') groups.user.push(model);
    else groups.builtin.push(model);
  });
  return groups;
}

/** Whether a model is the instance's (neither a person's nor a team's custom model). */
export const isCatalogModel = (model: { source?: ModelSource }): boolean =>
  model.source !== 'user' && !isTeamModel(model);
