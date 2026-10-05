import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { PanelBody, PanelHeader, SidePanel } from '@/components/ui/side-panel';

/**
 * App recipe for the /design gallery: a docked SidePanel beside live page content.
 * Rendered in place by its section; a candidate to cut from the system demos.
 */
export default function DockedPanelDemo() {
  const [dockedPanelOpen, setDockedPanelOpen] = useState(true);
  return (
    <div className="relative flex h-96 overflow-hidden rounded-xl border">
      <div className="flex min-w-0 flex-1 flex-col items-start gap-3 p-6">
        <p className="text-muted-foreground text-sm">
          The page stays live beside a docked panel: no scrim. Expand steps
          compact, half and full.
        </p>
        {!dockedPanelOpen ? (
          <Button variant="outline" onClick={() => setDockedPanelOpen(true)}>
            Open docked panel
          </Button>
        ) : null}
      </div>
      <SidePanel
        variant="docked"
        expandable="design-demo"
        open={dockedPanelOpen}
        onOpenChange={setDockedPanelOpen}
      >
        <PanelHeader
          title="renewal-note-dana.md"
          description="Note · updated just now"
        />
        <PanelBody>
          <p className="text-sm leading-6">
            The Halvorsen MSA auto-renews for 24 months unless notice is given
            by 3 August.
          </p>
        </PanelBody>
      </SidePanel>
    </div>
  );
}
