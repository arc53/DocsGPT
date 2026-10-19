import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { FormField } from '@/components/ui/form-field';
import { Input } from '@/components/ui/input';
import { Modal, ModalActions } from '@/components/ui/modal';
import { Textarea } from '@/components/ui/textarea';

import { formatCount } from '../../utils/dateTimeUtils';
import {
  nameTaken,
  RESERVED_TOPIC_NAME,
  TAG_DESCRIPTION_MAX,
  TAG_NAME_MAX,
  TOPIC_DESCRIPTION_UNITS,
  TOPIC_NAME_MAX,
  units,
} from '../analyticsConfig';

type Item = { name: string; description: string };

type AnalyticsItemModalProps = {
  kind: 'topic' | 'tag';
  /** The item being edited; left out to add one. */
  item?: Item;
  /** The other items' names, for the duplicate check. */
  others: string[];
  open: boolean;
  onClose: () => void;
  onSubmit: (item: Item) => void;
};

/**
 * Adds or edits one custom topic or tag. It edits the agent form's state
 * only; the agent's Save stores it. Errors show after the first submit, then
 * follow the typing.
 */
export default function AnalyticsItemModal({
  kind,
  item,
  others,
  open,
  onClose,
  onSubmit,
}: AnalyticsItemModalProps) {
  const { t } = useTranslation();
  const prefix = 'agents.form.analytics.modal';
  const start = t(`${prefix}.topicDescriptionStart`);
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [submitted, setSubmitted] = useState(false);

  useEffect(() => {
    if (!open) return;
    setName(item?.name ?? '');
    // A new topic's description starts the sentence the model reads best.
    setDescription(item?.description ?? (kind === 'topic' ? `${start} ` : ''));
    setSubmitted(false);
  }, [open, item, kind, start]);

  const trimmedName = name.trim();
  const trimmedDescription = description.trim();
  const isTopic = kind === 'topic';
  const nameError = !trimmedName
    ? t('agents.form.analytics.errors.nameRequired')
    : isTopic && nameTaken(trimmedName, [RESERVED_TOPIC_NAME])
      ? t('agents.form.analytics.errors.topicNameReserved')
      : nameTaken(trimmedName, others)
        ? t(
            isTopic
              ? 'agents.form.analytics.errors.topicNameTaken'
              : 'agents.form.analytics.errors.tagNameTaken',
          )
        : null;
  const used = units(trimmedDescription);
  const descriptionError =
    !trimmedDescription || (isTopic && trimmedDescription === start.trim())
      ? t('agents.form.analytics.errors.descriptionRequired')
      : isTopic && used > TOPIC_DESCRIPTION_UNITS
        ? t('agents.form.analytics.errors.topicDescriptionTooLong', {
            max: formatCount(TOPIC_DESCRIPTION_UNITS),
          })
        : null;

  const submit = () => {
    setSubmitted(true);
    if (nameError || descriptionError) return;
    onSubmit({ name: trimmedName, description: trimmedDescription });
  };

  const editing = item !== undefined;
  const title = t(
    `${prefix}.${editing ? 'edit' : 'add'}${isTopic ? 'Topic' : 'Tag'}`,
  );
  const submitLabel = t(
    `${prefix}.submit${editing ? 'Update' : 'Add'}${isTopic ? 'Topic' : 'Tag'}`,
  );

  return (
    <Modal
      open={open}
      onOpenChange={(next) => !next && onClose()}
      title={title}
      description={t(
        isTopic ? `${prefix}.topicDescription` : `${prefix}.tagDescription`,
      )}
      footer={
        <ModalActions
          cancelLabel={t('cancel')}
          onCancel={onClose}
          submitLabel={submitLabel}
          // The form's own submit, so Enter in the name field adds it too.
          submitProps={{ type: 'submit', form: `analytics-${kind}-form` }}
        />
      }
    >
      <form
        id={`analytics-${kind}-form`}
        className="flex flex-col gap-5"
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          submit();
        }}
      >
        <FormField
          label={t(`${prefix}.name`)}
          required
          error={submitted ? nameError : undefined}
        >
          <Input
            value={name}
            maxLength={isTopic ? TOPIC_NAME_MAX : TAG_NAME_MAX}
            placeholder={t(
              isTopic
                ? `${prefix}.topicNamePlaceholder`
                : `${prefix}.tagNamePlaceholder`,
            )}
            onChange={(event) => setName(event.target.value)}
          />
        </FormField>
        <FormField
          label={t(`${prefix}.description`)}
          required
          hint={
            isTopic
              ? t(`${prefix}.topicDescriptionHint`, {
                  used: formatCount(Math.ceil(used)),
                  max: formatCount(TOPIC_DESCRIPTION_UNITS),
                })
              : t(`${prefix}.tagDescriptionHint`)
          }
          error={submitted ? descriptionError : undefined}
        >
          <Textarea
            rows={3}
            value={description}
            maxLength={isTopic ? undefined : TAG_DESCRIPTION_MAX}
            placeholder={
              isTopic ? undefined : t(`${prefix}.tagDescriptionPlaceholder`)
            }
            onChange={(event) => setDescription(event.target.value)}
          />
        </FormField>
      </form>
    </Modal>
  );
}
