/** The palette type of an If / Else node that starts in AI mode. */
export const AI_DECISION_PALETTE_TYPE = 'decision';

/**
 * The node type a palette type adds.
 *
 * Args:
 *   paletteType: A node type, or a preset such as `decision`.
 */
export function paletteNodeType(paletteType: string): string {
  return paletteType === AI_DECISION_PALETTE_TYPE ? 'condition' : paletteType;
}
