import {
  Copy,
  MoreHorizontal,
  Pencil,
  Plus,
  Search,
  Settings,
  FileText,
  Book,
  MessageSquare,
  Trash2,
  File,
  Folder,
} from 'lucide-react';
import { useState } from 'react';
import { Button } from '@/components/ui/button';
import {
  Command,
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandShortcut,
} from '@/components/ui/command';
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuShortcut,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { Input } from '@/components/ui/input';
import { Modal, ModalActions } from '@/components/ui/modal';
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import {
  Sheet,
  SheetContent,
  SheetTitle,
  SheetTrigger,
} from '@/components/ui/sheet';

import ConfirmationModal from '@/modals/ConfirmationModal';
import { Example, Section } from '../shared';
import AgentPreviewDemo from './recipes/AgentPreviewDemo';
import ConnectModalDemo from './recipes/ConnectModalDemo';
import DockedPanelDemo from './recipes/DockedPanelDemo';
import RunDetailsPanelDemo from './recipes/RunDetailsPanelDemo';

export default function OverlaySection() {
  const [modalOpen, setModalOpen] = useState(false);
  const [showArchived, setShowArchived] = useState(true);
  const [modalDemo, setModalDemo] = useState<string | null>(null);
  const [connectStep, setConnectStep] = useState<'pick' | 'folders'>('pick');
  const [confirmDemo, setConfirmDemo] = useState<'succeeds' | 'fails' | null>(
    null,
  );
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [sortBy, setSortBy] = useState('recent');
  return (
    <Section
      id="overlays"
      title="Overlays"
      intro="Modal is the only dialog API for app code; the Radix Dialog underneath is private to ui/. SidePanel is every right-side panel (modal or docked); Sheet is for phone bottom sheets. Popovers and menus share the popover surface."
    >
      <Example
        title="Modal and sheet"
        code='<Modal size="md" title description leading footer={<ModalActions …/>}> · <SidePanel size="default | wide"><PanelHeader/><PanelBody/><PanelFooter/></SidePanel> (size is modal-only) · <SheetContent side="bottom" handle>'
      >
        <div className="flex flex-wrap items-center gap-3">
          <Button variant="outline" onClick={() => setModalOpen(true)}>
            Open modal
          </Button>
          <Modal
            open={modalOpen}
            onOpenChange={setModalOpen}
            title="Move to folder"
            description="Pick where this agent should live."
            footer={
              <ModalActions
                cancelLabel="Cancel"
                onCancel={() => setModalOpen(false)}
                submitLabel="Move"
                onSubmit={() => setModalOpen(false)}
              />
            }
          >
            <div className="flex flex-col gap-4">
              <Input label="Folder name" defaultValue="Finance" />
              <Select defaultValue="team">
                <SelectTrigger className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="team">Shared with team</SelectItem>
                  <SelectItem value="me">Only me</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </Modal>
          <ConnectModalDemo />
          <RunDetailsPanelDemo />
          <AgentPreviewDemo />
          <Sheet>
            <SheetTrigger asChild>
              <Button variant="outline">Open bottom sheet</Button>
            </SheetTrigger>
            <SheetContent side="bottom" handle>
              <div className="flex flex-col gap-1.5 p-4">
                <SheetTitle>Tools</SheetTitle>
                <p className="text-muted-foreground text-sm">
                  The phone picker shape: card fill, rounded top, grab handle,
                  clear of the home indicator. max-h-sheet caps it below the
                  visible screen, so the scrim above can always be tapped to
                  close it.
                </p>
              </div>
            </SheetContent>
          </Sheet>
        </div>
      </Example>
      <Example
        title="Docked side panel"
        code='<div className="relative flex"><main className="min-w-0 flex-1"/><SidePanel variant="docked" expandable="design-demo">…</SidePanel></div>'
      >
        <DockedPanelDemo />
      </Example>
      <Example
        title="Modal sizes and footers"
        code='size="sm | md | lg | xl" (md is the default) · onBack (a second step: Back beside the real title) · phones: a sheet by default, mobileVariant="dialog" for a yes/no · hideTitle · <ModalActions destructive | pending | footerStart> · no submitLabel = Cancel only'
      >
        <div className="flex flex-wrap items-center gap-3">
          {(
            [
              ['sm', 'sm, destructive, dialog on phones'],
              ['lg', 'lg, footerStart'],
              ['xl', 'xl, cancel only'],
              ['pending', 'md, pending'],
              ['sheet', 'Sheet on phones (default)'],
              ['hidden', 'hideTitle'],
              ['step', 'onBack, a second step'],
            ] as const
          ).map(([id, label]) => (
            <Button
              key={id}
              variant="outline"
              size="sm"
              onClick={() => {
                setConnectStep('pick');
                setModalDemo(id);
              }}
            >
              {label}
            </Button>
          ))}
          <Modal
            size="sm"
            mobileVariant="dialog"
            open={modalDemo === 'sm'}
            onOpenChange={(open) => !open && setModalDemo(null)}
            title='Delete "Carrier contracts"?'
            description="Its 1,204 chunks are deleted too, and agents using it lose the source. This can't be undone."
            footer={
              <ModalActions
                cancelLabel="Cancel"
                onCancel={() => setModalDemo(null)}
                submitLabel="Delete"
                destructive
                onSubmit={() => setModalDemo(null)}
              />
            }
          >
            {null}
          </Modal>
          <Modal
            size="lg"
            open={modalDemo === 'lg'}
            onOpenChange={(open) => !open && setModalDemo(null)}
            title="Edit MCP server"
            footer={
              <ModalActions
                footerStart={
                  <Button variant="outline" size="lg" shape="pill">
                    Test connection
                  </Button>
                }
                cancelLabel="Cancel"
                onCancel={() => setModalDemo(null)}
                submitLabel="Save"
                onSubmit={() => setModalDemo(null)}
              />
            }
          >
            <div className="flex flex-col gap-4">
              <Input label="Server name" defaultValue="Carrier rates" />
              <Input
                label="Server URL"
                defaultValue="https://mcp.meridianfreight.example"
              />
            </div>
          </Modal>
          <Modal
            size="xl"
            open={modalDemo === 'xl'}
            onOpenChange={(open) => !open && setModalDemo(null)}
            title="Run details"
            description="Read only: the footer is Cancel alone."
            footer={
              <ModalActions
                cancelLabel="Close"
                onCancel={() => setModalDemo(null)}
              />
            }
          >
            <p className="text-muted-foreground text-sm">
              Started 09:30, finished 09:31, 3 tools called.
            </p>
          </Modal>
          <Modal
            open={modalDemo === 'pending'}
            onOpenChange={(open) => !open && setModalDemo(null)}
            title="Import agents"
            footer={
              <ModalActions
                cancelLabel="Cancel"
                onCancel={() => setModalDemo(null)}
                submitLabel="Import"
                pending
              />
            }
          >
            <p className="text-muted-foreground text-sm">
              pending spins and disables the submit; the label stays.
            </p>
          </Modal>
          <Modal
            open={modalDemo === 'sheet'}
            onOpenChange={(open) => !open && setModalDemo(null)}
            title="Share to team"
            description="A centred modal from sm up; a bottom sheet with a grab handle on phones."
            footer={
              <ModalActions
                cancelLabel="Cancel"
                onCancel={() => setModalDemo(null)}
                submitLabel="Share"
                onSubmit={() => setModalDemo(null)}
              />
            }
          >
            <Input label="Add people" />
          </Modal>
          <Modal
            open={modalDemo === 'step'}
            onOpenChange={(open) => !open && setModalDemo(null)}
            onBack={
              connectStep === 'folders'
                ? () => setConnectStep('pick')
                : undefined
            }
            title={connectStep === 'pick' ? 'Add a source' : 'Choose folders'}
            description={
              connectStep === 'pick'
                ? 'Pick where the documents come from.'
                : 'Google Drive · lena.fischer@meridianfreight.com'
            }
            footer={
              connectStep === 'pick' ? (
                <ModalActions
                  cancelLabel="Cancel"
                  onCancel={() => setModalDemo(null)}
                  submitLabel="Continue"
                  onSubmit={() => setConnectStep('folders')}
                />
              ) : (
                <ModalActions
                  cancelLabel="Cancel"
                  onCancel={() => setModalDemo(null)}
                  submitLabel="Add source"
                  onSubmit={() => setModalDemo(null)}
                />
              )
            }
          >
            {connectStep === 'pick' ? (
              <p className="text-muted-foreground text-sm">
                Google Drive is selected. Continue to pick its folders.
              </p>
            ) : (
              <div className="flex flex-col gap-2 text-sm">
                <span>Carrier contracts 2026</span>
                <span>Customs declarations</span>
                <span>Insurance certificates</span>
              </div>
            )}
          </Modal>
          <Modal
            hideTitle
            open={modalDemo === 'hidden'}
            onOpenChange={(open) => !open && setModalDemo(null)}
            title="Image preview"
          >
            <div className="bg-muted flex h-48 items-center justify-center rounded-lg">
              <FileText className="text-muted-foreground size-8" />
            </div>
            <p className="text-muted-foreground mt-3 text-xs">
              The title is still announced to screen readers.
            </p>
          </Modal>
        </div>
      </Example>
      <Example
        title="Async confirm"
        code="<ConfirmationModal handleSubmit={() => request} error> · pending while the promise runs, closes on resolve, a destructive Alert on reject"
      >
        <div className="flex flex-wrap items-center gap-3">
          <Button
            variant="outline"
            size="sm"
            onClick={() => setConfirmDemo('succeeds')}
          >
            Delete, succeeds
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => setConfirmDemo('fails')}
          >
            Delete, fails
          </Button>
          <ConfirmationModal
            message='Delete "HR Policy Bot"?'
            description="Its schedules and run history are deleted too. This can't be undone."
            modalState={confirmDemo ? 'ACTIVE' : 'INACTIVE'}
            setModalState={(state) => {
              if (state === 'INACTIVE') setConfirmDemo(null);
            }}
            submitLabel="Delete"
            variant="destructive"
            error="Couldn't delete HR Policy Bot. Try again."
            handleSubmit={() =>
              new Promise<void>((resolve, reject) =>
                window.setTimeout(
                  () =>
                    confirmDemo === 'fails'
                      ? reject(new Error('demo'))
                      : resolve(),
                  1200,
                ),
              )
            }
          />
        </div>
      </Example>
      <Example
        title="Popover and dropdown menu"
        code="<Popover> · <DropdownMenu> with Shortcut, Sub, RadioGroup, CheckboxItem"
      >
        <div className="flex flex-wrap items-center gap-3">
          <Popover>
            <PopoverTrigger asChild>
              <Button variant="outline">Open popover</Button>
            </PopoverTrigger>
            <PopoverContent>
              <div className="flex flex-col gap-2">
                <p className="text-sm font-medium">Retrieval settings</p>
                <p className="text-muted-foreground text-sm">
                  Chunks per query and the reranker threshold.
                </p>
                <Input size="sm" defaultValue="8" label="Chunks" />
              </div>
            </PopoverContent>
          </Popover>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="outline">
                Actions
                <MoreHorizontal />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start">
              <DropdownMenuLabel>Conversation</DropdownMenuLabel>
              <DropdownMenuItem>
                <Pencil />
                Rename
                <DropdownMenuShortcut>F2</DropdownMenuShortcut>
              </DropdownMenuItem>
              <DropdownMenuItem>
                <Copy />
                Duplicate
                <DropdownMenuShortcut>⌘D</DropdownMenuShortcut>
              </DropdownMenuItem>
              <DropdownMenuSub>
                <DropdownMenuSubTrigger>
                  <Book />
                  Move to
                </DropdownMenuSubTrigger>
                <DropdownMenuSubContent>
                  <DropdownMenuItem>Finance</DropdownMenuItem>
                  <DropdownMenuItem>Legal</DropdownMenuItem>
                  <DropdownMenuItem>Operations</DropdownMenuItem>
                </DropdownMenuSubContent>
              </DropdownMenuSub>
              <DropdownMenuSeparator />
              <DropdownMenuLabel>Sort by</DropdownMenuLabel>
              <DropdownMenuRadioGroup value={sortBy} onValueChange={setSortBy}>
                <DropdownMenuRadioItem value="recent">
                  Most recent
                </DropdownMenuRadioItem>
                <DropdownMenuRadioItem value="name">Name</DropdownMenuRadioItem>
              </DropdownMenuRadioGroup>
              <DropdownMenuSeparator />
              <DropdownMenuCheckboxItem
                checked={showArchived}
                onCheckedChange={(v) => setShowArchived(Boolean(v))}
              >
                Show archived
              </DropdownMenuCheckboxItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem variant="destructive">
                <Trash2 />
                Delete
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </Example>
      <Example
        title="Command palette"
        code='<Command variant="palette">, the spacing CommandDialog uses · <CommandDialog open onOpenChange title description>'
      >
        <div className="flex flex-col items-start gap-4">
          <Button variant="outline" onClick={() => setPaletteOpen(true)}>
            <Search />
            Open CommandDialog
          </Button>
          <CommandDialog
            open={paletteOpen}
            onOpenChange={setPaletteOpen}
            title="Search conversations"
            description="Search your conversations by title"
          >
            <CommandInput placeholder="Search conversations…" />
            <CommandList>
              <CommandEmpty>No results.</CommandEmpty>
              <CommandGroup heading="Recent">
                <CommandItem onSelect={() => setPaletteOpen(false)}>
                  <MessageSquare />
                  Q3 carrier renewals
                </CommandItem>
                <CommandItem onSelect={() => setPaletteOpen(false)}>
                  <MessageSquare />
                  Halvorsen lane costs
                </CommandItem>
              </CommandGroup>
            </CommandList>
          </CommandDialog>
          <div className="border-border w-full max-w-md overflow-hidden rounded-lg border">
            <Command variant="palette">
              <CommandInput placeholder="Search agents, sources, settings…" />
              <CommandList>
                <CommandEmpty>No results.</CommandEmpty>
                <CommandGroup heading="Agents">
                  <CommandItem>
                    <Settings />
                    Contracts & Policy Assistant
                    <CommandShortcut>⌘1</CommandShortcut>
                  </CommandItem>
                  <CommandItem>
                    <Settings />
                    Customer Renewal Desk
                    <CommandShortcut>⌘2</CommandShortcut>
                  </CommandItem>
                </CommandGroup>
                <CommandGroup heading="Actions">
                  <CommandItem>
                    <Plus />
                    New conversation
                  </CommandItem>
                </CommandGroup>
              </CommandList>
            </Command>
          </div>
        </div>
      </Example>
      <Example
        title="Filter field over a list (source navigator)"
        code='<CommandInput variant="field" placeholder="Filter files" />'
      >
        <div className="flex w-64 flex-col gap-2">
          <Command className="contents">
            <CommandInput variant="field" placeholder="Filter files" />
            <CommandList>
              <CommandItem>
                <Folder />
                carriers
              </CommandItem>
              <CommandItem checked>
                <File />
                rate-card-2026.pdf
              </CommandItem>
            </CommandList>
          </Command>
        </div>
      </Example>
      <Example
        title="Chosen item in a picker"
        code="<CommandItem checked={item.id === selectedId}>"
      >
        <div className="border-border max-w-xs overflow-hidden rounded-lg border">
          <Command>
            <CommandList>
              <CommandItem value="default">default</CommandItem>
              <CommandItem value="creative" checked>
                creative
              </CommandItem>
              <CommandItem value="strict">strict</CommandItem>
            </CommandList>
          </Command>
        </div>
      </Example>
    </Section>
  );
}
