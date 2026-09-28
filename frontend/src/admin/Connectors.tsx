import { ExternalLink, Info, TriangleAlert } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';

import connectorsService from '../api/services/connectorsService';
import CopyButton from '../components/CopyButton';
import PageToolbar from '../components/PageToolbar';
import { Alert, AlertDescription, AlertTitle } from '../components/ui/alert';
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import { Card } from '../components/ui/card';
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
  enabled: boolean;
  credential_mode: Policy;
  configured: boolean;
  required_settings: { name: string; set: boolean }[];
  connection_count: number;
  docs_url: string | null;
  mcp_url: string | null;
};

type AdminConnectorsData = {
  success: boolean;
  connectors: AdminConnector[];
  allow_custom_mcp: boolean;
  default_encryption_key: boolean;
  oauth_redirect_uri: string;
  mcp_redirect_uri: string;
};

const POLICY_LABELS: Record<Policy, string> = {
  choose: 'Let owners choose',
  member: "Always each member's own account",
  owner: "Always the owner's account",
};

function CodeRow({ value }: { value: string }) {
  return (
    <Card variant="filled" padding="sm" className="flex-row items-start gap-2">
      <pre className="min-w-0 flex-1 font-mono text-xs wrap-anywhere whitespace-pre-wrap">
        {value}
      </pre>
      <CopyButton textToCopy={value} />
    </Card>
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
  return (
    <Modal
      open
      onOpenChange={(open) => !open && onClose()}
      title={`Set up ${connector.name}`}
      description="Register DocsGPT as an OAuth app with the provider, then set these server settings and restart the API and the worker."
      footer={
        <Button size="lg" shape="pill" onClick={onClose}>
          Done
        </Button>
      }
    >
      <div className="flex flex-col gap-6">
        <section className="flex flex-col gap-2">
          <SectionHeader as="h3" size="xs" title="Redirect URI to register" />
          <CodeRow value={redirectUri} />
        </section>
        <section className="flex flex-col gap-2">
          <SectionHeader as="h3" size="xs" title="Server settings" />
          <DescriptionList layout="justified" size="xs">
            {connector.required_settings.map((setting) => (
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
        </section>
        {connector.key === 'google_drive' && (
          <Alert variant="info" role="note">
            <Info />
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
              Setup guide
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

  const save = async (body: {
    policies?: Record<string, { enabled?: boolean; credential_mode?: Policy }>;
    allow_custom_mcp?: boolean;
  }) => {
    const failed = () =>
      dispatch(
        showActionToast({
          variant: 'destructive',
          message: 'Could not save the change.',
        }),
      );
    try {
      const next = await connectorsService.updateAdmin(body, token);
      if (next?.success) setData(next);
      else failed();
    } catch {
      failed();
    }
  };

  if (data === null && loading) return <LoadingState fill="block" />;
  if (!data?.success)
    return <LoadError message="Failed to load connectors." onRetry={load} />;

  return (
    <div className="flex flex-col gap-8">
      <PageToolbar intro="Choose which connectors members can use and whose account a shared tool runs with. A connector that still needs server settings starts turned off and is hidden from members; it turns on once its settings are in place, unless you switch it off." />

      {data.default_encryption_key && (
        <Alert variant="destructive">
          <TriangleAlert />
          <AlertTitle>
            Set ENCRYPTION_SECRET_KEY before connecting services.
          </AlertTitle>
          <AlertDescription>
            Stored credentials are encrypted with ENCRYPTION_SECRET_KEY, which
            still has its public default value. Set your own, keep the old one
            in ENCRYPTION_SECRET_KEY_PREVIOUS and run{' '}
            <code className="font-mono text-xs">
              docsgpt connectors reencrypt
            </code>
            .
          </AlertDescription>
        </Alert>
      )}

      <SettingRows>
        <SettingRow
          label="Allow custom MCP servers"
          description="Members can connect any remote MCP server. Presets are controlled one by one below."
          htmlFor="allow-custom-mcp"
        >
          <Switch
            id="allow-custom-mcp"
            checked={data.allow_custom_mcp}
            onCheckedChange={(checked) =>
              save({ allow_custom_mcp: checked === true })
            }
          />
        </SettingRow>
      </SettingRows>

      <section className="flex flex-col gap-3">
        <SectionHeader
          title="Redirect URIs"
          description="Register these with each provider's OAuth app."
        />
        <div className="grid grid-cols-1 gap-x-4 gap-y-3 lg:grid-cols-2">
          <div className="flex flex-col gap-1.5">
            <span className="text-muted-foreground text-xs">
              Google Drive, SharePoint and Confluence
            </span>
            <CodeRow value={data.oauth_redirect_uri} />
          </div>
          <div className="flex flex-col gap-1.5">
            <span className="text-muted-foreground text-xs">MCP servers</span>
            <CodeRow value={data.mcp_redirect_uri} />
          </div>
        </div>
      </section>

      <section className="flex flex-col gap-3">
        <SectionHeader title="Connectors" />
        <TableContainer>
          <Table>
            <TableHead>
              <TableRow>
                <TableHeader>Connector</TableHeader>
                <TableHeader>Status</TableHeader>
                <TableHeader align="right">Connections</TableHeader>
                <TableHeader>Enabled</TableHeader>
                <TableHeader>Shared tools use</TableHeader>
                <TableHeader />
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
                      <span className="truncate">{connector.name}</span>
                      {connector.publisher !== 'built_in' && (
                        <Badge variant="neutral">
                          {connector.publisher === 'preset'
                            ? 'Preset'
                            : 'Custom'}
                        </Badge>
                      )}
                    </span>
                  </TableCell>
                  <TableCell>
                    <Badge
                      variant={connector.configured ? 'success' : 'warning'}
                    >
                      {connector.configured ? 'Ready' : 'Needs setup'}
                    </Badge>
                  </TableCell>
                  <TableCell align="right" className="tabular-nums">
                    {fmtNumber(connector.connection_count)}
                  </TableCell>
                  <TableCell>
                    <Switch
                      checked={connector.enabled}
                      aria-label={`${connector.name} enabled`}
                      onCheckedChange={(checked) =>
                        save({
                          policies: {
                            [connector.key]: { enabled: checked === true },
                          },
                        })
                      }
                    />
                  </TableCell>
                  <TableCell>
                    <Select
                      value={connector.credential_mode}
                      onValueChange={(value) =>
                        save({
                          policies: {
                            [connector.key]: {
                              credential_mode: value as Policy,
                            },
                          },
                        })
                      }
                    >
                      <SelectTrigger
                        size="sm"
                        className="w-60"
                        aria-label={`${connector.name} sharing policy`}
                      >
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {(Object.keys(POLICY_LABELS) as Policy[]).map(
                          (policy) => (
                            <SelectItem key={policy} value={policy}>
                              {POLICY_LABELS[policy]}
                            </SelectItem>
                          ),
                        )}
                      </SelectContent>
                    </Select>
                  </TableCell>
                  <TableCell align="right">
                    {connector.required_settings.length > 0 && (
                      <Button
                        type="button"
                        variant="outline"
                        size="xs"
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
