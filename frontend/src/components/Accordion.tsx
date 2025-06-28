import React, { useRef, useState } from 'react';

import ChevronDown from '../assets/chevron-down.svg';

type AccordionProps = {
  title: string;
  children: React.ReactNode;
  className?: string;
  titleClassName?: string;
  contentClassName?: string;
  open?: boolean;
};

export default function Accordion({
  title,
  children,
  className = '',
  titleClassName = '',
  contentClassName = '',
  open: initialOpen = false,
}: AccordionProps) {
  const contentRef = useRef<HTMLDivElement>(null);
  const [isOpen, setIsOpen] = useState(initialOpen);

  const accordionContentStyle = {
    height: isOpen ? 'auto' : '0px',
    transition: 'height 0.3s ease-in-out, opacity 0.3s ease-in-out',
    overflow: 'hidden',
  } as React.CSSProperties;

  const toggleAccordion = () => {
    setIsOpen(!isOpen);
  };
  return (
    <div className={`overflow-hidden shadow-xs ${className}`}>
      <button
        className={`flex w-full items-center justify-between focus:outline-hidden ${titleClassName}`}
        onClick={toggleAccordion}
      >
        <p className="break-words">{title}</p>
        <img
          src={ChevronDown}
          className={`h-5 w-5 transform transition-transform duration-200 dark:invert ${
            isOpen ? 'rotate-180' : ''
          }`}
          aria-hidden="true"
        />
      </button>

      <div
        ref={contentRef}
        style={accordionContentStyle}
        className={`px-4 ${contentClassName} ${isOpen ? 'pb-3' : 'pb-0'}`}
      >
        {children}
      </div>
    </div>
  );
}
