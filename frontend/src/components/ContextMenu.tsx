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
  anchorRef: React.RefObject<HTMLDivElement | null>;
  position?: 'bottom-left' | 'bottom-right' | 'top-left' | 'top-right';
  offset?: { x: number; y: number };
  className?: string;
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
    if (isOpen && menuRef.current) {
      const positionStyle = getMenuPosition();
      if (menuRef.current) {
        Object.assign(menuRef.current.style, {
          top: positionStyle.top,
          left: positionStyle.left,
        });
      }
    }
  }, [isOpen]);
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

    // Get menu dimensions (need ref to be available)
    const menuWidth = menuRef.current?.offsetWidth || 144; // Default min-width
    const menuHeight = menuRef.current?.offsetHeight || 0;

    // Get viewport dimensions
    const viewportWidth = window.innerWidth;
    const viewportHeight = window.innerHeight;

    // Adjust position based on specified position
    switch (position) {
      case 'bottom-left':
        left = rect.left + scrollX - offset.x;
        break;
      case 'top-right':
        top = rect.top + scrollY - offset.y - menuHeight;
        break;
      case 'top-left':
        top = rect.top + scrollY - offset.y - menuHeight;
        left = rect.left + scrollX - offset.x;
        break;
      // bottom-right is default
    }

    if (left + menuWidth > viewportWidth) {
      left = Math.max(5, viewportWidth - menuWidth - 5);
    }

    if (left < 5) {
      left = 5;
    }

    if (top + menuHeight > viewportHeight + scrollY) {
      top = rect.top + scrollY - menuHeight - offset.y;
    }

    if (top < scrollY + 5) {
      top = rect.bottom + scrollY + offset.y;
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
        className="bg-lotion dark:bg-charleston-green-2 flex flex-col rounded-xl text-sm shadow-xl"
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
            className={`flex items-center justify-start gap-4 p-3 transition-colors duration-200 ease-in-out ${index === 0 ? 'rounded-t-xl' : ''} ${index === options.length - 1 ? 'rounded-b-xl' : ''} ${
              option.variant === 'danger'
                ? 'text-rosso-corsa hover:bg-bright-gray dark:text-red-2000 dark:hover:bg-charcoal-grey/20'
                : 'text-eerie-black hover:bg-bright-gray dark:text-bright-gray dark:hover:bg-charcoal-grey/20'
            } `}
          >
            {option.icon && (
              <div className="flex w-4 min-w-4 shrink-0 justify-center">
                <img
                  width={option.iconWidth || 16}
                  height={option.iconHeight || 16}
                  src={option.icon}
                  alt={option.label}
                  className={`cursor-pointer ${option.iconClassName || ''}`}
                />
              </div>
            )}
            <span className="break-words hyphens-auto">{option.label}</span>
          </button>
        ))}
      </div>
    </div>
  );
}
