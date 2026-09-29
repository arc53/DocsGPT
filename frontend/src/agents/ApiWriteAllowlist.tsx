import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';

import userService from '../api/services/userService';
import { Card } from '../components/ui/card';
import { Checkbox } from '../components/ui/checkbox';
import { Label } from '../components/ui/label';
import { SectionHeader } from '../components/ui/section-header';
import { showActionToast } from '../notifications/actionToastSlice';
import { selectToken } from '../preferences/preferenceSlice';
import type { Agent, AgentConfig } from './types';
import useAgentResourceStates from './useAgentResourceStates';
import { actionTitle } from '../connectors/i18n';

type WriteAction = {
  entry: string;
  tool: string;
  action: string;
  description: string;
};

type UserTool = {
  id: string;
  actions?: { name: string; description?: string }[];
};

/**
 * The write actions on the owner's accounts and stored credentials that
 * anyone reaching this agent through its API key, widget or its public link
 * may run. Nobody there can approve an action for the owner, so
 * the server refuses every other such write. The server names these writes
 * per running tool in the agent's `resource_states` (`owner_credential_writes`),
 * which covers tools an editor sponsored and a workflow agent's node tools
 * too; the owner's own tool list only adds action descriptions.
 *
 * A toggle saves at once, on top of the agent's last saved config
 * (`getSavedConfig`), so edits still pending in the form are not saved with
 * it. `onConfigChange` receives the config as saved.
 */
export default function ApiWriteAllowlist({
  agent,
  onConfigChange,
  getSavedConfig,
}: {
  agent: Agent;
  onConfigChange?: (config: AgentConfig) => void;
  getSavedConfig?: () => AgentConfig | undefined;
}) {
  const { t } = useTranslation();
  const dispatch = useDispatch();
  const token = useSelector(selectToken);
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

  const actions: WriteAction[] = (loaded?.items ?? [])
    .filter((item) => item.type === 'tool' && item.state === 'active')
    .flatMap((item) =>
      (item.owner_credential_writes ?? []).map((name) => ({
        entry: `${item.id}:${name}`,
        tool: item.name || t('agents.form.sponsors.unknownItem'),
        action: name,
        description: descriptions[`${item.id}:${name}`] ?? '',
      })),
    );

  if (actions.length === 0) return null;

  const toggle = async (entry: string, checked: boolean) => {
    const previous = allowed;
    const next = checked
      ? [...allowed, entry]
      : allowed.filter((item) => item !== entry);
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
          message: t('modals.agentDetails.apiWrites.saveFailed'),
        }),
      );
    }
  };

  return (
    <section className="flex flex-col gap-3">
      <SectionHeader
        as="h4"
        size="xs"
        title={t('modals.agentDetails.apiWrites.title')}
        description={t('modals.agentDetails.apiWrites.description')}
      />
      <Card padding="sm" className="gap-3">
        {actions.map((item) => {
          const id = `api-write-${item.entry}`;
          return (
            <div key={item.entry} className="flex items-start gap-2">
              <Checkbox
                id={id}
                checked={allowed.includes(item.entry)}
                onCheckedChange={(checked) =>
                  toggle(item.entry, checked === true)
                }
              />
              <div className="flex min-w-0 flex-col gap-0.5">
                <Label htmlFor={id} className="font-normal">
                  {t('modals.agentDetails.apiWrites.item', {
                    tool: item.tool,
                    action: actionTitle(item.action),
                    interpolation: { escapeValue: false },
                  })}
                </Label>
                {item.description && (
                  <span className="text-muted-foreground text-xs">
                    {item.description}
                  </span>
                )}
              </div>
            </div>
          );
        })}
      </Card>
    </section>
  );
}
