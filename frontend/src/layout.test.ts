import { describe, expect, it } from "vitest";

import { DEFAULT_LAYOUT, LAYOUT_KEY, loadLayout, saveLayout } from "./layout";

describe("layout persistence", () => {
  it("falls back when storage is absent, malformed, or blocked", () => {
    expect(loadLayout({ getItem: () => null })).toEqual(DEFAULT_LAYOUT);
    expect(loadLayout({ getItem: () => "{" })).toEqual(DEFAULT_LAYOUT);
    expect(loadLayout({ getItem: () => { throw new Error("blocked"); } })).toEqual(DEFAULT_LAYOUT);
  });

  it("keeps valid fields and bounds untrusted values", () => {
    const read = (value: unknown) => loadLayout({ getItem: () => JSON.stringify(value) });

    expect(read({ railOpen: false, railWidth: 999, canvasEnabled: false, workspaceView: "git" })).toEqual({
      railOpen: false,
      railWidth: 420,
      canvasEnabled: false,
      workspaceView: "git",
    });
    expect(read({ railOpen: "no", railWidth: "wide", canvasEnabled: 1, workspaceView: "secrets" })).toEqual(DEFAULT_LAYOUT);
  });

  it("writes one bounded non-sensitive record and ignores write failures", () => {
    let saved: [string, string] | null = null;
    saveLayout({
      railOpen: false,
      railWidth: 260,
      canvasEnabled: true,
      workspaceView: "terminal",
    }, { setItem: (key, value) => { saved = [key, value]; } });

    expect(saved?.[0]).toBe(LAYOUT_KEY);
    expect(JSON.parse(saved?.[1] || "{}")).toEqual({
      railOpen: false,
      railWidth: 260,
      canvasEnabled: true,
      workspaceView: "terminal",
    });
    expect(() => saveLayout(DEFAULT_LAYOUT, { setItem: () => { throw new Error("quota"); } })).not.toThrow();
  });
});
