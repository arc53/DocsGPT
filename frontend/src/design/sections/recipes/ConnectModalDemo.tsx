import { GitBranch } from 'lucide-react';
import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Modal, ModalActions } from '@/components/ui/modal';

/**
 * App recipe for the /design gallery: the connect-wizard opener: a lg Modal with a leading brand tile.
 * Rendered in place by its section; a candidate to cut from the system demos.
 */
export default function ConnectModalDemo() {
  const [leadingOpen, setLeadingOpen] = useState(false);
  return (
    <>
      <Button variant="outline" onClick={() => setLeadingOpen(true)}>
        Modal with leading
      </Button>
      <Modal
        open={leadingOpen}
        onOpenChange={setLeadingOpen}
        size="lg"
        title="Connect GitHub"
        description="Sync repositories into Knowledge and let agents read code, issues and pull requests."
        leading={
          <span className="bg-muted flex size-12 shrink-0 items-center justify-center rounded-xl">
            <GitBranch className="size-6" />
          </span>
        }
        footer={
          <ModalActions
            cancelLabel="Cancel"
            onCancel={() => setLeadingOpen(false)}
            submitLabel="Connect"
            onSubmit={() => setLeadingOpen(false)}
          />
        }
      >
        <Input label="Personal access token" />
      </Modal>
    </>
  );
}
