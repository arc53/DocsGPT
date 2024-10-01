import copy from 'copy-to-clipboard';
import { useState } from 'react';

import CheckMark from '../assets/checkmark.svg?react';
import Copy from '../assets/copy.svg?react';

export default function CoppyButton({
  text,
  colorLight,
  colorDark,
}: {
  text: string;
  colorLight?: string;
  colorDark?: string;
}) {
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
    <div
      className={`flex items-center justify-center rounded-full p-2 ${
        isCopyHovered
          ? `bg-[#EEEEEE] dark:bg-purple-taupe`
          : `bg-[${colorLight ? colorLight : '#FFFFFF'}] dark:bg-[${colorDark ? colorDark : 'transparent'}]`
      }`}
    >
      {copied ? (
        <CheckMark
          className="cursor-pointer stroke-green-2000"
          onMouseEnter={() => setIsCopyHovered(true)}
          onMouseLeave={() => setIsCopyHovered(false)}
        />
      ) : (
        <Copy
          className="cursor-pointer fill-none"
          onClick={() => {
            handleCopyClick(text);
          }}
          onMouseEnter={() => setIsCopyHovered(true)}
          onMouseLeave={() => setIsCopyHovered(false)}
        />
      )}
    </div>
  );
}
