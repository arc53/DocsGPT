import React from 'react';
import { useDispatch } from 'react-redux';
import { ActiveState } from '../models/misc';
import { useMediaQuery, useOutsideAlerter } from '../hooks';
import ConfirmationModal from './ConfirmationModal';
import { useTranslation } from 'react-i18next';
import { Action } from '@reduxjs/toolkit';

export default function DeleteConvModal({
  modalState,
  setModalState,
  handleDeleteAllConv,
}: {
  modalState: ActiveState;
  setModalState: (val: ActiveState) => Action;
  handleDeleteAllConv: () => void;
}) {
  const modalRef = React.useRef(null);
  const dispatch = useDispatch();
  const { isMobile } = useMediaQuery();
  const { t } = useTranslation();
  useOutsideAlerter(modalRef, () => {
    if (isMobile && modalState === 'ACTIVE') {
      dispatch(setModalState('INACTIVE'));
    }
  }, [modalState]);

  function handleSubmit() {
    handleDeleteAllConv();
    dispatch(setModalState('INACTIVE'));
  }

  function handleCancel() {
    dispatch(setModalState('INACTIVE'));
  }

  return (
    <ConfirmationModal
      message={t('modals.deleteConv.confirm')}
      modalState={modalState}
      setModalState={setModalState}
      submitLabel={t('modals.deleteConv.delete')}
      handleSubmit={handleSubmit}
      handleCancel={handleCancel}
    />
  );
}
