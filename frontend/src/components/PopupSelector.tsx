import React, { useRef } from 'react';
import { useOutsideAlerter } from '../hooks';

export function PopupSelector<SelectionItems extends { name: string }>({
  isOpen = false,
  setIsPopupOpen,
  positionTop = 0,
  positionLeft = 0,
  headerText,
  onSelect,
  selectionItems,
}: TPopupSelector<SelectionItems>) {
  const popupRef = useRef<HTMLDivElement>(null);
  useOutsideAlerter(popupRef, () => setIsPopupOpen(false), [], true);

  return isOpen ? (
    <div
      className={`absolute h-32 w-128 top=${positionTop} left-${positionLeft} z-20 -mt-52 overflow-y-auto rounded-b-xl rounded-t-xl border-2 border-silver bg-white shadow-lg dark:border-silver/40 dark:bg-dark-charcoal`}
      ref={popupRef}
    >
      {headerText && (
        <div className="mt-2 flex items-center justify-between">
          <span className="ml-4 flex-1 text-gray-500">{headerText}</span>
        </div>
      )}
      {selectionItems.map((item, idx) => {
        return (
          <div
            key={idx}
            className="flex cursor-pointer items-center justify-between hover:bg-gray-100 dark:text-bright-gray dark:hover:bg-purple-taupe"
            onClick={() => onSelect(item)}
          >
            <span className="ml-4 flex-1 overflow-hidden overflow-ellipsis whitespace-nowrap py-3">
              {item.name}
            </span>
          </div>
        );
      })}
    </div>
  ) : (
    <div></div>
  );
}

type TPopupSelector<SelectionItem> = {
  isOpen: boolean;
  setIsPopupOpen: React.Dispatch<React.SetStateAction<boolean>>;
  onSelect: (item: SelectionItem) => void;
  selectionItems: SelectionItem[];
  positionTop: number;
  positionLeft: number;
  handleOutsideClick?: () => void;
  headerText?: string;
};
