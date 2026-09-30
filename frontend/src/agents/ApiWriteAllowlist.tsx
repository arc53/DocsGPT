import { ChevronRight } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';

import userService from '../api/services/userService';
import { Button } from '../components/ui/button';
import { Card } from '../components/ui/card';
import { SectionHeader } from '../components/ui/section-header';
import { actionTitle } from '../connectors/i18n';
import PermissionGroup, {
  ALLOW_OR_OFF,
  PermissionRow,
  PermissionSelect,
} from '../connectors/PermissionGroup';
import type { ActionPermission } from '../connectors/types';
import { cn } from '../lib/utils';
import { showActionToast } from '../notifications/actionToastSlice';
import { selectToken } from '../preferences/preferenceSlice';
import { formatCount, intlLocale } from '../utils/dateTimeUtils';
import type { Agent, AgentConfig } from './types';
import useAgentResourceStates from './useAgentResourceStates';

type WriteAction = {
  entry: string;
  action: string;
  description: string;
};

/** One running tool and its writes on the owner's credentials. */
type ToolWrites = {
  id: string;
  name: string;
  actions: WriteAction[];
};

type UserTool = {
  id: string;
  actions?: { name: string; description?: string }[];
};

const K = 'modals.agentDetails.apiWrites';

/**
 * One tool's writes on the connectors' skeleton: Allow / Off for all of
 * them at once, or Customize, which lists each write with its own choice.
 */
function ToolAllowlist({
  tool,
  allowed,
  onChange,
  disabled = false,
}: {
  tool: ToolWrites;
  allowed: Set<string>;
  onChange: (entries: string[], allow: boolean) => void;
  /** While a save is in flight, so saves never overlap. */
  disabled?: boolean;
}) {
  const { t } = useTranslation();
  const allowedCount = tool.actions.filter((item) =>
    allowed.has(item.entry),
  ).length;
  const plain = { interpolation: { escapeValue: false } };
  const permissionOf = (item: WriteAction): ActionPermission =>
    allowed.has(item.entry) ? 'always' : 'off';
  return (
    <PermissionGroup
      data-tool={tool.id}
      title={`${tool.name} · ${t(`${K}.summaryCount`, {
        allowed: formatCount(allowedCount),
        formatted: formatCount(tool.actions.length),
      })}`}
      values={tool.actions.map(permissionOf)}
      options={ALLOW_OR_OFF}
      disabled={disabled}
      groupLabel={t(`${K}.toolLabel`, { ...plain, tool: tool.name })}
      onChoose={(permission) =>
        onChange(
          tool.actions.map((item) => item.entry),
          permission === 'always',
        )
      }
    >
      {(customizing) =>
        customizing && (
          <ul className="flex flex-col gap-3">
            {tool.actions.map((item) => {
              const title = actionTitle(item.action);
              return (
                <PermissionRow
                  key={item.entry}
                  title={title}
                  name={item.action}
                  description={item.description || undefined}
                  control={
                    <PermissionSelect
                      value={permissionOf(item)}
                      options={ALLOW_OR_OFF}
                      disabled={disabled}
                      label={t('settings.connectors.permission.label', {
                        ...plain,
                        action: title,
                      })}
                      onChange={(permission) =>
                        onChange([item.entry], permission === 'always')
                      }
                    />
                  }
                />
              );
            })}
          </ul>
        )
      }
    </PermissionGroup>
  );
}

/**
 * The write actions on the owner's accounts and stored credentials that
 * anyone reaching this agent through its API key, widget or its public link
 * may run. Nobody there can approve an action for the owner, so
 * the server refuses every other such write. The server names these writes
 * per running tool in the agent's `resource_states` (`owner_credential_writes`),
 * which covers tools an editor sponsored and a workflow agent's node tools
 * too; the owner's own tool list only adds action descriptions.
 *
 * The section starts folded to a one-line summary (which tools can make
 * changes, and how many of all the writes are allowed). Open, each tool has
 * one Allow / Off / Customize choice, the connectors' permission skeleton,
 * with its writes one by one under Customize. Entries are `tool_id:action`.
 *
 * A change saves at once, on top of the agent's last saved config
 * (`getSavedConfig`), so edits still pending in the form are not saved with
 * it. `onConfigChange` receives the config as saved.
 */
