# Style audit: cutting exceptions and unifying the system

_2026-09-30. Scope: `frontend/src`, `frontend/DESIGN.md` (1,967 lines), the `/design` gallery
(`src/design/DesignSystem.tsx`, 3,294 lines) and the design lint. Counts exclude the gallery and
tests; Button/Card/Badge counts come from a TypeScript-AST scan, not grep._

## Summary

The system is structurally healthy — colours are fully tokenised (no raw hex or palette classes
left outside `ui/`), the lint is respected (no rule is disabled anywhere), and almost all
arbitrary values are legal layout sizing. The growth is coming from four places:

1. **Exception rows that are really missing variants.** 35 eslint disables; ~20 of them are three
   repeating patterns. Three small component changes delete them.
2. **Variants nobody uses.** ~14 variant/size values have 0–2 call sites; several exist only in
   the gallery.
3. **Choices left to the call site that should be baked into the component** — shape (pill vs
   square), the ToggleGroup track, tabs' `variant="underline"`, breadcrumb truncation widths.
   These are where the app actually drifted.
4. **DESIGN.md doubling as a per-page app spec.** Roughly 700–800 of its lines describe pages
   (Source views, Connectors, Workflow builder, chrome), not the system.

Net effect of everything below: disables 35 → ~12, the Approved-exceptions table 28 → ~8 rows,
~14 variant values deleted, one shape decision instead of ~60 per-call-site ones, DESIGN.md at
roughly half its length.

---

## 1. Colour tokens: the sidebar block is mostly dead weight

You're right. The `sidebar-*` block is the stock shadcn set imported wholesale — 8 tokens, but:

| token | light | dark | app uses (excl. gallery) |
|---|---|---|---|
| `sidebar` | `#fbfbfb` (≈ background `#ffffff`) | `#161616` (real) | few (`bg-sidebar` rail) |
| `sidebar-accent` | `#ececec` **= accent** | `#222327` **= background** | **18** |
| `sidebar-border` | `#d9d9d9` **= border** | `#2b2c31` **= card** | 1 line (`Navigation.tsx:578`) |
| `sidebar-foreground` | = foreground | = foreground | 0 |
| `sidebar-primary` | = primary | `#976af3` = ring | 0 |
| `sidebar-primary-foreground` | = primary-foreground | = primary-foreground | 0 |
| `sidebar-accent-foreground` | = accent-foreground | = foreground | 0 |
| `sidebar-ring` | = ring | = ring | 0 |

In light mode 7 of 8 are byte-identical to base tokens; five are used **nowhere** in app code.

Beyond the sidebar, three more duplicate pairs:

- **`popover` = `card`** in both themes (`#ffffff` / `#2b2c31`). 8 class uses.
- **`input` = `border`** in both themes (`#d9d9d9` / `#44454c`).
- **`answer-bubble` = `muted` in light** (`#f6f6f6`); dark is `#2e303e` vs muted `#35363b` — a
  faint blue shift. 6 uses.

**Suggestions**

- Delete `sidebar-foreground`, `sidebar-primary`, `sidebar-primary-foreground`,
  `sidebar-accent-foreground`, `sidebar-ring` (zero app uses; remove their gallery swatches and
  the `@theme` lines). Keep `sidebar` and `sidebar-accent` — those carry the real design (the
  darker rail in dark mode). `sidebar-border` has one call site; either keep it or accept the
  slightly stronger `border` there and delete it too.
- Define the duplicates as aliases so the palette is honest about its size:
  `--popover: var(--card)`, `--input: var(--border)`, and the `*-foreground` twins
  (`card-foreground`, `popover-foreground`, `accent-foreground`) as `var(--foreground)`. Zero
  visual change; the token *names* stay for shadcn compatibility, but a theme edit now touches
  one value instead of four.
- Decide `answer-bubble`: if the blue-ish dark tint is intentional, keep it (it's then the only
  reason the token exists); if not, fold it into `muted` and delete.

End state: ~14 independent colour values per theme instead of ~40 declarations, with the
DESIGN.md table shrinking to match.

## 2. Buttons: 16 variants → 12, 10 sizes → 9

Measured usage (app call sites; Button + IconButton):

