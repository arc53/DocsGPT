import { useMDXComponents as getThemeComponents } from 'nextra-theme-docs';

export function useMDXComponents(components) {
  return {
    ...getThemeComponents(),
    ...components,
  };
}