export default function ApiWriteAllowlist({
  agent,
  onConfigChange,
  getSavedConfig,
  defaultOpen = false,
}: {
  agent: Agent;
  onConfigChange?: (config: AgentConfig) => void;
  getSavedConfig?: () => AgentConfig | undefined;
  /** Start open (Access details opened to allow changes). */
  defaultOpen?: boolean;
}) {
  const { t, i18n } = useTranslation();
  const dispatch = useDispatch();
  const token = useSelector(selectToken);
  const [open, setOpen] = useState(defaultOpen);
  // One save at a time: overlapping saves can land out of order, and a
  // failed one would put back a list that drops the later choice.
  const [saving, setSaving] = useState(false);

  const [descriptions, setDescriptions] = useState<Record<string, string>>({});
  const [allowed, setAllowed] = useState<string[]>(
    agent.config?.api_write_allowlist ?? [],
  );
  const loaded = useAgentResourceStates(agent.id, (agent.tools ?? []).join());

  useEffect(() => {
    setAllowed(agent.config?.api_write_allowlist ?? []);
  }, [agent.config?.api_write_allowlist]);

  // Descriptions of the actions of tools the owner can open themselves.
  useEffect(() => {
    let cancelled = false;
    userService
      .getUserTools(token)
      .then((response: Response) => response.json())
      .then((data: { tools?: UserTool[] }) => {
        if (cancelled) return;
        const found: Record<string, string> = {};
        for (const tool of data.tools ?? [])
          for (const action of tool.actions ?? [])
            if (action.description)
              found[`${tool.id}:${action.name}`] = action.description;
        setDescriptions(found);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [token]);

  const tools: ToolWrites[] = (loaded?.items ?? [])
    .filter(
      (item) =>
        item.type === 'tool' &&
        item.state === 'active' &&
        (item.owner_credential_writes ?? []).length > 0,
    )
    .map((item) => ({
      id: item.id,
      name: item.name || t('agents.form.sponsors.unknownItem'),
      actions: (item.owner_credential_writes ?? []).map((name) => ({
        entry: `${item.id}:${name}`,
        action: name,
        description: descriptions[`${item.id}:${name}`] ?? '',
      })),
    }));

  if (tools.length === 0) return null;

  const allowedSet = new Set(allowed);
  const total = tools.reduce((sum, tool) => sum + tool.actions.length, 0);
  const allowedCount = tools.reduce(
    (sum, tool) =>
      sum + tool.actions.filter((item) => allowedSet.has(item.entry)).length,
    0,
  );
  const changing = tools
    .filter((tool) => tool.actions.some((item) => allowedSet.has(item.entry)))
    .map((tool) => tool.name);
  const summary =
    changing.length === 0
      ? t(`${K}.summaryNone`)
      : [
          t(`${K}.summaryTools`, {
            count: changing.length,
            tools: new Intl.ListFormat(intlLocale(i18n.language), {
              type: 'conjunction',
            }).format(changing),
            interpolation: { escapeValue: false },
          }),
          t(`${K}.summaryCount`, {
            allowed: formatCount(allowedCount),
            formatted: formatCount(total),
          }),
        ].join(' · ');

  /** Allow or refuse these entries, and save the list. */
  const change = async (entries: string[], allow: boolean) => {
    if (saving) return;
    setSaving(true);
    const previous = allowed;
    const next = allow
      ? [...allowed, ...entries.filter((entry) => !allowed.includes(entry))]
      : allowed.filter((entry) => !entries.includes(entry));
    setAllowed(next);
    const config: AgentConfig = {
      ...((getSavedConfig ? getSavedConfig() : agent.config) ?? {}),
      api_write_allowlist: next,
    };
    const form = new FormData();
    form.append('config', JSON.stringify(config));
    try {
      const response = await userService.updateAgent(
        agent.id ?? '',
        form,
        token,
      );
      if (!response.ok) throw new Error('save failed');
      onConfigChange?.(config);
    } catch {
      setAllowed(previous);
      dispatch(
        showActionToast({
          variant: 'destructive',
          message: t(`${K}.saveFailed`),
        }),
      );
    } finally {
      setSaving(false);
    }
  };

  return (
    <section className="flex flex-col gap-3">
      <SectionHeader
        as="h3"
        size="xs"
        title={t(`${K}.title`)}
        description={<span data-testid="api-writes-summary">{summary}</span>}
      />
      {/* A collapsible group in a modal: the inline disclosure toggle. */}
      <Button
        type="button"
        variant="link"
        size="sm"
        aria-expanded={open}
        className="-ml-3 w-fit justify-start"
        onClick={() => setOpen(!open)}
      >
        <ChevronRight
          aria-hidden="true"
          className={cn(
            'transition-transform duration-200',
            open && 'rotate-90',
          )}
        />
        {t(`${K}.choose`)}
      </Button>
      {open && (
        <>
          <p className="text-muted-foreground text-xs">
            {t(`${K}.description`)}
          </p>
          <Card variant="outline" padding="sm" className="gap-4">
            {tools.map((tool) => (
              <ToolAllowlist
                key={tool.id}
                tool={tool}
                allowed={allowedSet}
                onChange={change}
                disabled={saving}
              />
            ))}
          </Card>
        </>
      )}
    </section>
  );
}
