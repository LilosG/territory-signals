/** ECharts theme derived from the CSS design tokens at runtime (so brand swaps flow through). */
const css = (name: string, fallback: string) =>
  (typeof document !== 'undefined' && getComputedStyle(document.documentElement).getPropertyValue(name).trim()) || fallback;

export function chartTheme() {
  const ink = css('--color-ink', '#14171f');
  const muted = css('--color-ink-muted', '#565c6b');
  const line = css('--color-line', '#e4e1da');
  const accent = css('--color-accent', '#17294d');
  // one accent plus tints and neutrals for multi-series; never a rainbow
  const palette = [accent, css('--color-band-warm', '#3f5f96'), css('--color-band-watch', '#8da2c6'), css('--color-ink-faint', '#626777'), css('--color-band-low', '#b9bdc7')];
  return {
    ink, muted, line, accent, palette,
    font: css('--font-sans', 'Inter, sans-serif'),
    base: {
      color: palette,
      textStyle: { fontFamily: css('--font-sans', 'Inter, sans-serif'), color: muted, fontSize: 12 },
      grid: { left: 8, right: 12, top: 28, bottom: 8, containLabel: true },
      tooltip: { backgroundColor: '#fff', borderColor: line, textStyle: { color: ink, fontSize: 12 }, extraCssText: 'box-shadow:0 8px 24px -8px rgba(20,23,31,.18);font-variant-numeric:tabular-nums;' },
      xAxis: { axisLine: { lineStyle: { color: line } }, axisTick: { show: false }, axisLabel: { color: muted } },
      yAxis: { splitLine: { lineStyle: { color: line } }, axisLabel: { color: muted } },
      animationDuration: 400,
    },
  };
}
