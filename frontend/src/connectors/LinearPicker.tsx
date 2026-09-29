import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import { useTranslation } from 'react-i18next';

import connectorsService from '../api/services/connectorsService';
import SearchInput from '../components/SearchInput';
import { Button } from '../components/ui/button';
import { Card } from '../components/ui/card';
import { Checkbox } from '../components/ui/checkbox';
import { EmptyState } from '../components/ui/empty-state';
import { ListRow, ListRows } from '../components/ui/list-row';
import { LoadingState } from '../components/ui/loading-state';
import { SectionHeader } from '../components/ui/section-header';
import { SettingRow, SettingRows } from '../components/ui/setting-row';
import { Switch } from '../components/ui/switch';
import type { LinearProject, LinearTeam } from './types';

/** What a Linear source syncs: the picked teams' and projects' issues. */
export type LinearSelection = {
  teams: LinearTeam[];
  projects: Pick<LinearProject, 'id' | 'name'>[];
  includeComments: boolean;
  /** The picked projects' Linear documents. */
  includeDocuments: boolean;
};

export const EMPTY_LINEAR_SELECTION: LinearSelection = {
  teams: [],
  projects: [],
  includeComments: true,
  includeDocuments: false,
};

/** `Linear · Engineering, Launch`: a source's name from what it syncs. */
export const linearSourceName = (selection: LinearSelection) => {
  const names = [...selection.teams, ...selection.projects].map((p) => p.name);
  return names.length ? `Linear · ${names.join(', ')}` : '';
};

/** The wizard's choice as the setup endpoint takes it. */
export const linearSyncItems = (selection: LinearSelection) => ({
  teams: selection.teams,
  projects: selection.projects,
  include_comments: selection.includeComments,
  include_documents: selection.includeDocuments && !!selection.projects.length,
});

type LoadError = 'reconnect' | 'failed' | null;

// More rows than this and a search field helps.
const SEARCH_FROM = 8;

/**
 * Pick the Linear teams and projects whose issues a source syncs, and
 * whether it brings comments and the projects' documents. The lists come
 * from Linear's MCP server, read with the connection's sign-in.
 */
