import React, { useRef, useEffect, useState } from 'react';
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
  anchorRef: React.RefObject<HTMLButtonElement>;
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
  
  const embeddingsName =
    import.meta.env.VITE_EMBEDDINGS_NAME ||
    'huggingface_sentence-transformers/all-mpnet-base-v2';

  const options = useSelector(selectSourceDocs);
  const selectedDocs = useSelector(selectSelectedDocs);

  const filteredOptions = options?.filter(option => 
    option.name.toLowerCase().includes(searchTerm.toLowerCase())
  );

  const getPopupPosition = () => {
    if (!anchorRef.current) return {};

    const rect = anchorRef.current.getBoundingClientRect();

    return {
      position: 'fixed' as const,
      top: `${rect.top - 8}px`,
      left: `${rect.left}px`,
      minWidth: `${rect.width}px`,
      transform: 'translateY(-100%)',
    };
  };

  const handleEmptyDocumentSelect = () => {
    dispatch(setSelectedDocs(null));
    handlePostDocumentSelect(null);
    onClose();
  };

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
      style={getPopupPosition()}
      className="bg-lotion dark:bg-charleston-green-2 rounded-xl shadow-md w-full max-w-md flex flex-col z-50 absolute"
    >
      <div className="px-6 py-4">
        <h2 className="text-lg font-bold text-[#141414] dark:text-bright-gray mb-4 dark:text-[20px]">
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

      <div className="overflow-y-auto h-[488px] mx-4 border border-[#D9D9D9] dark:border-dim-gray rounded-md">
        {options ? (
          <>
            {filteredOptions?.map((option: any, index: number) => {
              if (option.model === embeddingsName) {
                return (
                  <div
                    key={index}
                    className="flex cursor-pointer items-center p-3 hover:bg-gray-100 dark:hover:bg-[#2C2E3C] transition-colors border-b border-[#D9D9D9] dark:border-dim-gray border-opacity-80 dark:text-[14px]"
                    onClick={() => {
                      dispatch(setSelectedDocs(option));
                      handlePostDocumentSelect(option);
                      onClose();
                    }}
                  >
                    <img
                      src={SourceIcon}
                      alt="Source"
                      width={14} height={14}
                      className="mr-3"
                    />
                    <span className="text-[#5D5D5D] dark:text-bright-gray font-medium flex-grow overflow-hidden overflow-ellipsis whitespace-nowrap">
                      {option.name}
                    </span>
                    {selectedDocs && selectedDocs.id === option.id && (
                      <img
                        src={CheckIcon}
                        alt="Selected"
                        className="h-3 w-3 mr-2"
                      />
                    )}
                  </div>
                );
              }
              return null;
            })}
            <div
              className="flex cursor-pointer items-center p-3 hover:bg-gray-100 dark:hover:bg-[#2C2E3C] transition-colors border-b border-[#D9D9D9] dark:border-dim-gray border-opacity-80 dark:text-[14px]"
              onClick={handleEmptyDocumentSelect}
            >
              <img width={14} height={14} src={SourceIcon} alt="Source" className="mr-3" />
              <span className="text-[#5D5D5D] dark:text-bright-gray font-medium flex-grow">
                {t('none')}
              </span>
              {selectedDocs === null && (
                <img src={CheckIcon} alt="Selected" className="h-5 w-5 mr-2" />
              )}
            </div>
          </>
        ) : (
          <div className="p-4 text-center text-gray-500 dark:text-bright-gray dark:text-[14px]">
            {t('noSourcesAvailable')}
          </div>
        )}
      </div>

      <div className="px-6 py-4 opacity-75 hover:opacity-100 transition-opacity duration-200">
        <a 
          href="/settings/documents" 
          className="text-violets-are-blue text-base font-medium flex items-center gap-2"
          onClick={onClose}
        >
          Go to Documents
          <img src={RedirectIcon} alt="Redirect" className="w-3 h-3" />
        </a>
      </div>

      <div className="px-6 py-3 flex justify-start">
        <button
          onClick={handleUploadClick}
          className="py-2 px-4 rounded-full border text-violets-are-blue hover:bg-violets-are-blue border-violets-are-blue hover:text-white transition-colors duration-200 text-[14px] font-medium w-auto"
        >
          Upload new
        </button>
      </div>
    </div>
  );
}
