import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import {
  PanelBody,
  PanelFooter,
  PanelHeader,
  SidePanel,
} from '@/components/ui/side-panel';

/**
 * App recipe for the /design gallery: modal SidePanel at both sizes, populated like a run-details panel.
 * Rendered in place by its section; a candidate to cut from the system demos.
 */
export default function RunDetailsPanelDemo() {
  const [modalPanel, setModalPanel] = useState<'default' | 'wide' | null>(null);
  return (
    <>
      {(['default', 'wide'] as const).map((size) => (
        <Button
          key={size}
          variant="outline"
          onClick={() => setModalPanel(size)}
        >
          Modal panel · {size}
        </Button>
      ))}
      <SidePanel
        open={modalPanel !== null}
        onOpenChange={(open) => !open && setModalPanel(null)}
        size={modalPanel ?? 'default'}
      >
        <PanelHeader
          title="Run details"
          description={`variant="modal" size="${modalPanel ?? 'default'}": a form, one record or a preview, over the blurred scrim.`}
        />
        <PanelBody>
          <Card variant="subtle" padding="lg">
            <p className="text-muted-foreground text-sm">
              Panels in a side panel are subtle; the body is the one scroller.
            </p>
          </Card>
        </PanelBody>
        <PanelFooter>
          <Button
            variant="ghost"
            size="lg"
            shape="pill"
            onClick={() => setModalPanel(null)}
          >
            Cancel
          </Button>
          <Button size="lg" shape="pill" onClick={() => setModalPanel(null)}>
            Save
          </Button>
        </PanelFooter>
      </SidePanel>
    </>
  );
}
