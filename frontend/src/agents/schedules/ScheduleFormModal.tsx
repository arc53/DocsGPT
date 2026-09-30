import { CalendarIcon, CircleAlert, TriangleAlert } from 'lucide-react';
import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Calendar } from '@/components/ui/calendar';
import { Card } from '@/components/ui/card';
import { Checkbox } from '@/components/ui/checkbox';
import { FormField } from '@/components/ui/form-field';
import { Input } from '@/components/ui/input';
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
import { Textarea } from '@/components/ui/textarea';
import { TimePicker } from '@/components/ui/time-picker';
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';

import { Modal } from '../../components/ui/modal';
import { formatDateOnly } from '../../utils/dateTimeUtils';
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
import {
  buildToolAllowlist,
  initialApprovedIds,
  type ApprovalTool,
} from './toolApproval';

export type ScheduleFormModalProps = {
  open: boolean;
  initial?: Schedule | null;
  /** The agent's tools with an action that needs approval (see toolApproval). */
  approvalTools: ApprovalTool[];
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
  return formatDateOnly(value);
};

/** Whether two ISO timestamps fall in the same minute. */
const sameMinute = (a: string, b: string): boolean =>
  Math.floor(new Date(a).getTime() / 60000) ===
  Math.floor(new Date(b).getTime() / 60000);

