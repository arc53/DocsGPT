import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import type { ArtifactCardItem, OpenArtifactRequest } from './artifactCards';

/** What a view shows in place of its chat: one artifact, or an answer's list. */
export type ArtifactDetail =
  | { kind: 'artifact'; open: OpenArtifactRequest }
  | {
      kind: 'artifacts';
      /** The answer the list is from (its `useId`). */
      key: string;
      items: ArtifactCardItem[];
      open: OpenArtifactRequest | null;
    };

/**
 * The artifact (or answer's list) a view without a docked side panel shows:
 * the builder preview's drawer and the shared-agent page.
 *
 * The open list follows its answer as the answer's files arrive, and Back
 * puts focus on the card that opened it, which the detail hid.
 *
 * Returns:
 *   `detail` and `setDetail`; `back` (to the chat, focus to the card);
 *   `reset` (closes without moving focus, for a closing dialog); and the
 *   handlers and open markers the answers read.
 */
export function useArtifactDetail() {
  const [detail, setDetail] = useState<ArtifactDetail | null>(null);
  const detailRef = useRef(detail);
  useEffect(() => {
    detailRef.current = detail;
  }, [detail]);
  // The card focused when the chat was left for an artifact.
  const opener = useRef<HTMLElement | null>(null);
  const [focusOpener, setFocusOpener] = useState(false);

  const rememberOpener = useCallback(() => {
    if (detailRef.current) return;
    const active = document.activeElement;
    opener.current = active instanceof HTMLElement ? active : null;
  }, []);

  const openArtifact = useCallback(
    (request: OpenArtifactRequest) => {
      rememberOpener();
      setDetail({ kind: 'artifact', open: request });
    },
    [rememberOpener],
  );

  const openArtifactList = useCallback(
    (items: ArtifactCardItem[], key: string) => {
      rememberOpener();
      setDetail({ kind: 'artifacts', key, items, open: null });
    },
    [rememberOpener],
  );

  const syncArtifactList = useCallback(
    (key: string, items: ArtifactCardItem[]) =>
      setDetail((current) =>
        current?.kind === 'artifacts' &&
        current.key === key &&
        current.items !== items
          ? { ...current, items }
          : current,
      ),
    [],
  );

  const back = useCallback(() => {
    setDetail(null);
    setFocusOpener(true);
  }, []);

  const reset = useCallback(() => {
    opener.current = null;
    setDetail(null);
  }, []);

  // After the chat is shown again: the card can only take focus once visible.
  useEffect(() => {
    if (!focusOpener || detail) return;
    setFocusOpener(false);
    if (opener.current?.isConnected) opener.current.focus();
    opener.current = null;
  }, [focusOpener, detail]);

  const shownRequest = detail?.open ?? null;
  const shown = useMemo(
    () =>
      shownRequest
        ? { id: shownRequest.id, version: shownRequest.version }
        : null,
    [shownRequest],
  );
  const listKey = detail?.kind === 'artifacts' ? detail.key : null;

  return {
    detail,
    setDetail,
    back,
    reset,
    openArtifact,
    openArtifactList,
    syncArtifactList,
    shown,
    listKey,
  };
}
