import { useTranslation } from 'react-i18next';

import { Badge } from '@/components/ui/badge';
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import { cn, focusRing } from '@/lib/utils';

import { formatCount } from '../../utils/dateTimeUtils';

type TierBadgeProps = {
  tier: 'estimated' | 'experimental';
  /** Half the panel's widest range, in percentage points (estimated only). */
  points?: number;
};

/**
 * The badge beside a panel title whose figures are less certain than the
 * headline ones. It marks uncertainty, not quality, and its tooltip (on
 * hover and on keyboard focus) says how much.
 */
export default function TierBadge({ tier, points }: TierBadgeProps) {
  const { t } = useTranslation();
  const hint =
    tier === 'experimental'
      ? t('settings.analytics.insights.tiers.experimentalHint')
      : points !== undefined
        ? t('settings.analytics.insights.tiers.estimatedHint', {
            points: formatCount(points),
          })
        : t('settings.analytics.insights.tiers.estimatedHintPlain');
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Badge
          asChild
          variant={tier === 'experimental' ? 'warning' : 'neutral'}
        >
          <button
            type="button"
            className={cn(focusRing, 'cursor-help outline-none')}
          >
            {t(`settings.analytics.insights.tiers.${tier}`)}
          </button>
        </Badge>
      </TooltipTrigger>
      <TooltipContent>{hint}</TooltipContent>
    </Tooltip>
  );
}
