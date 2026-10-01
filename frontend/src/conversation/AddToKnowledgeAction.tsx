import { Database } from 'lucide-react';
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
      <p className="mt-2" role="status">
        {t('conversation.attachments.knowledgeAdded')}
      </p>
    );
  }
  return (
    // A real button under the alert's text, in body colour rather than the
    // alert's red, so it reads as the way out of the error.
    <div className="text-foreground mt-3 flex flex-wrap items-center gap-x-3 gap-y-1">
      <Button
        type="button"
        variant="outline"
        size="sm"
        shape="pill"
        loading={pending}
        onClick={async () => {
          if (await addToKnowledge(files)) {
            setAdded(true);
            onAdded?.();
          }
        }}
      >
        <Database />
        {t('conversation.attachments.addToKnowledge')}
      </Button>
      {error && <span className="text-destructive">{error}</span>}
    </div>
  );
}
