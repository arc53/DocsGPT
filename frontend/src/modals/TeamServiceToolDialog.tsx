import { UserRound, Users } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';
import { useNavigate } from 'react-router-dom';

import connectorsService from '../api/services/connectorsService';
import { Alert, AlertAction, AlertDescription } from '../components/ui/alert';
import { Avatar } from '../components/ui/avatar';
import { Modal, ModalActions } from '../components/ui/modal';
import { OptionCard } from '../components/ui/option-card';
import {
  connectionErrorCode,
  connectionErrorMessage,
} from '../connectors/connectionErrors';
import ConnectorIcon from '../connectors/ConnectorIcon';
import { connectorName } from '../connectors/i18n';
import type { ConnectorDefinition } from '../connectors/types';
import { type LeaveTo, leaveNow } from '../hooks/useLeaveGuard';
import { selectToken } from '../preferences/preferenceSlice';
import { selectCanCreateHere, selectInTeam } from '../settings/workspaceAccess';
import {
  roleAtLeast,
  selectWorkspaceRoleOrNull,
} from '../workspace/workspaceSlice';
import useLeaveForPersonal from './useLeaveForPersonal';

const noEscape = { interpolation: { escapeValue: false } };

type Refusal = { message: string; personalFirst: boolean };

/**
 * How a team adds a service's tool: on each person's own account (Editors
 * and up: the tool keeps no secret, and every run signs in as whoever runs
 * it), or on the team's account, which team Admins connect and manage on
 * the Connectors page (this dialog only points there).
 *
 * Args:
 *   connector: The service; null keeps the dialog closed.
 *   teamHasAccount: Whether the team holds an account for it.
 *   onClose: Closes the dialog.
 *   onCreated: The new tool's id, once a tool was added.
 *   onNavigate: The opener's guarded exit; the router's navigate otherwise.
 */
export default function TeamServiceToolDialog({
  connector,
  teamHasAccount,
  onClose,
  onCreated,
  onNavigate,
}: {
  connector: ConnectorDefinition | null;
  teamHasAccount: boolean;
  onClose: () => void;
  onCreated: (toolId: string) => void;
  onNavigate?: LeaveTo;
}) {
  const { t } = useTranslation();
  const token = useSelector(selectToken);
  const navigate = useNavigate();
  const inTeam = useSelector(selectInTeam);
  const canCreate = useSelector(selectCanCreateHere);
  const role = useSelector(selectWorkspaceRoleOrNull);
  const isAdmin = inTeam && roleAtLeast(role, 'admin');
  const leaveForPersonal = useLeaveForPersonal(onNavigate);
  const [pending, setPending] = useState(false);
  const [refusal, setRefusal] = useState<Refusal | null>(null);

  // Each service opens on a clean dialog.
  useEffect(() => {
    setRefusal(null);
    setPending(false);
  }, [connector?.key]);

  if (!connector) return null;
  const name = connectorName(t, connector);
  const connectorsPath = `/settings/connectors?connector=${encodeURIComponent(
    connector.key,
  )}`;

  const addForEachPerson = async () => {
    setPending(true);
    setRefusal(null);
    try {
      const result = await connectorsService.createMemberTool(
        { connector_key: connector.key },
        token,
      );
      if (result?.success && result.id) {
        onClose();
        onCreated(result.id);
        return;
      }
      setRefusal({
        message: connectionErrorMessage(t, result, {
          fallback: t('settings.tools.team.addFailed'),
        }),
        personalFirst: connectionErrorCode(result) === 'connect_personal_first',
      });
    } catch {
      setRefusal({
        message: t('settings.tools.team.addFailed'),
        personalFirst: false,
      });
    } finally {
      setPending(false);
    }
  };

  const leave = (path: string) => {
    onClose();
    if (onNavigate) onNavigate(path);
    else leaveNow(navigate, path);
  };

  return (
    <Modal
      open
      onOpenChange={(open) => !open && onClose()}
      title={t('settings.tools.team.serviceTitle', { name, ...noEscape })}
      description={t('settings.tools.team.serviceDescription', {
        name,
        ...noEscape,
      })}
      leading={
        <Avatar size="xl" shape="square" variant="icon">
          <ConnectorIcon icon={connector.icon} className="size-7" />
        </Avatar>
      }
      footer={<ModalActions cancelLabel={t('cancel')} onCancel={onClose} />}
    >
      <div className="flex flex-col gap-5">
        {refusal ? (
          <Alert variant={refusal.personalFirst ? 'warning' : 'destructive'}>
            <AlertDescription>
              <p>
                {refusal.message}
                {refusal.personalFirst ? (
                  <>
                    {' '}
                    <AlertAction
                      onClick={() => {
                        onClose();
                        leaveForPersonal(connectorsPath);
                      }}
                    >
                      {t('settings.tools.team.connectInPersonal')}
                    </AlertAction>
                  </>
                ) : null}
              </p>
            </AlertDescription>
          </Alert>
        ) : null}
        <div className="grid gap-3">
          {canCreate ? (
            <OptionCard
              icon={<UserRound />}
              title={t('settings.tools.team.eachPerson')}
              description={t('settings.tools.team.eachPersonHint', {
                name,
                ...noEscape,
              })}
              onClick={addForEachPerson}
              disabled={pending}
              aria-busy={pending}
              data-testid="team-service-each-person"
            />
          ) : null}
          {/* The team's account is the Admins' to connect and manage. */}
          {isAdmin ? (
            <OptionCard
              icon={<Users />}
              title={
                teamHasAccount
                  ? t('settings.tools.team.teamAccount')
                  : t('settings.tools.team.connectForTeam')
              }
              description={
                teamHasAccount
                  ? t('settings.tools.team.teamAccountHint', {
                      name,
                      ...noEscape,
                    })
                  : t('settings.tools.team.connectForTeamHint', {
                      name,
                      ...noEscape,
                    })
              }
              onClick={() => leave(connectorsPath)}
              data-testid="team-service-team-account"
            />
          ) : null}
        </div>
      </div>
    </Modal>
  );
}
