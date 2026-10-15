import { Monitor } from 'lucide-react';
import { useTranslation } from 'react-i18next';

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
      <div className="flex flex-1 flex-col items-center justify-center px-2 text-center">
        <div className="bg-secondary mb-6 flex size-20 items-center justify-center rounded-2xl">
          <Monitor className="text-primary size-10" />
        </div>
        <h2 className="text-foreground mb-2 text-xl leading-tight font-semibold">
          {t('agents.workflow.mobileBlocker.title')}
        </h2>
        <p className="text-muted-foreground max-w-sm text-sm leading-relaxed">
          {t('agents.workflow.mobileBlocker.body')}
        </p>
      </div>
    </div>
  );
}
