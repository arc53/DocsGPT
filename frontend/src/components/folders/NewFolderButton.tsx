import { FolderPlus } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import { Button } from '../ui/button';
import { Tooltip, TooltipContent, TooltipTrigger } from '../ui/tooltip';

type NewFolderButtonProps = {
  onClick: () => void;
  /** The folder open here is already 3 levels deep: no folder fits inside. */
  atDepthLimit?: boolean;
  /**
   * `toolbar`: the page's text-only `outline field pill` (Agents, Knowledge).
   * `dialog`: the Move dialog's footer, a `ghost lg pill` with `FolderPlus`.
   */
  look?: 'toolbar' | 'dialog';
};

/**
 * "New folder", the same button wherever a folder can be made. At the depth
 * limit it is disabled and says why in a tooltip (a disabled button gets no
 * pointer events, so the tooltip hangs on a focusable wrapper).
 */
export default function NewFolderButton({
  onClick,
  atDepthLimit = false,
  look = 'toolbar',
}: NewFolderButtonProps) {
  const { t } = useTranslation();
  const button =
    look === 'dialog' ? (
      <Button
        type="button"
        variant="ghost"
        size="lg"
        shape="pill"
        onClick={onClick}
        disabled={atDepthLimit}
      >
        <FolderPlus aria-hidden="true" />
        {t('folders.newFolder')}
      </Button>
    ) : (
      <Button
        type="button"
        variant="outline"
        size="field"
        shape="pill"
        onClick={onClick}
        disabled={atDepthLimit}
      >
        {t('folders.newFolder')}
      </Button>
    );
  if (!atDepthLimit) return button;
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span tabIndex={0} className="inline-flex">
          {button}
        </span>
      </TooltipTrigger>
      <TooltipContent side="bottom">{t('folders.depthLimit')}</TooltipContent>
    </Tooltip>
  );
}
