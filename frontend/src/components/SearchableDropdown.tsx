import React from 'react';

import Arrow2 from '../assets/dropdown-arrow.svg';
import Edit from '../assets/edit.svg';
import Search from '../assets/search.svg';
import Trash from '../assets/trash.svg';

/**
 * SearchableDropdown - A standalone dropdown component with built-in search functionality
 */

type SearchableDropdownOptionBase = {
  id?: string;
  type?: string;
};

type NameIdOption = { name: string; id: string } & SearchableDropdownOptionBase;

export type SearchableDropdownOption =
  | string
  | NameIdOption
  | ({ label: string; value: string } & SearchableDropdownOptionBase)
  | ({ value: number; description: string } & SearchableDropdownOptionBase);

export type SearchableDropdownSelectedValue = SearchableDropdownOption | null;

export interface SearchableDropdownProps<
  T extends SearchableDropdownOption = SearchableDropdownOption,
> {
  options: T[];
  selectedValue: SearchableDropdownSelectedValue;
  onSelect: (value: T) => void;
  size?: string;
  /** Controls border radius for both button and dropdown menu */
  rounded?: 'xl' | '3xl';
  border?: 'border' | 'border-2';
  showEdit?: boolean;
  onEdit?: (value: NameIdOption) => void;
  showDelete?: boolean | ((option: T) => boolean);
  onDelete?: (id: string) => void;
  placeholder?: string;
}

