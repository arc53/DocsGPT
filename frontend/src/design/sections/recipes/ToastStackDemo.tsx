import { ChevronDown, X } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  Toast,
  ToastActions,
  ToastContent,
  ToastFooter,
  ToastHeader,
  ToastItem,
  ToastMessage,
  ToastStatus,
  ToastTitle,
} from '@/components/ui/toast';

/**
 * App recipe for the /design gallery: a stack of real-looking toasts: upload, approval, team, sync, model.
 * Rendered in place by its section; a candidate to cut from the system demos.
 */
export default function ToastStackDemo() {
  return (
    <div className="bg-muted/40 flex flex-wrap items-start gap-4 rounded-xl p-6">
      <Toast>
        <ToastHeader variant="destructive">
          <ToastTitle>Upload failed</ToastTitle>
          <ToastActions>
            <Button size="icon-sm" variant="ghost-muted" aria-label="Collapse">
              <ChevronDown />
            </Button>
            <Button size="icon-sm" variant="ghost-muted" aria-label="Dismiss">
              <X />
            </Button>
          </ToastActions>
        </ToastHeader>
        <ToastContent>
          <ToastItem label="🦖1.png">
            <ToastStatus status="destructive" />
          </ToastItem>
          <ToastMessage variant="destructive">
            No text could be extracted from this file. It may be empty,
            image-only, or in an unsupported format.
          </ToastMessage>
        </ToastContent>
      </Toast>
      <Toast>
        <ToastHeader>
          <ToastTitle>Upload completed</ToastTitle>
          <ToastActions>
            <Button size="icon-sm" variant="ghost-muted" aria-label="Collapse">
              <ChevronDown />
            </Button>
            <Button size="icon-sm" variant="ghost-muted" aria-label="Dismiss">
              <X />
            </Button>
          </ToastActions>
        </ToastHeader>
        <ToastContent scrollable>
          <ToastItem label="Audit.md" meta="1.8k tokens">
            <ToastStatus status="success" />
          </ToastItem>
          <ToastItem label="Tender checklist.docx" meta="Indexing…">
            <ToastStatus status="pending" />
          </ToastItem>
        </ToastContent>
      </Toast>
      <Toast>
        <ToastHeader variant="warning">
          <ToastTitle>Tool approval needed</ToastTitle>
          <ToastActions>
            <Button size="icon-sm" variant="ghost-muted" aria-label="Dismiss">
              <X />
            </Button>
          </ToastActions>
        </ToastHeader>
        <ToastContent>
          <ToastItem
            icon={<ToastStatus status="warning" />}
            label="Vendor Due Diligence"
            meta="wants to run web_search"
          />
          <ToastFooter>
            <Button size="sm" variant="outline">
              Deny
            </Button>
            <Button size="sm">Approve</Button>
          </ToastFooter>
        </ToastContent>
      </Toast>
      <Toast>
        <ToastHeader>
          <ToastTitle wrap>
            Zu einem Team hinzugefügt: Meridian Freight Operations
          </ToastTitle>
          <ToastActions>
            <Button size="icon-sm" variant="ghost-muted" aria-label="Dismiss">
              <X />
            </Button>
          </ToastActions>
        </ToastHeader>
        <ToastContent>
          <ToastMessage size="sm">
            You were added to Meridian Freight Operations as member
          </ToastMessage>
        </ToastContent>
      </Toast>
      <Toast>
        <ToastHeader variant="success">
          <ToastTitle>Sync finished</ToastTitle>
        </ToastHeader>
        <ToastContent>
          <ToastItem label="SharePoint">
            <ToastStatus status="success" />
          </ToastItem>
          <ToastMessage>412 documents are up to date.</ToastMessage>
          <ToastItem label="Google Drive">
            <ToastStatus status="warning" />
          </ToastItem>
          <ToastMessage>
            3 files were skipped: over the 25 MB limit.
          </ToastMessage>
          <ToastItem label="Confluence">
            <ToastStatus status="info" />
          </ToastItem>
          <ToastMessage>Queued behind the nightly re-embed.</ToastMessage>
        </ToastContent>
      </Toast>
      <Toast>
        <ToastHeader variant="info">
          <ToastTitle>New model available</ToastTitle>
        </ToastHeader>
        <ToastContent>
          <ToastMessage size="sm">
            Re-embed your sources to use it for retrieval.
          </ToastMessage>
        </ToastContent>
      </Toast>
    </div>
  );
}
