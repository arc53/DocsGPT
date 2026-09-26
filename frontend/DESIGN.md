# DocsGPT frontend design system

The UI is Tailwind v4 plus the shadcn-style components in
`src/components/ui/`. `@shadcn/lint` enforces the rules below through
`npm run lint`; its messages point here. Everything in this file is either a
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
Every user-visible string, attributes included (`aria-label`, IconButton
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
| `border`, `input`, `ring`               | dividers and field borders (fields use `border-border`), focus rings              | `border-gray-200/300`, `dark:border-gray-600/700`                   |
| `primary`, `primary-foreground`         | brand purple: primary actions, links, selected states                             | `bg-purple-*`, `text-purple-*`, `#7D54D1`, `#A076F6`                |
| `secondary`, `secondary-foreground`     | pressed and active toggles (a brand tint), secondary buttons, the question bubble | `bg-accent` on an active icon button                                |
| `destructive`, `destructive-foreground` | errors, failed states, dangerous actions                                          | `text-red-*`, `bg-red-50/100`, `#B42318`, `#E60000`                 |
| `success`, `success-foreground`         | completed, active, healthy                                                        | `text-green-*`, `text-emerald-*`, `bg-green-50/100`                 |
| `warning`, `warning-foreground`         | paused, pending review, degraded                                                  | `text-amber-*`, `text-yellow-*`, `text-orange-*`, `bg-amber-50/100` |
| `info`, `info-foreground`               | running, informational                                                            | `text-blue-*`, `bg-blue-50/100`                                     |
| `sidebar-*`                             | the navigation rail                                                               |                                                                     |
| `chart-1` to `chart-5`                  | data series only, never UI chrome (see below)                                     |                                                                     |
| `answer-bubble`                         | assistant message background                                                      |                                                                     |

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
`secondary` is never a chart colour.

The status set is `success | warning | destructive | info`. `default` is the
component's own base tone (brand on a Badge or Button, quiet on an Alert or
Toast). `neutral` is the grey pill or box.

One tint scale, by purpose:

- Wash `/5`: a whole surface that is selected or receiving a drop (Card
  `selected`, Dropzone drag-active and drag-reject). The border carries the
  state; the wash only warms the surface. Never on a chip or a text fill.
- Brand soft fill: `bg-secondary text-secondary-foreground` (Badge `default`,
  Avatar `primary`, the OptionCard icon square), never `bg-primary/10`.
- Status soft fill: `bg-<role>/10` in both themes (Badge, Alert, ToastHeader,
  a danger-zone panel); no `dark:` twin.
- Status border: `border-<role>/50`.
- Tinted hover on a row that is already accent: `/15` light, `/20` dark
  (`ghost-on-accent`, `ghost-destructive-on-accent`, a destructive menu item).
- Neutral hover: solid `bg-accent` in both themes (ghost buttons, combobox,
  SelectTrigger, Card `interactive`, Dropzone, every list-row highlight).
- Quiet panel inside a page or card: `bg-muted`, not `bg-muted/40` or `/60`.
- Dividers: `border-border`, not `border-border/60`.

Patterns:

- Status pill: `<Badge variant="success">`. Status box: `<Alert variant="warning">`.
  Reach for `bg-success/10 text-success` directly only on dots and borders.
- Solid status fill: `bg-warning text-warning-foreground`.
- Guardrail outcomes: block `destructive`, flag `warning`, redact `info`,
  not evaluated `neutral`.
- Status border: `border-destructive/50`.
- De-emphasised text: `text-muted-foreground`; go lighter with an opacity
  modifier (`text-muted-foreground/70`) rather than a lighter grey.
- Text on the brand colour is `text-primary-foreground`, not `text-white`.
- `secondary` is a brand tint, not a grey: primary at 10% (light) or 15%
  (dark) over whatever sits behind it, with `primary` text in light and a
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
| `shape`   | `default` (rounded-md), `pill` (rounded-full, wider padding)                                                                                                                                                                                           |

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
  exception is a tiny check mark inside a status circle (the custom-model
  test result, the artifact and research step ticks), drawn at 2.5 to 3 so
  it stays legible at 10 to 12px; raw progress-ring `<svg>`s are not icons.
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
  link.
- Icon-only buttons are `IconButton` (below), never a `Button` with a
  `title`.
