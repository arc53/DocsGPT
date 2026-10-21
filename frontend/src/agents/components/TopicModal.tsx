import { useEffect, useId, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { Alert, AlertDescription } from '@/components/ui/alert';
import { FormField } from '@/components/ui/form-field';
import { Input } from '@/components/ui/input';
import { Modal, ModalActions } from '@/components/ui/modal';
import { SettingRow } from '@/components/ui/setting-row';
import { Switch } from '@/components/ui/switch';
import { Textarea } from '@/components/ui/textarea';

import { formatCount } from '../../utils/dateTimeUtils';
import {
  descriptionMax,
  nameTaken,
  RESERVED_TOPIC_NAME,
  TOPIC_NAME_MAX,
  units,
} from '../analyticsConfig';
import type { TopicFolder } from '../types';

export type TopicDraft = {
  name: string;
  description: string;
  overlap: boolean;
};

/** The description's counter shows past this share of its budget. */
const COUNTER_FROM = 0.8;

/** Length in code points, as the server counts a name. */
const chars = (text: string) => Array.from(text).length;

type TopicModalProps = {
  /** The owner's topic being edited; left out to add one or edit a folder. */
  item?: TopicDraft;
  /** The source folder being edited: saving turns it into an own topic. */
  folder?: TopicFolder;
  /** The other topics' and shown folders' names, for the duplicate check. */
  others: string[];
  /**
   * The server allows topics that can overlap (its limit is above 0). At 0
   * the switch still shows for a topic that overlaps, to turn it off.
   */
  overlapAllowed: boolean;
  /** No more topics that don't overlap fit, this one aside. */
  onePickFull: boolean;
  /** No more topics that can overlap fit, this one aside. */
  overlapFull: boolean;
  maxTopics: number;
  maxOverlapping: number;
  open: boolean;
  onClose: () => void;
  onSubmit: (topic: TopicDraft) => void;
};

/**
 * Adds or edits one topic, an owner's own or a source folder (which then
 * becomes the owner's). It edits the host's draft only; the host's Save
 * stores it. Errors show after the first submit, then follow the typing. The
 * host keeps `item` and `folder` while it closes, so the copy doesn't flip
 * during the exit animation.
 */
export default function TopicModal({
  item,
  folder,
  others,
  overlapAllowed,
  onePickFull,
  overlapFull,
  maxTopics,
  maxOverlapping,
  open,
  onClose,
  onSubmit,
}: TopicModalProps) {
  const { t } = useTranslation();
  const k = (key: string) => `agents.form.analytics.modal.${key}`;
  const overlapId = useId();
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [overlap, setOverlap] = useState(false);
  const [submitted, setSubmitted] = useState(false);

  useEffect(() => {
    if (!open) return;
    // A name past the limit (a long source's) starts cut to fit. Typing past
    // it shows the error instead: `maxLength` would count UTF-16 units, not
    // the code points the server counts, and stop emoji at half the limit.
    setName(
      Array.from(item?.name ?? folder?.name ?? '')
        .slice(0, TOPIC_NAME_MAX)
        .join(''),
    );
    setDescription(item?.description ?? folder?.description ?? '');
    // A new topic overlaps only when the other kind is full.
    setOverlap(item?.overlap ?? (onePickFull && !overlapFull));
    setSubmitted(false);
    // The list doesn't change while the dialog is open, so the limits only
    // move between openings.
  }, [open, item, folder, onePickFull, overlapFull]);

  const trimmedName = name.trim();
  const trimmedDescription = description.trim();
  const nameError = !trimmedName
    ? t('agents.form.analytics.errors.nameRequired')
    : chars(trimmedName) > TOPIC_NAME_MAX
      ? t('agents.form.analytics.errors.topicNameTooLong', {
          max: formatCount(TOPIC_NAME_MAX),
        })
      : nameTaken(trimmedName, [RESERVED_TOPIC_NAME])
        ? t('agents.form.analytics.errors.topicNameReserved')
        : nameTaken(trimmedName, others)
          ? t('agents.form.analytics.errors.topicNameTaken')
          : null;
  const max = descriptionMax(overlap);
  const used = units(trimmedDescription);
  const descriptionError =
    used > max
      ? t('agents.form.analytics.errors.topicDescriptionTooLong', {
          max: formatCount(max),
        })
      : null;
  // The budget shows only once it is close.
  const showCount = used > COUNTER_FROM * max;

  // A kind that is full can't be picked; the switch stays on the other.
  const locked = overlap ? onePickFull : overlapFull;
  const lockedHint = overlap
    ? t(k('onePickFull'), { max: formatCount(maxTopics) })
    : maxOverlapping === 0
      ? t(k('overlapOff'))
      : t(k('overlapFull'), { max: formatCount(maxOverlapping) });
  const kindChanged = item !== undefined && item.overlap !== overlap;

  const submit = () => {
    setSubmitted(true);
    if (nameError || descriptionError) return;
    onSubmit({ name: trimmedName, description: trimmedDescription, overlap });
  };

  const editing = item !== undefined || folder !== undefined;
  return (
    <Modal
      open={open}
      onOpenChange={(next) => !next && onClose()}
      title={t(k(editing ? 'editTopic' : 'addTopic'))}
      description={
        folder
          ? t(k('editFolder'), {
              name: folder.name,
              interpolation: { escapeValue: false },
            })
          : t(k('dialogDescription'))
      }
      footer={
        <ModalActions
          cancelLabel={t('cancel')}
          onCancel={onClose}
          submitLabel={t(k(editing ? 'submitSave' : 'submitAdd'))}
          // The form's own submit, so Enter in the name field adds it too.
          submitProps={{ type: 'submit', form: 'analytics-topic-form' }}
        />
      }
    >
      <form
        id="analytics-topic-form"
        className="flex flex-col gap-5"
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          submit();
        }}
      >
        <FormField
          label={t(k('name'))}
          required
          error={submitted ? nameError : undefined}
        >
          <Input
            value={name}
            placeholder={t(k('namePlaceholder'))}
            onChange={(event) => setName(event.target.value)}
          />
        </FormField>
        <FormField
          label={t(k('description'))}
          hint={
            <>
              {t(k('descriptionHint'))}
              {showCount && (
                <>
                  {' '}
                  <span className="tabular-nums">
                    {t('agents.form.analytics.countOf', {
                      count: formatCount(Math.ceil(used)),
                      max: formatCount(max),
                    })}
                  </span>
                </>
              )}
            </>
          }
          error={submitted ? descriptionError : undefined}
        >
          <Textarea
            rows={3}
            value={description}
            placeholder={t(k('descriptionPlaceholder'))}
            onChange={(event) => setDescription(event.target.value)}
          />
        </FormField>
        {(overlapAllowed || item?.overlap) && (
          <SettingRow
            label={t(k('overlap'))}
            description={locked ? lockedHint : t(k('overlapDescription'))}
            htmlFor={overlapId}
            alignStart
          >
            <Switch
              id={overlapId}
              checked={overlap}
              disabled={locked}
              data-testid="topic-overlap"
              onCheckedChange={setOverlap}
            />
          </SettingRow>
        )}
        {kindChanged ? (
          <Alert variant="warning" role="note">
            <AlertDescription>
              {t(k(overlap ? 'kindChangeToOverlap' : 'kindChangeToOnePick'))}
            </AlertDescription>
          </Alert>
        ) : (
          <p className="text-muted-foreground text-xs">
            {t(k(overlap ? 'reachOverlap' : 'reachOnePick'))}
          </p>
        )}
      </form>
    </Modal>
  );
}
