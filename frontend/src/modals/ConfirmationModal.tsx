import { useTranslation } from 'react-i18next';

import { Button } from '../components/ui/button';
import { Modal } from '../components/ui/modal';
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
  variant?: 'default' | 'danger';
}) {
  const { t } = useTranslation();

  const handleSubmitClick = (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    handleSubmit();
    setModalState('INACTIVE');
  };

  const handleCancelClick = (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
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
        <>
          <Button
            type="button"
            variant="ghost"
            onClick={handleCancelClick}
            className="rounded-3xl px-5"
          >
            {cancelLabel ? cancelLabel : t('cancel')}
          </Button>
          <Button
            type="button"
            variant={variant === 'danger' ? 'destructive' : 'default'}
            onClick={handleSubmitClick}
            className="rounded-3xl px-5"
          >
            {submitLabel}
          </Button>
        </>
      }
    >
      {null}
    </Modal>
  );
}
