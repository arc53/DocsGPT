import js from '@eslint/js';
import { plugin as shadcn } from '@shadcn/lint';
import tsParser from '@typescript-eslint/parser';
import tsPlugin from '@typescript-eslint/eslint-plugin';
import react from 'eslint-plugin-react';
import unusedImports from 'eslint-plugin-unused-imports';
import prettier from 'eslint-plugin-prettier';
import globals from 'globals';

import { cardSurfaceSelectors } from './eslint/card-surfaces.js';
import { everywhereSelectors, pageSelectors } from './eslint/design-rules.js';

// Selectors every file gets: viewport heights, focus return, card surfaces.
// On iOS Safari vh (and h-screen, which is 100vh) is the viewport with the
// toolbars hidden, so a vh height overflows the visible screen. w-screen is
// vw, which the toolbars don't change, so it stays allowed.
const baseSyntaxRules = [
  ...['Literal[value=/\\dvh\\b/]', 'TemplateElement[value.raw=/\\dvh\\b/]'].map(
    (selector) => ({
      selector,
      message:
        'vh is the toolbar-hidden viewport on iOS Safari. Use dvh for the app shell and caps on things that pop up, svh for a fixed-size panel in a page that scrolls, or max-h-sheet for a bottom sheet. See DESIGN.md.',
    }),
  ),
  ...[
    'Literal[value=/(^|[\\s:])(min-|max-)?h-screen\\b/]',
    'TemplateElement[value.raw=/(^|[\\s:])(min-|max-)?h-screen\\b/]',
  ].map((selector) => ({
    selector,
    message:
      "Tailwind's screen heights (h-/min-h-/max-h-screen) are the toolbar-hidden viewport on iOS Safari, taller than the visible screen. Use h-dvh / min-h-dvh, or svh for a fixed panel. See DESIGN.md.",
  })),
  // Modal, Sheet and DialogContent return focus to what had it on open
  // (ui/use-focus-return.ts). A hand-rolled return focuses the trigger
  // even after a tap, which lights its ring on iOS.
  {
    selector: 'JSXAttribute[name.name="onCloseAutoFocus"]',
    message:
      'Modal, Sheet and DialogContent already return focus to what had it on open (ui/use-focus-return.ts). Don\'t hand-roll onCloseAutoFocus. See DESIGN.md "Focus return".',
  },
  // Nothing on a filled tile repeats its muted fill (DESIGN.md "Card
  // surfaces").
  ...cardSurfaceSelectors,
];

