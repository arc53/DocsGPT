import clsx from 'clsx';
import copy from 'copy-to-clipboard';
import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';

import CheckMark from '../assets/checkmark.svg?react';
import CopyIcon from '../assets/copy.svg?react';

type CopyButtonProps = {
  textToCopy: string;
  bgColorLight?: string;
  bgColorDark?: string;
  hoverBgColorLight?: string;
  hoverBgColorDark?: string;
  iconSize?: string;
  padding?: string;
  showText?: boolean;
  copiedDuration?: number;
  className?: string;
  iconWrapperClassName?: string;
  textClassName?: string;
};

const DEFAULT_ICON_SIZE = 'w-4 h-4';
const DEFAULT_PADDING = 'p-2';
const DEFAULT_COPIED_DURATION = 2000;
const DEFAULT_BG_LIGHT = '#FFFFFF';
const DEFAULT_BG_DARK = 'transparent';
const DEFAULT_HOVER_BG_LIGHT = '#EEEEEE';
const DEFAULT_HOVER_BG_DARK = '#4A4A4A';

export default function CopyButton({
  textToCopy,
  bgColorLight = DEFAULT_BG_LIGHT,
  bgColorDark = DEFAULT_BG_DARK,
  hoverBgColorLight = DEFAULT_HOVER_BG_LIGHT,
  hoverBgColorDark = DEFAULT_HOVER_BG_DARK,
  iconSize = DEFAULT_ICON_SIZE,
  padding = DEFAULT_PADDING,
  showText = false,
  copiedDuration = DEFAULT_COPIED_DURATION,
  className,
  iconWrapperClassName,
  textClassName,
}: CopyButtonProps) {
  const { t } = useTranslation();
  const [isCopied, setIsCopied] = useState(false);
  const timeoutIdRef = useRef<number | null>(null);

  const iconWrapperClasses = clsx(
    'flex items-center justify-center rounded-full transition-colors duration-150 ease-in-out',
    padding,
    `bg-[${bgColorLight}] dark:bg-[${bgColorDark}]`,
    `hover:bg-[${hoverBgColorLight}] dark:hover:bg-[${hoverBgColorDark}]`,
    {
      'bg-green-100 dark:bg-green-900 hover:bg-green-100 dark:hover:bg-green-900':
        isCopied,
    },
    iconWrapperClassName,
  );

  const rootButtonClasses = clsx(
    'flex items-center gap-2 group',
    'focus:outline-hidden focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:ring-blue-500 rounded-full',
    className,
  );

  const textSpanClasses = clsx(
    'text-xs text-gray-600 dark:text-gray-400 transition-opacity duration-150 ease-in-out',
    { 'opacity-75': isCopied },
    textClassName,
  );

  const IconComponent = isCopied ? CheckMark : CopyIcon;
  const iconClasses = clsx(iconSize, {
    'stroke-green-600 dark:stroke-green-400': isCopied,
    'fill-none text-gray-700 dark:text-gray-300': !isCopied,
  });

  const buttonTitle = isCopied
    ? t('conversation.copied')
    : t('conversation.copy');
  const displayedText = isCopied
    ? t('conversation.copied')
    : t('conversation.copy');

  const handleCopy = useCallback(() => {
    if (isCopied) return;

    try {
      const success = copy(textToCopy);
      if (success) {
        setIsCopied(true);

        if (timeoutIdRef.current) {
          clearTimeout(timeoutIdRef.current);
        }

        timeoutIdRef.current = setTimeout(() => {
          setIsCopied(false);
          timeoutIdRef.current = null;
        }, copiedDuration);
      } else {
        console.warn('Copy command failed.');
      }
    } catch (error) {
      console.error('Failed to copy text:', error);
    }
  }, [textToCopy, copiedDuration, isCopied]);

  useEffect(() => {
    return () => {
      if (timeoutIdRef.current) {
        clearTimeout(timeoutIdRef.current);
      }
    };
  }, []);
  return (
    <button
      type="button"
      onClick={handleCopy}
      className={rootButtonClasses}
      title={buttonTitle}
      aria-label={buttonTitle}
      disabled={isCopied}
    >
      <div className={iconWrapperClasses}>
        <IconComponent className={iconClasses} aria-hidden="true" />
      </div>
      {showText && <span className={textSpanClasses}>{displayedText}</span>}
      <span className="sr-only" aria-live="polite" aria-atomic="true">
        {isCopied ? t('conversation.copied', 'Copied to clipboard') : ''}
      </span>
    </button>
  );
}
