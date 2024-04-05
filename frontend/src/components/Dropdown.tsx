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
  showEdit,
  onEdit,
  showDelete,
  onDelete,
  placeholder,
  fullWidth,
  alignMidddle,
}: {
  options:
    | string[]
    | { name: string; id: string; type: string }[]
    | { label: string; value: string }[];
  selectedValue: string | { label: string; value: string } | null;
  onSelect:
    | ((value: string) => void)
    | ((value: { name: string; id: string; type: string }) => void)
    | ((value: { label: string; value: string }) => void);
  size?: string;
  rounded?: 'xl' | '3xl';
  showEdit?: boolean;
  onEdit?: (value: { name: string; id: string; type: string }) => void;
  showDelete?: boolean;
  onDelete?: (value: string) => void;
  placeholder?: string;
  fullWidth?: boolean;
  alignMidddle?: boolean;
}) {
  const [isOpen, setIsOpen] = React.useState(false);
  return (
    <div
      className={[
        typeof selectedValue === 'string'
          ? 'relative mt-2'
          : 'relative align-middle',
        size,
      ].join(' ')}
    >
      <button
        onClick={() => setIsOpen(!isOpen)}
        className={`flex w-full cursor-pointer items-center justify-between border-2 bg-white px-5 py-3 dark:border-chinese-silver dark:bg-transparent ${
          isOpen ? `rounded-t-${rounded}` : `rounded-${rounded}`
        }`}
      >
        {typeof selectedValue === 'string' ? (
          <span className="overflow-hidden text-ellipsis dark:text-bright-gray">
            {selectedValue}
          </span>
        ) : (
          <span
            className={`${
              alignMidddle && 'flex-1'
            } overflow-hidden text-ellipsis dark:text-bright-gray ${
              !selectedValue && 'text-silver dark:text-gray-400'
            }`}
          >
            {selectedValue
              ? selectedValue.label
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
        <div className="absolute left-0 right-0 z-20 -mt-1 max-h-40 overflow-y-auto rounded-b-xl border-2 bg-white shadow-lg dark:border-chinese-silver dark:bg-dark-charcoal">
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
                className="ml-2 flex-1 overflow-hidden overflow-ellipsis whitespace-nowrap py-3 dark:text-light-gray"
              >
                {typeof option === 'string'
                  ? option
                  : option.name
                  ? option.name
                  : option.label}
              </span>
              {showEdit && onEdit && (
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
                  onClick={() => onDelete(option.id)}
                  disabled={option.type === 'public'}
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
