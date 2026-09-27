import { Maximize, Minus, Plus, Redo2, Undo2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Panel, useReactFlow, useStore } from 'reactflow';

import { IconButton } from '@/components/ui/icon-button';
import { Separator } from '@/components/ui/separator';

interface CanvasControlsProps {
  onUndo: () => void;
  onRedo: () => void;
  canUndo: boolean;
  canRedo: boolean;
}

const ZOOM_DURATION_MS = 200;

/**
 * The canvas's one control strip, bottom left: undo and redo, then zoom out,
 * the zoom level, zoom in and fit view. Replaces React Flow's own
 * `<Controls />`, whose buttons ignore the theme. Render inside `<ReactFlow>`.
 */
export default function CanvasControls({
  onUndo,
  onRedo,
  canUndo,
  canRedo,
}: CanvasControlsProps) {
  const { t } = useTranslation();
  const { zoomIn, zoomOut, fitView } = useReactFlow();
  const zoom = useStore((state) => state.transform[2]);

  return (
    <Panel
      position="bottom-left"
      className="bg-card border-border flex items-center gap-0.5 rounded-full border p-1"
    >
      <IconButton
        variant="ghost-muted"
        size="icon-sm"
        shape="pill"
        onClick={onUndo}
        disabled={!canUndo}
        label={t('agents.workflow.undo')}
        hint={t('agents.workflow.undoHint')}
        icon={Undo2}
      />
      <IconButton
        variant="ghost-muted"
        size="icon-sm"
        shape="pill"
        onClick={onRedo}
        disabled={!canRedo}
        label={t('agents.workflow.redo')}
        hint={t('agents.workflow.redoHint')}
        icon={Redo2}
      />
      <Separator orientation="vertical" className="mx-1 h-5" />
      <IconButton
        variant="ghost-muted"
        size="icon-sm"
        shape="pill"
        onClick={() => zoomOut({ duration: ZOOM_DURATION_MS })}
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
        onClick={() => zoomIn({ duration: ZOOM_DURATION_MS })}
        label={t('agents.workflow.zoomIn')}
        icon={Plus}
      />
      <IconButton
        variant="ghost-muted"
        size="icon-sm"
        shape="pill"
        onClick={() =>
          fitView({ padding: 0.2, maxZoom: 0.8, duration: ZOOM_DURATION_MS })
        }
        label={t('agents.workflow.fitView')}
        icon={Maximize}
      />
    </Panel>
  );
}
