import { Maximize, Minus, Plus } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import { IconButton } from '../ui/icon-button';

interface GraphCanvasControlsProps {
  /** The current zoom factor (1 = 100%). */
  zoom: number;
  onZoomIn: () => void;
  onZoomOut: () => void;
  onFit: () => void;
}

/**
 * The graph canvas's control strip, bottom left: zoom out, the zoom level,
 * zoom in, then fit view. The workflow builder's `CanvasControls` recipe
 * without React Flow.
 */
export default function GraphCanvasControls({
  zoom,
  onZoomIn,
  onZoomOut,
  onFit,
}: GraphCanvasControlsProps) {
  const { t } = useTranslation();

  return (
    <div className="bg-card border-border absolute bottom-3 left-3 flex items-center gap-0.5 rounded-full border p-1">
      <IconButton
        variant="ghost-muted"
        size="icon-sm"
        shape="pill"
        onClick={onZoomOut}
        label={t('agents.workflow.zoomOut')}
        icon={Minus}
      />
      <span className="text-foreground w-11 text-center text-xs tabular-nums">
        {Math.round(zoom * 100)}%
      </span>
      <IconButton
        variant="ghost-muted"
        size="icon-sm"
        shape="pill"
        onClick={onZoomIn}
        label={t('agents.workflow.zoomIn')}
        icon={Plus}
      />
      <IconButton
        variant="ghost-muted"
        size="icon-sm"
        shape="pill"
        onClick={onFit}
        label={t('agents.workflow.fitView')}
        icon={Maximize}
      />
    </div>
  );
}