export default [
  {
    ignores: [
      'node_modules/',
      'dist/',
      'prettier.config.cjs',
      'public/',
      '.prettierignore',
      'package-lock.json',
      'package.json',
      'postcss.config.cjs',
      'tsconfig.json',
      'tsconfig.node.json',
      'vite.config.ts',
    ],
  },
  {
    files: ['**/*.{js,jsx,ts,tsx}'],
    languageOptions: {
      ecmaVersion: 'latest',
      sourceType: 'module',
      parser: tsParser,
      parserOptions: {
        ecmaFeatures: {
          jsx: true,
        },
      },
      globals: {
        ...globals.browser,
        ...globals.es2021,
        ...globals.node,
      },
    },
    plugins: {
      '@typescript-eslint': tsPlugin,
      react,
      'unused-imports': unusedImports,
      prettier,
      shadcn,
    },
    rules: {
      ...js.configs.recommended.rules,
      ...tsPlugin.configs.recommended.rules,
      ...react.configs.recommended.rules,
      ...prettier.configs.recommended.rules,
      'react/prop-types': 'off',
      'unused-imports/no-unused-imports': 'error',
      'react/react-in-jsx-scope': 'off',
      'no-undef': 'off',
      '@typescript-eslint/no-explicit-any': 'warn',
      '@typescript-eslint/no-unused-vars': 'warn',
      '@typescript-eslint/no-unused-expressions': 'warn',
      'prettier/prettier': [
        'error',
        {
          endOfLine: 'auto',
        },
      ],
      // The Radix Dialog wrapper is an internal primitive; app code uses
      // <Modal> (or <CommandDialog>). Only src/components/ui may import it.
      'no-restricted-imports': [
        'error',
        {
          patterns: [
            {
              group: ['**/components/ui/dialog'],
              message:
                'Use <Modal> from @/components/ui/modal; the Dialog primitive is internal to ui/.',
            },
          ],
        },
      ],
      // DESIGN.md rules a selector can check: viewport heights, focus return
      // and card surfaces (baseSyntaxRules above), plus the class and markup
      // rules in eslint/design-rules.js.
      'no-restricted-syntax': [
        'error',
        ...baseSyntaxRules,
        ...everywhereSelectors,
        ...pageSelectors,
      ],
      // Design-system rules (@shadcn/lint). Tokens, variants and the
      // approved exceptions are documented in DESIGN.md.
      'shadcn/no-restyle': [
        'error',
        {
          allow: ['layout'],
          contracts: [
            {
              pattern: '^Button$',
              allow: ['layout'],
              message: {
                shape:
                  '"{{className}}" is not allowed on <Button>: use shape="pill" for round buttons. Other shapes need a new variant in {{file}}.',
                spacing:
                  '"{{className}}" is not allowed on <Button>: use a size ({{sizes}}). shape="pill" already widens the padding; put space around the button on the parent (gap) or as margin here.',
                color:
                  '"{{className}}" is not allowed on <Button>: use a variant ({{variants}}). Primary buttons already have white text; muted icon buttons are variant="ghost-muted"; bordered brand buttons are variant="outline-primary".',
                typography:
                  '"{{className}}" is not allowed on <Button>: size="xs" gives text-xs; the default size is text-sm. Add a size in {{file}} only if the design explicitly calls for one.',
                default:
                  '"{{className}}" is not allowed on <Button>: {{category}} belongs to the component. Use a variant ({{variants}}), a size ({{sizes}}) or a shape (default, pill). See DESIGN.md.',
              },
            },
            {
              pattern: '^Input$',
              // font-mono: code fields (JSON, keys) keep a monospace face.
              allow: [
                'layout',
                'text-left',
                'text-center',
                'text-right',
                'font-mono',
              ],
              message: {
                default:
                  '"{{className}}" is not allowed on <Input>: use size (default, sm, lg, field), shape (default, pill) and variant (default, bare, filled); alignment classes and font-mono are allowed. Add a variant in {{file}} only if the design explicitly calls for one.',
              },
            },
            {
              pattern: '^SelectTrigger$',
              allow: ['layout'],
              message: {
                default:
                  '"{{className}}" is not allowed on <SelectTrigger>: use size (sm, default, field), variant (default, ghost) and shape (default, pill) from {{file}}.',
              },
            },
            {
              pattern: '^Avatar$',
              allow: ['layout'],
              message: {
                default:
                  '"{{className}}" is not allowed on <Avatar>: use size (xs, sm, default, lg), shape (circle, square) and variant (primary, muted) from {{file}}.',
              },
            },
            {
              pattern: '^Card$',
              allow: ['layout', 'gap-*'],
              message: {
                default:
                  '"{{className}}" is not allowed on <Card>: use variant (outline, filled, subtle), tone (destructive), padding (none, sm, default, lg) and interactive/selected from {{file}}.',
              },
            },
            {
              pattern: '^Textarea$',
              // font-mono: code editors (JSON schema, workflow code) keep a
              // monospace face.
              allow: [
                'layout',
                'text-left',
                'text-center',
                'text-right',
                'font-mono',
              ],
              message: {
                default:
                  '"{{className}}" is not allowed on <Textarea>: use size (sm, default, lg), resize (none, vertical, both) and variant (default, filled) from {{file}}; min-height and width are layout and allowed.',
              },
            },
            {
              pattern: '^Badge$',
              allow: ['layout'],
              message: {
                default:
                  '"{{className}}" is not allowed on <Badge>: use a variant ({{variants}}) from {{file}}.',
              },
            },
            {
              pattern: '^(Alert|AlertTitle|AlertDescription)$',
              allow: ['layout'],
              message: {
                default:
                  '"{{className}}" is not allowed on <{{component}}>: use Alert variant (default, neutral, success, warning, info, destructive) from {{file}}.',
              },
            },
            {
              pattern: '^(Tabs|TabsList|TabsTrigger|TabsContent)$',
              allow: ['layout'],
              message: {
                default:
                  '"{{className}}" is not allowed on <{{component}}>: use the variants in {{file}}.',
              },
            },
            {
              pattern: '^Command(Input|List|Item|Group|Empty)?$',
              allow: ['layout'],
              message: {
                default:
                  '"{{className}}" is not allowed on <{{component}}>: use the parts and the checked prop from {{file}}.',
              },
            },
            {
              pattern: '^Skeleton$',
              allow: ['layout', 'rounded-*'],
            },
            {
              pattern: '^Spinner$',
              allow: ['layout', 'color'],
            },
            {
              pattern: '^(ToastContent|ToastItem|ToastFooter)$',
              allow: ['layout', 'spacing'],
            },
            {
              // The primitive measures Content's padding-block for its scroll
              // math, and the Viewport's top gap must scroll with the
              // messages, so padding here is part of the layout.
              pattern: '^MessageScroller(Viewport|Content)$',
              allow: ['layout', 'spacing'],
            },
            {
              pattern: '^(CardHeader|CardContent|CardFooter|CardAction)$',
              allow: ['layout', 'spacing', 'gap-*', 'bg-muted/*'],
            },
            {
              pattern: '^(CardTitle|CardDescription)$',
              allow: ['layout', 'typography', 'line-clamp-*'],
            },
            {
              pattern: '^(TableCell|TableHeader)$',
              allow: ['layout', 'typography', 'text-muted-foreground'],
            },
            {
              pattern:
                '^(Label|DialogTitle|DialogDescription|SheetTitle|SheetDescription)$',
              allow: [
                'layout',
                'typography',
                'text-muted-foreground',
                'text-foreground',
              ],
            },
            {
              // Modal wraps DialogContent and merges className after its p-8.
              pattern:
                '^((Dialog|Popover|Sheet|DropdownMenu|DropdownMenuSub|Select|Tooltip)Content|Sheet(Header|Footer)|Modal)$',
              allow: ['layout', 'p-0'],
            },
          ],
        },
      ],
      'shadcn/no-raw-colors': [
        'error',
        {
          message:
            '"{{className}}" uses the raw Tailwind palette. Map it to a token from {{file}}: grey text -> text-foreground or text-muted-foreground; grey borders -> border-border; grey fills -> bg-muted, bg-accent or bg-card; red -> destructive; green -> success; amber, yellow and orange -> warning; blue -> info; purple -> primary. Soft badge or alert fills use bg-<token>/10 and a single class replaces the light+dark pair. Status pills should be <Badge variant="...">.',
        },
      ],
      'shadcn/no-arbitrary-values': [
        'error',
        // Motion values (`transition-[color,box-shadow]`, custom easings)
        // have no token scale; everything else must come from the theme.
        { allow: ['layout', 'transition-*', 'ease-*'] },
      ],
      'shadcn/no-inline-styles': 'error',
      'shadcn/no-unknown-classes': 'error',
      'shadcn/require-static-classes': 'error',
    },
    settings: {
      react: {
        version: 'detect',
      },
      shadcn: {
        note: 'See frontend/DESIGN.md for tokens, component variants and approved exceptions.',
      },
    },
  },
  {
    // The design-system components define the styles; they are not restyled.
    files: ['src/components/ui/**'],
    rules: {
      'shadcn/no-restyle': 'off',
      'no-restricted-imports': 'off',
      // ui/ defines the parts the page rules ask for (the table, the
      // checkbox, the floating label's transition-all), so only the
      // everywhere rules apply here.
      'no-restricted-syntax': [
        'error',
        ...baseSyntaxRules,
        ...everywhereSelectors,
      ],
    },
  },
  {
    // Tests hold class strings as fixtures (often asserting their absence),
    // so the class-token rules don't apply to them.
    files: ['src/**/*.test.{ts,tsx}'],
    rules: {
      'no-restricted-syntax': ['error', ...baseSyntaxRules],
    },
  },
  {
    // Third-party renderers and canvas-positioned nodes take computed
    // runtime values that Tailwind classes cannot express.
    files: [
      'src/components/MermaidRenderer.tsx',
      'src/agents/workflow/nodes/**',
    ],
    rules: {
      'shadcn/no-inline-styles': 'off',
    },
  },
];
