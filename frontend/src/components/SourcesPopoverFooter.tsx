import { useTranslation } from 'react-i18next';

import PickerFooter from './PickerFooter';

type SourcesPopoverFooterProps = {
  /** Fires when the sources link is followed so the caller can close its popover. */
  onNavigate: () => void;
  onUploadClick: () => void;
};

/**
 * Shared footer for source pickers: a link to the sources page and an upload
 * shortcut.
 */
export default function SourcesPopoverFooter({
  onNavigate,
  onUploadClick,
}: SourcesPopoverFooterProps) {
  const { t } = useTranslation();

  return (
    <PickerFooter
      to="/settings/knowledge"
      linkLabel={t('settings.sources.goToSources')}
      onNavigate={onNavigate}
      actionLabel={t('settings.sources.uploadNew')}
      onAction={onUploadClick}
    />
  );
}
