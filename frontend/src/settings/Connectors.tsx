import { ChevronDown, Plus } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';
import { useSearchParams } from 'react-router-dom';

import PageToolbar from '../components/PageToolbar';
import SearchInput from '../components/SearchInput';
import SkeletonLoader from '../components/SkeletonLoader';
import { Button } from '../components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '../components/ui/dropdown-menu';
import { EmptyState } from '../components/ui/empty-state';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '../components/ui/select';
import { ToggleGroup, ToggleGroupItem } from '../components/ui/toggle-group';
import ConnectionDrawer from '../connectors/ConnectionDrawer';
import ConnectorCard from '../connectors/ConnectorCard';
import ConnectorIcon from '../connectors/ConnectorIcon';
import {
  loadConnectors,
  selectConnectorCatalog,
  selectConnectorsFailed,
  selectConnectorsLoaded,
} from '../connectors/connectorsSlice';
import { connectorDescription, connectorName } from '../connectors/i18n';
import type { ConnectorDefinition } from '../connectors/types';
import useConnectorLauncher, {
  type LaunchOptions,
} from '../connectors/useConnectorLauncher';
import { selectToken } from '../preferences/preferenceSlice';
import type { AppDispatch } from '../store';

const FILTERS = [
  'all',
  'connected',
  'files',
  'knowledge',
  'projects',
  'dev',
  'business',
  'messaging',
  'database',
  'search',
  'custom',
] as const;
type Filter = (typeof FILTERS)[number];

// Connected and needing attention first, then what can be connected, then
// what an admin still has to set up.
const STATE_ORDER: Record<ConnectorDefinition['state'], number> = {
  reconnect: 0,
  connected: 1,
  available: 2,
  custom: 3,
  needs_setup: 4,
  disabled: 5,
};

const isConnected = (connector: ConnectorDefinition) =>
  connector.connection_count > 0;

