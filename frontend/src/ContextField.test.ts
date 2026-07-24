import { describe, expect, it } from "vitest";
import { canvasParameters } from "./ContextField";

describe("canvasParameters", () => {
  it("makes tool active and approval constrained", () => {
    expect(canvasParameters("tool").speed).toBeGreaterThan(canvasParameters("idle").speed);
    expect(canvasParameters("approval").reach).toBeLessThan(canvasParameters("final").reach);
  });
});