/** Create/edit a Schedule via a modal dialog. */
export default function ScheduleFormModal({
  open,
  initial,
  approvalTools,
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
  // Nothing that needs approval runs unattended until the user ticks it.
  const [approvedIds, setApprovedIds] = useState<string[]>(() =>
    initialApprovedIds(
      approvalTools.map((tool) => tool.id),
      initial?.tool_allowlist,
    ),
  );
  const toggleApproved = (id: string, checked: boolean) =>
    setApprovedIds((current) =>
      checked
        ? [...current.filter((item) => item !== id), id]
        : current.filter((item) => item !== id),
    );
  const timezoneOptions = useMemo<string[]>(() => {
    const list = supportedTimezones();
    // Make sure the current selection is always present, even if absent from
    // the engine's supported list (e.g. an exotic tz saved on the schedule).
    return list.includes(timezone) ? list : [timezone, ...list];
  }, [timezone]);
  // A missing instruction is the Instructions field's error; a run time in
  // the past spans the date, time and timezone, so it is an Alert.
  const [instructionError, setInstructionError] = useState<string | null>(null);
  const [runAtError, setRunAtError] = useState<string | null>(null);
  // Why the server refused the save; its message is shown as the detail.
  const [saveError, setSaveError] = useState<string | null>(null);
  const setError = (field: 'instruction' | 'runAt', message: string) => {
    setInstructionError(field === 'instruction' ? message : null);
    setRunAtError(field === 'runAt' ? message : null);
  };

  const setFrequency = (frequency: ScheduleFrequency) =>
    setValues((current) => ({ ...current, frequency }));

  const submit = async () => {
    if (!instruction.trim()) {
      setError(
        'instruction',
        t('agents.schedules.modal.errors.instructionRequired'),
      );
      return;
    }
    const payload: ScheduleCreatePayload = {
      instruction: instruction.trim(),
      timezone,
      name: name.trim() || undefined,
      tool_allowlist: buildToolAllowlist(
        approvalTools.map((tool) => tool.id),
        approvedIds,
        initial?.tool_allowlist,
      ),
    };
    if (values.frequency === 'once') {
      let runAt: string;
      try {
        runAt = buildRunAtUtc(values.date, values.time, timezone);
      } catch {
        setError('runAt', t('agents.schedules.modal.errors.runAtInPast'));
        return;
      }
      payload.trigger_type = 'once';
      // An edit that keeps the saved time leaves run_at out, so renaming a
      // task that is due soon (or a paused one whose time has passed) isn't
      // refused as a time in the past. The form works in whole minutes.
      const unchanged =
        initial?.trigger_type === 'once' &&
        Boolean(initial.run_at) &&
        sameMinute(runAt, initial.run_at as string);
      if (!unchanged) {
        if (new Date(runAt).getTime() <= Date.now()) {
          setError('runAt', t('agents.schedules.modal.errors.runAtInPast'));
          return;
        }
        payload.run_at = runAt;
      }
    } else {
      const cron = buildCron(values.frequency, values);
      if (!cron) {
        setError(
          'instruction',
          t('agents.schedules.modal.errors.instructionRequired'),
        );
        return;
      }
      payload.trigger_type = 'recurring';
      payload.cron = cron;
    }
    setInstructionError(null);
    setRunAtError(null);
    setSaveError(null);
    try {
      await onSubmit(payload);
    } catch (err) {
      // A thunk's unwrap() rejects with a serialized error: a plain object
      // with the message, not an Error instance.
      const message = (err as { message?: unknown } | null)?.message;
      setSaveError(typeof message === 'string' ? message : '');
    }
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
      mobileVariant="sheet"
      footer={
        <Button
          type="button"
          size="lg"
          shape="pill"
          loading={submitting}
          onClick={submit}
        >
          {isEdit
            ? t('agents.schedules.modal.save')
            : t('agents.schedules.modal.create')}
        </Button>
      }
    >
      <div className="flex flex-col gap-5">
        <div className="flex items-start gap-3 pr-6">
          <Input
            type="text"
            variant="bare"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder={t('agents.schedules.modal.namePlaceholder')}
            /* eslint-disable-next-line shadcn/no-restyle -- the schedule's
               name is the dialog's editable title, so the bare field keeps
               title type (20px semibold); DESIGN.md Approved exceptions. */
            className="w-full text-xl font-semibold"
            aria-label={t('agents.schedules.modal.namePlaceholder')}
          />
        </div>

        <FrequencyTabs
          frequency={values.frequency}
          onChange={setFrequency}
          lockedKind={
            isEdit
              ? initial?.trigger_type === 'once'
                ? 'once'
                : 'recurring'
              : undefined
          }
          labels={{
            once: t('agents.schedules.modal.frequency.once'),
            daily: t('agents.schedules.modal.frequency.daily'),
            weekly: t('agents.schedules.modal.frequency.weekly'),
            monthly: t('agents.schedules.modal.frequency.monthly'),
            yearly: t('agents.schedules.modal.frequency.yearly'),
          }}
          ariaLabel={t('agents.schedules.modal.frequencyLabel')}
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
            days: t('agents.schedules.modal.dayOfWeek'),
          }}
        />

        <Card
          padding="sm"
          className="flex-row flex-wrap items-center justify-between gap-2"
        >
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
        </Card>

        <FormField
          label={t('agents.schedules.modal.instructionsLabel')}
          error={instructionError}
        >
          <Textarea
            value={instruction}
            onChange={(e) => setInstruction(e.target.value)}
            placeholder={t('agents.schedules.modal.instructionsPlaceholder')}
            rows={5}
          />
        </FormField>

        {approvalTools.length > 0 && (
          <ApprovalToolsPicker
            tools={approvalTools}
            approvedIds={approvedIds}
            onToggle={toggleApproved}
            labels={{
              label: t('agents.schedules.modal.approvalTools.label'),
              hint: t('agents.schedules.modal.approvalTools.hint'),
              warning: t('agents.schedules.modal.approvalTools.warning'),
            }}
          />
        )}

        {runAtError && (
          <Alert variant="destructive">
            <CircleAlert aria-hidden="true" className="size-4" />
            <AlertDescription>{runAtError}</AlertDescription>
          </Alert>
        )}

        {saveError !== null && (
          <Alert variant="destructive">
            <CircleAlert aria-hidden="true" className="size-4" />
            <AlertDescription>
              <p>{t('agents.schedules.modal.errors.saveFailed')}</p>
              {saveError && <p>{saveError}</p>}
            </AlertDescription>
          </Alert>
        )}
      </div>
    </Modal>
  );
}

type ApprovalToolsPickerProps = {
  tools: ApprovalTool[];
  approvedIds: string[];
  onToggle: (id: string, checked: boolean) => void;
  labels: { label: string; hint: string; warning: string };
};

/**
 * Opt-in checkboxes for the tools whose actions need approval. A ticked tool
 * runs those actions in a scheduled run without asking, so the warning stays
 * in view while any tool is listed.
 */
