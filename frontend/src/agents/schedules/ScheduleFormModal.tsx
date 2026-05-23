import { CalendarIcon } from 'lucide-react';
import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { Button } from '@/components/ui/button';
import { Calendar } from '@/components/ui/calendar';
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { TimePicker } from '@/components/ui/time-picker';
import { cn } from '@/lib/utils';

import { Modal } from '../../components/ui/modal';
import type { Schedule, ScheduleCreatePayload } from '../types/schedule';
import {
  browserTimezone,
  buildCron,
  buildRunAtUtc,
  parseScheduleToFormValues,
  supportedTimezones,
  todayDate,
  type ScheduleFormValues,
  type ScheduleFrequency,
} from './cronBuilder';
import TimezoneCombobox from './TimezoneCombobox';

export type ScheduleFormModalProps = {
  open: boolean;
  initial?: Schedule | null;
  agentToolIds: string[];
  onClose: () => void;
  onSubmit: (payload: ScheduleCreatePayload) => Promise<void> | void;
  submitting?: boolean;
};

const FREQUENCIES: ScheduleFrequency[] = [
  'once',
  'daily',
  'weekly',
  'monthly',
  'yearly',
];

// 0=Sun ... 6=Sat (matches POSIX cron's dow field).
const DAY_OPTIONS = [
  { value: 1, key: 'mon' },
  { value: 2, key: 'tue' },
  { value: 3, key: 'wed' },
  { value: 4, key: 'thu' },
  { value: 5, key: 'fri' },
  { value: 6, key: 'sat' },
  { value: 0, key: 'sun' },
] as const;

const MONTH_KEYS = [
  'jan',
  'feb',
  'mar',
  'apr',
  'may',
  'jun',
  'jul',
  'aug',
  'sep',
  'oct',
  'nov',
  'dec',
] as const;

/** Parse ``YYYY-MM-DD`` into a local Date (no tz drift for calendar use). */
const dateStringToDate = (value: string): Date | undefined => {
  const m = /^(\d{4})-(\d{1,2})-(\d{1,2})$/.exec(value ?? '');
  if (!m) return undefined;
  return new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
};

const dateToDateString = (d: Date): string => {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
};

const formatDateLabel = (value: string): string => {
  const d = dateStringToDate(value);
  if (!d) return '';
  return d.toLocaleDateString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  });
};

