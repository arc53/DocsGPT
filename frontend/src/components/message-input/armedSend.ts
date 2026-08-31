import { useCallback, useEffect, useRef, useState } from 'react';

import type { Attachment } from '../../upload/uploadSlice';

export type SendReadiness =
  | { state: 'ready' }
  | { state: 'waiting'; pendingCount: number }
  | { state: 'blocked'; failedNames: string[] };

export function getSendReadiness(attachments: Attachment[]): SendReadiness {
  const failedNames = attachments
    .filter((a) => a.status === 'failed')
    .map((a) => a.fileName);
  if (failedNames.length > 0) return { state: 'blocked', failedNames };

  const pendingCount = attachments.filter(
    (a) => a.status === 'uploading' || a.status === 'processing',
  ).length;
  if (pendingCount > 0) return { state: 'waiting', pendingCount };

  return { state: 'ready' };
}

export function useArmedSend({
  attachments,
  onFlush,
}: {
  attachments: Attachment[];
  onFlush: () => void;
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
    if (readiness.state === 'ready' && !flushedRef.current) {
      flushedRef.current = true;
      setArmed(false);
      flushRef.current();
    }
  }, [armed, readiness.state]);

  const arm = useCallback(() => setArmed(true), []);
  const cancel = useCallback(() => setArmed(false), []);

  return { armed, readiness, arm, cancel };
}
