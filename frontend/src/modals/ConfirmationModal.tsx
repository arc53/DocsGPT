import { useEffect, useRef, useState, type ReactNode } from 'react';
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
 * then closes on success or shows `error` in a destructive Alert. Closing
 * the dialog drops a request still in flight: its late result never reaches
 * the dialog when it is opened again.
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
  /**
   * The Alert text when the submit's promise rejects, or a function of the
   * rejection for a message that says why (e.g. the server's).
   */
  error?: string | ((reason: unknown) => string);
  /** A body under the title and description (choices, a list). */
  children?: ReactNode;
}) {
  const { t } = useTranslation();
  const [pending, setPending] = useState(false);
  const [failure, setFailure] = useState<{ reason: unknown } | null>(null);
  // Bumped on every close; a submit settling under an older one is dropped.
  const generation = useRef(0);

  const reset = () => {
    generation.current += 1;
    setPending(false);
    setFailure(null);
  };

  // The parent can close the dialog too (e.g. after its own success path).
  useEffect(() => {
    if (modalState === 'ACTIVE') return;
    generation.current += 1;
    setPending(false);
    setFailure(null);
  }, [modalState]);

  const close = () => {
    reset();
    setModalState('INACTIVE');
  };

  const handleSubmitClick = () => {
    if (pending) return;
    const result = handleSubmit();
    if (!isPromiseLike(result)) {
      setModalState('INACTIVE');
      return;
    }
    const issued = generation.current;
    setPending(true);
    setFailure(null);
    Promise.resolve(result).then(
      () => {
        if (issued !== generation.current) return;
        close();
      },
      (reason: unknown) => {
        if (issued !== generation.current) return;
        setPending(false);
        setFailure({ reason });
      },
    );
  };

  const handleCancelClick = () => {
    close();
    handleCancel?.();
  };

  const failureText = !failure
    ? null
    : typeof error === 'function'
      ? error(failure.reason)
      : (error ?? t('common.actionFailed'));

  const alert = failureText ? (
    <Alert variant="destructive">
      <AlertDescription>{failureText}</AlertDescription>
    </Alert>
  ) : null;

  return (
    <Modal
      mobileVariant="dialog"
      open={modalState === 'ACTIVE'}
      onOpenChange={(open) => {
        if (!open) close();
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
