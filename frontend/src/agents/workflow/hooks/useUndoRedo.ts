import { useCallback, useRef, useState } from 'react';

import type { Dispatch, SetStateAction } from 'react';
import type { Edge, Node } from 'reactflow';

export type WorkflowSnapshot = {
  nodes: Node[];
  edges: Edge[];
};

type UseUndoRedoOptions = {
  nodes: Node[];
  edges: Edge[];
  setNodes: Dispatch<SetStateAction<Node[]>>;
  setEdges: Dispatch<SetStateAction<Edge[]>>;
  onRestore?: (snapshot: WorkflowSnapshot) => void;
  maxHistorySize?: number;
};

const SNAPSHOT_GROUP_WINDOW_MS = 1000;

// Selection is not part of history: restored elements keep whatever
// selection the user has right now instead of the flags baked into the
// snapshot when it was taken.
function withCurrentSelection<T extends { id: string; selected?: boolean }>(
  restored: T[],
  current: T[],
): T[] {
  const selectedIds = new Set(
    current.filter((el) => el.selected).map((el) => el.id),
  );
  return restored.map((el) =>
    Boolean(el.selected) === selectedIds.has(el.id)
      ? el
      : { ...el, selected: selectedIds.has(el.id) },
  );
}

export function useUndoRedo({
  nodes,
  edges,
  setNodes,
  setEdges,
  onRestore,
  maxHistorySize = 100,
}: UseUndoRedoOptions) {
  const [past, setPast] = useState<WorkflowSnapshot[]>([]);
  const [future, setFuture] = useState<WorkflowSnapshot[]>([]);

  const stateRef = useRef<WorkflowSnapshot>({ nodes, edges });
  stateRef.current = { nodes, edges };
  const pastRef = useRef(past);
  pastRef.current = past;
  const futureRef = useRef(future);
  futureRef.current = future;
  const onRestoreRef = useRef(onRestore);
  onRestoreRef.current = onRestore;

  // Consecutive calls sharing a group key (e.g. keystrokes editing one
  // node's config) collapse into a single history entry while each call
  // stays inside the group window.
  const lastGroupKeyRef = useRef<string | null>(null);
  const lastGroupTimeRef = useRef(0);
  // One user action can request several snapshots in the same event tick
  // (deleting a node also deletes its edges); only the first one counts.
  const tickGuardRef = useRef(false);

  const takeSnapshot = useCallback(
    (groupKey?: string) => {
      const now = Date.now();
      if (
        groupKey &&
        groupKey === lastGroupKeyRef.current &&
        now - lastGroupTimeRef.current < SNAPSHOT_GROUP_WINDOW_MS
      ) {
        lastGroupTimeRef.current = now;
        return;
      }
      lastGroupKeyRef.current = groupKey ?? null;
      lastGroupTimeRef.current = now;

      if (tickGuardRef.current) return;
      tickGuardRef.current = true;
      queueMicrotask(() => {
        tickGuardRef.current = false;
      });

      const snapshot: WorkflowSnapshot = {
        nodes: stateRef.current.nodes,
        edges: stateRef.current.edges,
      };
      setPast((prev) =>
        prev.length >= maxHistorySize
          ? [...prev.slice(prev.length - maxHistorySize + 1), snapshot]
          : [...prev, snapshot],
      );
      setFuture([]);
    },
    [maxHistorySize],
  );

  const undo = useCallback(() => {
    const previous = pastRef.current[pastRef.current.length - 1];
    if (!previous) return;
    const current: WorkflowSnapshot = {
      nodes: stateRef.current.nodes,
      edges: stateRef.current.edges,
    };
    lastGroupKeyRef.current = null;
    setPast(pastRef.current.slice(0, -1));
    setFuture([...futureRef.current, current]);
    setNodes(withCurrentSelection(previous.nodes, current.nodes));
    setEdges(withCurrentSelection(previous.edges, current.edges));
    onRestoreRef.current?.(previous);
  }, [setNodes, setEdges]);

  const redo = useCallback(() => {
    const next = futureRef.current[futureRef.current.length - 1];
    if (!next) return;
    const current: WorkflowSnapshot = {
      nodes: stateRef.current.nodes,
      edges: stateRef.current.edges,
    };
    lastGroupKeyRef.current = null;
    setFuture(futureRef.current.slice(0, -1));
    setPast([...pastRef.current, current]);
    setNodes(withCurrentSelection(next.nodes, current.nodes));
    setEdges(withCurrentSelection(next.edges, current.edges));
    onRestoreRef.current?.(next);
  }, [setNodes, setEdges]);

  const clearHistory = useCallback(() => {
    lastGroupKeyRef.current = null;
    setPast([]);
    setFuture([]);
  }, []);

  return {
    takeSnapshot,
    undo,
    redo,
    clearHistory,
    canUndo: past.length > 0,
    canRedo: future.length > 0,
  };
}
