import React, { useRef, useEffect, useState, useLayoutEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';
import { Doc } from '../models/misc';
import SourceIcon from '../assets/source.svg';
import CheckIcon from '../assets/checkmark.svg';
import RedirectIcon from '../assets/redirect.svg';
import Input from './Input';
import {
  selectSourceDocs,
  selectSelectedDocs,
  setSelectedDocs,
} from '../preferences/preferenceSlice';
import { ActiveState } from '../models/misc';

type SourcesPopupProps = {
  isOpen: boolean;
  onClose: () => void;
  anchorRef: React.RefObject<HTMLButtonElement | null>;
  handlePostDocumentSelect: (doc: Doc | null) => void;
  setUploadModalState: React.Dispatch<React.SetStateAction<ActiveState>>;
};

export default function SourcesPopup({
  isOpen,
  onClose,
  anchorRef,
  handlePostDocumentSelect,
  setUploadModalState,
}: SourcesPopupProps) {
  const dispatch = useDispatch();
  const { t } = useTranslation();
  const popupRef = useRef<HTMLDivElement>(null);
  const [searchTerm, setSearchTerm] = useState('');
  const [popupPosition, setPopupPosition] = useState({
    top: 0,
    left: 0,
    maxHeight: 0,
    showAbove: false,
  });

  const embeddingsName =
    import.meta.env.VITE_EMBEDDINGS_NAME ||
    'huggingface_sentence-transformers/all-mpnet-base-v2';

  const options = useSelector(selectSourceDocs);
  const selectedDocs = useSelector(selectSelectedDocs);

  const filteredOptions = options?.filter((option) =>
    option.name.toLowerCase().includes(searchTerm.toLowerCase()),
  );

  useLayoutEffect(() => {
    if (!isOpen || !anchorRef.current) return;

    const updatePosition = () => {
      if (!anchorRef.current) return;

      const rect = anchorRef.current.getBoundingClientRect();
      const viewportHeight = window.innerHeight;
      const viewportWidth = window.innerWidth;
      const spaceAbove = rect.top;
      const spaceBelow = viewportHeight - rect.bottom;
      const showAbove = spaceAbove > spaceBelow && spaceAbove >= 300;
      const maxHeight = showAbove ? spaceAbove - 16 : spaceBelow - 16;
      const left = Math.min(
        rect.left,
        viewportWidth - Math.min(480, viewportWidth * 0.95) - 10,
      );

      setPopupPosition({
        top: showAbove ? rect.top - 8 : rect.bottom + 8,
        left,
        maxHeight: Math.min(600, maxHeight),
        showAbove,
      });
    };

    updatePosition();
    window.addEventListener('resize', updatePosition);
    return () => window.removeEventListener('resize', updatePosition);
  }, [isOpen, anchorRef]);

  const handleClickOutside = (event: MouseEvent) => {
    if (
      popupRef.current &&
      !popupRef.current.contains(event.target as Node) &&
      !anchorRef.current?.contains(event.target as Node)
    ) {
      onClose();
    }
  };

  useEffect(() => {
    if (isOpen) {
      document.addEventListener('mousedown', handleClickOutside);
    }
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, [isOpen]);

  if (!isOpen) return null;

  const handleUploadClick = () => {
    setUploadModalState('ACTIVE');
    onClose();
  };

  return (
    <div
      ref={popupRef}
      className="bg-lotion dark:bg-charleston-green-2 fixed z-50 flex flex-col rounded-xl shadow-[0px_9px_46px_8px_#0000001F,0px_24px_38px_3px_#00000024,0px_11px_15px_-7px_#00000033]"
      style={{
        top: popupPosition.showAbove ? popupPosition.top : undefined,
        bottom: popupPosition.showAbove
          ? undefined
          : window.innerHeight - popupPosition.top,
        left: popupPosition.left,
        maxWidth: Math.min(480, window.innerWidth * 0.95),
        width: '100%',
        height: popupPosition.maxHeight,
        transform: popupPosition.showAbove ? 'translateY(-100%)' : 'none',
      }}
    >
      <div className="flex h-full flex-col">
        <div className="shrink-0 px-4 py-4 md:px-6">
          <h2 className="dark:text-bright-gray mb-4 text-lg font-bold text-[#141414] dark:text-[20px]">
            {t('conversation.sources.text')}
          </h2>

          <Input
            id="source-search"
            name="source-search"
            type="text"
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            placeholder={t('settings.documents.searchPlaceholder')}
            borderVariant="thin"
            className="mb-4"
            labelBgClassName="bg-lotion dark:bg-charleston-green-2"
          />
        </div>

        <div className="dark:border-dim-gray mx-4 grow overflow-y-auto rounded-md border border-[#D9D9D9] [&::-webkit-scrollbar-thumb]:bg-[#888] [&::-webkit-scrollbar-thumb]:hover:bg-[#555] [&::-webkit-scrollbar-track]:bg-[#E2E8F0] dark:[&::-webkit-scrollbar-track]:bg-[#2C2E3C]">
          {options ? (
            <>
              {filteredOptions?.map((option: any, index: number) => {
                if (option.model === embeddingsName) {
                  const isSelected =
                    selectedDocs &&
                    (option.id
                      ? selectedDocs.id === option.id
                      : selectedDocs.date === option.date);

                  return (
                    <div
                      key={index}
                      className="border-opacity-80 dark:border-dim-gray flex cursor-pointer items-center border-b border-[#D9D9D9] p-3 transition-colors hover:bg-gray-100 dark:text-[14px] dark:hover:bg-[#2C2E3C]"
                      onClick={() => {
                        if (isSelected) {
                          dispatch(setSelectedDocs(null));
                          handlePostDocumentSelect(null);
                        } else {
                          dispatch(setSelectedDocs(option));
                          handlePostDocumentSelect(option);
                        }
                      }}
                    >
                      <img
                        src={SourceIcon}
                        alt="Source"
                        width={14}
                        height={14}
                        className="mr-3 shrink-0"
                      />
                      <span className="dark:text-bright-gray mr-3 grow overflow-hidden font-medium text-ellipsis whitespace-nowrap text-[#5D5D5D]">
                        {option.name}
                      </span>
                      <div
                        className={`flex h-4 w-4 shrink-0 items-center justify-center border border-[#C6C6C6] p-[0.5px] dark:border-[#757783]`}
                      >
                        {isSelected && (
                          <img
                            src={CheckIcon}
                            alt="Selected"
                            className="h-3 w-3"
                          />
                        )}
                      </div>
                    </div>
                  );
                }
                return null;
              })}
            </>
          ) : (
            <div className="dark:text-bright-gray p-4 text-center text-gray-500 dark:text-[14px]">
              {t('noSourcesAvailable')}
            </div>
          )}
        </div>

        <div className="shrink-0 px-4 py-4 opacity-75 transition-opacity duration-200 hover:opacity-100 md:px-6">
          <a
            href="/settings/documents"
            className="text-violets-are-blue inline-flex items-center gap-2 text-base font-medium"
            onClick={onClose}
          >
            {t('settings.documents.goToDocuments')}
            <img src={RedirectIcon} alt="Redirect" className="h-3 w-3" />
          </a>
        </div>

        <div className="flex shrink-0 justify-start px-4 py-3 md:px-6">
          <button
            onClick={handleUploadClick}
            className="border-violets-are-blue text-violets-are-blue hover:bg-violets-are-blue w-auto rounded-full border px-4 py-2 text-[14px] font-medium transition-colors duration-200 hover:text-white"
          >
            {t('settings.documents.uploadNew')}
          </button>
        </div>
      </div>
    </div>
  );
}
