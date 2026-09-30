import { Clock } from 'lucide-react';
import { useState } from 'react';
import { Calendar } from '@/components/ui/calendar';
import { Label } from '@/components/ui/label';
import { TimePicker } from '@/components/ui/time-picker';
import { Example, Section } from '../shared';

export default function PickerSection() {
  const [time, setTime] = useState('09:30');
  const [date, setDate] = useState<Date | undefined>(new Date());
  return (
    <Section
      id="pickers"
      title="Pickers"
      intro="Calendar wraps react-day-picker with the Button ghost variant; TimePicker is two Selects."
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
    </Section>
  );
}
