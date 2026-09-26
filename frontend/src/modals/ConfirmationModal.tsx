import { useTranslation } from 'react-i18next';

import { Modal, ModalActions } from '../components/ui/modal';
import { ActiveState } from '../models/misc';

export default function ConfirmationModal({
  message,
  modalState,
  setModalState,
  submitLabel,
  handleSubmit,
  cancelLabel,
  handleCancel,
  variant = 'default',
}: {
  message: string;
  modalState: ActiveState;
  setModalState: (state: ActiveState) => void;
  submitLabel: string;
  handleSubmit: () => void;
  cancelLabel?: string;
  handleCancel?: () => void;
  variant?: 'default' | 'destructive';
}) {
  const { t } = useTranslation();

  const handleSubmitClick = () => {
    handleSubmit();
    setModalState('INACTIVE');
  };

  const handleCancelClick = () => {
    setModalState('INACTIVE');
    handleCancel?.();
  };

  return (
    <Modal
      open={modalState === 'ACTIVE'}
      onOpenChange={(open) => {
        if (!open) setModalState('INACTIVE');
      }}
      title={message}
      footer={
        <ModalActions
          cancelLabel={cancelLabel ? cancelLabel : t('cancel')}
          onCancel={handleCancelClick}
          submitLabel={submitLabel}
          onSubmit={handleSubmitClick}
          destructive={variant === 'destructive'}
        />
      }
    >
      {null}
    </Modal>
  );
}
