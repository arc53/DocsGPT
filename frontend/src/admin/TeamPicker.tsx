import { useEffect, useState } from 'react';

import teamsService from '../api/services/teamsService';
import { Combobox } from '../components/ui/combobox';
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
 * A searchable picker of teams that have no allowance yet (a Combobox,
 * like the timezone picker). The server does the search, so it
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
    <Combobox
      options={teams.map((team) => ({ value: team.id, label: team.name }))}
      value={value?.id ?? null}
      valueOption={value ? { value: value.id, label: value.name } : undefined}
      onValueChange={(id, option) => onChange({ id, name: option.label })}
      open={open}
      onOpenChange={setOpen}
      shouldFilter={false}
      search={query}
      onSearchChange={setQuery}
      placeholder="Choose a team"
      searchPlaceholder="Search teams…"
      emptyText={
        loading
          ? 'Searching…'
          : debounced
            ? 'No team without an allowance matches.'
            : 'Every team has an allowance.'
      }
      align="end"
      aria-label="Team"
      className="w-52"
    />
  );
}
