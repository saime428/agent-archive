import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

export type ThemeName = "a" | "b" | "c";
export type ModePreference = "auto" | "dark" | "light";
export type ResolvedMode = "dark" | "light";

interface ThemeState {
  theme: ThemeName;
  mode: ModePreference;
  resolvedMode: ResolvedMode;
}

interface ThemeContextValue extends ThemeState {
  setTheme: (theme: ThemeName) => void;
  setMode: (mode: ModePreference) => void;
}

const THEME_KEY = "agent.frontend.theme";
const MODE_KEY = "agent.frontend.mode";
const ThemeContext = createContext<ThemeContextValue | null>(null);

export function resolveTheme(storedTheme: string | null, storedMode: string | null, systemDark: boolean): ThemeState {
  const theme: ThemeName = storedTheme === "a" || storedTheme === "c" ? storedTheme : "b";
  const mode: ModePreference = storedMode === "dark" || storedMode === "light" ? storedMode : "auto";
  return { theme, mode, resolvedMode: mode === "auto" ? (systemDark ? "dark" : "light") : mode };
}

function applyTheme(state: ThemeState) {
  document.documentElement.dataset.theme = state.theme;
  document.documentElement.dataset.mode = state.resolvedMode;
  document.documentElement.dataset.themeReady = "true";
  document.documentElement.style.colorScheme = state.resolvedMode;
}

export function applyInitialTheme(): ThemeState {
  const state = resolveTheme(
    localStorage.getItem(THEME_KEY),
    localStorage.getItem(MODE_KEY),
    matchMedia("(prefers-color-scheme: dark)").matches,
  );
  applyTheme(state);
  return state;
}

export function ThemeProvider({ initial, children }: { initial: ThemeState; children: ReactNode }) {
  const [theme, setThemeState] = useState(initial.theme);
  const [mode, setModeState] = useState(initial.mode);
  const [systemDark, setSystemDark] = useState(initial.resolvedMode === "dark");
  const resolvedMode: ResolvedMode = mode === "auto" ? (systemDark ? "dark" : "light") : mode;

  useEffect(() => {
    const media = matchMedia("(prefers-color-scheme: dark)");
    const update = () => setSystemDark(media.matches);
    update();
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);

  useEffect(() => applyTheme({ theme, mode, resolvedMode }), [theme, mode, resolvedMode]);

  const value = useMemo<ThemeContextValue>(
    () => ({
      theme,
      mode,
      resolvedMode,
      setTheme(next) {
        localStorage.setItem(THEME_KEY, next);
        setThemeState(next);
      },
      setMode(next) {
        if (next === "auto") localStorage.removeItem(MODE_KEY);
        else localStorage.setItem(MODE_KEY, next);
        setModeState(next);
      },
    }),
    [theme, mode, resolvedMode],
  );

  return <ThemeContext value={value}>{children}</ThemeContext>;
}

export function useTheme() {
  const value = useContext(ThemeContext);
  if (!value) throw new Error("useTheme must be used inside ThemeProvider.");
  return value;
}
