import { ChevronDown } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';
import { useSearchParams } from 'react-router-dom';

import PageToolbar from '../components/PageToolbar';
import SearchInput from '../components/SearchInput';
import SkeletonLoader from '../components/SkeletonLoader';
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import { ActionMenu } from '../components/ui/dropdown-menu';
import { EmptyState } from '../components/ui/empty-state';
import { ToggleGroup, ToggleGroupItem } from '../components/ui/toggle-group';
import ConnectionDrawer from '../connectors/ConnectionDrawer';
import ConnectorCard from '../connectors/ConnectorCard';
import ConnectorIcon from '../connectors/ConnectorIcon';
import {
  byState,
  catalogCards,
  partsOf as partsOfCatalog,
} from '../connectors/catalogCards';
import {
  connectionNeedsSignIn,
  loadConnectors,
  selectConnections,
  selectConnectorCatalog,
  selectConnectorsFailed,
  selectConnectorsLoaded,
} from '../connectors/connectorsSlice';
import { connectorDescription, connectorName } from '../connectors/i18n';
import type { Connection, ConnectorDefinition } from '../connectors/types';
import useConnectorLauncher, {
  type LaunchOptions,
} from '../connectors/useConnectorLauncher';
import { selectToken } from '../preferences/preferenceSlice';
import type { AppDispatch } from '../store';

// What people come here for is managing what they have, so the list filters
// by state; search finds a service by name.
const FILTERS = ['all', 'connected', 'disconnected'] as const;
type Filter = (typeof FILTERS)[number];

/** A card's own accounts: the service's and its parts'. */
const accountsOf = (connections: Connection[], keys: string[]): Connection[] =>
  connections.filter((c) => keys.includes(c.connector_key));

/** At least one account works. */
const hasWorking = (connector: ConnectorDefinition, accounts: Connection[]) =>
  accounts.some((c) => c.status === 'connected') ||
  connector.connected_count > 0;

/** An account needs signing in again, or was disconnected. */
const hasBroken = (connector: ConnectorDefinition, accounts: Connection[]) =>
  accounts.some(
    (c) => connectionNeedsSignIn(c) || c.status === 'disconnected',
  ) || connector.state === 'reconnect';

