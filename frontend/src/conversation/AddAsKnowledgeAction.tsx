import { useState } from 'react';
import { useTranslation } from 'react-i18next';

import { Button } from '../components/ui/button';
import {
  type KnowledgeFile,
  useAddToKnowledge,
} from '../upload/useAddToKnowledge';

/**
 * Offered under a turn that failed because its files did not fit the model:
 * makes a Knowledge source of them and selects it for the chat once ready,
 * so the question can be asked again against the source.
 */
export default function AddAsKnowledgeAction({
  files,
}: {
  files: KnowledgeFile[];
}) {
  const { t } = useTranslation();
  const { addToKnowledge, pending, error } = useAddToKnowledge();
  const [added, setAdded] = useState(false);

  if (added) {
    return (
      <p className="mt-2" role="status">
        {t('conversation.attachments.knowledgeAdded')}
      </p>
    );
  }
  return (
    <div className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1">
      <Button
        type="button"
        variant="link"
        size="inline"
        loading={pending}
        onClick={async () => {
          if (await addToKnowledge(files)) setAdded(true);
        }}
        // eslint-disable-next-line shadcn/no-restyle -- the link inherits its Alert's status colour
        className="text-current"
      >
        {t('conversation.attachments.addAsKnowledge')}
      </Button>
      {error && <span>{error}</span>}
    </div>
  );
}
