import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { ToggleGroup, ToggleGroupItem } from '../components/ui/toggle-group';
import type { ActionParameter } from './types';

type Mode = 'ai' | 'fixed';
export type ParameterValue = string | number | boolean | null;

const shown = (parameter: ActionParameter) =>
  parameter.fixed && parameter.value !== null ? String(parameter.value) : '';

function ParameterRow({
  parameter,
  readOnly,
  onSave,
}: {
  parameter: ActionParameter;
  readOnly: boolean;
  onSave: (value: ParameterValue) => Promise<boolean>;
}) {
  const { t } = useTranslation();
  const saved = shown(parameter);
  const [mode, setMode] = useState<Mode>(parameter.fixed ? 'fixed' : 'ai');
  const [draft, setDraft] = useState(saved);
  const [saving, setSaving] = useState(false);
  // A save (here or elsewhere) brings the stored value back.
  useEffect(() => {
    setMode(parameter.fixed ? 'fixed' : 'ai');
    setDraft(shown(parameter));
  }, [parameter]);

  const save = async (value: ParameterValue) => {
    setSaving(true);
    const ok = await onSave(value);
    setSaving(false);
    if (!ok) {
      setMode(parameter.fixed ? 'fixed' : 'ai');
      setDraft(saved);
    }
  };

  const choiceLabel = t('settings.connectors.parameters.choiceLabel', {
    parameter: parameter.name,
    interpolation: { escapeValue: false },
  });

  return (
    <li data-parameter={parameter.name} className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="min-w-0">
          <p className="text-foreground font-mono text-xs wrap-anywhere">
            {parameter.name}
          </p>
          {parameter.description && (
            <p
              className="text-muted-foreground line-clamp-2 text-xs"
              title={parameter.description}
            >
              {parameter.description}
            </p>
          )}
        </div>
        <div className="bg-muted rounded-full p-1">
          <ToggleGroup
            type="single"
            size="xs"
            value={mode}
            disabled={readOnly || saving}
            aria-label={choiceLabel}
            onValueChange={(value) => {
              if (!value) return;
              setMode(value as Mode);
              // Releasing a fixed value saves at once; fixing one waits for it.
              if (value === 'ai' && parameter.fixed) save(null);
            }}
          >
            <ToggleGroupItem value="ai" data-mode="ai">
              {t('settings.connectors.parameters.ai')}
            </ToggleGroupItem>
            <ToggleGroupItem value="fixed" data-mode="fixed">
              {t('settings.connectors.parameters.fixed')}
            </ToggleGroupItem>
          </ToggleGroup>
        </div>
      </div>
      {mode === 'fixed' && (
        <form
          className="flex items-center gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            if (draft.trim() && draft !== saved) save(draft);
          }}
        >
          <Input
            size="sm"
            className="flex-1"
            aria-label={t('settings.connectors.parameters.valueLabel', {
              parameter: parameter.name,
              interpolation: { escapeValue: false },
            })}
            value={draft}
            disabled={readOnly}
            onChange={(event) => setDraft(event.target.value)}
          />
          <Button
            type="submit"
            size="sm"
            shape="pill"
            variant="outline"
            loading={saving}
            disabled={readOnly || !draft.trim() || draft === saved}
          >
            {t('settings.connectors.parameters.save')}
          </Button>
        </form>
      )}
    </li>
  );
}

/**
 * One action's parameters, each left to the AI or fixed to a value that is
 * sent on every call and never shown to the AI (a Telegram chat, a project
 * key). Letting the AI decide saves at once; a fixed value saves with Save.
 */
export default function ActionParameters({
  parameters,
  readOnly = false,
  onSave,
}: {
  parameters: ActionParameter[];
  readOnly?: boolean;
  /** Saves `{name: value}`; resolves false when the save failed. */
  onSave: (changes: Record<string, ParameterValue>) => Promise<boolean>;
}) {
  const { t } = useTranslation();
  return (
    <div className="flex flex-col gap-3">
      <ul className="flex flex-col gap-4">
        {parameters.map((parameter) => (
          <ParameterRow
            key={parameter.name}
            parameter={parameter}
            readOnly={readOnly}
            onSave={(value) => onSave({ [parameter.name]: value })}
          />
        ))}
      </ul>
      <p className="text-muted-foreground text-xs">
        {t('settings.connectors.parameters.hint')}
      </p>
    </div>
  );
}
