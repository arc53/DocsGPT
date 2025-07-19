import React from 'react';

import Arrow2 from '../assets/dropdown-arrow.svg';
import Edit from '../assets/edit.svg';
import Trash from '../assets/trash.svg';
import { DropdownOption, DropdownProps } from './types/Dropdown.types';

function Dropdown<T extends DropdownOption>({
  options,
  selectedValue,
  onSelect,
  size = 'w-32',
  rounded = 'xl',
  buttonClassName = 'border-silver bg-white dark:bg-transparent dark:border-dim-gray',
  optionsClassName = 'border-silver bg-white dark:border-dim-gray dark:bg-dark-charcoal',
  border = 'border-2',
  showEdit,
  onEdit,
  showDelete,
  onDelete,
  placeholder,
  placeholderClassName = 'text-gray-500 dark:text-gray-400',
  contentSize = 'text-base',
}: DropdownProps<T>) {
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
        className={`flex w-full cursor-pointer items-center justify-between ${border} ${buttonClassName} px-5 py-3 ${
          isOpen ? `${borderTopRadius}` : `${borderRadius}`
        }`}
      >
        {typeof selectedValue === 'string' ? (
          <span className="dark:text-bright-gray truncate">
            {selectedValue}
          </span>
        ) : (
          <span
            className={`truncate ${selectedValue && `dark:text-bright-gray`} ${
              !selectedValue && ` ${placeholderClassName}`
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
          className={`absolute right-0 left-0 z-20 -mt-1 max-h-40 overflow-y-auto rounded-b-xl ${border} ${optionsClassName} shadow-lg`}
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
                className={`dark:text-light-gray ml-5 flex-1 overflow-hidden py-3 text-ellipsis whitespace-nowrap ${contentSize}`}
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
