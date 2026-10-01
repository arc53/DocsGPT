import { Clock } from 'lucide-react';
import { useState } from 'react';
import { Avatar } from '@/components/ui/avatar';
import { Calendar } from '@/components/ui/calendar';
import {
  Combobox,
  type ComboboxGroup,
  type ComboboxOption,
} from '@/components/ui/combobox';
import { FormField } from '@/components/ui/form-field';
import { Label } from '@/components/ui/label';
import { TimePicker } from '@/components/ui/time-picker';
import { Example, Section } from '../shared';

const TIMEZONES: ComboboxOption[] = [
  {
    value: 'Europe/London',
    label: 'Europe/London',
    hint: 'UTC+01:00',
    keywords: ['London', 'BST'],
  },
  {
    value: 'Europe/Berlin',
    label: 'Europe/Berlin',
    hint: 'UTC+02:00',
    keywords: ['Berlin', 'CEST'],
  },
  {
    value: 'Europe/Oslo',
    label: 'Europe/Oslo',
    hint: 'UTC+02:00',
    keywords: ['Oslo'],
  },
  {
    value: 'America/Chicago',
    label: 'America/Chicago',
    hint: 'UTC−05:00',
    keywords: ['Chicago', 'CDT'],
  },
  {
    value: 'Asia/Singapore',
    label: 'Asia/Singapore',
    hint: 'UTC+08:00',
    keywords: ['Singapore'],
  },
];

const MODELS: ComboboxOption[] = [
  { value: 'gpt-4.1', label: 'GPT-4.1' },
  { value: 'claude-sonnet', label: 'Claude Sonnet' },
  { value: 'llama-70b', label: 'Llama 3.3 70B' },
];

const AGENTS: ComboboxOption[] = [
  { value: 'vdd', label: 'Vendor Due Diligence' },
  { value: 'cpa', label: 'Contracts & Policy Assistant' },
  { value: 'crd', label: 'Customer Renewal Desk' },
];

const initialAvatar = (label: string, shape: 'circle' | 'square') => (
  <Avatar alt="" variant="primary" size="xs" shape={shape}>
    {label.charAt(0)}
  </Avatar>
);

const SHARE_GROUPS: ComboboxGroup[] = [
  {
    heading: 'Teams',
    options: ['Operations', 'Carrier Relations'].map((label) => ({
      value: `team:${label}`,
      label,
      leading: initialAvatar(label, 'square'),
    })),
  },
  {
    heading: 'People',
    options: ['Dana Whitfield', 'Marcus Lindqvist', 'Priya Raman'].map(
      (label) => ({
        value: `user:${label}`,
        label,
        leading: initialAvatar(label, 'circle'),
      }),
    ),
  },
];

export default function PickerSection() {
  const [time, setTime] = useState('09:30');
  const [date, setDate] = useState<Date | undefined>(new Date());
  const [timezone, setTimezone] = useState<string | null>('Europe/Berlin');
  const [model, setModel] = useState<string | null>(null);
  const [agent, setAgent] = useState<string | null>('vdd');
  const [shared, setShared] = useState<string[]>([]);
  return (
    <Section
      id="pickers"
      title="Pickers"
      intro="Calendar wraps react-day-picker with the Button ghost variant; TimePicker is two Selects. A searchable single-select is Combobox: never a hand-built Popover + Command."
    >
      <Example
        title="Calendar and time"
        code='<Calendar mode="single"> · <TimePicker>'
      >
        <div className="flex flex-wrap items-start gap-8">
          <div className="border-border rounded-lg border">
            <Calendar mode="single" selected={date} onSelect={setDate} />
          </div>
          <div className="flex flex-col gap-3">
            <Label>Run at</Label>
            <TimePicker value={time} onChange={setTime} minuteStep={5} />
            <p className="text-muted-foreground flex items-center gap-1 text-xs">
              <Clock className="size-3" />
              {date ? date.toLocaleDateString('en-GB') : 'No date'} at {time}
            </p>
          </div>
        </div>
      </Example>
      <Example
        title="Combobox"
        code='<Combobox options | groups value onValueChange placeholder searchPlaceholder emptyText shape="pill"?> · hint = muted trailing value · inside a FormField it takes the field id and error · modal by default · server search: shouldFilter={false} search onSearchChange · row actions: renderItem'
      >
        <div className="grid items-start gap-6 md:grid-cols-2">
          <div className="flex flex-col gap-2">
            <Label htmlFor="ds-timezone">Timezone</Label>
            <Combobox
              id="ds-timezone"
              options={TIMEZONES}
              value={timezone}
              onValueChange={setTimezone}
              placeholder="Select a timezone…"
              searchPlaceholder="Search timezones"
              emptyText="No timezone found."
            />
            <span className="text-muted-foreground text-xs">
              A hint (the UTC offset) on the rows and the trigger
            </span>
          </div>
          <FormField
            label="Model"
            required
            error={model ? undefined : 'Pick a model for this agent'}
          >
            <Combobox
              options={MODELS}
              value={model}
              onValueChange={setModel}
              placeholder="Select a model"
              searchPlaceholder="Search models"
              emptyText="No model found."
            />
          </FormField>
          <div className="flex flex-col gap-2">
            <Combobox
              aria-label="Agent"
              shape="pill"
              className="w-64"
              options={AGENTS}
              value={agent}
              onValueChange={setAgent}
              placeholder="All agents"
              searchPlaceholder="Search agents"
              emptyText="No agent found."
            />
            <span className="text-muted-foreground text-xs">
              shape=&quot;pill&quot; in a page toolbar
            </span>
          </div>
          <div className="flex flex-col gap-2">
            <Combobox
              aria-label="Add people or teams"
              mode="add"
              groups={SHARE_GROUPS.map((group) => ({
                ...group,
                options: group.options.filter(
                  (option) => !shared.includes(option.value),
                ),
              }))}
              onValueChange={(value) =>
                setShared((current) => [...current, value])
              }
              placeholder="Add people or teams"
              searchPlaceholder="Search people and teams"
              emptyText="Everyone is already added."
            />
            <span className="text-muted-foreground text-xs">
              mode=&quot;add&quot; with groups: picking adds, the trigger keeps
              the placeholder
              {shared.length
                ? ` (added ${shared
                    .map((value) => value.split(':')[1])
                    .join(', ')})`
                : ''}
            </span>
          </div>
        </div>
      </Example>
    </Section>
  );
}
