import { useCallback, useEffect, useId, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';

import { baseURL } from '../api/client';
import connectorsService from '../api/services/connectorsService';
import userService from '../api/services/userService';
import { Alert, AlertAction, AlertDescription } from '../components/ui/alert';
import { Collapsible, CollapsibleTrigger } from '../components/ui/collapsible';
import { Button } from '../components/ui/button';
import { Card } from '../components/ui/card';
import { Input } from '../components/ui/input';
import { FormField } from '../components/ui/form-field';
import { Label } from '../components/ui/label';
import { ListRow, ListRows } from '../components/ui/list-row';
import { RadioGroup, RadioGroupItem } from '../components/ui/radio-group';
import { SectionHeader } from '../components/ui/section-header';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '../components/ui/select';
import { ActiveState } from '../models/misc';
import { selectRecentEvents } from '../notifications/notificationsSlice';
import { selectToken } from '../preferences/preferenceSlice';
import { Modal, ModalActions } from '../components/ui/modal';
import { formatCount } from '../utils/dateTimeUtils';
import {
  connectionErrorCode,
  connectionErrorMessage,
} from '../connectors/connectionErrors';
import { selectCanCreateHere, selectInTeam } from '../settings/workspaceAccess';
import {
  roleAtLeast,
  selectWorkspaceRoleOrNull,
} from '../workspace/workspaceSlice';
import useLeaveForPersonal from './useLeaveForPersonal';

/**
 * A test result, or the OAuth handshake's progress: `waiting` while the
 * sign-in runs (info), `popupBlocked` when the browser stopped the sign-in
 * window (warning, with a link to open it by hand).
 */
type TestResult = {
  success: boolean;
  message: string;
  status?: string;
  notice?: 'waiting' | 'popupBlocked';
  authorization_url?: string;
  tools?: { name: string; description?: string }[];
  tools_count?: number;
};

const NOTICE_VARIANT = { waiting: 'info', popupBlocked: 'warning' } as const;

/**
 * Who signs in to a new sign-in (OAuth) server added in a team: each person
 * with their own account (a tool that keeps no sign-in), or the team once,
 * with the Admin's account (the team's connection, naming them).
 */
type TeamSignIn = 'member' | 'team';

/**
 * A save in a team: the connection the server now runs on (the team's), or
 * null for a tool on each person's own sign-in. Personal saves leave it out.
 */
export type McpSaved = { connectionId: string | null };

interface MCPServerModalProps {
  modalState: ActiveState;
  setModalState: (state: ActiveState) => void;
  /**
   * The server to reconnect or the preset to add. A team's sign-in being
   * reconnected from its connection carries `owner: 'team'` and its
   * `connection_id`, and no tool `id`.
   */
  server?: any;
  /** Called with the saved server's tool id once it is saved. */
  onServerSaved: (toolId?: string, saved?: McpSaved) => void;
}

/**
 * The origin (scheme, host, port) of a URL, or '' while it doesn't parse.
 * Saved secrets follow the origin, like the server's rule: the same host over
 * http would send them in cleartext, and another port can be another service.
 */
function originOf(url: string): string {
  try {
    return new URL(url.trim()).origin.toLowerCase();
  } catch {
    return '';
  }
}

// The saved secret each auth type keeps, named for the host-change notice.
const SECRET_FIELDS: Record<string, { field: string; nameKey: string }> = {
  api_key: { field: 'api_key', nameKey: 'apiKey' },
  bearer: { field: 'bearer_token', nameKey: 'bearer' },
  basic: { field: 'password', nameKey: 'password' },
};

export default function MCPServerModal({
  modalState,
  setModalState,
  server,
  onServerSaved,
}: MCPServerModalProps) {
  const { t } = useTranslation();
  const token = useSelector(selectToken);
  const recentEvents = useSelector(selectRecentEvents);

  // In a team a new server may sign in (OAuth): on each person's own
  // account (Editors and up) or once for the team (Admins). A team server
  // saved without sign-in keeps its kind; a server that signs in keeps its
  // value shown.
  const inTeam = useSelector(selectInTeam);
  const canCreate = useSelector(selectCanCreateHere);
  const role = useSelector(selectWorkspaceRoleOrNull);
  const isTeamAdmin = inTeam && roleAtLeast(role, 'admin');
  const isNewServer = !server?.id;
  const offerOAuth =
    !inTeam || server?.auth_type === 'oauth' || (isNewServer && canCreate);
  // The team's own sign-in, reconnected from its connection.
  const teamReconnectId =
    server?.owner === 'team' && typeof server?.connection_id === 'string'
      ? (server.connection_id as string)
      : null;
  const [teamSignIn, setTeamSignIn] = useState<TeamSignIn>('member');
  const leaveForPersonal = useLeaveForPersonal();
  // The adder has no sign-in of their own to the server yet.
  const [personalFirst, setPersonalFirst] = useState(false);
  const authTypes = [
    { label: t('settings.tools.mcp.authTypes.none'), value: 'none' },
    { label: t('settings.tools.mcp.authTypes.apiKey'), value: 'api_key' },
    { label: t('settings.tools.mcp.authTypes.bearer'), value: 'bearer' },
    ...(offerOAuth
      ? [{ label: t('settings.tools.mcp.authTypes.oauth'), value: 'oauth' }]
      : []),
    // { label: t('settings.tools.mcp.authTypes.basic'), value: 'basic' },
  ];

  const [formData, setFormData] = useState({
    name: server?.displayName || t('settings.tools.mcp.defaultServerName'),
    server_url: server?.server_url || '',
    auth_type: server?.auth_type || 'none',
    api_key: '',
    header_name: server?.api_key_header || 'X-API-Key',
    bearer_token: '',
    username: '',
    password: '',
    timeout: server?.timeout || 30,
    oauth_scopes: server?.oauth_scopes || '',
    oauth_task_id: '',
  });

  const [loading, setLoading] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<TestResult | null>(null);
  const [discoveredTools, setDiscoveredTools] = useState<
    { name: string; description?: string }[]
  >([]);
  const [errors, setErrors] = useState<{ [key: string]: string }>({});
  // A new sign-in server in a team asks who signs in; only an Admin may
  // sign in for the team, so anyone else adds it for each person.
  const asksWhoSignsIn =
    inTeam && isNewServer && !teamReconnectId && formData.auth_type === 'oauth';
  const memberMode =
    asksWhoSignsIn && (teamSignIn === 'member' || !isTeamAdmin);
  const teamMode =
    !!teamReconnectId ||
    (asksWhoSignsIn && teamSignIn === 'team' && isTeamAdmin);
  const oauthPopupRef = useRef<Window | null>(null);
  // Set after ``test_mcp_connection`` returns ``task_id``. The SSE
  // effect filters ``recentEvents`` to envelopes matching this id and
  // drives the OAuth UI (popup open / completion / failure) from the
  // push stream rather than polling the legacy status endpoint.
  const [oauthTaskId, setOauthTaskId] = useState<string | null>(null);
  // Highest event id we have already reacted to for this taskId. Each
  // mcp.oauth.* envelope must fire its side-effect once; without this
  // any later re-render that re-evaluates ``recentEvents`` would
  // re-open the popup or re-fire onComplete.
  const handledEventIdsRef = useRef<Set<string>>(new Set());
  // Holds the ``testConnection`` ``onComplete`` for the current
  // task id so the SSE effect can invoke it when the terminal event
  // lands. Reset to ``null`` on cancel / new test / unmount.
  const onCompleteRef = useRef<((result: any) => void) | null>(null);
  const popupOpenedRef = useRef(false);
  const [oauthCompleted, setOAuthCompleted] = useState(false);
  const [saveActive, setSaveActive] = useState(false);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const advancedId = useId();
  // A timeout error opens the section so the message is never hidden.
  const advancedOpen = showAdvanced || !!errors.timeout;

  // A tool shared with the caller (an editor reconnecting the owner's
  // server): its saved secrets stay hidden and a new entry replaces them.
  const isShared = !!server?.access && server.access !== 'owner';
  // Only the owner can change or re-run an OAuth server's sign-in (the tokens
  // are theirs), so the modal is read-only for a teammate. The Tools menu
  // doesn't offer it to them; this guards any other way in.
  const oauthOwnerOnly = isShared && server?.auth_type === 'oauth';
  const savedSecret = SECRET_FIELDS[formData.auth_type];
  const hasSavedSecret =
    !!server?.has_encrypted_credentials &&
    !!savedSecret &&
    formData.auth_type === server?.auth_type;
  // The server clears the saved secret when the origin changes, so the key
  // can't be pointed at another server, port or plain http.
  const serverChanged =
    hasSavedSecret &&
    originOf(formData.server_url) !== originOf(server?.server_url || '');
  const keepSavedSecret = hasSavedSecret && !serverChanged;

  const cleanupOAuthListener = useCallback(() => {
    setOauthTaskId(null);
    handledEventIdsRef.current = new Set();
    onCompleteRef.current = null;
    popupOpenedRef.current = false;
    if (oauthPopupRef.current && !oauthPopupRef.current.closed) {
      oauthPopupRef.current.close();
    }
    oauthPopupRef.current = null;
  }, []);

  useEffect(() => {
    return cleanupOAuthListener;
  }, [cleanupOAuthListener]);

  useEffect(() => {
    if (modalState === 'ACTIVE' && server) {
      const oauthScopes = Array.isArray(server.oauth_scopes)
        ? server.oauth_scopes.join(', ')
        : server.oauth_scopes || '';
      setFormData({
        name: server.displayName || t('settings.tools.mcp.defaultServerName'),
        server_url: server.server_url || '',
        auth_type: server.auth_type || 'none',
        api_key: '',
        header_name: server.api_key_header || 'X-API-Key',
        bearer_token: '',
        username: '',
        password: '',
        timeout: server.timeout || 30,
        oauth_scopes: oauthScopes,
        oauth_task_id: '',
      });
      setErrors({});
      setTestResult(null);
      setDiscoveredTools([]);
      setSaveActive(false);
      setOAuthCompleted(false);
      setTeamSignIn('member');
      setPersonalFirst(false);
    }
  }, [modalState, server]);

  const resetForm = () => {
    cleanupOAuthListener();
    setFormData({
      name: t('settings.tools.mcp.defaultServerName'),
      server_url: '',
      auth_type: 'none',
      api_key: '',
      header_name: 'X-API-Key',
      bearer_token: '',
      username: '',
      password: '',
      timeout: 30,
      oauth_scopes: '',
      oauth_task_id: '',
    });
    setErrors({});
    setTestResult(null);
    setDiscoveredTools([]);
    setSaveActive(false);
    setTesting(false);
    setOAuthCompleted(false);
    setTeamSignIn('member');
    setPersonalFirst(false);
  };

  // A sign-in for one choice is never saved under the other.
  const pickTeamSignIn = (value: string) => {
    if (value !== 'member' && value !== 'team') return;
    cleanupOAuthListener();
    setTeamSignIn(value);
    setTestResult(null);
    setDiscoveredTools([]);
    setSaveActive(false);
    setOAuthCompleted(false);
    setTesting(false);
    setErrors((prev) => ({ ...prev, general: '' }));
    setPersonalFirst(false);
  };

  // `owner: 'team'` signs in for the header's team (an Admin), and names
  // the team's connection when it is the one being reconnected.
  const teamOwner = () =>
    teamMode
      ? {
          owner: 'team' as const,
          ...(teamReconnectId && { connection_id: teamReconnectId }),
        }
      : {};

  const validateForm = () => {
    const requiredFields: { [key: string]: boolean } = {
      name: !formData.name.trim(),
      server_url: !formData.server_url.trim(),
    };

    const authFieldChecks: { [key: string]: () => void } = {
      api_key: () => {
        if (!formData.api_key.trim() && !keepSavedSecret)
          newErrors.api_key = t('settings.tools.mcp.errors.apiKeyRequired');
      },
      bearer: () => {
        if (!formData.bearer_token.trim() && !keepSavedSecret)
          newErrors.bearer_token = t('settings.tools.mcp.errors.tokenRequired');
      },
      basic: () => {
        if (!formData.username.trim())
          newErrors.username = t('settings.tools.mcp.errors.usernameRequired');
        if (!formData.password.trim() && !keepSavedSecret)
          newErrors.password = t('settings.tools.mcp.errors.passwordRequired');
      },
    };

    const newErrors: { [key: string]: string } = {};
    Object.entries(requiredFields).forEach(([field, isEmpty]) => {
      if (isEmpty)
        newErrors[field] = t(
          `settings.tools.mcp.errors.${field === 'name' ? 'nameRequired' : 'urlRequired'}`,
        );
    });

    if (formData.server_url.trim()) {
      try {
        new URL(formData.server_url);
      } catch {
        newErrors.server_url = t('settings.tools.mcp.errors.invalidUrl');
      }
    }

    const timeoutValue = formData.timeout === '' ? 30 : formData.timeout;
    if (
      typeof timeoutValue === 'number' &&
      (timeoutValue < 1 || timeoutValue > 300)
    )
      newErrors.timeout = t('settings.tools.mcp.errors.timeoutRange');

    if (authFieldChecks[formData.auth_type])
      authFieldChecks[formData.auth_type]();

    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  };

  const handleInputChange = (name: string, value: string | number) => {
    setFormData((prev) => ({ ...prev, [name]: value }));
    if (errors[name]) {
      setErrors((prev) => ({ ...prev, [name]: '' }));
    }
    setTestResult(null);
  };

  const buildToolConfig = () => {
    const config: any = {
      server_url: formData.server_url.trim(),
      auth_type: formData.auth_type,
      timeout: formData.timeout === '' ? 30 : formData.timeout,
    };

    if (formData.auth_type === 'api_key') {
      config.api_key = formData.api_key.trim();
      config.api_key_header = formData.header_name.trim() || 'X-API-Key';
    } else if (formData.auth_type === 'bearer') {
      config.bearer_token = formData.bearer_token.trim();
    } else if (formData.auth_type === 'basic') {
      config.username = formData.username.trim();
      config.password = formData.password.trim();
    } else if (formData.auth_type === 'oauth') {
      config.oauth_scopes = formData.oauth_scopes
        .split(',')
        .map((s: string) => s.trim())
        .filter(Boolean);
      config.oauth_task_id = formData.oauth_task_id.trim();
      config.redirect_uri = `${baseURL.replace(/\/$/, '')}/api/mcp_server/callback`;
    }
    return config;
  };

  /**
   * Drive the OAuth handshake straight from the SSE stream:
   *
   * - ``mcp.oauth.awaiting_redirect`` → open the popup with the
   *   ``authorization_url`` carried on the envelope. The worker publishes
   *   it inline; there is no polling endpoint, so OAuth needs SSE push on.
   * - ``mcp.oauth.completed`` → enable Save, surface discovered tools,
   *   invoke ``onComplete`` (resolves ``testConnection``'s pending state).
   * - ``mcp.oauth.failed`` → surface the error and reset Save.
   *
   * Each event is matched to the active task id via ``scope.id``. The
   * publisher is best-effort: a lost ``awaiting_redirect`` envelope
   * means the popup never opens, the user retries, and we accept that
   * over the prior 1s × 60 polling loop.
   */
  useEffect(() => {
    if (!oauthTaskId) return;
    // ``recentEvents`` is newest-first (the slice ``unshift``s on
    // arrival). Walk it oldest-first so we observe the natural OAuth
    // ordering (``awaiting_redirect`` → ``completed``) when both
    // arrive between effect runs — otherwise we would short-circuit
    // on ``completed`` and never open the popup for the
    // ``awaiting_redirect`` envelope that was already buffered.
    for (let i = recentEvents.length - 1; i >= 0; i--) {
      const event = recentEvents[i];
      if (event.scope?.id !== oauthTaskId) continue;
      if (!event.id || handledEventIdsRef.current.has(event.id)) continue;

      const payload = (event.payload || {}) as Record<string, unknown>;

      if (event.type === 'mcp.oauth.awaiting_redirect') {
        handledEventIdsRef.current.add(event.id);
        const authUrl = payload.authorization_url as string | undefined;
        if (authUrl && !popupOpenedRef.current) {
          popupOpenedRef.current = true;
          if (oauthPopupRef.current && !oauthPopupRef.current.closed) {
            oauthPopupRef.current.close();
          }
          oauthPopupRef.current = window.open(
            authUrl,
            'oauthPopup',
            'width=600,height=700',
          );
          if (!oauthPopupRef.current) {
            // Popup blocked — surface the URL inline so the user can
            // click through manually. Browsers gate ``window.open``
            // outside of a user gesture, and the SSE event arrives
            // asynchronously, so a blocked popup is expected on
            // some browsers / configs.
            setTestResult({
              success: false,
              notice: 'popupBlocked',
              message: t('settings.tools.mcp.oauthPopupBlocked'),
              authorization_url: authUrl,
            });
          }
        }
        continue;
      }

      if (event.type === 'mcp.oauth.completed') {
        handledEventIdsRef.current.add(event.id);
        const tools = Array.isArray(payload.tools) ? payload.tools : [];
        const toolsCount =
          (payload.tools_count as number | undefined) ?? tools.length;
        setOAuthCompleted(true);
        setSaveActive(true);
        if (oauthPopupRef.current && !oauthPopupRef.current.closed) {
          oauthPopupRef.current.close();
        }
        const cb = onCompleteRef.current;
        onCompleteRef.current = null;
        setOauthTaskId(null);
        if (cb) {
          cb({
            status: 'completed',
            task_id: oauthTaskId,
            tools,
            tools_count: toolsCount,
            success: true,
            message: t('settings.tools.mcp.oauthCompleted'),
          });
        }
        continue;
      }

      if (event.type === 'mcp.oauth.failed') {
        handledEventIdsRef.current.add(event.id);
        const message =
          (payload.error as string) ??
          t('settings.tools.mcp.errors.oauthFailed');
        setSaveActive(false);
        if (oauthPopupRef.current && !oauthPopupRef.current.closed) {
          oauthPopupRef.current.close();
        }
        const cb = onCompleteRef.current;
        onCompleteRef.current = null;
        setOauthTaskId(null);
        if (cb) {
          cb({
            status: 'error',
            task_id: oauthTaskId,
            success: false,
            message,
          });
        }
        continue;
      }
    }
  }, [recentEvents, oauthTaskId, t]);

  const testConnection = async () => {
    if (!validateForm()) return;
    cleanupOAuthListener();
    setTesting(true);
    setTestResult(null);
    setDiscoveredTools([]);
    setOAuthCompleted(false);
    try {
      const config = buildToolConfig();
      // The id lets the server test with the saved secret left empty.
      const response = await userService.testMCPConnection(
        { config, ...(server?.id && { id: server.id }), ...teamOwner() },
        token,
      );
      const result = await response.json();
      // A team sign-in refused (an Admin's, or one the team already holds).
      if (connectionErrorCode(result)) {
        setTestResult({
          success: false,
          message: connectionErrorMessage(t, result, {
            status: response.status,
          }),
        });
        setSaveActive(false);
        setTesting(false);
        return;
      }

      if (
        formData.auth_type === 'oauth' &&
        result.requires_oauth &&
        result.task_id
      ) {
        setTestResult({
          success: false,
          notice: 'waiting',
          message: t('settings.tools.mcp.oauthInProgress'),
        });
        setSaveActive(false);
        onCompleteRef.current = (finalResult: any) => {
          setTestResult(finalResult);
          if (finalResult.tools && Array.isArray(finalResult.tools)) {
            setDiscoveredTools(finalResult.tools);
          }
          setFormData((prev) => ({
            ...prev,
            oauth_task_id: result.task_id || '',
          }));
          setTesting(false);
        };
        // Activate the SSE listener for this task id. The effect above
        // will react when ``mcp.oauth.{awaiting_redirect,completed,failed}``
        // arrives.
        setOauthTaskId(result.task_id);
      } else {
        setTestResult(result);
        if (result.success && result.tools && Array.isArray(result.tools)) {
          setDiscoveredTools(result.tools);
        }
        setSaveActive(result.success === true);
        setTesting(false);
      }
    } catch (error) {
      setTestResult({
        success: false,
        message: t('settings.tools.mcp.errors.testFailed'),
      });
      setOAuthCompleted(false);
      setSaveActive(false);
      setTesting(false);
    }
  };

  // A team's tool on each person's own sign-in keeps no sign-in: the
  // server reads its actions with the adder's own (made in Personal).
  const saveForEachPerson = async () => {
    const result = await connectorsService.createMemberTool(
      {
        connector_key: 'custom_mcp',
        server_url: formData.server_url.trim(),
        displayName: formData.name.trim(),
      },
      token,
    );
    if (result?.success && result.id) {
      onServerSaved(result.id, { connectionId: null });
      setModalState('INACTIVE');
      resetForm();
      return;
    }
    setPersonalFirst(connectionErrorCode(result) === 'connect_personal_first');
    setErrors({
      general: connectionErrorMessage(t, result, {
        fallback: t('settings.tools.mcp.errors.saveFailed'),
      }),
    });
  };

  const handleSave = async () => {
    if (!validateForm()) return;
    setLoading(true);
    setPersonalFirst(false);
    try {
      if (memberMode) {
        await saveForEachPerson();
        return;
      }
      const config = buildToolConfig();
      const serverData = {
        displayName: formData.name,
        config,
        status: true,
        ...(server?.id && { id: server.id }),
        ...teamOwner(),
      };

      const response = await userService.saveMCPServer(serverData, token);
      const result = await response.json();

      if (response.ok && result.success) {
        setTestResult({
          success: true,
          message: result.message,
        });
        onServerSaved(
          typeof result.id === 'string' ? result.id : undefined,
          // A team's save names the team's connection it runs on.
          teamMode
            ? {
                connectionId:
                  typeof result.connection_id === 'string'
                    ? result.connection_id
                    : null,
              }
            : undefined,
        );
        setModalState('INACTIVE');
        resetForm();
      } else {
        setErrors({
          general: connectionErrorMessage(t, result, {
            status: response.status,
            fallback: t('settings.tools.mcp.errors.saveFailed'),
          }),
        });
      }
    } catch {
      setErrors({ general: t('settings.tools.mcp.errors.saveFailed') });
    } finally {
      setLoading(false);
    }
  };

  const renderAuthFields = () => {
    switch (formData.auth_type) {
      case 'api_key':
        return (
          <div className="flex flex-col gap-5">
            <FormField
              label={t('settings.tools.mcp.authTypes.apiKey')}
              required
              error={errors.api_key}
              hint={
                keepSavedSecret
                  ? t('settings.tools.mcp.savedKeyHint')
                  : undefined
              }
            >
              <Input
                type="password"
                autoComplete="off"
                value={formData.api_key}
                onChange={(e) => handleInputChange('api_key', e.target.value)}
                placeholder={t('settings.tools.mcp.placeholders.apiKey')}
              />
            </FormField>
            <FormField label={t('settings.tools.mcp.headerName')}>
              <Input
                type="text"
                value={formData.header_name}
                onChange={(e) =>
                  handleInputChange('header_name', e.target.value)
                }
                placeholder="X-API-Key"
              />
            </FormField>
          </div>
        );
      case 'bearer':
        return (
          <FormField
            label={t('settings.tools.mcp.authTypes.bearer')}
            required
            error={errors.bearer_token}
            hint={
              keepSavedSecret ? t('settings.tools.mcp.savedKeyHint') : undefined
            }
          >
            <Input
              type="password"
              autoComplete="off"
              value={formData.bearer_token}
              onChange={(e) =>
                handleInputChange('bearer_token', e.target.value)
              }
              placeholder={t('settings.tools.mcp.placeholders.bearerToken')}
            />
          </FormField>
        );
      case 'basic':
        return (
          <div className="flex flex-col gap-5">
            <FormField
              label={t('settings.tools.mcp.username')}
              required
              error={errors.username}
            >
              <Input
                type="text"
                value={formData.username}
                onChange={(e) => handleInputChange('username', e.target.value)}
                placeholder={t('settings.tools.mcp.placeholders.username')}
              />
            </FormField>
            <FormField
              label={t('settings.tools.mcp.password')}
              required
              error={errors.password}
              hint={
                keepSavedSecret
                  ? t('settings.tools.mcp.savedKeyHint')
                  : undefined
              }
            >
              <Input
                type="password"
                value={formData.password}
                onChange={(e) => handleInputChange('password', e.target.value)}
                placeholder={t('settings.tools.mcp.placeholders.password')}
              />
            </FormField>
          </div>
        );
      default:
        return null;
    }
  };

  return (
    <Modal
      open={modalState === 'ACTIVE'}
      onOpenChange={(o) => {
        if (!o) {
          setModalState('INACTIVE');
          resetForm();
        }
      }}
      title={
        server?.id
          ? t('settings.tools.mcp.reconnectServer')
          : server?.preset
            ? t('settings.connectors.wizard.connectTitle', {
                name: server.displayName,
                interpolation: { escapeValue: false },
              })
            : t('settings.tools.mcp.addServer')
      }
      description={
        isShared
          ? t('settings.tools.mcp.sharedByEditor', {
              interpolation: { escapeValue: false },
              owner: server.owner_label || t('settings.tools.mcp.aTeammate'),
            })
          : undefined
      }
      size="lg"
      footer={
        <ModalActions
          // Each person's own sign-in is tested when they sign in.
          footerStart={
            oauthOwnerOnly || memberMode ? undefined : (
              <Button
                type="button"
                variant="outline"
                onClick={testConnection}
                loading={testing}
                size="lg"
                shape="pill"
              >
                {t('settings.tools.mcp.testConnection')}
              </Button>
            )
          }
          cancelLabel={t('settings.tools.mcp.cancel')}
          onCancel={() => {
            setModalState('INACTIVE');
            resetForm();
          }}
          submitLabel={t('settings.tools.mcp.save')}
          onSubmit={handleSave}
          pending={loading}
          disabled={memberMode ? false : !saveActive || oauthOwnerOnly}
        />
      }
    >
      <div className="flex flex-col gap-5">
        {errors.general && (
          <Alert variant={personalFirst ? 'warning' : 'destructive'}>
            <AlertDescription>
              <p>
                {errors.general}
                {/* The adder signs in to the server in Personal, where the
                    form opens again with it filled in. */}
                {personalFirst ? (
                  <>
                    {' '}
                    <AlertAction
                      onClick={() => {
                        const newMcpServer = {
                          displayName: formData.name.trim(),
                          server_url: formData.server_url.trim(),
                          auth_type: 'oauth',
                          oauth_scopes: formData.oauth_scopes,
                        };
                        setModalState('INACTIVE');
                        resetForm();
                        leaveForPersonal('/settings/tools', { newMcpServer });
                      }}
                    >
                      {t('settings.tools.mcp.team.signInInPersonal')}
                    </AlertAction>
                  </>
                ) : null}
              </p>
            </AlertDescription>
          </Alert>
        )}
        {!server?.preset && (
          <Alert variant="warning" role="note">
            <AlertDescription>
              {t('settings.connectors.unverified')}
            </AlertDescription>
          </Alert>
        )}
        {isShared && (
          <Alert variant="info" role="note">
            <AlertDescription>
              {t('settings.tools.mcp.sharedCredentialsNotice')}
              {oauthOwnerOnly &&
                ` ${t('settings.tools.mcp.sharedOAuthOwnerOnly')}`}
            </AlertDescription>
          </Alert>
        )}
        <FormField
          label={t('settings.tools.mcp.serverName')}
          required
          error={errors.name}
        >
          <Input
            type="text"
            value={formData.name}
            onChange={(e) => handleInputChange('name', e.target.value)}
          />
        </FormField>

        <FormField
          label={t('settings.tools.mcp.serverUrl')}
          required
          error={errors.server_url}
        >
          <Input
            type="text"
            value={formData.server_url}
            onChange={(e) => handleInputChange('server_url', e.target.value)}
            placeholder="https://example.com/mcp"
            disabled={oauthOwnerOnly}
          />
        </FormField>
        {serverChanged && (
          <Alert variant="warning">
            <AlertDescription>
              {t('settings.tools.mcp.serverChangedNotice', {
                interpolation: { escapeValue: false },
                credential: t(
                  `settings.tools.mcp.credentialNames.${savedSecret.nameKey}`,
                ),
              })}
            </AlertDescription>
          </Alert>
        )}

        <FormField
          label={t('settings.tools.mcp.authType')}
          hint={
            offerOAuth
              ? undefined
              : t('settings.tools.mcp.team.oauthNewServerOnly')
          }
        >
          <Select
            value={formData.auth_type}
            onValueChange={(v) => handleInputChange('auth_type', v)}
            disabled={oauthOwnerOnly}
          >
            <SelectTrigger size="field" className="w-full">
              <SelectValue placeholder={t('settings.tools.mcp.authType')} />
            </SelectTrigger>
            <SelectContent>
              {authTypes.map((type) => (
                <SelectItem key={type.value} value={type.value}>
                  {type.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </FormField>

        {renderAuthFields()}

        {asksWhoSignsIn &&
          (isTeamAdmin ? (
            <RadioGroup
              value={teamSignIn}
              onValueChange={pickTeamSignIn}
              aria-label={t('settings.tools.mcp.team.whoSignsIn')}
            >
              {(['member', 'team'] as const).map((option) => {
                const id = `mcp-team-sign-in-${option}`;
                const key = option === 'member' ? 'eachPerson' : 'teamOnce';
                return (
                  <div key={option} className="flex items-start gap-3">
                    <RadioGroupItem
                      id={id}
                      value={option}
                      aria-describedby={`${id}-hint`}
                      className="mt-0.5"
                    />
                    <div className="flex min-w-0 flex-col gap-1">
                      <Label htmlFor={id}>
                        {t(`settings.tools.mcp.team.${key}`)}
                      </Label>
                      <p
                        id={`${id}-hint`}
                        className="text-muted-foreground text-sm"
                      >
                        {t(`settings.tools.mcp.team.${key}Hint`)}
                      </p>
                    </div>
                  </div>
                );
              })}
            </RadioGroup>
          ) : (
            <Alert variant="info" role="note">
              <AlertDescription>
                {t('settings.tools.mcp.team.eachPersonHint')}
              </AlertDescription>
            </Alert>
          ))}

        {/* Scopes and timeout rarely need changing: behind Advanced. The
            20px gap sits inside the body, so it folds away with it. Each
            person's own sign-in sets its own (none here). */}
        {memberMode ? null : (
          <div>
            <CollapsibleTrigger
              open={advancedOpen}
              onOpenChange={() => setShowAdvanced((open) => !open)}
              controls={advancedId}
              chevron="sm"
            >
              <span>{t('settings.tools.mcp.advanced')}</span>
            </CollapsibleTrigger>
            <Collapsible open={advancedOpen} id={advancedId}>
              <div className="flex flex-col gap-5 pt-5">
                {formData.auth_type === 'oauth' && (
                  <FormField
                    label={t('settings.tools.mcp.placeholders.oauthScopes')}
                  >
                    <Input
                      type="text"
                      value={formData.oauth_scopes}
                      onChange={(e) =>
                        handleInputChange('oauth_scopes', e.target.value)
                      }
                      placeholder="read, write"
                      disabled={oauthOwnerOnly}
                    />
                  </FormField>
                )}
                <FormField
                  label={t('settings.tools.mcp.timeout')}
                  error={errors.timeout}
                >
                  <Input
                    type="number"
                    value={formData.timeout}
                    onChange={(e) => {
                      const value = e.target.value;
                      if (value === '') {
                        handleInputChange('timeout', '');
                      } else {
                        const numValue = parseInt(value);
                        if (!isNaN(numValue) && numValue >= 1) {
                          handleInputChange('timeout', numValue);
                        }
                      }
                    }}
                    placeholder="30"
                    min={1}
                    max={300}
                  />
                </FormField>
              </div>
            </Collapsible>
          </div>
        )}

        {testResult && (
          <Alert
            variant={
              testResult.notice
                ? NOTICE_VARIANT[testResult.notice]
                : testResult.success
                  ? 'success'
                  : 'destructive'
            }
          >
            <AlertDescription>
              <p>
                {testResult.message}
                {testResult.authorization_url && (
                  <>
                    {' '}
                    <AlertAction asChild>
                      <a
                        href={testResult.authorization_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        onClick={(e) => {
                          e.preventDefault();
                          const popup = window.open(
                            testResult.authorization_url,
                            'oauthPopup',
                            'width=600,height=700',
                          );
                          if (popup) oauthPopupRef.current = popup;
                        }}
                      >
                        {t('settings.tools.mcp.openAuthPage')}
                      </a>
                    </AlertAction>
                  </>
                )}
              </p>
            </AlertDescription>
          </Alert>
        )}

        {discoveredTools.length > 0 && testResult?.success && (
          <div className="flex flex-col gap-2">
            <SectionHeader
              as="h3"
              size="xs"
              title={t('settings.tools.mcp.discoveredTools', {
                count: discoveredTools.length,
                formatted: formatCount(discoveredTools.length),
              })}
            />
            <Card padding="none" className="overflow-hidden">
              <ListRows>
                {discoveredTools.map((tool) => (
                  <ListRow
                    key={tool.name}
                    title={tool.name}
                    description={tool.description}
                  />
                ))}
              </ListRows>
            </Card>
          </div>
        )}
        {!saveActive && !oauthOwnerOnly && !memberMode && (
          <p className="text-muted-foreground text-xs">
            {t('settings.tools.mcp.testBeforeSave')}
          </p>
        )}
      </div>
    </Modal>
  );
}
