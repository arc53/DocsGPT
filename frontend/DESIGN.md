# DocsGPT frontend design system

The UI is Tailwind v4 plus the shadcn-style components in
`src/components/ui/`. `@shadcn/lint` and the `no-restricted-syntax`
selectors in `eslint/` enforce the rules below through `npm run lint`; their
messages point here. Everything in this file is either a
token in `src/index.css` or a variant in a `ui/` component, so an agent or a
contributor can always find the concrete thing to use.

Per-area specs (page chrome, the agent pages, app chrome, the chat, source views, the workflow
builder, connectors) live in [PATTERNS.md](PATTERNS.md): this file is the system, that one is how
each area applies it.

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
| `sidebar`, `sidebar-accent`             | the navigation rail and its hover / current-row fill                              |                                                                     |
| `chart-1` to `chart-5`                  | data series only, never UI chrome (see below)                                     |                                                                     |
| `answer-surface`                        | every panel under an answer: source cards, View more, the wiki path chip, the code-block and Mermaid headers (`CodeFrame`), the attachment chip, `CodePanel` |                    |

The shadcn twins are aliases in `src/index.css`, not values of their own:
`card-foreground`, `popover-foreground` and `accent-foreground` are
`var(--foreground)`, `popover` is `var(--card)` and `input` is
`var(--border)` (re-declared under `.dark` so they resolve to the dark
values). Change the base token; the twin follows.

Status colours are tuned to stay vivid rather than turning brown or olive,
so their contrast is low. Against white in light mode, `destructive` and
`success` are about 3.8:1, `warning` is 2.9:1 and `info` is 5.2:1. On the
dark card, `destructive` is 2.9:1 and the others are 5.5:1 or more. Do not
use them for long body text; they are for badges, icons, short labels and
fills.

`muted-foreground` is #6b6b6b in light: 5.33:1 on white, 4.93:1 on `muted`,
4.51:1 on `accent` and 4.67:1 on `secondary`, so muted text passes AA on a
hovered or open row too. Dark keeps #a1a1a1; its one known exception is a
dark hover (4.06:1 on `accent`). JS fallbacks for the token (chart and graph
colours read at runtime) use the same #6b6b6b.