export default function Connectors() {
  const { t } = useTranslation();
  const dispatch = useDispatch<AppDispatch>();
  const token = useSelector(selectToken);
  const catalog = useSelector(selectConnectorCatalog);
  const loaded = useSelector(selectConnectorsLoaded);
  const failed = useSelector(selectConnectorsFailed);
  const [searchParams, setSearchParams] = useSearchParams();
  const [search, setSearch] = useState('');
  const connections = useSelector(selectConnections);
  const filterParam = searchParams.get('filter') as Filter | null;
  // The address holds the filter, so Back and a reload keep it.
  const filter: Filter =
    filterParam && FILTERS.includes(filterParam) ? filterParam : 'all';
  const setFilter = (value: Filter) => {
    if (value === 'all') searchParams.delete('filter');
    else searchParams.set('filter', value);
    setSearchParams(searchParams, { replace: true });
  };
  const connectorParam = searchParams.get('connector');
  const [openKey, setOpenKey] = useState<string | null>(connectorParam);
  // A `?connector=` link followed while this page is already open (the
  // global Reconnect toast) changes only the search: open what it names.
  const [seenConnectorParam, setSeenConnectorParam] = useState(connectorParam);
  if (connectorParam !== seenConnectorParam) {
    setSeenConnectorParam(connectorParam);
    if (connectorParam) setOpenKey(connectorParam);
  }
  // The account to open the drawer on (a tool's "Manage in Connectors").
  const connectionParam = searchParams.get('connection') ?? undefined;
  const { launch, modals } = useConnectorLauncher();

  useEffect(() => {
    dispatch(loadConnectors({ token }));
  }, [dispatch, token]);

  const custom = catalog.filter((c) => c.publisher === 'custom');
  // A `?connector=` link to a part (a Reconnect that can't happen in place)
  // opens its parent's page.
  const openTarget = catalog.find((c) => c.key === openKey);
  const openConnector =
    (openTarget?.part_of &&
      catalog.find((c) => c.key === openTarget.part_of)) ||
    openTarget ||
    null;

  const partsOf = (key: string) => partsOfCatalog(catalog, key);

  // `?capability=` narrows the list to connectors that can sync content, or
  // give tools.
  const capability = searchParams.get('capability');
  const clearCapability = () => {
    searchParams.delete('capability');
    setSearchParams(searchParams, { replace: true });
  };
  // Listed for syncing (Knowledge's Connect a service, Add knowledge's Browse
  // all connectors): a connect starts with Sync into Knowledge on.
  const withPurpose = (options: LaunchOptions = {}): LaunchOptions =>
    capability === 'sync' ? { ...options, purpose: 'knowledge' } : options;

  const cards = catalogCards(catalog);
  const withCapability = cards.filter((connector) =>
    capability === 'sync'
      ? connector.capabilities.includes('sync')
      : capability === 'tools'
        ? connector.capabilities.some((c) => c !== 'sync')
        : true,
  );
  const keysOf = (connector: ConnectorDefinition) => [
    connector.key,
    ...partsOf(connector.key).map((part) => part.key),
  ];
  const matches = (connector: ConnectorDefinition, key: Filter) => {
    if (key === 'all') return true;
    const accounts = accountsOf(connections, keysOf(connector));
    return key === 'connected'
      ? hasWorking(connector, accounts)
      : hasBroken(connector, accounts);
  };
  const counts = Object.fromEntries(
    FILTERS.map((key) => [
      key,
      withCapability.filter((connector) => matches(connector, key)).length,
    ]),
  ) as Record<Filter, number>;
  // No pill leads to an empty list; with only All left there is no row.
  const filters = FILTERS.filter(
    (key) => key === 'all' || key === filter || counts[key] > 0,
  );

  const visible = useMemo(() => {
    const query = search.trim().toLowerCase();
    return withCapability
      .filter((connector) => matches(connector, filter))
      .filter(
        (connector) =>
          !query ||
          [connector, ...partsOf(connector.key)].some(
            (c) =>
              connectorName(t, c).toLowerCase().includes(query) ||
              connectorDescription(t, c).toLowerCase().includes(query),
          ),
      )
      .sort(byState);
  }, [withCapability, filter, search, t, connections]);

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
    if (searchParams.has('connector') || searchParams.has('connection')) {
      searchParams.delete('connector');
      searchParams.delete('connection');
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
          <ActionMenu
            trigger={
              <Button type="button" size="field" shape="pill">
                {t('settings.connectors.addCustom')}
                <ChevronDown />
              </Button>
            }
            menuWidth="sm"
            options={custom.map((connector) => ({
              label: connectorName(t, connector),
              icon: <ConnectorIcon icon={connector.icon} className="size-4" />,
              onClick: () => launch(connector),
            }))}
          />
        }
        divider
      >
        {filters.length > 1 ||
        capability === 'sync' ||
        capability === 'tools' ? (
          <div className="mb-6 flex flex-wrap items-center gap-3">
            {filters.length > 1 ? (
              <ToggleGroup
                type="single"
                value={filter}
                onValueChange={(value) => value && setFilter(value as Filter)}
                aria-label={t('settings.connectors.filterLabel')}
              >
                {filters.map((key) => (
                  <ToggleGroupItem key={key} value={key} count={counts[key]}>
                    {t(`settings.connectors.filters.${key}`)}
                  </ToggleGroupItem>
                ))}
              </ToggleGroup>
            ) : null}
            {capability === 'sync' || capability === 'tools' ? (
              <Badge
                onRemove={clearCapability}
                removeLabel={t('settings.connectors.capabilityFilter.clear')}
              >
                {t(`settings.connectors.capabilityChip.${capability}`)}
              </Badge>
            ) : null}
          </div>
        ) : null}
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
          onRetry={() => dispatch(loadConnectors({ token }))}
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
        initialConnectionId={connectionParam}
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
