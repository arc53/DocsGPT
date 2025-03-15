import { useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { useDarkTheme } from '../hooks';
import Send from '../assets/send.svg';
import SendDark from '../assets/send_dark.svg';
import SpinnerDark from '../assets/spinner-dark.svg';
import Spinner from '../assets/spinner.svg';

interface MessageInputProps {
  value: string;
  onChange: (e: React.ChangeEvent<HTMLTextAreaElement>) => void;
  onSubmit: () => void;
  loading: boolean;
}

export default function MessageInput({
  value,
  onChange,
  onSubmit,
  loading,
}: MessageInputProps) {
  const { t } = useTranslation();
  const [isDarkTheme] = useDarkTheme();
  const inputRef = useRef<HTMLTextAreaElement>(null);

  const handleInput = () => {
    if (inputRef.current) {
      if (window.innerWidth < 350) inputRef.current.style.height = 'auto';
      else inputRef.current.style.height = '64px';
      inputRef.current.style.height = `${Math.min(
        inputRef.current.scrollHeight,
        96,
      )}px`;
    }
  };

  // Focus the textarea and set initial height on mount.
  useEffect(() => {
    inputRef.current?.focus();
    handleInput();
  }, []);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      onSubmit();
      if (inputRef.current) {
        inputRef.current.value = '';
        handleInput();
      }
    }
  };

  return (
    <div className="flex w-full items-center rounded-[40px] border dark:border-grey border-dark-gray bg-lotion dark:bg-charleston-green-3">
      <label htmlFor="message-input" className="sr-only">
        {t('inputPlaceholder')}
      </label>
      <textarea
        id="message-input"
        ref={inputRef}
        value={value}
        onChange={onChange}
        tabIndex={1}
        placeholder={t('inputPlaceholder')}
        className="inputbox-style w-full overflow-y-auto overflow-x-hidden whitespace-pre-wrap rounded-full bg-lotion dark:bg-charleston-green-3 py-5 text-base leading-tight opacity-100 focus:outline-none dark:text-bright-gray dark:placeholder-bright-gray dark:placeholder-opacity-50 px-6"
        onInput={handleInput}
        onKeyDown={handleKeyDown}
        aria-label={t('inputPlaceholder')}
      />
      {loading ? (
        <img
          src={isDarkTheme ? SpinnerDark : Spinner}
          className="relative right-[38px] bottom-[24px] -mr-[30px] animate-spin cursor-pointer self-end bg-transparent"
          alt={t('loading')}
        />
      ) : (
        <div className="mx-1 cursor-pointer rounded-full p-3 text-center hover:bg-gray-3000 dark:hover:bg-dark-charcoal">
          <button
            onClick={onSubmit}
            aria-label={t('send')}
            className="flex items-center justify-center"
          >
            <img
              className="ml-[4px] h-6 w-6 text-white filter dark:invert-[0.45] invert-[0.35]"
              src={isDarkTheme ? SendDark : Send}
              alt={t('send')}
            />
          </button>
        </div>
      )}
    </div>
  );
}
