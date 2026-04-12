import { useTranslation } from 'react-i18next';

import { ActiveState } from '../models/misc';
import WrapperModal from './WrapperModal';

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

  const submitButtonClasses =
    variant === 'danger'
      ? 'rounded-3xl bg-destructive px-5 py-2 text-sm text-white transition-all hover:bg-destructive/90 hover:font-bold tracking-[0.019em] hover:tracking-normal'
      : 'rounded-3xl bg-primary px-5 py-2 text-sm text-white transition-all hover:bg-primary/90';

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
    <>
      {modalState === 'ACTIVE' && (
        <WrapperModal close={() => setModalState('INACTIVE')}>
          <div className="relative">
            <div>
              <p className="font-base text-foreground dark:text-foreground mb-1 w-[90%] text-lg wrap-break-word">
                {message}
              </p>
              <div>
                <div className="mt-6 flex flex-row-reverse gap-1">
                  <button
                    onClick={handleSubmitClick}
                    className={submitButtonClasses}
                  >
                    {submitLabel}
                  </button>
                  <button
                    onClick={handleCancelClick}
                    className="dark:text-foreground hover:bg-accent dark:hover:bg-accent cursor-pointer rounded-3xl px-5 py-2 text-sm font-medium"
                  >
                    {cancelLabel ? cancelLabel : t('cancel')}
                  </button>
                </div>
              </div>
            </div>
          </div>
        </WrapperModal>
      )}
    </>
  );
}
