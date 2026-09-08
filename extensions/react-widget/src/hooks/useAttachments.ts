import React from 'react';

import { fetchTaskOutcome, uploadAttachment } from '../requests/attachmentsApi';
import { Attachment } from '../types/index';

const POLL_INTERVAL_MS = 1500;
// A large PDF with OCR can take minutes to parse.
const POLL_TIMEOUT_MS = 5 * 60 * 1000;

const PROCESSING_FAILED = 'Could not read this file.';

const generateId = (): string =>
  `${Date.now()}-${Math.random().toString(36).slice(2)}`;

/** Lower-cased final extension including the dot, or '' (dotfiles have none). */
const fileExtension = (name: string): string => {
  const base = name.split(/[\\/]/).pop() ?? '';
  const dot = base.lastIndexOf('.');
  return dot <= 0 ? '' : base.slice(dot).toLowerCase();
};

/** `allowedFileExtensions` as '.ext' entries; 'pdf' and '.PDF' both work. */
export const normalizeExtensions = (types?: string[]): string[] => {
  if (!Array.isArray(types)) return [];
  return types
    .map((type) => String(type).trim().toLowerCase())
    .filter(Boolean)
    .map((type) => (type.startsWith('.') ? type : `.${type}`));
};

/** Picker filter; a hint only, `addFiles` does the real check. */
export const acceptAttribute = (extensions: string[]): string =>
  extensions.join(',');

/** Resolves on the timeout, or early on abort. */
const delay = (ms: number, signal: AbortSignal): Promise<void> =>
  new Promise<void>((resolve) => {
    const onAbort = () => {
      clearTimeout(timer);
      resolve();
    };
    const timer = setTimeout(() => {
      signal.removeEventListener('abort', onAbort);
      resolve();
    }, ms);
    signal.addEventListener('abort', onAbort, { once: true });
  });

interface UseAttachmentsOptions {
  apiKey: string;
  apiHost: string;
  /** Normalised '.ext' list; empty accepts nothing. */
  acceptedExtensions: string[];
}

/**
 * Upload each picked file, then poll its parse task for an attachment id.
 *
 * The widget authenticates on an agent key, so it has no user event stream
 * to subscribe to and completion has to be polled.
 */
export const useAttachments = ({
  apiKey,
  apiHost,
  acceptedExtensions,
}: UseAttachmentsOptions) => {
  const [attachments, setAttachments] = React.useState<Attachment[]>([]);
  // One per chip, so removing it cancels the upload and stops the poll.
  const controllersRef = React.useRef(new Map<string, AbortController>());

  const patch = React.useCallback(
    (id: string, updates: Partial<Attachment>) => {
      // A removed chip is not matched, so a late response cannot resurrect
      // it.
      setAttachments((prev) =>
        prev.map((item) => (item.id === id ? { ...item, ...updates } : item)),
      );
    },
    [],
  );

  const track = React.useCallback(
    async (id: string, taskId: string, controller: AbortController) => {
      const deadline = Date.now() + POLL_TIMEOUT_MS;

      while (!controller.signal.aborted) {
        await delay(POLL_INTERVAL_MS, controller.signal);
        if (controller.signal.aborted) return;

        let outcome;
        try {
          outcome = await fetchTaskOutcome(taskId, apiHost, controller.signal);
        } catch {
          // Offline for a moment; the deadline below bounds this.
          outcome = { state: 'pending' as const };
        }
        if (controller.signal.aborted) return;

        if (outcome.state === 'completed') {
          // No id means nothing to send, whatever the task status said.
          if (outcome.attachmentId)
            patch(id, {
              status: 'completed',
              progress: 100,
              attachmentId: outcome.attachmentId,
            });
          else patch(id, { status: 'failed', error: PROCESSING_FAILED });
          return;
        }
        if (outcome.state === 'failed') {
          patch(id, { status: 'failed', error: PROCESSING_FAILED });
          return;
        }
        if (Date.now() > deadline) {
          patch(id, {
            status: 'failed',
            error: 'Took too long to process.',
          });
          return;
        }
      }
    },
    [apiHost, patch],
  );

  const addFiles = React.useCallback(
    (files: File[]) => {
      files.forEach((file) => {
        const id = generateId();
        const extension = fileExtension(file.name);

        // A rejected file still gets a chip: mobile pickers ignore
        // `accept`, and a silent drop looks broken.
        if (!acceptedExtensions.includes(extension)) {
          setAttachments((prev) => [
            ...prev,
            {
              id,
              fileName: file.name,
              status: 'failed',
              progress: 0,
              error: `${extension || 'That file type'} is not accepted here.`,
            },
          ]);
          return;
        }

        const controller = new AbortController();
        controllersRef.current.set(id, controller);
        setAttachments((prev) => [
          ...prev,
          { id, fileName: file.name, status: 'uploading', progress: 0 },
        ]);

        uploadAttachment({
          file,
          apiKey,
          apiHost,
          signal: controller.signal,
          onProgress: (percent) => patch(id, { progress: percent }),
        })
          .then(({ taskId }) => {
            if (controller.signal.aborted) return undefined;
            patch(id, { status: 'processing', progress: 100 });
            return track(id, taskId, controller);
          })
          .catch((error: unknown) => {
            if (controller.signal.aborted) return;
            patch(id, {
              status: 'failed',
              error:
                error instanceof Error && error.message
                  ? error.message
                  : 'Upload failed.',
            });
          })
          .finally(() => {
            controllersRef.current.delete(id);
          });
      });
    },
    [acceptedExtensions, apiHost, apiKey, patch, track],
  );

  const remove = React.useCallback((id: string) => {
    controllersRef.current.get(id)?.abort();
    controllersRef.current.delete(id);
    setAttachments((prev) => prev.filter((item) => item.id !== id));
  }, []);

  const clear = React.useCallback(() => {
    controllersRef.current.forEach((controller) => controller.abort());
    controllersRef.current.clear();
    setAttachments([]);
  }, []);

  React.useEffect(() => {
    const controllers = controllersRef.current;
    return () => {
      controllers.forEach((controller) => controller.abort());
      controllers.clear();
    };
  }, []);

  const pendingCount = attachments.filter(
    (item) => item.status === 'uploading' || item.status === 'processing',
  ).length;
  const failedCount = attachments.filter(
    (item) => item.status === 'failed',
  ).length;
  const completed = attachments.filter(
    (item) => item.status === 'completed' && item.attachmentId,
  );

  return {
    attachments,
    addFiles,
    remove,
    clear,
    pendingCount,
    failedCount,
    completed,
  };
};
