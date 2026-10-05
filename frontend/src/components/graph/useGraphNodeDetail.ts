import { useCallback, useEffect, useRef, useState } from 'react';
import { useSelector } from 'react-redux';

import userService from '../../api/services/userService';
import { selectToken } from '../../preferences/preferenceSlice';
import type { GraphNodeDetail } from '../graphViewUtils';

export type GraphNodeDetailStatus = 'idle' | 'loading' | 'ready' | 'error';

/**
 * Fetch one graph node's detail (description, relationships, chunks).
 *
 * @param docId The source id.
 * @param nodeId The node to load; null loads nothing.
 * @returns The detail, its status, a retry (shows the loading state) and a
 *   reload (refetches behind the loaded detail, e.g. after a chunk edit).
 */
export function useGraphNodeDetail(docId: string, nodeId: string | null) {
  const token = useSelector(selectToken);
  const [detail, setDetail] = useState<GraphNodeDetail | null>(null);
  const [status, setStatus] = useState<GraphNodeDetailStatus>('idle');
  const [attempt, setAttempt] = useState(0);
  // Set by reload: keep the current detail on screen while refetching.
  const silentRef = useRef(false);
  const shownIdRef = useRef<string | null>(null);

  useEffect(() => {
    const silent = silentRef.current && shownIdRef.current === nodeId;
    silentRef.current = false;
    if (!silent) setDetail(null);
    if (!nodeId) {
      shownIdRef.current = null;
      setStatus('idle');
      return;
    }
    let cancelled = false;
    if (!silent) setStatus('loading');
    userService
      .getSourceGraphNode(docId, nodeId, token)
      .then((response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return response.json();
      })
      .then((body) => {
        if (cancelled) return;
        if (!body?.node) throw new Error('No node');
        const node = body.node as GraphNodeDetail;
        shownIdRef.current = nodeId;
        setDetail({ ...node, chunks: node.chunks ?? [] });
        setStatus('ready');
      })
      .catch((error) => {
        if (cancelled) return;
        console.error('Error loading graph node:', error);
        // A failed background reload keeps what is shown.
        if (!silent) setStatus('error');
      });
    return () => {
      cancelled = true;
    };
  }, [docId, nodeId, token, attempt]);

  const retry = useCallback(() => setAttempt((n) => n + 1), []);
  const reload = useCallback(() => {
    silentRef.current = true;
    setAttempt((n) => n + 1);
  }, []);
  return { detail, status, retry, reload };
}
