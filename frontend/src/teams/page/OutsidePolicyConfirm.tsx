import { useTranslation } from 'react-i18next';

import {
  type OutsidePolicy,
  teamErrorMessage,
} from '../../api/services/teamsService';
import ConfirmationModal from '../../modals/ConfirmationModal';
import { formatCount } from '../../utils/dateTimeUtils';

const noEscape = { interpolation: { escapeValue: false } };

type OutsidePolicyConfirmProps = {
  teamName: string;
  /** The policy now. */
  from: OutsidePolicy;
  /** The policy picked; the dialog is open while it is set. */
  to: OutsidePolicy | null;
  /** The caller is the team's Owner (only they unlock). */
  isOwner: boolean;
  /**
   * The team's shares with other teams and its agents reachable from
   * outside; null while unknown (the lines then carry no number).
   */
  counts: { shares: number; published: number } | null;
  onClose: () => void;
  /** Saves the pick; a rejection stays in the dialog. */
  onConfirm: (policy: OutsidePolicy) => Promise<unknown>;
};

/**
 * Asks before changing who may take the team's items outside, and says what
 * the change does: locking pauses the team's shares with other teams, its
 * agents' outside access and its chat links (and an Admin can't unlock it
 * again); unlocking brings them back; letting Editors in or out says what
 * they gain or what pauses.
 */
export default function OutsidePolicyConfirm({
  teamName,
  from,
  to,
  isOwner,
  counts,
  onClose,
  onConfirm,
}: OutsidePolicyConfirmProps) {
  const { t } = useTranslation();
  const K = 'settings.teams.outside.confirm';
  const locking = to === 'locked';
  const unlocking = from === 'locked' && to !== null && to !== 'locked';

  const countLine = (group: 'pauses' | 'returns', kind: string, n?: number) =>
    n === undefined
      ? t(`${K}.${group}.${kind}Any`)
      : t(`${K}.${group}.${kind}`, { count: n, formatted: formatCount(n) });

  // What pauses on a lock, or comes back on an unlock: nothing is deleted,
  // so the same three things either way. A known zero is left out.
  const outsideLines = (group: 'pauses' | 'returns'): string[] => {
    const lines: string[] = [];
    if (!counts || counts.shares > 0)
      lines.push(countLine(group, 'shares', counts?.shares));
    if (!counts || counts.published > 0)
      lines.push(countLine(group, 'published', counts?.published));
    lines.push(t(`${K}.${group}.chatLinks`));
    return lines;
  };

  let title: string;
  let description: string | undefined;
  let lines: string[] = [];
  const notes: string[] = [];
  let submitLabel: string;
  if (locking) {
    title = t(`${K}.lockTitle`, { team: teamName, ...noEscape });
    description = t(`${K}.lockIntro`);
    lines = outsideLines('pauses');
    notes.push(t(`${K}.lockStops`), t(`${K}.kept`));
    if (!isOwner) notes.push(t(`${K}.ownerUnlocks`));
    submitLabel = t(`${K}.submit.lock`);
  } else if (unlocking) {
    title = t(`${K}.unlockTitle`, { team: teamName, ...noEscape });
    description = t(`${K}.unlockIntro`);
    lines = outsideLines('returns');
    if (to === 'editors') notes.push(t(`${K}.toEditors`));
    submitLabel = t(`${K}.submit.unlock`);
  } else {
    title = t(`${K}.changeTitle`);
    description = to === 'editors' ? t(`${K}.toEditors`) : t(`${K}.toAdmins`);
    submitLabel = t(`${K}.submit.change`);
  }

  return (
    <ConfirmationModal
      message={title}
      description={description}
      modalState={to ? 'ACTIVE' : 'INACTIVE'}
      setModalState={(state) => state === 'INACTIVE' && onClose()}
      submitLabel={submitLabel}
      handleSubmit={() => (to ? onConfirm(to) : Promise.resolve())}
      error={(e) =>
        teamErrorMessage(t, e, t('settings.teams.outside.policyError'))
      }
      variant={locking ? 'destructive' : 'default'}
    >
      {lines.length > 0 || notes.length > 0 ? (
        <div className="flex flex-col gap-3 text-sm">
          {lines.length > 0 && (
            <ul className="text-foreground list-inside list-disc">
              {lines.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
          )}
          {notes.map((note) => (
            <p key={note} className="text-muted-foreground">
              {note}
            </p>
          ))}
        </div>
      ) : null}
    </ConfirmationModal>
  );
}
