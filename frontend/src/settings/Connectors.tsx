import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';
import { useSearchParams } from 'react-router-dom';

import FilterSelect from '../components/FilterSelect';
import PageToolbar from '../components/PageToolbar';
import SearchInput from '../components/SearchInput';
import SkeletonLoader from '../components/SkeletonLoader';
import { Button } from '../components/ui/button';
import { EmptyState } from '../components/ui/empty-state';
import { SectionHeader } from '../components/ui/section-header';
import { ToggleGroup, ToggleGroupItem } from '../components/ui/toggle-group';
import ConnectionDrawer from '../connectors/ConnectionDrawer';
import ConnectorCard from '../connectors/ConnectorCard';
import AddCustomConnectorModal from '../connectors/AddCustomConnectorModal';
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
import { shownFilters, useUrlFilter } from '../hooks/useUrlFilter';
import { selectToken } from '../preferences/preferenceSlice';
import type { AppDispatch } from '../store';

// The kind track is what a service does (the Knowledge / Tools split the
// Add knowledge and Tools pages link to with ?capability=); the status
// Select and the sections are what the reader has. Search finds a service
// by name.
const CAPABILITIES = ['all', 'sync', 'tools'] as const;
type CapabilityFilter = (typeof CAPABILITIES)[number];
const STATUSES = ['all', 'reconnect', 'connected', 'available'] as const;
type StatusFilter = (typeof STATUSES)[number];
type Status = Exclude<StatusFilter, 'all'>;
/** The page's sections, in order: what needs the reader first. */
const SECTIONS: Status[] = ['reconnect', 'connected', 'available'];

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
  // The address holds both filters, so Back and a reload keep them.
  const [capability, setCapability] = useUrlFilter(CAPABILITIES, {
    name: 'capability',
  });
  const [status, setStatus] = useUrlFilter(STATUSES, { name: 'status' });
  const connectorParam = searchParams.get('connector');
  const [openKey, setOpenKey] = useState<string | null>(connectorParam);
  const [choosingCustom, setChoosingCustom] = useState(false);
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

  // Listed for syncing (Add knowledge's Browse all connectors): a connect
  // starts with Sync into Knowledge on (sync-only connectors always do).
  const withPurpose = (options: LaunchOptions = {}): LaunchOptions =>
    capability === 'sync' ? { ...options, purpose: 'knowledge' } : options;

  const cards = catalogCards(catalog);
  const matchesCapability = (
    connector: ConnectorDefinition,
    key: CapabilityFilter,
  ) =>
    key === 'sync'
      ? connector.capabilities.includes('sync')
      : key === 'tools'
        ? connector.capabilities.some((c) => c !== 'sync')
        : true;
  const keysOf = (connector: ConnectorDefinition) => [
    connector.key,
    ...partsOf(connector.key).map((part) => part.key),
  ];
  /** Needs sign-in when an account broke, else Connected, else Available. */
  const statusOf = (connector: ConnectorDefinition): Status => {
    const accounts = accountsOf(connections, keysOf(connector));
    if (hasBroken(connector, accounts)) return 'reconnect';
    return hasWorking(connector, accounts) ? 'connected' : 'available';
  };
  const matchesStatus = (connector: ConnectorDefinition, key: StatusFilter) =>
    key === 'all' || statusOf(connector) === key;
  // Each filter counts with the other one applied.
  const capabilityCounts = Object.fromEntries(
    CAPABILITIES.map((key) => [
      key,
      cards.filter((c) => matchesStatus(c, status) && matchesCapability(c, key))
        .length,
    ]),
  ) as Record<CapabilityFilter, number>;
  const statusCounts = Object.fromEntries(
    STATUSES.map((key) => [
      key,
      cards.filter(
        (c) => matchesCapability(c, capability) && matchesStatus(c, key),
      ).length,
    ]),
  ) as Record<StatusFilter, number>;
  // No pill leads to an empty list; with only All left there is no track.
  const capabilities = shownFilters(CAPABILITIES, capability, capabilityCounts);

  const visible = useMemo(() => {
    const query = search.trim().toLowerCase();
    return cards
      .filter((connector) => matchesCapability(connector, capability))
      .filter((connector) => matchesStatus(connector, status))
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
  }, [cards, capability, status, search, t, connections]);
  const sections = SECTIONS.map((key) => ({
    key,
    connectors: visible.filter((connector) => statusOf(connector) === key),
  })).filter((section) => section.connectors.length > 0);

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
          custom.length > 0 ? (
            <Button
              type="button"
              size="field"
              shape="pill"
              onClick={() => setChoosingCustom(true)}
            >
              {t('settings.connectors.addCustom')}
            </Button>
          ) : undefined
        }
        divider
      >
        {loaded && cards.length > 0 ? (
          <div className="mb-6 flex flex-wrap items-center gap-3 empty:hidden">
            {capabilities.length > 0 ? (
              <ToggleGroup
                type="single"
                value={capability}
                onValueChange={(value) =>
                  value && setCapability(value as CapabilityFilter)
                }
                aria-label={t('settings.connectors.capabilityFilterLabel')}
              >
                {capabilities.map((key) => (
                  <ToggleGroupItem
                    key={key}
                    value={key}
                    count={capabilityCounts[key]}
                  >
                    {t(`settings.connectors.capabilityFilters.${key}`)}
                  </ToggleGroupItem>
                ))}
              </ToggleGroup>
            ) : null}
            <FilterSelect
              value={status}
              onValueChange={setStatus}
              values={STATUSES}
              counts={statusCounts}
              labelOf={(value) =>
                t(`settings.connectors.statusFilters.${value}`)
              }
              ariaLabel={t('settings.connectors.statusFilterLabel')}
            />
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
        status === 'connected' && !search ? (
          <EmptyState title={t('settings.connectors.empty')} />
        ) : (
          <EmptyState
            size="xs"
            illustration="none"
            title={t('settings.connectors.noMatches')}
          />
        )
      ) : (
        <div className="flex flex-col gap-8">
          {sections.map((section) => (
            <section key={section.key} className="flex flex-col gap-3">
              <SectionHeader
                size="sm"
                title={t(`settings.connectors.sections.${section.key}`)}
                count={section.connectors.length}
              />
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
                {section.connectors.map((connector) => (
                  <ConnectorCard
                    key={connector.key}
                    connector={connector}
                    onOpen={open}
                    // The section says Connected; a pill on every tile
                    // would only repeat it.
                    connectedBadge={false}
                  />
                ))}
              </div>
            </section>
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
      <AddCustomConnectorModal
        open={choosingCustom}
        onOpenChange={setChoosingCustom}
        connectors={custom}
        onPick={(connector) => launch(connector)}
      />
    </div>
  );
}
