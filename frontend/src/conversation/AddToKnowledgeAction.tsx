import { useState } from 'react';
import { useTranslation } from 'react-i18next';

import { Button } from '../components/ui/button';
import {
  type KnowledgeFile,
  useAddToKnowledge,
} from '../upload/useAddToKnowledge';

/**
 * Offered in a turn that failed because its files did not fit the model:
 * makes a Knowledge source of them and selects it for the chat once ready,
 * so the question can be asked again against the source. It fixes the
 * error, so it is a link in the Alert's text and colour, after the message;
 * the answer's bubble puts it there. Inline content only, since it sits in
 * the message's paragraph.
 */
export default function AddToKnowledgeAction({
  files,
  onAdded,
}: {
  files: KnowledgeFile[];
  /** Called once the server accepted the files. */
  onAdded?: () => void;
}) {
  const { t } = useTranslation();
  const { addToKnowledge, pending, error } = useAddToKnowledge();
  const [added, setAdded] = useState(false);

  if (added) {
    return (
      <span role="status">{t('conversation.attachments.knowledgeAdded')}</span>
    );
  }
  return (
    <>
      <Button
        type="button"
        variant="link"
        size="text"
        tone="current"
        loading={pending}
        onClick={async () => {
          if (await addToKnowledge(files)) {
            setAdded(true);
            onAdded?.();
          }
        }}
      >
        {t('conversation.attachments.addToKnowledge')}
      </Button>
      {error && <> {error}</>}
    </>
  );
}
