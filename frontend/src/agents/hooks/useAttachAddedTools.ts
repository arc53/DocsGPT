import { useCallback, useEffect, useRef } from 'react';

/**
 * Puts the tools an Add tool run created (`AddToolModal`'s `onToolsCreated`)
 * on what the picker belongs to, an agent or a workflow node, once the
 * reloaded tool list has them. A created tool the picker doesn't offer is
 * left off, and nothing is put on after the opener has gone.
 *
 * Args:
 *   reload: Reloads the picker's tool list and resolves to it.
 *
 * Returns:
 *   `attachCreated(toolIds, attach)`: reloads, then calls `attach` with the
 *   listed tools among `toolIds`, if any. `attach` is passed per call, so it
 *   can hold on to what was open when the run started (a node's id).
 */
export function useAttachAddedTools<T extends { id: string }>(
  reload: () => Promise<T[] | null | undefined>,
): (toolIds: string[], attach: (tools: T[]) => void) => Promise<void> {
  const reloadRef = useRef(reload);
  const mounted = useRef(false);
  useEffect(() => {
    reloadRef.current = reload;
  });
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  return useCallback(async (toolIds, attach) => {
    const tools = await reloadRef.current().catch(() => null);
    if (!tools || !mounted.current || toolIds.length === 0) return;
    const wanted = new Set(toolIds.map((id) => id.toLowerCase()));
    const created = tools.filter((tool) =>
      wanted.has(String(tool.id).toLowerCase()),
    );
    if (created.length > 0) attach(created);
  }, []);
}
