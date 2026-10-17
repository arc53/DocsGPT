import { useCallback, useState } from 'react';

import SponsorConfirmModal from './components/SponsorConfirmModal';
import type { SponsorConfirmation } from './sponsorConsent';

/**
 * The sponsor confirmation dialog as a promise.
 *
 * `ask` opens the dialog for one refused save and resolves to the keys the
 * caller agreed to, or null when they cancel; render `modal` once. Pass
 * `ask` to `saveWithSponsorConsent`, so the code that started the save gets
 * the retried save's result.
 */
export function useSponsorPrompt() {
  const [pending, setPending] = useState<{
    confirmation: SponsorConfirmation;
    resolve: (keys: string[] | null) => void;
  } | null>(null);

  const ask = useCallback(
    (confirmation: SponsorConfirmation) =>
      new Promise<string[] | null>((resolve) =>
        setPending({ confirmation, resolve }),
      ),
    [],
  );

  const settle = (keys: string[] | null) => {
    pending?.resolve(keys);
    setPending(null);
  };

  const modal = (
    <SponsorConfirmModal
      confirmation={pending?.confirmation ?? null}
      onCancel={() => settle(null)}
      onConfirm={(keys) => settle(keys)}
    />
  );

  return { ask, modal };
}
