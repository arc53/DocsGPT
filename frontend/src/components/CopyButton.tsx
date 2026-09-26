import copy from 'copy-to-clipboard';
import { Check, Copy } from 'lucide-react';
import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { Button } from './ui/button';
import { IconButton, type IconButtonProps } from './ui/icon-button';

type CopyButtonProps = {
  textToCopy: string;
  /**
   * `xs` is `icon-xs` (28px) and `sm` is `icon-sm` (32px), icon only; `lg`
   * is a text-only primary pill (Button `lg`, 40px) for a dialog footer.
   */
  size?: 'xs' | 'sm' | 'lg';
  /** Show a "Copy"/"Copied" label next to the icon (renders at Button `xs`). */
  showText?: boolean;
  copiedDuration?: number;
  /** The idle label (default `conversation.copy`). */
  copyLabel?: string;
  /** The label after a copy (default `conversation.copied`). */
  copiedLabel?: string;
  className?: string;
  /** Tooltip side of the icon-only button: `bottom` in a header or toolbar. */
  side?: IconButtonProps['side'];
};

const DEFAULT_COPIED_DURATION = 2000;

export default function CopyButton({
  textToCopy,
  size = 'sm',
  showText = false,
  copiedDuration = DEFAULT_COPIED_DURATION,
  copyLabel,
  copiedLabel,
  className,
  side,
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
    ? (copiedLabel ?? t('conversation.copied'))
    : (copyLabel ?? t('conversation.copy'));

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
  const liveRegion = (
    <span className="sr-only" aria-live="polite" aria-atomic="true">
      {isCopied ? t('conversation.copied', 'Copied to clipboard') : ''}
    </span>
  );
  const variant = isCopied ? 'secondary' : 'ghost-muted';

  if (size === 'lg') {
    // The visible label is the name; the live region announces the copy.
    return (
      <Button
        type="button"
        size="lg"
        shape="pill"
        onClick={handleCopy}
        className={className}
      >
        {buttonTitle}
        {liveRegion}
      </Button>
    );
  }

  if (showText) {
    return (
      <Button
        type="button"
        variant={variant}
        size="xs"
        shape="pill"
        onClick={handleCopy}
        className={className}
        aria-label={buttonTitle}
      >
        <IconComponent aria-hidden="true" />
        <span>{buttonTitle}</span>
        {liveRegion}
      </Button>
    );
  }

  return (
    <IconButton
      label={buttonTitle}
      variant={variant}
      size={size === 'xs' ? 'icon-xs' : 'icon-sm'}
      shape="pill"
      onClick={handleCopy}
      className={className}
      side={side}
    >
      <IconComponent aria-hidden="true" />
      {liveRegion}
    </IconButton>
  );
}
