import js from '@eslint/js';
import { plugin as shadcn } from '@shadcn/lint';
import tsParser from '@typescript-eslint/parser';
import tsPlugin from '@typescript-eslint/eslint-plugin';
import react from 'eslint-plugin-react';
import unusedImports from 'eslint-plugin-unused-imports';
import prettier from 'eslint-plugin-prettier';
import globals from 'globals';

export default [
  {
    ignores: [
      'node_modules/',
      'dist/',
      'prettier.config.cjs',
      '.eslintrc.cjs',
      'env.d.ts',
      'public/',
      'assets/',
      'vite-env.d.ts',
      '.prettierignore',
      'package-lock.json',
      'package.json',
      'postcss.config.cjs',
      'tailwind.config.cjs',
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
      // Design-system rules (@shadcn/lint). Tokens, variants and the
      // approved exceptions are documented in DESIGN.md. Every rule starts
      // at `warn`; promote a rule to `error` once its count reaches zero.
      'shadcn/no-restyle': [
        'warn',
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
                  '"{{className}}" is not allowed on <Input>: use size (default, sm, lg) and shape (default, pill); alignment classes are allowed. Add a variant in {{file}} only if the design explicitly calls for one.',
              },
            },
            {
              pattern: '^SelectTrigger$',
              allow: ['layout'],
              message: {
                default:
                  '"{{className}}" is not allowed on <SelectTrigger>: use size (sm, default, lg), variant (default, ghost) and shape (default, pill) from {{file}}.',
              },
            },
            {
              pattern: '^Avatar$',
              allow: ['layout'],
              message: {
                default:
                  '"{{className}}" is not allowed on <Avatar>: use size (sm, default, lg, xl), shape (circle, square) and variant (primary, muted) from {{file}}.',
              },
            },
            {
              pattern: '^Card$',
              allow: ['layout', 'gap-*'],
              message: {
                default:
                  '"{{className}}" is not allowed on <Card>: use variant (outline, filled, subtle), padding (none, sm, default, lg) and interactive/selected from {{file}}.',
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
                  '"{{className}}" is not allowed on <Textarea>: use size (sm, default, lg) and resize (none, vertical, both) from {{file}}; min-height and width are layout and allowed.',
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
              pattern: '^Progress$',
              allow: ['layout'],
            },
            {
              pattern: '^(Toast|ToastViewport)$',
              allow: ['layout'],
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
              pattern: '^OptionCard$',
              allow: ['layout'],
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
              pattern: '^((Dialog|Popover|Sheet|DropdownMenu)Content|Modal)$',
              allow: ['layout', 'p-0'],
            },
          ],
        },
      ],
      'shadcn/no-raw-colors': [
        'warn',
        {
          message:
            '"{{className}}" uses the raw Tailwind palette. Map it to a token from {{file}}: grey text -> text-foreground or text-muted-foreground; grey borders -> border-border; grey fills -> bg-muted, bg-accent or bg-card; red -> destructive; green -> success; amber, yellow and orange -> warning; blue -> info; purple -> primary. Soft badge or alert fills use bg-<token>/10 and a single class replaces the light+dark pair. Status pills should be <Badge variant="...">.',
        },
      ],
      'shadcn/no-arbitrary-values': [
        'warn',
        // Motion values (`transition-[color,box-shadow]`, custom easings)
        // have no token scale; everything else must come from the theme.
        { allow: ['layout', 'transition-*', 'ease-*'] },
      ],
      'shadcn/no-inline-styles': 'warn',
      'shadcn/no-unknown-classes': 'warn',
      'shadcn/require-static-classes': 'warn',
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
