import { ChevronRight } from 'lucide-react';
import { useEffect, useId, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';

import userService from '../api/services/userService';
import { Button } from '../components/ui/button';
import { Card } from '../components/ui/card';
import { SectionHeader } from '../components/ui/section-header';
import { SettingRow, SettingRows } from '../components/ui/setting-row';
import { Switch } from '../components/ui/switch';
import { ToggleGroup, ToggleGroupItem } from '../components/ui/toggle-group';
import { actionTitle } from '../connectors/i18n';
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

/** The tool-wide choice: every write off, every write on, or mixed (''). */
type ToolChoice = 'off' | 'all' | '';

const K = 'modals.agentDetails.apiWrites';

/**
 * One tool's writes: an Off / All choice for all of them at once, and each
 * write on its own switch under Customize, like a connector's permissions.
 */
function ToolAllowlist({
  tool,
  allowed,
  onChange,
}: {
  tool: ToolWrites;
  allowed: Set<string>;
  onChange: (entries: string[], allow: boolean) => void;
}) {
  const { t } = useTranslation();
  const [unfolded, setUnfolded] = useState(false);
  // Names the tool for its Customize link, which reads the same in each.
  const titleId = useId();
  const allowedCount = tool.actions.filter((item) =>
    allowed.has(item.entry),
  ).length;
  const choice: ToolChoice =
    allowedCount === 0
      ? 'off'
      : allowedCount === tool.actions.length
        ? 'all'
        : '';
  const plain = { interpolation: { escapeValue: false } };
  return (
    <div data-tool={tool.id} className="flex flex-col gap-2">
      <div className="flex items-start justify-between gap-3">
        <SectionHeader
          as="h4"
          size="xs"
          className="min-w-0 flex-1"
          title={<span id={titleId}>{tool.name}</span>}
          description={t(`${K}.toolCount`, {
            allowed: formatCount(allowedCount),
            formatted: formatCount(tool.actions.length),
          })}
        />
        <div className="bg-muted shrink-0 rounded-full p-1">
          <ToggleGroup
            type="single"
            size="xs"
            value={choice}
            aria-label={t(`${K}.toolLabel`, { ...plain, tool: tool.name })}
            onValueChange={(value) =>
              value &&
              onChange(
                tool.actions.map((item) => item.entry),
                value === 'all',
              )
            }
          >
            {(['off', 'all'] as const).map((value) => (
              <ToggleGroupItem key={value} value={value} data-choice={value}>
                {t(`${K}.choice.${value}`)}
              </ToggleGroupItem>
            ))}
          </ToggleGroup>
        </div>
      </div>
      <Button
        type="button"
        variant="link"
        size="inline"
        className="self-start"
        aria-expanded={unfolded}
        aria-describedby={titleId}
        onClick={() => setUnfolded(!unfolded)}
      >
        {unfolded
          ? t(`${K}.fold`)
          : t(`${K}.customize`, {
              count: tool.actions.length,
              formatted: formatCount(tool.actions.length),
            })}
      </Button>
      {unfolded && (
        <SettingRows>
          {tool.actions.map((item) => {
            const id = `api-write-${item.entry}`;
            return (
              <SettingRow
                key={item.entry}
                htmlFor={id}
                alignStart
                label={
                  <span title={item.action}>{actionTitle(item.action)}</span>
                }
                description={item.description || undefined}
              >
                <Switch
                  id={id}
                  checked={allowed.has(item.entry)}
                  onCheckedChange={(checked) => onChange([item.entry], checked)}
                />
              </SettingRow>
            );
          })}
        </SettingRows>
      )}
    </div>
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
 * one Off / All choice with its writes one by one under Customize. Entries
 * are `tool_id:action`.
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
    }
  };

  return (
    <section className="flex flex-col gap-3">
      {/* A collapsible group in a modal: the inline disclosure toggle. */}
      <div className="flex flex-col gap-0.5">
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
          {t(`${K}.title`)}
        </Button>
        <p
          data-testid="api-writes-summary"
          className="text-muted-foreground text-xs"
        >
          {summary}
        </p>
      </div>
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
              />
            ))}
          </Card>
        </>
      )}
    </section>
  );
}
