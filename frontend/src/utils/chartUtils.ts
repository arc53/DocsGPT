import { Chart as ChartJS } from 'chart.js';
import { useEffect, useMemo, useState } from 'react';

/**
 * Resolve a CSS custom property to a concrete colour string.
 *
 * Chart.js and other canvas renderers can't consume Tailwind classes or CSS
 * variables directly, so read the resolved value at render time and pass that
 * concrete string. Falls back when running outside a browser (SSR / tests).
 *
 * @param name The custom property, e.g. `--primary`.
 * @param fallback Returned when the property is unset or there is no DOM.
 * @returns The resolved value, trimmed.
 */
export function readCssVar(name: string, fallback: string): string {
  if (typeof window === 'undefined') return fallback;
  // The `.dark` class lives on document.body (see useDarkTheme), so query
  // body — querying documentElement would always resolve the :root value.
  const value = getComputedStyle(document.body).getPropertyValue(name).trim();
  return value || fallback;
}

/**
 * Build the hover fill for a bar: the same colour at 80% opacity.
 *
 * `color-mix()` accepts any CSS colour string (hex, `oklch()`, ...), which the
 * theme tokens are. Canvas `fillStyle` parses it in current engines. Where the
 * browser doesn't support `color-mix()`, a 6-digit hex gets an `cc` alpha and
 * anything else keeps its base colour, so the canvas never receives a string
 * it would silently ignore.
 *
 * @param color A resolved CSS colour.
 * @returns A colour string the canvas accepts.
 */
export function hoverColor(color: string): string {
  const mixed = `color-mix(in oklch, ${color} 80%, transparent)`;
  if (typeof CSS !== 'undefined' && CSS.supports?.('color', mixed)) {
    return mixed;
  }
  return /^#[0-9a-f]{6}$/i.test(color) ? `${color}cc` : color;
}

/**
 * Data-series tokens (DESIGN.md: `chart-1`..`chart-5`, data series only).
 * Fallbacks are the light-theme values from src/index.css.
 */
export const SERIES_TOKENS: [string, string][] = [
  ['--chart-1', '#7d54d1'],
  ['--chart-2', '#2563eb'],
  ['--chart-3', '#079455'],
  ['--chart-4', '#ca8a04'],
  ['--chart-5', '#ef4444'],
];

export type ChartPalette = {
  primary: string;
  series: string[];
  success: string;
  warning: string;
  destructive: string;
  /** Grid lines and axis borders. */
  border: string;
  /** Tick labels and legend text. */
  mutedForeground: string;
};

/**
 * Resolve every colour the charts use from the current theme tokens.
 *
 * @returns Concrete colour strings for the canvas: brand, the five series
 *   colours, the status colours, and the axis chrome.
 */
export function readChartPalette(): ChartPalette {
  return {
    primary: readCssVar('--primary', '#7d54d1'),
    series: SERIES_TOKENS.map(([name, fallback]) => readCssVar(name, fallback)),
    success: readCssVar('--success', '#079455'),
    warning: readCssVar('--warning', '#ca8a04'),
    destructive: readCssVar('--destructive', '#ef4444'),
    border: readCssVar('--border', '#d9d9d9'),
    mutedForeground: readCssVar('--muted-foreground', '#737373'),
  };
}

/**
 * Count theme changes, for canvases that must re-read their colours.
 *
 * Each useDarkTheme() call keeps its own state and applies the `.dark` class
 * in an effect, so a flip of `isDarkTheme` alone can be read before the class
 * lands, and a toggle made elsewhere never reaches the component. Watching the
 * body class catches the moment the tokens really change, either way.
 *
 * @returns A number that increments whenever the body class changes.
 */
export function useThemeVersion(): number {
  const [version, setVersion] = useState(0);
  useEffect(() => {
    const observer = new MutationObserver(() =>
      setVersion((current) => current + 1),
    );
    observer.observe(document.body, {
      attributes: true,
      attributeFilter: ['class'],
    });
    return () => observer.disconnect();
  }, []);
  return version;
}

/**
 * The chart palette for the current theme, re-read on every theme change.
 *
 * @returns The resolved {@link ChartPalette}.
 */
export function useChartPalette(): ChartPalette {
  const themeVersion = useThemeVersion();
  // themeVersion is not used inside the factory: it only signals a change.
  return useMemo(() => readChartPalette(), [themeVersion]);
}

const getOrCreateLegendList = (
  chart: ChartJS,
  id: string,
): HTMLUListElement => {
  const legendContainer = document.getElementById(id);
  let listContainer = legendContainer?.querySelector('ul') as HTMLUListElement;

  if (!listContainer) {
    listContainer = document.createElement('ul');
    listContainer.style.display = 'flex';
    listContainer.style.flexDirection = 'row';
    listContainer.style.margin = '0';
    listContainer.style.padding = '0';

    legendContainer?.appendChild(listContainer);
  }

  return listContainer;
};

export const htmlLegendPlugin = {
  id: 'htmlLegend',
  afterUpdate(chart: ChartJS, args: any, options: { containerID: string }) {
    const ul = getOrCreateLegendList(chart, options.containerID);

    while (ul.firstChild) {
      ul.firstChild.remove();
    }

    const items =
      chart.options.plugins?.legend?.labels?.generateLabels?.(chart) || [];

    items.forEach((item: any) => {
      const li = document.createElement('li');
      li.style.alignItems = 'center';
      li.style.cursor = 'pointer';
      li.style.display = 'flex';
      li.style.flexDirection = 'row';
      li.style.marginLeft = '10px';

      li.onclick = () => {
        chart.setDatasetVisibility(
          item.datasetIndex,
          !chart.isDatasetVisible(item.datasetIndex),
        );
        chart.update();
      };

      const boxSpan = document.createElement('span');
      boxSpan.style.background = item.fillStyle;
      boxSpan.style.borderColor = item.strokeStyle;
      boxSpan.style.borderWidth = item.lineWidth + 'px';
      boxSpan.style.display = 'inline-block';
      boxSpan.style.flexShrink = '0';
      boxSpan.style.height = '10px';
      boxSpan.style.marginRight = '10px';
      boxSpan.style.width = '10px';
      boxSpan.style.borderRadius = '10px';

      const textContainer = document.createElement('p');
      textContainer.style.fontSize = '12px';
      textContainer.style.color = item.fontColor;
      textContainer.style.margin = '0';
      textContainer.style.padding = '0';
      textContainer.style.textDecoration = item.hidden ? 'line-through' : '';

      const text = document.createTextNode(item.text);
      textContainer.appendChild(text);

      li.appendChild(boxSpan);
      li.appendChild(textContainer);
      ul.appendChild(li);
    });
  },
};