- Roles for dangerous and dismissive actions: a delete on a page (a "Danger
  zone" card's Delete agent or Revoke, Delete all) is `destructive-outline`;
  the submit of a confirm dialog is `destructive` (`ModalActions destructive`,
  `ConfirmationModal variant="destructive"`); Cancel is `ghost` at the size and
  shape of the button beside it, in a modal footer, a form header or an inline
  editor. A Cancel inside a line of text (the composer's queued send) is
  `link inline`.
- The composer controls under the chat field (Attach, Voice, Tools,
  Sources) are `size="sm" shape="pill"`. Their icons are `size-3.5 sm:size-4`
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
  `combobox field pill`, its Add button `outline-primary field pill`.
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
- Underline tabs (FilePicker's My Files / Shared with Me, the agent page
  sub-nav) are `variant="tab"`: muted text on a transparent 2px bottom border,
  square corners, no hover fill. Mark the current tab with `data-active`, which
  gives it `foreground` text and a `primary` underline. Padding-free tabs (a
  sub-nav with `gap-6`) add `size="inline"`, which keeps 4px above the line;
  the row draws the 1px baseline, and `-mb-px` lays the underline over it.
  Use them for a row of route links (the agent sub-nav: a `<nav>` whose
  current link carries `aria-current="page"`). Tabs that switch a panel in
  place are `ui/tabs` with `variant="underline"` on `TabsList` and each
  `TabsTrigger`: the same pixels, plus `role="tablist"`/`"tab"`,
  `aria-selected` and arrow-key focus; wrap the panel in `TabsContent`
  (FilePicker's My Files / Shared with Me). The `default` variant is a pill
  tab, unused in the app.
- A section panel's disclosure header (NewAgent's Advanced and Guardrails
  panels) is `variant="section-toggle" size="sm"` with `-ml-3 w-fit
justify-start` and `aria-expanded`: a lucide `ChevronRight` first
  (`rotate-90` while open) in primary, then the foreground title, with a
  primary underline on hover. The button draws no focus ring; the panel does,
  so keyboard focus outlines the whole white block:
  `has-[[data-variant=section-toggle]:focus-visible]:ring-3 …:ring-ring/50
…:ring-inset` on the panel `<div>` (inset, because a scrolling column clips
  an outset ring). Status badges go beside the button, not inside it, or the
  hover underline runs under them.
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

| Prop          | Values                                                                                                                                                        |
| ------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `variant`     | `outline` (border + card surface, the default), `filled` (muted fill, no border, for tiles on a card-coloured page), `subtle` (border on the page background) |
| `tone`        | `default`, `destructive` (the status soft fill and border, `border-destructive/50 bg-destructive/10`, over any variant)                                       |
| `padding`     | `none`, `sm` (p-3, row boxes and code blocks), `default` (p-4), `lg` (p-6, tiles, chart panels and stat tiles)                                                |
| `interactive` | whole card is the target: hover, focus ring and `selected` highlight; pair with `asChild` around a `<button>` or `<Link>`                                     |

Parts: `CardHeader` (title left, `CardAction` top-right), `CardTitle`,
`CardDescription`, `CardContent`, `CardFooter` (meta row, sticks to the
bottom). One radius for every card (`rounded-2xl`); pass only layout and
`gap-*` on `Card`. Children are spaced by Card's `gap-3`, so they carry no
`mt-*`. Replaces every hand-rolled
`rounded-(md|lg|xl|2xl|3xl|4xl) border bg-(card|muted) p-*` box:

- Tiles (sources, tools, custom models, agents, folders) are `filled`, `lg`
  (a folder row `default`), `interactive` only when a click navigates (a
  draft agent is not). The Add tool picker tiles sit on the modal's card, so
  they are `outline interactive lg` with `asChild` around a `<button>`.
- Chart panels are `subtle lg` with fixed heights passed as layout; a chart
  panel inside a modal is `outline` (the modal is already `bg-card`).
- Row boxes inside a form or panel (a guardrail check, the schedule's
  timezone box, the discovered MCP tools) are `padding="sm"`.
- A danger zone (Delete agent, Revoke a device) and a failing stat are
  `tone="destructive"`; the title beside it is `SectionHeader
tone="destructive"`. Muted text fails AA on the red fill, so the tone turns
  every `text-muted-foreground` inside it to `foreground`; don't pass a
  lighter colour back. Icon buttons inside a destructive-tone row are
  `ghost-destructive-on-accent`, whose red tint shows on the fill where
  ghost's grey square would not.
- A card on the page background that must not look raised (the shared
  agent card) is `subtle lg`. Cards never take a shadow.

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
`<pre>` takes the recipe with no Card, so boxes don't nest. Put scroll caps
(`max-h-* overflow-y-auto`) on the Card; never `break-all`.

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
pill, including schedule and run status pills, trace chips and statuses,
token scope chips, "Disabled" and tool chips. A grey chip is `neutral`, never
a `bg-muted` pill. The admin role is `default` wherever it shows (Teams, Admin
→ Users); every other role is `neutral`. Chips that show code (token scopes) pass `font-mono`, and
stat chips `tabular-nums`, as approved exceptions. HTTP method pills take their variant from
`getMethodBadgeVariant` (`utils/httpMethodColors.ts`): GET `success`, POST
`info`, PUT `warning`, DELETE `destructive`, PATCH `default`, anything else
`neutral`. `MultiSelect` (`ui/multi-select.tsx`) shows its first two picks as
`default` Badges with a remove X, then "+N more", on a `Button
variant="combobox" size="field"` trigger that grows past 38px when the chips
wrap, with SelectTrigger's turning chevron; each row in its list shows a
`Checkbox size="sm"`.

### Input (`ui/input.tsx`)

| Prop      | Values                                                                               |
| --------- | ------------------------------------------------------------------------------------ |
| `size`    | `sm` (h-8), `default` (h-9.5, 38px), `lg` (h-12), `field` (h-9.5, the form-row name) |
| `shape`   | `default`, `pill`                                                                    |
| `variant` | `default`, `bare` (no border, padding, radius, shadow or ring), `filled` (card fill) |

Text alignment classes (`text-right`) and `font-mono` (code fields) are
allowed on Input and Textarea. `<Input label>` is the shorthand for a
one-field `FormField`: the same floating label on the border, the same
`labelSurface` (`card` default, forms in cards and modals; `background`,
fields straight on a page; `muted`, fields on a muted panel). Never pass a
background class for it. A placeholder under a floating label is an example:
it stays hidden while the label rests inside and shows on focus. The chat and hero
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
instead of showing the panel through; never pass `bg-card` for it.

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
never `bg-card`. Three raw `<textarea>` elements stay, because each sits
under an overlay it must line up with: the chat composer, PromptTextArea's
variable highlighter and the chunk editor behind its line-number gutter.

### FormField (`ui/form-field.tsx`)

Every boxed form control is labelled by a floating label:
`<FormField label required hint error disabled labelSurface>` with the field
as its only child. The label sits on the field's border (12px muted,
`labelSurface` `card` | `background` | `muted` to match the surface behind
the field, so the notch hides the line). It rests inside an empty, unfocused
`Input` or `Textarea` and moves up on focus; on a `SelectTrigger`, combobox,
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
(the chat composer, the chunk and wiki editors, editing a sent question) and
repeated rows in a list (workflow expressions) have no visible label and
must have an `aria-label`. Never hand-build a label above a field, a
hand-positioned floating label, or a `div.flex-col` + `Label` + `<p>` stack.

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

`<Checkbox checked onCheckedChange>` (Radix), never `<input type="checkbox">`:
native boxes take the OS accent and ignore dark mode. `size`: `default`
(16px, option rows), `sm` (14px, table cells). Unchecked it is an
`border-input` box; checked, `primary` with a `primary-foreground` check.
Name it with a `Label htmlFor` or `aria-label`. For an on/off setting with a
description use a Switch in a SettingRow instead.

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

### Separator (`ui/separator.tsx`)

A 1px `bg-border` rule, horizontal or `orientation="vertical"`, decorative
(`role="none"`) unless `decorative={false}`. Pass margins and width only.
Replaces every `<hr>` and every `border-b` or `h-px` div that is only a line.

### Spinner and Skeleton (`ui/spinner.tsx`, `ui/skeleton.tsx`)

`Spinner size="xs | sm | default | lg"` (16, 20, 28, 40px) draws in
`currentColor`, so colour it with a `text-*` token on it or its parent. `xs`
is the icon-sized step: a busy Button, a step's status in a Preview or
research row. Never shrink a larger size with `className="size-*"`, and don't
use lucide `LoaderCircle` (formerly `Loader2`) or a hand-drawn SVG as a loader. `Skeleton` is a pulsing
muted block sized with layout classes; its default radius (`rounded-sm`, 6px)
is the bar radius, so pass none (`rounded-full` for an avatar or switch
stand-in). Bars inside a muted surface (a `Card variant="filled"` tile) take
`surface="muted"` (`bg-muted-foreground/20`), since `bg-muted` would vanish
there. A tile's loading mirror is the same `Card` as the tile (variant,
padding, height) with Skeleton bars laid out like its content; the Card
itself never pulses, only the bars do. Never put a Skeleton inside an
element that pulses itself; the two animations multiply.

