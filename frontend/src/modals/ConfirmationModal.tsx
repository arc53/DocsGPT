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
}: {
  message: string;
  modalState: ActiveState;
  setModalState: (state: ActiveState) => void;
  submitLabel: string;
  handleSubmit: () => void;
  cancelLabel?: string;
  handleCancel?: () => void;
}) {
  const { t } = useTranslation();
  return (
    <>
      {modalState === 'ACTIVE' && (
        <WrapperModal
          close={() => {
            setModalState('INACTIVE');
            handleCancel && handleCancel();
          }}
        >
          <div className="relative">
            <div className="p-8">
              <p className="font-base mb-1 w-[90%] text-lg text-jet dark:text-bright-gray">
                {message}
              </p>
              <div>
                <div className="mt-6 flex flex-row-reverse gap-1">
                  <button
                    onClick={handleSubmit}
                    className="rounded-3xl bg-purple-30 px-5 py-2 text-sm text-white transition-all hover:bg-[#6F3FD1]"
                  >
                    {submitLabel}
                  </button>
                  <button
                    onClick={() => {
                      setModalState('INACTIVE');
                      handleCancel && handleCancel();
                    }}
                    className="cursor-pointer rounded-3xl px-5 py-2 text-sm font-medium hover:bg-gray-100 dark:bg-transparent dark:text-light-gray dark:hover:bg-[#767183]/50"
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
