import {
  CircleQuestionMark,
  FileQuestionMark,
  Frown,
  Headset,
  MessageSquareWarning,
  Tag,
  type LucideIcon,
} from 'lucide-react';
import { useTranslation } from 'react-i18next';

import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';

import { formatCount, intlLocale } from '../utils/dateTimeUtils';

type ChipSpec = {
  key: string;
  variant: 'warning' | 'destructive' | 'info';
  icon: LucideIcon;
};

/**
 * The model's labels as chips, in this order. Amber: the answer fell short;
 * red: the user is upset (as a thumbs-down is); blue: someone should step in.
 */
const LABELS: Record<string, ChipSpec> = {
  docs_gap: { key: 'docsGap', variant: 'warning', icon: FileQuestionMark },
  not_answered: {
    key: 'notAnswered',
    variant: 'warning',
    icon: CircleQuestionMark,
  },
  negative_reaction: {
    key: 'negativeReaction',
    variant: 'warning',
    icon: MessageSquareWarning,
  },
  frustrated: { key: 'frustrated', variant: 'destructive', icon: Frown },
  asks_human: { key: 'asksHuman', variant: 'info', icon: Headset },
};

const ORDER = Object.keys(LABELS);

/** At most this many chips; the rest fold into "+N". */
const MAX_CHIPS = 3;

type Chip = { id: string; label: string; spec?: ChipSpec };

/**
 * The chips a row shows, in order: a docs gap stands for "not fully
 * answered" (it is one kind of it), and a tag whose name is unknown (a
 * deleted tag) is left out.
 */
export function labelChips(
  labels: string[],
  tagNames: Record<string, string>,
  name: (key: string) => string,
): Chip[] {
  const set = new Set(labels);
  if (set.has('docs_gap')) set.delete('not_answered');
  const known = ORDER.filter((label) => set.has(label)).map((label) => ({
    id: label,
    label: name(LABELS[label].key),
    spec: LABELS[label],
  }));
  const tags = labels
    .filter((label) => label.startsWith('tag:'))
    .map((label) => ({ id: label, label: tagNames[label.slice(4)] ?? '' }))
    .filter((chip) => chip.label);
  return [...known, ...tags];
}

type LabelChipsProps = {
  labels?: string[];
  /** Tag id to the owner's tag name. */
  tagNames?: Record<string, string>;
  /** Layout only. */
  className?: string;
};

/**
 * A Logs row's conversation labels, in its header so they can be scanned
 * without opening rows. Badges only: they sit inside the row's button.
 */
export default function LabelChips({
  labels,
  tagNames = {},
  className,
}: LabelChipsProps) {
  const { t, i18n } = useTranslation();
  if (!labels?.length) return null;
  const chips = labelChips(labels, tagNames, (key) =>
    t(`settings.logs.labels.${key}`),
  );
  if (!chips.length) return null;
  const shown = chips.slice(0, MAX_CHIPS);
  const rest = chips.slice(MAX_CHIPS);
  const restNames = new Intl.ListFormat(intlLocale(i18n.language), {
    type: 'conjunction',
  }).format(rest.map((chip) => chip.label));
  return (
    <span
      className={cn('flex flex-wrap gap-1.5', className)}
      data-testid="label-chips"
    >
      {shown.map((chip) => {
        const Icon = chip.spec?.icon ?? Tag;
        return (
          <Badge
            key={chip.id}
            variant={chip.spec?.variant ?? 'neutral'}
            className={chip.spec ? undefined : 'max-w-48'}
          >
            <Icon aria-hidden="true" />
            {chip.spec ? (
              chip.label
            ) : (
              <span className="min-w-0 truncate" title={chip.label}>
                {chip.label}
              </span>
            )}
          </Badge>
        );
      })}
      {rest.length > 0 && (
        <Badge variant="neutral" className="tabular-nums" title={restNames}>
          <span aria-hidden="true">
            {t('settings.logs.labels.more', {
              formatted: formatCount(rest.length),
            })}
          </span>
          <span className="sr-only">{restNames}</span>
        </Badge>
      )}
    </span>
  );
}
