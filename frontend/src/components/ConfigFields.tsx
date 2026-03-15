import { useMemo } from 'react';

import { cn } from '@/lib/utils';

import { ConfigRequirements } from '../modals/types';
import { Input } from './ui/input';
import { Label } from './ui/label';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from './ui/select';

type ConfigValues = { [key: string]: any };

interface ConfigFieldsProps {
  configRequirements: ConfigRequirements;
  values: ConfigValues;
  onChange: (key: string, value: any) => void;
  errors?: { [key: string]: string };
  isEditing?: boolean;
  hasEncryptedCredentials?: boolean;
}

function shouldShowField(
  spec: ConfigRequirements[string],
  values: ConfigValues,
): boolean {
  if (!spec.depends_on) return true;
  return Object.entries(spec.depends_on).every(
    ([depKey, depValue]) => values[depKey] === depValue,
  );
}

export default function ConfigFields({
  configRequirements,
  values,
  onChange,
  errors = {},
  isEditing = false,
  hasEncryptedCredentials = false,
}: ConfigFieldsProps) {
  const sortedFields = useMemo(
    () =>
      Object.entries(configRequirements).sort(
        ([, a], [, b]) => (a.order ?? 99) - (b.order ?? 99),
      ),
    [configRequirements],
  );

  if (sortedFields.length === 0) return null;

  return (
    <div className="flex flex-col gap-4">
      {sortedFields.map(([key, spec]) => {
        if (!shouldShowField(spec, values)) return null;

        const value = values[key] ?? spec.default ?? '';
        const hasEncrypted =
          isEditing && spec.secret && hasEncryptedCredentials;
        const placeholder = hasEncrypted ? '••••••••' : '';
        const hasError = !!errors[key];

        if (spec.enum) {
          return (
            <div key={key} className="flex flex-col gap-1.5">
              <Label htmlFor={key}>
                {spec.label || key}
                {spec.required && (
                  <span className="text-red-500">*</span>
                )}
              </Label>
              <Select
                value={value || spec.default || ''}
                onValueChange={(v) => onChange(key, v)}
              >
                <SelectTrigger
                  id={key}
                  variant="ghost"
                  size="lg"
                  className={cn(
                    'w-full rounded-xl',
                    hasError && 'border-destructive aria-invalid:ring-destructive/20',
                  )}
                >
                  <SelectValue placeholder={spec.label || key} />
                </SelectTrigger>
                <SelectContent>
                  {spec.enum.map((v) => (
                    <SelectItem key={v} value={v}>
                      {v.charAt(0).toUpperCase() + v.slice(1).replace(/_/g, ' ')}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {hasError && (
                <p className="text-xs text-destructive">{errors[key]}</p>
              )}
            </div>
          );
        }

        return (
          <div key={key} className="flex flex-col gap-1.5">
            <Label htmlFor={key}>
              {spec.label || key}
              {spec.required && (
                <span className="text-red-500">*</span>
              )}
            </Label>
            <Input
              id={key}
              type={
                spec.secret
                  ? 'password'
                  : spec.type === 'number'
                    ? 'number'
                    : 'text'
              }
              value={value}
              onChange={(e) => {
                const v = e.target.value;
                if (spec.type === 'number') {
                  if (v === '') onChange(key, '');
                  else {
                    const num = parseInt(v, 10);
                    if (!isNaN(num)) onChange(key, num);
                  }
                } else {
                  onChange(key, v);
                }
              }}
              placeholder={placeholder || spec.description || ''}
              min={spec.type === 'number' ? 1 : undefined}
              max={spec.type === 'number' && key === 'timeout' ? 300 : undefined}
              aria-invalid={hasError || undefined}
              className={cn('rounded-xl', hasError && 'border-destructive')}
            />
            {hasError && (
              <p className="text-xs text-destructive">{errors[key]}</p>
            )}
          </div>
        );
      })}
    </div>
  );
}
