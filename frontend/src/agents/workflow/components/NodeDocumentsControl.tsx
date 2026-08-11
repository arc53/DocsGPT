import { Plus } from 'lucide-react';
import { useState } from 'react';

import { Button } from '@/components/ui/button';
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
    <div>
      <label className="mb-2 block text-sm font-medium text-gray-700 dark:text-gray-300">
        {label}
      </label>
      <div className="border-border bg-card flex gap-1 rounded-xl border p-1">
        {MODE_OPTIONS.map(({ mode: optionMode, label: modeLabel }) => (
          <Button
            key={optionMode}
            type="button"
            variant="ghost"
            size="sm"
            onClick={() => selectMode(optionMode)}
            className={`h-auto flex-1 rounded-lg px-2 py-1.5 text-xs font-medium ${
              mode === optionMode
                ? 'bg-primary text-white'
                : 'text-gray-600 dark:text-gray-300'
            }`}
          >
            {modeLabel}
          </Button>
        ))}
      </div>
      {showChoose && (
        <div className="mt-2 flex flex-col gap-2">
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
              type="text"
              value={refDraft}
              onChange={(e) => setRefDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  e.preventDefault();
                  addRef();
                }
              }}
              className="bg-card h-auto rounded-xl px-3 py-2 text-sm shadow-none"
              placeholder="Add ref (e.g. A1)"
            />
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={addRef}
              className="h-auto shrink-0 gap-1 rounded-lg px-3 py-2 text-sm font-medium text-gray-600 dark:text-gray-300"
            >
              <Plus size={14} />
              Add
            </Button>
          </div>
        </div>
      )}
      {helpText && (
        <p className="text-muted-foreground mt-1 text-xs">{helpText}</p>
      )}
    </div>
  );
}
