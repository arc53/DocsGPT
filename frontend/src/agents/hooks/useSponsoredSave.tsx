import {
  type ReactNode,
  useCallback,
  useEffect,
  useRef,
  useState,
} from 'react';
import { useTranslation } from 'react-i18next';

import {
  confirmTakeOver,
  readSponsorRefusal,
  saveWithSponsorConsent,
  type SponsorAudience,
  type SponsorResource,
  sponsorNotAllowedMessage,
} from '../sponsorConsent';
import { useSponsorPrompt } from '../useSponsorPrompt';

/** The JSON body of a failed response, or null (a proxy page, an empty 502). */
async function readBody(response: Response): Promise<unknown> {
  try {
    return await response.json();
  } catch {
    return null;
  }
}

/**
 * The backend's own explanation in a failed save's body, else the fallback.
 *
 * The agent and workflow write endpoints answer a rejected save with
 * `{"success": false, "message": "<why>"}` (e.g. "Invalid chunks value: …"),
 * the one piece of information that tells the user what to change.
 */
function messageOf(body: unknown, fallback: string): string {
  const message = (body as { message?: unknown } | null)?.message;
  return typeof message === 'string' && message.trim() ? message : fallback;
}

/** How a sponsored save ended. */
export type SponsoredSaveResult =
  | { status: 'saved'; response: Response }
  /** The caller declined to run something with their access. */
  | { status: 'cancelled' }
  /**
   * Refused: `message` says why, in the UI's language where it can; `body`
   * is the response's JSON for anything else it lists (a workflow's
   * validation `errors`).
   */
  | { status: 'failed'; message: string; response: Response; body?: unknown };

type SponsoredSaveOptions = {
  /**
   * Reads the sponsor details and run state again (after a save, or when
   * a confirmation turned out to be outdated), leaving unsaved fields alone.
   */
  refresh: () => void;
};

export type SponsoredSave = {
  /**
   * Sends a save, asking whenever the server wants the caller's
   * confirmation to run something they added with their access, and
   * resending with it and the takeovers. A save the server took clears the
   * takeovers and refreshes; a refusal comes back as its message.
   */
  save: (
    send: (confirm: string[]) => Promise<Response>,
    fallback: string,
  ) => Promise<SponsoredSaveResult>;
  /** Keys of stopped items the caller agreed to run with their access. */
  takeovers: string[];
  /** Asks before a stopped item runs with the caller's access; on yes the next save confirms it. */
  takeOver: (
    item: Pick<SponsorResource, 'key' | 'type' | 'id'>,
    name: string,
    audience: SponsorAudience | undefined,
  ) => Promise<void>;
  /** Takes back a takeover (or drops it with its item). */
  undoTakeover: (key: string) => void;
  /** The confirmation dialog; render once. */
  modal: ReactNode;
};

/**
 * The agent and workflow builders' save with sponsor consent, in one place:
 * the confirmation round trips (`saveWithSponsorConsent`), a refusal mapped
 * to a message (not allowed, an outdated confirmation, the server's own
 * message), the takeovers that go with the next save, and the refresh once
 * a save is in.
 *
 * Args:
 *   options: `refresh`, which reads the sponsor details again.
 *
 * Returns:
 *   `save`, `takeovers`, `takeOver`, `undoTakeover` and `modal`.
 */
export function useSponsoredSave({
  refresh,
}: SponsoredSaveOptions): SponsoredSave {
  const { t, i18n } = useTranslation();
  const sponsorPrompt = useSponsorPrompt();
  const [takeovers, setTakeovers] = useState<string[]>([]);
  // The save reads the latest refresh and takeovers, not the ones of the
  // render it started in.
  const latest = useRef({ refresh, takeovers });
  useEffect(() => {
    latest.current = { refresh, takeovers };
  });

  const save = useCallback(
    async (
      send: (confirm: string[]) => Promise<Response>,
      fallback: string,
    ): Promise<SponsoredSaveResult> => {
      const response = await saveWithSponsorConsent(
        send,
        sponsorPrompt.ask,
        latest.current.takeovers,
      );
      if (!response) return { status: 'cancelled' };
      if (response.ok) {
        setTakeovers([]);
        latest.current.refresh();
        return { status: 'saved', response };
      }
      const refusal = await readSponsorRefusal(response);
      if (refusal?.kind === 'notAllowed')
        return {
          status: 'failed',
          response,
          message: sponsorNotAllowedMessage(
            t,
            i18n.language,
            refusal.resources,
          ),
        };
      if (refusal?.kind === 'unexpected') {
        // Someone changed it since the caller chose; show them now.
        setTakeovers([]);
        latest.current.refresh();
        return {
          status: 'failed',
          response,
          message: t('agents.form.sponsors.confirmationOutdated'),
        };
      }
      const body = await readBody(response);
      return {
        status: 'failed',
        response,
        body,
        message: messageOf(body, fallback),
      };
    },
    [i18n.language, sponsorPrompt.ask, t],
  );

  const takeOver = useCallback(
    async (
      item: Pick<SponsorResource, 'key' | 'type' | 'id'>,
      name: string,
      audience: SponsorAudience | undefined,
    ) => {
      const agreed = await confirmTakeOver(
        sponsorPrompt.ask,
        item,
        name,
        audience,
      );
      if (agreed)
        setTakeovers((prev) =>
          prev.includes(item.key) ? prev : [...prev, item.key],
        );
    },
    [sponsorPrompt.ask],
  );

  const undoTakeover = useCallback(
    (key: string) => setTakeovers((prev) => prev.filter((k) => k !== key)),
    [],
  );

  return {
    save,
    takeovers,
    takeOver,
    undoTakeover,
    modal: sponsorPrompt.modal,
  };
}
