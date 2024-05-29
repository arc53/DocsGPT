import Exit from '../assets/exit.svg';
import { ActiveState } from '../models/misc';
import { useTranslation } from 'react-i18next';
function ConfirmationModal({
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
    <article
      className={`${
        modalState === 'ACTIVE' ? 'visible' : 'hidden'
      } fixed top-0 left-0 z-30  h-screen w-screen  bg-gray-alpha`}
    >
      <article className="mx-auto mt-[35vh] flex w-[90vw] max-w-lg  flex-col gap-4 rounded-2xl bg-white shadow-lg dark:bg-outer-space">
        <div className="relative">
          <button
            className="absolute top-3 right-4 m-2 w-3"
            onClick={() => {
              setModalState('INACTIVE');
              handleCancel && handleCancel();
            }}
          >
            <img className="filter dark:invert" src={Exit} />
          </button>
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
      </article>
    </article>
  );
}

export default ConfirmationModal;