/** Create/edit a Schedule via a modal dialog. */
export default function ScheduleFormModal({
  open,
  initial,
  agentToolIds,
  onClose,
  onSubmit,
  submitting,
}: ScheduleFormModalProps) {
  const { t } = useTranslation();
  // Edit mode pre-populates from the saved schedule; create mode uses the browser tz.
  const initialTimezone = useMemo<string>(
    () => initial?.timezone || browserTimezone(),
    [initial?.timezone],
  );

  const defaults: ScheduleFormValues = useMemo(
    () =>
      initial
        ? parseScheduleToFormValues(initial, initialTimezone)
        : {
            frequency: 'daily',
            date: todayDate(initialTimezone),
            time: '09:00',
            dayOfWeek: 1,
            dayOfMonth: 1,
            month: 1,
          },
    [initial, initialTimezone],
  );

  const [name, setName] = useState<string>(initial?.name ?? '');
  const [instruction, setInstruction] = useState<string>(
    initial?.instruction ?? '',
  );
  const [values, setValues] = useState<ScheduleFormValues>(defaults);
  const [timezone, setTimezone] = useState<string>(initialTimezone);
  const timezoneOptions = useMemo<string[]>(() => {
    const list = supportedTimezones();
    // Make sure the current selection is always present, even if absent from
    // the engine's supported list (e.g. an exotic tz saved on the schedule).
    return list.includes(timezone) ? list : [timezone, ...list];
  }, [timezone]);
  const [error, setError] = useState<string | null>(null);

  const setFrequency = (frequency: ScheduleFrequency) =>
    setValues((current) => ({ ...current, frequency }));

  const submit = async () => {
    if (!instruction.trim()) {
      setError(t('agents.schedules.modal.errors.instructionRequired'));
      return;
    }
    const payload: ScheduleCreatePayload = {
      instruction: instruction.trim(),
      timezone,
      name: name.trim() || undefined,
      tool_allowlist: agentToolIds,
    };
    if (values.frequency === 'once') {
      let runAt: string;
      try {
        runAt = buildRunAtUtc(values.date, values.time, timezone);
      } catch {
        setError(t('agents.schedules.modal.errors.runAtInPast'));
        return;
      }
      if (new Date(runAt).getTime() <= Date.now()) {
        setError(t('agents.schedules.modal.errors.runAtInPast'));
        return;
      }
      payload.trigger_type = 'once';
      payload.run_at = runAt;
    } else {
      const cron = buildCron(values.frequency, values);
      if (!cron) {
        setError(t('agents.schedules.modal.errors.instructionRequired'));
        return;
      }
      payload.trigger_type = 'recurring';
      payload.cron = cron;
    }
    setError(null);
    await onSubmit(payload);
  };

  const isEdit = Boolean(initial?.id);

  return (
    <Modal
      open={open}
      onOpenChange={(o) => !o && onClose()}
      hideTitle
      title={
        isEdit
          ? t('agents.schedules.modal.save')
          : t('agents.schedules.modal.create')
      }
      size="md"
      className="w-[min(560px,92vw)] sm:p-6"
      contentClassName="max-h-[80vh]"
    >
      <div className="flex flex-col gap-5">
        <div className="flex items-start gap-3 pr-6">
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder={t('agents.schedules.modal.namePlaceholder')}
            className="text-foreground placeholder:text-muted-foreground w-full bg-transparent text-xl font-semibold outline-none"
            aria-label={t('agents.schedules.modal.namePlaceholder')}
          />
        </div>

        <FrequencyTabs
          frequency={values.frequency}
          onChange={setFrequency}
          labels={{
            once: t('agents.schedules.modal.frequency.once'),
            daily: t('agents.schedules.modal.frequency.daily'),
            weekly: t('agents.schedules.modal.frequency.weekly'),
            monthly: t('agents.schedules.modal.frequency.monthly'),
            yearly: t('agents.schedules.modal.frequency.yearly'),
          }}
        />

        <OnPicker
          values={values}
          onChange={setValues}
          tDay={(key) => t(`agents.schedules.modal.days.${key}`)}
          tMonth={(key) => t(`agents.schedules.modal.months.${key}`)}
          labels={{
            on: t('agents.schedules.modal.on'),
            at: t('agents.schedules.modal.at'),
            pickDate: t('agents.schedules.modal.pickDate'),
          }}
        />

        <div className="border-border flex flex-wrap items-center justify-between gap-2 rounded-md border p-3">
          <span className="text-foreground text-sm font-medium">
            {t('agents.schedules.modal.timezone')}
          </span>
          <div className="w-full max-w-[16rem]">
            <TimezoneCombobox
              value={timezone}
              options={timezoneOptions}
              onChange={setTimezone}
              placeholder={t('agents.schedules.modal.timezonePlaceholder')}
              searchPlaceholder={t(
                'agents.schedules.modal.timezoneSearchPlaceholder',
              )}
              emptyText={t('agents.schedules.modal.timezoneEmpty')}
              ariaLabel={t('agents.schedules.modal.timezone')}
            />
          </div>
        </div>

        <label className="flex flex-col gap-2">
          <span className="text-foreground text-sm font-medium">
            {t('agents.schedules.modal.instructionsLabel')}
          </span>
          <textarea
            value={instruction}
            onChange={(e) => setInstruction(e.target.value)}
            placeholder={t('agents.schedules.modal.instructionsPlaceholder')}
            rows={5}
            className="border-border bg-background text-foreground placeholder:text-muted-foreground focus:border-ring focus:ring-ring/40 rounded-md border px-3 py-2 text-sm outline-none focus:ring-2"
          />
        </label>

        {error && <p className="text-destructive text-sm">{error}</p>}

        <div className="flex justify-end">
          <Button
            type="button"
            disabled={submitting}
            onClick={submit}
            className="rounded-3xl px-5"
          >
            {submitting
              ? '…'
              : isEdit
                ? t('agents.schedules.modal.save')
                : t('agents.schedules.modal.create')}
          </Button>
        </div>
      </div>
    </Modal>
  );
}

