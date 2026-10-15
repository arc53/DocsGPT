import type { CalendarEvent } from './types';

/** The calendar's agent filter choice beyond "all": an agent, or chat tasks. */
export type AgentChoice = { id: string; name: string } | 'chat' | null;

/**
 * The agent filter's options: the agents with a slot in the window, by
 * name, and whether chat tasks have one. The chosen option stays listed in
 * a window it has no slot in, or the filter would read blank while it
 * still hides every other slot.
 */
export function agentOptions(
  events: CalendarEvent[],
  chosen: AgentChoice,
): { list: [string, string][]; chat: boolean } {
  const byId = new Map<string, string>();
  let chat = chosen === 'chat';
  for (const event of events) {
    if (event.kind === 'sync') continue;
    if (event.agent_id) byId.set(event.agent_id, event.agent_name ?? '');
    else chat = true;
  }
  if (chosen && chosen !== 'chat' && !byId.has(chosen.id)) {
    byId.set(chosen.id, chosen.name);
  }
  return {
    list: [...byId.entries()].sort((a, b) => a[1].localeCompare(b[1])),
    chat,
  };
}
