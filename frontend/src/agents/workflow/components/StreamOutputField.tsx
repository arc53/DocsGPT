import { useTranslation } from 'react-i18next';

import { FormField } from '@/components/ui/form-field';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';

import {
  normalizeStreamOutput,
  STREAM_OUTPUT_OPTIONS,
  type StreamOutput,
} from '../streamOutputConfig';

/** The node's `stream_output`: how much of a finished step the chat stream carries. */
export default function StreamOutputField({
  value,
  onChange,
}: {
  value: unknown;
  onChange: (value: StreamOutput) => void;
}) {
  const { t } = useTranslation();
  return (
    <FormField
      label={t('agents.workflow.builder.streamOutput')}
      hint={t('agents.workflow.builder.streamOutputHint')}
      labelSurface="background"
    >
      <Select
        value={normalizeStreamOutput(value)}
        onValueChange={(next) => onChange(next as StreamOutput)}
      >
        <SelectTrigger size="field" className="w-full">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {STREAM_OUTPUT_OPTIONS.map((option) => (
            <SelectItem key={option.value} value={option.value}>
              {t(`agents.workflow.streamOutput.${option.value}`, {
                defaultValue: option.label,
              })}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </FormField>
  );
}
