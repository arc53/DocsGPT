import js from '@eslint/js'
import tsParser from '@typescript-eslint/parser'
import tsPlugin from '@typescript-eslint/eslint-plugin'
import react from 'eslint-plugin-react'
import unusedImports from 'eslint-plugin-unused-imports'
import prettier from 'eslint-plugin-prettier'
import globals from 'globals'

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
    },
    settings: {
      react: {
        version: 'detect',
      },
    },
  },
]
