import React, { useEffect, useRef } from 'react';
import { WrapperModalProps } from './types';
import Exit from '../assets/exit.svg';

const WrapperModal: React.FC<WrapperModalProps> = ({ children, close }) => {
  const modalRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (
        modalRef.current &&
        !modalRef.current.contains(event.target as Node)
      ) {
        close();
      }
    };

    const handleEscapePress = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        close();
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    document.addEventListener('keydown', handleEscapePress);

    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
      document.removeEventListener('keydown', handleEscapePress);
    };
  }, [close]);

  return (
    <div className="fixed top-0 left-0 z-30 flex h-screen w-screen items-center justify-center bg-gray-alpha bg-opacity-50">
      <div
        ref={modalRef}
        className="relative w-11/12 rounded-2xl bg-white p-10 dark:bg-outer-space sm:w-[512px]"
      >
        <button className="absolute top-3 right-4 m-2 w-3" onClick={close}>
          <img className="filter dark:invert" src={Exit} />
        </button>
        {children}
      </div>
    </div>
  );
};

export default WrapperModal;