type FrequencyTabsProps = {
  frequency: ScheduleFrequency;
  onChange: (f: ScheduleFrequency) => void;
  labels: Record<ScheduleFrequency, string>;
};

function FrequencyTabs({ frequency, onChange, labels }: FrequencyTabsProps) {
  return (
    <div className="bg-muted/60 dark:bg-muted/40 inline-flex w-full gap-1 rounded-full p-1">
      {FREQUENCIES.map((f) => {
        const active = f === frequency;
        return (
          <button
            key={f}
            type="button"
            onClick={() => onChange(f)}
            className={cn(
              'flex-1 rounded-full px-3 py-1.5 text-xs font-medium transition-colors',
              active
                ? 'bg-card text-foreground shadow-sm'
                : 'text-muted-foreground hover:text-foreground',
            )}
            aria-pressed={active}
          >
            {labels[f]}
          </button>
        );
      })}
    </div>
  );
}

type OnPickerProps = {
  values: ScheduleFormValues;
  onChange: (next: ScheduleFormValues) => void;
  tDay: (key: string) => string;
  tMonth: (key: string) => string;
  labels: { on: string; at: string; pickDate: string };
};

function OnPicker({ values, onChange, tDay, tMonth, labels }: OnPickerProps) {
  const set = (patch: Partial<ScheduleFormValues>) =>
    onChange({ ...values, ...patch });

  return (
    <div className="border-border flex flex-col gap-3 rounded-md border p-3">
      {values.frequency === 'once' && (
        <div className="flex flex-wrap items-center justify-between gap-2">
          <span className="text-foreground text-sm font-medium">
            {labels.on}
          </span>
          <div className="flex items-center gap-2">
            <DatePicker
              value={values.date}
              onChange={(date) => set({ date })}
              placeholder={labels.pickDate}
            />
            <TimeInput
              value={values.time}
              onChange={(time) => set({ time })}
              ariaLabel={labels.at}
            />
          </div>
        </div>
      )}

      {values.frequency === 'daily' && (
        <div className="flex items-center justify-between gap-2">
          <span className="text-foreground text-sm font-medium">
            {labels.at}
          </span>
          <TimeInput
            value={values.time}
            onChange={(time) => set({ time })}
            ariaLabel={labels.at}
          />
        </div>
      )}

      {values.frequency === 'weekly' && (
        <div className="flex flex-col gap-2">
          <div className="flex flex-wrap gap-1">
            {DAY_OPTIONS.map((d) => {
              const active = d.value === values.dayOfWeek;
              return (
                <Button
                  key={d.key}
                  type="button"
                  size="sm"
                  variant={active ? 'default' : 'outline'}
                  onClick={() => set({ dayOfWeek: d.value })}
                  className="rounded-full"
                  aria-pressed={active}
                >
                  {tDay(d.key)}
                </Button>
              );
            })}
          </div>
          <div className="flex items-center justify-between gap-2">
            <span className="text-foreground text-sm font-medium">
              {labels.at}
            </span>
            <TimeInput
              value={values.time}
              onChange={(time) => set({ time })}
              ariaLabel={labels.at}
            />
          </div>
        </div>
      )}

      {values.frequency === 'monthly' && (
        <div className="flex flex-wrap items-center justify-between gap-2">
          <span className="text-foreground text-sm font-medium">
            {labels.on}
          </span>
          <div className="flex items-center gap-2">
            <DayOfMonthSelect
              value={values.dayOfMonth}
              onChange={(dayOfMonth) => set({ dayOfMonth })}
              ariaLabel={labels.on}
            />
            <TimeInput
              value={values.time}
              onChange={(time) => set({ time })}
              ariaLabel={labels.at}
            />
          </div>
        </div>
      )}

      {values.frequency === 'yearly' && (
        <div className="flex flex-wrap items-center justify-between gap-2">
          <span className="text-foreground text-sm font-medium">
            {labels.on}
          </span>
          <div className="flex flex-wrap items-center gap-2">
            <MonthSelect
              value={values.month}
              onChange={(month) => set({ month })}
              tMonth={tMonth}
              ariaLabel={labels.on}
            />
            <DayOfMonthSelect
              value={values.dayOfMonth}
              onChange={(dayOfMonth) => set({ dayOfMonth })}
              ariaLabel={labels.on}
            />
            <TimeInput
              value={values.time}
              onChange={(time) => set({ time })}
              ariaLabel={labels.at}
            />
          </div>
        </div>
      )}
    </div>
  );
}

