import { WandSparkles } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import { Button } from '@/components/ui/button';
import { IconButton } from '@/components/ui/icon-button';
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '@/components/ui/tooltip';

/**
 * The drafter's entry button: "Draft" on an empty form, "Improve" on a filled
 * one ("Write" for an empty prompt), "Resume" while a guided build is
 * unfinished, with the WandSparkles icon, as a bordered brand pill in page
 * chrome. Its open panel shows only through aria-expanded.
 * With `compactOnPhone` it is an icon-only button below `sm`, so a toolbar
 * row with three other buttons still fits a phone.
 *
 * Args:
 *   mode: `draft` (empty form), `improve` (filled form), `write` (an empty
 *     prompt) or `resume` (a build left halfway).
 *   label: The accessible name and tooltip when they say more than the
 *     button's word ("Resume drafting: step 3 of 4").
 *   onClick: Opens the drafter (or sends the prompt modal's request).
 *   disabled: Nothing to send yet.
 *   open: Whether the panel it opens is open (aria-expanded).
 *   size: `field` (38px, page toolbars, the default) or `sm` (a modal header).
 *   compactOnPhone: Icon only below `sm`.
 */
export function WandButton({
  mode,
  label,
  onClick,
  open,
  size = 'field',
  compactOnPhone = false,
  disabled,
}: {
  mode: 'draft' | 'improve' | 'write' | 'resume';
  label?: string;
  onClick: () => void;
  disabled?: boolean;
  open?: boolean;
  size?: 'field' | 'sm';
  compactOnPhone?: boolean;
}) {
  const { t } = useTranslation();
  const word =
    mode === 'draft'
      ? t('drafter.draft')
      : mode === 'write'
        ? t('drafter.prompt.write')
        : mode === 'resume'
          ? t('drafter.agent.build.resume')
          : t('drafter.improve');
  const button = (
    <Button
      type="button"
      variant="outline-primary"
      size={size}
      shape="pill"
      className={compactOnPhone ? 'hidden sm:inline-flex' : undefined}
      aria-label={label}
      aria-expanded={open}
      data-drafter-entry=""
      disabled={disabled}
      onClick={onClick}
    >
      <WandSparkles />
      {word}
    </Button>
  );
  return (
    <>
      {compactOnPhone && (
        <IconButton
          variant="outline-primary"
          size="icon"
          shape="pill"
          className="sm:hidden"
          label={label ?? word}
          icon={WandSparkles}
          aria-expanded={open}
          data-drafter-entry=""
          disabled={disabled}
          onClick={onClick}
        />
      )}
      {label ? (
        <Tooltip>
          <TooltipTrigger asChild>{button}</TooltipTrigger>
          <TooltipContent side="bottom">{label}</TooltipContent>
        </Tooltip>
      ) : (
        button
      )}
    </>
  );
}
