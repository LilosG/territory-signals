/** Per-client brand values. Swap this file (or its values) per deployment. */
export interface Brand {
  name: string;
  shortName: string;
  initials: string;
  tagline: string;
  /** CSS custom property values injected on :root; tokens.css consumes them. */
  colors: {
    accent: string;      // deep navy
    accentStrong: string;
    accentSoft: string;  // tinted surface
    accentFg: string;    // text on accent
  };
  fontFamily: string;
}

export const brand: Brand = {
  name: 'The Kaiser Team',
  shortName: 'Kaiser Team',
  initials: 'KT',
  tagline: 'Territory intelligence',
  colors: {
    accent: '#0F172A',
    accentStrong: '#020617',
    accentSoft: '#F1F5F9',
    accentFg: '#FFFFFF',
  },
  fontFamily: "'Inter Variable', Inter, ui-sans-serif, system-ui, sans-serif",
};

export const brandCssVars = (b: Brand = brand) =>
  `:root{--brand-accent:${b.colors.accent};--brand-accent-strong:${b.colors.accentStrong};--brand-accent-soft:${b.colors.accentSoft};--brand-accent-fg:${b.colors.accentFg};--brand-font:${b.fontFamily};}`;