| healthy | count | | cut candidates | count |
|---|---|---|---|---|
| outline | 89 | | **`tab`** | 2, one file (`AgentPageHeader`) → fold into `ui/tabs` (see §6) |
| sm | 118 | | **`section-toggle`** | 2 → wrap the whole h2/chevron/span recipe in a tiny `SectionToggle` component; the variant becomes internal and ~15 doc lines become one |
| ghost-muted | 46+ | | **`ghost-destructive-on-accent`** | 2 → keep `ghost-destructive`; the two rows take a one-line disable, or keep if you'd rather not trade a variant for two disables |
| link | 48 | | **`icon-lg`** | 1 (`ConversationBubble.tsx:221`) → delete, size the one icon locally |
| ghost | 41 | | `destructive` | 0 in JSX — **but keep**: ~20 confirm dialogs reach it via `ModalActions destructive` |
| inline | 32 | | | |

The higher-value change than deleting variants: **make `link size="inline"` inherit its
context's font size, weight and colour.** 13 of the 31 `no-restyle` disables exist only to add
`text-xs font-normal` (links inside 12px hints) or `text-current` (links inside status Alerts /
dark overlays). One contract change deletes ~13 disables and ~10 Approved-exceptions rows. Two
smaller siblings: allow `font-mono` / `tabular-nums` on Badge (3 disables) and give Alert an
`onClose` slot (2 disables, the two floating canvas notices).

## 3. Shapes: the rule exists on paper, reality drifted ~40 call sites away

DESIGN.md's implicit rule — page-level chrome and chat are pills, in-form/in-modal controls are
square — is real, but it's enforced per call site, and it slid:

- **Inputs**: 63 square vs 31 pill. The same field disagrees with itself: the folder-name input
  is pill in `MoveToFolderModal.tsx:206` and square in `FolderManagementModal.tsx:77` and
  `AgentsList.tsx:533` (sitting next to pill buttons). `NewAgent`'s form fields are pill; the
  workflow `AgentPanel`'s equivalent fields are square.
