import { WandSparkles } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import { Button } from '@/components/ui/button';
import { IconButton } from '@/components/ui/icon-button';

/**
 * The drafter's entry button: "Draft" on an empty form, "Improve" on a filled
 * one, with the WandSparkles icon, as a bordered brand pill in page chrome.
 * With `compactOnPhone` it is an icon-only button below `sm`, so a toolbar
 * row with three other buttons still fits a phone.
 *
 * Args:
 *   mode: `draft` (empty form) or `improve` (filled form).
 *   onClick: Opens the drafter.
 *   open: Whether the panel it opens is open (aria-expanded).
 *   size: `field` (38px, page toolbars, the default) or `sm` (a modal header).
 *   compactOnPhone: Icon only below `sm`.
 */
export function WandButton({
  mode,
  onClick,
  open,
  size = 'field',
  compactOnPhone = false,
}: {
  mode: 'draft' | 'improve';
  onClick: () => void;
  open?: boolean;
  size?: 'field' | 'sm';
  compactOnPhone?: boolean;
}) {
  const { t } = useTranslation();
  const label = mode === 'draft' ? t('drafter.draft') : t('drafter.improve');
  return (
    <>
      {compactOnPhone && (
        <IconButton
          variant="outline-primary"
          size="icon"
          shape="pill"
          className="sm:hidden"
          label={label}
          icon={WandSparkles}
          aria-expanded={open}
          data-drafter-entry=""
          onClick={onClick}
        />
      )}
      <Button
        type="button"
        variant="outline-primary"
        size={size}
        shape="pill"
        className={compactOnPhone ? 'hidden sm:inline-flex' : undefined}
        aria-expanded={open}
        data-drafter-entry=""
        onClick={onClick}
      >
        <WandSparkles />
        {label}
      </Button>
    </>
  );
}
