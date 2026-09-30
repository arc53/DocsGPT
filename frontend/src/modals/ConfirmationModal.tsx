import { CircleAlert } from 'lucide-react';
import { useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';

import { Alert, AlertDescription } from '../components/ui/alert';
import { Modal, ModalActions } from '../components/ui/modal';
import { ActiveState } from '../models/misc';

function isPromiseLike(value: unknown): value is PromiseLike<unknown> {
  return (
    typeof value === 'object' &&
    value !== null &&
    typeof (value as PromiseLike<unknown>).then === 'function'
  );
}

/**
 * The yes/no dialog: a title, an optional line and body, Cancel and a
 * submit. A sync `handleSubmit` closes it at once; one that returns a
 * promise keeps it open with a pending submit until the promise settles,
 * then closes on success or shows `error` in a destructive Alert.
 */
export default function ConfirmationModal({
  message,
  description,
  modalState,
  setModalState,
  submitLabel,
  handleSubmit,
  cancelLabel,
  handleCancel,
  variant = 'default',
  error,
  children,
}: {
  message: string;
  /** A muted line under the title that says what the action does. */
  description?: string;
  modalState: ActiveState;
  setModalState: (state: ActiveState) => void;
  submitLabel: string;
  /** Return the request's promise to show pending and keep a failure open. */
  handleSubmit: () => void | Promise<unknown>;
  cancelLabel?: string;
  handleCancel?: () => void;
  variant?: 'default' | 'destructive';
  /** The Alert text when the submit's promise rejects. */
  error?: string;
  /** A body under the title and description (choices, a list). */
  children?: ReactNode;
}) {
  const { t } = useTranslation();
  const [pending, setPending] = useState(false);
  const [failed, setFailed] = useState(false);

  const handleSubmitClick = () => {
    if (pending) return;
    const result = handleSubmit();
    if (!isPromiseLike(result)) {
      setModalState('INACTIVE');
      return;
    }
    setPending(true);
    setFailed(false);
    Promise.resolve(result).then(
      () => {
        setPending(false);
        setModalState('INACTIVE');
      },
      () => {
        setPending(false);
        setFailed(true);
      },
    );
  };

  const handleCancelClick = () => {
    setFailed(false);
    setModalState('INACTIVE');
    handleCancel?.();
  };

  const alert = failed ? (
    <Alert variant="destructive">
      <CircleAlert />
      <AlertDescription>{error ?? t('common.actionFailed')}</AlertDescription>
    </Alert>
  ) : null;

  return (
    <Modal
      mobileVariant="dialog"
      open={modalState === 'ACTIVE'}
      onOpenChange={(open) => {
        if (!open) {
          setFailed(false);
          setModalState('INACTIVE');
        }
      }}
      title={message}
      description={description}
      footer={
        <ModalActions
          cancelLabel={cancelLabel ? cancelLabel : t('cancel')}
          onCancel={handleCancelClick}
          submitLabel={submitLabel}
          onSubmit={handleSubmitClick}
          pending={pending}
          destructive={variant === 'destructive'}
        />
      }
    >
      {alert && children ? (
        <div className="flex flex-col gap-6">
          {alert}
          {children}
        </div>
      ) : (
        (alert ?? children ?? null)
      )}
    </Modal>
  );
}
