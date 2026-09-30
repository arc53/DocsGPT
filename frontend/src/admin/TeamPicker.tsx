import { ChevronsUpDown } from 'lucide-react';
import { useEffect, useState } from 'react';

import teamsService from '../api/services/teamsService';
import { Button } from '../components/ui/button';
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from '../components/ui/command';
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '../components/ui/popover';
import { useDebouncedValue } from '../hooks';

/** Matches per search; the admin types to narrow a long team list. */
const TEAM_SEARCH_LIMIT = 20;

export type PickedTeam = { id: string; name: string };

type TeamPickerProps = {
  value: PickedTeam | null;
  onChange: (team: PickedTeam) => void;
  token: string | null;
};

/**
 * A searchable picker of teams that have no allowance yet (Popover +
 * Command, like the timezone picker). The server does the search, so it
 * works however many teams the instance has.
 */
export default function TeamPicker({
  value,
  onChange,
  token,
}: TeamPickerProps) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const debounced = useDebouncedValue(query.trim(), 250);
  const [teams, setTeams] = useState<PickedTeam[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setLoading(true);
    teamsService
      .searchAdminTeams(token, {
        q: debounced,
        withoutQuota: true,
        limit: TEAM_SEARCH_LIMIT,
      })
      .then((res) => {
        if (cancelled) return;
        setTeams(
          (res?.teams ?? []).map((team: { id: string; name: string }) => ({
            id: String(team.id),
            name: team.name,
          })),
        );
      })
      .catch(() => {
        if (!cancelled) setTeams([]);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [open, debounced, token]);

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          type="button"
          variant="combobox"
          size="field"
          role="combobox"
          aria-expanded={open}
          aria-label="Team"
          data-placeholder={value ? undefined : ''}
          className="w-52 justify-between"
        >
          <span className="truncate">
            {value ? value.name : 'Choose a team'}
          </span>
          <ChevronsUpDown className="shrink-0 opacity-50" />
        </Button>
      </PopoverTrigger>
      <PopoverContent
        className="w-[min(18rem,calc(100vw-2rem))] p-0"
        align="end"
      >
        <Command shouldFilter={false}>
          <CommandInput
            placeholder="Search teams…"
            value={query}
            onValueChange={setQuery}
          />
          <CommandList>
            <CommandEmpty>
              {loading
                ? 'Searching…'
                : debounced
                  ? 'No team without an allowance matches.'
                  : 'Every team has an allowance.'}
            </CommandEmpty>
            <CommandGroup>
              {teams.map((team) => (
                <CommandItem
                  key={team.id}
                  value={team.id}
                  checked={value?.id === team.id}
                  onSelect={() => {
                    onChange(team);
                    setOpen(false);
                    setQuery('');
                  }}
                >
                  <span className="truncate">{team.name}</span>
                </CommandItem>
              ))}
            </CommandGroup>
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}