export default function Connectors() {
  const { t } = useTranslation();
  const dispatch = useDispatch<AppDispatch>();
  const token = useSelector(selectToken);
  const catalog = useSelector(selectConnectorCatalog);
  const loaded = useSelector(selectConnectorsLoaded);
  const failed = useSelector(selectConnectorsFailed);
  const [searchParams, setSearchParams] = useSearchParams();
  const [search, setSearch] = useState('');
  const initialFilter = searchParams.get('filter') as Filter | null;
  const [filter, setFilter] = useState<Filter>(
    initialFilter && FILTERS.includes(initialFilter) ? initialFilter : 'all',
  );
  const connectorParam = searchParams.get('connector');
  const [openKey, setOpenKey] = useState<string | null>(connectorParam);
  // A `?connector=` link followed while this page is already open (the
  // global Reconnect toast) changes only the search: open what it names.
  const [seenConnectorParam, setSeenConnectorParam] = useState(connectorParam);
  if (connectorParam !== seenConnectorParam) {
    setSeenConnectorParam(connectorParam);
    if (connectorParam) setOpenKey(connectorParam);
  }
  const { launch, modals } = useConnectorLauncher();

  useEffect(() => {
    dispatch(loadConnectors({ token }));
  }, [dispatch, token]);

  const custom = catalog.filter((c) => c.publisher === 'custom');
  // A link to a part (a tool's "Manage connection") opens its parent's page.
  const openTarget = catalog.find((c) => c.key === openKey);
  const openConnector =
    (openTarget?.part_of &&
      catalog.find((c) => c.key === openTarget.part_of)) ||
    openTarget ||
    null;

  // One service offered two ways (Confluence sync and the Jira & Confluence
  // MCP actions) is one card. A part is shown on its own only when its
  // parent is not listed (not set up, or turned off).
  const partsOf = (key: string) => catalog.filter((c) => c.part_of === key);
  const isShownUnderParent = (connector: ConnectorDefinition) =>
    !!connector.part_of && catalog.some((c) => c.key === connector.part_of);
  const merged = (connector: ConnectorDefinition): ConnectorDefinition => {
    const parts = partsOf(connector.key);
    if (parts.length === 0) return connector;
    const all = [connector, ...parts];
    const state = all.some((c) => c.state === 'reconnect')
      ? 'reconnect'
      : all.some((c) => c.state === 'connected')
        ? 'connected'
        : connector.state;
    return {
      ...connector,
      capabilities: Array.from(new Set(all.flatMap((c) => c.capabilities))),
      connection_count: all.reduce((n, c) => n + c.connection_count, 0),
      connected_count: all.reduce((n, c) => n + c.connected_count, 0),
      state,
    };
  };

  // "Connect more" in the composer opens the connectors that can do what the
  // picker is for: sync content, or give tools.
  const capability = searchParams.get('capability');
  const clearCapability = () => {
    searchParams.delete('capability');
    setSearchParams(searchParams, { replace: true });
  };
  // Listed for syncing (Knowledge's Connect a service, the sources picker's
  // Connect more): a connect starts with Sync into Knowledge on.
  const withPurpose = (options: LaunchOptions = {}): LaunchOptions =>
    capability === 'sync' ? { ...options, purpose: 'knowledge' } : options;

  // Only categories that have something in them once the composer's
  // capability filter applies (hidden connectors can empty one too), so no
  // pill leads to an empty page.
  const cards = catalog
    .filter((connector) => !isShownUnderParent(connector))
    .map(merged);
  const withCapability = cards.filter((connector) =>
    capability === 'sync'
      ? connector.capabilities.includes('sync')
      : capability === 'tools'
        ? connector.capabilities.some((c) => c !== 'sync')
        : true,
  );
  const filters = FILTERS.filter(
    (key) =>
      key === 'all' ||
      key === filter ||
      (key === 'connected'
        ? withCapability.some(isConnected)
        : withCapability.some((connector) => connector.category === key)),
  );

  const visible = useMemo(() => {
    const query = search.trim().toLowerCase();
    return withCapability
      .filter((connector) => {
        if (filter === 'connected') return isConnected(connector);
        if (filter !== 'all') return connector.category === filter;
        return true;
      })
      .filter(
        (connector) =>
          !query ||
          [connector, ...partsOf(connector.key)].some(
            (c) =>
              connectorName(t, c).toLowerCase().includes(query) ||
              connectorDescription(t, c).toLowerCase().includes(query),
          ),
      )
      .sort((a, b) => STATE_ORDER[a.state] - STATE_ORDER[b.state]);
  }, [withCapability, filter, search, t]);

  const open = (connector: ConnectorDefinition) => {
    const hasParts = partsOf(connector.key).length > 0;
    if (
      !hasParts &&
      (connector.state === 'available' || connector.state === 'custom')
    ) {
      launch(connector, withPurpose());
      return;
    }
    setOpenKey(connector.key);
  };

  const closeDrawer = () => {
    setOpenKey(null);
    if (searchParams.has('connector')) {
      searchParams.delete('connector');
      setSearchParams(searchParams, { replace: true });
    }
  };

  return (
    <div className="flex flex-col">
      <PageToolbar
        intro={t('settings.connectors.subtitle')}
        search={
          <SearchInput
            maxLength={256}
            label={t('settings.connectors.search')}
            id="connector-search-input"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        }
        action={
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button type="button" size="field" shape="pill">
                <Plus />
                {t('settings.connectors.addCustom')}
                <ChevronDown />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              {custom.map((connector) => (
                <DropdownMenuItem
                  key={connector.key}
                  onSelect={() => launch(connector)}
                >
                  <ConnectorIcon icon={connector.icon} className="size-4" />
                  {connectorName(t, connector)}
                </DropdownMenuItem>
              ))}
            </DropdownMenuContent>
          </DropdownMenu>
        }
      >
        <div className="mb-6 flex flex-col gap-3">
          {/* Nine pills wrap to four lines on a phone: a Select there. */}
          <ToggleGroup
            type="single"
            value={filter}
            onValueChange={(value) => value && setFilter(value as Filter)}
            aria-label={t('settings.connectors.categoriesLabel')}
            className="hidden sm:flex"
          >
            {filters.map((key) => (
              <ToggleGroupItem key={key} value={key}>
                {t(`settings.connectors.categories.${key}`)}
              </ToggleGroupItem>
            ))}
          </ToggleGroup>
          <div className="sm:hidden">
            <Select
              value={filter}
              onValueChange={(value) => setFilter(value as Filter)}
            >
              <SelectTrigger
                size="field"
                shape="pill"
                className="w-full"
                aria-label={t('settings.connectors.categoriesLabel')}
              >
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {filters.map((key) => (
                  <SelectItem key={key} value={key}>
                    {t(`settings.connectors.categories.${key}`)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          {(capability === 'sync' || capability === 'tools') && (
            <p className="text-muted-foreground text-sm">
              {t(`settings.connectors.capabilityFilter.${capability}`)}{' '}
              <Button
                type="button"
                variant="link"
                size="inline"
                onClick={clearCapability}
              >
                {t('settings.connectors.capabilityFilter.showAll')}
              </Button>
            </p>
          )}
        </div>
      </PageToolbar>

      {!loaded && !failed ? (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          <SkeletonLoader component="toolCards" count={8} />
        </div>
      ) : failed && catalog.length === 0 ? (
        <EmptyState
          tone="destructive"
          illustration="none"
          title={t('settings.connectors.loadFailed')}
          action={
            <Button
              variant="outline"
              size="sm"
              shape="pill"
              onClick={() => dispatch(loadConnectors({ token }))}
            >
              {t('retry')}
            </Button>
          }
        />
      ) : visible.length === 0 ? (
        filter === 'connected' && !search ? (
          <EmptyState title={t('settings.connectors.empty')} />
        ) : (
          <EmptyState
            size="xs"
            illustration="none"
            title={t('settings.connectors.noMatches')}
          />
        )
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {visible.map((connector) => (
            <ConnectorCard
              key={connector.key}
              connector={connector}
              onOpen={open}
            />
          ))}
        </div>
      )}

      <ConnectionDrawer
        connector={openConnector}
        parts={openConnector ? partsOf(openConnector.key) : []}
        onClose={closeDrawer}
        onConnect={(connector, options) => {
          closeDrawer();
          launch(connector, withPurpose(options));
        }}
      />
      {modals}
    </div>
  );
}