### LoadingState and EmptyState (`ui/loading-state.tsx`, `ui/empty-state.tsx`)

A page, panel or dialog that is still loading shows `LoadingState`, never a
hand-centred `Spinner`. `fill`: `parent` (`h-full`, needs a parent with a
height: the artifact panel, a drawer body), `screen` (`h-screen`, the app and
admin guards) or `block` (`py-10`, a page section or dialog body with no
height of its own). `label` puts a muted caption under the ring (a long job:
Convert to wiki, Enable GraphRAG); it is also the ring's name. Spinners
inside a control (a busy Button, a picker's `sm` ring) stay `Spinner`.

Nothing to show is `EmptyState`: `size` `default | sm | xs` (128 / 96 / 64px
art, page / panel / popover), `illustration` `no-files | none` (a "no
results" line is `size="xs" illustration="none"`), `title`, `description`
(plain `muted-foreground`), `action`. A page or panel whose fetch failed is
`EmptyState tone="destructive" illustration="none"` with a `Retry` action
(`t('retry')`): a red `CircleAlert`, a red title, `role="alert"`. Never a bare
`text-destructive` paragraph.

### Progress (`ui/progress.tsx`)

`value` 0 to 100, `variant`: `default`, `success`, `warning`,
`destructive`, `info`; `size`: `sm`, `default`, `lg`. Replaces the
width-percent divs in quota, indexing and guardrail views.

### Avatar (`ui/avatar.tsx`)

`size`: `none` (image decides, the default), `xs` (28px), `sm` (32px),
`default` (36px), `lg` (40px): Button's names at Button's heights;
`shape`: `none`, `circle`, `square`; `variant`: `default`, `primary` (brand
initials on `secondary`), `muted` (grey initials). Initials boxes pass the letters as
children.

### Dropzone (`ui/dropzone.tsx`)

`size`: `default` (tall target), `compact` (one row, for forms and modals).
Props: `onDrop`, `accept`, `multiple`, `maxFiles`, `maxSize`, `disabled`,
`title`, `description`, `icon`, `error`. Border and fill follow the drag
state through `data-drag-active` and `data-drag-reject` (the `/5` wash);
it hovers to solid `accent`. Every drop
target renders it, including `components/FileUpload.tsx` (which keeps its
preview and validation logic) and the Import agent / Import API
specification dialogs; don't hand-roll a `border-2 border-dashed` target
around `useDropzone`.

### Toast (`ui/toast.tsx`)

Feedback on anything the user did outside a modal (uploads, runs,
approvals, team events, a page action's result) is a toast in the
bottom-right stack; a result inside an open modal is an `Alert` there (see
"Where a message lives"), since the toast stack paints under the modal's
overlay. The app has one
`ToastViewport`, mounted in `App.tsx`; it is the live region
(`role="status"`, `aria-live="polite"`) and the fixed stack, so `Toast`
cards carry no role and no toast renders its own rail or positioning. Top
to bottom it holds `TeamNotificationToast`, `ToolApprovalToast`,
`UploadToast` and `ActionToast`, and it moves to the bottom-left while the
workflow Preview drawer is open. A new toast component returns only its
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
Sources adds its count and a right chevron, and opens the All sources sheet.

### Breadcrumb (`ui/breadcrumb.tsx`)

`BreadcrumbPage`, the current crumb, is always one line and truncates with
an ellipsis. Pages pass only its width (`w-[16ch]`, `max-w-[32ch]`) and a
`title` with the full text; never `truncate` or typography. Give every
current crumb a width cap so a long name cannot push the row past the
screen. A crumb that runs a handler instead of navigating is
`BreadcrumbLink asChild` around a `<button type="button">`; the link carries
the focus ring. The current crumb is never a disabled button. The path row above a
source's file tree and chunk viewer is `components/tree/PathHeader`
(back button, chevron crumbs, the last capped at `max-w-[32ch]`, actions on
the right); don't hand-roll a `/`-separated path.

### ListRow and DescriptionList (`ui/list-row.tsx`, `ui/description-list.tsx`)

An identity row (avatar or icon square, a truncating title, one muted meta
line, a trailing control) is `ListRow` inside `ListRows` (`divide-y
divide-border`, no box of its own; wrap it in `Card padding="none"` or a
bordered list for one). Rows are `px-4 py-3`, the title `text-sm
font-medium`. `interactive` (with `asChild` around a `<Link>` or `<button>`)
hovers to `bg-accent` and draws an inset focus ring. An icon square in
`leading` is a plain `bg-muted text-muted-foreground size-8 rounded-md` span.

Key/value rows are `DescriptionList` + `DescriptionItem`, never a hand-rolled
`flex` of label and value. `layout="columns"` (default) is an 8rem label
column beside the values (drawers, detail panels); `layout="justified"`
right-aligns the values (a phone card; `columns={2}` for a stats dialog).
`size` `sm | xs`; `mono` on an item for ids and URLs. Values wrap
(`break-words`), they never run past the column.

### Pagination (`ui/pagination.tsx`)

The pager under a table, tile grid or list: "Page N of M" and four chevron
`IconButton`s. `pageSize` adds the Rows per page select; `summary` puts a
count on the left ("1,024 users"). `labels="text"` swaps the chevrons for
Previous / Next buttons. Don't hand-roll a Previous / Next row.

### Page chrome: SectionShell, PageToolbar, SearchInput

Every section page (settings, admin, agents, teams) is wrapped in
`navigation/SectionShell` (`width` `default` 6xl, `wide` 7xl for admin,
`narrow` 5xl; `pills` for the phone destination pills); it draws the title and
starts the content 32px below it, so pages carry no root `mt-*`. The block
under the title is `components/PageToolbar`: `intro`, then the page `search`
(left, `max-w-md`) and the page `action` (right, `Button size="field"
shape="pill"`), then `divider` (a `Separator`). A page search is
`components/SearchInput`: the 38px pill with a search icon and a floating
`label`. The chunk viewer's and file tree's searches stay `CommandInput` in
their frame, because their results are `CommandItem`s.

### Grids

Two recipes, no component. Tiles (sources, tools, custom models, agents):
`grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4`; tiles
take the column width, never a fixed `w-[300px]`. Team cards stop at three
columns (`lg:grid-cols-3`): their header row holds an initial, the name, a
role badge and a chevron. Stat rows: `grid grid-cols-2 gap-4 md:grid-cols-4`
(five tiles: `md:grid-cols-3 lg:grid-cols-5`; a dialog: `grid-cols-3`). A
grid inside a Modal keeps its own column counts, because breakpoints follow
the window, not the dialog.
Skeleton mirrors follow the grid they stand in for.

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
(a form or a one-column list: Move to folder, Upload), `xl` 896 (a grid of
tiles or a wide editor: Add tool, Test retrieval, the prompt editor), `full`.
Never add a width or height class. The dialog caps itself at `85dvh` and
its body is the one scroller, so the header and footer stay put; don't cap
the body with `contentClassName`. `contentClassName="overflow-visible"`
(`!overflow-visible`) is only for a body whose popover must escape it (the
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
scroller) and the same blurred overlay. Modal, DialogContent and every Sheet share one scrim,
`overlayScrim` in `lib/utils.ts` (`bg-black/25 backdrop-blur-xs
dark:bg-black/50`).

Every phone bottom sheet has one shape: `bg-card`, 16px top corners, no top
border, at most 90% of the viewport, and bottom padding that clears the iPhone
home indicator. `SheetContent side="bottom"` gives it with `pb-safe-0` (the
bare inset); pass `handle` for the grab bar, which also hides the X (the handle and
the overlay dismiss it; pass `showCloseButton` to keep one).
`Modal mobileVariant="sheet"` shares the shape and the `SheetHandle`, with
`pb-safe` (the inset, at least 1rem) under its footer. `pb-safe` and
`pb-safe-0` are the `index.css` utilities for `env(safe-area-inset-bottom)`;
never spell `env()` in a class.

**Open question: side panel or right sheet for chat content.** Chat has two
ways to show something beside an answer. Notes, todos and files open in
`components/ArtifactSidebar`, a panel that takes a column and leaves the chat
usable. An answer's full source list opens in a right `Sheet`, which blurs
and blocks the chat, so the answer being checked is hidden while its sources
are read. No rule picks between them yet. The leading proposal is one
surface: content read alongside the chat (artifacts, sources, a cited
source) opens in the side panel, with citation chips opening it at that
source; overlays stay for tasks that interrupt (forms, confirmations,
pickers); phones keep the bottom sheet. Until that is decided, don't add a
third pattern: new "read beside the chat" content uses the side panel.

In a picker list, mark the item that is currently chosen with
`CommandItem checked` (a `secondary` brand tint through `data-checked`), not
with `bg-accent`: cmdk's own `data-selected` highlight is `bg-accent` and
follows the pointer and arrow keys, so an accent fill would look like hover.
While a checked item is also highlighted it keeps its tint and text and gains
a 1px inset `primary` ring, so the chosen row never turns plain grey.

### ActionMenu (`ui/dropdown-menu.tsx`)

The three-dots menu on a card, tile or row. Pass `options: MenuOption[]`
(`label`, `onClick`, optional lucide `icon`, `variant: 'destructive'`,
`disabled`) and a `triggerLabel`. It renders a `ghost-on-accent` `icon-xs`
trigger with `EllipsisVertical`, and stops clicks and keys on the trigger and
the menu from reaching the host, so it can sit inside a clickable card.
`className` takes layout only (position, margin) and lands on the trigger;
the menu is at least 144px wide and grows with its labels. `open`/`onOpenChange` make it controlled. Don't hand-build
this menu from `DropdownMenu`, and don't declare a local option type.

### Table, Label, dialog text

Every table is `ui/table`; never a raw `<table>` or a table utility class (the
chat's markdown tables are the one exception). The header row is dense by
default (`px-2 py-1 text-sm font-normal text-foreground`, 28px, on
`TableHead`'s sticky `bg-muted` strip). A `TableRow` hovers (`bg-accent`,
pointer) only when it has an `onClick`; a read-only row does not. Use
`TableContainer` for the bordered, scrolling frame; a table that already sits
in a frame renders `Table` alone. `Table` keeps a 600px minimum so wide
tables scroll sideways; a narrow one inside a panel passes
`minWidth="min-w-0"`. A fixed icon column is `width="50px" align="center"`.
`TableCell` and `TableHeader` accept typography and alignment classes and
`text-muted-foreground` (RunLog's headers pass the eyebrow). `Label`, `DialogTitle`, `DialogDescription`,
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

### Typography roles

- **Page title**: `SectionPageHeader` (24px bold); the only other text at
  that size is a stat figure (`StatCard`).
- **Title** of a dialog, sheet, drawer header or detail page: `text-xl
leading-tight font-semibold`. `DialogTitle` and `SheetTitle` default to it;
  `font-bold` is never a title weight. A picker popover's header is a
  sub-heading, not a title.
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
  don't declare a local heading map.
- **Mono**: ids, keys and code snippets are `font-mono text-xs`; code fields
  (textareas) follow the field size; code blocks follow the Card recipe
  (see Card). A preview of text a person or a model wrote (a trace's query
  or output) stays proportional at the same size; only what the app
  serialised (arguments, results, attributes) is mono. Every stat figure is
  `tabular-nums`.

### Rhythm

32px between the page title and the content (`SectionShell`); 24px (`gap-6`)
between sections inside a panel or drawer; 20px (`gap-5`) between floating
fields; 8px (`gap-2`) in a button row, 12px (`gap-3`) in a modal footer. A
two-up field grid is `grid grid-cols-1 gap-x-4 gap-y-5 sm:grid-cols-2`. Stack
with `flex flex-col gap-*`, not `space-y-*` (a child's own margin adds to a
gap, so drop it).

### Radius by role

`rounded-xs` 2px, `rounded-sm` 6px, `rounded-md` 8px, `rounded-lg` 10px,
`rounded-xl` 14px, `rounded-2xl` 18px (from `--radius`); bare `rounded` is a
fixed 4px, so don't use it. Skeleton bars: the default. Tinted icon squares:
`rounded-md` at `size-7|8`, `rounded-xl` at `size-12|14`, `rounded-2xl` at
`size-20`. `rounded-full` only for avatars, status dots and the workflow
palette pills.

## Motion

Transition only the property that changes: `transition-colors` by default,
`transition-transform duration-200` for chevrons,
`transition-[grid-template-rows,opacity] duration-300 ease-out` for
collapsibles, `duration-300 ease-in-out` on the named property for the shell
(sidebar, main column, top buttons); a shadow or ring change is
`transition-shadow`, several at once a bare `transition`. No `transition-all`
(the floating labels in `form-field.tsx` and `input.tsx`, which move and
resize, are the exception) and no `hover:scale`: hover is a fill, border or
text-colour change.

New entrances are `animate-in fade-in duration-200 motion-reduce:animate-none`
(`SectionRail`). Two chat timings are decided exceptions: the disclosure fade
`animate-in fade-in duration-160 ease-out` and the answer bubble `animate-in
fade-in slide-in-from-bottom-1.5 duration-260 ease-out`, both with
`motion-reduce:animate-none`. `ui/` overlays keep their own enter and exit.

## Breakpoints

Phone / desktop is `lg` (1024px) in classes and `isDesktop` in JS
(`useMediaQuery`); `sm` and `md` only reflow content. Wide two-column layouts
that need more room (Analytics' chart rows, the agent form beside its preview)
go two-up at `xl`. No custom breakpoints (`min-[…]`, `max-[…]`,
`[@media(…)]`). The workflow builder needs `lg`; below it `MobileBlocker`
shows.

## Focus, elevation and stacking

- **Focus ring**: `focus-visible:ring-3 focus-visible:ring-ring/50` plus
  `focus-visible:border-ring` on fields. Never `focus:` (mouse users see it)
  and never `ring-2` or `ring-[3px]`; the `ui/` components already carry it,
  so plain elements should become components rather than copy the classes.
  Inside `ui/`, spell it with the `focusRing` constant from `lib/utils.ts`
  (with `invalidState` and `fieldFrame` for fields) rather than retyping it.
- **Close buttons** on Modal, Sheet and DialogContent are a `ghost-muted`
  `size="icon-sm"` Button (32px, accent square on hover) at `top-2 right-2`.
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
  while you drag it); the workflow builder's node-settings panel and its
  publish-error panel, which float over the canvas at popover elevation
  (`shadow-md`, `z-20`); the chunk viewer's and file tree's search result
  lists (`shadow-md`, in-page `z-20`, their results are `CommandItem`s inside
  the search frame); and the Hero model picker's menu (an Approved
  exception). Don't add new ones: a floating panel is a `Popover`,
  `DropdownMenu` or `Modal`, which carry their own shadow and stacking; never
  an `absolute` div with a shadow and a hand-picked `z-*`.
- **Stacking**: `z-10` sticky headers and table heads inside a page;
  `z-20` in-page floating chrome (banners, scroll-to-bottom, drag
  handles); `z-50` overlays, modals, sheets and toasts; `z-200` every
  portalled floating list (popover, menu, select, tooltip), so it opens above
  a Modal without an override. Do not invent values in between.

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

| Where                                                               | Rule                            | Why                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| ------------------------------------------------------------------- | ------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `components/Notification.tsx`                                       | `shadcn/no-restyle`             | The promo banner's close X (`ghost icon-xs`) sits on the purple gradient. Any fill would be a grey square on it, so hover dims the icon instead (`hover:bg-transparent hover:opacity-70`, plus `dark:hover:bg-transparent` to beat ghost's dark hover), and `text-primary-foreground` keeps it white, because the button inherits the page colour. One user, so it isn't a variant.                                                                                                             |
| `components/ui/calendar.tsx`                                        | `shadcn/require-static-classes` | The day button merges `defaultClassNames.day`, which react-day-picker returns from `getDefaultClassNames()` at runtime; no static form exists.                                                                                                                                                                                                                                                                                                                                                  |
| `navigation/SidebarLevel.tsx`                                       | `shadcn/no-arbitrary-values`    | The incoming sidebar panel casts a strong shadow off its left edge while it slides (`shadow-[-12px_0_24px_-6px_rgba(0,0,0,0.45)]`); no scale shadow is horizontal, and the container clips it once the panel comes to rest.                                                                                                                                                                                                                                                                     |
| `components/MessageInput.tsx`                                       | `shadcn/no-restyle`             | The empty composer's send button is a grey circle (`bg-muted`, `dark:bg-accent`), not a faded brand one; no variant is neutral while disabled, and `secondary` is the brand-tinted pressed state.                                                                                                                                                                                                                                                                                               |
| `Hero.tsx`                                                          | `shadcn/no-restyle`             | The landing page's model picker keeps its hero look: a borderless muted pill at 16px (`rounded-4xl px-6 py-4 text-base`) whose menu hangs from it as one shape. Three disables: `SelectTrigger`, `SelectContent`, `SelectItem`.                                                                                                                                                                                                                                                                 |
| `agents/AgentsList.tsx`                                             | `shadcn/no-restyle`             | Inside a folder, the breadcrumb trail replaces the section `<h2>`, so its `BreadcrumbList` keeps heading typography (`text-foreground text-lg font-semibold gap-2`). It's the only breadcrumb that does.                                                                                                                                                                                                                                                                                        |
| `conversation/MarkdownAnswer.tsx`, `components/ArtifactSidebar.tsx` | `shadcn/no-inline-styles`       | SyntaxHighlighter's `style` prop is its Prism theme object (`oneLight` / `vscDarkPlus`), picked by theme at runtime. It is not CSS, so no class or custom property can replace it. One disable per file.                                                                                                                                                                                                                                                                                        |
| `agents/workflow/WorkflowPreview.tsx`                               | `shadcn/no-restyle`             | The Preview minimap's node rows are status tiles: the fill, border and ring follow the step (success, primary running + pulse, destructive, muted pending; a ring on the active row) and stay pinned on hover, pending and running rows stay unfaded while disabled, and clickable rows dim to 80% on hover. No Button variant is status-tinted. The rule reports each string inside `cn(...)`, so it's a `/* eslint-disable */` … `/* eslint-enable */` pair around the `className` attribute. |
| `agents/schedules/ScheduleFormModal.tsx`                            | `shadcn/no-restyle`             | The schedule's name is the dialog's editable title: a `bare` Input with title type (`text-xl font-semibold`), so the dialog passes `hideTitle`. One disable.                                                                                                                                                                                                                                                                                                                                    |
| `components/MermaidRenderer.tsx`                                    | `shadcn/no-restyle`             | The zoom − / + buttons sit on the diagram's `bg-black/70` overlay, where ghost's accent hover paints a light square with dark text; they hover to `white/20` with white text instead, in both themes. Two disables.                                                                                                                                                                                                                                                                             |
| `Hero.tsx`                                                          | `shadcn/no-restyle`             | The landing page's demo cards are `Button outline lg pill`, but each is a two-line pill (a title over a clamped 12px query), so it undoes lg's height, the base's one-row layout, weight and nowrap: `h-auto w-full flex-col items-start gap-0 py-3.5 text-left text-xs font-normal whitespace-normal`. One disable (phase 7, 36a).                                                                                                                                                             |
| `Navigation.tsx`, `conversation/ConversationTile.tsx`               | `shadcn/no-restyle`             | A sidebar row whose link has sibling buttons (an agent's pin, a conversation's menu and rename Save / Cancel) keeps its fill while the pointer is on a sibling or the menu is open (`group-hover:bg-sidebar-accent`, `bg-sidebar-accent`), and `pr-10` keeps the label clear of the buttons. ConversationTile's `cn(...)` needs a `/* eslint-disable */` … `/* eslint-enable */` pair.                                                                                                          |
| `admin/Usage.tsx`                                                   | `shadcn/no-restyle`             | The Top users id is a `link inline` Button inside a mono table cell; it keeps the cell's type and wraps (`font-mono text-xs font-normal whitespace-normal text-left`). One disable.                                                                                                                                                                                                                                                                                                             |
| `agents/workflow/WorkflowBuilder.tsx`                               | `shadcn/no-restyle`             | The "Learn more" links in the Set state and Condition nodes' 12px hints keep the sentence's size and weight (`text-xs font-normal` on `link inline`). Two disables.                                                                                                                                                                                                                                                                                                                             |
| `components/MessageInput.tsx`                                       | `shadcn/no-restyle`             | The queued-send Cancel is a `link inline` inside the composer's 12px status line, so it takes the line's size (`text-xs`). One disable, beside the send button's.                                                                                                                                                                                                                                                                                                                               |
| `settings/PersonalAccessTokens.tsx`                                 | `shadcn/no-restyle`             | Token scope chips are identifiers, so the `neutral` Badge is set in mono (`font-mono`). One disable.                                                                                                                                                                                                                                                                                                                                                                                            |
| `settings/traces/TraceChips.tsx`                                    | `shadcn/no-restyle`             | Trace stat chips (durations, counts) use tabular figures so they don't jitter between rows (`tabular-nums` on Badge). One disable.                                                                                                                                                                                                                                                                                                                                                              |
| `modals/MCPServerModal.tsx`                                         | `shadcn/no-restyle`             | The authorization link inside the test-result Alert keeps the Alert's status colour (`text-current` on `link inline`). One disable (phase 11, 63g).                                                                                                                                                                                                                                                                                                                                             |
| `components/MermaidRenderer.tsx`                                    | `shadcn/no-restyle`             | The zoom readout between − and + is a `link inline` Button on the `bg-black/70` overlay; it keeps the overlay's white 12px regular text (`text-xs font-normal text-current`). One disable, beside the two zoom-button ones above (phase 11, 63g).                                                                                                                                                                                                                                               |
| `conversation/SharedConversation.tsx`                               | `shadcn/no-restyle`             | The "DocsGPT" link sits in the `/share/:id` page's regular-weight byline (`font-normal`). One disable (phase 11, 63g).                                                                                                                                                                                                                                                                                                                                                                          |
| `conversation/ConversationBubble.tsx`                               | `shadcn/no-restyle`             | A source card's URL row is a `link inline` around an `<a>`: foreground at rest, primary on hover, regular weight, truncating (`text-current font-normal hover:text-primary underline-offset-2 max-w-full justify-start`). One disable (phase 11, 63g).                                                                                                                                                                                                                                          |
| `admin/Overview.tsx`                                                | `shadcn/no-restyle`             | "View in Audit" under the denied-sign-ins tile keeps the tile's destructive tone at hint size (`text-destructive text-xs font-normal`). One disable (phase 11, 63g).                                                                                                                                                                                                                                                                                                                            |
| `settings/PairDeviceModal.tsx`                                      | `shadcn/no-restyle`             | The install link in Pair a remote machine sits in a 12px hint (`text-xs font-normal`, `self-start` in its column). One disable (phase 11, 63g).                                                                                                                                                                                                                                                                                                                                                 |
| `agents/workflow/WorkflowBuilder.tsx`                               | `shadcn/no-restyle`             | The publish-error Alert floats over the canvas with its close button in the top-right corner, so it pads `pr-10` to keep a long title clear of the button. One disable.                                                                                                                                                                                                                                                                                                                         |

Note that a multi-line reason has to be a `/* ... */` block comment;
consecutive `//` lines only disable the next comment line, not the code.

## Removed classes

The lint reports classes Tailwind cannot generate; `no-unknown-classes` is at
`error`, so none remain. For the record, they were bugs, not missing
configuration:

- `xs:` has never been a breakpoint here (not in the old Tailwind v3 config
  either), so `xs:px-3`, `xs:text-xs` never applied. Remove them rather than
  declaring the breakpoint, which would change layouts that were never seen.
- `text-s`, `dark:text-gray`, `w-inherit` are typos for `text-sm`,
  `dark:text-gray-*` and `w-[inherit]`.
- `agents-container`, `conversations-container`, `loader` and `mermaid` are
  unused hooks; nothing selects them. Before deleting a class like these,
  grep for it in `querySelector` and `classList` calls too. `star` was
  defined at runtime by a `<style>` element in `components/Notification.tsx`;
  it is now the `notification-star` utility in `src/index.css`. `msc-spacer`
  was a lookup hook for `ConversationMessages`' `querySelector`; the lookup
  now uses the primitive's `[data-message-scroller-spacer]` attribute.

## Live style guide

`npm run dev`, then open `/design`. The page (`src/design/DesignSystem.tsx`)
renders every `ui/` component with the variants above, shows the resolved
value of each colour token and has a theme toggle. It is registered only
when Vite runs in development mode, so it never ships. When you add a
variant or token, add it there too.

## Cleanup playbook

Every `shadcn/*` rule is at `error`, and `lint-staged` runs the lint on
staged files, so a violation blocks the commit. Work one file at a time and
keep every step green.

1. **See the state.** `npm run lint:design` prints warnings by rule and the
   worst files. `npm run lint:design -- --file src/settings/Teams.tsx` lists
   every warning in one file with the fix the message proposes;
   `-- --rule no-raw-colors` lists files for one rule.
2. **Pick a file, read it whole**, then fix all of its design warnings in
   one pass. Map raw colours to tokens (table above), replace hand-rolled
   boxes, pills, tiles, spinners and dropzones with the `ui/` components,
   and move Button/Input/Select overrides onto `variant`, `size`, `shape`.
   Delete the `dark:` twin of every class you tokenise. Remove classes the
   lint calls unknown (`xs:*`, `text-s`, `dark:text-gray`, unused hooks).
3. **Do not restyle `ui/` components from a page.** If a treatment is used
   in more than one place and no variant fits, add the variant in the
   component file, add it to `src/design/DesignSystem.tsx`, and document it
   here. A one-off gets `// eslint-disable-next-line shadcn/<rule> -- reason`.
4. **Keep behaviour identical.** Same DOM order, same handlers, same
   translations (`t(...)` keys stay). Only classes and component choice
   change. Prettier with the Tailwind plugin reorders classes; run
   `npm run lint-fix` rather than fighting it.
5. **Verify per file**: `npx eslint <file>` (zero `shadcn/*` warnings),
   `npx tsc --noEmit -p tsconfig.json`, `npm test`, and look at the screen
   in the running app (`npm run dev`, then the page that renders the file)
   in both themes.

Known traps:

- `npm run lint` also reports 6 pre-existing Prettier errors (union-type
  line breaks in `cronBuilder.ts`, `types/schedule.ts`, `types/workflow.ts`,
  `api/client.ts`, `models/misc.ts`, `models/types.ts`) and about 330
  TypeScript warnings unrelated to design; `npm run lint-fix` clears the
  Prettier ones.
- Port 5173 may be held by another checkout; check the Vite banner shows
  this repo's path before trusting what you see.
- `components/SkeletonLoader.tsx` renders `Skeleton` in its table, logs,
  default and files layouts and its four tile mirrors (Card + bars). Its
  analysis, dropdown, chunk-card and connected-state layouts still pulse their
  own surface; move them onto Card + `Skeleton` the same way when you touch
  them. (`agents/schedules/StatusBadge.tsx` is a status→variant map over
  `Badge`, not a wrapper; keep it.)

## Working with the lint

```bash
cd frontend && npm run lint
```

All `shadcn/*` rules are `error`. Add a variant or token only when a treatment
is used in more than one place and none of the existing ones fits; a single
special case gets a disable comment with a reason.
