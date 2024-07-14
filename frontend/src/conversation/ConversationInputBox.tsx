import React, {
  ClipboardEvent,
  KeyboardEvent,
  useState,
  RefObject,
  useLayoutEffect,
} from 'react';
import Spinner from './../assets/spinner.svg';
import SpinnerDark from './../assets/spinner-dark.svg';
import Send from './../assets/send.svg';
import SendDark from './../assets/send_dark.svg';
import { useTranslation } from 'react-i18next';
import { PopupSelector } from '../components/PopupSelector';
import { useDispatch, useSelector } from 'react-redux';
import {
  selectSelectedDocs,
  selectSourceDocs,
  setSelectedDocs,
} from '../preferences/preferenceSlice';
import { Doc } from '../models/misc';
import { ConversationSourceList } from './ConversationSourceList';

export function ConversationInputBox({
  inputRef,
  onSubmit,
  handlePaste,
  isDarkTheme,
  status,
}: TConversationInputBox) {
  const [isPopupOpen, setIsPopupOpen] = useState(false);
  const [popupPosition, setPopupPosition] = useState({ top: 0, left: 0 });
  const docs = useSelector(selectSourceDocs);
  const selectedDocs = useSelector(selectSelectedDocs);
  const dispatch = useDispatch();
  const { t } = useTranslation();

  useLayoutEffect(() => {
    if (inputRef.current) {
      const rect = inputRef.current.getBoundingClientRect();
      setPopupPosition({
        top: rect.bottom + window.scrollY,
        left: rect.left + window.scrollX,
      });
    }
  }, []);

  const onPopupSelection = (selectedDocument: Doc) => {
    dispatch(setSelectedDocs(selectedDocument));
    setIsPopupOpen(false);
  };

  const onKeyDown = (e: KeyboardEvent) => {
    if (e.ctrlKey === true && e.key === 'd') {
      setIsPopupOpen(!isPopupOpen);
    } else {
      setIsPopupOpen(false);
    }
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      onSubmit();
    }
  };

  return (
    <div className="flex h-full w-full flex-col">
      <div className="mb-2 h-full w-full">
        <ConversationSourceList
          docs={isDoc(selectedDocs) ? [selectedDocs] : []}
        />
      </div>
      <div className="flex h-full w-full flex-row items-center rounded-[40px] border border-silver bg-white py-1 dark:bg-raisin-black">
        <PopupSelector
          isOpen={isPopupOpen}
          setIsPopupOpen={setIsPopupOpen}
          selectionItems={docs || []}
          positionTop={popupPosition.top}
          positionLeft={popupPosition.left}
          onSelect={onPopupSelection}
          headerText={t('selectADocument')}
        />
        <div
          id="inputbox"
          ref={inputRef}
          tabIndex={1}
          placeholder={t('inputPlaceholder')}
          contentEditable
          onPaste={handlePaste}
          className={`inputbox-style max-h-24 w-full overflow-y-auto overflow-x-hidden whitespace-pre-wrap rounded-full bg-white pt-5 pb-[22px] text-base leading-tight opacity-100 focus:outline-none dark:bg-raisin-black dark:text-bright-gray`}
          onKeyDown={onKeyDown}
        ></div>
        {status === 'loading' ? (
          <img
            src={isDarkTheme ? SpinnerDark : Spinner}
            className="relative right-[38px] bottom-[24px] -mr-[30px] animate-spin cursor-pointer self-end bg-transparent"
          ></img>
        ) : (
          <div className="mx-1 cursor-pointer rounded-full p-4 text-center hover:bg-gray-3000">
            <img
              className="w-6 text-white "
              onClick={onSubmit}
              src={isDarkTheme ? SendDark : Send}
            ></img>
          </div>
        )}
      </div>
    </div>
  );
}

//TODO: There may be a bug where if page is loaded with "None" source docs selected then the initial value of
//selectedDocs in the global data store is an array.  This case is not caught as a TS error this array is passed
//unexpectedly even though it has a type set to Doc.  This type check is used to counteract this unexpected behavior in
//the mean time.
function isDoc(doc: Doc | unknown): doc is Doc {
  return !!doc && (doc as Doc).name !== undefined;
}

type TConversationInputBox = {
  inputRef: RefObject<HTMLDivElement>;
  handlePaste: (e: ClipboardEvent) => void;
  onSubmit: () => void;
  isDarkTheme?: boolean;
  status: string;
};
