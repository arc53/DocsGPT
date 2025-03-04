import React from 'react';

type DropdownMenuProps = {
  name: string;
  options: { label: string; value: string }[];
  onSelect: (value: string) => void;
  defaultValue?: string;
  icon?: string;
  isOpen?: boolean;
  onOpenChange?: (isOpen: boolean) => void;
  anchorRef?: React.RefObject<HTMLElement>;
  className?: string;
  position?: 'left' | 'right';
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
  className,
  position = 'left',
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
      !dropdownRef.current.contains(event.target as Node)
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
    document.addEventListener('mousedown', handleClickOutside);
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, []);

  return (
    <div className={`fixed ${className || ''}`} ref={dropdownRef}>
      <div
        className={`w-28 transform rounded-md bg-white dark:bg-dark-charcoal shadow-lg ring-1 ring-black ring-opacity-5 transition-all duration-200 ease-in-out ${
          isOpen
            ? 'scale-100 opacity-100'
            : 'pointer-events-none scale-95 opacity-0'
        }`}
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
    </div>
  );
}
