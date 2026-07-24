import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "@fontsource-variable/geist";
import "@fontsource-variable/geist-mono";
import { App } from "./App";
import { applyInitialTheme, ThemeProvider } from "./theme";
import "./styles.css";

const root = document.getElementById("root");

if (!root) {
  throw new Error("Missing #root element.");
}

const initialTheme = applyInitialTheme();

createRoot(root).render(
  <StrictMode>
    <ThemeProvider initial={initialTheme}>
      <App />
    </ThemeProvider>
  </StrictMode>,
);
