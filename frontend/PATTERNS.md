# DocsGPT frontend patterns

DESIGN.md is the system; this is how each area applies it. DESIGN.md holds the tokens, the
`ui/` component contracts, spacing, type, radius, motion, focus and the approved exceptions,
and every rule there holds here too. This file is the per-area spec: the page chrome every
section page shares, the agent pages, the app chrome, the chat, the source views, the workflow
builder and the connectors. A "see X" below points to a section of this file unless it names
DESIGN.md.

## Contents

- [Page chrome: SectionShell, PageToolbar, SearchInput](#page-chrome-sectionshell-pagetoolbar-searchinput)
- [Agent pages](#agent-pages)
- [App chrome: the phone top bar and New Chat](#app-chrome-the-phone-top-bar-and-new-chat)
- [Chat composer](#chat-composer)
- [Chat answer column](#chat-answer-column)
- [Source views](#source-views-componentstree-wikiviewer-componentsgraph-graphview)
- [Workflow builder](#workflow-builder-agentsworkflow)
- [Connectors](#connectors-connectors-conversationtoolcallcard)

## Page chrome: SectionShell, PageToolbar, SearchInput

Every section page (settings, admin, agents, teams) is wrapped in
`navigation/SectionShell` (`width` `default` 6xl, `wide` 7xl for admin,
`narrow` 5xl; `title` replaces the section title; `titleAction` puts a page-level
control, such as a toolbar `ActionMenu`, at the title row's end;
`header={false}` drops the title for the phone section index, which draws
its own);
it draws the title and
starts the content 32px below it, so pages carry no root `mt-*`. The block
under the title is `components/PageToolbar`: `intro`, then the page `search`
(left, `max-w-md`) and the page `action` (right, `Button size="field"
shape="pill"`, text only: no `Plus`, a dropdown keeps its `ChevronDown`), then `children` (notices that belong to the action, such as
a limit warning), then `divider` (a `Separator`). With no `search` the intro
moves into the row's left slot (`max-w-2xl`) beside the action. A page search
is `components/SearchInput`: the 38px pill (one size everywhere) with a
search icon and a floating `label` on `labelSurface="background"` (its
default); a placeholder-only search is named by its placeholder. A source
view's navigator filter is a `CommandInput variant="field"` (the same 38px
pill, text 40px in, the ring on the frame), because its rows are
`CommandItem`s (see Source views, and DESIGN.md › Command). `CommandInput`'s `default` variant is the
`h-9` row with a bottom border at the top of a popover or palette list; the
wrapper carries `data-variant` for styling from the parent. Nothing else
hand-frames a `CommandInput`.

An agent's tabs (Overview, Logs, Schedules) share one header,
`agents/components/AgentPageToolbar` on top of `PageToolbar`, under
`SectionShell`'s title (the tab's name, or "New agent" through SectionShell's
`title` prop). Its props: `name` (the agent, first in a muted byline),
`status` (a Badge beside the name, Overview's Published / Draft), `meta` (the
tab's context after a middle dot, "Last used" on Logs and Schedules),
`actions` (the tab's buttons on the right, at most three; the page's ⋯ goes
in the title row, not here), `intro` (a line that replaces
the byline: the new-agent form) and `children` (notices between the row and
the rule, such as the failed-save `Alert`). With a status badge the meta
takes its own line on a phone. The row keeps the 38px field height when a
tab has no actions, so the rule lands in the same place on every tab.
`AgentPageHeader` remains only in the workflow builder's fixed toolbar. All
three tabs are `SectionShell` pages at the default width; the agent preview
is a drawer (see DESIGN.md › Modal, not Dialog). Overview groups its fields into three
`subtle lg` panels (Basics, Knowledge and behaviour, Model) with the two-up
field grid, then Advanced, Guardrails and the danger zone. Schedules shows a
`StatCard` row, Recurring / One-time as `ui/tabs`, and
each schedule as a `ScheduleRow` (see Agent pages).

## Agent pages

The agent section pages (Overview, Logs, Schedules), the agent form and the workflow builder's
toolbar. Their header row is `AgentPageToolbar` (see Page chrome).

Buttons:

- One variant and size per role on the agent pages (Overview, Logs,
  Schedules, the workflow builder's toolbar): the page's primary action is
  `default field pill` (Publish, Save, New schedule), a secondary action
  `outline field pill` (Save draft, Preview with `Play` first), Cancel `ghost
field pill`, and page-level actions go in the `ActionMenu` (`size="toolbar"`)
  at the end of the title row, through `SectionShell titleAction`: Access
  details and Share with team on Overview (each only when the role allows
  it, see DESIGN.md › Access and roles), and Preview until the agent is
  published (before that the preview only says "Publish to preview"). So the
  row never holds more than three buttons and fits a phone, where the main
  one stretches across it (`flex-1 sm:flex-none`; `PageToolbar`'s action slot
  spans the stacked row below `sm`). The workflow builder's toolbar has no
  title row and keeps its ⋯ at the row's end, holding Edit details, Access
  details, Share with team and Delete (see Workflow builder). The
  agent's Delete is in Overview's danger zone; only the workflow builder's
  toolbar has it in the ⋯ menu, as a `destructive` item. The row itself is
  `agents/components/AgentPageToolbar` (see Page chrome). A row's common
  action is `outline sm pill` (a schedule's Run now or Resume) with its other
  actions in the row's `ActionMenu`; a delete there is a `destructive` item
  that opens the confirm modal.

Cards (the recipes by role in DESIGN.md › Card surfaces, applied here):

- Form sections (the agent form's Basics, Knowledge and behaviour, Model,
  Advanced, Guardrails) are `subtle lg` with `gap-5`; Basics, Knowledge and
  behaviour and Model are titled by a `SectionHeader`, Advanced and
  Guardrails by a `CollapsibleTrigger look="section"` in an `<h2>` (see
  DESIGN.md › Disclosure), its status badges beside the `<h2>`. The toggle
  and its Collapsible share a plain `<div>`, and the body opens with `pt-5`
  (its rows in a `flex flex-col gap-5` column, no `mt-*`), so every section
  has 20px under its title and none under a closed toggle. The danger zone
  follows them (see DESIGN.md › Card, Danger zone).
- Guardrails' stage panels (one per active check and stage) are `Card
variant="subtle" padding="sm"`, `tone="destructive"` while the control
  needs setup; their fields use `float={false}` on that fill (see DESIGN.md ›
  FormField).
- A schedule is `agents/schedules/ScheduleRow`: `subtle`, `padding="none"`,
  with its run log flush under it; a chevron `IconButton ghost-muted
icon-xs` toggles the runs.

## App chrome: the phone top bar and New Chat

Below `lg` the top of every page is `navigation/MobileTopBar` (56px, `h-14`):
the sidebar toggle (`PanelLeft`), a title, then New Chat and the account
avatar (`ProfileButton size="xs"`). It is on `bg-background` like the page,
with no border and no shadow; a `from-background to-transparent` gradient under
it lets the content fade out as it scrolls. At `lg` and up, `ActionButtons`
holds Share and the avatar in the top-right corner instead, and it renders
nothing on a phone.

The title is for chats only: the open conversation's name, or the agent's
name on a new agent chat, with the agent's `Avatar` in front. A plain new chat
has no title. So do section pages (settings, admin, an agent's pages), because
`SectionShell` already draws their title. When the chat has actions, the title
is a `ghost sm` Button that opens a `DropdownMenu` with Edit agent (a role
that may open its edit page), Share, Rename and Delete. Rename edits the name in place, as the
sidebar row does. A title with no actions (a shared agent's new chat) is
plain text.

A long title truncates to one line and never runs under New Chat or the
avatar: the title slot is `flex min-w-0 flex-1`, the agent's `Avatar` and the
chevron keep their size, and only the name gives way (a `truncate` span with
`title=` holding the full name). This is the rule for any Button that holds a
user-supplied name (a chat, agent or source) in a flex row (see DESIGN.md ›
Button).

New Chat is `SquarePen` everywhere: the phone bar, the sidebar's New Chat row
and the collapsed rail. `Plus` means "add an item to this list", not "start
a chat".

## Chat composer

- The composer controls under the chat field (Attach, Voice, Tools,
  Sources) are `outline sm pill`. Their icons are `size-3.5 sm:size-4`
  with no margin; the size's `gap-1.5` spaces them, and the label span keeps
  `text-xs sm:text-sm` so the row still fits on a phone.
- The attachment chips above the field (`message-input/AttachmentChipList`)
  sit in one `scrollbar-overlay` area capped at `max-h-32 sm:max-h-48` (about
  two and a half rows on a phone, three and a half wider, so the cut row
  shows there is more), so many files never push the composer over the page;
  its `p-1` keeps focus and drag rings clear of the scroll clip. A chip's brand tile shows its state: `Clock` while it waits
  for an upload slot, a progress ring while it uploads or the worker parses
  it (both faded), `Paperclip` once attached. A failed chip is the status
  look: `border-destructive/50 bg-destructive/10` at full opacity, a solid
  `bg-destructive` tile with `CircleAlert`, and the reason in a tooltip that
  opens on hover and on focus (the failed chip is a tab stop), also tied to
  the chip and its remove button with `aria-describedby`.

## Chat answer column

The answer column never scrolls sideways. Its boxes, from AnswerFlow down to
MarkdownAnswer, are stretched full width (`w-full min-w-0`, or the flex
default), never `items-start` / `self-start` with `max-w-full`: a
shrink-to-fit box sizes to its longest code line, and `max-w-full` caps it at
100% before its margins are added, so it still spills past a phone screen.
Wide markdown blocks scroll inside their own frame, not the page: fenced code
scrolls sideways in its bordered `CodeFrame` with the language and copy row
fixed above it (see DESIGN.md › Code blocks), and tables do the same (`overflow-x-auto` on their bordered
wrapper).

A failed chat answer is an `Alert variant="destructive"` on the answer's
`mr-5 ml-6` column (its `CircleAlert` drawn by the variant): the fixed title
`conversation.failedTitle`,
and the backend's error (often a raw provider exception) as `font-mono text-xs`
detail in `AlertDescription`. Its action row is Retry (`RotateCcw`) and Copy,
both `ghost-muted icon-sm pill` like every other answer action. An action
that fixes the error (Add to Knowledge, when a turn's files overflowed the
model) is an `outline sm pill` Button with a leading lucide icon under the
message, in a `text-foreground` wrapper so its label is body text rather than
the alert's red; a link in the alert's colour does not read as a control.

The rows in an answer's step column (Sources, Reasoning, each tool step) are
one recipe: `Button variant="ghost" size="sm"` at `ml-3.5 w-fit`, which puts a
16px muted icon on the `ml-6` text column, then muted 14px text and a chevron.
Sources adds its count and a right chevron, and opens the answer's sources in
the chat's side panel (see DESIGN.md › Side panels).

The column renders in the order the answer streamed: answer text, reasoning
and tool calls interleaved (`answerSegments`, saved with the message as
`metadata.segments`; a message with no saved order, or one that no longer fits
its text, puts the steps first and the answer after them). `layoutAnswer` turns
that order into blocks:

- **Step group** (`conversation/StepGroup`): three or more tool calls in a row
  are one step row in the Sources row's shape: the lucide `Wrench` (the
  composer's Tools icon), "Tools" (`settings.tools.label`'s word), the call
  count in `text-muted-foreground/70 font-normal`, and the red "N failed" when
  any failed. It opens a `Collapsible` list of 28px rows on a
  1px `bg-border` rule through the icon centres. A row is a framed-row
  `<button aria-expanded aria-controls>` (see DESIGN.md › Disclosure) whose
  chevron shows on hover, focus or while open, and opens the call's Arguments
  and Response (`ToolCallDetail`). Reasoning between the run's calls is a
  "Reasoning" row in the list; one short paragraph the model wrote between two
  calls (≤400 characters, no blank line, heading, list, quote, table or fence)
  is a muted `text-sm` note in it. Anything longer is answer and splits the
  run. Reasoning or narration after the run's last call stays outside, and
  folds in if another call follows.
- While the group is the live end of a streaming answer it is open on a fixed
  `h-21` window holding the newest three rows (`mask-t-from-50%`, `inert`), so
  arriving steps never resize the page; it closes when anything follows it. A
  click on the header wins over both from then on.
- One or two calls stay single step rows. Approval bars, wiki-write cards and
  the scheduler card carry actions, so they end a run and stay in the column.
- Labels name the action and its target (`describeToolCall`: "Read wiki page
  /sales/pricing.md", "Added todo “…”", "Updated the note", "Checked the BTC
  price in EUR"); a tool without its own case is "Used {tool}: {action}", and
  the bare tool name only when the action repeats it. A label carries its full
  text as `title`. The backend stores a call whose result reports failure
  (`status: error`, an `error` key, or an HTTP `status_code` of 400 or more) as
  `error`, and its Response shows the result in the destructive tone.
- Icons in the column are one muted weight (`StepIcon`): a tool whose bundled
  icon is a brand mark in its own colours, or that has none, draws a lucide
  stand-in (wiki `BookOpen`, Brave and DuckDuckGo `Search`, Telegram `Send`,
  ntfy `Bell`, Postgres `Database`). The Tools page keeps the brand marks.

A cited source opens in that panel as its second level, `CitationReader`:
a source card under the answer, a tile in the list and an inline `[n]` pill
all open the source they name, with Back to the list. The reader fetches the
full passage by the chunk key retrieval labelled it with (`source_id` +
`chunk_key`; the endpoint searches the excerpt's start in the same call for a
re-chunked source), renders it with `SourceMarkdown`, and lists what is known in a
`DescriptionList`. When the passage can't be fetched (an answer saved before
chunk keys, a re-chunked source, a source out of reach) it shows the answer's
excerpt under an `info` note saying why; a failed load is the destructive
`EmptyState` with Retry. A web source's link sits in the reader's footer, never
inside the clickable tile, beside "Open in Knowledge": a `Link` built by
`settings/knowledgeLink.ts` that opens the source's view on the cited chunk
(`linkedChunk`, its file for a folder source) or wiki page (`initialPath`).
Knowledge reads the link once and drops it from the URL; the source comes from
the caller's own lists, so its view gets their real access. The reader's
Knowledge row links the source itself (no chunk), one level above "Open in
Knowledge".

Wiki pages link each other by wiki path (`/engineering/runbook.md`, or
relative to the page). `SourceMarkdown`'s `resolveLink` sends those somewhere
real: `WikiViewer` opens the page in place, the citation reader opens it in
Knowledge, and a link to a page that does not exist, or one the reader can't
reach, reads as text. Only web addresses open in a new tab.

## Source views (`components/tree/`, `WikiViewer`, `components/graph/`, `GraphView`)

Every source view (a file or connector tree, a one-document chunk list, a
wiki, a knowledge graph) is one shell:

- **Header**: `PathHeader`, 16px (`gap-4`) above the content in every
  source view, crumbs and no back button: Sources (leaves the source view),
  the source, its folders, the open file and the open chunk ("Chunk 12"),
  each opening its level, the last one current. A wiki's open page is not a
  crumb: its crumbs stop at the source, and the page is marked in the
  navigator and named by its path in the reader's meta. Up one level is
  a crumb, as on the Tools and Teams detail pages (`DetailBreadcrumb`); the
  phone's `SectionBackLink` above the title is the only arrow, and it leaves
  the section. Crumbs never take `text-primary`; parents are muted like any
  crumb, and the Breadcrumb primitive keeps the row on one line. A tree embedded in another source view (a graph
  source's Files tab) draws no Sources crumb and reports its crumbs to the
  host (`onCrumbsChange`), whose header shows them while that tab is open. The
  file table has no `..` row. `badge` is the source kind as a `neutral` Badge with a 12px lucide
  icon (Living wiki, Knowledge graph, a connector's provider; plain uploads
  have none); `byline` is one muted `text-sm` line of counts ("33 files ·
  11,420 tokens", "12 pages · 8,111 tokens · …", "371 entities · 1,172
  relationships"), where a kind that needs explaining adds one sentence. No
  explainer box. Actions on the right: Test retrieval (`outline field pill`)
  and the kind's one primary action (Add file, Sync).
- **Navigator**: `SourceNavigator`, a `w-64` column shown only when there is
  more than one thing to open (files, wiki pages). A filter `CommandInput
variant="field"` over a `CommandList` of `CommandItem`s, so the arrow keys
  walk from the field into the list; the open item is `checked`. Files are a
  tree (folders expand, a folder opens its table on the right and expands,
  24px of indent per level to depth 4 and 12px per level below it, every row
  with its path as `title`); wiki pages are grouped under their top folder as
  `CommandGroup` headings, labelled by title or by file name in sentence case
  (`wikiPageLabel`). Typing flattens the list to matching leaves with their
  full parent path as a muted second line. The column caps its list at
  `max-h-[70svh]`. Below `lg` it is a `combobox field pill`
  that opens the same list in a bottom sheet, uncapped (the sheet body
  scrolls). A source with one file opens
  straight on its chunk list, and a wiki with one page on its reader at full
  width: no navigator, no table.
- **Reader**: `ReaderPanel`, the content you read (a wiki page, an open
  chunk): a `subtle` Card with `padding="none"`, its meta (muted 12px lines)
  left and its actions right in a `min-h-14 px-6` header row, a `Separator`,
  then the body at `px-6 py-5`. The body is always rendered markdown,
  `components/SourceMarkdown` (the chat answer's headings and tables, lists
  outside the text); raw text is never the reading view. Actions: an open
  chunk's previous / next (`IconButton ghost-muted icon-sm pill`, and the
  arrow keys), then Edit (`outline sm pill`, `Pencil` first) and an
  `ActionMenu size="toolbar"` (Copy text; a chunk's also has Delete, a
  destructive item). A wiki page has Edit and the same menu
  with Copy text, and no previous / next; the navigator walks them. Edit,
  Delete and Add chunk show only to a role that may edit (see DESIGN.md › Access and
  roles).
- **Read in the page, edit in a drawer**: Edit and Add chunk open
  `SourceEditSheet`, a modal `SidePanel size="wide"` (a working surface): title
  and a mono description (path, version, tokens), then any `fields` edited
  with the content (a chunk's Title, a `FormField` + `Input` with
  `labelSurface="background"` and the hint "The name answers cite this
  chunk by."; Add prefills it with the title the file's chunks already use,
  else the file's name), Write · Preview
  (`ui/tabs`; Preview renders the draft with
  `SourceMarkdown`), one filling `font-mono` Textarea, then Cancel (`ghost lg
pill`) and Save (`default lg pill`, off until the draft or a field changes, and while the draft is blank). The drawer
  edits a copy: closing with changes asks "Discard your unsaved changes?". A
  save result stays in the drawer as an Alert above the field (a wiki
  conflict `warning`, forbidden and failures `destructive`); success closes
  it and the page re-renders behind. Never edit in place in the reader.
- **Chunk grid**: `SearchInput` ("Search chunks"), then Add chunk at the end.
  The count is in the header's byline; only a chunk list inside a file tree,
  whose byline is the tree's totals, repeats it as muted meta beside the
  search; tiles show `chunkPreviewText` (heading markers and dot
  leaders removed, display only) and `#n · tokens` in `CardFooter`.
- **Graph**: under the header, `ui/tabs` Graph · Entities
  · Files (Files is the embedded file tree; a source with no folder structure
  shows its embedded chunk list there instead, as the plain view does). A tab's own action goes in the
  header's action row after Test retrieval, only while that tab is open (the
  Files tab's Add file or Sync, portalled through `TreeBrowser`'s
  `actionsTarget`), as on the agent pages; the embedded tree draws no row of
  its own. The Graph tab's toolbar holds the
  entity search (`graph/GraphEntitySearch`: a `SearchInput` whose results
  over the server's `/graph/nodes?q=` open in a Command anchored under it,
  the field keeping focus and driving the list with the arrows and Enter),
  the phrase "Show top [50 | 100 | 250] by connections" (muted `text-sm`
  words around a `ToggleGroup xs`, its track holding only the numbers) and the
  legend, which is the type filter (`ToggleGroup type="multiple" xs`,
  a colour dot per item). The surface is one `subtle` Card, `padding="none"`, at `h-[70svh]`;
  the canvas controls (`graph/GraphCanvasControls`) are the workflow
  builder's `CanvasControls` strip without React Flow or Undo / Redo; change
  the two together. Type colours come from `graph/GraphTypeDot`
  (`GraphTypeDot`, `GraphTypeBadge`, `GraphSeriesDot`), never a hand-picked
  hue; the node panel is a docked `SidePanel expandable="graph-node"` inside
  the Card (which is `relative`), open only while a node is selected (see DESIGN.md › Side
  panels): the entity's name, its type Badge as the description, "Show in
  graph" under the title on the Entities tab. The Entities tab is
  the same frame: toolbar (`SearchInput` with a `label`, the type Select),
  then the `h-[70svh]` Card holding the `Table` (no `TableContainer`, it
  scrolls inside) and the same dock, the open entity's row `selected`, and the
  pager under the frame. The canvas labels only the ten biggest hubs, the
  hovered node and the selection with its neighbours, and dims everything
  unconnected to the selection to 15%. The panel lists the node's
  relationships, one row per neighbour with its normalised edge labels
  (`groupRelationships`), each a button that selects that neighbour, then its
  source chunks as `filled sm interactive` tiles. A tile opens the chunk as
  the panel's second level (`graph/GraphChunkReader`): a Back arrow, the chunk
  rendered with the entity's name marked in the brand tint (`bg-secondary`),
  and Open in Files and Edit (the modal `SourceEditSheet`) in its footer,
  which is omitted when neither applies. Cancel or Discard in the edit drawer
  returns to the chunk; Back, Open in Files and a saved edit return to the
  entity. The relationship list is capped server-side: its heading
  counts the true total (`relationships_total`) and, when the list is partial,
  a muted `text-xs` line says how many are shown.

## Workflow builder (`agents/workflow/`)

The toolbar is `AgentPageHeader` on `bg-background` with a `border-b`. Its
current crumb is the agent's `Avatar` (circle, 20px image, the robot when
there is none), the name (`truncate`, `max-w-[32ch]`, the current crumb's cap) and a muted
`ChevronDown` in a `ghost sm` Button, the phone top bar's title recipe; it
opens the workflow details. The status Badge follows (`success` Published,
`neutral` Draft until the first save), then the tabs. On the right: "Unsaved
changes" as muted `text-sm` meta while there are any, Preview, Save, and the
⋯ (`ActionMenu size="toolbar"`): Edit details first (the same drawer, for
anyone who doesn't try the name), then Access details, Share with team and
Delete once the workflow is saved, each only when the role allows it.

The workflow details are a modal `SidePanel size="default"`
(`components/WorkflowDetailsSheet.tsx`, see DESIGN.md › Side panels) with the classic
Basics phone layout: a
`subtle lg` Basics panel with `FileUpload size="tile" tileSize="fixed"` beside
the Name pill and Description across the row, then an Advanced panel with the
prompt-override `SettingRow`. Its `PanelFooter` is a `ghost lg pill` Cancel
and a `default lg pill` Save. The panel edits a copy: Cancel,
the X, Escape and the scrim drop the edits; Save is disabled until something
changes, then saves the workflow and closes, or stays open with a destructive
`Alert` listing the errors.

The canvas is `bg-muted`; the node palette to its left is a `bg-background`
rail with `border-r` (`NodePalette.tsx`), and each palette pill is a
`<button>` that is also `draggable`: drag it onto the canvas, or click (or
press Enter) to add the node beside the selected one, or in the middle of the
view. Each pill's icon is a `size-8 rounded-md` tinted square, like the
settings panel's header (the pill is round, its icon is not; the canvas
nodes keep their `size-10` circles). Pills hover to `bg-accent` only, with
the focus ring, and a muted `text-xs` line under the groups says so.

- **One tone per node type**: `nodeTones.ts` (`NODE_TONES`, `nodeToneClass`)
  is read by the palette, every canvas node and the settings panel's header.
  Agent is the brand soft fill (`bg-secondary text-secondary-foreground`),
  Start and End `success`, Note and If / Else `warning`, Set State and Code
  `info`, each `bg-<tone>/10 text-<tone>`. End is never `destructive`.
- **Selected node**: `border-primary ring-3 ring-ring/50`, the focus-ring
  look, with no scale (the Note node: `border-warning ring-3
ring-warning/50`). Node meta is translated and muted (the agent type · the
  model's display name, from `WorkflowModelsContext`); an output variable is
  an `ArrowRight` then the name in `font-mono`.
- **Canvas controls**: one `bg-card border rounded-full p-1` strip at the
  bottom left (`CanvasControls.tsx`, no shadow): Undo, Redo, a vertical
  `Separator`, Zoom out, the zoom level, Zoom in and Fit view, each
  `ghost-muted icon-sm pill` with a top tooltip. React Flow's own
  `<Controls />` and attribution are not shown.
- **Node settings** are a docked `SidePanel expandable="workflow-node"` at
  the canvas's right edge (`panels/NodePanel.tsx`), under the builder header
  (see DESIGN.md › Side panels). The header's `leading` is the type's `size-8 rounded-md`
  icon square; the description is the type's name, then the id in `font-mono
text-xs` with a `CopyButton`; `actions` is an `ActionMenu size="toolbar"`
  (Duplicate, Delete node; none on Start). Start and End have no Title field:
  their body is one muted `text-sm` line saying what the node does. Its fields pass
  `labelSurface="background"` and its row boxes (a condition case, a state
  assignment) are `Card variant="subtle" padding="sm"`. The agent node's
  fields are grouped by `SectionHeader size="xs" as="h3"` (Model, Prompt,
  Knowledge, Output) with an Advanced settings `CollapsibleTrigger` that
  opens on its own when one of its settings is set. The column is narrow, so
  every field stacks at full width (`flex flex-col gap-5`), Agent type and
  Model included; no two-up grids. A row box's title is `SectionHeader
size="xs" as="h4"`. In an If / Else case's Simple mode, the operator Select
  and Value each carry a floating label (Operator, Value).

## Connectors (`connectors/`, `conversation/ToolCallCard`)

One tile, `connectors/ConnectorTile`, draws a service everywhere: the
Connectors catalog, the Tools page and Add a tool's picker. A header row (a
24px icon, the `CardTitle` truncating, a ⋮ `ActionMenu` in `CardAction` only
on a tile that isn't itself a button), a `CardDescription size="xs"
line-clamp-2`, a badge row that hides when empty (the state first: `success`
Connected, `warning` Reconnect, `neutral` Needs admin setup / Disabled by
admin; then the capability badges, `neutral`), and `CardFooter` meta (the
account line, the Tools switch). No fixed heights. An available service has
no badge and no footer: the whole tile is its Connect, and an action drawn in
the footer would read like the account line there. A custom entry has no
state. On a page the tile is `filled lg`; in a modal it is
`outline interactive lg`. A connected tool's header shows its service's icon.

The Connectors page filters by state, not by category: All, Connected (a
working account) and Disconnected (an account that needs signing in again or
was disconnected), DESIGN.md's (ToggleGroup) filter-by-kind track (`sm`, the
page size) with each state's `count`, kept in the
address (`?filter=`). A state with nothing in it isn't offered; with only All
left there is no row. A narrowed list (`?capability=sync|tools`) is a removable
`default` Badge beside the track (`onRemove` clears it; see DESIGN.md › Badge). Search finds a service by
name.

One broken connection has one word everywhere: **Reconnect**
(`settings.connectors.status.reconnect`), the `warning` Badge for the state
and the label of the action. "Needs sign-in" is one rule,
`connectionNeedsSignIn` (`reconnect_needed` or `error`); a `disconnected`
account is the user's own choice and isn't flagged.

The Tools page groups its grid like the composer's picker
(`settings/toolGroups.ts`): `SectionHeader size="sm"` for Built-in, one group
per connected service with its icon, then Custom; a group may continue onto
the next page under a repeated header. Add a tool lists "From a service", then
a Custom section (MCP server, OpenAPI / REST) whose tiles launch in place, and
its footer is Cancel only. A tool's config tables (`settings/ToolConfig`:
headers, query parameters, an action's properties) fix the Name column with
`TableHeader width="14rem"`; their edit rows size the fields with flex and
the column widths, never `min-w-[…]` pins (see DESIGN.md › Table). Add knowledge is one view: the upload and web
tiles, then "From a service" (see DESIGN.md › OptionCard) and "Browse all connectors"
(`settings.connectors.browseAll`, 12px `ArrowRight`) under the tiles.

The connection drawer (`ConnectionDrawer`, a `default` SidePanel) keeps the
capability badges in `PanelHeader` children. Its accounts are one `Card subtle
padding="none" overflow-hidden` of ListRows (name, account line, status Badge,
⋯); with several, the row whose tools show below is `selected` (see DESIGN.md › ListRow).
A part (Jira & Confluence inside Confluence) is a sibling section with the
parent's header row and Connect size. It shows `LoadingState` until the
connections list and this connector's details have loaded, never "No account"
with a Connect meanwhile. The account ⋯ is Rename, Disconnect, then Remove
after a separator (`separatorBefore`); both confirmations name the account,
say what the account actually has and are async submits (see DESIGN.md ›
Modal, not Dialog). Disconnect's submit is primary; only
Remove is destructive. "In my chats" stays as in DESIGN.md › Switch.

Per-action permissions are `connectors/PermissionGroup` everywhere (the
drawer's ToolPermissions, an agent's API write allowlist, the Tools page
editor): a `SectionHeader size="xs"`, the group's name with its action tally as
`count` (the API write allowlist's "2 of 5 allowed"), whose `actions` hold one
`ToggleGroup xs`, Allow / Ask first / Off / **Customize**
(Allow / Off / Customize where nobody can approve: the API, the widget, a
public link). Customize is pressed while the rows disagree and is the fold:
rows (`PermissionRow`: the action title, a muted `line-clamp-2` description,
a `PermissionSelect` `Select sm w-32`) show only under it. There is no
"Customize each of N" or "Show all" link. Who fills a parameter is always
"Let AI decide / Always use"; "Parameters" is `ActionParametersToggle` (an
inline `CollapsibleTrigger`, named "Parameters for {action}").

The connect wizard (`ConnectWizard`) is a `size="lg"` Modal on every step,
with the connector's icon tile in `leading` (`Avatar size="xl" shape="square"
variant="icon"`, as in the connection drawer's header; see DESIGN.md › Avatar) and a `description` (the
service's description, then "Signed in as …"). Every step title names the
service ("Choose what to sync from GitHub") and doesn't change with a switch.
The setup step's footer is one submit named by what it does ("Add to
Knowledge" while Sync is on, else "Finish setup"; Cancel + "Add to Knowledge"
when syncing more), never Skip. Every path ends on the done step, whose
summary is a `success` Alert. With several accounts and none chosen, the
first setup field is an account Select. The pickers (repositories, Linear,
SharePoint / Confluence / Drive files) are one recipe: a search on
`labelSurface="card"`, then an `outline padding="none" overflow-hidden` Card
of ListRows (a Checkbox and the icon square in `leading` for a multi-pick, a
muted meta line "Updated 12/09/2026 · 2.29 MB", a trailing `ghost-muted
icon-sm` chevron to open a folder), a muted `text-xs` "N selected" line under
it, no scroll cap (the modal body scrolls) and `useLoadMore` +
`LoadMoreStatus loadingLabel` for more pages. An expired sign-in in a picker
offers Reconnect.

Credential forms put every hint under its field (FormField `hint`); required
fields carry the star, so no field says "Optional". A catalog hint may wrap one
phrase in `<link>…</link>` with the field's `hint_url`: it renders as a `link
text` Button, so it takes the hint's size and weight, with a trailing 12px
`ExternalLink`.

A paused tool call in chat, an approval or a Connect card, is
`conversation/ToolCallCard`: a `bg-muted rounded-2xl border` frame, a header
row (a 20px logo, "Service · Action" truncating, an optional muted meta, a
state Badge: `info` Needs approval, `neutral` Not connected, `warning`
Reconnect, `success` Connected), an optional body and a wrapping row of `xs`
pill actions. The arguments stay behind the Details chevron. The card sits in
a `w-full min-w-0` wrapper with its margins on an inner div, because the
answer bubble is a wrapping flex column and would let a one-line preview widen
the card past the column.
