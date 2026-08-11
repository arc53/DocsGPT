import { useEffect, useRef, useState } from 'react';

import userService from '../api/services/userService';
import {
  type BytesPreviewMode,
  MAX_INLINE_TEXT_BYTES,
  readPresignedUrlEnvelope,
} from './artifactViewUtils';

type BytesState =
  | { status: 'loading' }
  | { status: 'error' }
  | { status: 'text'; text: string }
  | { status: 'image'; url: string };

/**
 * Fetch a version's downloadable bytes via the authed download endpoint and
 * expose them for inline preview. Version-aware: refetches whenever the
 * artifact id, version, or mode changes, and ignores stale responses. Images
 * are exposed as a blob object URL that is revoked on cleanup/version change;
 * text/markup is read as a string and bounded by {@link MAX_INLINE_TEXT_BYTES}.
 *
 * On any fetch/size failure the state becomes `error` so the caller can fall
 * back to the download card. The returned object URL must NOT be revoked by the
 * caller; this hook owns its lifecycle.
 */
export function useArtifactBytes(
  artifactId: string,
  version: number,
  mode: BytesPreviewMode,
  token: string | null,
): BytesState {
  const [state, setState] = useState<BytesState>({ status: 'loading' });
  const objectUrlRef = useRef<string | null>(null);

  useEffect(() => {
    if (mode === 'card') {
      setState({ status: 'error' });
      return;
    }

    let cancelled = false;
    setState({ status: 'loading' });

    const revoke = () => {
      if (objectUrlRef.current) {
        URL.revokeObjectURL(objectUrlRef.current);
        objectUrlRef.current = null;
      }
    };

    userService
      .downloadArtifact(artifactId, token, version, 'url')
      .then(async (response: Response) => {
        if (!response.ok) throw new Error('download failed');

        // Under URL_STRATEGY=s3 the endpoint returns a presigned URL; fetch the
        // bytes directly from it (a bucket without a CORS grant for the app
        // origin blocks this read → caught below → download-card fallback). The
        // backend strategy streams the bytes here, so this is a no-op for it.
        const presignedUrl = await readPresignedUrlEnvelope(response);
        const bytesResponse = presignedUrl
          ? await fetch(presignedUrl)
          : response;
        if (!bytesResponse.ok) throw new Error('bytes fetch failed');

        if (mode === 'image') {
          const blob = await bytesResponse.blob();
          if (cancelled) return;
          revoke();
          const url = URL.createObjectURL(blob);
          objectUrlRef.current = url;
          setState({ status: 'image', url });
          return;
        }

        // html / svg / text families render as a (bounded) string.
        const blob = await bytesResponse.blob();
        if (cancelled) return;
        if (blob.size > MAX_INLINE_TEXT_BYTES) throw new Error('too large');
        const text = await blob.text();
        if (cancelled) return;
        setState({ status: 'text', text });
      })
      .catch(() => {
        if (cancelled) return;
        setState({ status: 'error' });
      });

    return () => {
      cancelled = true;
      revoke();
    };
  }, [artifactId, version, mode, token]);

  return state;
}
