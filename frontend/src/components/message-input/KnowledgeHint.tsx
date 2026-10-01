import { useTranslation } from 'react-i18next';

import { Button } from '../ui/button';

type KnowledgeHintProps = {
  /**
   * Whether the model can reach the files that do not fit through its
   * attachment tools. Without tools the rest is left out of the turn.
   */
  readsRest: boolean;
  pending: boolean;
  /** Why the last attempt was refused, shown in place. */
  error: string | null;
  onAdd: () => void;
};

/**
 * The composer's note under the chips when its files are more than the model
 * reads in one turn: the files still send, and Knowledge is offered as the
 * better home for them. Informative, so muted rather than a status colour.
 */
export default function KnowledgeHint({
  readsRest,
  pending,
  error,
  onAdd,
}: KnowledgeHintProps) {
  const { t } = useTranslation();
  return (
    <div className="text-muted-foreground flex flex-wrap items-center gap-x-2 gap-y-0.5 px-2 pb-1 text-xs sm:px-3">
      <span role="status">
        {readsRest
          ? t('conversation.attachments.knowledgeHint')
          : t('conversation.attachments.knowledgeHintNoTools')}
      </span>
      <Button
        type="button"
        variant="link"
        size="inline"
        loading={pending}
        onClick={onAdd}
        /* eslint-disable-next-line shadcn/no-restyle --
           The Add as Knowledge action sits inline in the composer's 12px hint line; link inline keeps the base text-sm, so it takes the line's size. */
        className="text-xs"
      >
        {t('conversation.attachments.addAsKnowledge')}
      </Button>
      {error && (
        <span className="text-destructive" role="alert">
          {error}
        </span>
      )}
    </div>
  );
}
