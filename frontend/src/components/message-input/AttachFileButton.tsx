import { useTranslation } from 'react-i18next';

import ClipIcon from '../../assets/clip.svg';
import { ATTACHMENT_FILE_ACCEPT_ATTR } from '../../constants/fileUpload';

type AttachFileButtonProps = {
  onChange: (e: React.ChangeEvent<HTMLInputElement>) => void;
};

export default function AttachFileButton({ onChange }: AttachFileButtonProps) {
  const { t } = useTranslation();

  return (
    // translate="no": Chrome's page translator rewrites text nodes inside
    // this label into <font> wrappers and React then loses the control — a
    // user with auto-translate on rage-clicked a dead Attach button until
    // they reloaded. Keep the composer's controls out of the translator.
    <label
      translate="no"
      className="xs:px-3 xs:py-1.5 dark:border-border border-border hover:bg-muted dark:hover:bg-muted flex cursor-pointer items-center rounded-full border px-2 py-1 transition-colors"
    >
      <img
        src={ClipIcon}
        alt="Attach"
        className="mr-1 h-3.5 w-3.5 sm:mr-1.5 sm:h-4 sm:w-4"
      />
      <span className="xs:text-xs dark:text-foreground text-muted-foreground text-xs font-medium sm:text-sm">
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
  );
}
