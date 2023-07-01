import * as React from 'react';

interface ModalProps {
  handleSubmit: () => void;
  isCancellable: boolean;
  handleCancel?: () => void;
  render: () => JSX.Element;
  modalState: string;
  isError: boolean;
}
const Modal = (props: ModalProps) => {
  return (
    <div
      className={`${
        props.modalState === 'ACTIVE' ? 'visible' : 'hidden'
      } absolute z-30  h-screen w-screen  bg-gray-alpha`}
    >
      {props.render()}
      <div className=" mx-auto flex w-[90vw] max-w-lg flex-row-reverse rounded-lg bg-white pb-5 pr-5  shadow-lg">
        <div>
          <button
            onClick={() => props.handleSubmit()}
            className="ml-auto h-10 w-20 rounded-lg bg-violet-800 text-white transition-all hover:bg-violet-700"
          >
            Save
          </button>
          {props.isCancellable && (
            <button
              onClick={() => props.handleCancel && props.handleCancel()}
              className="ml-5 h-10 w-20 rounded-lg border border-violet-700 bg-white text-violet-800 transition-all hover:bg-violet-700 hover:text-white"
            >
              Cancel
            </button>
          )}
        </div>
        {props.isError && (
          <p className="mx-auto mt-2 mr-auto text-sm text-red-500">
            Please enter a valid API key
          </p>
        )}
      </div>
    </div>
  );
};

export default Modal;
