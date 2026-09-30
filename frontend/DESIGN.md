# DocsGPT frontend design system

The UI is Tailwind v4 plus the shadcn-style components in
`src/components/ui/`. `@shadcn/lint` and the `no-restricted-syntax`
selectors in `eslint/` enforce the rules below through `npm run lint`; their
messages point here. Everything in this file is either a
token in `src/index.css` or a variant in a `ui/` component, so an agent or a
contributor can always find the concrete thing to use.

## Rules in one paragraph

Pages compose `ui/` components and choose their look through props
(`variant`, `size`, `shape`). `className` on a component is for placement
only: margin, width, flex and grid, positioning. Colours come from the theme
tokens, never from the raw Tailwind palette. Spacing, type and radii come
from the Tailwind scale, never from arbitrary `[...]` values. Runtime values
go in CSS custom properties or, when unavoidable, an inline style with a
disable comment. Conditional classes go through `cn(...)`, never a template
literal (prettier sorts the classes inside `cn`, and `cn` merges conflicts).
What a role may do is gated with `can(item, action)` and a refused action is
not rendered (see Access and roles). Every user-visible string, attributes included (`aria-label`, IconButton
`label`, `placeholder`, `title`, `alt`, `hint`), is a `t()` key in all seven
locales (`de en es jp ru zh zh-TW`); admin pages are English by design.
Interpolated user text (a name, a timezone, a date) passes `interpolation: {
escapeValue: false }`, or `/` renders as `&#x2F;`.

## Colour tokens

Defined in `src/index.css` (`:root` for light, `.dark` for dark) and exposed
through `@theme inline`, so `bg-`, `text-`, `border-`, `ring-`, `fill-` and
`stroke-` all accept them, including opacity modifiers such as
`bg-success/10`. One token class replaces a light + dark pair.

| Token                                   | Use for                                                                           | Replaces                                                            |
| --------------------------------------- | --------------------------------------------------------------------------------- | ------------------------------------------------------------------- |
| `background`, `foreground`              | page surface and primary text                                                     | `bg-white`, `text-gray-700/800/900`, `dark:text-gray-200/300`       |
| `card`, `card-foreground`               | raised surfaces (cards, dialogs, dropdowns)                                       | `bg-white dark:bg-[#2b2c31]`                                        |
| `popover`, `popover-foreground`         | floating menus and popovers                                                       | same as card                                                        |
| `muted`, `muted-foreground`             | quiet fills and secondary text, icons, placeholders, timestamps                   | `bg-gray-100/200`, `text-gray-400/500/600`, `dark:text-gray-400`    |
| `accent`, `accent-foreground`           | hover and selected fills                                                          | `hover:bg-gray-100`, `dark:hover:bg-gray-700`                       |
| `border`, `input`, `ring`               | dividers, field borders (fields use `border-input`, `fieldFrame`), focus rings    | `border-gray-200/300`, `dark:border-gray-600/700`                   |
| `primary`, `primary-foreground`         | brand purple: primary actions, links, selected states                             | `bg-purple-*`, `text-purple-*`, `#7D54D1`, `#A076F6`                |
| `secondary`, `secondary-foreground`     | pressed and active toggles (a brand tint), secondary buttons, the question bubble | `bg-accent` on an active icon button                                |
| `destructive`, `destructive-foreground` | errors, failed states, dangerous actions                                          | `text-red-*`, `bg-red-50/100`, `#B42318`, `#E60000`                 |
| `success`, `success-foreground`         | completed, active, healthy                                                        | `text-green-*`, `text-emerald-*`, `bg-green-50/100`                 |
| `warning`, `warning-foreground`         | paused, pending review, degraded                                                  | `text-amber-*`, `text-yellow-*`, `text-orange-*`, `bg-amber-50/100` |
| `info`, `info-foreground`               | running, informational                                                            | `text-blue-*`, `bg-blue-50/100`                                     |
| `sidebar-*`                             | the navigation rail                                                               |                                                                     |
| `chart-1` to `chart-5`                  | data series only, never UI chrome (see below)                                     |                                                                     |
| `answer-bubble`                         | the source cards under an answer and the answer-side panels (AnswerFlow)          |                                                                     |

Status colours are tuned to stay vivid rather than turning brown or olive,
so their contrast is low. Against white in light mode, `destructive` and
`success` are about 3.8:1, `warning` is 2.9:1 and `info` is 5.2:1. On the
dark card, `destructive` is 2.9:1 and the others are 5.5:1 or more. Do not
use them for long body text; they are for badges, icons, short labels and
fills.

The dark `primary` (#8855f1) is set so white text on it reaches 4.55:1 on
every default Button. As text on the dark surfaces it is below 4.5:1 (3.45:1
on background, 3.06:1 on card), so links and `text-primary` in dark pass only
as large or UI text; a fix for that needs its own link token. `ring`,
`secondary` and `sidebar-primary` keep the lighter #976af3.

Chart colours are not a separate palette. `chart-1` to `chart-5` alias
`primary`, `info`, `success`, `warning` and `destructive`, in that order,
so the charts use the same colours as the rest of the app in both themes.
A single series uses `chart-1`, the brand colour. When a series has a
meaning, use the token for that meaning, not the next one in order:
failed tool calls use `destructive`, succeeded ones `success`, pending
ones `warning`. Series with no meaning (models, agents, sources) take
`chart-1` to `chart-5` in order. When there are more than five, the four
largest keep `chart-1` to `chart-4` and the rest are summed into one
"Other" series in `chart-5`, so no colour repeats (`settings/foldSeries.ts`).
`secondary` is never a chart colour. The knowledge graph is the one
place Other is not `chart-5`: its entity types have no meaning to map, and
half a graph often folds into Other, so red would read as "these failed".
There the four largest types take `chart-1` to `chart-4` and Other is
`muted-foreground` (`foldGraphTypes`, `readGraphPalette` in
`components/graphViewUtils.ts`).

The status set is `success | warning | destructive | info`. `default` is the
component's own base tone (brand on a Badge or Button, quiet on an Alert or
Toast). `neutral` is the grey pill or box.

One tint scale, by purpose:

- Wash `/5`: a whole surface that is selected or receiving a drop (Card
  `selected`, Dropzone drag-active and drag-reject). The border carries the
  state; the wash only warms the surface. Never on a chip or a text fill.
- Brand soft fill: `bg-secondary text-secondary-foreground` (Badge `default`,
  Avatar `primary`, the OptionCard icon square), never `bg-primary/10`
  (enforced).
- Status soft fill: `bg-<role>/10` in both themes (Badge, Alert, ToastHeader,
  a danger-zone panel); no `dark:` twin.
- Status border: `border-<role>/50`.
- Tinted hover on a row that is already accent: `/15` light, `/20` dark
  (`ghost-on-accent`, `ghost-destructive-on-accent`, a destructive menu item).
- Neutral hover: solid `bg-accent` in both themes (ghost buttons, combobox,
  SelectTrigger, Card `interactive`, Dropzone, every list-row highlight).
- Quiet panel inside a page or card: `bg-muted`, not `bg-muted/40` or `/60`.
  It is a small box inside a panel (a well, a guardrail stage), never a
  page-sized panel around cards (see Card surfaces).
- Dividers: `border-border`, not `border-border/60`.

Patterns:

- Status pill: `<Badge variant="success">`. Status box: `<Alert variant="warning">`.
  Reach for `bg-success/10 text-success` directly only on dots and borders.
- Solid status fill: `bg-warning text-warning-foreground`.
- Guardrail outcomes: block `destructive`, flag `warning`, redact `info`,
  not evaluated `neutral`.
- De-emphasised text: `text-muted-foreground`; go lighter with an opacity
  modifier (`text-muted-foreground/70`) rather than a lighter grey.
- Text on the brand colour is `text-primary-foreground`, not `text-white`.
- `secondary` is a brand tint, not a grey: primary at 10% (light) or the
  lighter #976af3 at 15% (dark) over whatever sits behind it, with `primary` text in light and a
  lighter purple (#b89cf8) in dark. So a pressed toggle (CopyButton's copied
  state, text-to-speech while speaking) shows on card, background and muted
  alike, and never reads as the neutral ghost hover. Use it as
  `variant={active ? 'secondary' : 'ghost-muted'}`. That is for one thing
  switched on or off. Picking one value of several (a 7d / 30d / 90d range,
  a schedule's frequency, a filter row) is a `ToggleGroup`, whose on item has
  the `outline` look with no hue.
- A brand chip, a small action that opens something an answer produced (an
  artifact chip under an answer, a citation pill in its text), is also
  `variant="secondary" shape="pill"`: the default size with a lucide icon
  first for artifacts, `size="xs"` for citations. It is the same tint as a
  pressed toggle; the difference is that a chip never toggles and always
  opens or scrolls to something. The citation pill keeps `h-5 min-w-5`
  (20px) so it sits in a line of text.
- The user's question bubble is `bg-secondary text-foreground`: the brand
  tint as the fill, with body text in `foreground` (15.7:1 light, 12.4:1
  dark) rather than `secondary-foreground`, which is only 4.5:1 in light.
  Controls on it (the collapse chevron) are plain `ghost` with a lucide icon
  in `currentColor`.
- `white`, `black`, `transparent`, `current` and `inherit` are allowed; use
  them only for overlays and imagery, not for text or surfaces.
- Swapping a state's colour for its same-hue token (amber to `warning`, red
  to `destructive`) is fine without review; changing the hue of a state the
  user sees (an error, a recording state, a selected tab) is a design
  decision. Non-state UI follows the token even when its hue shifts.

## Components and their variants

### Button (`ui/button.tsx`)

| Prop      | Values                                                                                                                                                                                                                                                 |
| --------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `variant` | `default`, `secondary`, `outline`, `outline-primary`, `ghost`, `ghost-muted`, `ghost-destructive`, `ghost-on-accent`, `ghost-destructive-on-accent`, `link`, `destructive`, `destructive-outline`, `combobox`, `sidebar-item`, `tab`, `section-toggle` |
| `size`    | `xs`, `sm`, `default`, `lg`, `field`, `icon-xs`, `icon-sm`, `icon`, `icon-lg`, `inline`                                                                                                                                                                |
| `shape`   | `default` (rounded-md), `pill` (rounded-full, wider padding at `default`, `lg` and `field`)                                                                                                                                                            |

- Round brand buttons (`rounded-3xl px-5`, `rounded-full px-6`): `shape="pill"`,
  plus `size="lg"` if they were `px-6`.
- Muted icon buttons (`text-muted-foreground hover:text-foreground`):
  `variant="ghost-muted"`.
- Icon actions that remove something (a trash can on a member or shared
  resource row) are `variant="ghost-destructive"`: muted at rest, red on
  hover, so the warning shows even where the click deletes without asking.
- Icon buttons on a row that is already `bg-accent` or `bg-sidebar-accent`
  while you point at it (a highlighted Command item, a card or tile with
  `hover:bg-accent`, a hovered sidebar row) are `variant="ghost-on-accent"`
  (delete: `ghost-destructive-on-accent`). They hover with a
  `foreground/15` (`destructive/15`) tint, which shows on accent where
  ghost's accent square would not.
