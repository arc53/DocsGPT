import { envVar } from '@/env';
import type { TFunction } from 'i18next';
import { focusRing } from '@/lib/utils';
import { ExternalLink, Wallet } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';

import ApiWriteAllowlist, {
  type GetSavedConfig,
} from '../agents/ApiWriteAllowlist';
import {
  outsideAccessOn,
  outsidePauseReason,
  rememberOutsideAccess,
} from '../agents/OwnerInactiveNotice';
import { Agent, type AgentConfig } from '../agents/types';
import payerService from '../api/services/payerService';
import userService from '../api/services/userService';
import CopyButton from '../components/CopyButton';
import {
  connectionErrorCode,
  connectionErrorMessage,
} from '../connectors/connectionErrors';
import { Alert, AlertAction, AlertDescription } from '../components/ui/alert';
import { Button } from '../components/ui/button';
import { Modal } from '../components/ui/modal';
import { SectionHeader } from '../components/ui/section-header';
import { ActiveState } from '../models/misc';
import { showActionToast } from '../notifications/actionToastSlice';
import { paidByText } from '../payer/pauseReason';
import TakeOverModal from '../payer/TakeOverModal';
import type { OutsideAccess } from '../payer/types';
import { selectToken } from '../preferences/preferenceSlice';
import { isOwner } from '../utils/accessUtils';
import { readerIdFromToken } from '../utils/personLabel';
import ConfirmationModal from './ConfirmationModal';

const baseURL = envVar('VITE_BASE_URL');
// The public and webhook URLs are raw links in running text.
const linkFocus = `${focusRing} rounded-sm outline-none`;

/**
 * What to say about a refused call: the app's words for a refusal over a
 * team's account (naming the tools that keep the agent inside the team),
 * else the backend's `message`, else null.
 */
const errorMessage = async (
  response: Response,
  t: TFunction,
): Promise<string | null> => {
  try {
    const body = await response.json();
    if (connectionErrorCode(body))
      return connectionErrorMessage(t, body, { status: response.status });
    return typeof body?.message === 'string' && body.message.trim()
      ? body.message
      : null;
  } catch {
    return null;
  }
};

/**
 * Who pays for an agent's key, public link and webhook ("Paid by Dana"), or
 * why they are paused, with Take over for a reader the server lets take it
 * over. Shown only while something is on.
 *
 * Args:
 *   agent: The agent.
 *   outside: Its `outside_access`.
 *   onChange: Receives the block a Take over answered with.
 */
function OutsidePayer({
  agent,
  outside,
  onChange,
}: {
  agent: Agent;
  outside: OutsideAccess;
  onChange: (access: OutsideAccess) => void;
}) {
  const { t, i18n } = useTranslation();
  const dispatch = useDispatch();
  const token = useSelector(selectToken);
  const teamId =
    agent.workspace?.kind === 'team' ? agent.workspace.team_id : null;
  const teamName = useSelector(
    (state: {
      workspace?: { workspaces?: { id: string; name?: string | null }[] };
    }) =>
      (teamId &&
        state.workspace?.workspaces?.find((row) => row.id === teamId)?.name) ||
      null,
  );
  const me = readerIdFromToken(token);
  const [takeOverState, setTakeOverState] = useState<ActiveState>('INACTIVE');

  const handleTakeOver = async () => {
    if (!agent.id) return;
    const result = await payerService.takeOverOutsideAccess(agent.id, token);
    onChange(result.outside_access);
    rememberOutsideAccess(agent.id, result.outside_access);
    dispatch(
      showActionToast({
        variant: 'success',
        message: t('payer.access.takenOver'),
      }),
    );
  };

  const pauseReason = outsidePauseReason(t, agent, outside, {
    me,
    teamName,
    language: i18n?.language,
  });
  const paidBy = paidByText(t, outside.paid_by, me);
  const takeOverLabel = t('payer.common.takeOver.submit');
  const openTakeOver = () => setTakeOverState('ACTIVE');

  return (
    <>
      {outside.paused_for ? (
        <Alert variant="warning">
          <AlertDescription>
            <p>
              {pauseReason
                ? t('payer.access.notice', {
                    reason: pauseReason,
                    interpolation: { escapeValue: false },
                  })
                : t('payer.access.noticeUnknown')}
              {outside.can_take_over ? (
                <>
                  {' '}
                  <AlertAction onClick={openTakeOver}>
                    {takeOverLabel}
                  </AlertAction>
                </>
              ) : null}
            </p>
          </AlertDescription>
        </Alert>
      ) : paidBy ? (
        <div className="flex items-center justify-between gap-3">
          <p className="text-muted-foreground flex min-w-0 items-center gap-2 text-sm">
            <Wallet className="size-4 shrink-0" aria-hidden="true" />
            <span className="truncate">{paidBy}</span>
          </p>
          {outside.can_take_over ? (
            <Button
              type="button"
              variant="outline"
              size="sm"
              shape="pill"
              className="shrink-0"
              onClick={openTakeOver}
            >
              {takeOverLabel}
            </Button>
          ) : null}
        </div>
      ) : null}
      <TakeOverModal
        kind="outside_access"
        name={agent.name}
        payer={outside.paid_by}
        modalState={takeOverState}
        setModalState={setTakeOverState}
        onConfirm={handleTakeOver}
      />
    </>
  );
}

