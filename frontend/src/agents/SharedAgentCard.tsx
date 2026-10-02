import { useTranslation } from 'react-i18next';
import { Pencil } from 'lucide-react';

import ToolIcon from '../components/ToolIcon';
import { Avatar } from '../components/ui/avatar';
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import { Card } from '../components/ui/card';
import { IconButton } from '../components/ui/icon-button';
import { formatDateTime } from '../utils/dateTimeUtils';
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
    <Card
      variant="filled"
      padding="lg"
      className="w-full max-w-[720px] sm:w-fit sm:min-w-[480px]"
    >
      <div className="flex items-start gap-3">
        <div className="flex size-12 items-center justify-center overflow-hidden rounded-full p-1">
          <Avatar
            src={agent.image}
            alt={agent.name}
            shape="circle"
            className="size-full overflow-hidden"
            imgClassName="size-full object-contain"
          />
        </div>
        <div className="flex min-w-0 flex-1 flex-col gap-1">
          <h2 className="text-foreground text-base leading-snug font-semibold wrap-break-word sm:text-lg">
            {agent.name}
          </h2>
          <p
            className="text-muted-foreground line-clamp-3 text-xs leading-relaxed wrap-break-word sm:text-sm"
            title={agent.description}
          >
            {agent.description}
          </p>
        </div>
        {onEdit && (
          <>
            {/* A phone has no room for a long localised label beside the name. */}
            <IconButton
              label={t('agents.edit')}
              icon={Pencil}
              variant="outline"
              size="icon-sm"
              shape="pill"
              onClick={onEdit}
              className="shrink-0 sm:hidden"
            />
            <Button
              type="button"
              variant="outline"
              size="sm"
              shape="pill"
              onClick={onEdit}
              className="hidden shrink-0 sm:inline-flex"
            >
              <Pencil />
              {t('agents.edit')}
            </Button>
          </>
        )}
      </div>
      {hasSharedMetadata && (
        <div className="mt-1 flex items-center gap-8">
          {agent.shared_metadata?.shared_by && (
            <p className="text-foreground text-xs font-light sm:text-sm">
              {t('agents.shared.sharedBy', {
                name: agent.shared_metadata.shared_by,
                interpolation: { escapeValue: false },
              })}
            </p>
          )}
          {agent.shared_metadata?.shared_at && (
            <p className="text-muted-foreground text-xs font-light sm:text-sm">
              {t('agents.shared.sharedOn', {
                date: formatDateTime(agent.shared_metadata.shared_at),
                interpolation: { escapeValue: false },
              })}
            </p>
          )}
        </div>
      )}
      {agent.tool_details && agent.tool_details.length > 0 && (
        <div className="mt-5">
          <p className="text-foreground text-sm font-semibold sm:text-base">
            {t('agents.shared.connectedTools')}
          </p>
          <div className="mt-2 flex flex-wrap gap-2">
            {agent.tool_details.map((tool, index) => (
              <Badge key={index} variant="default">
                <ToolIcon
                  name={tool.name}
                  title={t('agents.shared.toolIconTitle', {
                    name: getToolDisplayName(tool),
                    interpolation: { escapeValue: false },
                  })}
                  className="size-3"
                />{' '}
                {getToolDisplayName(tool)}
              </Badge>
            ))}
          </div>
        </div>
      )}
    </Card>
  );
}
