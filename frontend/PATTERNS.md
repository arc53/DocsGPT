# DocsGPT frontend patterns

DESIGN.md is the system; this is how each area applies it. DESIGN.md holds the tokens, the
`ui/` component contracts, spacing, type, radius, motion, focus and the approved exceptions,
and every rule there holds here too. This file is the per-area spec: the page chrome every
section page shares, the agent pages, the Monitoring pages, the app chrome, the chat, the source views, the
workflow builder, the connectors and Activity. A "see X" below points to a section of this file unless it names
DESIGN.md.

## Contents

- [Page chrome: SectionShell, PageToolbar, SearchInput](#page-chrome-sectionshell-pagetoolbar-searchinput)
- [Agent pages](#agent-pages)
- [Monitoring pages: Analytics, Insights, Logs](#monitoring-pages-analytics-insights-logs)
- [App chrome: the phone top bar and New Chat](#app-chrome-the-phone-top-bar-and-new-chat)
- [Chat composer](#chat-composer)
- [Chat answer column](#chat-answer-column)
- [Source views](#source-views-componentstree-wikiviewer-componentsgraph-graphview)
- [Workflow builder](#workflow-builder-agentsworkflow)
- [Connectors](#connectors-connectors-conversationtoolcallcard)
- [Activity](#activity-activity)

## Page chrome: SectionShell, PageToolbar, SearchInput

Every section page (settings, admin, agents, teams, activity) is wrapped in
`navigation/SectionShell` (`width` `default` 6xl, `wide` 7xl for admin,
`narrow` 5xl; `title` replaces the section title;
`header={false}` drops the title for the phone section index, which draws
its own);
it draws the title and
starts the content 32px below it, so pages carry no root `mt-*`. The block
under the title is `components/PageToolbar`: `intro`, then the page `search`
(left, `max-w-md`) and the page `action` (right, `Button size="field"
shape="pill"`, text only: no `Plus`, a dropdown keeps its `ChevronDown`), then `children` (notices that belong to the action, such as
a limit warning), then `divider` (a `Separator`). With no `search` the intro
moves into the row's left slot (`max-w-2xl`) beside the action. The row
stacks below `sm` (the action under the intro, spanning it); `stack={false}`
keeps a small action, such as a lone ⋯, beside the intro there. A page search
is `components/SearchInput`: the 38px pill (one size everywhere) with a
search icon and a floating `label` on `labelSurface="background"` (its
default); a placeholder-only search is named by its placeholder. A source
view's navigator filter is a `CommandInput variant="field"` (the same 38px
pill, text 40px in, the ring on the frame), because its rows are
`CommandItem`s (see Source views, and DESIGN.md › Command). `CommandInput`'s `default` variant is the
`h-9` row with a bottom border at the top of a popover or palette list; the
wrapper carries `data-variant` for styling from the parent. Nothing else
hand-frames a `CommandInput`.

An agent's pages (Overview and Schedules, then the Monitoring group: Analytics, Insights and Logs) share one header,
`agents/components/AgentPageToolbar` on top of `PageToolbar`, under
`SectionShell`'s title (the tab's name, or "New agent" through SectionShell's
`title` prop). Its props: `name` (the agent, first in a muted byline),
`status` (a Badge beside the name, Overview's Published / Draft), `meta` (the
page's context after a middle dot, "Last used" on every page of a saved agent),
`actions` (the page's buttons on the right, at most three; on Analytics and Insights the window select, and Insights' Settings beside it),
`menu` (the agent's ⋯, last in the row after the actions, as a source view's
`PathHeader menu`; with no actions it stays beside the byline on a phone), `intro` (a line that replaces
the byline: the new-agent form) and `children` (notices between the row and
the rule, such as the failed-save `Alert`). With a status badge the meta
takes its own line on a phone. The row keeps the 38px field height when a
page has no actions (Logs), so the rule lands in the same place on every page.
`AgentPageHeader` remains only in the workflow builder's fixed toolbar. All
five pages are `SectionShell` pages at the default width; the agent preview
is a drawer (see DESIGN.md › Modal, not Dialog). Overview groups its fields into three
`subtle lg` panels (Basics, Knowledge and behaviour, Model) with the two-up
field grid, then Advanced, Guardrails and Insights. Schedules shows a
`StatCard` row, Recurring / One-time as `ui/tabs`, and
each schedule as a `ScheduleRow` (see Agent pages).

A detail page inside a list section (an open team, tool or remote device)
swaps the list's `PageToolbar` for a crumb row at the 38px field height
(`min-h-9.5`): `DetailBreadcrumb` on the left; on the right the page's
buttons (`field` pills: the tool's Save) and the object's ⋯ (`ActionMenu
size="toolbar"`) last, as a source view's `PathHeader` ends with its `menu`.
An open tool's ⋯ is its tile's menu less Edit / View (`getMenuOptions(tool,
true)` in `settings/Tools`, whose dialogs serve both); a device's holds
Revoke. A delete or revoke is the ⋯'s last item, `destructive` after a rule.

## Agent pages

The agent section pages (Overview, Schedules, Analytics, Insights, Logs), the agent form and the workflow builder's
toolbar. The three Monitoring pages have their own section (see Monitoring pages). Their header row is `AgentPageToolbar` (see Page chrome).

Buttons:

- One variant and size per role on the agent pages (Overview, Schedules,
  Analytics, Insights, Logs, the workflow builder's toolbar): the page's primary action is
  `default field pill` (Publish, Save, New schedule), a secondary action
  `outline field pill` (Save draft, Preview with `Play` first), Cancel `ghost
field pill`, and page-level actions go in the `ActionMenu` (`size="toolbar"`)
  last in the toolbar row, through `AgentPageToolbar menu`, on Overview
  only (and the workflow's phone Overview, `MobileBlocker`; Schedules and
  the Monitoring pages keep to their own actions): Access details and
  Share with team (each only when the role allows
  it, see DESIGN.md › Access and roles), and Preview until the agent is
  published (before that the preview only says "Publish to preview"); each
  item has its icon (`Link`, `Users`, `Play`), and the ⋯ isn't drawn with no
  items. So the row never holds more than three buttons and the ⋯, and fits a
  phone, where the main one stretches across it (`flex-1 sm:flex-none`;
  `PageToolbar`'s action slot spans the stacked row below `sm`, the ⋯ at its
  end). The workflow builder's toolbar keeps its ⋯ at the row's end too, holding Edit details, Access
  details, Share with team and Delete (see Workflow builder). Delete is the
  agent ⋯'s last item on both, a `destructive` item after a rule
  (`separatorBefore`) that opens the confirm. The menu comes from
  `agents/hooks/useAgentMenu`, which also draws the dialogs; Overview adds
  Preview first and opens its own Access details. The row itself is
  `agents/components/AgentPageToolbar` (see Page chrome). A row's common
  action is `outline sm pill` (a schedule's Run now or Resume) with its other
  actions in the row's `ActionMenu`; a delete there is a `destructive` item
  that opens the confirm modal.

Cards (the recipes by role in DESIGN.md › Card surfaces, applied here):

- Form sections (the agent form's Basics, Knowledge and behaviour, Model,
  Advanced, Guardrails, Insights) are `subtle lg` with `gap-5`; Basics, Knowledge and
  behaviour and Model are titled by a `SectionHeader`, Advanced,
  Guardrails and Insights by a `CollapsibleTrigger look="section"` in an `<h2>` (see
  DESIGN.md › Disclosure), its status badges beside the `<h2>` (Insights' `neutral`
  Off while the agent collects none). The toggle
  and its Collapsible share a plain `<div>`, and the body opens with `pt-5`
  (its rows in a `flex flex-col gap-5` column, no `mt-*`), so every section
  has 20px under its title and none under a closed toggle.
- Guardrails' stage panels (one per active check and stage) are `Card
variant="subtle" padding="sm"`, `tone="destructive"` while the control
  needs setup; their fields use `float={false}` on that fill (see DESIGN.md ›
  FormField).
- A schedule is `agents/schedules/ScheduleRow`: `subtle`, `padding="none"`,
  with its run log flush under it; a chevron `IconButton ghost-muted
icon-xs` toggles the runs.

## Monitoring pages: Analytics, Insights, Logs

The same three pages at two levels, under one group heading, Monitoring
(`navigation.sections.groups.monitoring`): an agent's sidebar puts Overview and
Schedules first, then Analytics, Insights and Logs; Settings' Monitoring group
holds the account's three (`/settings/analytics`, `/settings/insights`,
`/settings/logs`). Both lists live in `navigation/sections.ts`:
`buildAgentSection` for an agent (each item behind its `TAB_ACTIONS` action:
the Monitoring pages need `view_logs`, Schedules `manage_schedules`) and
`SETTINGS_SECTION`. Insights is `feature: 'analytics'`, listed only while
`/api/config` reports analytics on (`selectAnalyticsEnabled`, the one read in
the store); a deep link while it is off redirects (an agent's to its Logs,
Settings' to Analytics) instead of drawing an empty page. The workflow builder
has no sidebar: `AgentPageHeader` draws the same items flat and in order
(`getVisibleGroups(buildAgentSection(…)).flatMap`), five `NavTab`s with
Overview current, and `MobileBlocker` lists them after Overview as `outline`
Buttons; neither keeps a list of its own.

Page chrome (see Page chrome): the window select, `settings/TimeFilterSelect`
(`field pill`, `min-w-[125px]`, `SelectContent fit`; Hour, 24 hours, 7 days,
15 days, 30 days, the default last), is the toolbar's action on every
Analytics and Insights page: `AgentPageToolbar actions` on an agent,
`PageToolbar action` beside the `intro` in Settings. On an agent's Insights it
shares the slot with Settings (`outline field pill`, `Settings2` first), shown
only to a role that may edit the agent. Logs has no window select; Guardrail
activity keeps its own day select inside its panel. An agent's Logs is
Guardrail activity, then a `<section id="logs">` (the drill-down target, which
`revealElement` scrolls to) headed by a `SectionHeader` "Logs" with
agent-scoped copy. Each agent page reads the agent once (`useAgent`); a failed
read is `EmptyState tone="destructive" size="sm" illustration="none" onRetry`
under the toolbar.

Chart panels: every chart on Analytics and Insights is
`settings/insights/ChartPanel`, never a hand-built Card. It is `subtle lg`,
`min-h-[345px]`, and fills its grid row; the chart sits out of flow, so the
row's height comes from its tallest panel and never from a canvas. The title is
a `SectionHeader as="h2" size="xs"` (the panels sit straight under the page's
title), and `actions` share its wrapping row (Token usage's Group by select,
and its Background tokens switch pushed right with `ml-auto`). The body is one
of: `loading`, the `analysis` SkeletonLoader in the chart's place under the
real title; `error` with `onRetry`, the destructive `EmptyState size="sm"`
("Could not load this chart." on Analytics); `empty`, an `EmptyState size="sm"
illustration="none"` saying why there is no figure yet; `children`, an in-flow
body that sizes itself (Insights' share bars when there is no trend to draw);
else the chart and its legend container. `summary` sits in flow between the
title row and the body (Insights' headline), and only with figures. Analytics pairs them in `xl:flex-row` rows; Insights lays them
in `grid-cols-1 xl:grid-cols-2` with `gap-3`, in rows of equal height.

Insights (`settings/insights/ConversationInsights`, the body of an agent's
Insights and of Settings › Insights) draws one state from `insightsState`.
Only `partial` and `ready` (`showsFigures`) draw the intro, the language note
(an `info` Alert, `role="note"`), the tiles, the panels and Docs gaps; every
other state is one `EmptyState size="sm" illustration="none"` that names its
next step, and the panels say nothing about it:

- `agentOff`: "Insights are off for this agent" and, for a role that may edit
  it, Turn on (`outline field pill`), which opens the settings drawer already
  switched on.
- `noTraffic`: "No conversations in the last 30 days", named by the window.
- `analyzing`: "Analyzing conversations", "12 of 40 answers analyzed · newest
  first" (`tabular-nums`) and a `Progress` in the action slot (`w-64 sm:w-96`),
  only while unlabelled answers sit inside the labelling window and fewer than
  `MIN_SAMPLE` are done.
- `olderOnly`: every answer in the window predates the labelling window ("Insights
  cover conversations from 13 Oct onwards…", the date in `headingLocale`).
- `loading` is `InsightsSkeleton`: the five tiles and the four panels every
  window has, in grid order under their real titles, so nothing moves or
  renames when the figures land; `error` is the destructive EmptyState.

The intro ("Estimated by an AI model from each conversation.", Learn more to
the docs' `#conversation-insights`, and "N of M answers analyzed" while
`partial`) shows only above figures: Settings passes it as the toolbar's
`intro` (`InsightsIntro`, with `intro={false}` on the body), an agent's page
draws it inline. Figures are the estimate alone: no confidence ranges and no
tier badges (both stay in the API, and the ranges in the CSV). The guard is
`MIN_SAMPLE` (10): under it a tile reads `—` with "Not enough data yet (6 so
far)", a panel "Not enough data yet", a tag row `—`.

- Tiles are five `StatCard`s in `grid-cols-2 md:grid-cols-3 lg:grid-cols-5`, the
  last `col-span-2 md:col-span-1` so it never sits alone on a phone (Analytics'
  five cards take the same rule); `sub` names the denominator ("of 81
  questions"), `hint` what the figure counts.
- The two chart panels (Answer status, How users replied) open with an
  `InsightHeadline` in `ChartPanel summary`: the period's figure (`text-2xl
  font-bold`), what it is and its denominator ("of 67 questions"), and
  "Previous period: 63%" with an up, down or equal arrow once the previous
  period (`previous` in the API) has `MIN_SAMPLE`. Over time they draw counts,
  never shares, so a quiet week is a short column: `AnalyticsChart
  columnTooltip` (one tooltip per column with each non-empty series rounded,
  "<1" for slivers, the bucket's count in the footer; level x labels). The
  headline's mix strip and its legend ("Fully answered 59%") name the series,
  so the chart draws no legend. Buckets are the API's `bucket_unit` (it
  coarsens days to weeks while they average under 10 answers), labelled by
  `bucketLabel` ("17 Oct", "13–19 Oct", "14:00"). Fewer than `MIN_BUCKETS` (3)
  buckets with `MIN_SAMPLE` items each is no trend: the panel shows the
  period's mix as `ShareBars` under the headline, without the strip, each bar
  in its series' colour (the row's `tone`, a `Progress` variant; `muted` for
  the neutral kind).
- Answer status stacks the four outcomes; greetings are not drawn. How users
  replied reads the same replies two ways, switched by a `ToggleGroup
  size="xs"` (Replies to answers / Sentiment) in the title row: the good kind
  up from zero, the bad kinds down (`AnalyticsChart diverging`, the zero line
  in the tick colour), the neutral kind (Moved on, Neutral) in the headline
  only, with a muted line saying it isn't drawn. As bars it shows both under
  `SectionHeader as="h3" size="sm"` headings, without the toggle.
  Series take colour by meaning (`success`, `warning`, `destructive`, `info`
  for Asked for details); a series that is no failure, "Said it didn't know",
  Neutral and Moved on, is `muted-foreground`.
- Share lists (Request type, Why not fully answered, Topics) are
  `ShareBars` in a `subtle lg` Card with a `SectionHeader as="h2" size="xs"` and a
  muted `text-xs` "Share of N answers" line: per row the label (`text-xs`,
  wrapping, `sm:w-40`), a stock `ui/Progress` (the brand colour: these
  options have no good or bad) and the whole percent, as one
  `sr-only` text run ("How-to: 38%") with the drawing `aria-hidden`. A panel
  left alone on the last row spans both columns and lays its rows in two.
- Topics (agent pages only; each agent has its own list) always spans both
  columns, after Why not fully answered. With both kinds it is two halves, from
  `xl` side by side, each under a `SectionHeader as="h3" size="sm"` named as the
  settings groups (One per question, a share of messages; Can overlap, a share
  of conversations, with a muted "don't add up to 100%" line), each list named
  by its heading. With one kind, its bars in two columns and no halves. An
  overlapping topic under the sample floor reads `—`; the rows sort by share.
  Without either kind it is left out, except for editors of an agent that asks
  no topic question: `EmptyState sm` with Set up topics (`outline field pill`),
  which opens the settings drawer.
- One name per label on every surface (charts, tiles, Logs): Replies to
  answers, Docs gap, Asked again or pushed back; copy says "analyzed", never
  "labelled".

Docs gaps (`settings/DocsGaps`) is its own section after the figures,
`id="docs-gaps"` (the weekly summary's target, scrolled to once it has
loaded): a `SectionHeader` whose `actions` are the Page / Source / Topic
`ToggleGroup` (Topic only on an agent with topics that don't overlap; the pick kept in
localStorage) and Export CSV (`outline field pill`, `Download` first). From `lg`
the rows are a `Table`; below it, `filled interactive` tiles with a
`MetaSegment` line. A row opens a `SidePanel`: the page name as its title, then
the source and the URL (`font-mono text-xs wrap-anywhere`) as its description,
a `DescriptionList` (Gaps, Share of questions, Previous period) and the examples
as interactive `ListRows` linking into Logs.

- Page names drop the tail that every titled row shares (`pageNames`; per
  source when not all rows share one); the CSV keeps the full title. The
  source is a muted second line: always in Settings, where the page alone
  doesn't say where it is from, and on an agent only when its rows name more
  than one source.
- Change: `—` (with an `sr-only` "No earlier data") until the previous period
  has labelled answers (`previous_labelled`), then "New", a `Minus` for no
  change, or an arrow with `+N` / `−N`. The text stays plain (`muted-foreground`
  for New and the dash, foreground for the number); only the arrows take a
  hue: up `destructive`, down `success`.

Logs label chips (`settings/LabelChips`, in the row's header) are text-only
`Badge`s, since status and outcome badges carry no icon, coloured by meaning:
`warning` where the answer needs attention (Docs gap, Not fully answered,
Asked for a person), `destructive` where the user is upset (Asked again or
pushed back, Negative sentiment, Frustrated), `neutral` for the agent's
topics that can overlap (truncating at `max-w-48`) and the "+N" for the rest (named in `sr-only`). At
most three; a docs gap stands for not fully answered, frustrated for negative
sentiment. The Logs filter selects are named (`aria-label`), `field pill` with
a `min-w-[…]` and `SelectContent fit`; the label select is there from the first
paint (the flag from Redux) and, on an agent, only while it collects insights.
On an agent it ends with a Topics group: every topic, as `/api/analytics/topics`
lists it (folders included), sorted by name and without badges.

Insights settings are one body, `agents/components/InsightsSettingsBody`, in
three hosts that each save it their own way:

- Overview's Insights section, `AnalyticsSection`: a collapsible form section
  (see Agent pages) saved by the agent's Save; the source folders load only
  once it opens (`active`).
- The Workflow details card (`subtle lg`, `SectionHeader as="h3" size="xs"`, the
  body at `headingLevel="h4"` with `topicSource="none"`), saved by that sheet's
  Save.
- The Insights page's Settings drawer, `InsightsSettingsSheet`: a modal
  `SidePanel` with `PanelHeader` (the agent's name as description) and its own
  Cancel / Save, which saves only `config.analytics` on top of the saved config,
  so it never meets unsaved Overview edits. Turn on opens it with
  `startEnabled`.

The first two hide while the server has insights off, unless the agent already
has settings of its own, and then show an `info` Alert that they don't run yet.
The body edits `value` only and renders sibling blocks for its host's
`flex flex-col gap-5`: Collect insights (`SettingRow` and `Switch`, with Learn
more to the docs' `#analytics-settings-for-an-agent`); then, only while it is
on, Topics; then the Weekly docs-gap summary switch.

Topics is one `SectionHeader size="xs"` (the `count` is the rows shown) with
Add topic (`outline sm`, `Plus`) over one `Card variant="subtle"
padding="none"`:

- Rows: the source folders (a `neutral` From sources `Badge` with `Folder` in
  the title) and the owner's own topics, by name. A folder's ⋯ is Edit (it
  becomes an own topic and the folder hides) and Hide; an own topic's is Edit
  and Remove, after a separator, confirming only for one that can overlap,
  whose results go with it. Each ⋯ is the same `ActionMenu`.
- Groups: none until a topic can overlap; then One per question and Can
  overlap, each under a `SectionHeader size="sm"` one heading level down, named
  as the halves of the Insights Topics panel.
- Notes under the rows, muted `text-xs` lines with a `link` `size="text"`
  action: hidden folders (Show), folders past the limit, folders that failed
  (Retry), one topic on its own, both limits reached (Add topic leaves), the
  folders that come after the first save, and the folders a read-only caller
  can't list.
- Empty: `EmptyState sm` with `illustration="none"` in the card, its copy by
  cause (a workflow, unsaved, no folders, every folder hidden with Show
  folders); three skeleton rows while folders load.

`TopicModal` adds and edits both kinds: name, optional description (its
budget, and the counter past 80%, follow the kind), Can overlap other topics
as a `SettingRow` and `Switch` (off by default, locked when the other kind is
full, absent when the server allows none), then a muted line on what the change
reaches, or a `warning` Alert when an edit changes the kind. Workflows pass
`topicSource="none"` and never load folders. A confirm or the dialog keeps its
copy while it animates closed (`useKept`).

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
- Tools and Knowledge show what is on without opening the picker. Tools
  adds a `Badge` with the count of tools on in this chat. Knowledge names
  a single source; with several it keeps the "Knowledge" label, adds the
  count `Badge` and lists the names in its `title`. The badge is
  `tabular-nums` and `aria-hidden`; the trigger's `aria-label` says the
  count instead. With nothing on (or one source), neither has a badge.
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
An answer its user stopped before it wrote anything (`error_code: "stopped"`)
is the same block as a note, `Alert variant="info" role="note"` titled
`conversation.stoppedTitle`, with the same Retry and Copy: nothing failed.

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

An answer's artifacts (files and notes its tool calls made, and its
workflow run's files) are cards between the answer and its action row
(`components/ArtifactCard`, built by `conversation/artifactCards`), never
chips in the action row, which holds only the answer's own actions:

- A card is the answer's surface (`bg-answer-surface`, `hover:bg-accent`,
  `rounded-2xl p-3`): the kind's lucide icon on the brand soft fill
  (`bg-secondary text-secondary-foreground`, a 40px `rounded-xl` square; the
  grey icon tile would vanish, as `muted` is the answer surface in light),
  the title (the artifact's title, else its filename) and a muted meta line,
  the kind and the version its turn made ("PDF · v2"). The whole card opens
  the artifact in the side panel on that version through a stretched button
  named by the title; Download (`ghost-muted icon-sm pill`, `z-10`) saves
  that version (DESIGN.md › A clickable card that holds a link). The card the
  panel shows is `bg-secondary` (the open-row rule).
- The list is a container query: two columns once the answer column fits two
  (`@min-[33rem]`, across the full answer column), one below that, so the builder
  preview's narrow column stacks them on any screen. Its outer box is
  `w-full min-w-0`: in the answer's wrapping flex column a container-query
  box has no width of its own and lays its height out as if stacked.
- Order: documents (HTML, PDF, slides, documents, spreadsheets, notes), then
  images, then data and other files, each in the order produced; one card per
  artifact.
- Past four, the first three cards and a fourth, "N more files · Show all
  M", with a chevron instead of Download, that opens the answer's list in the
  side panel (`conversation/ArtifactsPanel`): `ListRows` grouped by kind
  under `SectionHeader size="xs"` with counts, in a `subtle` Card, each row
  opening that artifact as the panel's second level with Back to the list,
  the Sources pattern. The fourth card is open while its list shows.
- A workflow run's files are listed only where they can open (not in a
  shared chat), quietly: no spinner, nothing for a run that made none, a
  destructive `EmptyState` with Retry when the list fails.

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
  explainer box. Actions on the right, source-level only: Test retrieval
  (`outline field pill`), the kind's one primary action (`default field
  pill`, text only: Add file for an upload, Add pages for a website, Sync now
  for a synced source, none for a wiki or a graph), then the source's ⋯
  (`ActionMenu size="toolbar"`, PathHeader's `menu`, always last). The ⋯ is
  `settings/useSourceActions`' `menuOptions(doc, 'view')`: the card's menu less
  View and Test retrieval (and less Sync now where that is the primary); its
  Delete is "Delete source" and returns to the list. File and page actions
  never sit in this row.
- **Synced sources** (`settings/sourceKinds` `isSyncedSource`: a connection, a
  connector type or a schedule, whatever the stored type, so S3 and GitHub
  too) open in `ConnectorTree`: the connection's badge, the schedule in the
  byline ("12 files · 13,080 tokens · Weekly · synced 2 days ago"), Sync now,
  and no Add file or file Delete (a sync replaces them). A website keeps
  WebsiteTree and Add pages, with Sync now in its ⋯.
- **Source menu** (the card's ⋯ and the view's): View, Reingest (a failed
  ingest only), Sync now, Settings, Test retrieval, Convert to wiki, Share with
  team, then Delete after a rule (`separatorBefore`); never more than that, and
  no per-value rows (the schedule is a field in Settings). Settings is one
  dialog, `SourceConfigModal`: its first section depends on the kind (a
  website's pages, skips, Keep links and schedule; a synced source's "Keep up
  to date"; nothing for an upload), then RetrievalOptions, with Sync now in the
  footer; a viewer with `view_config` reads only the retrieval part. A wiki's
  Settings is WikiSettingsModal. A card whose source has a schedule shows
  "{frequency} · synced {when}" instead of its date, and "via {connection} ·
  N files" for a connection.
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
- **Item bar**: an open file or website page (TreeBrowser: uploads, websites,
  synced sources; a wiki page has the Reader) has `tree/ItemBar` above its chunks, the
  same wherever it was opened (table, navigator, citation, the one-file
  shortcut): a `subtle` Card with one `ListRow`, the item's icon and name, its
  address (`link inline` with ExternalLink) or size, muted counts ("N chunks ·
  N tokens · fetched …") and the row's ⋯ less View. The source's last item has
  no Remove or Delete (Delete source covers it), and an empty menu draws no ⋯.
  Notices about the item (a synced website's hand-edits note) go under the bar.
  The header byline stays the source's. Leaving the navigator with the pointer
  hands cmdk's highlight back to the open item, so only one row looks picked.
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
  Files tab's Add file or Sync now, portalled through `TreeBrowser`'s
  `actionsTarget`), as on the agent pages; the embedded tree draws no row of
  its own. A website source's page changes and the syncs started from its ⋯
  are held by the graph view (`tree/useWebsiteChanges`), not by the Files
  tab's WebsiteTree, which mounts only while that tab is open: they finish
  and toast whichever tab shows, the running one's muted label ("Syncing the
  source…") sits after Test retrieval on the other tabs, and the view reports
  them (`onBusyChange`) so the ⋯'s Sync now is off meanwhile. Overlapping
  changes each hold the busy state until the last ends. The Graph tab's toolbar holds the
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

Add knowledge's forms (Upload, Website, New wiki): Name first, the
kind's fields, then the `Advanced settings` disclosure, and one submit, "Add to
Knowledge", for all three. A wiki's "Initial content" is a default Textarea
with its hint in FormField `hint`. A website's "Keep links in page text" is a
Website field (`WebsiteFields keepLinks`), not a chunking setting.
`settings/components/RetrievalOptions` is flat groups with `GroupHeader`
eyebrows (h3, "· tag"): Retrieval · Relevance · Filtering · Graph retrieval ·
Graph extraction · Chunking, never a nested toggle. `variant="create"` (the
add forms and the connector wizard's sync setup) drops the re-ingest tags and
the Filtering group (unless inherited LLM screening doesn't add up) and ends
with the muted "Fine-tune filtering after the first ingest…" line; Source
settings, Test retrieval and admin Defaults use the default.

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

The drawer's "Knowledge from this connection": with nothing synced, an
`EmptyState size="sm"` with an outline "Sync content"; with sources, the header
link "Sync more content". Each source row opens the source in Knowledge
through a stretched button, its description worded as the source's card
("Weekly · synced 2 days ago"), and its ⋯ is Sync now (connected and not
paused only; a row `Spinner xs` and a disabled item while it starts) and Open
in Knowledge. Syncs this session started show first as neutral "Indexing"
rows ("First sync started …") until the server lists the source
(`connectorsSlice.startedSyncs`).

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
service's description, then the account: "Signed in as …", or "Connected
with the key ending …" for a pasted key). Every step title names the service
("Choose what to sync from GitHub") and doesn't change with a choice. A
sync-only connector (`setup.tools === 'off'`: S3, Drive, SharePoint,
Confluence, Reddit) asks how to use it on its first connect with two `OptionCard`s in a
`role="radiogroup"`, "Sync content now" (picked from any entry point) and
"Just connect"; the setup form sits under them behind a `Separator` in a
Collapsible that folds away on Just connect and keeps its values. A connector
with tools and sync (GitHub, Linear) keeps one switch each. The setup step's
footer is one submit named by what it does ("Add to Knowledge" while syncing,
else "Finish setup"; Cancel + "Add to Knowledge" when syncing more), never
Skip. Every path ends on the done step, whose summary is a `success` Alert
that reports and never gives directions; its footer follows what happened: a
lone Done after a reconnect; Done + "Open in Knowledge" (the first new source)
when sources were created; Done + "Try it in chat" (a new chat with no sources
picked) when only tools were turned on; outline "Sync content" (the sync step
in place, on the account just connected) + Done when nothing syncs yet. With several accounts and none chosen, the
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

## Activity (`activity/`)

A section like Settings: `activity/index.tsx` puts Now, Calendar and History,
then the Automations group (Schedules across every agent, and Monitors, which
moved here from Settings; `/settings/monitors` redirects) in `ACTIVITY_SECTION`,
and below `lg` the root is the `SectionIndexPage`. Times on these pages are
24-hour `formatClock`, and day and range headings use `headingLocale()` (see
the dates rule in DESIGN.md › Pagination); a monitor's end is `formatDeadline`, the one
time in the browser's own clock.

A sidebar chat carries one status mark, `activity/ConversationMark`, in a
fixed `size-4` slot so every mark's centre lines up. It shows the most urgent
state the chat is in: failed (`bg-destructive` dot), needs you (`bg-warning`
dot, an approval waiting), working (`Spinner size="xs"`), unread
(`bg-primary` dot), watching (a hollow `border-muted-foreground` ring:
something is on, nothing to do). The tooltip names every state, joined with
` · `. A new chat state joins `useConversationStates` at its place in that
order; it never gets a second mark beside the first.

The sidebar's Activity row ends in `ActivityNavBadge`: a dot while something
needs the user (red only when a schedule paused itself after failures, else
amber) and the running count (`formatCount`), `text-xs text-muted-foreground
tabular-nums`, named by a `Tooltip` on the right as ConversationMark is. On the
collapsed rail it is the dot alone, at the icon's corner, and the
counts are an `sr-only` span the icon button names with `aria-describedby`.
`useActivitySummary` is the one count for the row and the Now page.

A Now row's leading icon is the `Avatar variant="icon" size="sm"
shape="square"` tile; in Needs you a waiting row's tile is `bg-warning/10
text-warning` and a failed one's `bg-destructive/10 text-destructive`, the
same `size-8 rounded-md` square (Avatar has no status tone). Running rows end
in an `info` Badge.

Calendar events take their look from `calendar/layout.ts`, never inline
classes: `STATE_CLASS` per run state and `SYNC_CLASS` for a knowledge sync,
and the legend reads the same maps. A planned slot is the brand soft fill
with a `border-l-2 border-primary` stripe; a run is `bg-<role>/10` with a
full-strength `border-l-2 border-<role>` stripe, because on a 20px block a
`/50` stripe disappears; skipped and paused are a dashed
`border-muted-foreground` on the background, missed the same dash in
`border-warning` (nobody chose it: the scheduler was down), a sync is
`bg-muted` dashed. A running run adds a pulsing `bg-info` dot. Event hover is
`hover:brightness-95`, the calendar's exception to the fill-change hover: an
accent fill would hide the state colour. Events are raw buttons positioned
with `--top` / `--height` custom properties, so each carries `focusRing` and
`outline-none`.

The pages stay live without a reload: the Now snapshot (`activitySlice`) is
loaded every 60 s by `useActivityLoader` and refetched, debounced, on the
realtime events that change it (`message.*`, `schedule.*`, `job.updated`,
`workflow.run.step`, `activity.updated`). A relative time or an Overdue label
re-renders through `useClock`, never a timer of its own.
