import { useCallback, useEffect, useRef, useState } from 'react';
import { useSelector } from 'react-redux';

import adminService from '../api/services/adminService';
import teamsService from '../api/services/teamsService';
import { Modal } from '../components/ui/modal';
import { selectToken } from '../preferences/preferenceSlice';
import { LoadError, Loading, fmtDate } from './AdminUI';
import QuotaEditor, { UsageBar } from './QuotaEditor';
import {
  sourceLabel,
  type BucketStatus,
  type Budget,
  type QuotaPolicy,
} from './quotaUtils';

/** A user's effective limits and usage, with the editor for their override. */
export default function UserQuotaModal({
  userId,
  onClose,
}: {
  userId: string | null;
  onClose: () => void;
}) {
  const token = useSelector(selectToken);
  const [data, setData] = useState<any | null>(null);
  const [teamNames, setTeamNames] = useState<Record<string, string>>({});

  // Bumped per request so a slow response for a previous user is discarded
  // instead of showing (and letting the editor save) that user's policy.
  const requestRef = useRef(0);

  const load = useCallback(async () => {
    const request = ++requestRef.current;
    setData(null);
    if (!userId) return;
    try {
      const [res, teamsJson] = await Promise.all([
        adminService.getUserQuota(userId, token),
        teamsService.listAll(token).catch(() => ({})),
      ]);
      const json = await res.json().catch(() => ({ success: false }));
      if (request !== requestRef.current) return;
      setData(json);
      setTeamNames(
        Object.fromEntries(
          (teamsJson?.teams ?? []).map((team: any) => [
            String(team.id),
            team.name,
          ]),
        ),
      );
    } catch {
      if (request === requestRef.current) setData({ success: false });
    }
  }, [userId, token]);

  useEffect(() => {
    load();
  }, [load]);

  const overall: BucketStatus | undefined = (data?.effective ?? []).find(
    (status: BucketStatus) => status.bucket === 'all',
  );
  const override: QuotaPolicy | null =
    (data?.policies ?? []).find((p: QuotaPolicy) => p.bucket === 'all') ?? null;
  const caption = (budget: Budget) =>
    sourceLabel(
      budget,
      budget.source_id ? teamNames[budget.source_id] : undefined,
    );

  return (
    <Modal
      open={userId !== null}
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title={userId ? `Quota · ${userId}` : 'Quota'}
    >
      {data === null ? (
        <Loading />
      ) : !data.success ? (
        <LoadError message="Failed to load this user's quota." />
      ) : (
        <div className="space-y-5">
          {overall ? (
            <div className="space-y-3">
              <UsageBar
                label={`Tokens this ${data.period}`}
                kind="tokens"
                budget={overall.tokens}
                caption={caption(overall.tokens)}
              />
              <UsageBar
                label={`Cost this ${data.period}`}
                kind="cost"
                budget={overall.cost}
                caption={caption(overall.cost)}
              />
              <p className="text-muted-foreground text-xs">
                Resets {fmtDate(overall.resets_at)}
              </p>
            </div>
          ) : null}
          <div className="border-border border-t pt-4">
            <p className="text-foreground mb-2 text-sm font-bold">
              User override
            </p>
            <QuotaEditor
              scope="user"
              subjectId={userId}
              policy={override}
              inheritHint="Overrides team allowances and the instance default for this user. Leave a budget as “Not set here” to keep what the user inherits."
              onSaved={load}
            />
          </div>
        </div>
      )}
    </Modal>
  );
}
