// Pure helpers behind the quota editor and usage bars.

export type BudgetMode = 'inherit' | 'limit' | 'unlimited';

export type QuotaPolicy = {
  scope: 'instance' | 'team' | 'user';
  subject_id: string | null;
  bucket: string;
  token_limit: number | null;
  token_unlimited: boolean;
  cost_limit_usd: number | null;
  cost_unlimited: boolean;
  enabled: boolean;
  note?: string | null;
  updated_by?: string | null;
  updated_at?: string | null;
};

export type Budget = {
  limit: number | null;
  used: number;
  source?: string | null;
  source_id?: string | null;
};

export type BucketStatus = {
  bucket: string;
  tokens: Budget;
  cost: Budget;
  resets_at: string;
};

export type QuotaForm = {
  tokenMode: BudgetMode;
  tokenLimit: string;
  costMode: BudgetMode;
  costLimit: string;
  note: string;
};

const mode = (limit: number | null, unlimited: boolean): BudgetMode => {
  if (unlimited) return 'unlimited';
  return limit === null || limit === undefined ? 'inherit' : 'limit';
};

export function policyToForm(policy?: QuotaPolicy | null): QuotaForm {
  return {
    tokenMode: policy
      ? mode(policy.token_limit, policy.token_unlimited)
      : 'inherit',
    tokenLimit: policy?.token_limit != null ? String(policy.token_limit) : '',
    costMode: policy
      ? mode(policy.cost_limit_usd, policy.cost_unlimited)
      : 'inherit',
    costLimit:
      policy?.cost_limit_usd != null ? String(policy.cost_limit_usd) : '',
    note: policy?.note ?? '',
  };
}

export type FormResult =
  { ok: true; policy: Record<string, unknown> } | { ok: false; error: string };

// An empty form (both budgets inherited) is not a policy: the caller deletes instead.
export function isEmptyForm(form: QuotaForm): boolean {
  return form.tokenMode === 'inherit' && form.costMode === 'inherit';
}

export function formToPolicy(form: QuotaForm): FormResult {
  const policy: Record<string, unknown> = {
    bucket: 'all',
    token_limit: null,
    token_unlimited: form.tokenMode === 'unlimited',
    cost_limit_usd: null,
    cost_unlimited: form.costMode === 'unlimited',
    note: form.note.trim() || null,
  };
  if (form.tokenMode === 'limit') {
    const raw = form.tokenLimit.trim();
    if (!/^\d+$/.test(raw))
      return { ok: false, error: 'Token limit must be a whole number.' };
    const tokens = Number(raw);
    if (!Number.isSafeInteger(tokens))
      return { ok: false, error: 'Token limit is too large.' };
    policy.token_limit = tokens;
  }
  if (form.costMode === 'limit') {
    const raw = form.costLimit.trim();
    const cost = Number(raw);
    if (raw === '' || !Number.isFinite(cost) || cost < 0)
      return { ok: false, error: 'Cost limit must be a number, 0 or more.' };
    policy.cost_limit_usd = cost;
  }
  return { ok: true, policy };
}

export function usagePercent(used: number, limit: number | null): number {
  if (limit === null || limit === undefined) return 0;
  if (limit <= 0) return 100;
  return Math.min(100, Math.max(0, (used / limit) * 100));
}

export function fmtUsd(value?: number | null): string {
  return new Intl.NumberFormat(undefined, {
    style: 'currency',
    currency: 'USD',
    maximumFractionDigits: value != null && value < 1 ? 4 : 2,
  }).format(value ?? 0);
}

export function describeBudget(
  limit: number | null,
  unlimited: boolean,
  kind: 'tokens' | 'cost',
): string {
  if (unlimited) return 'Unlimited';
  if (limit === null || limit === undefined) return '—';
  return kind === 'cost'
    ? fmtUsd(limit)
    : `${new Intl.NumberFormat().format(limit)} tokens`;
}

export function sourceLabel(budget: Budget, teamName?: string): string {
  if (!budget.source) return 'No limit set';
  if (budget.source === 'user') return 'User override';
  if (budget.source === 'team')
    return teamName ? `Team: ${teamName}` : 'Team allowance';
  if (budget.source === 'instance') return 'Instance default';
  return 'Plan default';
}