- Icons are `lucide-react` at the default stroke (2). Don't pass
  `strokeWidth`, and don't use an `<img>` for a glyph lucide has. The one
  exception is a tiny glyph inside a status circle or chip (the custom-model
  test result and capability chips, the artifact and research step ticks,
  `ToastStatus`'s four status icons), drawn at 2.5 to 3 so it stays legible
  at 10 to 12px; raw progress-ring `<svg>`s are not icons.
- Icon size is one `size-N` class (never `h-N w-N`, never lucide's `size`
  prop); colour goes on the icon (`text-muted-foreground`), spacing on the
  parent (`gap-*`, not `mr-2` on the icon). Use current lucide names
  (`TriangleAlert`, `CircleAlert`, `CircleCheck`, `CircleX`, `Trash2`,
  `CodeXml`, `Search`), no `as` aliases. Inside a Button the size comes from
  the Button: 16px, 14px at `xs`, 20px at `size="icon"`; write a `size-N`
  only to differ from it, since any `size-` class switches the default off.
- Bordered purple buttons (`border-primary text-primary hover:bg-primary`):
  `variant="outline-primary"`.
- Tiny inline actions (`h-auto px-2 py-1 text-xs`): `size="xs"`.
- A link inside running text (an artifact link in an answer, a link in
  markdown, a hint's "Learn more") is `variant="link" size="inline"`, with
  `asChild` around the `<a>`: no height or padding, underlined on hover, the
  shared focus ring. Standalone links ("Learn more" with `ExternalLink`, "Go to
  Tools" with `ArrowRight`) are the same, the icon a child. Toggles and crumbs
  keep a normal size. The base is `text-sm font-medium`, so a link in a 12px
  hint passes `text-xs font-normal` (an approved exception), and a link that
  must keep the colour of what it sits in (a status Alert, a dark overlay, a
  source card's URL row) passes `text-current`. Never style a raw `<a>` as a
  link (enforced).
- Icon-only buttons: see IconButton below. A `title` on a `Button` is
  rejected (enforced).
- An action whose label doesn't fit beside a name on a phone (the shared
  agent card's Edit, in a long locale) is two elements: an `IconButton`
  with `sm:hidden` and the labelled `Button` with `hidden sm:inline-flex`.
  Never hide a Button's label span, which leaves an icon-only Button.
- Roles for dangerous and dismissive actions: a delete on a page (a "Danger
  zone" card's Delete agent or Revoke, Delete all) is `destructive-outline`;
  the submit of a confirm dialog is `destructive` (`ModalActions destructive`,
  `ConfirmationModal variant="destructive"`); Cancel is `ghost` at the size and
  shape of the button beside it, in a modal footer, a form header or an inline
  editor. A Cancel inside a line of text (the composer's queued send) is
  `link inline`.
- The composer controls under the chat field (Attach, Voice, Tools,
  Sources) are `outline sm pill`. Their icons are `size-3.5 sm:size-4`
  with no margin; the size's `gap-1.5` spaces them, and the label span keeps
  `text-xs sm:text-sm` so the row still fits on a phone.
- Popover comboboxes (`role="combobox"` + `Command`) use `variant="combobox"`,
  which matches `SelectTrigger`: card fill, normal weight, and muted text
  while `data-placeholder` is set (`data-placeholder={value ? undefined : ''}`).
  Pass only layout (`w-full justify-between`) and keep the chevron as the
  last child.
- A button or picker that sits in a row of fields is `size="field"`: 38px.
  `Input` and `SelectTrigger` take `size="field"` too (the same 38px as
  Input `default`), so a form column has one name for one height. Page
  actions beside a page's search field (Add Source, Add Tool, Test
  retrieval, Sync) are `size="field" shape="pill"` too, with no min-width
  or hand height. With `shape="pill"` its text starts 21px in, like the
  Input and Select pills beside it. The agent form's pickers are
  `combobox field pill`, each labelled by a `FormField` (the Prompt picker
  through `Prompts titleAs="field"`), its Add button `outline-primary field
pill`, the only `outline-primary` on the agent pages themselves (the Access
  details modal they open has its own).
- One variant and size per role on the agent pages (Overview, Logs,
  Schedules, the workflow builder's toolbar): the page's primary action is
  `default field pill` (Publish, Save, New schedule), a secondary action
  `outline field pill` (Save draft, Preview with `Play` first), Cancel `ghost
field pill`, and page-level actions go in the `ActionMenu` (`size="toolbar"`)
  at the end of the title row, through `SectionShell titleAction`: Access
  details and Share with team on Overview (each only when the role allows
  it, see Access and roles), and Preview until the agent is
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
- Rows in the navigation sidebar (`hover:bg-sidebar-accent … pl-3 gap-2.5
rounded-3xl`) are `variant="sidebar-item"`: left-aligned, full-radius, normal
  weight, `bg-sidebar-accent` on hover and while `aria-current="page"`. Use it
  with `asChild` around a `<Link>` for navigation rows, the label in a
  `truncate` span. A row that also holds buttons (an agent's pin, a
  conversation's menu, rename's Save / Cancel) puts the link and the buttons
  side by side in a `group relative` wrapper, never buttons inside the link;
  the link keeps its fill while the pointer is on a sibling with
  `group-hover:bg-sidebar-accent`. The section sidebar's "Back to app" row is
  the same variant.
- Inline disclosure toggles ("Advanced settings", "Show advanced options")
  are `variant="link" size="sm"` with only `-ml-3 w-fit justify-start`;
  a chevron, when the toggle has one, is a lucide `ChevronRight` (so it
  takes the link colour) as the first child.
- Underline route tabs are `variant="tab"`: muted text on a transparent 2px
  bottom border, square corners, no hover fill. Mark the current tab with
  `data-active`, which gives it `foreground` text and a `primary` underline.
  Padding-free tabs (a sub-nav with `gap-6`) add `size="inline"`, which keeps
  4px above the line; the row draws the 1px baseline, and `-mb-px` lays the
  underline over it. Its one use is `agents/AgentPageHeader.tsx`, the workflow
  builder's fixed toolbar: a breadcrumb, the status Badge and the Overview /
  Logs / Schedules tabs in a `<nav>` (no tabs until the workflow has an
  id), the others `<Link>`s and the current one a `<span
aria-current="page">` with `data-active`. The
  agent section pages switch with the section sidebar (the phone menu below
  `lg`) and carry no pill row; the agent tile's ⋯ also opens Logs. Tabs that switch a panel in place are
  `ui/tabs` with `variant="underline"` on `TabsList` and each `TabsTrigger`:
  the same pixels, plus `role="tablist"`/`"tab"`, `aria-selected` and
  arrow-key focus; wrap the panel in `TabsContent` (FilePicker's My Files /
  Shared with Me, Schedules' Recurring / One-time in
  `agents/schedules/SchedulesView.tsx`, the graph source view, the source
  edit drawer). Each trigger keeps its `px-4`, so the first label sits 16px
  in from the content edge and the underline runs past the label on both
  sides. That inset is deliberate (decided 2026-09-28): the tab row reads as
  its own strip, with a wider target per tab, so don't pull it flush with
  `-ml-4` or strip the padding. Only the workflow builder's toolbar, where
  the tabs share a row with a breadcrumb, uses the padding-free `Button
variant="tab" size="inline"`. The `default` variant is a pill tab, unused
  in the app. Panels unmount when hidden, except one whose state is costly to
  rebuild (the graph source view's laid-out canvas and zoom): that
  `TabsContent` takes `forceMount` plus `data-[state=inactive]:hidden`.
- A section panel's disclosure header (NewAgent's Advanced and Guardrails
  panels) is `variant="section-toggle" size="sm"` with `-ml-3 w-fit
justify-start` and `aria-expanded`: a lucide `ChevronRight` first
  (`rotate-90` while open) in primary, then the foreground title, with a
  primary underline on hover. Both call sites wrap the Button in an `<h2>`
  (a button flattens heading children, so the heading goes outside) and put
  the title in a `text-lg font-semibold` span. The button draws no focus ring; the panel does,
  so keyboard focus outlines the whole panel. The panel is a `Card` (a place,
  `subtle lg`), and every Card carries that ring
  (`has-[[data-variant=section-toggle]:focus-visible]:ring-3 … ring-inset`,
  inset because a scrolling column clips an outset ring), so pages pass
  nothing for it. Status badges go beside the button, not inside it, or the
  hover underline runs under them. Because the ring comes from the Card,
  `section-toggle` only goes inside a Card: a collapsible group in a Modal
  or drawer (Share's Access settings) is the inline `link sm` disclosure
  toggle above.
- Drop `text-white` on default and destructive buttons; the foreground token
  already provides it. Drop `disabled:cursor-not-allowed` on buttons; the
  base disables pointer events. Fields are the other way round (see Focus,
  elevation and stacking: "Disabled"). A disabled primary button just fades
  (`disabled:opacity-50`); never hand-roll a grey disabled state.
- A text button that removes something (Remove on a row) is
  `ghost-destructive size="xs"`: grey at rest, red on hover.
- A button that is busy (saving, creating, testing) takes `loading`: it
  disables itself, sets `aria-busy`, and draws a 16px spinner over the label,
  which stays in the layout (invisible) so the width doesn't jump. Keep the
  idle label; never hand-place a `Spinner` in a button, swap the label for
  "Saving…", or pin a fixed width to stop the jump. The one exception is a
  button whose busy state says something the user needs: a progress figure
  (a connector's Sync shows "42%") or a mode (the composer's Voice button shows
  "Transcribing"). It keeps its busy label with a `Spinner size="xs"` (the
  16px icon step, with a `label` so it doesn't announce "Loading") where its
  icon was.

### Card (`ui/card.tsx`)

| Prop          | Values                                                                                                                                                          |
| ------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `variant`     | `outline` (border + card surface, the default), `filled` (muted fill, no border), `subtle` (border on the page background); which one is decided by role, below |
| `tone`        | `default`, `destructive` (the status soft fill and border, `border-destructive/50 bg-destructive/10`, over any variant)                                         |
| `padding`     | `none`, `sm` (p-3, row boxes and code blocks), `default` (p-4), `lg` (p-6, tiles, panels and stat tiles)                                                        |
| `interactive` | whole card is the target: hover, focus ring and `selected` highlight; pair with `asChild` around a `<button>` or `<Link>`                                       |
| `selected`    | an `interactive` card that is the current choice: `border-primary` and the `/5` wash                                                                            |

Parts: `CardHeader` (title left, `CardAction` top-right), `CardTitle`,
`CardDescription`, `CardContent`, `CardFooter` (meta row, sticks to the
bottom). One radius for every card (`rounded-2xl`); pass only layout and
`gap-*` on `Card`. Children are spaced by Card's `gap-3`, so they carry no
`mt-*`. Replaces every hand-rolled
`rounded-(md|lg|xl|2xl|3xl|4xl) border bg-(card|muted) p-*` box.

#### Card surfaces: a thing or a place

The variant follows what the card is, not where it looks nice. Ask one
question: is it a **thing** you open, move, share or delete as a whole, or a
**place** where you read or edit content? The fill marks objects; the border
marks structure.

| Role                 | Variant                                                                           | Examples                                                                             |
| -------------------- | --------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------ |
| Thing (a tile)       | `filled`, on a page or in a modal                                                 | agents, folders, sources, tools, custom models, teams, chunks, the shared agent card |
| Place (a panel)      | `subtle` on the page or a right drawer, `outline` on a card (modal, bottom sheet) | the agent form's sections, chart panels, stat tiles, log tables, schedule rows       |
| Choice (picker tile) | `outline interactive`, or `OptionCard`                                            | the Add tool tiles; selection is drawn by the border, so the border stays            |
| Well                 | `filled padding="sm"`                                                             | code, a token to copy, run output, inside a panel (see Code blocks below)            |

- Layers go page → panel (border) → well (fill), or page → tile (fill).
  `subtle` and `outline` are one role on two surfaces; in light mode they
  look the same.
- An item that you read inside, rather than open elsewhere, is a place: a
  schedule is an item, but its row (`agents/schedules/ScheduleRow`) expands
  into a run table, so it is a `subtle` panel. The tile look is for a summary you open.
- **No fill on a fill.** Nothing on a `filled` tile repeats its muted fill,
  or it disappears: no `bg-muted` strip or box, no filled Card inside it, and
  Skeleton bars take `surface="muted"`. Put a meta line such as a token count
  in `CardFooter` instead of a muted header strip. The neutral Badge and the
  muted Avatar are `bg-muted-foreground/15`, a tint that shows on the fill,
  so they are fine on a tile. `no-restricted-syntax` enforces this for
  children written in the same JSX as the `<Card variant="filled">`
  (`eslint/card-surfaces.js`).
- Never a page-sized `bg-muted` panel around a page's cards: panels sit on
  the page background, as on Logs and Analytics.
- A field in a `subtle` panel passes `labelSurface="background"` (see
  FormField).

Recipes by role:

- Tiles are `filled`, `lg` (a folder row `default`), `interactive` only when a
  click navigates (a draft agent is not). The Add tool picker tiles are
  choices: `outline interactive lg` with `asChild` around a `<button>`.
- Chart panels are `subtle lg` with fixed heights passed as layout; a chart
  panel inside a modal is `outline` (the modal is already `bg-card`).
- Form sections (the agent form's Basics, Knowledge and behaviour, Model,
  Advanced, Guardrails) are `subtle lg` with `gap-5`; Basics, Knowledge and
  behaviour and Model are titled by a `SectionHeader`, Advanced and
  Guardrails by a `section-toggle` (see Button). A disclosure panel's body
  under its toggle is one `flex flex-col gap-5` wrapper, its rows carrying
  no `mt-*`, so every section has 20px under its title. The destructive
  danger-zone Card follows them.
- Row boxes inside a form or panel (a guardrail check, the schedule's
  timezone box, the discovered MCP tools) are `padding="sm"`, in the panel
  variant of the surface they sit on (`subtle` in a page panel, `outline` in
  a modal).
- A schedule is `agents/schedules/ScheduleRow`: `subtle`, `padding="none"`,
  with its run log flush under it; a chevron `IconButton ghost-muted
icon-xs` toggles the runs.
- A danger zone (Delete agent, Revoke a device) and a failing stat are
  `tone="destructive"`; the title beside it is `SectionHeader
tone="destructive"`. Muted text fails AA on the red fill, so the tone turns
  every `text-muted-foreground` inside it to `foreground`; don't pass a
  lighter colour back. Icon buttons inside a destructive-tone row are
  `ghost-destructive-on-accent`, whose red tint shows on the fill where
  ghost's grey square would not.
- The shared agent card (its page and a new agent chat) is a thing:
  `filled lg`. Cards never take a shadow.
- The shared agent card's description is `line-clamp-3` with no inner
  scroller (`max-h-* overflow-y-auto`) and no hover hint for the cut text.

Stat tiles are `components/StatCard.tsx`, never a hand-rolled Card: `label`,
`value` (24px bold `tabular-nums`), `sub` (a 12px muted line or link),
`hint` (a native `title` with the help cursor), `variant` (`subtle` on a
page, `outline` inside a modal), `tone="destructive"` for a failing figure,
`valueTone` (`destructive | warning | info | muted`) to colour the figure by
meaning, and `loading` for a figure-sized Skeleton.

Code blocks (a run's output, an error trace, a token or command to copy) are
a `<pre className="font-mono text-xs whitespace-pre-wrap wrap-break-word">`
in a Card picked by the surface underneath: `filled padding="sm"` (a muted
well) on a card or background surface, `subtle padding="sm"` on a muted one
(the tool-approval card, an expanded log row). A copy row is the same Card
with `className="flex-row items-start gap-2"` and the `CopyButton` inside.
Inside an Alert or a trace's tool panel, and in a full-pane viewer, the
`<pre>` takes the recipe with no Card, so boxes don't nest. A scroll cap
goes on an inner `<div className="scrollbar-overlay max-h-* overflow-y-auto">`
around the `<pre>`, inside the Card's padding, never on the Card: on the Card
the scrollbar runs into its rounded corners. Never `break-all` (enforced).
This recipe is for app output. A fenced code block in a markdown answer is
source code: it keeps its lines (`white-space: pre`, indentation intact) and
scrolls sideways inside its own bordered frame (see Chat answer column).

Tile text: the name is `CardTitle` (14px semibold from Card's `text-sm`; pass
`as="h2"` on a page that goes from its title straight to a tile grid, but
never a heading inside a clickable tile, whose children a button flattens), the
description `CardDescription size="xs"` (12px muted, `leading-relaxed`), and
meta lines (a date, a token count, a model id or host) go in `CardFooter` at
regular weight. `font-medium` is for list rows (`ListRow`), not tiles.

### SectionHeader (`ui/section-header.tsx`)

`<SectionHeader as title description actions size tone>`. `size`: `default`
(18px `text-lg font-semibold`, a section title on a page or panel), `sm` (the
eyebrow, `text-muted-foreground text-xs font-semibold uppercase
tracking-wider`, a label set in caps above a group or a table head), `xs`
(14px `text-sm font-semibold`, a sub-heading inside a panel, drawer or modal).
`tone="destructive"` for a danger zone only. `as` is the level in the outline
(`h2` default). The spacing below belongs to the parent's `gap-*`, never an
`mb-*` on the heading. Not for dialog and sheet titles (their own title) or a
page byline (a muted `text-sm` paragraph).

A title with controls beside it (Add, a filter Select, Import spec) passes
them as `actions`, never a hand-rolled `flex justify-between` row around the
header: the row centres the title on the buttons and wraps them under it on
a phone (`flex-wrap items-center gap-x-4 gap-y-2`). Panel and chart titles
are `size="xs"` with `as="h3"`; a title row that also holds a legend or a
"Resets" line keeps its wrapper and swaps only the heading. Disclosure
headers (`Button variant="section-toggle"`) and the Agents breadcrumb are not
SectionHeaders.

### OptionCard (`ui/option-card.tsx`)

The picker tile: a whole-card `<button>` with an icon in a tinted square, a
title and an optional description; `selected` fills the icon square and
outlines the card. Use it wherever the user picks one of several ways to
proceed (agent type, source type). Title-only tiles keep the same layout.
Pass `selected` (true or false) only in a
single-select picker inside a `role="radiogroup"`; the tile is then a radio.
Tiles that advance a step or navigate (Upload's source types, the agent-type
modal) leave it out and stay plain buttons. Only layout classes on it.

### Badge (`ui/badge.tsx`)

`variant`: `default` (brand), `neutral`, `success`, `warning`, `destructive`,
`info`, `outline`. Replaces every hand-rolled
`rounded-full bg-<colour>-100 px-2 py-0.5 text-xs text-<colour>-700 dark:...`
pill, including schedule and run status pills (`agents/schedules/StatusBadge.tsx`
maps schedule and run statuses to Badge variants), trace chips and statuses,
token scope chips, "Disabled" and tool chips. A grey chip is `neutral`, never
a `bg-muted` pill. The admin role is `default` wherever it shows (Teams, Admin
→ Users); every other role is `neutral`. A shared asset's tile (agent,
source, tool, prompt) shows the caller's role with `components/RoleBadge`: a
`neutral` Badge with `Users` first (Editor, Viewer, from `roleOf()`); your own
assets show none. Chips that show code (token scopes) pass `font-mono`, and
stat chips `tabular-nums`, as approved exceptions. HTTP method pills take their variant from
`getMethodBadgeVariant` (`utils/httpMethodColors.ts`): GET `success`, POST
`info`, PUT `warning`, DELETE `destructive`, PATCH `default`, anything else
`neutral`. `MultiSelect` (`ui/multi-select.tsx`) shows its first two picks as
`default` Badges with a remove X, then "+N more", on a `Button
variant="combobox" size="field"` trigger that grows past 38px when the chips
wrap, with SelectTrigger's turning chevron; each row in its list shows a
`Checkbox size="sm"`. Inside a Modal pass `modal`, or its popover can't
scroll and doesn't close on an outside click.

In a picker list, mark the item that is currently chosen with
`CommandItem checked` (a `secondary` brand tint through `data-checked`), not
with `bg-accent`: cmdk's own `data-selected` highlight is `bg-accent` and
follows the pointer and arrow keys, so an accent fill would look like hover.
While a checked item is also highlighted it keeps its tint and text and gains
a 1px inset `primary` ring, so the chosen row never turns plain grey.

A picker's footer (`MultiSelectPopover footer`) links to the page that manages
the list, as a `link inline` Button with a 12px `ArrowRight` (Go to Sources, Go
to Tools). A shortcut action (Upload new, an `outline-primary pill`) sits at the
right end of the same row: `flex flex-wrap items-center justify-between gap-3`,
so on a narrow sheet or in a long locale it wraps under the link rather than
taking a row of its own everywhere (`SourcesPopoverFooter`).

### Input (`ui/input.tsx`)

| Prop      | Values                                                                               |
| --------- | ------------------------------------------------------------------------------------ |
| `size`    | `sm` (h-8), `default` (h-9.5, 38px), `lg` (h-12), `field` (h-9.5, the form-row name) |
| `shape`   | `default`, `pill`                                                                    |
| `variant` | `default`, `bare` (no border, padding, radius, shadow or ring), `filled` (card fill) |

Text alignment classes (`text-right`) and `font-mono` (code fields) are
allowed on Input and Textarea. `<Input label>` is the shorthand for a
one-field `FormField`: the same floating label on the border and the same
`labelSurface` (see FormField). The chat and hero
fields (`rounded-3xl px-5 py-3`) are `size="lg" shape="pill"`. A
default-size pill (38px, the form-row height) pads `px-5` like the large
one, so its text lines up with the Select pills. Compact table
filters (`h-auto px-2 py-1 text-sm`) are `size="sm"`. An inset icon (a
search glass) is `leftIcon`, with or without a `label`; it pads the field
`pl-10`, so never hand-place an icon over an Input. A field inside a host
that already draws the frame (the renaming sidebar row, a search strip in a
bordered panel) is `variant="bare"`; the host shows focus, and any inset
padding goes on the host, not the field. A field on a muted panel (the
ImportSpec Base URL box) is `variant="filled"`, so it keeps the card fill
instead of showing the panel through; never pass `bg-card` for it. A floating
label rests at the field's own text size (16px, 14px from `md`), so a
labelled search and a placeholder-only one read the same, and with a
`leftIcon` it rests where the text starts (40px in).

### SelectTrigger (`ui/select.tsx`)

`size`: `sm` (32px), `default` (36px), `field` (38px, the form-row
height); `variant`: `default`, `ghost`; `shape`: `default`, `pill`. Pills
pad `px-5` at every size but `sm` (`px-3`), so their text starts 21px in
like the Input and Button field pills. A select in a form is
`size="field"`, labelled by `FormField`. SelectTrigger is `w-fit`; pass
`w-full` in a form column. Fields that take typing or sit beside one are 16px
below `md` (iOS zooms on focus under 16px) and 14px from `md`: Input,
Textarea, SelectTrigger `default | field`, Button `combobox` `default | field |
lg` and CommandInput. The `sm` sizes stay 14px. A highlighted list row is
`bg-accent` in Select, Command and DropdownMenu alike.

### Textarea (`ui/textarea.tsx`)

`size`: `sm`, `default`, `lg` (rounded-2xl, for prompt editors); `resize`:
`none`, `vertical` (default), `both`. Same border, ring and invalid styling
as Input. `variant`: `default` (transparent), `filled` (card fill), with
the same rule as Input: a textarea on a muted panel is `variant="filled"`,
never `bg-card`. Two raw `<textarea>` elements stay, because each sits
under an overlay it must line up with: the chat composer and PromptTextArea's
variable highlighter.

### Command (`ui/command.tsx`)

`Command` is the list primitive (cmdk) behind comboboxes, pickers, the
search palette and the source navigator; its `variant` is `default` or
`palette` (the search palette's spacing, see Modal, not Dialog).
`CommandInput`'s `variant` is `default`, the `h-9` row with a bottom border
at the top of a popover or palette list, or `field`, the 38px pill of a
list that sits on the page (a source view's navigator filter, see Page
chrome and Source views); nothing else hand-frames it. `CommandList` caps
itself at `max-h-75` and scrolls; a list that already scrolls inside its
host (a `Modal mobileVariant="sheet"` body) passes `max-h-none` so there is
one scroller. `CommandItem` rows are `cursor-default` like Select and menu
items, highlight `bg-accent` and mark the open item `checked`
(`bg-secondary`); don't add `cursor-pointer`. cmdk highlights the first row
by default, which reads as hover. A list used as navigation, where a current
item exists (the source navigator), starts the highlight on that item, or on
a value that matches no row while nothing is open
(`tree/SourceNavigator`'s `NO_HIGHLIGHT`); a search-then-pick list keeps
cmdk's first-row highlight.

### FormField (`ui/form-field.tsx`)

Every boxed form control is labelled by a floating label:
`<FormField label required hint error disabled labelSurface>` with the field
as its only child. The label sits on the field's border (12px muted), and
`labelSurface` matches the surface behind the field so the notch hides the
line: `card` (the default: forms in cards, modals and `outline` panels),
`background` (fields straight on a page or in a `subtle` panel), `muted`
(fields on a muted panel). Never pass a background class for it. It rests inside an empty, unfocused
`Input` or `Textarea` at the field's own text size (16px, 14px from `md`;
14px on an `sm` Input), where the text starts (40px in beside a `leftIcon`),
and moves up to the 12px border label on focus; on a `SelectTrigger`, combobox,
`MultiSelect`, number field or `Dropzone` it stays on the border. It turns
red (`text-destructive`) with an `error`, and dims while `disabled`. Under
the field come a muted `text-xs` hint and a red `text-xs` error
(`role="alert"`), 6px apart. The required star follows the label
(`aria-hidden`; the field gets `aria-required`, not native `required`). A
placeholder is an example: hidden while the label rests, shown on focus.
Stack floating fields with `gap-5` so each label clears the field above.

`Input`, `Textarea`, `SelectTrigger` (even nested in `Select`), `MultiSelect`,
`Dropzone` and `Checkbox` read their `id`, `aria-invalid`, `aria-describedby`,
`aria-required` and `disabled` from it, so don't set those by hand; an id
the field already has wins. Any other control: pass `id` to FormField and
the same id to the control. One FormField holds one control: a second field
inside it needs its own `id`, or it takes the field's. Popovers reset the
wiring (`FormFieldBoundary`), so a picker's search box is safe.
`className` is layout only. `<Input label>` is the one-field shorthand; never
put it inside a FormField (two labels).

`float={false}` puts the label above instead (14px medium, 6px up), for a
FormField with no single box to sit on: a list of checkboxes, several
controls in a row, a loading or error line in place of the field. Controls
whose label sits beside them (Switch, Checkbox, radio) use `SettingRow` or
an inline `Label`, not FormField. An editing surface that fills its area
(the chat composer, the source edit drawer's field, editing a sent question) and
bare repeated rows in a list have no visible label and must have an
`aria-label`. A row box that is a small form (a workflow condition case or
state assignment) is not a bare row: each of its fields has a floating
label. Never hand-build a label above a field, a
hand-positioned floating label, or a `div.flex-col` + `Label` + `<p>` stack.

A saved secret (an API key, a tool's credential, a custom header value) never
comes back from the API, for any role. Its field is empty and `type="password"`;
in a FormField the saved state is the `hint` ("Saved. Leave empty to keep
it."), because a placeholder is hidden while the label rests. Only a
label-less table cell carries it as the placeholder
(`settings.tools.savedSecretPlaceholder`). Never a `••••` placeholder.

### SettingRow (`ui/setting-row.tsx`)

A setting with a control on the right (a Switch, a short Input) is
`<SettingRow label description htmlFor alignStart stack as after>{control}</SettingRow>`,
grouped in `<SettingRows>`, which splits rows with `divide-border/50` and pads
each 12px (none at the group's ends). The title is a `Label` for the control
(`htmlFor` = the control's id), so every switch has a name and clicking the
title toggles it; `as="h2" | "h3"` keeps a heading tag, and the control then
needs its own `aria-label`. `alignStart` top-aligns the control for wrapping
descriptions. `stack` puts a control too wide for a phone row (a 224px
picker) under the title below `sm` at full width; give the picker
`w-full sm:w-56`. `after` holds a field that belongs to the row, 8px under it
(the agent form's limit Inputs). Settings → General is the page-level example:
`PageToolbar` intro and rule, then `SectionHeader`ed groups of SettingRows in a
`max-w-3xl` column. Inline "switch + label" pairs (a filter
toggle) are not SettingRows.

### Checkbox (`ui/checkbox.tsx`)

`<Checkbox checked onCheckedChange>` (Radix), never `<input type="checkbox">`
(enforced): native boxes take the OS accent and ignore dark mode. `size`: `default`
(16px, option rows), `sm` (14px, table cells). Unchecked it is an
`border-input` box; checked, `primary` with a `primary-foreground` check.
Name it with a `Label htmlFor` or `aria-label`. For an on/off setting with a
description use a Switch in a SettingRow instead.

### Switch, TimePicker and Calendar (`ui/switch.tsx`, `ui/time-picker.tsx`, `ui/calendar.tsx`)

`Switch` (Radix) is an on/off setting, placed inside a `SettingRow` that names
it. A tool's own "In my chats" on/off is the one exception. On a Tools page
tile it is a bare `Switch` at the tile's bottom-right, named only by its
`aria-label` (no visible label); in a connection's drawer, a tool row ends in
a `Label text-muted-foreground text-xs font-normal` + `Switch` pair. Either way
it is the caller's own preference, never a switch that turns the tool off for
everyone. The track is `primary` when on and `bg-input` when off, with a white
thumb in both themes (see Elevation).

`TimePicker` picks a time of day as two `SelectTrigger`s, hours and minutes,
with a `value`/`onChange` pair in 24-hour `"HH:MM"`. `minuteStep` sets the
minute list's step (default 1), `ariaLabel` names the group and each select,
and `showIcon={false}` drops the leading clock. Never a native
`<input type="time">`, which ignores dark mode.

`Calendar` is react-day-picker styled with the theme tokens, its days `ghost`
Buttons; open it in a `Popover` from a field (ScheduleFormModal's date). Its
day button carries the one approved lint exception in the file (see Approved
exceptions).

### Tooltip (`ui/tooltip.tsx`) and IconButton (`ui/icon-button.tsx`)

Every icon-only button is an `IconButton`: `<IconButton label icon hint?
side? variant size />`. `label` is the accessible name and the tooltip text;
`hint` replaces the tooltip text when it says more than the name ("Undo
(Ctrl+Z)"); `icon` is a lucide icon, rendered `aria-hidden`, or pass
`children` for a swapping or custom glyph. It never sets `title`. Tooltip
side: `bottom` for buttons in a header or toolbar at the top of a page, panel
or dialog; `right` on the collapsed sidebar rail, where a top tooltip would
cover the button above; the default `top` everywhere else (under an answer,
in the composer, in rows). Toast close and collapse buttons are plain `Button`s with
an `aria-label` and no tooltip.

Tooltips open after 400ms. One `TooltipProvider` is mounted in `main.tsx`,
so moving along a row of icon buttons opens each at once after the first
(Radix's skip-delay); a `Tooltip` outside it (tests, a portal root) adds its
own provider. For a hint on something that is not an icon button, compose
`Tooltip` + `TooltipTrigger asChild` + `TooltipContent`. `title=` stays only
on truncating text (`span`, `p`, `div`), where it shows the full name.

### ToggleGroup (`ui/toggle-group.tsx`)

The segmented control for picking one value of several (`type="single"`) or
several of several (`type="multiple"`).
Items are pills: the on item is the `outline` look (`bg-background`, border,
`shadow-xs`), the others `ghost-muted`. `size` is `sm` (32px, the default) or
`xs` (28px, inside a muted track: a wrapper `<div className="bg-muted
rounded-full p-1">` around the group, whose own className takes layout only). A single group is a `radiogroup` with one Tab
stop and arrow keys; it sends `""` when the on item is clicked again, so
ignore that in `onValueChange` (`(v) => v && setRange(v)`). Route links in a
row (the Agents filter pills) are not a ToggleGroup: they are `Button asChild
variant={active ? 'outline' : 'ghost-muted'} size="sm" shape="pill"` around
each `Link`, with `aria-current="page"` on the current one.

Filtering a list by kind (a team's shared resources, Share's People) is this
`xs` group in its muted track, each item `{label} {formatCount(n)}`, beside a
`SearchInput size="sm"` (`w-full sm:w-56`); no match is `EmptyState size="xs"
illustration="none"`.

### Separator (`ui/separator.tsx`)

A 1px `bg-border` rule, horizontal or `orientation="vertical"`, decorative
(`role="none"`) unless `decorative={false}`. Pass margins and width only.
Replaces every `<hr>` and every `border-b` or `h-px` div that is only a line.

### Spinner and Skeleton (`ui/spinner.tsx`, `ui/skeleton.tsx`)

`Spinner size="xs | sm | default | lg"` (16, 20, 28, 40px) draws in
`currentColor`, so colour it with a `text-*` token on it or its parent. `xs`
is the icon-sized step: a busy Button, a step's status in a Preview or
research row. Never shrink a larger size with `className="size-*"`, and don't
use lucide `LoaderCircle`/`Loader2` or a hand-drawn SVG as a loader (the
`Loader`, `Loader2` and `LoaderCircle` imports are enforced). `Skeleton` is a pulsing
muted block sized with layout classes; its default radius (`rounded-sm`, 6px)
is the bar radius, so pass none (`rounded-full` for an avatar or switch
stand-in). Bars inside a muted surface (a `Card variant="filled"` tile) take
`surface="muted"` (`bg-muted-foreground/20`), since `bg-muted` would vanish
there. A tile's loading mirror is the same `Card` as the tile (variant,
padding, height) with Skeleton bars laid out like its content; the Card
itself never pulses, only the bars do. A loader inside a panel that is
already on screen (a chart panel whose title shows while its data loads) is
bars only, shaped like the content; the panel is the Card. A loader for an
`Alert` or row box is an `outline sm` Card in a modal with bars inside. Never
put a Skeleton inside an element that pulses itself; the two animations
multiply.

### LoadingState and EmptyState (`ui/loading-state.tsx`, `ui/empty-state.tsx`)

A page, panel or dialog that is still loading shows `LoadingState`, never a
hand-centred `Spinner`. `fill`: `parent` (`h-full`, needs a parent with a
height: the artifact panel, a drawer body), `screen` (`h-dvh`, the app and
admin guards) or `block` (`py-10`, a page section or dialog body with no
height of its own). `label` puts a muted caption under the ring (a long job:
Convert to wiki, Enable GraphRAG); it is also the ring's name. `size` takes
the Spinner sizes (`default` unless set): `sm` inside a picker (the
MultiSelect popover's list), `lg` for a full panel (a remote device's
config). A role guard shows it while it resolves, then redirects
silently: `AdminRoute` at `fill="screen"`, `AgentRouteGuard` at
`fill="parent"` (it renders inside the app shell's scroll column) (see Access and roles). Spinners
inside a control (a busy Button, a picker's `sm` ring) stay `Spinner`.

Nothing to show is `EmptyState`: `size` `default | sm | xs` (128 / 96 / 64px
art, page / panel / popover), `illustration` `no-files | none` (a "no
results" line is `size="xs" illustration="none"`), `title`, `description`
(plain `muted-foreground`), `action`. A page or panel whose fetch failed is
`EmptyState tone="destructive" illustration="none"` with a `Retry` action
(`t('retry')`, an `outline sm pill` Button at every EmptyState size): a red
`CircleAlert`, a red title, `role="alert"`. Never a bare
`text-destructive` paragraph.

### Progress (`ui/progress.tsx`)

`value` 0 to 100, `variant`: `default`, `success`, `warning`,
`destructive`, `info`; `size`: `sm`, `default`, `lg`. Replaces the
width-percent divs in quota, indexing and guardrail views.

### Avatar (`ui/avatar.tsx`)

`size`: `none` (image decides, the default), `xs` (28px), `sm` (32px),
`default` (36px), `lg` (40px): Button's names at Button's heights;
`shape`: `none`, `circle`, `square`; `variant`: `default`, `primary` (brand
initials on `secondary`), `muted` (a grey `bg-muted-foreground/15` box with
`foreground` initials). Initials boxes pass the letters as
children.

### Dropzone (`ui/dropzone.tsx`)

`size`: `default` (tall target, for a step whose whole job is the file: Upload
from device, Import agent, Import API specification), `compact` (one row, a
file field among other fields),
`tile` (a square beside a form's fields, the agent's avatar: 64px and
icon-only on a phone beside the Name field, 88px with a one-word title from
`sm` beside Name and Description; no description). `tileSize="fixed"` keeps
it 64px and icon-only at every width, for a tile in a narrow drawer (the
workflow details sheet), where the breakpoint follows the window rather than
the drawer. `FileUpload size="tile"` fills the tile
with the picked image, or with `currentImage` (the saved one) until then.
Props: `onDrop`, `accept`, `multiple`, `maxFiles`, `maxSize`, `disabled`,
`title`, `description`, `icon`, `error`, `validator` (react-dropzone's
per-file check) and `children`, which replaces the icon, title and
description block. Border and fill follow the drag
state through `data-drag-active` and `data-drag-reject` (the `/5` wash);
it hovers to solid `accent`. Every drop
target renders it, including `components/FileUpload.tsx` (which keeps its
preview and validation logic) and the Import agent / Import API
specification dialogs; don't hand-roll a `border-2 border-dashed` target
around `useDropzone`. Picked files show under it as `ListRows` (name and
size) in an `outline` Card, and rejected files (too large, wrong type) as the
Dropzone's `error`, never dropped silently. The chat composer is the one other
`useDropzone` host: the whole composer is the drop area, with its own
overlay, whose prompt is a Title (see Typography roles).

### Toast (`ui/toast.tsx`)

Feedback on anything the user did outside a modal (uploads, runs,
approvals, team events, a page action's result) is a toast in the
bottom-right stack; a result inside an open modal is an `Alert` there (see
"Where a message lives"), since the toast stack paints under the modal's
overlay. The app has one
`ToastViewport`, mounted in `App.tsx`; it is the live region
(`role="status"`, `aria-live="polite"`) and the fixed stack, so `Toast`
cards carry no role and no toast renders its own rail or positioning. Top
to bottom it holds `TeamNotificationToast`, `ConnectionHealthToast` (a
connection that needs reconnecting, with a Reconnect action),
`ToolApprovalToast`, `UploadToast` and `ActionToast`, and it moves to the
bottom-left while any agent preview drawer is open (workflow or classic). A new toast component returns only its
`Toast` cards and is added to that viewport. A page that reports the result
of an action (the admin Users actions) dispatches
`showActionToast({ variant: 'success' | 'destructive', message })` from
`notifications/actionToastSlice.ts`; `ActionToast` shows it and dismisses
it after 4.5s, and a new result replaces the previous one.

Compose `Toast` > `ToastHeader variant` (`default`, `success`, `warning`,
`destructive`, `info`) with `ToastTitle` and `ToastActions` (collapse and
close as `Button variant="ghost-muted" size="icon-sm"`), then
`ToastContent` (add `scrollable` for long lists) with `ToastItem label meta`
rows (optional `icon` before the label), a `ToastStatus status` circle per
row (`pending`, `success`, `warning`, `destructive`, `info`),
`ToastMessage variant` for an explanation and `ToastFooter` for action
buttons. `ToastTitle` truncates to one line; `wrap` lets a long title (a
localised string, a team name) wrap instead. `ToastMessage size` is `xs`
(default, the note under a row) or `sm` (`text-sm leading-4.5`, the whole
body of a notice). A message that is the only content under the header
gets its top padding on its own, and a message right after a `ToastItem`
shares that row's divider. Toasts own their width, radius and shadow; pass
no width or colour to them.

### A clickable card that holds a link

A card that opens something and also holds a link (a source card under an
answer, with its URL) is a plain `relative` container: a `<button
type="button">` inside it covers the card with `after:absolute after:inset-0`
(the card's radius on `after:`), and the link is a sibling after it with
`relative z-10`, so both are real controls, one tab stop each, and neither
sits inside the other. The container draws the focus ring for the button
(`has-[>button:focus-visible]:ring-3 …ring-ring/50`). Never put a link inside
a `role="button"` or a `<button>`.

### Where a message lives: FormField, Alert or Toast

- A message about one control is `FormField error` (it also turns the
  floating label red).
- A result the user must read before closing the modal (a failed share, a
  failed import, a Test connection result) is an `Alert` in the modal body.
- A fire-and-forget result, or any result on a page rather than in a modal,
  is a toast (`showActionToast`).
- A page or panel that failed to load its own content is
  `EmptyState tone="destructive"` in place of that content, with `Retry`.
- A notice the user must read before acting (an expiring token, a policy that
  forces a setting, models without a price) is an `Alert`; one that is only
  informative and should not be announced passes `role="note"`.
- Status text of a sentence or more is an `Alert` with a lucide icon, never a
  coloured paragraph. A long notice about an old run inside a collapsed panel
  is `Alert role="status"`, not `alert`.
- An action's error on a full-page form (saving an agent) is an `Alert
variant="destructive"` above the form, not text in or beside the button.
- A list of errors the user must read on a canvas or page (the workflow's
  publish validation) is a destructive `Alert` floating at `z-20` on an opaque
  `bg-card rounded-xl shadow-md` wrapper that stays until closed; a toast
  would truncate each error to one line and dismiss itself.
- A switch moves at once and flips back when the server refuses, with a
  destructive toast (an Alert inside a modal). A delete removes its row only
  after the server confirms; a 403 shows `errors.forbidden`.

### Access and roles

Agents, sources, tools and prompts come to the UI with `access` and
`allowed_actions`. Gate every control with `can(item, action)`
(`utils/accessUtils`; `canAgent` in `agents/agentAccess.ts` for agents, which
also refuses Logs, Schedules and Pin on a draft), never on `ownership`,
`team_access` or the user id.

- An action the role doesn't allow is not rendered. A menu builds its
  options from `can()`, and a ⋯ with no options is not drawn; a footer or
  row left empty goes, with its `Separator`. Never a disabled Save or a
  disabled menu item for a role.
- A control stays visible but `disabled` only when it shows state the caller
  should still see (a switch's on/off, a policy's value). Then the reason is
  on screen (an Alert or a FormField `hint`), never a bare grey control. A
  control that can't apply to the caller at all (a tool's "In my chats" when
  the grant doesn't allow it in their chats) is hidden, not disabled.
- A view-only form opens with the same fields and `ViewOnlyNotice`
  (`components/ViewOnlyNotice`: an `Alert role="note"` with `Lock` first and
  `common.viewOnlyNotice`) as its first child. Where only part of an editable
  form is locked (a tool's credentials when the owner turned off "Editors can
  change credentials", or when the tool runs on the owner's connection, whose
  secret only the owner changes), the same notice passes its own `message`. There is no Save; Cancel becomes a lone Close.
  Fields are `disabled` (a group: `<fieldset disabled className="min-w-0">`);
  long text the user reads or copies (a prompt, a chunk) is `readOnly`, so it
  keeps full contrast and scrolls. Titles and menu items swap Edit and
  `Pencil` for View and `Eye`.
- Source views follow the same rule: every write (Add file, Sync, Add chunk,
  Edit, Delete) shows only with `can(source, 'edit')`; reading, copying and
  paging stay.
- A page the role can't open is refused twice: its tabs and section items
  are filtered by the same action (`AgentPageHeader`, `navigation/sections`),
  and its route is wrapped in a guard (`AgentRouteGuard`) that redirects to
  the list as a deep-link fallback, with `LoadingState` while it resolves.

### Alert (`ui/alert.tsx`)

Inline notice inside a form, modal or panel (see above). It is never a
hand-rolled `rounded-lg bg-<role>/10` box.
`variant`: `default`, `neutral` (the same quiet box, by name: a guardrail
"not evaluated" outcome), `success`, `warning`, `info`, `destructive`. 14px
corners (`rounded-xl`), like a popover. Every
coloured variant is the same shape: `border-<role>/50 bg-<role>/10
text-<role>`; `default` sits on `bg-background`. Icon first (a lucide icon,
no classes: the Alert sizes it to 16px and colours it with the text), then
`AlertTitle` and `AlertDescription`. The icon has its own column and sits
centred on the text block, beside a single line, a wrapped paragraph or a
title with its description. Every variant is
`role="alert"` except `success`, which is `role="status"` so a confirmation
is announced politely; pass `role` only to override that. Replaces the hand-rolled
`rounded-lg border bg-amber-50 text-amber-800` boxes.

A failed chat answer is an `Alert variant="destructive"` on the answer's
`mr-5 ml-6` column: `CircleAlert`, the fixed title `conversation.failedTitle`,
and the backend's error (often a raw provider exception) as `font-mono text-xs`
detail in `AlertDescription`. Its action row is Retry (`RotateCcw`) and Copy,
both `ghost-muted icon-sm pill` like every other answer action.

The rows in an answer's step column (Sources, Reasoning, each tool step) are
one recipe: `Button variant="ghost" size="sm"` at `ml-3.5 w-fit`, which puts a
16px muted icon on the `ml-6` text column, then muted 14px text and a chevron.
Sources adds its count and a right chevron, and opens the answer's sources in
the chat's side panel (see Side panels).

### Breadcrumb (`ui/breadcrumb.tsx`)

`BreadcrumbPage`, the current crumb, is always one line and truncates with
an ellipsis. Pages pass only its width (`w-[16ch]`, `max-w-[32ch]`) and a
`title` with the full text; never `truncate` or typography. Give every
current crumb a width cap so a long name cannot push the row past the
screen. It carries the link's focus ring: after a crumb step, PathHeader
moves focus to the new current crumb (`tabIndex={-1}`) so keyboard focus
never drops to the page. A crumb that runs a handler instead of navigating is
`BreadcrumbLink asChild` around a `<button type="button">`; the link carries
the focus ring. Parent crumbs cap at `max-w-[16ch]` with `truncate` on the
button itself (a parent with no handler is a plain truncating `<span>`, never
a disabled button). The current crumb is never a disabled button. The header of
every source view is `components/tree/PathHeader` (see Source views); don't
hand-roll a `/`-separated path.

### ListRow and DescriptionList (`ui/list-row.tsx`, `ui/description-list.tsx`)

An identity row (avatar or icon square, a truncating title, one muted meta
line, a trailing control) is `ListRow` inside `ListRows` (`divide-y
divide-border`, no box of its own; wrap it in `Card padding="none"` or a
bordered list for one). Rows are `px-4 py-3`, the title `text-sm
font-medium`. `interactive` (with `asChild` around a `<Link>` or `<button>`)
hovers to `bg-accent` and draws an inset focus ring. `selected` marks the
row whose detail is open in a drawer beside the list (a team's shared
resources), exactly as a selected TableRow (see Table). An icon square in
`leading` is a plain `bg-muted text-muted-foreground size-8 rounded-md` span.
In a narrow side panel (the graph node panel's relationships) rows are
`size="sm"`: `px-2 py-1.5`, `gap-2.5`, `rounded-md` and top-aligned so a small
leading mark (a `GraphTypeDot` with `mt-1.5`) sits on the title line. They go
in a plain `<ul className="-mx-2">`, not `ListRows` (no divide rules), and
are `interactive asChild` around a `<button>` like the others.

Key/value rows are `DescriptionList` + `DescriptionItem`, never a hand-rolled
`flex` of label and value. `layout="columns"` (default) is an 8rem label
column beside the values (drawers, detail panels); `layout="justified"`
right-aligns the values (a phone card; `columns={2}` for a stats dialog).
`size` `sm | xs`; `mono` on an item for ids and URLs. Values wrap
(`break-words`), they never run past the column.

### Pagination (`ui/pagination.tsx`)

The pager under a table, tile grid or list. It takes `page`, `pageSize` and
`total` and derives the rest: a range summary on the left ("1–12 of 86
sources": pass `rangeLabel` with the list's plural key and `pageRangeParams`,
else the noun-free `pagination.range`), then Previous, five numbered slots
(`pageSlots`: first, last and current page, an ellipsis always hiding two
pages or more: `1 2 3 … 8`, `1 … 4 … 8`, `1 … 6 7 8`) and Next. The current
page is the `outline` button, the others `ghost`. `onPageSizeChange` adds the
"Per page" select (`pageSizeLabel` renames it, e.g. "Rows per page" on a real
table); tile grids keep multiples of 12 (`[12, 24, 48]`, the default) so a
full page fills 1, 2, 3 or 4 columns. The pager is an `@container`: under
36rem of its own width (a phone, a side panel) it shows the short range and
`‹ 2 / 8 ›` instead, without the size select. Render it unconditionally once
the list has loaded; it draws nothing while every item fits on the smallest
page. With a size select it stays while the total exceeds the smallest
option, not the current page size, so picking a bigger size never hides the
way back (page buttons off). Keep a routed list's page in the URL
(`usePageParam`, replaces the history entry) and a chosen size on the device
(`usePageSize`, `DocsGPTPageSize:<list>`); a new search or filter starts on
page 1, and a page the server clamped is followed. Don't hand-roll a
Previous / Next row.

Pick the pattern by the list: a grid or table you browse or search pages;
a newest-first feed (logs, run history, guardrail decisions, a device's
audit, the conversations sidebar) loads older items as it scrolls, never
page numbers (see Feeds below); a usually short
list that is loaded in full (tools, custom models, teams, a team's shared
resources) pages client-side at `SHORT_LIST_PAGE_SIZE` (48, no size select,
`useClientPage`), a safety net that never splits a normal list; a fixed
catalog (connectors) and a table of a few rows (access tokens) have no pager;
a sectioned gallery caps each section at two full rows (`useGridColumns`)
and links "Show all N" beside the title to the section's own page, which
shows everything at 48 per page. Sources opens at 24 per page on desktop and
12 below it.

**Feeds.** `useLoadMore` (items in the component) or `useScrollSentinel`
(items in Redux, where SSE merges new rows) watches a 1px sentinel after the
last item, so loading follows whatever already scrolls and never adds a
scroller: in a Modal, Sheet or SidePanel the body is still the one scroller,
and the sidebar's chats load inside the sidebar column. Only a feed on a page
gets its own cap: an inner `scrollbar-overlay max-h-[45svh] overflow-y-auto`
div inside the frame (the run log's schedule card, the guardrail table's
frame, the audit accordion), never on the Card. Under it, outside the
scroller, `LoadMoreStatus` (`divider` under a flush table) says "Loading
older…", "Nothing older" or offers Retry; it keeps one row's height and so
keeps the scrollbar clear of the rounded corner. A feed shorter than one page
draws no strip. The end is a page shorter than requested, so no count is
needed. A first load shows `LoadingState`, and a failed first load a
destructive state with Retry, never the empty message.

Counts and numbers in the UI format on the app language: `formatCount` (`utils/dateTimeUtils`, `Intl` on `intlLocale()`), never
`toLocaleString()` or a raw `{{count}}`; plural keys get the number as `count`
and the formatted text as `formatted` (`{{formatted}} members`), a key with no
plural passes only `formatted`, and a count is never baked into the key name
(`memberCountOne`). `jp` and `zhTW` aren't language tags i18next knows, so it
plurals them by English rules: every plural key there has an `_one` form too
(the same text as `_other`), or a count of 1 falls back to English. The one exception is a headline
total that can reach tens of thousands (the chunk count in the Chunks byline
and embedded toolbar): it may use `abbreviateCount` (`components/chunkUtils`,
`Intl` compact notation: "12K", "12 тыс.", "1.2万"; grouped digits where the
language has no short form). Counts in tables, pagers and inline text use
`formatCount`. Lists of names join with
`Intl.ListFormat`, never a hard-coded `', '`.

### Page chrome: SectionShell, PageToolbar, SearchInput

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
shape="pill"`), then `children` (notices that belong to the action, such as
a limit warning), then `divider` (a `Separator`). With no `search` the intro
moves into the row's left slot (`max-w-2xl`) beside the action. A page search
is `components/SearchInput`: the 38px pill (`size="sm"` for 32px) with a
search icon and a floating `label` on `labelSurface="background"` (its
default); a placeholder-only search is named by its placeholder. A source
view's navigator filter is a `CommandInput variant="field"` (the same 38px
pill, text 40px in, the ring on the frame), because its rows are
`CommandItem`s (see Source views and Command). `CommandInput`'s `default` variant is the
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
is a drawer (see Modal, not Dialog). Overview groups its fields into three
`subtle lg` panels (Basics, Knowledge and behaviour, Model) with the two-up
field grid, then Advanced, Guardrails and the danger zone. Schedules shows a
`StatCard` row, Recurring / One-time as `ui/tabs variant="underline"`, and
each schedule as a `ScheduleRow` (see Card surfaces).

### App chrome: the phone top bar and New Chat

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
user-supplied name (a chat, agent or source) in a flex row: Button's base is
`shrink-0 whitespace-nowrap`, so `min-w-0` alone does nothing. Pass `min-w-0
shrink` (or `flex-1` when it should fill the row) and put the name in the
`truncate` span; its icons stay `shrink-0`. `w-full` doesn't count: a
`w-full shrink-0` Button takes the whole row and pushes its neighbour out,
under the next control (an `outline` Button's fill is translucent in dark, so
it shows through there and hides in light). `variant="combobox"` already
carries `min-w-0 shrink`, like the fields it sits among.

New Chat is `SquarePen` everywhere: the phone bar, the sidebar's New Chat row
and the collapsed rail. `Plus` means "add an item to this list", not "start
a chat".

### Source views (`components/tree/`, `WikiViewer`, `components/graph/`, `GraphView`)

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
  crumb, truncate at `max-w-[16ch]` with a `title`, and the row stays on one
  line (`flex-nowrap`). A tree embedded in another source view (a graph
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
  Delete and Add chunk show only to a role that may edit (see Access and
  roles).
- **Read in the page, edit in a drawer**: Edit and Add chunk open
  `SourceEditSheet`, a modal `SidePanel size="wide"` (a working surface): title
  and a mono description (path, version, tokens), then any `fields` edited
  with the content (a chunk's Title, a `FormField` + `Input` with
  `labelSurface="background"` and the hint "The name answers cite this
  chunk by."; Add prefills it with the title the file's chunks already use,
  else the file's name), Write · Preview
  (`ui/tabs variant="underline"`; Preview renders the draft with
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
- **Graph**: under the header, `ui/tabs variant="underline"` Graph · Entities
  · Files (Files is the embedded file tree; a source with no folder structure
  shows its embedded chunk list there instead, as the plain view does). A tab's own action goes in the
  header's action row after Test retrieval, only while that tab is open (the
  Files tab's Add file or Sync, portalled through `TreeBrowser`'s
  `actionsTarget`), as on the agent pages; the embedded tree draws no row of
  its own. The Graph tab's toolbar holds the
  entity search (a Popover + Command over the server's `/graph/nodes?q=`),
  the phrase "Show top [50 | 100 | 250] by connections" (muted `text-sm`
  words, the `ToggleGroup xs` alone in its muted track) and the legend, which
  is the type filter (`ToggleGroup type="multiple" xs` in its own muted track,
  a colour dot per item). The surface is one `subtle` Card, `padding="none"`, at `h-[70svh]`;
  the canvas controls (`graph/GraphCanvasControls`) are the workflow
  builder's `CanvasControls` strip without React Flow or Undo / Redo; change
  the two together. Type colours come from `graph/GraphTypeDot`
  (`GraphTypeDot`, `GraphTypeBadge`, `GraphSeriesDot`), never a hand-picked
  hue; the node panel is a docked `SidePanel expandable="graph-node"` inside
  the Card (which is `relative`), open only while a node is selected (see Side
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

### Chat answer column

The answer column never scrolls sideways. Its boxes, from AnswerFlow down to
MarkdownAnswer, are stretched full width (`w-full min-w-0`, or the flex
default), never `items-start` / `self-start` with `max-w-full`: a
shrink-to-fit box sizes to its longest code line, and `max-w-full` caps it at
100% before its margins are added, so it still spills past a phone screen.
Wide markdown blocks scroll inside their own frame, not the page: fenced code
scrolls sideways in its bordered box with the language and copy row fixed
above it, and tables do the same (`overflow-x-auto` on their bordered
wrapper).

### Grids

Three recipes, no component. Tiles (sources, tools, custom models, agents):
`grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4`; tiles
take the column width, never a fixed `w-[300px]`. Team cards stop at three
columns (`lg:grid-cols-3`): their header row holds an initial, the name, a
role badge and a chevron. Stat rows: `grid grid-cols-2 gap-4 md:grid-cols-4`
(five tiles: `md:grid-cols-3 lg:grid-cols-5`; a dialog: `grid-cols-3`). Text
tiles whose body is the content (chunks) follow their container, since the
same list renders beside the source navigator: `grid grid-cols-1 gap-4
sm:grid-cols-[repeat(auto-fit,minmax(min(400px,100%),1fr))]`. A
grid inside a Modal keeps its own column counts, because breakpoints follow
the window, not the dialog.
Skeleton mirrors follow the grid they stand in for.

### Workflow builder (`agents/workflow/`)

The toolbar is `AgentPageHeader` on `bg-background` with a `border-b`. Its
current crumb is the agent's `Avatar` (circle, 20px image, the robot when
there is none), the name (`truncate`, `max-w-[24ch]`) and a muted
`ChevronDown` in a `ghost sm` Button, the phone top bar's title recipe; it
opens the workflow details. The status Badge follows (`success` Published,
`neutral` Draft until the first save), then the tabs. On the right: "Unsaved
changes" as muted `text-sm` meta while there are any, Preview, Save, and the
⋯ (`ActionMenu size="toolbar"`): Edit details first (the same drawer, for
anyone who doesn't try the name), then Access details, Share with team and
Delete once the workflow is saved, each only when the role allows it.

The workflow details are a modal `SidePanel size="default"`
(`components/WorkflowDetailsSheet.tsx`, see Side panels) with the classic
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
  (see Side panels). The header's `leading` is the type's `size-8 rounded-md`
  icon square; the description is the type's name, then the id in `font-mono
text-xs` with a `CopyButton`; `actions` is an `ActionMenu size="toolbar"`
  (Duplicate, Delete node; none on Start). Start and End have no Title field:
  their body is one muted `text-sm` line saying what the node does. Its fields pass
  `labelSurface="background"` and its row boxes (a condition case, a state
  assignment) are `Card variant="subtle" padding="sm"`. The agent node's
  fields are grouped by `SectionHeader size="xs" as="h3"` (Model, Prompt,
  Knowledge, Output) with an Advanced settings `link sm` disclosure that
  opens on its own when one of its settings is set. The column is narrow, so
  every field stacks at full width (`flex flex-col gap-5`), Agent type and
  Model included; no two-up grids. A row box's title is `SectionHeader
size="xs" as="h4"`. In an If / Else case's Simple mode, the operator Select
  and Value each carry a floating label (Operator, Value).

### Accordion (`ui/accordion.tsx`)

`AccordionTrigger` carries its own inset and type (`px-4 py-3 text-sm
font-medium`) and an inset focus ring, since `AccordionItem` clips anything
outside it. Pages pass nothing to the trigger; put the frame (a bordered,
rounded box) on a wrapper around `Accordion`.

### Modal, not Dialog

`ui/dialog.tsx` is the Radix primitive and is private to `ui/`; ESLint
rejects imports of it elsewhere. App code uses `Modal` (sizes `sm` to
`full`, `mobileVariant="sheet"`) or `CommandDialog`.

The width comes from `size` only: `sm` 384, `md` 512 (the default), `lg` 672
(a form or a one-column list: Move to folder), `xl` 896 (a grid of
tiles or a wide editor: Add tool, Test retrieval, the prompt editor), `full`.
Never add a width or height class. The dialog caps itself at `85dvh` and
its body is the one scroller, so the header and footer stay put; don't cap
the body with `contentClassName`. `contentClassName="overflow-visible"`
(`cn` drops the body's `overflow-y-auto` for it) is only for a body whose popover must escape it (the
prompt editor, Share conversation, Move to folder). `className` is placement
only.

A modal's body is `flex flex-col gap-5` when it stacks floating fields,
with `gap-6` between labelled groups (a `SectionHeader size="xs"` and its
fields); FormField supplies the 6px to its hint. The body carries no padding:
Modal's scroll area already insets it (`px-1 pt-3 pb-0.5`) so focus rings
aren't clipped. Never `space-y-*` on a body.

A modal's heading is its `title` (20px, `text-xl leading-tight
font-semibold`) and `description` (muted `text-sm`, 8px under the title).
Don't pass `hideTitle` to draw your own `<h2>`; `hideTitle` is only for
dialogs whose top line is not a title (Upload's step headings,
ScheduleFormModal's editable name, the search palette). A step heading
under a Back button uses the title's classes (`text-xl leading-tight
font-semibold`), not a larger size.

A list in a modal that can grow long (Share's People) shows the first three
once it passes five, a `link inline` "Show all N" (12px `ArrowRight`) in its
SectionHeader's `actions` and a muted `text-xs` "and N more" line, counts
through `formatCount`. The full list is a second step: a `ghost sm` Back with
`ArrowLeft`, the title-class heading, then the search and kind filter (see
ToggleGroup), with `hideTitle` on that step only.

Buttons go in `footer`, never in `children`. The footer stacks full width on
phones (primary on top) and sits in a right-aligned row from `sm` up. The
standard pair is `footer={<ModalActions cancelLabel onCancel submitLabel
onSubmit pending disabled destructive />}`: a ghost Cancel and a primary
(or `destructive`) submit, both `size="lg" shape="pill"`; `pending` shows
the submit's `loading` spinner. A left-hand extra (Test connection) is
`footerStart`, and `submitProps` / `cancelProps` carry `type="submit"`,
`form` or a test id. A lone button is a `size="lg" shape="pill"` Button.

A search palette is `CommandDialog` on desktop. Pass cmdk options to its
inner `Command` through `commandProps` (`shouldFilter={false}` when results
come from a server search, a controlled `value`). On phones the same palette
goes in `Modal mobileVariant="sheet"` as `<Command variant="palette">`, which
gives it the dialog's 48px input row and row spacing, so both widths look
the same (`modals/SearchConversationsModal.tsx`). `CommandDialog` sits on
`DialogContent`, which has Modal's surface (`bg-card rounded-2xl
shadow-modal`, no border, `p-8`, a 20px title, a `gap-3` footer, a left-aligned
header, and the `flex-col max-h-[85dvh]` column whose body the caller makes the
scroller) and the same blurred overlay. Modal, DialogContent, every Sheet and
the phone sidebar's backdrop (`Navigation.tsx`, at `z-20` so an open sidebar
dims the top bar, with SheetOverlay's `animate-in fade-in-0`) share one scrim,
`overlayScrim` in `lib/utils.ts` (`bg-black/25 backdrop-blur-xs
dark:bg-black/50`).

#### Side panels

Every right-side panel is `ui/side-panel`: a `SidePanel` holding one
`PanelHeader`, one `PanelBody` and an optional `PanelFooter`. Pick the
variant with one question: do you need to keep working with what's behind
it?

- **`variant="modal"`** (no): a form, one record, editing or a preview (a
  connection, a team resource, a schedule run, a trace, the workflow details,
  the source edit drawer, an agent preview). A right `Sheet` over the blurred
  `overlayScrim`, the full viewport high, focus kept inside.
- **`variant="docked"`** (yes): what you read or tweak beside a live page
  (the chat's artifact or an answer's sources, a workflow node's settings, a
  graph entity). An `<aside>` in the page: no scrim, `border-l` on
  `bg-background`, the full height of its host. It slides in like the modal
  one and closes at once (an exit slide snaps back for a frame before it
  unmounts). The host is a `relative flex overflow-hidden` row with the page
  as a `min-w-0 flex-1` sibling. While open it covers the app's floating Share
  and account menu in the top-right corner (`ActionButtons`, `z-10` under the
  panel's `z-20`); they come back when it closes. One docked slot per page:
  opening another thing replaces what is there, never stacks.
  The chat's slot (`conversation/chatCompanion`) holds an artifact or an
  answer's sources; where there is no slot (a shared chat, an agent preview)
  the sources open modal.

Two widths, by `size`, never a `w-*` or `max-w-*` class (enforced):
`default` 480px for every panel, and `wide` (600 / 700 / 800px) only for a
working surface: a trace, an agent preview, the source editor. A docked
panel can be
`expandable="<surface>"`: Expand in its header steps compact (its `size`),
half of the host (never narrower than compact) and full (covering the host,
the page keeping its scroll underneath), then back, and the last width is
remembered per surface (the artifact, a workflow node, a graph entity). A
modal panel never expands. Below `lg` both variants are the same full-width
right sheet; a docked panel's sheet opens on the panel, without a ring on
its first control.

The panel is itself a place: it paints no card of its own, panels in it are
`subtle` and tiles `filled` (see Card surfaces). The anatomy never changes:

- **`PanelHeader`**: fixed at `px-6 pt-6 pb-4`, then a `Separator`. The
  title is the 20px Title role and wraps (`wrap-break-word`), it doesn't
  truncate; `description` is one muted line (a span inside carries its own
  typography: `font-mono text-xs` for a path). `leading` takes a node tile or
  a connector icon; `actions` (a badge, a ⋯ menu), Expand and the X share the
  title row, so nothing is placed absolutely and no `pr-12` is needed.
  `onBack` adds a Back arrow for a second level inside the panel (a graph
  entity's chunk); `children` sit under the title row, still fixed (a team
  resource's Open and Manage sharing).
- **`PanelBody`**: the one scroller (`scrollbar-overlay`), its sections
  `gap-6` apart at `px-6 py-6`; `scroll={false}` when the content owns its
  scroller (an artifact's iframe or code view).
- **`PanelFooter`**: a `Separator`, then the actions at the right, `gap-3
px-6 py-4` (Cancel `ghost lg pill`, Save `default lg pill`).

The row whose panel is open is `selected` (ListRow or TableRow). An agent is
previewed in one shared panel, `agents/components/AgentPreviewSheet`, for
workflow and classic agents alike: `size="wide"`, the agent's name as the
one-line description, an `info` Running badge in `actions` while it answers,
then the preview, which owns its scroller. The workflow preview's Execution
details and Artifacts rows are the answer's step-row recipe (see Alert), each
step a `subtle sm` panel with its output in a `filled sm` well. Never
hand-build a right panel (an `<aside border-l>` column or a `SheetContent
side="right"`); compose SidePanel.

Every phone bottom sheet has one shape: `bg-card`, 18px top corners (`rounded-t-2xl`), no top
border, `shadow-lg` (both `SheetContent side="bottom"` and Modal's phone
sheet), `max-h-sheet` (the visible viewport less the top safe-area inset and a
3rem strip, so the scrim above it can always be tapped to close), and bottom
padding that clears the iPhone home indicator. Never cap a sheet with `vh` (see
Viewport heights): a `90vh` sheet slides under Safari's URL bar and covers its
scrim. `SheetContent side="bottom"` gives the
shape with `pb-safe-0` (the bare inset); pass `handle` for the grab bar, which
also hides the X (the overlay dismisses it; the handle is only a cue and doesn't
drag; pass `showCloseButton` to keep an X).
`Modal mobileVariant="sheet"` shares the shape and the `SheetHandle` (and,
like a handled sheet, has no X), with `pb-safe` (the inset, at least 1rem)
under its footer. `pb-safe`, `pb-safe-0`
and `max-h-sheet` are the `index.css` utilities for the safe-area insets; never
spell `env()` in a class.

Closing a bottom sheet resets iOS Safari's bottom bar. Safari 26 takes the bar's
colour from a fixed element that appears on the bottom edge, so an open sheet
turns it `bg-card`, and it never changes back when the sheet goes away or the
page changes colour. `SheetContent side="bottom"` and `Modal`'s phone sheet
mount `BottomTintReset` (`ui/bar-tint-reset.ts`), which shows a 6px
`bg-background` strip on the edge for one painted frame after the sheet
unmounts, and Safari samples the page colour again. `useDarkTheme` calls
`resetBottomTint()` and `resetTopTint()` (a 16px strip on the top edge) when the
theme changes. Anything else fixed to the bottom edge that can go away (a
drawer, a bottom banner) calls `resetBottomTint()` when it is removed. The sizes
and the one-frame life were measured on an iPhone (6px at the bottom, 16px at
the top), and a strip behind the content, transparent or at `opacity-0` isn't
sampled, so don't shrink or hide the strip.

Content read alongside the chat (notes, todos, files, `components/ArtifactPanel`)
and an answer's full source list (`conversation/SourcesPanel`) share the chat's
docked side panel (see Side panels). Don't add another pattern.

### ActionMenu (`ui/dropdown-menu.tsx`)

The three-dots menu on a card, tile or row. Pass `options: MenuOption[]`
(`label`, `onClick`, optional lucide `icon`, `variant: 'destructive'`,
`disabled`) and a `triggerLabel`. It renders a `ghost-on-accent` `icon-xs`
trigger with `EllipsisVertical`, and stops clicks and keys on the trigger and
the menu from reaching the host, so it can sit inside a clickable card.
In a page header or toolbar on a plain surface (the agent Overview's title
row, through `SectionShell titleAction`; the workflow builder's toolbar), pass
`size="toolbar"`: the trigger is a 36px `ghost-muted` icon button like the
others there, hovering to `accent`, with its tooltip below. The default
`row` trigger's darker hover is only for hosts that turn `accent` themselves.
`align` (default `end`) places the menu, `disabled` greys the trigger, and
`triggerTestId` puts a `data-testid` on it. `className` takes layout only (position, margin) and lands on the trigger;
the menu is at least 144px wide and grows with its labels. `open`/`onOpenChange` make it controlled. Don't hand-build
this menu from `DropdownMenu`, and don't declare a local option type.

### Table, Label, dialog text

Every table is `ui/table`, markdown tables included (`markdownTables` renders
its parts); never a raw `<table>` (enforced) or a table utility class. The header row is dense by
default (`px-2 py-1 lg:px-3 text-sm font-normal text-foreground`, 28px, on
`TableHead`'s sticky `bg-muted` strip). A `TableRow` hovers (`bg-accent`,
pointer) only when it has an `onClick`; a read-only row does not. `selected`
marks the row whose detail is open beside the table (the graph's Entities):
`bg-secondary`, the brand tint of an open navigator item, kept on hover, with
`aria-current`. Use
A number column (sizes, tokens, counts) is `align="right"` with
`tabular-nums` on its cells, header included in the alignment, whatever the
column order (the file table, the graph's Entities). Use
`TableContainer` for the bordered, scrolling frame; a table that already sits
in a frame renders `Table` alone. `Table` keeps a 600px minimum so wide
tables scroll sideways; a narrow one inside a panel passes
`minWidth="min-w-0"`. A fixed icon column is `width="40px" align="center"`.
`TableCell` and `TableHeader` accept typography and alignment classes and
`text-muted-foreground`. `Label`, `DialogTitle`, `DialogDescription`,
`SheetTitle` and `SheetDescription` accept typography plus
`text-foreground` and `text-muted-foreground`. `DialogContent`,
`PopoverContent`, `SheetContent`, `SheetHeader`, `SheetFooter`,
`DropdownMenuContent`, `DropdownMenuSubContent`, `SelectContent`,
`TooltipContent` and `Modal` accept `p-0` for edge-to-edge content; Modal
merges it after its own `p-8`, so no `!` is needed. A modal that needs a
full-bleed band under its title keeps the padding and bleeds the band out
with negative margin (Move to folder's breadcrumb band). Everything else on these components is layout only.
`MessageScrollerViewport` and `MessageScrollerContent` accept layout and
spacing: the primitive measures Content's padding-block for its scroll and
spacer math, and the Viewport's top gap must scroll with the messages, so
padding there cannot move to a margin or a wrapper.

## Spacing, type and radii

Use the Tailwind scale. Tailwind v4 accepts fractional steps, so
`h-10.5` is 42px and `ring-3` is a 3px ring; neither needs brackets. Layout
values (`h-[calc(100dvh-64px)]`, `max-w-[520px]`) and motion values
(`transition-[color,box-shadow]`, custom easings) are allowed. Font sizes,
padding, colours and radii in brackets are not; pick the nearest scale step
or add a token.

### Viewport heights

Never size anything with `vh` or the `h-screen` family (`h-`, `min-h-`,
`max-h-screen`, which are `100vh`). On iOS Safari `vh` is the viewport with the
toolbars hidden, so while the URL bar and tab bar show, a `vh` height is about
140px taller than the screen: a centred message sits low, a panel or dropdown
runs under the tab bar, and the app shell can be dragged and bounce. ESLint
(`no-restricted-syntax`) rejects both. Pick by what the height does:

- **`dvh`** (the visible viewport, follows the toolbars): the app shell
  and the `screen` `LoadingState` (`h-dvh`), full-screen states (`min-h-dvh`:
  404, MobileBlocker), and caps on things that pop up over the page (a search
  dropdown's `max-h-[calc(100dvh-200px)]`, `Modal`'s `85dvh`).
- **`svh`** (the smallest viewport, steady): a fixed-size panel inside a page
  that scrolls (the Logs panel's `h-[55svh]`, a list's `max-h-[45svh]`, the
  graph surface's `h-[70svh]`, the source edit drawer's `min-h`), so it doesn't resize while Safari's bars slide in
  and out.
- **`max-h-sheet`**: every bottom sheet (see Modal, not Dialog).
- A row or control has a fixed height (`h-12`), never a share of the viewport.

`w-screen` is `vw`, which the toolbars don't change, so it stays allowed.

### Typography roles

- **Page title**: `SectionPageHeader` (24px bold; the phone section index,
  `SectionIndexPage`, draws the same `h1`); the only other text at that size
  is a stat figure (`StatCard`).
- **Title** of a dialog, sheet, drawer header or detail page: `text-xl
leading-tight font-semibold`. `DialogTitle` and `SheetTitle` default to it;
  `font-bold` is never a title weight. A picker popover's header is a
  sub-heading, not a title. The composer's drag-and-drop prompt is a Title
  in `foreground`. Every side panel's title, the artifact's included, is this
  role (`PanelHeader`), and wraps.
- **Section title**: `SectionHeader` (18px). **Sub-heading** inside a panel,
  drawer or modal: `SectionHeader size="xs"` (14px semibold). **Eyebrow**
  (anything set in caps): `SectionHeader size="sm"`; never `uppercase` on a
  value (a variable name, a mode, an agent type).
- **Tile text**: `CardTitle` + `CardDescription size="xs"` (see Card).
- **Hint** under a control: FormField's `hint` (12px muted, 6px under the
  field); a control with no FormField writes the same line as
  `text-muted-foreground mt-1.5 text-xs`. Hints are muted, never a status
  colour; a warning that needs attention is an `Alert`. **Description** under
  a heading: `text-sm text-muted-foreground`.
- **Markdown**: every renderer spreads `markdownHeadings` from
  `lib/markdown.tsx` (h1 20px, h2 18px, h3 16px, semibold, `mt-4|3 mb-2`);
  don't declare a local heading map. Tables are `markdownTables` from the same
  file: the `ui/table` parts in a `TableContainer` (the frame scrolls
  sideways, `minWidth="min-w-0"` so a narrow table shrinks), so a table in a
  chat answer, a wiki page, a chunk, a note or a preview looks like every
  other table. Every markdown renderer spreads it.
- **Mono**: ids, keys and code snippets are `font-mono text-xs`; code fields
  (textareas) follow the field size; code blocks follow the Card recipe
  (see Card). A preview of text a person or a model wrote (a trace's query
  or output) stays proportional at the same size; only what the app
  serialised (arguments, results, attributes) is mono. Every stat figure is
  `tabular-nums`.
- **Wrapping**: prose that can run long (a name, a description) wraps with
  `wrap-break-word` in a column that can shrink (`min-w-0` in a flex row).
  A single long token (a URL, a key, an id, an email, a filename, a command)
  is `wrap-anywhere`, which also lets a table cell or flex item shrink below
  the token instead of widening the table. Both break at spaces first and
  split a token only when it would overflow. Never `break-all`: it splits
  ordinary words mid-word ("notif / ications"); the lint rejects it.

### Rhythm

32px between the page title and the content (`SectionShell`); 24px (`gap-6`)
between sections inside a panel or drawer; 20px (`gap-5`) between floating
fields; 8px (`gap-2`) in a button row, 12px (`gap-3`) in a modal footer. A
two-up field grid is `grid grid-cols-1 gap-x-4 gap-y-5 sm:grid-cols-2`. Stack
with `flex flex-col gap-*`, not `space-y-*` (a child's own margin adds to a
gap, so drop it).

### Radius by role

`rounded-xs` 2px, `rounded-sm` 6px, `rounded-md` 8px, `rounded-lg` 10px,
`rounded-xl` 14px, `rounded-2xl` 18px, `rounded-3xl` 22px, `rounded-4xl`
26px (from `--radius`); bare `rounded` is a fixed 4px, so don't use it
(enforced). `3xl` is the chat's own shapes (the composer, the question
bubble) and `4xl` the answer's source cards and the landing page's model
picker; app chrome stops at `2xl`. Skeleton bars: the default. Tinted icon squares:
`rounded-md` at `size-7|8`, `rounded-xl` at `size-12|14`, `rounded-2xl` at
`size-20`. `rounded-full` only for pills (`shape="pill"` controls and
fields), avatars, status dots, the workflow palette pills (not their icon
squares) and the canvas nodes' icon circles.

## Motion

Transition only the property that changes: `transition-colors` by default,
`transition-transform duration-200` for chevrons,
`transition-[grid-template-rows,opacity] duration-300 ease-out` for
collapsibles, `duration-300 ease-in-out` on the named property for the shell
(sidebar, main column, top buttons); a shadow or ring change is
`transition-shadow`, several at once a bare `transition`. No `transition-all`
(the floating labels in `form-field.tsx` and `input.tsx`, which move and
resize, are the exception) and no `hover:scale-*`, both enforced: hover is a
fill, border or text-colour change.

New entrances are `animate-in fade-in duration-200 motion-reduce:animate-none`
(`SectionRail`). Two chat timings are decided exceptions: the disclosure fade
`animate-in fade-in duration-160 ease-out` and the answer bubble `animate-in
fade-in slide-in-from-bottom-1.5 duration-260 ease-out`, both with
`motion-reduce:animate-none`. `ui/` overlays keep their own enter and exit.

## Breakpoints

Phone / desktop is `lg` (1024px) in classes and `isDesktop` in JS
(`useMediaQuery`); `sm` and `md` only reflow content. Wide two-column layouts
that need more room (Analytics' chart rows) go two-up at `xl`. No custom
breakpoints (`min-[…]`, `max-[…]`, `[@media(…)]`; enforced). The workflow builder needs `lg`; below it `MobileBlocker`
shows.

## Focus, elevation and stacking

- **Focus ring**: `focus-visible:ring-3 focus-visible:ring-ring/50` plus
  `focus-visible:border-ring` on fields. Never `focus:` (mouse users see it)
  and never `ring-2` or `ring-[3px]` (a `focus:` or `focus-within:` ring
  with `ring-2` is enforced); the `ui/` components already carry it,
  so plain elements should become components rather than copy the classes.
  Inside `ui/`, spell it with the `focusRing` constant from `lib/utils.ts`
  (with `invalidState` and `fieldFrame` for fields) rather than retyping it.
- **Focus return**: Modal, Sheet and DialogContent give focus back on close
  only to the element that had it when they opened (`ui/use-focus-return.ts`).
  A tap on iOS, and a click in Safari, doesn't focus the trigger, so Radix's
  default `trigger.focus()` lit it with a ring nobody asked for; after a
  keyboard open the trigger did have focus and still gets it back. Don't pass
  `onCloseAutoFocus` from app code to remember focus yourself (ESLint rejects
  it); the primitive already does. `onOpenAutoFocus` with `preventDefault()`
  is still how a phone picker keeps the keyboard down (`MultiSelectPopover`),
  and how a docked side panel's phone sheet opens without a focus ring on its
  first control (`SidePanel` does it).
  A dialog panel is a `tabIndex=-1` focus target that Radix can focus, so it
  carries `outline-none`: Safari draws its own blue `outline: auto` there and
  ignores our `outline-color`. Any new focusable container needs the same.
- **Close buttons**: every Modal, bottom Sheet and DialogContent uses its
  built-in close (a phone sheet with a handle has none), a `ghost-muted`
  `size="icon-sm"` Button (32px, accent square on hover) at `top-2 right-2`;
  a side panel's is the same Button in `PanelHeader`'s title row. Never
  hand-place another X.
- **Disabled**: buttons (Button, Accordion, Tabs) use
  `disabled:pointer-events-none disabled:opacity-50`, so the pointer passes
  through. Fields (Input, SelectTrigger, Switch, Textarea, CommandInput,
  Label) use `disabled:cursor-not-allowed disabled:opacity-50` and never
  `pointer-events-none`, which would hide the cursor.
- **Elevation**: cards have no shadow; fields and outline buttons
  `shadow-xs`; popovers, menus and select lists `shadow-md`; sheets
  `shadow-lg`; modals (Modal and DialogContent) `shadow-modal`; toasts
  `shadow-toast`. The one exception in `ui/` is the Switch thumb, `bg-white
shadow-lg` in both themes: the knob is white on any track, and a white knob
  on a white card needs the lift to read as raised. The off track is
  `bg-input`. Accordions are
  panels and have none. Outside `ui/` the only shadows are: the workflow
  canvas nodes (`shadow-md`, `hover:shadow-lg`: a node lifts off the canvas
  while you drag it); the workflow builder's publish-error panel, which
  floats over the canvas at popover elevation (`shadow-md`, `z-20`); the sliding panel in `navigation/SidebarLevel.tsx`,
  which casts a horizontal shadow while it slides; and the Hero model
  picker's menu (both Approved exceptions). Don't add new ones: a floating panel is a `Popover`,
  `DropdownMenu` or `Modal`, which carry their own shadow and stacking; never
  an `absolute` div with a shadow and a hand-picked `z-*`.
- **Stacking**: `z-10` sticky headers and table heads inside a page;
  `z-20` in-page floating chrome (banners, scroll-to-bottom, drag
  handles); `z-50` overlays, modals, sheets, toasts and the one-frame
  bar-tint strips; `z-200` every portalled floating list (popover, menu,
  select, tooltip), so it opens above a Modal without an override. Do not
  invent values in between: a `z-*` outside 0, 10, 20, 50, 200 and `auto` is
  rejected (enforced). The app
  shell uses the low layers too: the phone top bar is `z-10`, and the
  sidebar and its phone backdrop are `z-20`, so an open sidebar dims the bar.

## Inline styles

Allowed without comment in `src/components/MermaidRenderer.tsx` and
`src/agents/workflow/nodes/**` (third-party renderers and canvas
positions). Elsewhere, prefer a CSS custom property
(`style={{ '--progress': pct }}` with `w-(--progress)`), and when a value
truly is computed at runtime, keep the inline style and add
`// eslint-disable-next-line shadcn/no-inline-styles -- <reason>`.

## Approved exceptions

Places where a rule is knowingly disabled. Each one carries the same reason
as a comment at the call site; add a row here when you add a disable so the
list stays reviewable.

| Where                                                             | Rule                            | Why                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| ----------------------------------------------------------------- | ------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `components/Notification.tsx`                                     | `shadcn/no-restyle`             | The promo banner's close X (`ghost icon-xs`) sits on the purple gradient. Any fill would be a grey square on it, so hover dims the icon instead (`hover:bg-transparent hover:opacity-70`, plus `dark:hover:bg-transparent` to beat ghost's dark hover), and `text-primary-foreground` keeps it white, because the button inherits the page colour. One user, so it isn't a variant.                                                                                                             |
| `components/ui/calendar.tsx`                                      | `shadcn/require-static-classes` | The day button merges `defaultClassNames.day`, which react-day-picker returns from `getDefaultClassNames()` at runtime; no static form exists.                                                                                                                                                                                                                                                                                                                                                  |
| `navigation/SidebarLevel.tsx`                                     | `shadcn/no-arbitrary-values`    | The incoming sidebar panel casts a strong shadow off its left edge while it slides (`shadow-[-12px_0_24px_-6px_rgba(0,0,0,0.45)]`); no scale shadow is horizontal, and the container clips it once the panel comes to rest.                                                                                                                                                                                                                                                                     |
| `components/MessageInput.tsx`                                     | `shadcn/no-restyle`             | The empty composer's send button is a grey circle (`bg-muted`, `dark:bg-accent`), not a faded brand one; no variant is neutral while disabled, and `secondary` is the brand-tinted pressed state.                                                                                                                                                                                                                                                                                               |
| `Hero.tsx`                                                        | `shadcn/no-restyle`             | The landing page's model picker keeps its hero look: a borderless muted pill at 16px (`rounded-4xl px-6 py-4 text-base`) whose menu hangs from it as one shape. Three disables: `SelectTrigger`, `SelectContent`, `SelectItem`.                                                                                                                                                                                                                                                                 |
| `agents/AgentsList.tsx`                                           | `shadcn/no-restyle`             | Inside a folder, the breadcrumb trail replaces the section `<h2>`, so its `BreadcrumbList` keeps heading typography (`text-foreground text-lg font-semibold gap-2`). It's the only breadcrumb that does.                                                                                                                                                                                                                                                                                        |
| `conversation/MarkdownAnswer.tsx`, `components/ArtifactPanel.tsx` | `shadcn/no-inline-styles`       | SyntaxHighlighter's `style` prop is its Prism theme object (`oneLight` / `vscDarkPlus`), picked by theme at runtime. It is not CSS, so no class or custom property can replace it. One disable per file.                                                                                                                                                                                                                                                                                        |
| `agents/workflow/WorkflowPreview.tsx`                             | `shadcn/no-restyle`             | The Preview minimap's node rows are status tiles: the fill, border and ring follow the step (success, primary running + pulse, destructive, muted pending; a ring on the active row) and stay pinned on hover, pending and running rows stay unfaded while disabled, and clickable rows dim to 80% on hover. No Button variant is status-tinted. The rule reports each string inside `cn(...)`, so it's a `/* eslint-disable */` … `/* eslint-enable */` pair around the `className` attribute. |
| `agents/schedules/ScheduleFormModal.tsx`                          | `shadcn/no-restyle`             | The schedule's name is the dialog's editable title: a `bare` Input with title type (`text-xl font-semibold`), so the dialog passes `hideTitle`. One disable.                                                                                                                                                                                                                                                                                                                                    |
| `components/MermaidRenderer.tsx`                                  | `shadcn/no-restyle`             | The zoom − / + buttons sit on the diagram's `bg-black/70` overlay, where ghost's accent hover paints a light square with dark text; they hover to `white/20` with white text instead, in both themes. Two disables.                                                                                                                                                                                                                                                                             |
| `Hero.tsx`                                                        | `shadcn/no-restyle`             | The landing page's demo cards are `Button outline lg pill`, but each is a two-line pill (a title over a clamped 12px query), so it undoes lg's height, the base's one-row layout, weight and nowrap: `h-auto w-full flex-col items-start gap-0 py-3.5 text-left text-xs font-normal whitespace-normal`. One disable.                                                                                                                                                                            |
| `Navigation.tsx`, `conversation/ConversationTile.tsx`             | `shadcn/no-restyle`             | A sidebar row whose link has sibling buttons (an agent's pin, a conversation's menu and rename Save / Cancel) keeps its fill while the pointer is on a sibling or the menu is open (`group-hover:bg-sidebar-accent`, `bg-sidebar-accent`), and `pr-10` keeps the label clear of the buttons. ConversationTile's `cn(...)` needs a `/* eslint-disable */` … `/* eslint-enable */` pair.                                                                                                          |
| `admin/Usage.tsx`                                                 | `shadcn/no-restyle`             | The Top users id is a `link inline` Button inside a mono table cell; it keeps the cell's type and wraps (`font-mono text-xs font-normal whitespace-normal text-left`). One disable.                                                                                                                                                                                                                                                                                                             |
| `agents/workflow/panels/ConditionPanel.tsx`                       | `shadcn/no-restyle`             | The "Learn more" link in the Condition node's Advanced-mode 12px hint keeps the sentence's size and weight (`text-xs font-normal` on `link inline`). One disable; the Set state node's link sits in its `text-sm` intro and needs none.                                                                                                                                                                                                                                                         |
| `components/MessageInput.tsx`                                     | `shadcn/no-restyle`             | The queued-send Cancel is a `link inline` inside the composer's 12px status line, so it takes the line's size (`text-xs`). One disable, beside the send button's.                                                                                                                                                                                                                                                                                                                               |
| `settings/PersonalAccessTokens.tsx`                               | `shadcn/no-restyle`             | Token scope chips are identifiers, so the `neutral` Badge is set in mono (`font-mono`). One disable.                                                                                                                                                                                                                                                                                                                                                                                            |
| `agents/workflow/WorkflowPreview.tsx`                             | `shadcn/no-restyle`             | A step's state changes (keys and values the app serialised) are `neutral` Badges set in mono (`font-mono`), like token scopes. One disable.                                                                                                                                                                                                                                                                                                                                                     |
| `settings/traces/TraceChips.tsx`                                  | `shadcn/no-restyle`             | Trace stat chips (durations, counts) use tabular figures so they don't jitter between rows (`tabular-nums` on Badge). One disable.                                                                                                                                                                                                                                                                                                                                                              |
| `connectors/ConnectorSetupNotice.tsx`                             | `shadcn/no-restyle`             | The setup-guide link inside the needs-setup warning Alert keeps the Alert's status colour (`text-current` on `link inline`). One disable.                                                                                                                                                                                                                                                                                                                                                       |
| `modals/MCPServerModal.tsx`                                       | `shadcn/no-restyle`             | The authorization link inside the test-result Alert keeps the Alert's status colour (`text-current` on `link inline`). One disable.                                                                                                                                                                                                                                                                                                                                                             |
| `components/MermaidRenderer.tsx`                                  | `shadcn/no-restyle`             | The zoom readout between − and + is a `link inline` Button on the `bg-black/70` overlay; it keeps the overlay's white 12px regular text (`text-xs font-normal text-current`). One disable, beside the two zoom-button ones above.                                                                                                                                                                                                                                                               |
| `conversation/SharedConversation.tsx`                             | `shadcn/no-restyle`             | The "DocsGPT" link sits in the `/share/:id` page's regular-weight byline (`font-normal`). One disable.                                                                                                                                                                                                                                                                                                                                                                                          |
| `conversation/ConversationBubble.tsx`                             | `shadcn/no-restyle`             | A source card's URL row is a `link inline` around an `<a>`: foreground at rest, primary on hover, regular weight, truncating (`text-current font-normal hover:text-primary underline-offset-2 max-w-full justify-start`). One disable.                                                                                                                                                                                                                                                          |
| `admin/Overview.tsx`                                              | `shadcn/no-restyle`             | "View in Audit" under the denied-sign-ins tile keeps the tile's destructive tone at hint size (`text-destructive text-xs font-normal`). One disable.                                                                                                                                                                                                                                                                                                                                            |
| `settings/PairDeviceModal.tsx`                                    | `shadcn/no-restyle`             | The install link in Pair a remote machine sits in a 12px hint (`text-xs font-normal`, `self-start` in its column). One disable.                                                                                                                                                                                                                                                                                                                                                                 |
| `agents/workflow/WorkflowBuilder.tsx`                             | `shadcn/no-restyle`             | The publish-error Alert floats over the canvas with its close button in the top-right corner, so it pads `pr-10` to keep a long title clear of the button. One disable.                                                                                                                                                                                                                                                                                                                         |

Note that a multi-line reason has to be a `/* ... */` block comment;
consecutive `//` lines only disable the next comment line, not the code.

## Removed classes

`no-unknown-classes` is at `error`. Before deleting a class the lint calls
unknown, grep for it in `querySelector`, `classList` and `data-` lookups; a
class can be a hook for code rather than a style.

## Live style guide

`npm run dev`, then open `/design`. The page (`src/design/DesignSystem.tsx`)
renders every `ui/` component with the variants above, shows the resolved
value of each colour token and has a theme toggle. It is registered only
when Vite runs in development mode, so it never ships. When you add a
variant or token, add it there too.

## Cleanup playbook

Every `shadcn/*` rule is at `error`, and on commit `lint-staged` runs
`npm run lint-fix` and `npm run format` (both over the whole `src`), so a
violation blocks the commit. Work one file at a time and
keep every step green.

1. **See the state.** `npm run lint:design` prints violations (`shadcn/*`
   and the design `no-restricted-syntax` selectors) by rule and the worst
   files. `npm run lint:design -- --file src/settings/Teams.tsx`
   lists every violation in one file with the fix the message proposes;
   `-- --rule no-raw-colors` lists files for one rule.
2. **Pick a file, read it whole**, then fix all of its design violations in
   one pass. Map raw colours to tokens (table above), replace hand-rolled
   boxes, pills, tiles, spinners and dropzones with the `ui/` components,
   and move Button/Input/Select overrides onto `variant`, `size`, `shape`.
   Delete the `dark:` twin of every class you tokenise.
3. **Do not restyle `ui/` components from a page.** If a treatment is used
   in more than one place and no variant fits, add the variant in the
   component file, add it to `src/design/DesignSystem.tsx`, and document it
   here. A one-off gets `// eslint-disable-next-line shadcn/<rule> -- reason`.
4. **Keep behaviour identical.** Same DOM order, same handlers, same
   translations (`t(...)` keys stay). Only classes and component choice
   change. Prettier with the Tailwind plugin reorders classes; run
   `npm run lint-fix` rather than fighting it.
5. **Verify per file**: `npx eslint <file>` (zero errors),
   `npx tsc --noEmit -p tsconfig.json`, `npm test`, and look at the screen
   in the running app (`npm run dev`, then the page that renders the file)
   in both themes.

Known traps:

- `npm run lint` reports 0 errors and about 325 `@typescript-eslint`
  warnings (mostly `no-explicit-any`) unrelated to design; `tsc` is clean.
- Port 5173 may be held by another checkout; check the Vite banner shows
  this repo's path before trusting what you see.
- `components/SkeletonLoader.tsx`: the chunk, source, tool, add-tool and
  agent layouts are Card mirrors with `Skeleton` bars, and the `chatbot`,
  table, logs, default, analysis, connected-state and files layouts use
  `Skeleton`; none pulses its own surface. `renderFilesSection` (and the
  GoogleDrivePicker box it mirrors) is still a raw `border rounded-lg` box;
  move both onto `Card` when you touch them.

## Working with the lint

```bash
cd frontend && npm run lint
```

All `shadcn/*` rules are `error`, and so are the DESIGN.md selectors under
`no-restricted-syntax`: `eslint/design-rules.js` (class and markup rules,
tested in `src/design/designRules.lint.test.ts`), `eslint/card-surfaces.js`
(tested in `src/design/cardSurfaces.lint.test.ts`) and the viewport-height
and focus-return entries in `eslint.config.js`. Add a new checkable rule as
a selector there, with a test and a line here. Add a variant or token only when a treatment
is used in more than one place and none of the existing ones fits; a single
special case gets a disable comment with a reason.
