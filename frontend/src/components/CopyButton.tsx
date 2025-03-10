import copy from 'copy-to-clipboard';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';

import CheckMark from '../assets/checkmark.svg?react';
import Copy from '../assets/copy.svg?react';

export default function CopyButton({
  text,
  colorLight,
  colorDark,
  showText = false,
}: {
  text: string;
  colorLight?: string;
  colorDark?: string;
  showText?: boolean;
}) {
  const { t } = useTranslation();
  const [copied, setCopied] = useState(false);
  const [isCopyHovered, setIsCopyHovered] = useState(false);

  const handleCopyClick = (text: string) => {
    copy(text);
    setCopied(true);
    setTimeout(() => {
      setCopied(false);
    }, 3000);
  };

  return (
    <button
      onClick={() => handleCopyClick(text)}
      onMouseEnter={() => setIsCopyHovered(true)}
      onMouseLeave={() => setIsCopyHovered(false)}
      className="flex items-center gap-2"
    >
      <div
        className={`flex items-center justify-center rounded-full p-2 ${
          isCopyHovered
            ? `bg-[#EEEEEE] dark:bg-purple-taupe`
            : `bg-[${colorLight ? colorLight : '#FFFFFF'}] dark:bg-[${colorDark ? colorDark : 'transparent'}]`
        }`}
      >
        {copied ? (
          <CheckMark className="cursor-pointer stroke-green-2000" />
        ) : (
          <Copy className="w-4 cursor-pointer fill-none" />
        )}
      </div>
      {showText && (
        <span className="text-xs text-gray-600 dark:text-gray-400">
          {copied ? t('conversation.copied') : t('conversation.copy')}
        </span>
      )}
    </button>
  );
}
