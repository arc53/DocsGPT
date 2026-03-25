import React, { useEffect, useMemo, useRef, useState } from 'react';

import { ChevronDown, Pencil, Search, Trash2 } from 'lucide-react';

type OptionBase = { id?: string; type?: string };
type NameIdOption = { name: string; id: string } & OptionBase;
type LabelValueOption = { label: string; value: string } & OptionBase;
type ValueDescriptionOption = {
  value: number;
  description: string;
} & OptionBase;

export type DropdownOption =
  | string
  | NameIdOption
  | LabelValueOption
  | ValueDescriptionOption;

export type { NameIdOption, LabelValueOption, ValueDescriptionOption };

function getOptionText(option: DropdownOption): string {
  if (typeof option === 'string') return option;
  if ('name' in option) return option.name;
  if ('label' in option) return option.label;
  if ('description' in option)
    return option.value < 1e9
      ? `${option.value} (${option.description})`
      : option.description;
  return '';
}

function optionMatches(
  option: DropdownOption,
  selected: DropdownOption | null,
): boolean {
  if (!selected) return false;
  if (typeof selected === 'string') return selected === option;
  if (typeof option === 'string') return false;
  const a = option as Record<string, unknown>;
  const b = selected as Record<string, unknown>;
  if ('name' in a && 'name' in b) return a.name === b.name;
  if ('label' in a && 'label' in b) return a.label === b.label;
  if ('value' in a && 'value' in b) return a.value === b.value;
  return false;
}

export interface DropdownProps<T extends DropdownOption = DropdownOption> {
  options: T[];
  selectedValue: DropdownOption | null;
  onSelect: (value: T) => void;
  size?: string;
  rounded?: 'xl' | '3xl';
  searchable?: boolean;
  placeholder?: string;
  contentSize?: string;
  showEdit?: boolean;
  onEdit?: (value: NameIdOption) => void;
  showDelete?: boolean | ((option: T) => boolean);
  onDelete?: (id: string) => void;
}

function Dropdown<T extends DropdownOption>({
  options,
  selectedValue,
  onSelect,
  size = 'w-full',
  rounded = '3xl',
  searchable = false,
  placeholder = 'Select...',
  contentSize = 'text-sm',
  showEdit,
  onEdit,
  showDelete,
  onDelete,
}: DropdownProps<T>) {
  const ref = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');

  const radius = rounded === '3xl' ? 'rounded-3xl' : 'rounded-xl';
  const radiusTop = rounded === '3xl' ? 'rounded-t-3xl' : 'rounded-t-xl';
  const radiusBottom = rounded === '3xl' ? 'rounded-b-3xl' : 'rounded-b-xl';

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
        setQuery('');
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  useEffect(() => {
    if (open && searchable && searchRef.current) searchRef.current.focus();
  }, [open, searchable]);

  const filtered = useMemo(() => {
    if (!searchable || !query.trim()) return options;
    const q = query.toLowerCase();
    return options.filter((o) => getOptionText(o).toLowerCase().includes(q));
  }, [options, query, searchable]);

  const displayValue = selectedValue ? getOptionText(selectedValue) : null;

  return (
    <div className={`relative ${size}`} ref={ref}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className={`flex w-full cursor-pointer items-center justify-between border border-border bg-card px-5 py-3 text-foreground ${open ? radiusTop : radius}`}
      >
        <span
          className={`truncate ${contentSize} ${displayValue ? '' : 'text-muted-foreground'}`}
        >
          {displayValue ?? placeholder}
        </span>
        <ChevronDown
          className={`ml-2 h-4 w-4 shrink-0 text-muted-foreground transition-transform ${open ? 'rotate-180' : ''}`}
        />
      </button>

      {open && (
        <div
          className={`absolute inset-x-0 z-20 -mt-px overflow-hidden border border-t-0 border-border bg-card shadow-lg ${radiusBottom}`}
        >
          {searchable && (
            <div className="flex items-center border-b border-border px-3 py-2">
              <Search className="mr-2 h-4 w-4 shrink-0 text-muted-foreground" />
              <input
                ref={searchRef}
                type="text"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search..."
                className="w-full bg-transparent text-sm text-foreground placeholder:text-muted-foreground focus:outline-none"
                onClick={(e) => e.stopPropagation()}
              />
            </div>
          )}

          <div className="max-h-48 overflow-y-auto">
            {filtered.length === 0 ? (
              <div className="px-4 py-3 text-center text-sm text-muted-foreground">
                No results found
              </div>
            ) : (
              filtered.map((option, i) => {
                const active = optionMatches(option, selectedValue);
                const optObj =
                  typeof option !== 'string'
                    ? (option as Record<string, unknown>)
                    : null;

                return (
                  <div
                    key={i}
                    className={`flex cursor-pointer items-center justify-between hover:bg-accent ${active ? 'bg-accent' : ''}`}
                  >
                    <span
                      onClick={() => {
                        onSelect(option);
                        setOpen(false);
                        setQuery('');
                      }}
                      className={`flex-1 truncate px-4 py-2.5 text-foreground ${contentSize}`}
                    >
                      {getOptionText(option)}
                    </span>

                    {showEdit &&
                      onEdit &&
                      optObj &&
                      optObj.type !== 'public' && (
                        <button
                          type="button"
                          onClick={() => {
                            onEdit({
                              id: optObj.id as string,
                              name: optObj.name as string,
                              type: optObj.type as string,
                            });
                            setOpen(false);
                            setQuery('');
                          }}
                          className="mr-1 rounded p-1 hover:bg-accent"
                        >
                          <Pencil className="h-3.5 w-3.5 text-muted-foreground" />
                        </button>
                      )}

                    {showDelete && onDelete && (
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          onDelete(
                            typeof option === 'string'
                              ? option
                              : ((optObj?.id as string) ?? ''),
                          );
                        }}
                        className={`mr-1 rounded p-1 hover:bg-accent ${
                          typeof showDelete === 'function' && !showDelete(option)
                            ? 'hidden'
                            : ''
                        } ${optObj?.type === 'public' ? 'pointer-events-none opacity-30' : ''}`}
                      >
                        <Trash2 className="h-3.5 w-3.5 text-muted-foreground" />
                      </button>
                    )}
                  </div>
                );
              })
            )}
          </div>
        </div>
      )}
    </div>
  );
}

export default Dropdown;
