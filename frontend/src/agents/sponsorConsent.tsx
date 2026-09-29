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

/** What a save asks the caller to agree to before it goes ahead. */
export type SponsorConfirmation = {
  resources: SponsorResource[];
  audience: SponsorAudience;
};

export type SponsorRefusal =
  | { kind: 'confirm'; confirmation: SponsorConfirmation }
  | { kind: 'notAllowed'; resources: SponsorResource[] };

/**
 * The sponsor refusal a failed agent or workflow save carries, if any.
 *
 * A save that would run a resource the owner can't use with the caller's
 * access answers 409 `sponsor_confirmation_required` until it is retried
 * with `confirm_sponsor`; one the caller may not sponsor at all answers 403
 * `sponsor_not_allowed`. Reads a clone, so the caller can still read the
 * body for any other error.
 */
export async function readSponsorRefusal(
  response: Response,
): Promise<SponsorRefusal | null> {
  if (response.status !== 409 && response.status !== 403) return null;
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
  return null;
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
