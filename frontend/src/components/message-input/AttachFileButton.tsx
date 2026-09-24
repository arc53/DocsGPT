import { useTranslation } from 'react-i18next';

import ClipIcon from '../../assets/clip.svg';
import { ATTACHMENT_FILE_ACCEPT_ATTR } from '../../constants/fileUpload';
import { Button } from '../ui/button';

type AttachFileButtonProps = {
  onChange: (e: React.ChangeEvent<HTMLInputElement>) => void;
};

export default function AttachFileButton({ onChange }: AttachFileButtonProps) {
  const { t } = useTranslation();

  return (
    <Button asChild variant="outline" size="sm" shape="pill">
      {/* translate="no": Chrome's page translator rewrites text nodes inside
          this label into <font> wrappers and React then loses the control — a
          user with auto-translate on rage-clicked a dead Attach button until
          they reloaded. Keep the composer's controls out of the translator. */}
      <label translate="no" className="cursor-pointer justify-start">
        <img
          src={ClipIcon}
          alt="Attach"
          className="h-3.5 w-3.5 shrink-0 sm:h-4 sm:w-4 dark:invert"
        />
        <span className="dark:text-foreground text-muted-foreground text-xs sm:text-sm">
          {t('conversation.attachments.attach')}
        </span>
        <input
          type="file"
          className="hidden"
          multiple
          accept={ATTACHMENT_FILE_ACCEPT_ATTR}
          onChange={onChange}
        />
      </label>
    </Button>
  );
}
