import { useTranslation } from 'react-i18next';

import { Modal } from '../components/ui/modal';
import { OptionCard } from '../components/ui/option-card';
import ConnectorIcon from './ConnectorIcon';
import { connectorDescription, connectorName } from './i18n';
import type { ConnectorDefinition } from './types';

type AddCustomConnectorModalProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** The catalog's custom kinds (MCP server, OpenAPI / REST). */
  connectors: ConnectorDefinition[];
  /** Starts setting up the kind picked; the chooser closes first. */
  onPick: (connector: ConnectorDefinition) => void;
};

/**
 * The Connectors page's "Add custom connector" chooser: one option card per
 * custom kind, with its icon, name and what it connects, the way New agent
 * chooses between an agent and a workflow.
 */
export default function AddCustomConnectorModal({
  open,
  onOpenChange,
  connectors,
  onPick,
}: AddCustomConnectorModalProps) {
  const { t } = useTranslation();
  return (
    <Modal
      open={open}
      onOpenChange={onOpenChange}
      title={t('settings.connectors.addCustom')}
      description={t('settings.connectors.addCustomDescription')}
    >
      <div className="flex flex-col gap-4">
        {connectors.map((connector) => (
          <OptionCard
            key={connector.key}
            icon={<ConnectorIcon icon={connector.icon} />}
            title={connectorName(t, connector)}
            description={connectorDescription(t, connector)}
            onClick={() => {
              onOpenChange(false);
              onPick(connector);
            }}
          />
        ))}
      </div>
    </Modal>
  );
}