type DatePickerProps = {
  value: string;
  onChange: (next: string) => void;
  placeholder: string;
};

function DatePicker({ value, onChange, placeholder }: DatePickerProps) {
  const [open, setOpen] = useState<boolean>(false);
  const selected = dateStringToDate(value);
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          type="button"
          variant="outline"
          size="sm"
          aria-label={placeholder}
          className={cn(
            'h-9 justify-start gap-2 px-3 font-normal',
            !value && 'text-muted-foreground',
          )}
        >
          <CalendarIcon className="size-4 opacity-70" />
          {value ? formatDateLabel(value) : placeholder}
        </Button>
      </PopoverTrigger>
      {/* z-200 keeps the popover above Modal (z-50); matches SelectContent. */}
      <PopoverContent className="z-200 w-auto p-0" align="start">
        <Calendar
          mode="single"
          selected={selected}
          onSelect={(d) => {
            if (!d) return;
            onChange(dateToDateString(d));
            setOpen(false);
          }}
          captionLayout="dropdown"
        />
      </PopoverContent>
    </Popover>
  );
}

type TimeInputProps = {
  value: string;
  onChange: (next: string) => void;
  ariaLabel: string;
};

// Theme-aware replacement for <input type="time"> (clock icon + hours/minutes selects).
function TimeInput({ value, onChange, ariaLabel }: TimeInputProps) {
  return <TimePicker value={value} onChange={onChange} ariaLabel={ariaLabel} />;
}

type DayOfMonthSelectProps = {
  value: number;
  onChange: (next: number) => void;
  ariaLabel: string;
};

function DayOfMonthSelect({
  value,
  onChange,
  ariaLabel,
}: DayOfMonthSelectProps) {
  return (
    <Select value={String(value)} onValueChange={(v) => onChange(Number(v))}>
      <SelectTrigger size="sm" aria-label={ariaLabel} className="h-9 w-[5rem]">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {Array.from({ length: 31 }, (_, i) => i + 1).map((d) => (
          <SelectItem key={d} value={String(d)}>
            {d}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

type MonthSelectProps = {
  value: number;
  onChange: (next: number) => void;
  tMonth: (key: string) => string;
  ariaLabel: string;
};

function MonthSelect({ value, onChange, tMonth, ariaLabel }: MonthSelectProps) {
  return (
    <Select value={String(value)} onValueChange={(v) => onChange(Number(v))}>
      <SelectTrigger
        size="sm"
        aria-label={ariaLabel}
        className="h-9 w-[6.5rem]"
      >
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {MONTH_KEYS.map((k, i) => (
          <SelectItem key={k} value={String(i + 1)}>
            {tMonth(k)}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
