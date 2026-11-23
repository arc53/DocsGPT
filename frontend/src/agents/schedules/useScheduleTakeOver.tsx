import { useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';

import type { ActiveState } from '../../models/misc';
import { showActionToast } from '../../notifications/actionToastSlice';
import TakeOverModal from '../../payer/TakeOverModal';
import { selectToken } from '../../preferences/preferenceSlice';
import type { AppDispatch, RootState } from '../../store';
import { readerIdFromToken } from '../../utils/personLabel';
import { PERSONAL_WORKSPACE } from '../../workspace/requestWorkspace';
import type { Schedule } from '../types/schedule';
import { takeOverSchedule } from './schedulesSlice';

/** The current team's name; null in Personal or before the list loads. */
const selectTeamName = (state: RootState): string | null => {
  // Read defensively: a page's test store may leave the workspace out.
  const workspace = state.workspace as RootState['workspace'] | undefined;
  if (!workspace || workspace.current === PERSONAL_WORKSPACE) return null;
  return (
    workspace.workspaces?.find((row) => row.id === workspace.current)?.name ||
    null
  );
};

/**
 * "Take over" for a schedule list: asks once in `TakeOverModal`, then makes
 * the caller the schedule's payer, puts the answer in every list that holds
 * the row and says so in a toast. A refusal stays in the dialog, worded by
 * its code.
 *
 * Returns:
 *   `requestTakeOver(schedule)` to open the confirm, `takeOverModal` to
 *   render once on the page, and `rowProps` to spread on each `ScheduleRow`
 *   (the Take over handler, the reader's id and the team's name).
 */
export default function useScheduleTakeOver(): {
  requestTakeOver: (schedule: Schedule) => void;
  takeOverModal: ReactNode;
  rowProps: {
    onTakeOver: (schedule: Schedule) => void;
    viewerId: string | null;
    teamName: string | null;
  };
} {
  const { t } = useTranslation();
  const dispatch = useDispatch<AppDispatch>();
  const token = useSelector(selectToken);
  const teamName = useSelector(selectTeamName);
  const viewerId = readerIdFromToken(token) ?? null;
  const [target, setTarget] = useState<Schedule | null>(null);
  const [modalState, setModalState] = useState<ActiveState>('INACTIVE');

  const requestTakeOver = (schedule: Schedule) => {
    setTarget(schedule);
    setModalState('ACTIVE');
  };

  const confirm = async () => {
    if (!target) return;
    await dispatch(takeOverSchedule({ id: target.id, token })).unwrap();
    dispatch(
      showActionToast({
        variant: 'success',
        message: t('payer.schedules.takenOver'),
      }),
    );
  };

  // The last target stays mounted while closed, so the dialog closes with its
  // own words rather than going blank.
  const takeOverModal = target ? (
    <TakeOverModal
      kind="schedule"
      name={target.name || target.instruction.slice(0, 80)}
      payer={target.paid_by}
      modalState={modalState}
      setModalState={setModalState}
      onConfirm={confirm}
    />
  ) : null;

  return {
    requestTakeOver,
    takeOverModal,
    rowProps: { onTakeOver: requestTakeOver, viewerId, teamName },
  };
}
