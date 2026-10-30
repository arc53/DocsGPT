import type { ResourceUsage } from '../settings/types';

/**
 * How many agents use a resource: the ones the caller can open and the
 * ones they can't. A missing `used_by` (an older server) counts as none.
 *
 * Args:
 *   usage: The resource's `used_by`.
 *
 * Returns:
 *   The number of agents.
 */
export const agentUseCount = (
  usage: ResourceUsage | null | undefined,
): number => (usage?.agents?.length ?? 0) + (usage?.others ?? 0);