type AgentDetailsModalProps = {
  agent: Agent;
  mode: 'new' | 'edit' | 'draft';
  modalState: ActiveState;
  setModalState: (state: ActiveState) => void;
  onKeyRegenerated?: (key: string) => void;
  /** The agent's saved config and new `updated_at` after its API-key write allowlist changed. */
  onConfigChange?: (config: AgentConfig, updatedAt?: string) => void;
  /** The agent's last saved config, which an allowlist change saves onto. */
  getSavedConfig?: GetSavedConfig;
  /** Open with the API write allowlist unfolded (sent here to allow changes). */
  openApiWrites?: boolean;
};

export default function AgentDetailsModal({
  agent,
  mode,
  modalState,
  setModalState,
  onKeyRegenerated,
  onConfigChange,
  getSavedConfig,
  openApiWrites = false,
}: AgentDetailsModalProps) {
  const { t } = useTranslation();
  const token = useSelector(selectToken);
  // The agent's team row: its name and whether it is locked.
  const teamId =
    agent.workspace?.kind === 'team' ? agent.workspace.team_id : null;
  const teamRow = useSelector(
    (state: {
      workspace?: {
        workspaces?: {
          id: string;
          name?: string | null;
          outside_policy?: string | null;
        }[];
      };
    }) =>
      (teamId &&
        state.workspace?.workspaces?.find((row) => row.id === teamId)) ||
      null,
  );

  // Who pays for the key, link and webhook, and why they are paused: only
  // for a reader who manages them (the server leaves it out otherwise).
  const [outside, setOutside] = useState<OutsideAccess | null>(
    agent.outside_access ?? null,
  );

  const [sharedToken, setSharedToken] = useState<string | null>(
    agent.shared_token ?? null,
  );
  const [apiKey, setApiKey] = useState<string | null>(null);
  const [webhookUrl, setWebhookUrl] = useState<string | null>(null);
  const [resetKeyConfirmState, setResetKeyConfirmState] =
    useState<ActiveState>('INACTIVE');
  // A failed generate, shown in the modal until the next attempt.
  const [error, setError] = useState<string | null>(null);
  // A failed key reset, shown in its confirm.
  const [resetKeyError, setResetKeyError] = useState<string>();
  const [loadingStates, setLoadingStates] = useState({
    publicLink: false,
    apiKey: false,
    webhook: false,
  });

  const setLoading = (
    key: 'publicLink' | 'apiKey' | 'webhook',
    state: boolean,
  ) => {
    setLoadingStates((prev) => ({ ...prev, [key]: state }));
  };

  /**
   * Runs one of the modal's calls and reports its failure.
   *
   * @param key Which button shows the spinner.
   * @param request The call; resolves to the response.
   * @param onSuccess Receives the parsed body of a successful response.
   * @param onFailure Receives the failure message; the modal's Alert by default.
   */
  const run = async (
    key: 'publicLink' | 'apiKey' | 'webhook',
    request: () => Promise<Response>,
    onSuccess: (data: Record<string, string>) => void,
    onFailure: (message: string) => void = setError,
  ) => {
    setLoading(key, true);
    setError(null);
    let failure: string | null = null;
    try {
      const response = await request();
      if (response.ok) onSuccess(await response.json());
      else
        failure =
          (await errorMessage(response, t)) ??
          t('modals.agentDetails.actionFailed');
    } catch {
      failure = t('modals.agentDetails.actionFailed');
    } finally {
      setLoading(key, false);
    }
    if (failure !== null) onFailure(failure);
  };

  /**
   * Reads who pays again once something was turned on: on a team agent the
   * Admin who turns it on pays for it, which may end a pause.
   */
  const refreshOutside = async () => {
    if (!outside || !agent.id) return;
    try {
      const response = await userService.getAgent(agent.id, token);
      if (!response.ok) return;
      const body = (await response.json()) as Partial<Agent>;
      if (body.outside_access) {
        setOutside(body.outside_access);
        rememberOutsideAccess(agent.id, body.outside_access);
      }
    } catch {
      // The line keeps what it said; the next open reads it again.
    }
  };

  const handleGeneratePublicLink = () =>
    run(
      'publicLink',
      () => userService.shareAgent({ id: agent.id ?? '', shared: true }, token),
      (data) => {
        setSharedToken(data.shared_token);
        void refreshOutside();
      },
    );

  const handleGenerateWebhook = () =>
    run(
      'webhook',
      () => userService.getAgentWebhook(agent.id ?? '', token),
      (data) => {
        setWebhookUrl(data.webhook_url);
        void refreshOutside();
      },
    );

  const handleRegenerateKey = () =>
    run(
      'apiKey',
      () => userService.regenerateAgentKey(agent.id ?? '', token),
      (data) => {
        setApiKey(data.key);
        onKeyRegenerated?.(data.key);
        void refreshOutside();
      },
      // The reset confirm stays open and shows the failure itself.
      (message) => {
        setResetKeyError(message);
        throw new Error(message);
      },
    );

  useEffect(() => {
    setSharedToken(agent.shared_token ?? null);
    setApiKey(agent.key ?? null);
    setOutside(agent.outside_access ?? null);
  }, [agent]);

  // A locked team's agents are reached from nowhere outside it: nothing can
  // be turned on, and what is on is paused (the payer notice says so then).
  const teamLocked =
    teamRow?.outside_policy === 'locked' ||
    outside?.paused_for?.reason === 'team_locked';
  const pauseSaysLocked =
    !!outside &&
    outsideAccessOn(outside) &&
    outside.paused_for?.reason === 'team_locked';

  return (
    <>
      <Modal
        open={modalState === 'ACTIVE'}
        onOpenChange={(o) => !o && setModalState('INACTIVE')}
        title={t('modals.agentDetails.title')}
      >
        <div>
          {error && (
            <Alert variant="destructive" className="mt-6">
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}
          <div className="mt-8 flex flex-col gap-6">
            {teamLocked && !pauseSaysLocked ? (
              <Alert variant="info" role="note">
                <AlertDescription>
                  {teamRow?.name
                    ? t('modals.agentDetails.teamLocked', {
                        team: teamRow.name,
                        interpolation: { escapeValue: false },
                      })
                    : t('modals.agentDetails.teamLockedNoTeam')}
                </AlertDescription>
              </Alert>
            ) : null}
            {/* Who pays for all three ways in, or why they are paused. */}
            {outside && outsideAccessOn(outside) ? (
              <OutsidePayer
                agent={agent}
                outside={outside}
                onChange={setOutside}
              />
            ) : null}
            <div className="flex flex-col gap-3">
              <div className="flex items-center gap-2">
                <SectionHeader
                  as="h3"
                  size="xs"
                  title={t('modals.agentDetails.publicLink')}
                />
              </div>
              {sharedToken ? (
                <div className="flex flex-col gap-2">
                  <p className="text-foreground inline text-sm leading-normal font-medium wrap-anywhere">
                    <a
                      href={`${baseURL}/shared/agent/${sharedToken}`}
                      target="_blank"
                      rel="noreferrer"
                      className={linkFocus}
                    >
                      {`${baseURL}/shared/agent/${sharedToken}`}
                    </a>
                    <CopyButton
                      textToCopy={`${baseURL}/shared/agent/${sharedToken}`}
                      size="xs"
                      className="absolute -mt-0.5 ml-1 inline-flex"
                    />
                  </p>
                  <Button
                    variant="link"
                    size="inline"
                    asChild
                    className="w-fit"
                  >
                    <a
                      href="https://docs.docsgpt.cloud/Agents/basics#core-components-of-an-agent"
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      {t('modals.agentDetails.learnMore')}
                      <ExternalLink />
                    </a>
                  </Button>
                </div>
              ) : teamLocked ? null : (
                <Button
                  type="button"
                  variant="outline-primary"
                  shape="pill"
                  onClick={handleGeneratePublicLink}
                  loading={loadingStates.publicLink}
                >
                  {t('modals.agentDetails.generate')}
                </Button>
              )}
            </div>
            <div className="flex flex-col gap-3">
              <SectionHeader
                as="h3"
                size="xs"
                title={t('modals.agentDetails.apiKey')}
              />
              {apiKey ? (
                <div className="flex flex-col gap-2">
                  <div className="flex items-center gap-2">
                    <div className="text-foreground text-sm leading-normal font-medium wrap-anywhere">
                      {apiKey}
                      {!apiKey.includes('...') && (
                        <CopyButton
                          textToCopy={apiKey}
                          size="xs"
                          className="absolute -mt-0.5 ml-1 inline-flex"
                        />
                      )}
                    </div>
                    {!apiKey.includes('...') && (
                      <Button
                        asChild
                        variant="outline-primary"
                        size="sm"
                        shape="pill"
                        className="group ml-8 w-[101px]"
                      >
                        <a
                          href={`https://widget.docsgpt.cloud/?api-key=${apiKey}`}
                          target="_blank"
                          rel="noopener noreferrer"
                        >
                          {t('modals.agentDetails.test')}
                          <ExternalLink />
                        </a>
                      </Button>
                    )}
                    {apiKey.includes('...') && !teamLocked && (
                      <Button
                        type="button"
                        onClick={() => setResetKeyConfirmState('ACTIVE')}
                        loading={loadingStates.apiKey}
                        variant="outline-primary"
                        size="sm"
                        shape="pill"
                        className="ml-8"
                      >
                        {t('modals.agentDetails.resetKey')}
                      </Button>
                    )}
                  </div>
                </div>
              ) : teamLocked ? null : agent.status === 'draft' ? (
                // A draft has no key yet: the first one is minted on publish.
                <p className="text-muted-foreground text-sm">
                  {t('modals.agentDetails.apiKeyAfterPublish')}
                </p>
              ) : (
                // No key shown on a published agent: minting one replaces
                // any key it has, so it goes through the reset confirmation.
                <Button
                  type="button"
                  variant="outline-primary"
                  shape="pill"
                  onClick={() => setResetKeyConfirmState('ACTIVE')}
                  loading={loadingStates.apiKey}
                >
                  {t('modals.agentDetails.generate')}
                </Button>
              )}
            </div>
            <div className="flex flex-col gap-3">
              <div className="flex items-center gap-2">
                <SectionHeader
                  as="h3"
                  size="xs"
                  title={t('modals.agentDetails.webhookUrl')}
                />
              </div>
              {webhookUrl ? (
                <div className="flex flex-col gap-2">
                  <p className="text-foreground text-sm leading-normal font-medium wrap-anywhere">
                    <a
                      href={webhookUrl}
                      target="_blank"
                      rel="noreferrer"
                      className={linkFocus}
                    >
                      {webhookUrl}
                    </a>
                    <CopyButton
                      textToCopy={webhookUrl}
                      size="xs"
                      className="absolute -mt-0.5 ml-1 inline-flex"
                    />
                  </p>
                  <Button
                    variant="link"
                    size="inline"
                    asChild
                    className="w-fit"
                  >
                    <a
                      href="https://docs.docsgpt.cloud/Agents/basics#core-components-of-an-agent"
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      {t('modals.agentDetails.learnMore')}
                      <ExternalLink />
                    </a>
                  </Button>
                </div>
              ) : teamLocked ? null : (
                <Button
                  type="button"
                  variant="outline-primary"
                  shape="pill"
                  onClick={handleGenerateWebhook}
                  loading={loadingStates.webhook}
                >
                  {t('modals.agentDetails.generate')}
                </Button>
              )}
            </div>
            {/* Changes others can make as the owner, through the API, the
                widget and the public link alike: the modal's last group. It
                acts on the owner's connected accounts, so only the owner
                changes it (the server keeps it otherwise), and it lists the
                writes once the agent has a key. */}
            {apiKey && isOwner(agent) && (
              <ApiWriteAllowlist
                agent={agent}
                onConfigChange={onConfigChange}
                getSavedConfig={getSavedConfig}
                defaultOpen={openApiWrites}
              />
            )}
          </div>
        </div>
      </Modal>
      <ConfirmationModal
        message={t('modals.agentDetails.resetKeyConfirm', {
          interpolation: { escapeValue: false },
          name: agent.name,
        })}
        description={t('modals.agentDetails.resetKeyConsequence')}
        modalState={resetKeyConfirmState}
        setModalState={setResetKeyConfirmState}
        submitLabel={t('modals.agentDetails.reset')}
        handleSubmit={handleRegenerateKey}
        error={resetKeyError}
        variant="destructive"
      />
    </>
  );
}
