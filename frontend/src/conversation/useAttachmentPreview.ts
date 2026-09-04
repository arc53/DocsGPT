import { useEffect, useState } from 'react';

import userService from '../api/services/userService';
import { isImageFileName } from '../constants/fileUpload';

/**
 * Session cache of attachment-id -> blob URL, so a conversation that shows
 * the same image twice (re-render, scroll-back, duplicate turns) fetches
 * its bytes once. Bounded: the least-recently-used entry is evicted (and
 * revoked) past the cap, and a later revisit simply refetches.
 */
const previewCache = new Map<string, string>();
const previewInflight = new Map<string, Promise<string | null>>();
const PREVIEW_CACHE_CAP = 50;

function cacheKey(attachmentId: string, shareId?: string | null): string {
  return `${shareId ?? ''}:${attachmentId}`;
}

function cacheSet(key: string, url: string): void {
  previewCache.delete(key);
  previewCache.set(key, url);
  while (previewCache.size > PREVIEW_CACHE_CAP) {
    const oldest = previewCache.keys().next();
    if (oldest.done) break;
    const oldestUrl = previewCache.get(oldest.value);
    previewCache.delete(oldest.value);
    if (oldestUrl) {
      try {
        URL.revokeObjectURL(oldestUrl);
      } catch {
        // Already revoked — nothing to do.
      }
    }
  }
}

function isPreviewableImage(attachment: {
  mimeType?: string;
  fileName?: string;
}): boolean {
  if (
    attachment.mimeType &&
    attachment.mimeType.toLowerCase().startsWith('image/')
  ) {
    return true;
  }
  if (attachment.fileName) {
    return isImageFileName(attachment.fileName);
  }
  return false;
}

async function fetchPreviewUrl(
  attachmentId: string,
  token: string | null,
  shareId?: string | null,
): Promise<string | null> {
  const key = cacheKey(attachmentId, shareId);
  const cached = previewCache.get(key);
  if (cached) {
    // Refresh recency.
    previewCache.delete(key);
    previewCache.set(key, cached);
    return cached;
  }
  const inflight = previewInflight.get(key);
  if (inflight) return inflight;

  const pending = (async () => {
    try {
      const response: Response = await userService.getAttachmentPreview(
        attachmentId,
        token,
        shareId,
      );
      if (!response.ok) return null;
      const blob = await response.blob();
      if (blob.size === 0) return null;
      const url = URL.createObjectURL(blob);
      cacheSet(key, url);
      return url;
    } catch {
      return null;
    } finally {
      previewInflight.delete(key);
    }
  })();
  previewInflight.set(key, pending);
  return pending;
}

export type AttachmentPreviewSource = {
  id?: string;
  fileName?: string;
  mimeType?: string;
  previewUrl?: string;
};

/**
 * Resolve an attachment to a renderable image URL, in priority order:
 * live snapshot ``previewUrl`` (instant, no fetch) -> fetched bytes for
 * the attachment ID (session-cached) -> ``null`` (caller renders the
 * generic icon).
 *
 * Non-image attachments never fetch. Failures resolve to ``null`` so the
 * caller falls back gracefully. Blob URLs minted here are owned by the
 * module cache (LRU-revoked); callers must NOT revoke them.
 */
export function useAttachmentPreviewUrl(
  attachment: AttachmentPreviewSource | undefined,
  token: string | null,
  shareId?: string | null,
): string | null {
  const snapshotUrl = attachment?.previewUrl ?? null;
  const attachmentId = attachment?.id;
  const shouldFetch =
    !snapshotUrl &&
    !!attachmentId &&
    isPreviewableImage({
      mimeType: attachment?.mimeType,
      fileName: attachment?.fileName,
    });

  const [fetchedUrl, setFetchedUrl] = useState<string | null>(null);

  useEffect(() => {
    if (!shouldFetch || !attachmentId) {
      setFetchedUrl(null);
      return;
    }
    let cancelled = false;
    setFetchedUrl(null);
    fetchPreviewUrl(attachmentId, token, shareId).then((url) => {
      if (!cancelled) setFetchedUrl(url);
    });
    return () => {
      cancelled = true;
    };
  }, [shouldFetch, attachmentId, token, shareId]);

  return snapshotUrl ?? fetchedUrl;
}
