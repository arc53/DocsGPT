import { useCallback, useEffect, useRef, useState } from 'react';

import type { Attachment } from '../../upload/uploadSlice';

export type SendReadiness =
  { state: 'ready' } | { state: 'waiting'; pendingCount: number };

// A failed file never resolves, so it never holds the send: the composer
// drops it at submit time and sends the question with whatever succeeded.
export function getSendReadiness(attachments: Attachment[]): SendReadiness {
  const pendingCount = attachments.filter(
    (a) => a.status === 'uploading' || a.status === 'processing',
  ).length;
  if (pendingCount > 0) return { state: 'waiting', pendingCount };

  return { state: 'ready' };
}

export function useArmedSend({
  attachments,
  onFlush,
  canFlush = true,
}: {
  attachments: Attachment[];
  onFlush: () => void;
  // False while the composer can't take a submit (an answer is streaming):
  // the armed send holds until it can, instead of flushing into a refusal.
  canFlush?: boolean;
}) {
  const [armed, setArmed] = useState(false);
  // Latest-closure ref so the flush submits the current composer value,
  // not the one captured when the send was armed.
  const flushRef = useRef(onFlush);
  flushRef.current = onFlush;
  const flushedRef = useRef(false);

  const readiness = getSendReadiness(attachments);

  useEffect(() => {
    if (!armed) {
      flushedRef.current = false;
      return;
    }
    if (readiness.state === 'ready' && canFlush && !flushedRef.current) {
      flushedRef.current = true;
      setArmed(false);
      flushRef.current();
    }
  }, [armed, readiness.state, canFlush]);

  const arm = useCallback(() => setArmed(true), []);
  const cancel = useCallback(() => setArmed(false), []);

  return { armed, readiness, arm, cancel };
}
