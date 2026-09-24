import copy from 'copy-to-clipboard';
import { Check, Copy } from 'lucide-react';
import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { Button } from './ui/button';

type CopyButtonProps = {
  textToCopy: string;
  /** Icon-only button size: `xs` is `icon-xs` (28px), `sm` is `icon-sm` (32px). */
  size?: 'xs' | 'sm';
  /** Show a "Copy"/"Copied" label next to the icon (renders at Button `xs`). */
  showText?: boolean;
  copiedDuration?: number;
  className?: string;
};

const DEFAULT_COPIED_DURATION = 2000;

export default function CopyButton({
  textToCopy,
  size = 'sm',
  showText = false,
  copiedDuration = DEFAULT_COPIED_DURATION,
  className,
}: CopyButtonProps) {
  const { t } = useTranslation();
  const [isCopied, setIsCopied] = useState(false);
  const timeoutIdRef = useRef<number | null>(null);
  // `copy` is async, so `isCopied` only catches up after it resolves. Guard
  // that window so rapid clicks cannot start a second write. The button is
  // never disabled, so the copied confirmation does not fade.
  const copyInFlightRef = useRef(false);

  const IconComponent = isCopied ? Check : Copy;

  const buttonTitle = isCopied
    ? t('conversation.copied')
    : t('conversation.copy');
  const displayedText = isCopied
    ? t('conversation.copied')
    : t('conversation.copy');

  const handleCopy = useCallback(async () => {
    if (isCopied || copyInFlightRef.current) return;
    copyInFlightRef.current = true;

    try {
      const success = await copy(textToCopy);
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
    } finally {
      copyInFlightRef.current = false;
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
    <Button
      type="button"
      variant={isCopied ? 'secondary' : 'ghost-muted'}
      size={showText ? 'xs' : size === 'xs' ? 'icon-xs' : 'icon-sm'}
      shape="pill"
      onClick={handleCopy}
      className={className}
      title={buttonTitle}
      aria-label={buttonTitle}
    >
      <IconComponent aria-hidden="true" />
      {showText && <span>{displayedText}</span>}
      <span className="sr-only" aria-live="polite" aria-atomic="true">
        {isCopied ? t('conversation.copied', 'Copied to clipboard') : ''}
      </span>
    </Button>
  );
}
