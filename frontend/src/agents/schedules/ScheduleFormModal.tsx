import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';

import WrapperModal from '../../modals/WrapperModal';
import type { Schedule, ScheduleCreatePayload } from '../types/schedule';
import {
  browserTimezone,
  buildCron,
  buildRunAtUtc,
  parseScheduleToFormValues,
  type ScheduleFormValues,
  type ScheduleFrequency,
  todayDate,
} from './cronBuilder';

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
  const timezone = useMemo<string>(() => browserTimezone(), []);

  const defaults: ScheduleFormValues = useMemo(
    () =>
      initial
        ? parseScheduleToFormValues(initial, timezone)
        : {
            frequency: 'daily',
            date: todayDate(timezone),
            time: '09:00',
            dayOfWeek: 1,
            dayOfMonth: 1,
            month: 1,
          },
    [initial, timezone],
  );

  const [name, setName] = useState<string>(initial?.name ?? '');
  const [instruction, setInstruction] = useState<string>(
    initial?.instruction ?? '',
  );
  const [values, setValues] = useState<ScheduleFormValues>(defaults);
  const [error, setError] = useState<string | null>(null);

  if (!open) return null;

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
    <WrapperModal
      className="w-[min(560px,92vw)] sm:p-6"
      contentClassName="max-h-[80vh]"
      close={onClose}
      isPerformingTask={submitting}
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
          }}
        />

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
          <button
            type="button"
            disabled={submitting}
            onClick={submit}
            className="bg-primary text-primary-foreground hover:bg-primary/90 rounded-full px-5 py-2 text-sm font-semibold disabled:opacity-60"
          >
            {submitting
              ? '…'
              : isEdit
                ? t('agents.schedules.modal.save')
                : t('agents.schedules.modal.create')}
          </button>
        </div>
      </div>
    </WrapperModal>
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
            className={[
              'flex-1 rounded-full px-3 py-1.5 text-xs font-medium transition-colors',
              active
                ? 'bg-card text-foreground shadow-sm'
                : 'text-muted-foreground hover:text-foreground',
            ].join(' ')}
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
  labels: { on: string; at: string };
};

function OnPicker({ values, onChange, tDay, tMonth, labels }: OnPickerProps) {
  const set = (patch: Partial<ScheduleFormValues>) =>
    onChange({ ...values, ...patch });
  const inputClass =
    'border-border bg-background text-foreground rounded-md border px-2 py-1 text-sm outline-none focus:border-ring focus:ring-ring/40 focus:ring-2';

  return (
    <div className="border-border flex flex-col gap-3 rounded-md border p-3">
      {values.frequency === 'once' && (
        <div className="flex items-center justify-between gap-2">
          <span className="text-foreground text-sm font-medium">
            {labels.on}
          </span>
          <div className="flex items-center gap-2">
            <input
              type="date"
              value={values.date}
              onChange={(e) => set({ date: e.target.value })}
              className={inputClass}
              aria-label={labels.on}
            />
            <input
              type="time"
              value={values.time}
              onChange={(e) => set({ time: e.target.value })}
              className={inputClass}
              aria-label={labels.at}
            />
          </div>
        </div>
      )}

      {values.frequency === 'daily' && (
        <div className="flex items-center justify-between gap-2">
          <span className="text-foreground text-sm font-medium">
            {labels.at}
          </span>
          <input
            type="time"
            value={values.time}
            onChange={(e) => set({ time: e.target.value })}
            className={inputClass}
            aria-label={labels.at}
          />
        </div>
      )}

      {values.frequency === 'weekly' && (
        <div className="flex flex-col gap-2">
          <div className="flex flex-wrap gap-1">
            {DAY_OPTIONS.map((d) => {
              const active = d.value === values.dayOfWeek;
              return (
                <button
                  key={d.key}
                  type="button"
                  onClick={() => set({ dayOfWeek: d.value })}
                  className={[
                    'rounded-full px-3 py-1 text-xs font-medium transition-colors',
                    active
                      ? 'bg-primary text-primary-foreground'
                      : 'border-border text-muted-foreground hover:bg-accent border',
                  ].join(' ')}
                  aria-pressed={active}
                >
                  {tDay(d.key)}
                </button>
              );
            })}
          </div>
          <div className="flex items-center justify-between gap-2">
            <span className="text-foreground text-sm font-medium">
              {labels.at}
            </span>
            <input
              type="time"
              value={values.time}
              onChange={(e) => set({ time: e.target.value })}
              className={inputClass}
              aria-label={labels.at}
            />
          </div>
        </div>
      )}

      {values.frequency === 'monthly' && (
        <div className="flex items-center justify-between gap-2">
          <span className="text-foreground text-sm font-medium">
            {labels.on}
          </span>
          <div className="flex items-center gap-2">
            <select
              value={values.dayOfMonth}
              onChange={(e) => set({ dayOfMonth: Number(e.target.value) })}
              className={inputClass}
              aria-label={labels.on}
            >
              {Array.from({ length: 31 }, (_, i) => i + 1).map((d) => (
                <option key={d} value={d}>
                  {d}
                </option>
              ))}
            </select>
            <input
              type="time"
              value={values.time}
              onChange={(e) => set({ time: e.target.value })}
              className={inputClass}
              aria-label={labels.at}
            />
          </div>
        </div>
      )}

      {values.frequency === 'yearly' && (
        <div className="flex items-center justify-between gap-2">
          <span className="text-foreground text-sm font-medium">
            {labels.on}
          </span>
          <div className="flex items-center gap-2">
            <select
              value={values.month}
              onChange={(e) => set({ month: Number(e.target.value) })}
              className={inputClass}
              aria-label={labels.on}
            >
              {MONTH_KEYS.map((k, i) => (
                <option key={k} value={i + 1}>
                  {tMonth(k)}
                </option>
              ))}
            </select>
            <select
              value={values.dayOfMonth}
              onChange={(e) => set({ dayOfMonth: Number(e.target.value) })}
              className={inputClass}
              aria-label={labels.on}
            >
              {Array.from({ length: 31 }, (_, i) => i + 1).map((d) => (
                <option key={d} value={d}>
                  {d}
                </option>
              ))}
            </select>
            <input
              type="time"
              value={values.time}
              onChange={(e) => set({ time: e.target.value })}
              className={inputClass}
              aria-label={labels.at}
            />
          </div>
        </div>
      )}
    </div>
  );
}
