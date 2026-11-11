import { Plus, X } from 'lucide-react';
import { useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';

import { Button } from '../../components/ui/button';
import { FormField } from '../../components/ui/form-field';
import { IconButton } from '../../components/ui/icon-button';
import { Input } from '../../components/ui/input';
import { MAX_STARTER_LENGTH, MAX_STARTERS } from '../starters';

/**
 * An agent's starters as an editable list, for the agent form and a
 * workflow's details: no fields until "Add a starter" (they are optional),
 * a remove button on each, and no add link once there are four. Entries are
 * kept as typed; a save cleans them (`cleanStarters`).
 */
export default function StartersFields({
  starters,
  onChange,
}: {
  starters: string[];
  onChange: (next: string[]) => void;
}) {
  const { t } = useTranslation();
  const inputs = useRef<(HTMLInputElement | null)[]>([]);
  // The field "Add a starter" just made, focused once it renders.
  const added = useRef<number | null>(null);

  useEffect(() => {
    if (added.current === null) return;
    inputs.current[added.current]?.focus();
    added.current = null;
  }, [starters.length]);

  const setStarter = (index: number, value: string) =>
    onChange(starters.map((starter, i) => (i === index ? value : starter)));

  return (
    <div className="flex flex-col gap-3">
      {starters.map((starter, index) => (
        <div key={index} className="flex items-start gap-2">
          {/* The floating label's wrapper doesn't grow by itself in a row. */}
          <FormField
            className="min-w-0 flex-1"
            labelSurface="background"
            label={t('agents.form.starters.label', { number: index + 1 })}
          >
            <Input
              ref={(input) => {
                inputs.current[index] = input;
              }}
              type="text"
              className="w-full"
              value={starter}
              maxLength={MAX_STARTER_LENGTH}
              onChange={(e) => setStarter(index, e.target.value)}
            />
          </FormField>
          <IconButton
            variant="ghost-muted"
            icon={X}
            label={t('agents.form.starters.remove', { number: index + 1 })}
            onClick={() => onChange(starters.filter((_, i) => i !== index))}
          />
        </div>
      ))}
      {starters.length < MAX_STARTERS && (
        <Button
          type="button"
          variant="link"
          size="inline"
          className="self-start"
          onClick={() => {
            added.current = starters.length;
            onChange([...starters, '']);
          }}
        >
          <Plus className="size-4" />
          {t('agents.form.starters.add')}
        </Button>
      )}
    </div>
  );
}