function ApprovalToolsPicker({
  tools,
  approvedIds,
  onToggle,
  labels,
}: ApprovalToolsPickerProps) {
  return (
    <Card padding="sm">
      <fieldset className="m-0 flex min-w-0 flex-col gap-3 border-0 p-0">
        <legend className="text-foreground text-sm font-medium">
          {labels.label}
        </legend>
        <p className="text-muted-foreground text-xs">{labels.hint}</p>
        <div className="flex flex-col gap-2.5">
          {tools.map((tool) => {
            const id = `schedule-approve-${tool.id}`;
            return (
              <label
                key={tool.id}
                htmlFor={id}
                className="flex cursor-pointer items-center gap-3"
              >
                <Checkbox
                  id={id}
                  checked={approvedIds.includes(tool.id)}
                  onCheckedChange={(checked) =>
                    onToggle(tool.id, checked === true)
                  }
                />
                <span className="text-foreground min-w-0 text-sm break-words">
                  {tool.name}
                </span>
              </label>
            );
          })}
        </div>
        <Alert variant="warning" role="note">
          <TriangleAlert aria-hidden="true" />
          <AlertDescription>{labels.warning}</AlertDescription>
        </Alert>
      </fieldset>
    </Card>
  );
}

type FrequencyTabsProps = {
  frequency: ScheduleFrequency;
  onChange: (f: ScheduleFrequency) => void;
  labels: Record<ScheduleFrequency, string>;
  ariaLabel: string;
  /** When editing, the saved kind; tabs of the other kind are disabled. */
  lockedKind?: 'once' | 'recurring';
};

function FrequencyTabs({
  frequency,
  onChange,
  labels,
  ariaLabel,
  lockedKind,
}: FrequencyTabsProps) {
  // A saved schedule can't change between one-time and recurring: the API
  // keeps its trigger type, so the other kind's tabs are disabled.
  const isDisabled = (f: ScheduleFrequency) =>
    lockedKind !== undefined && (f === 'once') !== (lockedKind === 'once');
  return (
    // The muted track is a plain wrapper: ToggleGroup takes layout only.
    <div className="bg-muted w-full rounded-full p-1">
      <ToggleGroup
        type="single"
        size="xs"
        value={frequency}
        onValueChange={(f) => f && onChange(f as ScheduleFrequency)}
        aria-label={ariaLabel}
        className="flex-nowrap"
      >
        {FREQUENCIES.map((f) => (
          <ToggleGroupItem
            key={f}
            value={f}
            disabled={isDisabled(f)}
            className="flex-1"
          >
            {labels[f]}
          </ToggleGroupItem>
        ))}
      </ToggleGroup>
    </div>
  );
}

type OnPickerProps = {
  values: ScheduleFormValues;
  onChange: (next: ScheduleFormValues) => void;
  tDay: (key: string) => string;
  tMonth: (key: string) => string;
  labels: { on: string; at: string; pickDate: string; days: string };
};

function OnPicker({ values, onChange, tDay, tMonth, labels }: OnPickerProps) {
  const set = (patch: Partial<ScheduleFormValues>) =>
    onChange({ ...values, ...patch });

  return (
    <Card padding="sm">
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
          {/* A weekly schedule runs on one day: a radio group. */}
          <ToggleGroup
            type="single"
            value={String(values.dayOfWeek)}
            onValueChange={(day) => day && set({ dayOfWeek: Number(day) })}
            aria-label={labels.days}
          >
            {DAY_OPTIONS.map((d) => (
              <ToggleGroupItem key={d.key} value={String(d.value)}>
                {tDay(d.key)}
              </ToggleGroupItem>
            ))}
          </ToggleGroup>
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
    </Card>
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
          variant="combobox"
          aria-label={placeholder}
          data-placeholder={value ? undefined : ''}
          className="justify-start"
        >
          <CalendarIcon className="opacity-70" />
          {value ? formatDateLabel(value) : placeholder}
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-auto p-0" align="start">
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
      <SelectTrigger aria-label={ariaLabel} className="w-[5rem]">
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
      <SelectTrigger aria-label={ariaLabel} className="w-[6.5rem]">
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
