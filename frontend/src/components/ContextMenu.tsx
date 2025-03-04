import { SyntheticEvent, useRef, useEffect, CSSProperties } from 'react';

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
  offset = { x: 0, y: 8 },
}: ContextMenuProps) {
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (
        menuRef.current &&
        !menuRef.current.contains(event.target as Node) &&
        !anchorRef.current?.contains(event.target as Node)
      ) {
        setIsOpen(false);
      }
    };

    if (isOpen) {
      document.addEventListener('mousedown', handleClickOutside);
      return () =>
        document.removeEventListener('mousedown', handleClickOutside);
    }
  }, [isOpen, setIsOpen]);

  if (!isOpen) return null;

  const getMenuPosition = (): CSSProperties => {
    if (!anchorRef.current) return {};

    const rect = anchorRef.current.getBoundingClientRect();
    const scrollY = window.scrollY || document.documentElement.scrollTop;
    const scrollX = window.scrollX || document.documentElement.scrollLeft;

    let top = rect.bottom + scrollY + offset.y;
    let left = rect.right + scrollX + offset.x;

    // Adjust position based on position prop
    switch (position) {
      case 'bottom-left':
        left = rect.left + scrollX - offset.x;
        break;
      case 'top-right':
        top = rect.top + scrollY - offset.y;
        break;
      case 'top-left':
        top = rect.top + scrollY - offset.y;
        left = rect.left + scrollX - offset.x;
        break;
      // bottom-right is default
    }

    return {
      position: 'fixed',
      top: `${top}px`,
      left: `${left}px`,
    };
  };

  return (
    <div
      ref={menuRef}
      className={`fixed z-50 ${className}`}
      style={{ ...getMenuPosition() }}
      onClick={(e) => e.stopPropagation()}
    >
      <div
        className="flex w-32 flex-col rounded-xl text-sm shadow-xl md:w-36 dark:bg-charleston-green-2 bg-lotion"
        style={{ minWidth: '144px' }}
      >
        {options.map((option, index) => (
          <button
            key={index}
            onClick={(event) => {
              event.preventDefault();
              event.stopPropagation();
              option.onClick(event);
              setIsOpen(false);
            }}
            className={`
              flex justify-start items-center gap-4 p-3
              transition-colors duration-200 ease-in-out
              ${index === 0 ? 'rounded-t-xl' : ''}
              ${index === options.length - 1 ? 'rounded-b-xl' : ''}
              ${
                option.variant === 'danger'
                  ? 'dark:text-red-2000 dark:hover:bg-charcoal-grey text-rosso-corsa hover:bg-bright-gray'
                  : 'dark:text-bright-gray dark:hover:bg-charcoal-grey text-eerie-black hover:bg-bright-gray'
              }
            `}
          >
            {option.icon && (
              <img
                width={option.iconWidth || 16}
                height={option.iconHeight || 16}
                src={option.icon}
                alt={option.label}
                className={`cursor-pointer hover:opacity-75 ${option.iconClassName || ''}`}
              />
            )}
            <span>{option.label}</span>
          </button>
        ))}
      </div>
    </div>
  );
}
