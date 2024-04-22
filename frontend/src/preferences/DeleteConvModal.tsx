import { useRef } from 'react';
import { ActiveState } from '../models/misc';
import { useMediaQuery, useOutsideAlerter } from './../hooks';
import Modal from '../Modal';
import { useDispatch } from 'react-redux';

export default function DeleteConvModal({
  modalState,
  setModalState,
  handleDeleteAllConv,
}: {
  modalState: ActiveState;
  setModalState: (val: ActiveState) => void;
  handleDeleteAllConv: () => void;
}) {
  const dispatch = useDispatch();
  const modalRef = useRef(null);
  const { isMobile } = useMediaQuery();

  useOutsideAlerter(
    modalRef,
    () => {
      if (isMobile && modalState === 'ACTIVE') {
        dispatch(setModalState('INACTIVE'));
      }
    },
    [modalState],
  );

  function handleSubmit() {
    handleDeleteAllConv();
    dispatch(setModalState('INACTIVE'));
  }

  function handleCancel() {
    dispatch(setModalState('INACTIVE'));
  }

  return (
    <Modal
      handleCancel={handleCancel}
      isError={false}
      modalState={modalState}
      isCancellable={true}
      handleSubmit={handleSubmit}
      textDelete={true}
      render={() => {
        return (
          <article
            ref={modalRef}
            className="mx-auto mt-24 flex w-[90vw] max-w-lg  flex-col gap-4 rounded-t-lg bg-white p-6 shadow-lg"
          >
            <p className="text-xl text-jet">
              Are you sure you want to delete all the conversations?
            </p>
            <p className="text-md leading-6 text-gray-500"></p>
          </article>
        );
      }}
    />
  );
}
