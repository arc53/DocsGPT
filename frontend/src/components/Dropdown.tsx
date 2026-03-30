import { Check, ChevronDown, Pencil, Search, Trash2 } from 'lucide-react';
import React, { useEffect, useMemo, useRef, useState } from 'react';

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
  if (typeof selected === 'string' && typeof option === 'string')
    return selected === option;
  if (typeof selected === 'string') return getOptionText(option) === selected;
  if (typeof option === 'string') return getOptionText(selected) === option;
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
        className={`border-border bg-card text-foreground flex w-full cursor-pointer items-center justify-between border px-5 py-3 ${open ? radiusTop : radius}`}
      >
        <span
          className={`truncate ${contentSize} ${displayValue ? '' : 'text-muted-foreground'}`}
        >
          {displayValue ?? placeholder}
        </span>
        <ChevronDown
          className={`text-muted-foreground ml-2 h-4 w-4 shrink-0 transition-transform ${open ? 'rotate-180' : ''}`}
        />
      </button>

      {open && (
        <div
          className={`border-border bg-card absolute inset-x-0 z-20 -mt-px overflow-hidden border border-t-0 shadow-lg ${radiusBottom}`}
        >
          {searchable && (
            <div className="flex items-center px-3 py-2">
              <Search className="text-muted-foreground mr-2 h-4 w-4 shrink-0" />
              <input
                ref={searchRef}
                type="text"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search..."
                className="text-foreground placeholder:text-muted-foreground w-full bg-transparent text-sm focus:outline-none"
                onClick={(e) => e.stopPropagation()}
              />
            </div>
          )}

          <div className="scrollbar-thin border-border max-h-48 overflow-y-auto border-t">
            {filtered.length === 0 ? (
              <div className="text-muted-foreground px-4 py-3 text-center text-sm">
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
                    className={`hover:bg-accent flex cursor-pointer items-center justify-between ${active ? 'bg-accent font-medium' : ''}`}
                  >
                    <span
                      onClick={() => {
                        onSelect(option);
                        setOpen(false);
                        setQuery('');
                      }}
                      className={`text-foreground flex-1 truncate px-4 py-2.5 ${contentSize}`}
                    >
                      {getOptionText(option)}
                    </span>

                    {active && !showEdit && !showDelete && (
                      <Check className="text-primary mr-3 h-4 w-4 shrink-0" />
                    )}

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
                          className="hover:bg-accent mr-1 rounded p-1"
                        >
                          <Pencil className="text-muted-foreground h-3.5 w-3.5" />
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
                        className={`hover:bg-accent mr-1 rounded p-1 ${
                          typeof showDelete === 'function' &&
                          !showDelete(option)
                            ? 'hidden'
                            : ''
                        } ${optObj?.type === 'public' ? 'pointer-events-none opacity-30' : ''}`}
                      >
                        <Trash2 className="text-muted-foreground h-3.5 w-3.5" />
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