export default function LinearPicker({
  connectionId,
  token,
  value,
  onChange,
}: {
  connectionId: string;
  token: string | null;
  value: LinearSelection;
  onChange: (selection: LinearSelection) => void;
}) {
  const { t } = useTranslation();
  const [teams, setTeams] = useState<LinearTeam[]>([]);
  const [projects, setProjects] = useState<LinearProject[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<LoadError>(null);
  const [query, setQuery] = useState('');
  const requestRef = useRef(0);

  const load = useCallback(async () => {
    const request = ++requestRef.current;
    setLoading(true);
    setError(null);
    try {
      const data = await connectorsService.linearWorkspace(connectionId, token);
      if (request !== requestRef.current) return;
      if (!data?.success) {
        setError(data?.code === 'reconnect' ? 'reconnect' : 'failed');
        return;
      }
      setTeams(data.teams ?? []);
      setProjects(data.projects ?? []);
    } catch {
      if (request === requestRef.current) setError('failed');
    } finally {
      if (request === requestRef.current) setLoading(false);
    }
  }, [connectionId, token]);

  useEffect(() => {
    load();
  }, [load]);

  // A few hundred rows at most, so filtering on each render is cheap.
  const needle = query.trim().toLowerCase();
  const matches = (...texts: string[]) =>
    !needle || texts.some((text) => text.toLowerCase().includes(needle));
  const visibleTeams = teams.filter((team) => matches(team.name, team.key));
  const visibleProjects = projects.filter((project) => matches(project.name));

  const pickedTeams = new Set(value.teams.map((team) => team.id));
  const pickedProjects = new Set(value.projects.map((project) => project.id));

  const toggleTeam = (team: LinearTeam, on: boolean) =>
    onChange({
      ...value,
      teams: on
        ? [...value.teams, { id: team.id, key: team.key, name: team.name }]
        : value.teams.filter((picked) => picked.id !== team.id),
    });
  const toggleProject = (project: LinearProject, on: boolean) =>
    onChange({
      ...value,
      projects: on
        ? [...value.projects, { id: project.id, name: project.name }]
        : value.projects.filter((picked) => picked.id !== project.id),
    });

  if (loading && teams.length + projects.length === 0)
    return <LoadingState fill="block" />;
  if (error) {
    return (
      <EmptyState
        tone="destructive"
        size="sm"
        illustration="none"
        title={
          error === 'reconnect'
            ? t('settings.connectors.detail.expired')
            : t('settings.connectors.linear.loadFailed')
        }
        action={
          error === 'failed' ? (
            <Button variant="outline" size="sm" shape="pill" onClick={load}>
              {t('retry')}
            </Button>
          ) : undefined
        }
      />
    );
  }
  if (teams.length + projects.length === 0) {
    return (
      <EmptyState
        size="xs"
        illustration="none"
        title={t('settings.connectors.linear.empty')}
      />
    );
  }

  const row = (
    id: string,
    checked: boolean,
    title: string,
    description: string,
    onToggle: (on: boolean) => void,
  ) => (
    <ListRow
      key={id}
      interactive
      asChild
      leading={
        <Checkbox
          id={`linear-${id}`}
          checked={checked}
          onCheckedChange={(state) => onToggle(state === true)}
        />
      }
      title={title}
      description={description || undefined}
    >
      <label htmlFor={`linear-${id}`} />
    </ListRow>
  );

  const list = (children: ReactNode) => (
    <Card variant="subtle" padding="none" className="max-h-60 overflow-y-auto">
      <ListRows>{children}</ListRows>
    </Card>
  );

  return (
    <div className="flex flex-col gap-5">
      {teams.length + projects.length > SEARCH_FROM && (
        <SearchInput
          label={t('settings.connectors.linear.search')}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
      )}
      {visibleTeams.length + visibleProjects.length === 0 ? (
        <EmptyState
          size="xs"
          illustration="none"
          title={t('settings.connectors.linear.noMatches')}
        />
      ) : (
        <>
          {visibleTeams.length > 0 && (
            <section className="flex flex-col gap-3">
              <SectionHeader
                as="h3"
                size="xs"
                title={t('settings.connectors.linear.teams')}
                description={t('settings.connectors.linear.teamsHint')}
              />
              {list(
                visibleTeams.map((team) =>
                  row(
                    team.id,
                    pickedTeams.has(team.id),
                    team.name,
                    team.key,
                    (on) => toggleTeam(team, on),
                  ),
                ),
              )}
            </section>
          )}
          {visibleProjects.length > 0 && (
            <section className="flex flex-col gap-3">
              <SectionHeader
                as="h3"
                size="xs"
                title={t('settings.connectors.linear.projects')}
                description={t('settings.connectors.linear.projectsHint')}
              />
              {list(
                visibleProjects.map((project) =>
                  row(
                    project.id,
                    pickedProjects.has(project.id),
                    project.name,
                    [project.state, project.teams.join(', ')]
                      .filter(Boolean)
                      .join(' · '),
                    (on) => toggleProject(project, on),
                  ),
                ),
              )}
            </section>
          )}
        </>
      )}
      <SettingRows>
        <SettingRow
          label={t('settings.connectors.linear.includeComments')}
          description={t(
            'settings.connectors.linear.includeCommentsDescription',
          )}
          htmlFor="linear-include-comments"
          alignStart
        >
          <Switch
            id="linear-include-comments"
            checked={value.includeComments}
            onCheckedChange={(checked) =>
              onChange({ ...value, includeComments: checked === true })
            }
          />
        </SettingRow>
        <SettingRow
          label={t('settings.connectors.linear.includeDocuments')}
          description={t(
            'settings.connectors.linear.includeDocumentsDescription',
          )}
          htmlFor="linear-include-documents"
          alignStart
        >
          <Switch
            id="linear-include-documents"
            checked={value.includeDocuments && value.projects.length > 0}
            disabled={value.projects.length === 0}
            onCheckedChange={(checked) =>
              onChange({ ...value, includeDocuments: checked === true })
            }
          />
        </SettingRow>
      </SettingRows>
    </div>
  );
}
