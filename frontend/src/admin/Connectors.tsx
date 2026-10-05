import { ExternalLink } from 'lucide-react';
import { useCallback, useEffect, useRef, useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';

import connectorsService from '../api/services/connectorsService';
import { Alert, AlertDescription, AlertTitle } from '../components/ui/alert';
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import { Card } from '../components/ui/card';
import { CopyField } from '../components/ui/code-block';
import { FormField } from '../components/ui/form-field';
import { ListRow, ListRows } from '../components/ui/list-row';
import { PanelBody, PanelHeader, SidePanel } from '../components/ui/side-panel';
import {
  DescriptionItem,
  DescriptionList,
} from '../components/ui/description-list';
import { LoadingState } from '../components/ui/loading-state';
import { Modal } from '../components/ui/modal';
import { SectionHeader } from '../components/ui/section-header';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '../components/ui/select';
import { SettingRow, SettingRows } from '../components/ui/setting-row';
import { Switch } from '../components/ui/switch';
import {
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableHeader,
  TableRow,
} from '../components/ui/table';
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '../components/ui/tooltip';
import ConnectorIcon from '../connectors/ConnectorIcon';
import { showActionToast } from '../notifications/actionToastSlice';
import { selectToken } from '../preferences/preferenceSlice';
import { LoadError, fmtNumber } from './AdminUI';

type Policy = 'choose' | 'owner' | 'member';

type AdminConnector = {
  key: string;
  name: string;
  icon: string;
  publisher: 'built_in' | 'preset' | 'custom';
  auth_kind: string;
  capabilities: string[];
  enabled: boolean;
  credential_mode: Policy;
  configured: boolean;
  required_settings: { name: string; set: boolean }[];
  /** Optional settings that add a second sign-in (GitHub's App). */
  oauth_settings?: { name: string; set: boolean }[];
  oauth_configured?: boolean;
  connection_count: number;
  docs_url: string | null;
  mcp_url: string | null;
  /**
   * Whether members may let agents make changes through it (GitHub's write
   * tools); null where the connector offers no such choice.
   */
  allow_writes?: boolean | null;
};

type AdminConnectorsData = {
  success: boolean;
  connectors: AdminConnector[];
  allow_custom_mcp: boolean;
  default_encryption_key: boolean;
  /** Every new connection is refused (multi-user install on the default key). */
  connections_blocked?: boolean;
  oauth_redirect_uri: string;
  mcp_redirect_uri: string;
};

const POLICY_LABELS: Record<Policy, string> = {
  choose: 'Sharer decides',
  member: "Each person's own",
  owner: "Sharer's account",
};

const hasTools = (connector: AdminConnector) =>
  connector.capabilities.some((capability) => capability !== 'sync');

const hasSetupGuide = (connector: AdminConnector) =>
  connector.required_settings.length > 0 ||
  (connector.oauth_settings?.length ?? 0) > 0;

/** The connectors whose OAuth app registers the connectors callback. */
const callbackCaption = (connectors: AdminConnector[]) => {
  const names = connectors.filter(hasSetupGuide).map((c) => c.name);
  return names.length > 0
    ? new Intl.ListFormat('en-GB', { type: 'conjunction' }).format(names)
    : 'OAuth connectors';
};

/** Works with pasted tokens, but its optional OAuth sign-in is not set up yet. */
const tokensOnly = (connector: AdminConnector) =>
  (connector.oauth_settings?.length ?? 0) > 0 && !connector.oauth_configured;

function SettingsList({
  settings,
}: {
  settings: { name: string; set: boolean }[];
}) {
  return (
    <DescriptionList layout="justified" size="xs">
      {settings.map((setting) => (
        <DescriptionItem
          key={setting.name}
          label={<code className="font-mono">{setting.name}</code>}
        >
          <Badge variant={setting.set ? 'success' : 'warning'}>
            {setting.set ? 'Set' : 'Missing'}
          </Badge>
        </DescriptionItem>
      ))}
    </DescriptionList>
  );
}

function SetupGuide({
  connector,
  redirectUri,
  onClose,
}: {
  connector: AdminConnector;
  redirectUri: string;
  onClose: () => void;
}) {
  // Focus lands on Done, not on the Copy button, whose tooltip opens on
  // focus. autoFocus covers a dialog opened from the page; over the phone
  // panel the panel's focus trap takes focus back first and the dialog then
  // focuses its first button, so Done takes it again once both have run.
  const focusDone = useCallback((node: HTMLButtonElement | null) => {
    if (node) window.setTimeout(() => node.focus(), 0);
  }, []);
  const oauthSettings = connector.oauth_settings ?? [];
  const optionalOAuth =
    connector.required_settings.length === 0 && oauthSettings.length > 0;
  return (
    <Modal
      open
      onOpenChange={(open) => !open && onClose()}
      title={`Set up ${connector.name}`}
      description={
        optionalOAuth
          ? `Members can already connect ${connector.name} with their own access tokens. To also offer Sign in with ${connector.name}, register a GitHub App, then set these server settings and restart the API and the worker.`
          : 'Register DocsGPT as an OAuth app with the provider, then set these server settings and restart the API and the worker.'
      }
      footer={
        <Button
          ref={focusDone}
          autoFocus
          size="lg"
          shape="pill"
          onClick={onClose}
        >
          Done
        </Button>
      }
    >
      <div className="flex flex-col gap-6">
        <section className="flex flex-col gap-2">
          <SectionHeader
            as="h3"
            size="xs"
            title={
              optionalOAuth
                ? 'Callback URL to register'
                : 'Redirect URI to register'
            }
          />
          <CopyField value={redirectUri} wrap="anywhere" />
        </section>
        {connector.required_settings.length > 0 && (
          <section className="flex flex-col gap-2">
            <SectionHeader as="h3" size="xs" title="Server settings" />
            <SettingsList settings={connector.required_settings} />
          </section>
        )}
        {oauthSettings.length > 0 && (
          <section className="flex flex-col gap-2">
            <SectionHeader
              as="h3"
              size="xs"
              title={`Sign in with ${connector.name} (optional)`}
            />
            <SettingsList settings={oauthSettings} />
          </section>
        )}
        {connector.key === 'github' && (
          <Alert variant="info" role="note">
            <AlertDescription>
              In the GitHub App, give repository permissions Contents and
              Metadata read-only access, and turn on Request user authorization
              (OAuth) during installation so choosing repositories returns to
              DocsGPT. For agents to make changes, also give Issues and Pull
              requests read and write access (Contents read and write only if
              agents should edit files). GITHUB_APP_SLUG is the name in the
              app&apos;s public link (github.com/apps/&lt;slug&gt;).
            </AlertDescription>
          </Alert>
        )}
        {connector.key === 'google_drive' && (
          <Alert variant="info" role="note">
            <AlertDescription>
              Publish the Google OAuth app (or use an internal Workspace app).
              Apps left in Testing get refresh tokens that expire after seven
              days, which stops background sync.
            </AlertDescription>
          </Alert>
        )}
        {connector.docs_url && (
          <Button variant="link" size="inline" asChild className="w-fit">
            <a
              href={connector.docs_url}
              target="_blank"
              rel="noopener noreferrer"
            >
              Documentation
              <ExternalLink />
            </a>
          </Button>
        )}
      </div>
    </Modal>
  );
}

/**
 * Admin > Connectors: which connectors members may use, whose account a
 * shared tool runs with, and what each OAuth connector still needs from the
 * server. English only, like the rest of the admin pages.
 */
export default function Connectors() {
  const dispatch = useDispatch();
  const token = useSelector(selectToken);
  const [data, setData] = useState<AdminConnectorsData | null>(null);
  const [loading, setLoading] = useState(true);
  const [guide, setGuide] = useState<AdminConnector | null>(null);
  const [detailKey, setDetailKey] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setData(await connectorsService.getAdmin(token));
    } catch {
      setData({ success: false } as AdminConnectorsData);
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    load();
  }, [load]);

  // Saves run one after another: each response is a full snapshot, so an
  // older one arriving last would otherwise put back a stale policy.
  const saveQueue = useRef<Promise<void>>(Promise.resolve());
  const save = (body: {
    policies?: Record<
      string,
      { enabled?: boolean; credential_mode?: Policy; allow_writes?: boolean }
    >;
    allow_custom_mcp?: boolean;
  }) => {
    const failed = () =>
      dispatch(
        showActionToast({
          variant: 'destructive',
          message: 'Could not save the change.',
        }),
      );
    saveQueue.current = saveQueue.current.then(async () => {
      try {
        const next = await connectorsService.updateAdmin(body, token);
        if (next?.success) setData(next);
        else failed();
      } catch {
        failed();
      }
    });
    return saveQueue.current;
  };

  if (data === null && loading) return <LoadingState fill="block" />;
  if (!data?.success)
    return <LoadError message="Failed to load connectors." onRetry={load} />;

  // The sheet (phones) always shows the connector's latest saved state.
  const detail = data.connectors.find((c) => c.key === detailKey) ?? null;
  const writable = data.connectors.filter(
    (connector) =>
      connector.allow_writes !== null && connector.allow_writes !== undefined,
  );

  // The custom MCP row is the one switch for members' own MCP servers.
  const isCustomMcp = (connector: AdminConnector) =>
    connector.key === 'custom_mcp';
  const enabledOf = (connector: AdminConnector) =>
    connector.enabled && (!isCustomMcp(connector) || data.allow_custom_mcp);
  const setEnabled = (connector: AdminConnector, on: boolean) =>
    save(
      isCustomMcp(connector)
        ? { allow_custom_mcp: on, policies: { custom_mcp: { enabled: on } } }
        : { policies: { [connector.key]: { enabled: on } } },
    );

  // Settings come first: a row that needs setup keeps saying so. A ready
  // row can't be connected while connects are refused.
  const blocked = data.connections_blocked === true;
  const statusBadge = (connector: AdminConnector) => (
    <span className="inline-flex flex-wrap gap-1">
      {connector.configured && blocked ? (
        <Badge variant="destructive">Blocked</Badge>
      ) : (
        <>
          <Badge variant={connector.configured ? 'success' : 'warning'}>
            {connector.configured ? 'Ready' : 'Needs setup'}
          </Badge>
          {connector.configured && tokensOnly(connector) && (
            <Badge variant="neutral">Tokens only</Badge>
          )}
        </>
      )}
    </span>
  );

  const summary = (connector: AdminConnector) =>
    [
      // The badge beside it says whether setup is missing; this is what
      // members get.
      connector.configured && enabledOf(connector) ? 'On' : 'Off',
      `${fmtNumber(connector.connection_count)} ${
        connector.connection_count === 1 ? 'connection' : 'connections'
      }`,
      hasTools(connector)
        ? POLICY_LABELS[connector.credential_mode]
        : 'No tools',
    ].join(' · ');

  const enabledSwitch = (connector: AdminConnector, id?: string) => {
    const control = (
      <Switch
        id={id}
        checked={enabledOf(connector)}
        disabled={!connector.configured}
        aria-label={`${connector.name} enabled`}
        onCheckedChange={(checked) => setEnabled(connector, checked === true)}
      />
    );
    // Off until its server settings exist: switching it on would do nothing.
    if (connector.configured) return control;
    return (
      <Tooltip>
        <TooltipTrigger asChild>
          <span tabIndex={0} className="inline-flex w-fit">
            {control}
          </span>
        </TooltipTrigger>
        <TooltipContent>Add its server settings first</TooltipContent>
      </Tooltip>
    );
  };

  const policyControl = (connector: AdminConnector, fullWidth = false) =>
    hasTools(connector) ? (
      <Select
        value={connector.credential_mode}
        onValueChange={(value) =>
          save({
            policies: { [connector.key]: { credential_mode: value as Policy } },
          })
        }
      >
        <SelectTrigger
          size={fullWidth ? 'field' : 'sm'}
          className={fullWidth ? 'w-full' : 'w-60'}
          aria-label={`${connector.name} sharing policy`}
        >
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {(Object.keys(POLICY_LABELS) as Policy[]).map((policy) => (
            <SelectItem key={policy} value={policy}>
              {POLICY_LABELS[policy]}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    ) : (
      <span className="text-muted-foreground text-sm">No tools</span>
    );

  return (
    <div className="flex flex-col gap-8">
      <p className="text-muted-foreground text-sm">
        Choose which connectors members can use and whose account a shared tool
        runs with. A connector that still needs server settings starts turned
        off and is hidden from members; it turns on once its settings are in
        place, unless you switch it off.
      </p>

      {data.default_encryption_key && (
        <Alert variant="destructive">
          <AlertTitle>
            {blocked ? (
              <>
                Members can&apos;t connect services until you set{' '}
                <code className="font-mono text-xs">ENCRYPTION_SECRET_KEY</code>
                .
              </>
            ) : (
              <>
                Set{' '}
                <code className="font-mono text-xs">ENCRYPTION_SECRET_KEY</code>{' '}
                before connecting services.
              </>
            )}
          </AlertTitle>
          <AlertDescription>
            <p>
              Stored credentials are encrypted with{' '}
              <code className="font-mono text-xs">ENCRYPTION_SECRET_KEY</code>,
              which still has its public default value
              {blocked ? ', so every new connection is refused' : ''}. Set your
              own, keep the old one in{' '}
              <code className="font-mono text-xs">
                ENCRYPTION_SECRET_KEY_PREVIOUS
              </code>{' '}
              and run{' '}
              <code className="font-mono text-xs">
                docsgpt connectors reencrypt
              </code>
              .
            </p>
          </AlertDescription>
        </Alert>
      )}

      <section className="flex flex-col gap-3">
        <SectionHeader
          title="Connectors"
          description="The MCP server row decides whether members can add their own MCP servers; presets are switched one by one."
        />
        {/* Phones: a list; each row opens the connector's controls. */}
        <Card padding="none" className="overflow-hidden md:hidden">
          <ListRows>
            {data.connectors.map((connector) => (
              <ListRow
                key={connector.key}
                interactive
                asChild
                leading={
                  <ConnectorIcon
                    icon={connector.icon}
                    className="size-5 shrink-0"
                  />
                }
                title={connector.name}
                description={summary(connector)}
                trailing={statusBadge(connector)}
              >
                <button
                  type="button"
                  onClick={() => setDetailKey(connector.key)}
                />
              </ListRow>
            ))}
          </ListRows>
        </Card>
        <TableContainer className="hidden md:block">
          <Table>
            <TableHead>
              <TableRow>
                <TableHeader>Connector</TableHeader>
                <TableHeader>Status</TableHeader>
                <TableHeader align="right">Connections</TableHeader>
                <TableHeader>Enabled</TableHeader>
                <TableHeader>Shared tools use</TableHeader>
                <TableHeader align="right">Actions</TableHeader>
              </TableRow>
            </TableHead>
            <TableBody>
              {data.connectors.map((connector) => (
                <TableRow key={connector.key}>
                  <TableCell>
                    <span className="flex items-center gap-2">
                      <ConnectorIcon
                        icon={connector.icon}
                        className="size-5 shrink-0"
                      />
                      <span className="truncate" title={connector.name}>
                        {connector.name}
                      </span>
                      {connector.publisher !== 'built_in' && (
                        <Badge variant="neutral">
                          {connector.publisher === 'preset'
                            ? 'Preset'
                            : 'Custom'}
                        </Badge>
                      )}
                    </span>
                  </TableCell>
                  <TableCell>{statusBadge(connector)}</TableCell>
                  <TableCell align="right" className="tabular-nums">
                    {fmtNumber(connector.connection_count)}
                  </TableCell>
                  <TableCell>{enabledSwitch(connector)}</TableCell>
                  <TableCell>{policyControl(connector)}</TableCell>
                  <TableCell align="right">
                    {hasSetupGuide(connector) && (
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        onClick={() => setGuide(connector)}
                      >
                        Setup guide
                      </Button>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      </section>

      {writable.length > 0 && (
        <section className="flex flex-col gap-3">
          <SectionHeader
            title="Write access"
            description="Members can let agents make changes through these connectors, one connection at a time. Each change asks first unless the member allows it."
          />
          <SettingRows>
            {writable.map((connector) => (
              <SettingRow
                key={connector.key}
                label={`Let agents make changes through ${connector.name}`}
                description={
                  connector.key === 'github'
                    ? 'Create issues, comments and pull requests. Off keeps every GitHub tool read-only, including ones already set up for changes.'
                    : `Off keeps every ${connector.name} tool read-only.`
                }
                htmlFor={`allow-writes-${connector.key}`}
                alignStart
              >
                <Switch
                  id={`allow-writes-${connector.key}`}
                  checked={connector.allow_writes === true}
                  onCheckedChange={(checked) =>
                    save({
                      policies: {
                        [connector.key]: { allow_writes: checked === true },
                      },
                    })
                  }
                />
              </SettingRow>
            ))}
          </SettingRows>
        </section>
      )}

      {/* Reference an admin copies once, so it comes last. */}
      <section className="flex flex-col gap-3">
        <SectionHeader
          title="Redirect URIs"
          description="Register these with each provider's OAuth app."
        />
        <div className="grid grid-cols-1 gap-x-4 gap-y-4 lg:grid-cols-2">
          <section className="flex flex-col gap-2">
            <SectionHeader
              as="h3"
              size="xs"
              title={callbackCaption(data.connectors)}
            />
            <CopyField value={data.oauth_redirect_uri} wrap="anywhere" />
          </section>
          <section className="flex flex-col gap-2">
            <SectionHeader as="h3" size="xs" title="MCP servers" />
            <CopyField value={data.mcp_redirect_uri} wrap="anywhere" />
          </section>
        </div>
      </section>

      {detail && (
        <SidePanel open onOpenChange={(open) => !open && setDetailKey(null)}>
          <PanelHeader
            title={detail.name}
            description={summary(detail)}
            leading={
              <ConnectorIcon icon={detail.icon} className="size-7 shrink-0" />
            }
          />
          <PanelBody>
            <SettingRows>
              <SettingRow
                label="Enabled"
                htmlFor={`enabled-${detail.key}`}
                description={
                  detail.configured
                    ? 'Members can connect and use it.'
                    : 'Add its server settings first (Setup guide).'
                }
              >
                {enabledSwitch(detail, `enabled-${detail.key}`)}
              </SettingRow>
            </SettingRows>
            {hasTools(detail) && (
              <FormField label="Shared tools use">
                {policyControl(detail, true)}
              </FormField>
            )}
            {hasSetupGuide(detail) && (
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="w-fit"
                onClick={() => setGuide(detail)}
              >
                Setup guide
              </Button>
            )}
          </PanelBody>
        </SidePanel>
      )}

      {guide && (
        <SetupGuide
          connector={guide}
          redirectUri={data.oauth_redirect_uri}
          onClose={() => setGuide(null)}
        />
      )}
    </div>
  );
}
