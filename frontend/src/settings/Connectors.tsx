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
import useConnectorLauncher from '../connectors/useConnectorLauncher';
import { selectToken } from '../preferences/preferenceSlice';
import type { AppDispatch } from '../store';

const FILTERS = [
  'all',
  'connected',
  'files',
  'knowledge',
  'dev',
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
  const [openKey, setOpenKey] = useState<string | null>(
    searchParams.get('connector'),
  );
  const { launch, modals } = useConnectorLauncher();

  useEffect(() => {
    dispatch(loadConnectors({ token }));
  }, [dispatch, token]);

  const custom = catalog.filter((c) => c.publisher === 'custom');
  const openConnector = catalog.find((c) => c.key === openKey) ?? null;

  const visible = useMemo(() => {
    const query = search.trim().toLowerCase();
    return catalog
      .filter((connector) => {
        if (filter === 'connected') return isConnected(connector);
        if (filter !== 'all') return connector.category === filter;
        return true;
      })
      .filter(
        (connector) =>
          !query ||
          connectorName(t, connector).toLowerCase().includes(query) ||
          connectorDescription(t, connector).toLowerCase().includes(query),
      )
      .sort((a, b) => STATE_ORDER[a.state] - STATE_ORDER[b.state]);
  }, [catalog, filter, search, t]);

  const open = (connector: ConnectorDefinition) => {
    if (connector.state === 'available' || connector.state === 'custom') {
      launch(connector);
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
        <ToggleGroup
          type="single"
          value={filter}
          onValueChange={(value) => value && setFilter(value as Filter)}
          aria-label={t('settings.connectors.categoriesLabel')}
          className="mb-6"
        >
          {FILTERS.map((key) => (
            <ToggleGroupItem key={key} value={key}>
              {t(`settings.connectors.categories.${key}`)}
            </ToggleGroupItem>
          ))}
        </ToggleGroup>
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
              onClick={() => dispatch(loadConnectors({ token }))}
            >
              {t('retry')}
            </Button>
          }
        />
      ) : visible.length === 0 ? (
        <EmptyState
          title={
            filter === 'connected' && !search
              ? t('settings.connectors.empty')
              : t('settings.connectors.noMatches')
          }
        />
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
        onClose={closeDrawer}
        onConnect={(connector, options) => {
          closeDrawer();
          launch(connector, options);
        }}
      />
      {modals}
    </div>
  );
}
