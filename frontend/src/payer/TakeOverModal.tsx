import { Gauge, History, Wallet, type LucideIcon } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import { payerErrorMessage } from '../api/services/payerService';
import ConfirmationModal from '../modals/ConfirmationModal';
import type { ActiveState } from '../models/misc';
import { payerOf } from './pauseReason';
import type { PersonRef } from './types';

export type TakeOverKind = 'schedule' | 'outside_access';

export type TakeOverModalProps = {
  /** A schedule, or an agent's key, public link and webhook. */
  kind: TakeOverKind;
  /** The schedule's or the agent's name, for the title. */
  name: string;
  /** Who pays now (`paid_by`); null when nobody does. */
  payer?: PersonRef | null;
  /**
   * The agent's own limit, as the caller words it ("Carrier desk: no agent
   * limit set."); left out, a general line says it still applies.
   */
  agentLimit?: string | null;
  /** What it used so far, when the caller knows ("It ran 4 times…"). */
  history?: string | null;
  modalState: ActiveState;
  setModalState: (state: ActiveState) => void;
  /**
   * The Take over call (`payerService.takeOverSchedule` or
   * `takeOverOutsideAccess`) and whatever the page does with its answer.
   * A rejection keeps the dialog open with the refusal worded.
   */
  onConfirm: () => Promise<unknown>;
};

function Fact({
  icon: Icon,
  title,
  detail,
}: {
  icon: LucideIcon;
  title: string;
  detail?: string | null;
}) {
  return (
    <li className="flex items-start gap-3">
      <Icon
        className="text-muted-foreground mt-0.5 size-4 shrink-0"
        aria-hidden="true"
      />
      <div className="min-w-0">
        <p className="text-foreground text-sm font-medium">{title}</p>
        {detail ? (
          <p className="text-muted-foreground text-sm">{detail}</p>
        ) : null}
      </div>
    </li>
  );
}

/**
 * The confirm for "Take over": the person who clicks becomes the payer of a
 * team agent's schedule or of its outside access. It says that their
 * allowance pays from now on, that what was spent so far stays with the old
 * payer, and that the agent's own limit still applies.
 */
export default function TakeOverModal({
  kind,
  name,
  payer,
  agentLimit,
  history,
  modalState,
  setModalState,
  onConfirm,
}: TakeOverModalProps) {
  const { t } = useTranslation();
  const noEscape = { interpolation: { escapeValue: false } };
  const block = kind === 'schedule' ? 'schedule' : 'access';
  const payerName = payerOf(payer).label;
  return (
    <ConfirmationModal
      message={t('payer.common.takeOver.title', { name, ...noEscape })}
      modalState={modalState}
      setModalState={setModalState}
      submitLabel={t('payer.common.takeOver.submit')}
      handleSubmit={onConfirm}
      error={(reason) =>
        payerErrorMessage(t, reason, t('payer.common.takeOver.failed'))
      }
    >
      <ul className="flex flex-col gap-3">
        <Fact
          icon={Wallet}
          title={t(`payer.common.takeOver.${block}.youPay`)}
          detail={
            payerName
              ? t(`payer.common.takeOver.${block}.youPayDetail`, {
                  name: payerName,
                  ...noEscape,
                })
              : t(`payer.common.takeOver.${block}.youPayUnnamed`)
          }
        />
        {history ? <Fact icon={History} title={history} /> : null}
        <Fact
          icon={Gauge}
          title={t('payer.common.takeOver.limitApplies')}
          detail={agentLimit || t('payer.common.takeOver.limitDetail')}
        />
      </ul>
    </ConfirmationModal>
  );
}
