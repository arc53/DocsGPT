import type { TFunction } from 'i18next';

import ToolIcon from '../components/ToolIcon';
import type { MultiSelectPopoverItem } from '../components/MultiSelectPopover';
import { intlLocale } from '../utils/dateTimeUtils';
import { getToolDisplayName } from '../utils/toolUtils';
import type { ToolSummary } from './types';

/** A resource a save would have run with the caller's access. */
export type SponsorResource = {
  /** `"<type>:<id>"`, the value `confirm_sponsor` takes. */
  key: string;
  type: 'tool' | 'source' | 'prompt';
  id: string;
  name: string | null;
};

/** Who reaches the agent's resources (409 `audience`). */
export type SponsorAudience = {
  /** Names of the teams the agent is shared with. */
  teams: string[];
  /** The agent has an API key (the API and the website widget). */
  api_key: boolean;
  public_link: boolean;
  webhook: boolean;
};

/** An audience with nobody in it, for a read that sent none. */
export const NO_AUDIENCE: SponsorAudience = {
  teams: [],
  api_key: false,
  public_link: false,
  webhook: false,
};

/** What a save asks the caller to agree to before it goes ahead. */
export type SponsorConfirmation = {
  resources: SponsorResource[];
  audience: SponsorAudience;
};

export type SponsorRefusal =
  | { kind: 'confirm'; confirmation: SponsorConfirmation }
  | { kind: 'notAllowed'; resources: SponsorResource[] }
  /** The save confirmed something it no longer needs (the agent changed). */
  | { kind: 'unexpected' };

/**
 * The sponsor refusal a failed agent or workflow save carries, if any.
 *
 * A save that would run a resource the owner can't use with the caller's
 * access answers 409 `sponsor_confirmation_required` until it is retried
 * with `confirm_sponsor`; one the caller may not sponsor at all answers 403
 * `sponsor_not_allowed`; one whose confirmation names something it no
 * longer needs answers 400 `sponsor_confirmation_unexpected`. Reads a
 * clone, so the caller can still read the body for any other error.
 */
export async function readSponsorRefusal(
  response: Response,
): Promise<SponsorRefusal | null> {
  if (![400, 403, 409].includes(response.status)) return null;
  if (typeof response.clone !== 'function') return null;
  let body: {
    code?: string;
    resources?: SponsorResource[];
    audience?: SponsorAudience;
  };
  try {
    body = await response.clone().json();
  } catch {
    return null;
  }
  if (body?.code === 'sponsor_confirmation_required' && body.audience) {
    return {
      kind: 'confirm',
      confirmation: {
        resources: body.resources ?? [],
        audience: body.audience,
      },
    };
  }
  if (body?.code === 'sponsor_not_allowed') {
    return { kind: 'notAllowed', resources: body.resources ?? [] };
  }
  if (body?.code === 'sponsor_confirmation_unexpected') {
    return { kind: 'unexpected' };
  }
  return null;
}

/**
 * Send an agent or workflow save, asking the caller whenever the server
 * wants their confirmation to sponsor something, and resending with it.
 *
 * Args:
 *   send: Sends the save with these `confirm_sponsor` keys.
 *   ask: Shows the confirmation; resolves to the agreed keys, or null.
 *   confirmed: Keys already agreed (items the caller chose to take over).
 *
 * Returns:
 *   The last response, or null when the caller declined.
 */
export async function saveWithSponsorConsent(
  send: (confirm: string[]) => Promise<Response>,
  ask: (confirmation: SponsorConfirmation) => Promise<string[] | null>,
  confirmed: string[] = [],
): Promise<Response | null> {
  let keys = Array.from(new Set(confirmed));
  let response = await send(keys);
  // The agent can change between rounds; three asks is plenty.
  for (let round = 0; round < 3; round += 1) {
    const refusal = await readSponsorRefusal(response);
    if (refusal?.kind !== 'confirm') return response;
    const agreed = await ask(refusal.confirmation);
    if (!agreed) return null;
    keys = Array.from(new Set([...keys, ...agreed]));
    response = await send(keys);
  }
  return response;
}

/**
 * A MultiSelect's options plus one for each selected id the caller can't
 * list (the owner's private tool or source on a workflow node), so it can
 * be removed. Selecting only removes it; nothing opens.
 *
 * Args:
 *   options: The caller's own options.
 *   attached: Known names of referenced resources, by id.
 *   selected: The ids selected now.
 *   format: Turns a name into the option's label.
 */
export function withAttachedOptions(
  options: { value: string; label: string }[],
  attached: { id: string; label: string }[],
  selected: string[],
  format: (name: string) => string,
): { value: string; label: string }[] {
  const listed = new Set(options.map((option) => option.value));
  const names = new Map(attached.map((item) => [item.id, item.label]));
  const extra = selected
    .filter((id, index) => !listed.has(id) && selected.indexOf(id) === index)
    .map((id) => ({ value: id, label: format(names.get(id) || id) }));
  return extra.length ? [...options, ...extra] : options;
}

/** The error for a save that attached resources the caller may not sponsor. */
export function sponsorNotAllowedMessage(
  t: TFunction,
  language: string,
  resources: SponsorResource[],
): string {
  const names = new Intl.ListFormat(intlLocale(language), {
    type: 'conjunction',
  }).format(
    resources.map((item) => item.name || t('agents.form.sponsors.unknownItem')),
  );
  return t('agents.form.sponsors.notAllowed', {
    names,
    interpolation: { escapeValue: false },
  });
}

/**
 * The tool picker's rows plus one per attached tool the caller can't list.
 *
 * An editor of someone else's agent doesn't see the owner's private tools in
 * their own list, so without a row of its own such a tool reads as selected
 * with nothing to switch it off. The row only removes it (and puts it back
 * before saving); it offers nothing to open or configure.
 */
export function withAttachedToolRows(
  items: MultiSelectPopoverItem[],
  attached: ToolSummary[],
  labels: { group: string; description: string },
): MultiSelectPopoverItem[] {
  const seen = new Set(items.map((item) => item.id));
  const extra: MultiSelectPopoverItem[] = [];
  for (const tool of attached) {
    if (!tool?.id || seen.has(tool.id)) continue;
    seen.add(tool.id);
    extra.push({
      id: tool.id,
      label: getToolDisplayName(tool),
      icon: <ToolIcon name={tool.name} className="size-5" />,
      group: labels.group,
      description: labels.description,
    });
  }
  return extra.length ? [...items, ...extra] : items;
}

/**
 * Ask the caller to run one stopped item with their access, naming who
 * reaches it through the agent (the read's `sponsor_audience`).
 *
 * Args:
 *   ask: Shows the confirmation; resolves to the agreed keys, or null.
 *   item: The stopped item.
 *   name: Its display name.
 *   audience: Who reaches the agent's resources.
 *
 * Returns:
 *   Whether they agreed; the next save then sends its key.
 */
export async function confirmTakeOver(
  ask: (confirmation: SponsorConfirmation) => Promise<string[] | null>,
  item: Pick<SponsorResource, 'key' | 'type' | 'id'>,
  name: string,
  audience: SponsorAudience | undefined,
): Promise<boolean> {
  const agreed = await ask({
    resources: [{ key: item.key, type: item.type, id: item.id, name }],
    audience: audience ?? NO_AUDIENCE,
  });
  return Boolean(agreed?.includes(item.key));
}