function SearchableDropdown<T extends SearchableDropdownOption>({
  options,
  selectedValue,
  onSelect,
  size = 'w-32',
  rounded = 'xl',
  border = 'border-2',
  showEdit,
  onEdit,
  showDelete,
  onDelete,
  placeholder,
}: SearchableDropdownProps<T>) {
  const dropdownRef = React.useRef<HTMLDivElement>(null);
  const searchInputRef = React.useRef<HTMLInputElement>(null);
  const [isOpen, setIsOpen] = React.useState(false);
  const [searchQuery, setSearchQuery] = React.useState('');

  const borderRadius = rounded === 'xl' ? 'rounded-xl' : 'rounded-3xl';

  React.useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (
        dropdownRef.current &&
        !dropdownRef.current.contains(event.target as Node)
      ) {
        setIsOpen(false);
        setSearchQuery('');
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  React.useEffect(() => {
    if (isOpen && searchInputRef.current) {
      searchInputRef.current.focus();
    }
  }, [isOpen]);

  const getOptionText = (option: SearchableDropdownOption): string => {
    if (typeof option === 'string') return option;
    if ('name' in option) return option.name;
    if ('label' in option) return option.label;
    if ('description' in option) return option.description;
    return '';
  };

  const filteredOptions = React.useMemo(() => {
    if (!searchQuery.trim()) return options;
    const query = searchQuery.toLowerCase();
    return options.filter((option) =>
      getOptionText(option).toLowerCase().includes(query),
    );
  }, [options, searchQuery]);

  const getDisplayValue = (): string => {
    if (!selectedValue) return placeholder ?? 'From URL';
    if (typeof selectedValue === 'string') return selectedValue;
    if ('label' in selectedValue) return selectedValue.label;
    if ('name' in selectedValue) return selectedValue.name;
    if ('description' in selectedValue) {
      return selectedValue.value < 1e9
        ? `${selectedValue.value} (${selectedValue.description})`
        : selectedValue.description;
    }
    return placeholder ?? 'From URL';
  };

  const isOptionSelected = (option: T): boolean => {
    if (!selectedValue) return false;
    if (typeof selectedValue === 'string')
      return selectedValue === (option as unknown as string);
    if (typeof option === 'string') return false;

    const optionObj = option as Record<string, unknown>;
    const selectedObj = selectedValue as Record<string, unknown>;

    if ('name' in optionObj && 'name' in selectedObj)
      return selectedObj.name === optionObj.name;
    if ('label' in optionObj && 'label' in selectedObj)
      return selectedObj.label === optionObj.label;
    if ('value' in optionObj && 'value' in selectedObj)
      return selectedObj.value === optionObj.value;
    return false;
  };

  return (
    <div
      className={`relative ${typeof selectedValue === 'string' ? '' : 'align-middle'} ${size}`}
      ref={dropdownRef}
    >
      <button
        onClick={() => setIsOpen(!isOpen)}
        className={`flex w-full cursor-pointer items-center justify-between ${border} border-silver bg-white px-5 py-3 dark:border-dim-gray dark:bg-transparent ${borderRadius}`}
      >
        <span
          className={`truncate dark:text-bright-gray ${!selectedValue ? 'text-gray-500 dark:text-gray-400' : ''}`}
        >
          {getDisplayValue()}
        </span>
        <img
          src={Arrow2}
          alt="arrow"
          className={`h-3 w-3 transform transition-transform ${isOpen ? 'rotate-180' : 'rotate-0'}`}
        />
      </button>

      {isOpen && (
        <div className={`absolute left-0 right-0 z-20 mt-2 ${borderRadius} bg-[#FBFBFB] shadow-[0px_24px_48px_0px_#00000029] dark:bg-dark-charcoal`}>
          <div className={`sticky top-0 z-10 border-b border-silver bg-[#FBFBFB] px-3 py-2 dark:border-dim-gray dark:bg-dark-charcoal ${rounded === 'xl' ? 'rounded-t-xl' : 'rounded-t-3xl'}`}>
            <div className="relative flex items-center">
              <img
                src={Search}
                alt="search"
                className="absolute left-3 h-4 w-4 opacity-50"
              />
              <input
                ref={searchInputRef}
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search..."
                className="w-full rounded-lg border-0 bg-transparent py-2 pl-10 pr-3 font-['Inter'] text-[14px] font-normal leading-[16.5px] focus:outline-none focus:ring-0 dark:text-bright-gray"
                onClick={(e) => e.stopPropagation()}
              />
            </div>
          </div>

          <div className="max-h-40 overflow-y-auto">
            {filteredOptions.length === 0 ? (
              <div className="px-5 py-3 text-center text-sm text-gray-500 dark:text-gray-400">
                No results found
              </div>
            ) : (
              filteredOptions.map((option, index) => {
                const selected = isOptionSelected(option);
                const optionObj =
                  typeof option !== 'string'
                    ? (option as Record<string, unknown>)
                    : null;
                const optionType = optionObj?.type as string | undefined;
                const optionId = optionObj?.id as string | undefined;
                const optionName = optionObj?.name as string | undefined;

                return (
                  <div
                    key={index}
                    className={`flex cursor-pointer items-center justify-between hover:bg-[#ECECEC] dark:hover:bg-[#545561] ${selected ? 'bg-[#ECECEC] dark:bg-[#545561]' : ''}`}
                  >
                    <span
                      onClick={() => {
                        onSelect(option);
                        setIsOpen(false);
                        setSearchQuery('');
                      }}
                      className="ml-5 flex-1 overflow-hidden text-ellipsis whitespace-nowrap py-3 font-['Inter'] text-[14px] font-normal leading-[16.5px] dark:text-light-gray"
                    >
                      {getOptionText(option)}
                    </span>
                    {showEdit &&
                      onEdit &&
                      optionObj &&
                      optionType !== 'public' && (
                        <img
                          src={Edit}
                          alt="Edit"
                          className="mr-4 h-4 w-4 cursor-pointer hover:opacity-50"
                          onClick={() => {
                            if (optionName && optionId) {
                              onEdit({
                                id: optionId,
                                name: optionName,
                                type: optionType,
                              });
                            }
                            setIsOpen(false);
                            setSearchQuery('');
                          }}
                        />
                      )}
                    {showDelete && onDelete && (
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          const id =
                            typeof option === 'string' ? option : optionId ?? '';
                          onDelete(id);
                        }}
                        className={`mr-2 h-4 w-4 cursor-pointer hover:opacity-50 ${
                          typeof showDelete === 'function' && !showDelete(option)
                            ? 'hidden'
                            : ''
                        }`}
                      >
                        <img
                          src={Trash}
                          alt="Delete"
                          className={`mr-2 h-4 w-4 cursor-pointer hover:opacity-50 ${
                            optionType === 'public'
                              ? 'cursor-not-allowed opacity-50'
                              : ''
                          }`}
                        />
                      </button>
                    )}
                  </div>
                );
              })
            )}
          </div>
        </div>
      )}
    </div>
  );
}

export default SearchableDropdown;

