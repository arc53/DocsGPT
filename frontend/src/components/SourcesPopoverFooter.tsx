import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';

import RedirectIcon from '../assets/redirect.svg';
import { Button } from './ui/button';

type SourcesPopoverFooterProps = {
  /** Fires when the sources link is followed so the caller can close its popover. */
  onNavigate: () => void;
  onUploadClick: () => void;
};

/** Shared footer for source pickers: a link to the sources page and an upload shortcut. */
export default function SourcesPopoverFooter({
  onNavigate,
  onUploadClick,
}: SourcesPopoverFooterProps) {
  const { t } = useTranslation();

  return (
    <div className="flex flex-col gap-3">
      <Link
        to="/settings/sources"
        className="text-primary inline-flex items-center gap-2 text-base font-medium"
        onClick={onNavigate}
      >
        {t('settings.sources.goToSources')}
        <img src={RedirectIcon} alt="" aria-hidden="true" className="h-3 w-3" />
      </Link>
      <Button
        type="button"
        variant="outline"
        onClick={onUploadClick}
        className="border-primary text-primary hover:bg-primary/90 h-auto w-auto self-start rounded-full border bg-transparent px-4 py-2 text-sm font-medium shadow-none transition-colors duration-200 hover:text-white"
      >
        {t('settings.sources.uploadNew')}
      </Button>
    </div>
  );
}
