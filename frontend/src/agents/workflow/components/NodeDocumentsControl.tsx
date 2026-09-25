import { Plus } from 'lucide-react';
import { useId, useState } from 'react';

import { Button } from '@/components/ui/button';
import { FormField } from '@/components/ui/form-field';
import { Input } from '@/components/ui/input';
import { MultiSelect } from '@/components/ui/multi-select';

import {
  appendDocumentRef,
  documentsModeToInputDocuments,
  DocumentsMode,
  getDocumentsMode,
  withChosenDocumentOptions,
} from '../documentConfig';

interface NodeDocumentsControlProps {
  value: string[];
  onChange: (next: string[]) => void;
  options: { value: string; label: string }[];
  label: string;
  helpText?: string;
}

const MODE_OPTIONS: { mode: DocumentsMode; label: string }[] = [
  { mode: 'all', label: 'All input docs' },
  { mode: 'none', label: 'None' },
  { mode: 'choose', label: 'Choose…' },
];

/** Shared All/None/Choose documents picker for agent and code workflow nodes. */
export default function NodeDocumentsControl({
  value,
  onChange,
  options,
  label,
  helpText,
}: NodeDocumentsControlProps) {
  // Track mode in component state so "Choose" stays reachable even when the
  // chosen list is empty (an empty list otherwise reads back as "None").
  const [mode, setMode] = useState<DocumentsMode>(() =>
    getDocumentsMode(value),
  );
  const [refDraft, setRefDraft] = useState('');
  const fieldId = useId();

  const chosen = documentsModeToInputDocuments('choose', value);
  const showChoose = mode === 'choose';

  const selectMode = (next: DocumentsMode) => {
    setMode(next);
    onChange(documentsModeToInputDocuments(next, chosen));
  };

  const addRef = () => {
    const next = appendDocumentRef(chosen, refDraft);
    setRefDraft('');
    if (next === chosen) return;
    setMode('choose');
    onChange(documentsModeToInputDocuments('choose', next));
  };

  return (
    <FormField label={label} hint={helpText} id={fieldId}>
      <div
        id={fieldId}
        role="group"
        aria-label={label}
        className="border-border bg-card flex gap-1 rounded-xl border p-1"
      >
        {MODE_OPTIONS.map(({ mode: optionMode, label: modeLabel }) => (
          <Button
            key={optionMode}
            type="button"
            variant={mode === optionMode ? 'outline' : 'ghost-muted'}
            size="xs"
            onClick={() => selectMode(optionMode)}
            className="flex-1"
          >
            {modeLabel}
          </Button>
        ))}
      </div>
      {showChoose && (
        <div className="flex flex-col gap-2">
          <MultiSelect
            options={withChosenDocumentOptions(options, chosen)}
            selected={chosen}
            onChange={(next) =>
              onChange(documentsModeToInputDocuments('choose', next))
            }
            placeholder="Select documents..."
            searchPlaceholder="Search variables..."
            emptyText="No upstream documents"
          />
          <div className="flex gap-2">
            <Input
              id={`${fieldId}-ref`}
              type="text"
              value={refDraft}
              onChange={(e) => setRefDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  e.preventDefault();
                  addRef();
                }
              }}
              placeholder="Add ref (e.g. A1)"
            />
            <Button
              type="button"
              variant="ghost-muted"
              onClick={addRef}
              className="shrink-0"
            >
              <Plus size={14} />
              Add
            </Button>
          </div>
        </div>
      )}
    </FormField>
  );
}
