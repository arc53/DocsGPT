import { ArrowRight } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';

import { Button } from './ui/button';

type SourcesPopoverFooterProps = {
  /** Fires when the sources link is followed so the caller can close its popover. */
  onNavigate: () => void;
  onUploadClick: () => void;
};

/**
 * Shared footer for source pickers: links to the sources page and to the
 * connectors that can sync content, and an upload shortcut.
 */
export default function SourcesPopoverFooter({
  onNavigate,
  onUploadClick,
}: SourcesPopoverFooterProps) {
  const { t } = useTranslation();

  return (
    // One row when it fits (link left, upload right); on a narrow sheet or a
    // long locale the button wraps under the link.
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <Button variant="link" size="inline" asChild>
          <Link to="/settings/sources" onClick={onNavigate}>
            {t('settings.sources.goToSources')}
            <ArrowRight aria-hidden="true" className="size-3" />
          </Link>
        </Button>
        <Button variant="link" size="inline" asChild>
          <Link to="/settings/connectors?capability=sync" onClick={onNavigate}>
            {t('conversation.sources.connectMore')}
            <ArrowRight aria-hidden="true" className="size-3" />
          </Link>
        </Button>
      </div>
      <Button
        type="button"
        variant="outline-primary"
        shape="pill"
        onClick={onUploadClick}
      >
        {t('settings.sources.uploadNew')}
      </Button>
    </div>
  );
}
