import { useTranslation } from 'react-i18next';

import EditIcon from '../assets/edit.svg';
import AgentImage from '../components/AgentImage';
import { getToolDisplayName } from '../utils/toolUtils';
import { Agent } from './types';

export default function SharedAgentCard({
  agent,
  onEdit,
}: {
  agent: Agent;
  onEdit?: () => void;
}) {
  const { t } = useTranslation();
  // Check if shared metadata exists and has properties (type is 'any' so we validate it's a non-empty object)
  const hasSharedMetadata =
    agent.shared_metadata &&
    typeof agent.shared_metadata === 'object' &&
    agent.shared_metadata !== null &&
    Object.keys(agent.shared_metadata).length > 0;
  return (
    <div className="border-border dark:border-border flex w-full max-w-[720px] flex-col rounded-3xl border p-6 shadow-xs sm:w-fit sm:min-w-[480px]">
      <div className="flex items-start gap-3">
        <div className="flex h-12 w-12 items-center justify-center overflow-hidden rounded-full p-1">
          <AgentImage
            src={agent.image}
            className="h-full w-full rounded-full object-contain"
          />
        </div>
        <div className="flex max-h-[92px] flex-1 flex-col gap-px">
          <h2 className="text-foreground text-base font-semibold sm:text-lg">
            {agent.name}
          </h2>
          <p className="text-muted-foreground overflow-y-auto text-xs text-wrap break-all sm:text-sm">
            {agent.description}
          </p>
        </div>
        {onEdit && (
          <button
            type="button"
            onClick={onEdit}
            className="border-border hover:bg-accent text-foreground flex shrink-0 items-center gap-1.5 rounded-full border px-3 py-1.5 text-sm font-medium transition-colors"
            aria-label={t('agents.edit')}
          >
            <img src={EditIcon} alt="" className="h-3.5 w-3.5" />
            {t('agents.edit')}
          </button>
        )}
      </div>
      {hasSharedMetadata && (
        <div className="mt-4 flex items-center gap-8">
          {agent.shared_metadata?.shared_by && (
            <p className="text-foreground text-xs font-light sm:text-sm">
              by {agent.shared_metadata.shared_by}
            </p>
          )}
          {agent.shared_metadata?.shared_at && (
            <p className="text-muted-foreground text-xs font-light sm:text-sm">
              Shared on{' '}
              {new Date(agent.shared_metadata.shared_at).toLocaleString(
                'en-US',
                {
                  month: 'long',
                  day: 'numeric',
                  year: 'numeric',
                  hour: '2-digit',
                  minute: '2-digit',
                  hour12: true,
                },
              )}
            </p>
          )}
        </div>
      )}
      {agent.tool_details && agent.tool_details.length > 0 && (
        <div className="mt-8">
          <p className="text-foreground text-sm font-semibold sm:text-base">
            Connected Tools
          </p>
          <div className="mt-2 flex flex-wrap gap-2">
            {agent.tool_details.map((tool, index) => (
              <span
                key={index}
                className="bg-accent text-foreground dark:bg-card flex items-center gap-1 rounded-full px-3 py-1 text-xs font-light"
              >
                <img
                  src={`/toolIcons/tool_${tool.name}.svg`}
                  alt={`${getToolDisplayName(tool)} icon`}
                  className="h-3 w-3"
                />{' '}
                {getToolDisplayName(tool)}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
