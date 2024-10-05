import React from 'react';
import Arrow2 from '../assets/dropdown-arrow.svg';
import Edit from '../assets/edit.svg';
import Trash from '../assets/trash.svg';

function Dropdown({
  options,
  selectedValue,
  onSelect,
  size = 'w-32',
  rounded = 'xl',
  border = 'border-2',
  borderColor = 'silver',
  showEdit,
  onEdit,
  showDelete,
  onDelete,
  placeholder,
  contentSize = 'text-base',
}: {
  options:
    | string[]
    | { name: string; id: string; type: string }[]
    | { label: string; value: string }[]
    | { value: number; description: string }[];
  selectedValue:
    | string
    | { label: string; value: string }
    | { value: number; description: string }
    | { name: string; id: string; type: string }
    | null;
  onSelect:
    | ((value: string) => void)
    | ((value: { name: string; id: string; type: string }) => void)
    | ((value: { label: string; value: string }) => void)
    | ((value: { value: number; description: string }) => void);
  size?: string;
  rounded?: 'xl' | '3xl';
  border?: 'border' | 'border-2';
  borderColor?: string;
  showEdit?: boolean;
  onEdit?: (value: { name: string; id: string; type: string }) => void;
  showDelete?: boolean;
  onDelete?: (value: string) => void;
  placeholder?: string;
  contentSize?: string;
}) {
  const dropdownRef = React.useRef<HTMLDivElement>(null);
  const [isOpen, setIsOpen] = React.useState(false);
  const [dropdownPosition, setDropdownPosition] = React.useState({ top: 0});
  
  const borderRadius = rounded === 'xl' ? 'rounded-xl' : 'rounded-3xl';
  const borderTopRadius = rounded === 'xl' ? 'rounded-t-xl' : 'rounded-t-3xl';

  const handleClickOutside = (event: MouseEvent) => {
    if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
      setIsOpen(false);
    }
  };

  React.useEffect(() => {
    document.addEventListener('mousedown', handleClickOutside);
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, []);

  const handleToggleDropdown = () => {
    setIsOpen(prev => !prev);
    if (!isOpen) {
      adjustDropdownPosition();
    }
  };

  const adjustDropdownPosition = () => {
    if (dropdownRef.current) {
      const rect = dropdownRef.current.getBoundingClientRect();
      const dropdownMenuHeight = Math.min(200, options.length * 40); // Adjust height based on options
      const viewportHeight = window.innerHeight;

      // Check if dropdown overflows the bottom of the viewport
      const newPosition = {
        top: rect.bottom + dropdownMenuHeight > viewportHeight ? -dropdownMenuHeight : 0,
        left: 0,
      };

      setDropdownPosition(newPosition);
    }
  };

  return (
    <div
      className={[typeof selectedValue === 'string' ? 'relative mt-2' : 'relative align-middle', size].join(' ')}
      ref={dropdownRef}
    >
      <button
        onClick={handleToggleDropdown}
        className={`flex w-full cursor-pointer items-center justify-between ${border} border-${borderColor} bg-white px-5 py-3 dark:border-${borderColor}/40 dark:bg-transparent ${isOpen ? borderTopRadius : borderRadius}`}
      >
        <span className={`truncate dark:text-bright-gray ${contentSize}`}>
          {selectedValue && 'label' in selectedValue ? selectedValue.label : placeholder}
        </span>
        <img src={Arrow2} alt="arrow" className={`transform ${isOpen ? 'rotate-180' : 'rotate-0'} h-3 w-3 transition-transform`} />
      </button>
      {isOpen && (
        <div
          className={`absolute left-0 right-0 z-20 -mt-1 max-h-40 overflow-y-auto rounded-b-xl ${border} border-${borderColor} bg-white shadow-lg dark:border-${borderColor}/40 dark:bg-dark-charcoal`}
          style={{
            transform: `translateY(${dropdownPosition.top}px)`, // Adjust Y position
          }}
        >
          {options.map((option: any, index) => (
            <div
              key={index}
              className="hover:eerie-black flex cursor-pointer items-center justify-between hover:bg-gray-100 dark:hover:bg-purple-taupe"
            >
              <span
                onClick={() => {
                  onSelect(option);
                  setIsOpen(false);
                }}
                className={`ml-5 flex-1 overflow-hidden overflow-ellipsis whitespace-nowrap py-3 dark:text-light-gray ${contentSize}`}
              >
                {typeof option === 'string' ? option : option.name || option.label || option.description}
              </span>
              {showEdit && onEdit && (
                <img
                  src={Edit}
                  alt="Edit"
                  className="mr-4 h-4 w-4 cursor-pointer hover:opacity-50"
                  onClick={() => {
                    onEdit(option);
                    setIsOpen(false);
                  }}
                />
              )}
              {showDelete && onDelete && (
                <button
                  onClick={() => onDelete(option.id)}
                  disabled={option.type === 'public'}
                >
                  <img
                    src={Trash}
                    alt="Delete"
                    className={`mr-2 h-4 w-4 cursor-pointer hover:opacity-50 ${option.type === 'public' ? 'cursor-not-allowed opacity-50' : ''}`}
                  />
                </button>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default Dropdown;
