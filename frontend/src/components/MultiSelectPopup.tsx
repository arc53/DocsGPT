import React, { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';

import CheckmarkIcon from '../assets/checkmark.svg';
import NoFilesDarkIcon from '../assets/no-files-dark.svg';
import NoFilesIcon from '../assets/no-files.svg';
import { useDarkTheme } from '../hooks';
import Input from './Input';

export type OptionType = {
  id: string | number;
  label: string;
  icon?: string | React.ReactNode;
  [key: string]: any;
};

type MultiSelectPopupProps = {
  isOpen: boolean;
  onClose: () => void;
  anchorRef: React.RefObject<HTMLElement | null>;
  options: OptionType[];
  selectedIds: Set<string | number>;
  onSelectionChange: (newSelectedIds: Set<string | number>) => void;
  title?: string;
  searchPlaceholder?: string;
  noOptionsMessage?: string;
  loading?: boolean;
  footerContent?: React.ReactNode;
  showSearch?: boolean;
  singleSelect?: boolean;
};

export default function MultiSelectPopup({
  isOpen,
  onClose,
  anchorRef,
  options,
  selectedIds,
  onSelectionChange,
  title,
  searchPlaceholder,
  noOptionsMessage,
  loading = false,
  footerContent,
  showSearch = true,
  singleSelect = false,
}: MultiSelectPopupProps) {
  const { t } = useTranslation();
  const [isDarkTheme] = useDarkTheme();

  const popupRef = useRef<HTMLDivElement>(null);

  const [searchTerm, setSearchTerm] = useState('');
  const [popupPosition, setPopupPosition] = useState({
    top: 0,
    left: 0,
    maxHeight: 0,
    showAbove: false,
  });

  const filteredOptions = options.filter((option) =>
    option.label.toLowerCase().includes(searchTerm.toLowerCase()),
  );

  const handleOptionClick = (optionId: string | number) => {
    let newSelectedIds: Set<string | number>;
    if (singleSelect) newSelectedIds = new Set<string | number>();
    else newSelectedIds = new Set(selectedIds);
    if (newSelectedIds.has(optionId)) {
      newSelectedIds.delete(optionId);
    } else newSelectedIds.add(optionId);
    onSelectionChange(newSelectedIds);
  };

  const renderIcon = (icon: string | React.ReactNode) => {
    if (typeof icon === 'string') {
      if (icon.startsWith('/') || icon.startsWith('http')) {
        return (
          <img
            src={icon}
            alt=""
            className="mr-3 h-5 w-5 shrink-0"
            aria-hidden="true"
          />
        );
      }
      return (
        <span className="mr-3 h-5 w-5 shrink-0" aria-hidden="true">
          {icon}
        </span>
      );
    }
    return <span className="mr-3 shrink-0">{icon}</span>;
  };

  useLayoutEffect(() => {
    if (!isOpen || !anchorRef.current) return;

    const updatePosition = () => {
      if (!anchorRef.current) return;

      const rect = anchorRef.current.getBoundingClientRect();
      const viewportHeight = window.innerHeight;
      const viewportWidth = window.innerWidth;
      const popupPadding = 16;
      const popupMinWidth = 300;
      const popupMaxWidth = 462;
      const popupDefaultHeight = 300;

      const spaceAbove = rect.top;
      const spaceBelow = viewportHeight - rect.bottom;
      const showAbove =
        spaceBelow < popupDefaultHeight && spaceAbove >= popupDefaultHeight;

      const maxHeight = Math.max(
        150,
        showAbove ? spaceAbove - popupPadding : spaceBelow - popupPadding,
      );

      const availableWidth = viewportWidth - 20;
      const calculatedWidth = Math.min(popupMaxWidth, availableWidth);

      let left = rect.left;
      if (left + calculatedWidth > viewportWidth - 10) {
        left = viewportWidth - calculatedWidth - 10;
      }
      left = Math.max(10, left);

      setPopupPosition({
        top: showAbove ? rect.top - 8 : rect.bottom + 8,
        left: left,
        maxHeight: Math.min(600, maxHeight),
        showAbove,
      });
    };

    updatePosition();
    window.addEventListener('resize', updatePosition);
    window.addEventListener('scroll', updatePosition, true);

    return () => {
      window.removeEventListener('resize', updatePosition);
      window.removeEventListener('scroll', updatePosition, true);
    };
  }, [isOpen, anchorRef]);

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (
        popupRef.current &&
        !popupRef.current.contains(event.target as Node) &&
        anchorRef.current &&
        !anchorRef.current.contains(event.target as Node)
      )
        onClose();
    };
    if (isOpen) document.addEventListener('mousedown', handleClickOutside);
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, [onClose, anchorRef, isOpen]);

  useEffect(() => {
    if (!isOpen) setSearchTerm('');
  }, [isOpen]);

  if (!isOpen) return null;
  return (
    <div
      ref={popupRef}
      className="border-light-silver bg-lotion dark:border-dim-gray dark:bg-charleston-green-2 fixed z-9999 flex flex-col rounded-lg border shadow-[0px_9px_46px_8px_#0000001F,0px_24px_38px_3px_#00000024,0px_11px_15px_-7px_#00000033]"
      style={{
        top: popupPosition.showAbove ? undefined : popupPosition.top,
        bottom: popupPosition.showAbove
          ? window.innerHeight - popupPosition.top + 8
          : undefined,
        left: popupPosition.left,
        maxWidth: `${Math.min(462, window.innerWidth - 20)}px`,
        width: '100%',
        maxHeight: `${popupPosition.maxHeight}px`,
      }}
    >
      {(title || showSearch) && (
        <div className="shrink-0 p-4">
          {title && (
            <h3 className="mb-4 text-lg font-medium text-gray-900 dark:text-white">
              {title}
            </h3>
          )}
          {showSearch && (
            <Input
              id="multi-select-search"
              name="multi-select-search"
              type="text"
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              placeholder={
                searchPlaceholder ||
                t('settings.tools.searchPlaceholder', 'Search...')
              }
              labelBgClassName="bg-lotion dark:bg-charleston-green-2"
              borderVariant="thin"
              className="mb-4"
              textSize="small"
            />
          )}
        </div>
      )}
      <div className="dark:border-dim-gray mx-4 mb-4 grow overflow-auto rounded-md border border-[#D9D9D9]">
        {loading ? (
          <div className="flex h-full items-center justify-center py-4">
            <div className="h-6 w-6 animate-spin rounded-full border-b-2 border-gray-900 dark:border-white"></div>
          </div>
        ) : (
          <div className="h-full overflow-y-auto [&::-webkit-scrollbar]:w-2 [&::-webkit-scrollbar-thumb]:rounded-full [&::-webkit-scrollbar-thumb]:bg-gray-400 dark:[&::-webkit-scrollbar-thumb]:bg-gray-600 [&::-webkit-scrollbar-track]:bg-gray-200 dark:[&::-webkit-scrollbar-track]:bg-[#2C2E3C]">
            {filteredOptions.length === 0 ? (
              <div className="flex h-full flex-col items-center justify-center px-4 py-8 text-center">
                <img
                  src={isDarkTheme ? NoFilesDarkIcon : NoFilesIcon}
                  alt="No options found"
                  className="mx-auto mb-3 h-16 w-16"
                />
                <p className="text-sm text-gray-500 dark:text-gray-400">
                  {searchTerm
                    ? 'No results found'
                    : noOptionsMessage || 'No options available'}
                </p>
              </div>
            ) : (
              filteredOptions.map((option) => {
                const isSelected = selectedIds.has(option.id);
                return (
                  <div
                    key={option.id}
                    onClick={() => handleOptionClick(option.id)}
                    className="dark:border-dim-gray dark:hover:bg-charleston-green-3 flex cursor-pointer items-center justify-between border-b border-[#D9D9D9] p-3 last:border-b-0 hover:bg-gray-100"
                    role="option"
                    aria-selected={isSelected}
                  >
                    <div className="mr-3 flex grow items-center overflow-hidden">
                      {option.icon && renderIcon(option.icon)}
                      <p
                        className="overflow-hidden text-sm font-medium text-ellipsis whitespace-nowrap text-gray-900 dark:text-white"
                        title={option.label}
                      >
                        {option.label}
                      </p>
                    </div>
                    <div className="shrink-0">
                      <div
                        className={`dark:bg-charleston-green-2 flex h-4 w-4 items-center justify-center rounded-xs border border-[#C6C6C6] bg-white dark:border-[#757783]`}
                        aria-hidden="true"
                      >
                        {isSelected && (
                          <img
                            src={CheckmarkIcon}
                            alt="checkmark"
                            width={10}
                            height={10}
                          />
                        )}
                      </div>
                    </div>
                  </div>
                );
              })
            )}
          </div>
        )}
      </div>
      {footerContent && (
        <div className="border-light-silver dark:border-dim-gray shrink-0 border-t p-4">
          {footerContent}
        </div>
      )}
    </div>
  );
}
