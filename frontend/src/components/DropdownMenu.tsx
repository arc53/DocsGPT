import React from 'react';
import ReactDOM from 'react-dom';

type DropdownMenuProps = {
  name: string;
  options: { label: string; value: string }[];
  onSelect: (value: string) => void;
  defaultValue?: string;
  icon?: string;
  isOpen: boolean;
  onOpenChange: (isOpen: boolean) => void;
  anchorRef: React.RefObject<HTMLElement | null>;
  position?: 'bottom-left' | 'bottom-right' | 'top-left' | 'top-right';
  offset?: { x: number; y: number };
  className?: string;
};

export default function DropdownMenu({
  name,
  options,
  onSelect,
  defaultValue = 'none',
  icon,
  isOpen: controlledIsOpen,
  onOpenChange,
  anchorRef,
  className = '',
  position = 'bottom-right',
  offset = { x: 0, y: 8 },
}: DropdownMenuProps) {
  const dropdownRef = React.useRef<HTMLDivElement>(null);
  const [internalIsOpen, setInternalIsOpen] = React.useState(false);
  const [selectedOption, setSelectedOption] = React.useState(
    options.find((option) => option.value === defaultValue) || options[0],
  );

  const isOpen =
    controlledIsOpen !== undefined ? controlledIsOpen : internalIsOpen;
  const setIsOpen = onOpenChange || setInternalIsOpen;

  const handleClickOutside = (event: MouseEvent) => {
    if (
      dropdownRef.current &&
      !dropdownRef.current.contains(event.target as Node) &&
      !anchorRef?.current?.contains(event.target as Node)
    ) {
      setIsOpen(false);
    }
  };

  const handleClickOption = (optionId: number) => {
    setIsOpen(false);
    setSelectedOption(options[optionId]);
    onSelect(options[optionId].value);
  };

  React.useEffect(() => {
    if (isOpen) {
      document.addEventListener('mousedown', handleClickOutside);
      return () =>
        document.removeEventListener('mousedown', handleClickOutside);
    }
  }, [isOpen]);

  if (!isOpen) return null;

  const getMenuPosition = (): React.CSSProperties => {
    if (!anchorRef?.current) return {};

    const rect = anchorRef.current.getBoundingClientRect();

    const top = rect.bottom + offset.y;
    const left = rect.right + offset.x;

    return {
      position: 'fixed',
      top: `${top}px`,
      left: `${left}px`,
      zIndex: 9999,
    };
  };

  // Use a portal to render the dropdown outside the table flow
  return ReactDOM.createPortal(
    <div
      ref={dropdownRef}
      style={{ ...getMenuPosition() }}
      onClick={(e) => e.stopPropagation()}
    >
      <div
        className={`w-28 transform rounded-md bg-white shadow-lg ring-1 ring-black ring-opacity-5 transition-all duration-200 ease-in-out dark:bg-dark-charcoal ${className}`}
      >
        <div
          role="menu"
          className="overflow-hidden rounded-md"
          aria-orientation="vertical"
          aria-labelledby="options-menu"
        >
          {options.map((option, idx) => (
            <div
              id={`option-${idx}`}
              className={`cursor-pointer px-4 py-2 text-xs hover:bg-gray-100 dark:text-light-gray dark:hover:bg-purple-taupe ${
                selectedOption.value === option.value
                  ? 'bg-gray-100 dark:bg-purple-taupe'
                  : 'bg-white dark:bg-dark-charcoal'
              }`}
              role="menuitem"
              key={option.value}
              onClick={() => handleClickOption(idx)}
            >
              {option.label}
            </div>
          ))}
        </div>
      </div>
    </div>,
    document.body,
  );
}
