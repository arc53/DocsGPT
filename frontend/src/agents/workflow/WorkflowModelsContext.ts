import { createContext, useContext } from 'react';

/**
 * Model display names by model id, provided by the builder so the canvas
 * nodes (rendered by React Flow, out of reach of props) can name a model.
 */
export const WorkflowModelsContext = createContext<Record<string, string>>({});

/**
 * A model's display name.
 *
 * Args:
 *   modelId: The model id stored on the node.
 *
 * Returns:
 *   The display name, the id itself when the model is unknown, or undefined
 *   when no id is set.
 */
export function useModelDisplayName(
  modelId: string | undefined,
): string | undefined {
  const names = useContext(WorkflowModelsContext);
  if (!modelId) return undefined;
  return names[modelId] || modelId;
}
