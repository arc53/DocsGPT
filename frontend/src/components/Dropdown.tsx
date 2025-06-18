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
  buttonBackgroundColor = 'white',
  buttonDarkBackgroundColor = 'transparent',
  optionsBackgroundColor = 'white',
  optionsDarkBackgroundColor = 'dark-charcoal',
  border = 'border-2',
  borderColor = 'silver',
  darkBorderColor = 'dim-gray',
  showEdit,
  onEdit,
  showDelete,
  onDelete,
  placeholder,
  placeholderTextColor = 'gray-500',
  darkPlaceholderTextColor = 'gray-400',
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
  buttonBackgroundColor?: string;
  buttonDarkBackgroundColor?: string;
  optionsBackgroundColor?: string;
  optionsDarkBackgroundColor?: string;
  border?: 'border' | 'border-2';
  borderColor?: string;
  darkBorderColor?: string;
  showEdit?: boolean;
  onEdit?: (value: { name: string; id: string; type: string }) => void;
  showDelete?: boolean | ((option: any) => boolean);
  onDelete?: (value: string) => void;
  placeholder?: string;
  placeholderTextColor?: string;
  darkPlaceholderTextColor?: string;
  contentSize?: string;
}) {
  const dropdownRef = React.useRef<HTMLDivElement>(null);
  const [isOpen, setIsOpen] = React.useState(false);
  const borderRadius = rounded === 'xl' ? 'rounded-xl' : 'rounded-3xl';
  const borderTopRadius = rounded === 'xl' ? 'rounded-t-xl' : 'rounded-t-3xl';

  const handleClickOutside = (event: MouseEvent) => {
    if (
      dropdownRef.current &&
      !dropdownRef.current.contains(event.target as Node)
    ) {
      setIsOpen(false);
    }
  };

  React.useEffect(() => {
    document.addEventListener('mousedown', handleClickOutside);
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, []);
  return (
    <div
      className={[
        typeof selectedValue === 'string'
          ? 'relative'
          : 'relative align-middle',
        size,
      ].join(' ')}
      ref={dropdownRef}
    >
      <button
        onClick={() => setIsOpen(!isOpen)}
        className={`flex w-full cursor-pointer items-center justify-between ${border} border-${borderColor} bg-${buttonBackgroundColor} px-5 py-3 dark:border-${darkBorderColor} dark:bg-${buttonDarkBackgroundColor} ${
          isOpen ? `${borderTopRadius}` : `${borderRadius}`
        }`}
      >
        {typeof selectedValue === 'string' ? (
          <span className="truncate dark:text-bright-gray">
            {selectedValue}
          </span>
        ) : (
          <span
            className={`truncate ${selectedValue && `dark:text-bright-gray`} ${
              !selectedValue &&
              `text-${placeholderTextColor} dark:text-${darkPlaceholderTextColor}`
            } ${contentSize}`}
          >
            {selectedValue && 'label' in selectedValue
              ? selectedValue.label
              : selectedValue && 'description' in selectedValue
                ? `${
                    selectedValue.value < 1e9
                      ? selectedValue.value + ` (${selectedValue.description})`
                      : selectedValue.description
                  }`
                : placeholder
                  ? placeholder
                  : 'From URL'}
          </span>
        )}
        <img
          src={Arrow2}
          alt="arrow"
          className={`transform ${
            isOpen ? 'rotate-180' : 'rotate-0'
          } h-3 w-3 transition-transform`}
        />
      </button>
      {isOpen && (
        <div
          className={`absolute left-0 right-0 z-20 -mt-1 max-h-40 overflow-y-auto rounded-b-xl ${border} border-${borderColor} bg-${optionsBackgroundColor} shadow-lg dark:border-${darkBorderColor} dark:bg-${optionsDarkBackgroundColor}`}
        >
          {options.map((option: any, index) => (
            <div
              key={index}
              className="hover:eerie-black flex cursor-pointer items-center justify-between hover:bg-gray-100 dark:hover:bg-[#545561]"
            >
              <span
                onClick={() => {
                  onSelect(option);
                  setIsOpen(false);
                }}
                className={`ml-5 flex-1 overflow-hidden overflow-ellipsis whitespace-nowrap py-3 dark:text-light-gray ${contentSize}`}
              >
                {typeof option === 'string'
                  ? option
                  : option.name
                    ? option.name
                    : option.label
                      ? option.label
                      : `${
                          option.value < 1e9
                            ? option.value + ` (${option.description})`
                            : option.description
                        }`}
              </span>
              {showEdit && onEdit && option.type !== 'public' && (
                <img
                  src={Edit}
                  alt="Edit"
                  className="mr-4 h-4 w-4 cursor-pointer hover:opacity-50"
                  onClick={() => {
                    onEdit({
                      id: option.id,
                      name: option.name,
                      type: option.type,
                    });
                    setIsOpen(false);
                  }}
                />
              )}
              {showDelete && onDelete && (
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    onDelete?.(typeof option === 'string' ? option : option.id);
                  }}
                  className={`${
                    typeof showDelete === 'function' && !showDelete(option)
                      ? 'hidden'
                      : ''
                  } mr-2 h-4 w-4 cursor-pointer hover:opacity-50`}
                >
                  <img
                    src={Trash}
                    alt="Delete"
                    className={`mr-2 h-4 w-4 cursor-pointer hover:opacity-50 ${
                      option.type === 'public'
                        ? 'cursor-not-allowed opacity-50'
                        : ''
                    }`}
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
