import { useEffect, useState } from 'react';
import { useSelector } from 'react-redux';

import adminService, { type QuotaScope } from '../api/services/adminService';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Progress } from '../components/ui/progress';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '../components/ui/select';
import { selectToken } from '../preferences/preferenceSlice';
import { fmtNumber } from './AdminUI';
import {
  fmtUsd,
  formToPolicy,
  isEmptyForm,
  policyToForm,
  usagePercent,
  type Budget,
  type BudgetMode,
  type QuotaForm,
  type QuotaPolicy,
} from './quotaUtils';

const MODES: { value: BudgetMode; label: string }[] = [
  { value: 'inherit', label: 'Not set here' },
  { value: 'limit', label: 'Limit' },
  { value: 'unlimited', label: 'Unlimited' },
];

export function UsageBar({
  label,
  budget,
  kind,
  caption,
}: {
  label: string;
  budget: Budget;
  kind: 'tokens' | 'cost';
  caption?: string;
}) {
  const fmt = (n: number) => (kind === 'cost' ? fmtUsd(n) : fmtNumber(n));
  const percent = usagePercent(budget.used, budget.limit);
  const tone =
    percent >= 100 ? 'destructive' : percent >= 80 ? 'warning' : 'default';
  return (
    <div>
      <div className="flex items-baseline justify-between gap-3 text-sm">
        <span className="text-muted-foreground">{label}</span>
        <span className="tabular-nums">
          {fmt(budget.used)}
          {budget.limit === null ? ' · no limit' : ` of ${fmt(budget.limit)}`}
        </span>
      </div>
      {budget.limit !== null ? (
        <Progress
          className="mt-1"
          size="sm"
          variant={tone}
          value={percent}
          aria-label={label}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={Math.round(percent)}
        />
      ) : null}
      {caption ? (
        <p className="text-muted-foreground mt-1 text-xs">{caption}</p>
      ) : null}
    </div>
  );
}

function BudgetField({
  label,
  hint,
  mode,
  value,
  step,
  onMode,
  onValue,
}: {
  label: string;
  hint: string;
  mode: BudgetMode;
  value: string;
  step: string;
  onMode: (mode: BudgetMode) => void;
  onValue: (value: string) => void;
}) {
  return (
    <div>
      <p className="text-foreground text-sm font-medium">{label}</p>
      <div className="mt-1 flex items-center gap-2">
        <Select value={mode} onValueChange={(v) => onMode(v as BudgetMode)}>
          <SelectTrigger className="w-40" aria-label={`${label} mode`}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {MODES.map((m) => (
              <SelectItem key={m.value} value={m.value}>
                {m.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {mode === 'limit' ? (
          <Input
            type="number"
            min="0"
            step={step}
            inputMode="decimal"
            value={value}
            aria-label={label}
            placeholder={hint}
            onChange={(e) => onValue(e.target.value)}
            className="flex-1"
          />
        ) : null}
      </div>
    </div>
  );
}

/**
 * Edits the ``all``-bucket policy of one subject. Saving a form with neither
 * budget set removes the policy, since a policy without an opinion is not stored.
 */
export default function QuotaEditor({
  scope,
  subjectId,
  policy,
  inheritHint,
  onSaved,
}: {
  scope: QuotaScope;
  subjectId: string | null;
  policy: QuotaPolicy | null;
  inheritHint: string;
  onSaved: () => void;
}) {
  const token = useSelector(selectToken);
  const [form, setForm] = useState<QuotaForm>(() => policyToForm(policy));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setForm(policyToForm(policy));
    setError(null);
  }, [policy, scope, subjectId]);

  const patch = (fields: Partial<QuotaForm>) =>
    setForm((prev) => ({ ...prev, ...fields }));

  const submit = async (request: () => Promise<Response>) => {
    setBusy(true);
    setError(null);
    try {
      const res = await request();
      const json = await res.json().catch(() => ({}));
      if (res.ok && json.success !== false) onSaved();
      else setError(json.message || 'Could not save the quota.');
    } catch {
      setError('Could not save the quota.');
    } finally {
      setBusy(false);
    }
  };

  const remove = () =>
    submit(() => adminService.deleteQuota(scope, subjectId, 'all', token));

  const save = () => {
    if (isEmptyForm(form)) {
      if (policy) remove();
      return;
    }
    const result = formToPolicy(form, policy);
    if (!result.ok) {
      setError(result.error);
      return;
    }
    submit(() => adminService.setQuota(scope, subjectId, result.policy, token));
  };

  return (
    <div className="space-y-4">
      <p className="text-muted-foreground text-xs">{inheritHint}</p>
      {policy && !policy.enabled ? (
        <p className="text-warning text-xs">
          This policy is disabled and is not enforced. Saving keeps it disabled.
        </p>
      ) : null}
      <BudgetField
        label="Tokens"
        hint="e.g. 2000000"
        step="1"
        mode={form.tokenMode}
        value={form.tokenLimit}
        onMode={(tokenMode) => patch({ tokenMode })}
        onValue={(tokenLimit) => patch({ tokenLimit })}
      />
      <BudgetField
        label="Cost (USD)"
        hint="e.g. 25"
        step="0.01"
        mode={form.costMode}
        value={form.costLimit}
        onMode={(costMode) => patch({ costMode })}
        onValue={(costLimit) => patch({ costLimit })}
      />
      <div>
        <p className="text-foreground text-sm font-medium">Note</p>
        <Input
          value={form.note}
          maxLength={500}
          aria-label="Note"
          placeholder="Optional, visible to admins only"
          onChange={(e) => patch({ note: e.target.value })}
          className="mt-1"
        />
      </div>
      {error ? (
        <p role="alert" className="text-destructive text-sm">
          {error}
        </p>
      ) : null}
      <div className="flex justify-end gap-2">
        {policy ? (
          <Button
            type="button"
            variant="destructive-outline"
            size="sm"
            disabled={busy}
            onClick={remove}
          >
            Remove
          </Button>
        ) : null}
        <Button
          type="button"
          size="sm"
          disabled={busy || (isEmptyForm(form) && !policy)}
          onClick={save}
        >
          Save
        </Button>
      </div>
    </div>
  );
}
