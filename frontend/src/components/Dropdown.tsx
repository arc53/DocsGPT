import { useState } from 'react';
import Arrow2 from '../assets/dropdown-arrow.svg';

function Dropdown({
  options,
  selectedValue,
  onSelect,
  showDelete,
  onDelete,
}: {
  options:
    | string[]
    | { name: string; id: string; type: string }[]
    | { label: string; value: string }[];
  selectedValue: string | { label: string; value: string };
  onSelect:
    | ((value: string) => void)
    | ((value: { name: string; id: string; type: string }) => void)
    | ((value: { label: string; value: string }) => void);
  showDelete?: boolean;
  onDelete?: (value: string) => void;
}) {
  const [isOpen, setIsOpen] = useState(false);
  return (
    <div
      className={
        typeof selectedValue === 'string'
          ? 'relative mt-2 w-32'
          : 'relative w-full align-middle'
      }
    >
      <button
        onClick={() => setIsOpen(!isOpen)}
        className={`flex w-full cursor-pointer items-center justify-between border-2 bg-white p-3 dark:border-chinese-silver dark:bg-transparent ${
          isOpen
            ? typeof selectedValue === 'string'
              ? 'rounded-t-xl'
              : 'rounded-t-3xl'
            : typeof selectedValue === 'string'
            ? 'rounded-xl'
            : 'rounded-3xl'
        }`}
      >
        {typeof selectedValue === 'string' ? (
          <span className="flex-1 overflow-hidden text-ellipsis dark:text-bright-gray">
            {selectedValue}
          </span>
        ) : (
          <span
            className={`overflow-hidden text-ellipsis dark:text-bright-gray ${
              !selectedValue && 'text-silver'
            }`}
          >
            {selectedValue ? selectedValue.label : 'From URL'}
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
        <div className="absolute left-0 right-0 z-50 -mt-1 overflow-y-auto rounded-b-xl border-2 bg-white shadow-lg dark:border-chinese-silver dark:bg-dark-charcoal">
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
              {showDelete && onDelete && (
                <button onClick={() => onDelete(option)} className="p-2">
                  Delete
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