The dark `primary` (#8855f1) is set so white text on it reaches 4.55:1 on
every default Button. As text on the dark surfaces it is below 4.5:1 (3.45:1
on background, 3.06:1 on card), so links and `text-primary` in dark pass only
as large or UI text; a fix for that needs its own link token. `ring`
and `secondary` keep the lighter #976af3.

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
component's own base tone (brand on a Badge or Button, quiet on a Toast).
`neutral` is the grey pill. Alert has neither: it is always one of the four
statuses (see Alert).

One tint scale, by purpose:

- Wash `/5`: a whole surface that is selected or receiving a drop (OptionCard
  `selected`, Dropzone drag-active and drag-reject, a chosen checkbox row; see
  Row states below). The border carries the state; the wash only warms the
  surface. Never on a chip or a text fill.
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
  It is a small well inside a panel that holds an asset (code, a file, a value
  to copy; see Code blocks), never a note (a static note is `Alert
  variant="info" role="note"`, see Alert) and never a page-sized panel around
  cards (see Card surfaces). Other grey boxes are Cards: a grouped sub-panel
  inside a `subtle` panel is a `subtle` Card (`padding="sm"`), a search result
  or a summary with its field in a modal is an `outline` Card, and a token or
  record tile is a `filled` Card.
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
  alike, and never reads as the neutral ghost hover. On a Button, use it as
  `variant={active ? 'secondary' : 'ghost-muted'}` with `aria-pressed={active}`;
  a chip in a wrapping "any of N" row is `ToggleChip`, which draws the same
  pair (see ToggleChip). That is for one thing
  switched on or off. Picking one value of several (a 7d / 30d / 90d range,
  a schedule's frequency, a filter row) is a `ToggleGroup`, whose on item has
  the `outline` look with no hue (see ToggleGroup).
- Row states: an open or selected list row is `bg-secondary` (ListRow and
  TableRow `selected`, CommandItem `checked`, Logs' open row); hover is
  `bg-accent`. Framed rows (Logs, ToolConfig's actions) have no fill at rest,
  `hover:bg-accent` while closed and `bg-secondary` while open, with no hover
  fill under an open row; a trash on the header is
  `ghost-destructive-on-accent`. A chosen checkbox row (ImportSpec's endpoints) is
  `has-[[data-state=checked]]:border-primary
  has-[[data-state=checked]]:bg-primary/5`; its wash beats the hover by
  design, so a chosen row never turns grey under the pointer.
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

| Prop      | Values                                                                                                                                                                                                                                          |
| --------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `variant` | `default`, `secondary`, `outline`, `outline-primary`, `ghost`, `ghost-muted`, `ghost-destructive`, `ghost-on-accent`, `ghost-destructive-on-accent`, `link`, `destructive`, `destructive-outline`, `combobox`, `sidebar-item`, `section-toggle` |
| `size`    | `default`, `xs`, `sm`, `lg`, `field`, `icon`, `icon-xs`, `icon-sm`, `inline`, `text`; the type (size and weight) lives on the size, and `text` has none, so it inherits                                                                         |
| `shape`   | `default` (rounded-md), `pill` (rounded-full, wider padding at `default`, `lg` and `field`)                                                                                                                                                     |
| `tone`    | unset (the variant's colour) or `current` (the text colour of what it sits in, hover included)                                                                                                                                                  |

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
  markdown, a hint's "Learn more", a Cancel in a status line) is
  `variant="link" size="text"`, with `asChild` around the `<a>`: no height or
  padding and no type of its own, so it takes the sentence's size, weight and
  line-height and keeps `primary`; underlined on hover, the shared focus ring.
  A standalone link ("Learn more" with `ExternalLink`, "Go to Tools" with
  `ArrowRight`, the icon a child) is `size="inline"`: the same, but 14px
  medium, so it reads as a control. A link that takes the colour of what it
  sits in (a status Alert, the Mermaid dark overlay) adds `tone="current"`.
  A trailing link icon (`ArrowRight`, `ExternalLink`) is 12px, and `inline`
  and `text` set it, so don't add `size-3`; a leading icon in a link sets
  `size-4`. Toggles and crumbs keep a normal size. Never style a raw `<a>` as
  a link (enforced).
- Icon-only buttons: see IconButton below. A `title` on a `Button` is
  rejected (enforced).
- An action whose label doesn't fit beside a name on a phone (the shared
  agent card's Edit, in a long locale) is two elements: an `IconButton`
  with `sm:hidden` and the labelled `Button` with `hidden sm:inline-flex`.
  Never hide a Button's label span, which leaves an icon-only Button.
- A Button that holds a user-supplied name (a chat, agent or source) in a
  flex row: Button's base is `shrink-0 whitespace-nowrap`, so `min-w-0` alone
  does nothing. Pass `min-w-0 shrink` (or `flex-1` when it should fill the row) and put the name in the
  `truncate` span; its icons stay `shrink-0`. `w-full` doesn't count: a
  `w-full shrink-0` Button takes the whole row and pushes its neighbour out,
  under the next control (an `outline` Button's fill is translucent in dark, so
  it shows through there and hides in light). `variant="combobox"` already
  carries `min-w-0 shrink`, like the fields it sits among. The phone top bar's
  title is the worked example (PATTERNS.md › App chrome).
- Roles for dangerous and dismissive actions: a delete on a page (a "Danger
  zone" card's Delete agent or Revoke, Delete all; see Card › Danger zone) is
  `destructive-outline`;
  the submit of a confirm dialog is `destructive` (`ModalActions destructive`,
  `ConfirmationModal variant="destructive"`); Cancel is `ghost` at the size and
  shape of the button beside it, in a modal footer, a form header or an inline
  editor. A Cancel inside a line of text (the composer's queued send) is
  `link text`.
- The composer controls under the chat field: see PATTERNS.md › Chat composer.
- `variant="combobox"` is the trigger of a popover picker and matches
  `SelectTrigger`: card fill, normal weight, muted text while
  `data-placeholder` is set, a ChevronDown that turns while open. App code
  doesn't draw it by hand: a single-select picker is `ui/combobox` and a
  multi-pick is `MultiSelect`, which both draw it (see Combobox).
- A button or picker that sits in a row of fields is `size="field"`: 38px.
  `Input` and `SelectTrigger` are 38px too (Input `default`,
  SelectTrigger's default `field`, Combobox and MultiSelect always `field`),
  so a form column has one height. Page actions beside a
  page's search field (Add Source, Add Tool, Test retrieval, Sync) are
  `size="field" shape="pill"`, with no min-width or hand height. With
  `shape="pill"` its text starts 21px in, like the Input and Select pills
  beside it. The agent form's pickers are `combobox field`, each labelled by
  a `FormField` (the Prompt picker through `Prompts titleAs="field"`), its Add
  button `outline-primary field`, the only `outline-primary` on the agent
  pages themselves (the Access details modal they open has its own).
- **Shape by place.** Form controls (Input, SelectTrigger, a combobox Button,
  Textarea, and a button inline with a field such as Add or Run) are square
  in forms, modals and sheets. Pill is for page chrome: header and toolbar
  actions, `SearchInput`, page filters (Logs, Analytics, GuardrailEvents,
  the admin Activity toolbar, whose CSV / NDJSON exports are `outline field
pill`), and a field that takes a pill header button's place (AgentsList's
  new-folder field). Modal footers (`ModalActions`) stay `lg pill`.
- Buttons on the agent pages (Overview, Logs, Schedules, the workflow builder's
  toolbar): see PATTERNS.md › Agent pages.
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
- Inline disclosure toggles ("Advanced settings", "Show advanced options",
  a device's audit log, the connect wizard's tool count): use
  `CollapsibleTrigger` (see Disclosure).
- Tabs are `ui/tabs`, and the underline is their only look (no `variant`
  prop): muted text on a transparent 2px bottom border, square corners, no
  hover fill; the active tab gets `foreground` text and a `primary`
  underline, on a 1px baseline the list draws. Tabs that switch a panel in
  place are `TabsList` + `TabsTrigger`, with `role="tablist"`/`"tab"`,
  `aria-selected` and arrow-key focus; wrap the panel in `TabsContent`
  (FilePicker's My files / Shared with me, Schedules' Recurring / One-time in
  `agents/schedules/SchedulesView.tsx`, the graph source view, the source
  edit drawer). Each trigger is 36px with `px-4`, so the first label sits
  16px in from the content edge and the underline runs past the label on
  both sides. That inset is deliberate: the tab row reads
  as its own strip, with a wider target per tab, so don't pull it flush with
  `-ml-4` or strip the padding. Tabs that navigate are `NavTab` (`asChild`
  around a router `<Link>`, or a `<span>` for the page on screen, `current`
  setting `aria-current="page"`), in a `<nav>`: the same recipe and 36px,
  edge to edge, `-mb-px` laying the underline over the row's baseline. Never
  Radix Tabs for routes. Its one use is `agents/AgentPageHeader.tsx`, the
  workflow builder's fixed toolbar (Overview / Logs / Schedules, no tabs until
  the workflow has an id); the agent section pages switch with the section
  sidebar (the phone menu below `lg`) and the agent tile's ⋯ also opens Logs.
  Panels unmount when hidden, except one whose state is costly to rebuild
  (the graph source view's laid-out canvas and zoom): that `TabsContent`
  takes `forceMount` plus `data-[state=inactive]:hidden`.
- A section panel's disclosure header (NewAgent's Advanced and Guardrails
  panels, `variant="section-toggle"`): use `CollapsibleTrigger
  look="section"` (see Disclosure).
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
  "Saving…", or pin a fixed width to stop the jump. A busy link (`size="text"`
  or `inline`) has no frame to hold that empty space, so `loading` keeps its
  label readable in place, faded, with the spinner after it. The one exception is a
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
| `padding`     | `none`, `sm` (p-3, row boxes; code wells are `CodeBlock` / `CopyField`, which draw it), `default` (p-4), `lg` (p-6, tiles, panels, stat tiles, a danger zone) |
| `interactive` | `true`: whole card is the target: hover and focus ring; pair with `asChild` around a `<button>` or `<Link>`. `within`: a stretched child `<button>` is the target and the card draws its hover and focus ring (see A clickable card that holds a link) |

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
| Choice (picker tile) | `outline interactive`, or `OptionCard`                                            | the Add tool tiles; a chosen tile is an `OptionCard` `selected`, drawn by the border |
| Well                 | `CodeBlock` / `CopyField` (a `filled sm` Card they draw)                          | code, a token to copy, run output, inside a panel (see Code blocks below)            |

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
- **Muted text on a fill.** `text-muted-foreground` fails AA on the muted
  fill, so inside a `filled` Card (a tile, and also a well, since `CodeBlock`
  and `CopyField` draw one) every `text-muted-foreground` element that isn't
  an svg or a button reads as `foreground`, the same mechanism
  `tone="destructive"` uses. Icons and ⋯ buttons stay muted (3:1 is enough
  for them). A tile's hierarchy comes from size and weight, not a lighter
  grey; don't pass one back.
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
- Form sections (the agent form's panels): see PATTERNS.md › Agent pages.
- Row boxes inside a form or panel (a guardrail check, the schedule's
  timezone box) are `padding="sm"`, in the panel
  variant of the surface they sit on (`subtle` in a page panel, `outline` in
  a modal). A list of named items in one (the custom MCP modal's discovered
  tools) is a `SectionHeader size="xs"` over `Card padding="none"
  overflow-hidden` holding `ListRows`.
- A schedule row: see PATTERNS.md › Agent pages.
- **Danger zone** (Delete agent, Revoke a device, Settings → General's Delete
  all): `Card tone="destructive" padding="lg"` laid out as a wrapping row
  (`flex-row flex-wrap items-center justify-between`), a `SectionHeader
tone="destructive"` (the title, and the consequence as its `description`)
  and one `destructive-outline field pill` Button whose label is the action
  ("Delete agent", "Revoke"), which opens the confirm (see Confirm dialogs).
  A failing stat is `tone="destructive"` too. Muted text fails AA on the red fill, so the tone turns
  every `text-muted-foreground` inside it to `foreground`, except a hovered
  Button, which keeps its hover colour (a `ghost-destructive` Remove still
  turns red); don't pass a lighter colour back. Icon buttons inside a destructive-tone row are
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

Tile text: the name is `CardTitle` (14px semibold from Card's `text-sm`; pass
`as="h2"` on a page that goes from its title straight to a tile grid, but
never a heading inside a clickable tile, whose children a button flattens; it
sets its own `title` from a string child when its className truncates or
clamps, see Typography roles › Truncation), the
description `CardDescription size="xs"` (12px muted, `leading-relaxed`, no `title`), and
meta lines (a date, a token count, a model id or host) go in `CardFooter` at
regular weight. `font-medium` is for list rows (`ListRow`), not tiles.

### Code blocks (`ui/code-block.tsx`)

App output, a value to copy, a labelled block and a markdown fence are one
family; never hand-build a `<pre>` in a Card. Text is `font-mono text-xs`
(one 16px line), `whitespace-pre-wrap`, and never `break-all` (enforced).

- **`CodeBlock`**: app output (a run's output, an error trace, a JSON
  payload). `surface` follows what is underneath: `filled` (a muted well) on a
  card or background, `subtle` on a muted surface (the tool-approval card, an
  expanded log row), `bare` (no box, so boxes don't nest) inside an Alert or a
  `CodePanel`, `pane` for a full-pane file viewer (the pane's `p-4`, scrolling
  inside its height). `maxHeight` `sm | md | lg` (160 / 240 / 320px) or
  `parent` (scrolls inside a height the caller sets); the cap is the
  component's, on an inner div so the scrollbar never runs into the Card's
  corners, so never cap it yourself. `wrap="anywhere"` for URLs and tokens,
  `tone` `muted | destructive` (`muted` reads as foreground on a `filled`
  well; see Card surfaces), `font="sans"` for recorded prose (a trace's
  query).
- **`CopyField`**: a value to copy (a URL, a token, a command): a filled row
  with the value (`select-all`) and the copy button, its first line on the
  button's centre whether it runs one line or several. `wrap="anywhere"` for
  URLs and tokens; `size="display"` for a short code read aloud (a pairing
  code: 30px, centred).
- **`CodePanel`**: a labelled block under an answer or in a trace (a tool
  call's arguments and result): the `answer-surface` strip with the label and
  the copy button, a `bare` CodeBlock under it.
- **Markdown fences** go through `markdownCode` (`lib/markdown.tsx`; see
  Typography roles › Markdown), which draws a `CodeFrame`: the bordered frame
  with the language and copy button in a header (the `answer` or `muted`
  surface) over the highlighted source, which keeps its
  lines (`white-space: pre`) and scrolls sideways inside the frame. The
  Mermaid diagram uses the same `CodeFrame`.

Every copy button in the family is the icon-only `CopyButton` at `sm`, drawn
by the component; never `showText` there.

### SectionHeader (`ui/section-header.tsx`)

`<SectionHeader as title count description actions size tone>`. `size`:
`title` (20px `text-xl leading-tight font-semibold`, the Title role for a
detail page or panel whose header isn't a Modal or PanelHeader: a remote
device's config), `default` (18px `text-lg font-semibold`, a section title
on a page or panel), `sm` (the eyebrow, `text-muted-foreground text-xs
font-semibold uppercase tracking-wider`, a label set in caps above a group or
a table head), `xs` (14px `text-sm font-semibold`, a sub-heading inside a
panel, drawer or modal). A title that truncates with its full value in a
`title` attribute (a team's detail page) stays a plain heading.
`tone="destructive"` for a danger zone only. `count` is the tally beside the
title (see Counts). `as` is the level in the outline
(`h2` default, down to `h6`): nested panel sections keep the outline (the
connection drawer: service `h3`, Knowledge / Tools `h4`, a tool `h5`, its
action groups `h6`). The spacing below belongs to the parent's `gap-*`, never an
`mb-*` on the heading. Not for dialog and sheet titles (their own title) or a
page byline (a muted `text-sm` paragraph).

A title with controls beside it (Add, a filter Select, Import spec) passes
them as `actions`, never a hand-rolled `flex justify-between` row around the
header: the row centres the title on the buttons and wraps them under it on
a phone (`flex-wrap items-center gap-x-4 gap-y-2`). Panel and chart titles
are `size="xs"` with `as="h3"`; a title row that also holds a legend or a
"Resets" line keeps its wrapper and swaps only the heading. Disclosure
headers (`CollapsibleTrigger look="section"`) and the Agents breadcrumb are not
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
Icons take the square's colour, lucide glyphs and service logos alike: a
service tile (Add knowledge's "From a service", three to a row from `md`)
draws its logo in `text-current` so it matches the source-type tiles above
it, and its description is only its status ("Connected", "Reconnect"), never
an account name. "From a service" shows at most six tiles: every service with
an account, then the rest up to the cap, and always a "Browse all
connectors" link under them.

### Badge (`ui/badge.tsx`)

`variant`: `default` (brand), `neutral`, `success`, `warning`, `destructive`,
`info`, `outline`. Replaces every hand-rolled
`rounded-full bg-<colour>-100 px-2 py-0.5 text-xs text-<colour>-700 dark:...`
pill, including schedule and run status pills (`agents/schedules/StatusBadge.tsx`
maps schedule and run statuses to Badge variants), trace chips and statuses,
token scope chips, "Disabled" and tool chips. A grey chip is `neutral`, never
a `bg-muted` pill: `neutral` is `bg-muted-foreground/15 text-foreground`
(muted text fails on its own tint; the same pair as Avatar `muted`). The admin role is `default` wherever it shows (Teams, Admin
→ Users); every other role is `neutral`. A shared asset's tile (agent,
source, tool, prompt) shows the caller's role with `components/RoleBadge`: a
`neutral` Badge with `Users` first (Editor, Viewer, from `roleOf()`); your own
assets show none. Badge's contract allows `font-mono` (chips that show
identifiers: token scopes, workflow state keys) and `tabular-nums` (stat
chips: durations, counts); no disable needed. HTTP method pills take their variant from
`getMethodBadgeVariant` (`utils/httpMethodColors.ts`): GET `success`, POST
`info`, PUT `warning`, DELETE `destructive`, PATCH `default`, anything else
`neutral`.

A removable chip (a filter chip, a picked source) is `<Badge onRemove
removeLabel>`: a named X button (12px X in a 16px round hover well, a 24px
hit area) at the chip's end. Never a hand-placed X beside a Badge, and never
a remove button inside another button.

`MultiSelect` (`ui/multi-select.tsx`) shows its first two picks as `default`
Badges (one on a `pill` trigger, so a toolbar stays one row), then "+N more",
on a `combobox field` trigger (`shape` passes through: `pill` in a page
toolbar) that grows past 38px when the chips wrap, with the turning chevron.
The chips have no X, since the trigger is a button: unselect in the list. Each
row in its list shows a `Checkbox size="sm"`. An option's `description` is a muted `text-xs` line
under its label in the list only ("Added by Lena"); the chips show the label. Inside a Modal
or Sheet pass `modal` (see Modal, not Dialog).

In a picker list, mark the item that is currently chosen with
`CommandItem checked` (a `secondary` brand tint through `data-checked`), not
with `bg-accent`: cmdk's own `data-selected` highlight is `bg-accent` and
follows the pointer and arrow keys, so an accent fill would look like hover.
While a checked item is also highlighted it keeps its tint and text and gains
a 1px inset `primary` ring, so the chosen row never turns plain grey.

`MultiSelectPopover` searches with the stock `CommandInput` strip, full
bleed, over an unframed `CommandList`, and caps itself at the height Radix
says is free (`--radix-popover-content-available-height`, at most 600px).
A picker's footer (`MultiSelectPopover footer`) links to the page that manages
the list, as a `link inline` Button with a 12px `ArrowRight` (Go to Sources, Go
to Tools). A shortcut action (Upload new, Add tool; an `outline-primary pill`)
sits at the right end of the same row: `flex flex-wrap items-center
justify-between gap-3`, so on a narrow sheet or in a long locale it wraps under
the link rather than taking a row of its own everywhere. Every picker uses
`PickerFooter` for this row (`SourcesPopoverFooter` wraps it for sources); a
notice (connections to sign in again) goes above it.

### Input (`ui/input.tsx`)

| Prop      | Values                                                                               |
| --------- | ------------------------------------------------------------------------------------ |
| `size`    | `sm` (h-8), `default` (h-9.5, 38px, the form-row height)                             |
| `shape`   | `default`, `pill`                                                                    |
| `variant` | `default`, `bare` (no border, padding, radius, shadow or ring), `filled` (card fill) |

Text alignment classes (`text-right`) and `font-mono` (code fields) are
allowed on Input and Textarea. `<Input label>` is the shorthand for a
one-field `FormField`: the same floating label on the border and the same
`labelSurface` (see FormField). A
default-size pill (38px, the form-row height) pads `px-5`, so its text
lines up with the Select pills. Compact table
filters (`h-auto px-2 py-1 text-sm`) are `size="sm"`. An inset icon (a
search glass) is `leftIcon`, with or without a `label`; it pads the field
`pl-10`, so never hand-place an icon over an Input. A field inside a host
that already draws the frame (the renaming sidebar row, a search strip in a
bordered panel) is `variant="bare"`; the host shows focus, and any inset
padding goes on the host, not the field. A field on a muted panel (the
tool-approval card's deny reason) is `variant="filled"`, so it keeps the card fill
instead of showing the panel through; never pass `bg-card` for it. A floating
label rests at the field's own text size (16px, 14px from `md`), so a
labelled search and a placeholder-only one read the same, and with a
`leftIcon` it rests where the text starts (40px in).

### SelectTrigger (`ui/select.tsx`)

`size`: `sm` (32px) or `field` (38px, the form-row height, the default);
`shape`: `default`, `pill` (page filters: Logs, Analytics, GuardrailEvents).
There is no ghost trigger. A `field` pill pads `px-5` (an `sm` one `px-3`), so
its text starts 21px in like the Input and Button field pills. A select in a
form is labelled by `FormField`. SelectTrigger is `w-fit`; pass `w-full` in a
form column. Fields that take typing or sit beside one are 16px
below `md` (iOS zooms on focus under 16px) and 14px from `md`: Input,
Textarea, SelectTrigger `field`, Button `combobox` `default | field | lg` and
CommandInput. The `sm` sizes stay 14px. A highlighted list row is
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
list that sits on the page (a source view's navigator filter, see PATTERNS.md ›
Page chrome and Source views); nothing else hand-frames it. `CommandList` caps
itself at `max-h-75` and scrolls; a list that already scrolls inside its
host (a Modal's phone sheet body) passes `max-h-none` so there is
one scroller. `CommandItem` rows are `cursor-default` like Select and menu
items, highlight `bg-accent` and mark the open item `checked`
(`bg-secondary`); don't add `cursor-pointer`. cmdk highlights the first row
by default, which reads as hover. A list used as navigation, where a current
item exists (the source navigator), starts the highlight on that item, or on
a value that matches no row while nothing is open
(`tree/SourceNavigator`'s `NO_HIGHLIGHT`); a search-then-pick list keeps
cmdk's first-row highlight. A list whose focus stays elsewhere (PromptTextArea's
`{{` variable menu under its textarea) forwards ArrowUp / ArrowDown / Home /
End / Enter from that element to the `Command` root, so the keys drive the
list while the caret stays put.

### Combobox (`ui/combobox.tsx`)

A single-select picker is `Combobox`; never hand-build a Popover + Command
picker. Its trigger is `combobox field` (`shape="pill"` in a page toolbar)
with the turning ChevronDown, the picked label truncating with a `title`, and
its option's `hint` muted at the end; the list is a Command in a popover at
least the trigger's width (18rem by default), the picked row `checked`. It is
`modal` by default, so it works inside a Modal or Sheet, and a `FormField`
labels and wires it (see FormField).

- Options are `options` or headed `groups`; an option's `leading` (an
  Avatar) and `hint` (muted trailing text: a UTC offset) show in the row.
- A server-searched list passes `shouldFilter={false}` with `search` /
  `onSearchChange`, and `valueOption` when the picked option isn't in the
  current results.
- Row actions (a prompt's Edit or View) go in `renderItem`, which replaces
  the row's body.
- `mode="add"` is a picker that adds something (Share's "Add people or
  teams"): the trigger always shows the placeholder and no row is marked.

A multi-pick is `MultiSelect` (see Badge).

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

`Input`, `Textarea`, `SelectTrigger` (even nested in `Select`), `Combobox`,
`MultiSelect`, `Dropzone`, `Checkbox` and `Switch` read their `id`, `aria-invalid`, `aria-describedby`,
`aria-required` and `disabled` from it, so don't set those by hand; an id
the field already has wins. Any other control: pass `id` to FormField and
the same id to the control. One FormField holds one control: a second field
inside it needs its own `id`, or it takes the field's. Popovers reset the
wiring (`FormFieldBoundary`), so a picker's search box is safe.
`className` is layout only. `<Input label>` is the one-field shorthand; never
put it inside a FormField (two labels).

`float={false}` puts the label above instead (14px medium, 6px up), for a
FormField with no single box to sit on: a list of checkboxes, several
controls in a row, a loading or error line in place of the field. On a
`tone="destructive"` fill no `labelSurface` matches, so fields there use
`float={false}` too. Controls
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
each 12px (none at the group's ends). It wires its control like FormField:
the title is a `Label` for the control's id (`htmlFor`, or a generated one),
and the control's `aria-describedby` is the description, so every switch has
a name and a description and clicking the title toggles it. A `Switch`,
`Input`, `SelectTrigger` or `Checkbox` takes the id from the row and needs
none of its own; any other control takes `htmlFor`. `as="h2" | "h3"` keeps a
heading tag, and the control then needs its own `aria-label`. `alignStart` top-aligns the control for wrapping
descriptions. `stack` puts a control too wide for a phone row (a 224px
picker) under the title below `sm` at full width; give the picker
`w-full sm:w-56`. `after` holds a field that belongs to the row, 8px under it
(the agent form's limit Inputs); it isn't wired, so it names itself
(`aria-label`, or a FormField of its own). Settings → General is the page-level example:
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

Tooltip text is 12px in a box at most 320px wide (`max-w-xs`) that wraps
with `text-pretty`, so a two-line tooltip fills its box; `text-balance` would
even the lines out and leave half the box empty. Tooltips open after 400ms. One `TooltipProvider` is mounted in `main.tsx`,
so moving along a row of icon buttons opens each at once after the first
(Radix's skip-delay); a `Tooltip` outside it (tests, a portal root) adds its
own provider. For a hint on something that is not an icon button, compose
`Tooltip` + `TooltipTrigger asChild` + `TooltipContent`; an icon-only link
(the collapsed rail's) is `TooltipTrigger asChild` around it, never `title`.
`title=` is not a tooltip: it only carries a cut-off value in full (see
Typography roles › Truncation).

### ToggleGroup (`ui/toggle-group.tsx`)

The segmented control for picking one value of several (`type="single"`) or
several of several (`type="multiple"`).
It has one look: the group draws its own muted pill track (`bg-muted
rounded-full`), and its items are pills, the on item the `outline` look
(`bg-background`, `shadow-xs`) with a `muted-foreground` border, which stands
out from the track at 3:1 or more in both themes, the others `ghost-muted`.
Off-item text is `muted-foreground`, 4.93:1 on the track in light. Never
hand-build a track: no `bg-muted rounded-full p-1` wrapper around a group,
and its className takes layout only (`shrink-0`, `self-start`, a margin).
An item's tally is its `count` prop (see Counts).

- **Width.** Pass `fill` when the group is the only control on its row, a
  form field (a schedule's frequency and weekday, the connect wizard's
  sign-in method, keep/delete in Remove, a workflow panel's mode): the track
  is `w-full flex-nowrap` and each item `flex-1 min-w-0 px-1`, so the row
  ends where the field under it ends. Everywhere else (toolbars, header
  actions, beside other controls) leave it off and the track hugs its items
  (`w-fit max-w-full`). A pill track never wraps: one that outgrows its row
  (a long kind filter on a phone) scrolls sideways (`overflow-x-auto
  no-scrollbar`; the track's padding keeps the focus ring unclipped).
- **Size is density.** `sm` (the default: 32px items in a 38px track) is
  level with `field` controls: forms and page toolbars. `xs` (28px items in
  a 36px track) is for dense panels: the graph toolbar, workflow panels,
  permission and parameter rows.

A single group is a `radiogroup` with one Tab
stop and arrow keys; it sends `""` when the on item is clicked again, so
ignore that in `onValueChange` (`(v) => v && setRange(v)`). Route links in a
row (the Agents filter pills) are not a ToggleGroup: they are `Button asChild
variant={active ? 'outline' : 'ghost-muted'} size="sm" shape="pill"` around
each `Link`, with `aria-current="page"` on the current one.

Filtering a list by kind (a team's shared resources, Share's People) is a
ToggleGroup that hugs (`sm` on a page, beside a 38px `SearchInput`; `xs` in
Share's dense list step), each item its label with the kind's `count`,
beside a `SearchInput` (`w-full sm:w-56`); no match is `EmptyState size="xs"
illustration="none"`.

### ToggleChip (`ui/toggle-chip.tsx`)

A pressed chip in a wrapping "any of N" row (guardrail stages, PII entities,
a custom model's capabilities, Mermaid's code view) is `ToggleChip`: Radix
Toggle, so it sets `aria-pressed`; the tint means on (`secondary`), off is
`ghost-muted`, both pills. `size` `xs` (28px, the default, dense panels) or
`sm` (32px, forms; a leading `Check` on the on chip). Never hand-build it as
`variant={on ? 'secondary' : 'ghost-muted'} shape="pill"`, and never
`role="switch"`. A `locked` chip is on and can't be turned off (an
instance-enforced guardrail floor): full colour, a trailing `Lock`,
`aria-disabled` (not `disabled`, so it stays readable) and the reason in
`title`; never an emoji. `disabled` is for a chip that is really unavailable
(a view-only form) and fades. Picking one of N is a ToggleGroup.

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
art, page / panel / popover), `illustration` `no-files | none`, `title`,
`description` (plain `muted-foreground`), `action`. An empty inline or inside
a card or panel (no runs yet, no members) is `size="sm" illustration="none"`,
and a "no results" line in a picker, popover or dense list `size="xs"
illustration="none"`; never a hand-built muted `<p>`. A page or panel whose fetch failed (see
Where a message lives › Load errors) is
`EmptyState tone="destructive" illustration="none" onRetry`: a red
`CircleAlert`, a red title, `role="alert"`, and `onRetry` draws the Retry
(`t('retry')`, an `outline sm pill` Button at every size, after `action` when
both are set). Hand-set that Button only for a Retry outside an EmptyState
(DeviceAuditList's inline one). Admin's `LoadError` is the same EmptyState, so
its Retry follows the locale too. Never a bare `text-destructive` paragraph.

### Progress (`ui/progress.tsx`)

`value` 0 to 100, `variant`: `default`, `success`, `warning`,
`destructive`, `info`; `size`: `sm`, `default`. Replaces the
width-percent divs in quota, indexing and guardrail views.

### Avatar (`ui/avatar.tsx`)

`size`: `none` (image decides, the default), `xs` (28px), `sm` (32px),
`default` (36px), `lg` (40px): Button's names at Button's heights; `xl`
(48px, `rounded-xl` when square) for a connector logo leading a drawer or
wizard header. `shape`: `none`, `circle`, `square`; `variant`: `default`,
`primary` (brand initials on `secondary`), `muted` (a grey
`bg-muted-foreground/15` box with `foreground` initials), `icon` (the icon
tile: `bg-muted` with muted text). Initials boxes pass the letters as
children.

The icon tile leading a row is `<Avatar size="sm" shape="square"
variant="icon"><Icon className="size-4" /></Avatar>` (32px; `xs`, 28px, in
the team switcher). Never a hand-built `bg-muted … size-8 rounded-md` span.

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

Feedback the screen itself can't show (uploads, runs, approvals, team
events, a page action's failure) is a toast in the bottom-right stack; a
result inside an open modal is an `Alert` there, since the toast stack
paints under the modal's overlay (see "Where a message lives"). The app has one
`ToastViewport`, mounted in `App.tsx`; it is the live region
(`role="status"`, `aria-live="polite"`) and the fixed stack, so `Toast`
cards carry no role and no toast renders its own rail or positioning. Top
to bottom it holds `TeamNotificationToast`, `ConnectionHealthToast` (a
connection that needs reconnecting, with a Reconnect action),
`ToolApprovalToast`, `UploadToast` and `ActionToast`, and it moves to the
bottom-left while any agent preview drawer is open (workflow or classic). A new toast component returns only its
`Toast` cards and is added to that viewport. A result the screen can't show
dispatches `showActionToast({ variant: 'success' | 'destructive', message })`
from `notifications/actionToastSlice.ts`: a chunk saved from the graph
reader's edit drawer, which closes as it saves ("Chunk saved"); a copy from a
reader's ⋯ menu; an admin Force logout; a page action's failure that happens
after its confirm closed (a source file delete). `ActionToast` shows it and
dismisses it after 4.5s, and a new result replaces the previous one. A result
the row shows gets no toast: Admin › Users' grant, revoke, activate and
deactivate show their success in the row's badge. Work that finishes after
the user has moved on has its own card: `UploadToast` follows an upload
through ingest to "Upload completed".

Compose `Toast` > `ToastHeader variant` (`default`, `success`, `warning`,
`destructive`, `info`) with `ToastTitle` and `ToastActions` (collapse and
close as `Button variant="ghost-muted" size="icon-sm"`), then
`ToastContent` (add `scrollable` for long lists) with `ToastItem label meta`
rows (optional `icon` before the label), a `ToastStatus status` circle per
row (`pending`, `success`, `warning`, `destructive`, `info`),
`ToastMessage variant` (`default`, or `destructive` for a failure) for an explanation and `ToastFooter` for action
buttons. `ToastTitle` truncates to one line; `wrap` lets a long title (a
localised string, a team name) wrap instead. `ToastMessage size` is `xs`
(default, the note under a row) or `sm` (`text-sm leading-4.5`, the whole
body of a notice). A message that is the only content under the header
gets its top padding on its own, and a message right after a `ToastItem`
shares that row's divider. Toasts own their width, radius and shadow; pass
no width or colour to them.

### A clickable card that holds a link

A card that opens something and also holds a link or other controls (a
source card under an answer, with its URL; a tile with a ⋯) is a plain
`relative` container:

- The target is a `<button type="button">` that is a **direct child** of the
  card and covers it with `after:absolute after:inset-0` (the card's radius
  on `after:`). The container draws its focus ring
  (`has-[>button:focus-visible]:ring-3 …ring-ring/50`); a `Card` does it with
  `interactive="within"` (Knowledge's source cards, the agent tiles).
- It comes first in DOM order, so Tab reaches the item before its menu.
- It is named by the title alone: the title is its content (or its
  `aria-label`), and the description stays outside it. A decorative avatar
  beside the title is `alt=""`.
- Every other control, the `ActionMenu` included, sits in a `relative z-10`
  (or `absolute … z-10`) element, so all are real controls, one tab stop each,
  and none sits inside another.

Never put a link inside a `role="button"` or a `<button>`.

### Where a message lives: FormField, Alert or Toast

- A message about one control is `FormField error` (it also turns the
  floating label red).
- A result the user must read before closing the modal (a failed share, a
  failed import, a Test connection result) is an `Alert` in the modal body.
- **Success** shows in the screen itself: the new row, the saved value, the
  closed modal or drawer, "Unsaved changes" going away. It doesn't also
  toast. A success toast is only for a result the screen can't show:
  background work that started, a copy from a menu, a save from a surface
  that has closed or navigated away.
- A failure on a page rather than in a modal, or a fire-and-forget result,
  is a toast (`showActionToast`). A failed confirm is the exception: its
  message stays in the open ConfirmationModal, never also a toast or a page
  Alert (see Modal › Async submits).
- **Load errors.** Every fetch that fills a page or panel has three states:
  loading, error and data. Its `catch` sets an error that renders
  `EmptyState tone="destructive" illustration="none" onRetry` in place of the
  content, never the empty message; resetting a list to `[]` in a `catch` is
  a bug. A 404 on a single item is "not found"; any other failure is the
  error. A failed later page of a feed is the `LoadMoreStatus` error strip
  (see Pagination › Feeds).
- A notice the user must read before acting (an expiring token, a policy that
  forces a setting, models without a price) is an `Alert`. A static note that
  is only informative and should not be announced (a view-only form, an
  explainer) is `Alert variant="info" role="note"`, never a `bg-muted` box.
- Status text of a sentence or more is an `Alert` (its variant draws the
  icon), never a coloured paragraph. A long notice about an old run inside a collapsed panel
  is `Alert role="status"`, not `alert`.
- An action's error on a full-page form (saving an agent) is an `Alert
variant="destructive"` above the form, not text in or beside the button.
- A list of errors the user must read on a canvas or page (the workflow's
  publish validation) is a destructive `Alert` floating at `z-20` on an opaque
  `bg-card rounded-xl shadow-md` wrapper that stays until closed; a toast
  would truncate each error to one line and dismiss itself. The workflow's
  stopped-resources warning is the same recipe (`FloatingResourceNotice`): it
  floats only while something is stopped, its X sits inside the Alert (`Alert onClose`), a long
  list scrolls in an inner `scrollbar-overlay max-h-* overflow-y-auto` div,
  and it steps aside while the publish errors show; once closed a chip
  reopens it.
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
  (`components/ViewOnlyNotice`: an info note, `Alert variant="info"
  role="note"`, with `common.viewOnlyNotice`) as its first child. Where only part of an editable
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
`variant` is required: `success`, `warning`, `info`, `destructive`. There is
no quiet default; a note is `info` with `role="note"`. 14px
corners (`rounded-xl`), like a popover. Every variant is the same
shape: `border-<role>/50 bg-<role>/10 text-<role>`. Children are
`AlertTitle` and `AlertDescription`.

The variant draws its icon: destructive `CircleAlert`, warning
`TriangleAlert`, success `CircleCheck`, info `Info`. Never pass an icon child, and no per-site overrides: a lock, a
shield or a mail glyph on one notice is not a reason. `icon={null}` drops it
where the body is itself the message (a `CodeBlock` error body:
TraceSpanDetails). The icon has its own 16px column in the text colour and
sits centred on the text block, beside a single line, a wrapped paragraph or
a title with its description.

A static note is `variant="info" role="note"` (see Where a message lives);
`bg-muted` wells are for assets, not notes.

Every variant is `role="alert"` except `success`, which is `role="status"` so a confirmation
is announced politely; pass `role` only to override that. `onClose` adds a
ghost `icon-xs` X in the top-right corner (named `close`) and pads the text
`pr-10` clear of it: the floating canvas notices (publish errors, stopped
resources); never hand-place a close button in an Alert. Replaces the hand-rolled
`rounded-lg border bg-amber-50 text-amber-800` boxes.

A failed chat answer and the rows in an answer's step column are chat recipes:
see PATTERNS.md › Chat answer column.

### Breadcrumb (`ui/breadcrumb.tsx`)

Pages pass nothing to the breadcrumb parts; the primitive does the layout.
`BreadcrumbList` stays on one line (`flex-nowrap`), every crumb gives way
(`min-w-0`) except the first, which stays whole (`shrink-0`), a
`BreadcrumbLink` truncates at `16ch`, and `BreadcrumbPage`, the current crumb,
at `32ch`, with a `title` set from string children. The one trail that wraps
is AgentsList's folder trail (see Approved exceptions). `BreadcrumbPage`
carries the link's focus ring: after a crumb step, PathHeader moves focus to
the new current crumb (`tabIndex={-1}`) so keyboard focus never drops to the
page. A crumb that runs a handler instead of navigating is `BreadcrumbLink
asChild` around a `<button type="button">`; the link carries the focus ring
and the cap. A parent with no handler is a plain `<span>` with `max-w-[16ch]
truncate` and a `title` (PathHeader's; it isn't a BreadcrumbLink, so it sets
the cap by hand), never a disabled button, and the current crumb is never a
disabled button either. The header of every source view is
`components/tree/PathHeader` (see PATTERNS.md › Source views); don't hand-roll a
`/`-separated path.

### ListRow and DescriptionList (`ui/list-row.tsx`, `ui/description-list.tsx`)

An identity row (avatar or icon square, a truncating title, one muted meta
line, a trailing control) is `ListRow` inside `ListRows` (`divide-y
divide-border`, no box of its own; wrap it in `Card padding="none"` or a
bordered list for one). Rows are `px-4 py-3`, the title `text-sm
font-medium`. A string `title` or `description` sets its own `title=` for the cut-off
value; for a node, put `title` on the node. `interactive` (with `asChild`
around a `<Link>` or `<button>`) hovers to `bg-accent` and draws an inset
focus ring. `selected` marks the row whose detail is open in a drawer beside
the list (a team's shared resources) and the chosen row in a single-pick list
(a repository in the connect wizard): the `bg-secondary` fill of a selected
TableRow (see Table), kept on hover, with `aria-current`, but the row's text
keeps its own colours (a foreground title, a muted meta line). A row you select that
also holds a ⋯ (a connection's accounts) can't be one `<button>`: it is
`ListRow interactive selected asChild` around a `relative` box whose title is
a stretched `<button data-account-select>` (`after:absolute after:inset-0`),
the box drawing that button's inset focus ring
(`has-[[data-account-select]:focus-visible]:ring-3 …ring-ring/50 ring-inset`),
and the ⋯ in a `relative z-10` trailing group. An icon square in
`leading` is the Avatar icon tile (see Avatar).
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
and links "Show all N" (a `link inline` Button) beside the title to the section's own page, which
shows everything at 48 per page. Sources opens at 24 per page on desktop and
12 below it.

**Feeds.** `useLoadMore` (items in the component) or `useScrollSentinel`
(items in Redux, where SSE merges new rows) watches a 1px sentinel after the
last item, so loading follows whatever already scrolls and never adds a
scroller: in a Modal, Sheet or SidePanel the body is still the one scroller,
and the sidebar's chats load inside the sidebar column. Only a feed on a page
gets its own cap: an inner `scrollbar-overlay max-h-[45svh] overflow-y-auto`
div inside the frame (the run log's schedule card, the guardrail table's
frame, a device's audit list), never on the Card. Under it, outside the
scroller, `LoadMoreStatus` (`divider` under a flush table) says "Loading
older…", "Nothing older" or offers Retry (an `outline xs` pill; `loadingLabel` / `doneLabel` for a
list that isn't newest-first: "Loading more…"); it keeps one row's height and so
keeps the scrollbar clear of the rounded corner. A feed shorter than one page
draws no strip. The end is a page shorter than requested, so no count is
needed. A first load shows `LoadingState`, and a failed one follows Where a
message lives › Load errors.

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

**Counts.** A count beside a label is the `count` prop of `SectionHeader` or
`ToggleGroupItem`: muted, normal weight, `tabular-nums`, never set in caps
(on an eyebrow too) and muted on the selected item too. A number is
formatted by the component; text is allowed ("2 of 5 allowed"). Never bake
`· N` or a number into a title string.

Dates and missing values go through the same file. Absolute dates are
`formatDate`, `formatDateOnly` or `formatDateTime`, en-GB (DD/MM/YYYY,
24-hour) in every language by decision; "a date or nothing" is
`formatTimestamp`, never a local wrapper. "Last …" and "next run" are
`formatRelative` (in the app language; `dateAfterDays` switches to the date
past a cut-off, `future` words a coming time as "in …"), never a hand-rolled
"5m / 3h". A missing value (a date, a count, an id) is `EMPTY_VALUE` (`—`),
never `-` or blank. A formatted date passed into `t()` is interpolated user
text (see Rules in one paragraph).

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

### Disclosure (`ui/collapsible.tsx`)

A body that opens and closes in place is `<Collapsible open id>`: a grid that
goes from `0fr` to `1fr` rows and fades over 300ms (`motion-reduce` turns the
transition off), its content clipped in one track and kept mounted while
closed but `inert`, so its fields leave the tab order. The body clips only
while closed or moving, so focus rings inside it show once it is open. There
is no Accordion.

The trigger is `CollapsibleTrigger` (same file): `open`, `onOpenChange` and
`controls` (the Collapsible's `id`). It sets `aria-expanded` and
`aria-controls` and draws a lucide `ChevronRight` first that turns while
open; pass layout only. Never hand-roll the Button.

- `look="inline"` (the default) is the `link sm` toggle for a group in a
  form, modal or drawer (RetrievalOptions' Advanced, a device's audit log,
  the connect wizard's tools, Share's Access settings). `chevron="sm"` draws
  a 12px chevron.
- `look="section"` is a section panel's header (NewAgent's Advanced,
  Guardrails): `variant="section-toggle"`, an 18px semibold title, a
  primary underline on hover. It only goes inside a Card: the toggle draws no
  focus ring, and every Card draws one round itself instead
  (`has-[[data-variant=section-toggle]:focus-visible]:ring-3 … ring-inset`).
  The caller wraps it in the `<h2>` (a button flattens heading children), and
  status badges go beside it, not inside, or the underline runs under them.
- Layout: a closed Collapsible is still a flex item, so a parent's `gap-*`
  would leave space under a closed toggle. Wrap the trigger and the
  Collapsible in a plain `<div>` and give the body the gap as top padding
  (`pt-3`, `pt-5` in a `gap-5` panel).
- Framed rows (ToolConfig's actions, Logs' rows) keep their own header: a
  real `<button type="button" aria-expanded aria-controls>` holding the
  chevron and the title, with any control (a `PermissionSelect`) as its
  sibling, never inside it, and never a `div role="button"` with hand-written
  key handlers. Their fills follow Row states: `bg-secondary` while open,
  never `bg-muted`.
- WorkflowPreview's step rows and UploadToast's rows use the Collapsible
  too; don't hand-roll a grid-rows wrapper.

### Modal, not Dialog

`ui/dialog.tsx` is the Radix primitive and is private to `ui/`; ESLint
rejects imports of it elsewhere. App code uses `Modal` (sizes `sm` to
`xl`) or `CommandDialog`.

On phones (below `lg`) a Modal is a bottom sheet by default (see Side panels
for the shape). `mobileVariant="dialog"` keeps the centred dialog, and only
for a yes/no confirmation: `ConfirmationModal` passes it, and so do the few
named opt-outs (sponsor confirm, Disconnect and Remove connection, Export
failed, Convert to wiki, Enable GraphRAG). A sheet never autofocuses a field
on a phone, where it would pop the keyboard up: the phone sheet skips Radix's
open autofocus, and a field's own `autoFocus` would bypass that, so a field
shown when a Modal opens doesn't take it (one that appears on a tap inside
it, Move to folder's new-folder field, may).

The width comes from `size` only: `sm` 384, `md` 512 (the default), `lg` 672
(a form or a one-column list: Move to folder), `xl` 896 (a grid of
tiles or a wide editor: Add tool, Test retrieval, the prompt editor). Don't
pass the default `size="md"`. Never add a width or height class. The dialog caps itself at `85dvh` and
its body is the one scroller, so the header and footer stay put; don't cap
the body with `contentClassName`. `contentClassName="overflow-visible"`
(`cn` drops the body's `overflow-y-auto` for it) is only for a body whose popover must escape it (Share
conversation, Move to folder). A Select's list is portaled and needs no escape. `className` is placement
only.

A modal's body is `flex flex-col gap-5` when it stacks floating fields,
with `gap-6` between labelled groups (a `SectionHeader size="xs"` and its
fields); FormField supplies the 6px to its hint. The body carries no padding:
Modal's scroll area already insets it (`px-1 pt-3 pb-0.5`) so focus rings
aren't clipped. Never `space-y-*` on a body.

A modal's heading is its `title` (20px, `text-xl leading-tight
font-semibold`) and `description` (muted `text-sm`, 8px under the title).
`leading` puts a node before that pair, as `PanelHeader leading` does: the
connect wizard's connector icon tile, on every step.

**Steps.** A second step inside a modal (Upload's source form, Share's full
list) passes `onBack`: an icon Back arrow beside the step's real `title` and
`description`, as PanelHeader's. Never hide the title and draw a Back
button and an `<h2>` in the body. `hideTitle` is only for dialogs whose top
line is not a title (ScheduleFormModal's editable name, the search palette).

A list in a modal that can grow long (Share's People) shows the first three
once it passes five, a `link inline` "Show all N" (its 12px `ArrowRight`
drawn by the size) in its SectionHeader's `actions` and a muted `text-xs`
"and N more" line, counts through `formatCount`. The full list is the second
step (`onBack`, the list's title and a summary as `description`), then the
search and kind filter (see ToggleGroup).

Buttons go in `footer`, never in `children`. The footer stacks full width on
phones (primary on top) and sits in a right-aligned row from `sm` up. The
standard pair is `footer={<ModalActions cancelLabel onCancel submitLabel
onSubmit pending disabled destructive />}`: a ghost Cancel and a primary
(or `destructive`) submit, both `size="lg" shape="pill"`; `pending` shows
the submit's `loading` spinner. A left-hand extra (Test connection) is
`footerStart`, and `submitProps` / `cancelProps` carry `type="submit"`,
`form` or a test id. A lone button is a `size="lg" shape="pill"` Button.

**Async submits.** A submit whose handler awaits the server passes `pending`
while it runs and closes only when it resolves; a failure stays in the dialog
as a destructive `Alert`. A yes/no confirm is `ConfirmationModal`: return the
request's promise from `handleSubmit` and let a failure reject (rethrow
after setting any message); it shows `pending`, closes on success and on a
rejection stays open and shows `error` (default `common.actionFailed`,
"Something went wrong. Please try again."). Prefer a domain key for `error`
over a transport message. Don't also toast or put an Alert on the page
underneath: one message, where the user is looking. Clear the confirm's
subject only on success. The exception is work that runs after the dialog has
closed (FileTree's queued file or folder delete): its failure is a destructive
`showActionToast`. `message` is the title, `description` the muted line
under it and `children` the body. A sync handler closes it at once, which is
right only for work that reports its own progress (a sync fires and closes).

#### Confirm dialogs

`src/modals/confirmCopy.test.ts` guards this copy.

- **Title** (`message`): the verb and the quoted name as a question,
  `Delete "{{name}}"?`, in each locale's quotes: `"…"` en / de / es, `「…」`
  jp / zh-TW, `«…»` ru, `“…”` zh. Never "Are you sure…".
- **`description`**: the consequence: what else goes with it, then "This
  can't be undone." (`common.cantUndo`) only when that is true.
- **Submit**: the bare verb from the domain's own key, never another
  domain's (`convTile.delete` is for conversations only). Every destructive
  confirm sets `variant="destructive"`.
- Names interpolate with `escapeValue: false` (see Rules in one paragraph).
- **When to confirm**: a remove that loses data or someone else's access
  confirms, unsharing from a team included; a remove the user can redo in
  one click (unpin, their own chip) doesn't.

A Popover, date picker or picker opened inside a Modal or Sheet takes
`modal` (Radix's, or `MultiSelect`'s; Combobox is modal by default), or its
list can't scroll and doesn't close on an outside click.

A search palette is `CommandDialog` on desktop. Pass cmdk options to its
inner `Command` through `commandProps` (`shouldFilter={false}` when results
come from a server search, a controlled `value`). On phones the same palette
goes in a `Modal` (its phone sheet) as `<Command variant="palette">`, which
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
working surface: a trace, an agent preview, the source editor. `size` is
modal-only (the types refuse it on a docked panel, which is always 480px
compact). A docked panel can be
`expandable="<surface>"` (the types refuse it on a modal one): Expand in its header steps compact,
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
details and Artifacts rows are the answer's step-row recipe (see PATTERNS.md › Chat answer column), each
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
shape with `pb-safe-0` (the bare inset) and draws no X (the scrim dismisses
it); pass `handle` for the grab bar, which is only a cue and doesn't drag.
Modal's phone sheet shares the shape and the `SheetHandle` (and has no X
either), with `pb-safe` (the inset, at least 1rem)
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
drawer, a bottom banner) calls `resetBottomTint()` when it is removed. Keep the
strip at 6px (bottom) and 16px (top) for one frame, in front of the content and
opaque: a strip behind the content, transparent or at `opacity-0` isn't
sampled, so don't shrink or hide the strip (the measurements are in
`ui/bar-tint-reset.ts`).

Content read alongside the chat (notes, todos, files, `components/ArtifactPanel`)
and an answer's sources (`conversation/SourcesPanel`, with a cited source's
`CitationReader` as its second level) share the chat's docked side panel (see
Side panels). Don't add another pattern.

### ActionMenu (`ui/dropdown-menu.tsx`)

The three-dots menu on a card, tile or row. Pass `options: MenuOption[]`
(`label`, `onClick`, optional lucide `icon`, `variant: 'destructive'`,
`disabled`, `separatorBefore` for a rule above a row, which sets a
destructive Remove apart from the reversible items; `icon` also takes an
element, such as a `ConnectorIcon`) and a `triggerLabel`. It renders a `ghost-on-accent` `icon-xs`
trigger with `EllipsisVertical`, and stops clicks and keys on the trigger and
the menu from reaching the host, so it can sit inside a clickable card.
In a page header or toolbar on a plain surface (the agent Overview's title
row, through `SectionShell titleAction`; the workflow builder's toolbar), pass
`size="toolbar"`: the trigger is a 36px `ghost-muted` icon button like the
others there, hovering to `accent`, with its tooltip below. The default
`row` trigger's darker hover is only for hosts that turn `accent` themselves.
`align` (default `end`) places the menu, `disabled` greys the trigger, and
`triggerTestId` puts a `data-testid` on it. `className` takes layout only (position, margin) and lands on the trigger.
`menuWidth` sets the panel: `default` (at least 144px, growing with its
labels), `sm` (128px), `lg` (192px) or `fixed` (160px). `open`/`onOpenChange` make it controlled.

A menu behind a labelled button ("Actions" as an `outline` pill with a
`ChevronDown`, "Download", a title button) passes that Button as `trigger`
instead of `triggerLabel`; its clicks propagate as usual and it has no
tooltip. Don't hand-build this menu from `DropdownMenu`, and don't declare a
local option type. A raw `DropdownMenu` is only for custom content (Help, the
team switcher, and the account menu: `ProfileButton`, whose header is a
`DropdownMenuLabel` (avatar, name and email) over a separator and Sign
out).

### Table, Label, dialog text

Every table is `ui/table`, markdown tables included (`markdownTables` renders
its parts); never a raw `<table>` (enforced) or a table utility class. The header row is dense by
default (`px-2 py-1 lg:px-3 text-sm font-normal text-foreground`, 28px, on
`TableHead`'s sticky `bg-muted` strip); Logs' header strip over its rows,
which is not a table, takes the same `foreground` text. A `TableRow` hovers (`bg-accent`,
pointer) only when it has an `onClick`; a read-only row does not. `selected`
marks the row whose detail is open beside the table (the graph's Entities):
`bg-secondary text-secondary-foreground`, the brand tint of an open navigator
item, kept on hover, with `aria-current`. A number column (sizes, tokens,
counts) is `align="right"` with `tabular-nums` on its cells, header included
in the alignment, whatever the column order (the file table, the graph's
Entities). Use `TableContainer` for the bordered, scrolling frame; a table that already sits
in a frame renders `Table` alone. `Table` keeps a 600px minimum so wide
tables scroll sideways; a narrow one inside a panel passes
`minWidth="min-w-0"`. A fixed column is `TableHeader width` (an icon column
`width="40px" align="center"`, a Name column `width="14rem"`), never a
`min-w-[…]` pin on the cells or the fields inside them.
`TableCell` and `TableHeader` accept typography and alignment classes and
`text-muted-foreground`. `Label`, `DialogTitle`, `DialogDescription` and
`SheetTitle` accept typography plus
`text-foreground` and `text-muted-foreground`. `DialogContent`,
`PopoverContent`, `SheetContent`,
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
leading-tight font-semibold`. `DialogTitle`, `SheetTitle` and `PanelHeader`
  draw it, and a detail page or panel title is `SectionHeader size="title"`;
  don't hand-write the classes, except on a title that truncates with a
  `title` attribute (a team's detail page). `font-bold` is never a title
  weight. A picker popover's header is a
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
  other table. Every markdown renderer spreads it. Code is `markdownCode`
  from the same file: one inline-code chip in every markdown surface, and
  fences in a `CodeFrame` (`surface` `answer` in a chat answer, `muted` in an
  artifact or preview; `SourceMarkdown` passes none and keeps its plain
  bordered `pre`; see Code blocks).
- **Mono**: ids, keys and code snippets are `font-mono text-xs`; code fields
  (textareas) follow the field size; code blocks are `ui/code-block` (see
  Code blocks). A preview of text a person or a model wrote (a trace's query
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
- **Truncation**: text the user or the server supplied (a name, title, path,
  URL, email, id or file name) that truncates or clamps carries its full
  value as `title`. Fixed UI labels don't, nor do clamps that expand in place
  or excerpts that open in full (a tile's description). The primitives do it
  for plain text: ListRow for a string title or description, CardTitle for a
  string child whose className truncates or clamps, BreadcrumbPage for a
  plain-text crumb; for a node, put `title` on the node. `title` is never a
  tooltip (see Tooltip).

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
collapsibles (`ui/collapsible` carries it), `duration-300 ease-in-out` on the named property for the shell
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
  with `ring-2` is enforced); the `ui/` components already carry it. So
  every interactive element in app code is a `ui/` component or `asChild`
  under one. A raw `<button>`, `<a>` or `<Link>` is only a stretched target
  (see A clickable card that holds a link), or it carries `focusRing` plus
  `outline-none`. Spell the ring with the `focusRing` constant from
  `lib/utils.ts` (with `invalidState` and `fieldFrame` for fields) rather
  than retyping it.
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
- **Close buttons**: every Modal and DialogContent uses its built-in close
  (a phone sheet has none; the scrim closes it), a `ghost-muted`
  `size="icon-sm"` Button (32px, accent square on hover) at `top-2 right-2`,
  labelled `t('close')`; a side panel's is the same Button in `PanelHeader`'s
  title row. Never hand-place another X.
- **Disabled**: buttons (Button, Tabs) use
  `disabled:pointer-events-none disabled:opacity-50`, so the pointer passes
  through, and so do targets that act like one: the Dropzone and the Command,
  menu and Select items (`data-[disabled]:pointer-events-none`). Fields
  (Input, SelectTrigger, Switch, Checkbox, Textarea, CommandInput, Label) use
  `disabled:cursor-not-allowed disabled:opacity-50` and never
  `pointer-events-none`, which would hide the cursor.
- **Elevation**: cards have no shadow; fields and outline buttons
  `shadow-xs`; popovers, menus and select lists `shadow-md`; sheets
  `shadow-lg`; modals (Modal and DialogContent) `shadow-modal`; toasts
  `shadow-toast`. The one exception in `ui/` is the Switch thumb, `bg-white
shadow-lg` in both themes: the knob is white on any track, and a white knob
  on a white card needs the lift to read as raised. The off track is
  `bg-input`. Outside `ui/` the only shadows are: the workflow
  canvas nodes (`shadow-md`, `hover:shadow-lg`: a node lifts off the canvas
  while you drag it); the workflow builder's publish-error panel, which
  floats over the canvas at popover elevation (`shadow-md`, `z-20`); the sliding panel in `navigation/SidebarLevel.tsx`,
  which casts a horizontal shadow while it slides; and the Hero model
  picker's menu (both Approved exceptions). Don't add new ones: a floating panel is a `Popover`,
  `DropdownMenu` or `Modal`, which carry their own shadow and stacking; never
  an `absolute` div with a shadow and a hand-picked `z-*`.
- **Stacking**: `z-10` sticky headers and table heads inside a page, a real
  control lifted over a stretched target (see A clickable card that holds a
  link) and a corner control pinned inside a card; `z-20` in-page floating
  chrome (banners, scroll-to-bottom, drag handles); `z-50` overlays, modals,
  sheets, toasts, the one-frame bar-tint strips and full-screen takeovers
  (the workflow builder's shell, the composer's drop overlay),
  where DOM order decides between them; `z-200` every portalled floating list (popover, menu,
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
| `agents/AgentsList.tsx`                                           | `shadcn/no-restyle`             | Inside a folder, the breadcrumb trail replaces the section `<h2>`, so its `BreadcrumbList` keeps heading typography (`text-foreground text-lg font-semibold gap-2`) and passes `flex-wrap` (the primitive is `flex-nowrap`). It's the only breadcrumb that does either.                                                                                                                                                                                                                                                                                        |
| `lib/markdown.tsx`                                                | `shadcn/no-inline-styles`       | SyntaxHighlighter's `style` prop is its Prism theme object (`oneLight` / `vscDarkPlus`), picked by theme at runtime. It is not CSS, so no class or custom property can replace it. One disable, in `markdownCode`, which every markdown fence goes through.                                                                                                                                                                                                                                    |
| `agents/workflow/WorkflowPreview.tsx`                             | `shadcn/no-restyle`             | The Preview minimap's node rows are status tiles: the fill, border and ring follow the step (success, primary running + pulse, destructive, muted pending; a ring on the active row) and stay pinned on hover, pending and running rows stay unfaded while disabled, and clickable rows dim to 80% on hover. No Button variant is status-tinted. The rule reports each string inside `cn(...)`, so it's a `/* eslint-disable */` … `/* eslint-enable */` pair around the `className` attribute. |
| `agents/schedules/ScheduleFormModal.tsx`                          | `shadcn/no-restyle`             | The schedule's name is the dialog's editable title: a `bare` Input with title type (`text-xl font-semibold`), so the dialog passes `hideTitle` (see Modal › Steps). One disable.                                                                                                                                                                                                                                                                                                                                    |
| `components/MermaidRenderer.tsx`                                  | `shadcn/no-restyle`             | The zoom − / + buttons sit on the diagram's `bg-black/70` overlay, where ghost's accent hover paints a light square with dark text; they hover to `white/20` with white text instead, in both themes. Two disables.                                                                                                                                                                                                                                                                             |
| `Hero.tsx`                                                        | `shadcn/no-restyle`             | The landing page's demo cards are `Button outline lg pill`, but each is a two-line pill (a title over a clamped 12px query), so it undoes lg's height, the base's one-row layout, weight and nowrap: `h-auto w-full flex-col items-start gap-0 py-3.5 text-left text-xs font-normal whitespace-normal`. Two disables: the demo cards and the connect card.                                                                                                                                                                            |
| `Navigation.tsx`, `conversation/ConversationTile.tsx`             | `shadcn/no-restyle`             | A sidebar row whose link has sibling buttons (an agent's pin, a conversation's menu and rename Save / Cancel) keeps its fill while the pointer is on a sibling or the menu is open (`group-hover:bg-sidebar-accent`, `bg-sidebar-accent`), and `pr-10` keeps the label clear of the buttons. ConversationTile's `cn(...)` needs a `/* eslint-disable */` … `/* eslint-enable */` pair.                                                                                                          |
| `admin/Usage.tsx`                                                 | `shadcn/no-restyle`             | The Top users id is a `link inline` Button inside a mono table cell; it keeps the cell's type and wraps (`font-mono text-xs font-normal whitespace-normal text-left`). One disable.                                                                                                                                                                                                                                                                                                             |
| `conversation/ConversationBubble.tsx`                             | `shadcn/no-restyle`             | A source card's URL row is a `link inline` around an `<a>`: foreground at rest, primary on hover, regular weight, truncating (`text-current font-normal hover:text-primary underline-offset-2 max-w-full justify-start`). One disable.                                                                                                                                                                                                                                                          |
| `admin/Overview.tsx`                                              | `shadcn/no-restyle`             | "View in Audit" under the denied-sign-ins tile keeps the tile's destructive tone at hint size (`text-destructive text-xs font-normal`). One disable.                                                                                                                                                                                                                                                                                                                                            |

Note that a multi-line reason has to be a `/* ... */` block comment;
consecutive `//` lines only disable the next comment line, not the code.

## Removed classes

`no-unknown-classes` is at `error`. Before deleting a class the lint calls
unknown, grep for it in `querySelector`, `classList` and `data-` lookups; a
class can be a hook for code rather than a style.

## Live style guide

`npm run dev`, then open `/design`. The page (`src/design/DesignSystem.tsx`)
is a shell: the nav and the list of sections. Each section lives in
`src/design/sections/<Name>Section.tsx`, built from `Section` and `Example`
in `src/design/shared.tsx`; app recipes (the toast stack, the connect modal,
populated side panels) are in `src/design/sections/recipes/`. It renders every
`ui/` component with the variants above, shows the resolved value of each
colour token and has a theme toggle. It is registered only when Vite runs in
development mode, so it never ships. The Button, Badge and Avatar matrices are
built from the exported cva keys (`buttonVariantNames`, `buttonSizeNames`,
`badgeVariantNames`, `avatarSizeNames`), so a new variant shows up there by
itself; any other new variant or token goes into its section file.

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
   component file, add it to its section in `src/design/sections/`, and document it
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
  agent layouts are Card mirrors with `Skeleton` bars, and the file table,
  logs, default and analysis layouts use `Skeleton`; none pulses its own
  surface.

## Working with the lint

```bash
cd frontend && npm run lint
```

All `shadcn/*` rules are `error`, and so are the DESIGN.md selectors under
`no-restricted-syntax`: `eslint/design-rules.js` (class and markup rules,
tested in `src/design/designRules.lint.test.ts`), `eslint/card-surfaces.js`
(tested in `src/design/cardSurfaces.lint.test.ts`) and the viewport-height
and focus-return entries in `eslint.config.js`. The `shadcn/no-restyle`
component contracts (what each `ui/` part allows in `className`, and their
messages) are tested against the real config in
`src/design/noRestyle.lint.test.ts`. Add a new checkable rule as
a selector there, with a test and a line here. Add a variant or token only when a treatment
is used in more than one place and none of the existing ones fits; a single
special case gets a disable comment with a reason.
