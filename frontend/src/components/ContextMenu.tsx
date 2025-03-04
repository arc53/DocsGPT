import { SyntheticEvent, useRef, useEffect } from 'react';

export interface MenuOption {
  icon?: string;
  label: string;
  onClick: (event: SyntheticEvent) => void;
  variant?: 'primary' | 'danger';
  iconClassName?: string;
  iconWidth?: number;
  iconHeight?: number;
}

interface ContextMenuProps {
  isOpen: boolean;
  setIsOpen: (isOpen: boolean) => void;
  options: MenuOption[];
  anchorRef: React.RefObject<HTMLElement>;
  className?: string;
  position?: 'bottom-right' | 'bottom-left' | 'top-right' | 'top-left';
  offset?: { x: number; y: number };
}

export default function ContextMenu({
  isOpen,
  setIsOpen,
  options,
  anchorRef,
  className = '',
  position = 'bottom-right',
  offset = { x: 1, y: 5 },
}: ContextMenuProps) {
  const menuRef = useRef<HTMLDivElement>(null);

  const handleClickOutside = (event: MouseEvent) => {
    if (menuRef.current && !menuRef.current.contains(event.target as Node)) {
      setIsOpen(false);
    }
  };

  useEffect(() => {
    document.addEventListener('mousedown', handleClickOutside);
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, []);

  const getPositionClasses = () => {
    const positionMap = {
      'bottom-right': 'translate-x-1 translate-y-5',
      'bottom-left': '-translate-x-full translate-y-5',
      'top-right': 'translate-x-1 -translate-y-full',
      'top-left': '-translate-x-full -translate-y-full',
    };
    return positionMap[position];
  };

  if (!isOpen) return null;

  const getMenuPosition = () => {
    if (!anchorRef.current) return {};

    const rect = anchorRef.current.getBoundingClientRect();
    return {
      top: `${rect.top + window.scrollY + offset.y}px`,
    };
  };

  const getOptionStyles = (option: MenuOption, index: number) => {
    if (option.variant === 'danger') {
      return `
          dark:text-red-2000 dark:hover:bg-charcoal-grey
          text-rosso-corsa hover:bg-bright-gray
      }`;
    }

    return `
      dark:text-bright-gray dark:hover:bg-charcoal-grey
        text-eerie-black hover:bg-bright-gray
    }`;
  };

  return (
    <div
      ref={menuRef}
      className={`absolute z-30 ${getPositionClasses()} ${className}`}
      style={getMenuPosition()}
    >
      <div
        className={`flex w-32 flex-col rounded-xl text-sm shadow-xl md:w-36 dark:bg-charleston-green-2 bg-lotion`}
        style={{ minWidth: '144px' }}
      >
        {options.map((option, index) => (
          <button
            key={index}
            onClick={(event: SyntheticEvent) => {
              event.stopPropagation();
              option.onClick(event);
              setIsOpen(false);
            }}
            className={`${`
      flex justify-start items-center gap-4 p-3
      transition-colors duration-200 ease-in-out
      ${index === 0 ? 'rounded-t-xl' : ''}
      ${index === options.length - 1 ? 'rounded-b-xl' : ''}
    `}${getOptionStyles(option, index)}`}
          >
            {option.icon && (
              <img
                width={option.iconWidth || 16}
                height={option.iconHeight || 16}
                src={option.icon}
                alt={option.label}
                className={`cursor-pointer hover:opacity-75 ${option.iconClassName}`}
              />
            )}
            <span>{option.label}</span>
          </button>
        ))}
      </div>
    </div>
  );
}
