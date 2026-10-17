import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';

import { selectConnectionsNeedAttention } from './connectorsSlice';

/**
 * A warning dot on the nav entries that lead to Connectors while a
 * connection needs signing in again. Unlike the reconnect toast it does not
 * expire, so the signal stays until the connection is fixed.
 */
export default function ConnectionHealthDot() {
  const { t } = useTranslation();
  const needsAttention = useSelector(selectConnectionsNeedAttention);
  if (!needsAttention) return null;
  return (
    <span
      data-testid="connection-health-dot"
      role="img"
      aria-label={t('settings.connectors.health.navDot')}
      className="bg-warning ml-auto size-2 shrink-0 rounded-full"
    />
  );
}
