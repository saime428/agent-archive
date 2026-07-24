import { describe, expect, it } from "vitest";
import { resolveTheme } from "./theme";

describe("resolveTheme", () => {
  it("defaults to theme B and the system mode", () => {
    expect(resolveTheme(null, null, true)).toEqual({ theme: "b", mode: "auto", resolvedMode: "dark" });
    expect(resolveTheme(null, null, false).resolvedMode).toBe("light");
  });

  it("keeps valid manual values and rejects invalid storage", () => {
    expect(resolveTheme("c", "light", true)).toEqual({ theme: "c", mode: "light", resolvedMode: "light" });
    expect(resolveTheme("x", "sepia", true)).toEqual({ theme: "b", mode: "auto", resolvedMode: "dark" });
  });
});
