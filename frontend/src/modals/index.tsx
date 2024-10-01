import * as React from 'react';
import { useTranslation } from 'react-i18next';
interface ModalProps {
  handleSubmit: () => void;
  isCancellable: boolean;
  handleCancel?: () => void;
  render: () => JSX.Element;
  modalState: string;
  isError: boolean;
  errorMessage?: string;
  textDelete?: boolean;
}

const Modal = (props: ModalProps) => {
  const { t } = useTranslation();
  return (
    <div
      className={`${
        props.modalState === 'ACTIVE' ? 'visible' : 'hidden'
      } absolute z-30  h-screen w-screen  bg-gray-alpha`}
    >
      {props.render()}
      <div className=" mx-auto flex w-[90vw] max-w-lg flex-row-reverse rounded-b-lg bg-white pb-5 pr-5 shadow-lg  dark:bg-outer-space">
        <div>
          <button
            onClick={() => props.handleSubmit()}
            className="ml-auto h-10 w-20 rounded-3xl bg-violet-800 text-white transition-all hover:bg-violet-700 dark:text-silver"
          >
            {props.textDelete ? 'Delete' : 'Save'}
          </button>
          {props.isCancellable && (
            <button
              onClick={() => props.handleCancel && props.handleCancel()}
              className="cursor-pointer rounded-3xl px-5 py-2 text-sm font-medium hover:bg-gray-100 dark:bg-transparent dark:text-light-gray dark:hover:bg-[#767183]/50"
            >
              {t('cancel')}
            </button>
          )}
        </div>
        {props.isError && (
          <p className="mx-auto mt-2 mr-auto text-sm text-red-500">
            {props.errorMessage}
          </p>
        )}
      </div>
    </div>
  );
};

export default Modal;