- **The two searches you noticed**: page/list searches are 38px pills (`SearchInput`,
  `SourceNavigator`'s `CommandInput variant="field"`), while popover searches (`CommandInput`
  default) are square h-9 underline strips — that part is a deliberate cmdk convention and fine.
  The genuine outliers: `MultiSelectPopover.tsx:178` overrides its strip to 40px with its own
  padding (used by NewAgent's Sources/Tools pickers and the chat composer pickers), and
  `settings/Teams` + `admin/Quotas` use the 32px `sm` search while every other page uses 38px.
- **Buttons**: Retry after a failed load is `outline sm pill` per the spec at ~16 sites and
  square at 10 (`AdminUI`, `GuardrailEvents`, `RunLog`, `ArtifactPanel`, `TraceSheet`…). "New
  team" is pill at `Teams.tsx:846` and square at `:876` — same label, same file. Edit/Save/
  destructive actions and nearly all admin pages are square where equivalent settings pages are
  pill.
- **Selects**: `field` size splits 21 square / 16 pill; `ToolConfig.tsx` mixes both.

**Suggestion: take the shape decision away from call sites.** Concretely:

1. `SearchInput` already forces pill — good. Standardise its size (38px everywhere; make Teams/
   Quotas follow), and make `MultiSelectPopover`'s search a stock `CommandInput`.
2. Make the pill contexts structural: `PageToolbar`'s action slot, `ModalActions`, and
   `EmptyState`'s Retry render their own Buttons — bake `shape="pill"` in there and delete it
   from call sites.
3. Then pick one shape for form controls (square is the majority: 63 vs 31 Inputs, 29 vs 17
   Selects) and migrate the pill forms (`NewAgent`, `GuardrailsSection`, `ToolConfig`'s two,
   `TestRetrievalModal`, `MoveToFolderModal`, `WorkflowDetailsSheet`). After that, `shape` on
   Input/Select can go entirely (SearchInput keeps pill internally), and Button keeps it only
   for chat/page chrome.

This is the single biggest "cut on exceptions" win in the app: one rule, mechanically checkable,
instead of ~60 per-call-site choices, ~40 of which currently disagree with each other.

## 4. Segmented controls: two sanctioned looks + two stragglers → one

The documented rule actually holds perfectly — all 11 `xs` ToggleGroups sit in the muted track,
all 8 `sm` ones are bare. But that's still **two looks for one concept**, chosen by size, and
`ScheduleFormModal` shows both within one form (tracked frequency picker at `:334`, bare weekday
picker at `:402`). Around them:

- `SectionPills` (route links, `AgentsList` below lg) looks exactly like a bare `sm` group.
- Chip toggles (`secondary` on / `ghost-muted` off): pill at `GuardrailsSection` and
  `CustomModelModal`, **square** at `MermaidRenderer.tsx:301` — the one true straggler.

**Suggestion**: move the track *into* ToggleGroup (both sizes render it; delete the wrapper divs
at 11 sites) so there is one segmented-control look, and the xs/sm choice is only density. The
8 bare `sm` groups (admin ranges, ConnectWizard auth, weekdays) get the track — a visual change,
but it unifies rather than redesigns. Fix Mermaid's square chip to pill. `SectionPills` stays as
is (they're links, and the doc already separates them).

## 5. Selects: 6 living combos → 2

Current reality across 53 app call sites:

| combo | count | verdict |
|---|---|---|
| field / default / square | 21 | keep (the form select) |
| field / default / pill | 16 | migrate per §3 |
| sm / default / square | 8 | keep (tables, dense rows) |
| sm / default / pill | 1 | migrate |
| **default (h-9) / square** | 7 | **delete the size** — it sits 2px off the 38px form row; `PairDeviceModal:166` and `ImportAgentModal:384` are literally form fields beside `field` neighbours. Migrate these 7 (+ `time-picker`'s two internal triggers) to `field` |
| **ghost variant** | **0** | **delete** (gallery-only) |

End state: `SelectTrigger` = two sizes (`sm`, `field`), one variant, no shape prop. Same story
for `Button variant="combobox"` (5 pill-field vs 4 square-h-9 today) and `MultiSelect`, which
has no shape prop at all — `admin/Activity.tsx:266-289` currently puts a pill search, two square
MultiSelects and a bare 32px ToggleGroup in one toolbar; after §3–§5 that toolbar unifies by
construction. Hero's restyled select stays the documented exception.

## 6. Tabs: three implementations, one needed

- `ui/tabs` `variant="underline"`: 4 call sites, each repeating `variant="underline"` on the
  list **and every trigger**.
- `ui/tabs` `variant="default"` (pill): **0 app uses.**
- `Button variant="tab"`: 2 uses in one file (`AgentPageHeader`, the workflow-builder toolbar),
  admittedly "the same pixels" as underline tabs.

**Suggestion**: delete the pill variant, make underline the default (the `variant` prop goes;
4 sites get shorter), and rebuild `AgentPageHeader`'s row on the tabs primitives (or a small
`NavTabs` wrapper around them) so `Button variant="tab"` is deleted along with its long
DESIGN.md passage. One tab treatment, defined once.

## 7. Accordion and breadcrumb: converge or delete

**Accordion** has 2 call sites, and both hand-build slightly different frames
(`RemoteDeviceConfig.tsx:339` lacks `overflow-hidden`; `ConnectWizard.tsx:883` double-pads its
content). Meanwhile the app has **~8 disclosure mechanisms**: Accordion, a raw `<details>`
(`TraceSpanDetails`), `section-toggle` (2), the `link` + chevron disclosure (9 sites), the
animated `grid-rows-[0fr]/[1fr]` collapse (5 sites), hand-rolled `div role="button"` headers
(`ToolConfig` ×2, `Logs`), icon-button row expanders (3), and tree expanders.

**Suggestion**: settle on three — (a) the `link`/`SectionToggle` disclosure for forms and
panels, (b) one `Collapsible` helper that owns the `grid-rows` animation (also retires 6 of the
arbitrary-value classes), (c) row/tree expanders as they are. Convert Accordion's two call sites
to (a) or (b) and delete `ui/accordion`; move `ToolConfig`'s and `Logs`' hand-rolled headers
onto the same helper.

**Breadcrumb** is one primitive with six treatments and no shared truncation policy.
`AgentPageHeader` alone uses four widths — `max-w-[24ch]`, a **fixed** `w-[16ch]`,
`max-w-[40ch]`, uncapped — and `AgentsList`'s trail is the only one that wraps and the only one
with heading typography (a documented exception). `PathHeader` and `DetailBreadcrumb` cap
parents at 16ch; the other four don't cap middle crumbs at all.

**Suggestion**: bake the policy into `ui/breadcrumb` — `BreadcrumbPage` defaults to
`max-w-[32ch]` + `title`, parent crumbs to `max-w-[16ch] truncate`, list to `flex-nowrap` — and
strip the per-page width classes. Fix `AgentPageHeader`'s fixed `w-[16ch]` (a short name gets
padded to 16ch today) and give its four states one width. Keep `AgentsList` as the one listed
exception. That also deletes most of the doc's Breadcrumb section.

## 8. Modals and sheets: prune the dead surface

- **Modal `size="full"`: 0 uses — delete.** Five call sites pass `size="md"` explicitly (the
  default) — drop. Remaining sizes all earn their keep (sm 5, md 16, lg 19, xl 3).
- **`mobileVariant` is a per-call choice that drifted**: 18 sheet vs 25 modal, with lg form
  modals split arbitrarily (`ConnectWizard` is a sheet on phones; `ImportAgentModal`,
  `ShareConversationModal`, `Upload` are not). Suggestion: default by size — `lg`/`xl` become
  sheets below `lg`, `sm`/`md` stay dialogs — and delete the prop from call sites (keep an
  escape hatch if some md modal truly needs a sheet). One decision instead of 43.
- **`ui/sheet`**: one direct app use (`MultiSelectPopover`, bottom). `side="left"`, `side="top"`,
  `SheetHeader`, `SheetFooter`, `SheetDescription`, `SheetClose` and `closeLabel` are unused —
  prune them; the component becomes an internal helper for SidePanel and Modal plus one picker.
- **`SidePanel`**: docked+`wide` is dead (`DOCKED_SIZE.wide` / `DOCKED_HALF.wide` unreachable),
  and `expandable` on a modal panel is accepted but ignored — tighten the types so the props
  can't be combined.
- `ConfirmationModal` (24 uses) is in good shape; nothing to do.

---

## Beyond your list

### 9. Other unused / near-unused variants (from the AST scan)

Delete, along with their gallery demos and doc lines:

- Badge `outline` (0, and no status-map helper returns it), Input `lg` (0), `Progress lg` (0),
  `Spinner lg` (0), `ListRow sm` (0 — **DESIGN.md documents it for the graph node panel; the
  doc is stale**), all `ToastMessage` variants (0).
- Input `size="field"` is byte-identical to `default` — a pure alias; drop it.
- Card: `selected` is only passed by `OptionCard` internally (move the classes there),
  `interactive="within"` has 1 use, explicit `padding="default"` ×2 is redundant.
- `CardContent`, `CommandShortcut`, `BreadcrumbEllipsis` and the `DropdownMenu`
  sub/radio/checkbox/shortcut parts: 0 app uses — at minimum remove their gallery demos;
  deleting the code is optional (they track upstream shadcn).
- Textarea `sm`: one file (`GuardrailsSection`) — judgement call.

### 10. DESIGN.md: split the app spec out

Roughly 700–800 lines are per-page specification (Page chrome, App chrome, Source views,
Connectors, Workflow builder, Chat answer column, deep toast composition). Move them to a
`PATTERNS.md` (or per-area docs); DESIGN.md keeps tokens, component contracts, spacing / type /
radius / motion / focus, and the shrunken exceptions table. Trim embedded decision history
("decided 2026-09-28", the Safari strip measurements) to the rule plus a pointer. Combined with
§1–§9 the file lands near half its size with every enforced rule intact.

Doc drift found on the way: `ListRow sm` and `Dropzone tile`'s documented call sites don't match
the code, and `GoogleDrivePicker.tsx` has a disable with no Approved-exceptions row (it
disappears with the §2 link fix anyway).

### 11. The /design gallery

Same split: keep the variant matrices, move the long app-recipe demos (full toast stacks, the
connect-wizard modal, populated side panels) out or cut them. Split the 3,294-line file into one
file per section. And derive the Button/Badge matrices from the cva config objects instead of
the hardcoded lists at `DesignSystem.tsx:306-331` — the gallery then can't drift, and unused
variants stop looking "used".

### 12. Arbitrary values worth naming

~127 bracket classes outside `ui/`, nearly all legal layout. The repeats: chart heights
`h-[345px]` / `h-[245px]` (11 uses, mostly `Analytics.tsx` — a height prop on the chart-panel
recipe), the `grid-rows-[0fr]/[1fr]` collapse (§7's `Collapsible` removes it), and the measured
magic numbers `min-w-[130.5px]` / `min-w-[175.5px]` — find out what they pin and replace.

The lint machinery itself needs no cutting: ~20 rules, zero disables against them, and even the
narrow ones are cheap. Gap worth closing while in there: the `vh` / `h-screen` /
`onCloseAutoFocus` selectors have no lint tests.

---

## Suggested order

| # | change | effort | deletes |
|---|---|---|---|
| 1 | `link inline` inherits context; Badge mono; Alert `onClose` | small | ~18 disables, ~15 exception rows |
| 2 | Delete zero-use variants/tokens (§1 sidebar+aliases, §9, Modal `full`, Select `ghost`, tabs pill) | small | ~14 variants, 5–6 tokens, gallery demos |
| 3 | Tabs unification (underline default, retire Button `tab`) | small | 1 variant, a doc section |
| 4 | Segmented-control track into ToggleGroup; fix stragglers | medium | 11 wrapper divs, one of two looks |
| 5 | Select sizes → `sm`+`field`; migrate the 7 h-9 sites | medium | 1 size, 1 variant |
| 6 | Shape by construction (SearchInput/PageToolbar/ModalActions/EmptyState), then one form shape | large | the `shape` prop from Input/Select and ~60 call-site choices |
| 7 | Breadcrumb defaults in the primitive; Accordion → Collapsible | medium | per-page widths, `ui/accordion`, 3 hand-rolled headers |
| 8 | Modal `mobileVariant` by size | medium | 43 per-call choices → 1 rule |
| 9 | Split DESIGN.md + gallery; generate variant matrices | medium | ~900 doc lines from DESIGN.md |

Items 1–3 are mechanical and low-risk. Items 4–8 change pixels (in the direction of uniformity)
and deserve a screenshot pass per area. Item 6 is the one real design decision: which shape the
forms keep — the counts say square.

---

## Verified against the live app (2026-09-30)

Every visual change above was checked in the running app and drawn as Now / Proposed / Design in
`design-review/style-audit.html` (decisions S1–S15, live screenshots in `design-review/shots/sa/`).
Corrections to the sections above:

- **§1** `answer-bubble` has 4 app uses, not 6, and colours source cards, the "View more" card, the
  wiki path chip and ToolCallPanel (answers have no bubble). `sidebar-border` is on one line, twice
  (`border-` + `hover:border-`).
- **§2** Link-inline disables: 12, of which ~9 can go (Usage:232 mono, Overview:110 destructive,
  ConversationBubble:375 hover keep theirs). Inheriting size/weight/colour as written would make ~10
  standalone links plain body text and grey the hint links: recommend a new `size="text"` + a
  `tone="current"` instead. `ghost-destructive-on-accent`: only Prompts.tsx:414 is on an accent row;
  GuardrailsSection.tsx:401 sits on a destructive card whose `[&_.text-muted-foreground]` override stops
  "Remove" turning red on hover (an existing bug). `icon-lg` removal is pixel-identical.
- **§3** MultiSelectPopover's `h-10` lands on the inner input; the strip is 36px (the visible
  difference is the `px-4 pt-4` inset). Teams/Quotas searches are 32px *section-header* searches, which
  DESIGN.md allows; the real outlier is Quotas' 36px TeamPicker. ModalActions (lg pill) and
  PageToolbar (field pill) are already pill, so baking the shape in is code-only; the visible part is an
  EmptyState `onRetry` (Retry is 13 pill / 10 square; 21 of 23 are in EmptyState). `Teams.tsx:876` is
  the ghost empty-list CTA, not a square copy of the toolbar button. Inputs are 82 square / 10 pill (the
  "31" counted SearchInput). `shape` can't leave Select: 11 pill Selects are page filters that stay pill.
- **§4** Counts hold. As written, an `sm` track would be 40px next to 38px fields: use `p-0.75`.
  The Mermaid chip is at :303, is a disclosure (code opens below), and sits beside a square
  "Download ▼": recommend a chevron disclosure, not a pill.
- **§5** The 7 default-size triggers are PairDeviceModal:166, ImportAgentModal:384,
  ScheduleFormModal:539/:563, admin/Usage:118, QuotaEditor:102, ShareToTeamModal:1081. The Activity
  toolbar (to :337, plus 32px export buttons) does **not** unify by construction; it needs a `shape`
  pass-through on MultiSelect.
- **§6** Not the same pixels: builder tabs are `tab` + `inline` (26px, gap-6, no baseline) vs 36px
  underline tabs. They're route links (`nav` + `aria-current`), so a shared NavTab recipe, not Radix
  Tabs. `variant="underline"` appears 13 times (4 lists, 9 triggers).
- **§7** AgentPageHeader's only caller always renders the 24ch name button; the `w-[16ch]` and 40ch
  branches are dead code (delete, don't re-width). DetailBreadcrumb doesn't cap parents. Uncapped middle
  crumbs wrap, not overflow. RemoteDeviceConfig's AccordionItem has `overflow-hidden` but square
  corners (the focus ring pokes past the wrapper's `rounded-xl`); ConnectWizard's double padding is
  confirmed. grid-rows collapse: 3 sites; link+chevron disclosure: 7.
- **§8** 43 Modal sites: sm 6 / md 20 (7 explicit) / lg 13 / xl 4; 19 sheet / 24 dialog. Upload is
  already a sheet; ShareConversationModal is xl. The size rule also turns 9 sm/md sheets (Teams ×3,
  ScheduleForm, RegenerateAccessToken, ConvertToWiki, EnableGraphRAG, SearchConversations,
  SourceNavigator) into dialogs. Recommended instead: sheet on phones by default, dialog only for
  confirmations. `size="full"` and the unused ui/sheet parts are still referenced by the gallery.
  Separate bug: `Input autoFocus` on the Teams sheets (Teams.tsx:1494/1528/1574) raises the phone keyboard.

## Pavel's answers (2026-09-30)

S1 Design (keep the tint as `answer-surface`; code-block header + attachment chip move onto it) · S2 Proposed ·
S3 refined plan (new `size="text"` keeps primary; `tone="current"` for Alert/overlay links; `inline` unchanged) ·
S4 Proposed (keep `ghost-destructive-on-accent`; fix the guardrail "Remove" hover) · S5 code-only · S6 Proposed ·
S7 Proposed · S8 Proposed (square forms) · **S9 re-mock** (tracks must fit their rows) · S10 Proposed · S11 Proposed ·
S12 Proposed (NavTab, builder tabs grow) · S13 Proposed · S14 Proposed (delete `ui/accordion`) · S15 Design (sheet by
default on phones, dialog for confirmations). Implementation spec: `design-review/STYLE_IMPL_BRIEF.md`.

## Built (2026-09-30, uncommitted)

Every answered decision except S9 is built: 144 files changed, 8 new test files, new `ui/collapsible`,
`ui/accordion` deleted, DESIGN.md updated (8 Approved-exceptions rows removed). Checks: tsc clean, vitest
258 files / 2580 tests, lint:design 0, eslint 0 errors on changed files, `npm run build` ok.
Fixed on the way: guardrail "Remove" hover (`ui/card` destructive tone), MultiSelectPopover opening off-screen
(capped at Radix available height), closed Collapsible content now `inert`, phone autofocus dropped on the
Teams, TestRetrieval and FolderManagement sheets, PromptsModal insert-variable select square.
Open: **S9** (round-2 mock `design-review/style-audit-s9.html`: track in ToggleGroup + `fill` prop).
Not started (code-only, from the audit): §1 token aliases, §9 zero-use variants (Badge outline, Input lg/field
alias, Progress/Spinner lg, ToastMessage variants, Modal `full`), Badge mono / Alert `onClose`, §10 DESIGN.md
split, §11 gallery split, `load-more-status` square Retry.
