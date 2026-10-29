import { describe, expect, it } from "vitest";
import { parseDimension, validateAnnotation, type AnnotShape } from "./guideFormats";

describe("parseDimension", () => {
  it("parses a plain metric dimension", () => {
    expect(parseDimension("3.5 mm")).toEqual({ value: 3.5, unit: "mm" });
  });
  it("trims whitespace and lowercases units", () => {
    expect(parseDimension("  12 CM ")).toEqual({ value: 12, unit: "cm" });
  });
  it("rejects missing values instead of inventing one", () => {
    const r = parseDimension("about this big");
    expect("error" in r && r.error).toBeTruthy();
  });
  it("rejects unknown units", () => {
    const r = parseDimension("3.5 parsecs");
    expect("error" in r && r.error).toMatch(/unit/i);
  });
  it("rejects zero and empty input", () => {
    expect("error" in parseDimension("0 mm")).toBe(true);
    expect("error" in parseDimension("")).toBe(true);
  });
});

describe("validateAnnotation", () => {
  const pt = (x: number, y: number): [number, number] => [x, y];
  it("accepts a minimal valid point", () => {
    expect(validateAnnotation([{ type: "point", points: [pt(0.5, 0.5)] }])).toBeNull();
  });
  it("accepts a valid dimension with exact user value", () => {
    const shapes: AnnotShape[] = [{ type: "dimension", points: [pt(0.5, 0.5)], dimension: { value: 3.5, unit: "mm" } }];
    expect(validateAnnotation(shapes)).toBeNull();
  });
  it("requires at least one shape", () => {
    expect(validateAnnotation([])).toMatch(/at least one/i);
  });
  it("rejects out-of-range coordinates (no guessing positions)", () => {
    expect(validateAnnotation([{ type: "point", points: [pt(1.5, 0.5)] }])).toMatch(/0\.\.1/);
  });
  it("rejects two-point shapes with one point", () => {
    expect(validateAnnotation([{ type: "rect", points: [pt(0.1, 0.1)] }])).toMatch(/coordinates must be/);
  });
  it("rejects invented dimension units", () => {
    const shapes: AnnotShape[] = [{ type: "dimension", points: [pt(0.5, 0.5)], dimension: { value: 3.5, unit: "parsecs" } }];
    expect(validateAnnotation(shapes)).toMatch(/unit/i);
  });
  it("rejects non-positive dimension values", () => {
    const shapes: AnnotShape[] = [{ type: "dimension", points: [pt(0.5, 0.5)], dimension: { value: 0, unit: "mm" } }];
    expect(validateAnnotation(shapes)).toMatch(/positive/i);
  });
  it("rejects dimensions on non-dimension shapes", () => {
    const shapes = [{ type: "point", points: [pt(0.5, 0.5)], dimension: { value: 1, unit: "mm" } }] as unknown as AnnotShape[];
    expect(validateAnnotation(shapes)).toMatch(/only dimension/i);
  });
  it("rejects overlong labels", () => {
    expect(validateAnnotation([{ type: "label", points: [pt(0.5, 0.5)], text: "x".repeat(201) }])).toMatch(/too long|max 200/i);
  });
});
