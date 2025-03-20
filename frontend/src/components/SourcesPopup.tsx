import React, { useRef, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';
import { Doc } from '../models/misc';
import SourceIcon from '../assets/source.svg';
import CheckIcon from '../assets/checkmark.svg';
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
  const embeddingsName =
    import.meta.env.VITE_EMBEDDINGS_NAME ||
    'huggingface_sentence-transformers/all-mpnet-base-v2';

  const options = useSelector(selectSourceDocs);
  const selectedDocs = useSelector(selectSelectedDocs);

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
        <h2 className="text-lg font-bold text-[#141414] dark:text-bright-gray">
          {t('conversation.sources.text')}
        </h2>
      </div>

      <div className="overflow-y-auto h-[488px] mx-4 border border-[#D9D9D9] dark:border-purple-taupe rounded-md">
        {options ? (
          <>
            {options.map((option: any, index: number) => {
              if (option.model === embeddingsName) {
                return (
                  <div
                    key={index}
                    className="flex cursor-pointer items-center p-3 hover:bg-gray-100 dark:hover:bg-[#2C2E3C] transition-colors border-b border-[#D9D9D9] border-opacity-80"
                    onClick={() => {
                      dispatch(setSelectedDocs(option));
                      handlePostDocumentSelect(option);
                      onClose();
                    }}
                  >
                    <img
                      src={SourceIcon}
                      alt="Source"
                      className="w-5 h-5 mr-3"
                    />
                    <span className="text-[#5D5D5D] dark:text-bright-gray font-medium flex-grow overflow-hidden overflow-ellipsis whitespace-nowrap">
                      {option.name}
                    </span>
                    {selectedDocs && selectedDocs.id === option.id && (
                      <img
                        src={CheckIcon}
                        alt="Selected"
                        className="h-5 w-5 mr-2"
                      />
                    )}
                  </div>
                );
              }
              return null;
            })}
            <div
              className="flex cursor-pointer items-center p-3 hover:bg-gray-100 dark:hover:bg-[#2C2E3C] transition-colors border-b border-[#D9D9D9] border-opacity-80"
              onClick={handleEmptyDocumentSelect}
            >
              <img src={SourceIcon} alt="Source" className="w-5 h-5 mr-3" />
              <span className="text-[#5D5D5D] dark:text-bright-gray font-medium flex-grow">
                {t('none')}
              </span>
              {selectedDocs === null && (
                <img src={CheckIcon} alt="Selected" className="h-5 w-5 mr-2" />
              )}
            </div>
          </>
        ) : (
          <div className="p-4 text-center text-gray-500 dark:text-gray-400">
            {t('noSourcesAvailable')}
          </div>
        )}
      </div>

      <div className="px-6 py-3 flex justify-start">
        <button
          onClick={handleUploadClick}
          className="py-2 px-4 rounded-full border border-[#7D54D1] text-[#7D54D1] hover:bg-[#7D54D1] hover:text-white transition-colors duration-200 text-[14px] font-medium w-auto"
        >
          Upload new
        </button>
      </div>
    </div>
  );
}
