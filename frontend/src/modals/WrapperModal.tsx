import React, { useEffect, useRef } from 'react';
import { createPortal } from 'react-dom';

import Exit from '../assets/exit.svg';

type WrapperModalPropsType = {
  children: React.ReactNode;
  close: () => void;
  isPerformingTask?: boolean;
  className?: string;
  contentClassName?: string;
};

export default function WrapperModal({
  children,
  close,
  isPerformingTask = false,
  className = '',
  contentClassName = '',
}: WrapperModalPropsType) {
  const modalRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (isPerformingTask) return;

    const handleClickOutside = (event: MouseEvent) => {
      if (modalRef.current && !modalRef.current.contains(event.target as Node))
        close();
    };

    const handleEscapePress = (event: KeyboardEvent) => {
      if (event.key === 'Escape') close();
    };

    document.addEventListener('mousedown', handleClickOutside);
    document.addEventListener('keydown', handleEscapePress);

    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
      document.removeEventListener('keydown', handleEscapePress);
    };
  }, [close, isPerformingTask]);

  const modalContent = (
    <div className="fixed top-0 left-0 z-30 flex h-screen w-screen items-center justify-center">
      <div
        ref={modalRef}
        className={`relative rounded-2xl bg-white dark:bg-[#26272E] p-8 shadow-[0px_4px_40px_-3px_#0000001A] ${className}`}
      >
        {!isPerformingTask && (
          <button
            className="absolute top-3 right-4 z-50 m-2 w-3"
            onClick={close}
          >
            <img className="filter dark:invert" src={Exit} alt="Close" />
          </button>
        )}
        <div className={`overflow-y-auto no-scrollbar text-[#18181B] dark:text-[#ECECF1] ${contentClassName}`}>{children}</div>
      </div>
    </div>
  );

  return createPortal(modalContent, document.body);
}
