import { Monitor } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import { EmptyState } from '@/components/ui/empty-state';

import { BackLink } from '../../../navigation/SectionPageHeader';
import { AGENTS_MANAGE_ROOT } from '../../paths';

/**
 * Stands in for the builder below ``lg``. Keeps the agent pages' "← Agents"
 * link so the way back doesn't go through the sidebar.
 */
export default function MobileBlocker() {
  const { t } = useTranslation();
  return (
    // h-full, not h-dvh: the page area already sits under the 56px top bar.
    <div className="bg-background flex h-full flex-col p-4 lg:hidden">
      <BackLink to={AGENTS_MANAGE_ROOT} className="self-start">
        {t('agents.title')}
      </BackLink>
      <div className="flex flex-1 flex-col justify-center">
        <EmptyState
          icon={Monitor}
          title={t('agents.workflow.mobileBlocker.title')}
          description={t('agents.workflow.mobileBlocker.body')}
        />
      </div>
    </div>
  );
}
