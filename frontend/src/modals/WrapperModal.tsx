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
      const target = event.target as Node;
      if (
        (target as Element)?.closest?.(
          '[data-radix-popper-content-wrapper], [data-radix-select-viewport], [role="listbox"]',
        )
      )
        return;
      if (document.querySelector('[data-radix-select-content]')) return;
      if (modalRef.current && !modalRef.current.contains(target))
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
    <div
      className="fixed top-0 left-0 z-100 flex h-screen w-screen items-center justify-center"
      onClick={(e: React.MouseEvent) => e.stopPropagation()}
      onMouseDown={(e: React.MouseEvent) => e.stopPropagation()}
    >
      <div
        className="absolute inset-0 bg-black/25 backdrop-blur-xs dark:bg-black/50"
        onClick={isPerformingTask ? undefined : close}
      />
      <div
        ref={modalRef}
        className={`relative rounded-2xl bg-white p-8 shadow-[0px_4px_40px_-3px_#0000001A] dark:bg-[#26272E] ${className}`}
      >
        {!isPerformingTask && (
          <button
            className="absolute top-3 right-4 z-50 m-2 w-3"
            onClick={close}
          >
            <img className="filter dark:invert" src={Exit} alt="Close" />
          </button>
        )}
        <div
          className={`no-scrollbar overflow-y-auto text-[#18181B] dark:text-[#ECECF1] ${contentClassName}`}
        >
          {children}
        </div>
      </div>
    </div>
  );

  return createPortal(modalContent, document.body);
}
