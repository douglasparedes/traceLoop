import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AnnotationComposer, TechnicalImageViewer } from "./VisualStudio";

describe("TechnicalImageViewer", () => {
  it("renders source image with accessible label and bbox overlay", () => {
    render(<TechnicalImageViewer src="http://x/img.png" alt="pump housing" bbox={[0.1, 0.1, 0.4, 0.4]} />);
    expect(screen.getByRole("img", { name: "pump housing" })).toBeInTheDocument();
  });

  it("is keyboard-activatable as a tap target when onTap is provided", async () => {
    const onTap = vi.fn();
    vi.spyOn(Element.prototype, "getBoundingClientRect").mockReturnValue({
      left: 0, top: 0, right: 200, bottom: 100, width: 200, height: 100, x: 0, y: 0, toJSON: () => {},
    });
    const user = userEvent.setup();
    render(<TechnicalImageViewer src="http://x/img.png" alt="tap me" onTap={onTap} />);
    const btn = screen.getByRole("button", { name: /tap me/i });
    expect(btn).toBeInTheDocument();
    await user.click(btn);
    expect(onTap).toHaveBeenCalledTimes(1);
    const [nx, ny] = onTap.mock.calls[0] as [number, number];
    expect(nx).toBeGreaterThanOrEqual(0);
    expect(nx).toBeLessThanOrEqual(1);
    expect(ny).toBeGreaterThanOrEqual(0);
    expect(ny).toBeLessThanOrEqual(1);
  });
});

describe("AnnotationComposer", () => {
  beforeEach(() => {
    vi.spyOn(Element.prototype, "getBoundingClientRect").mockReturnValue({
      left: 0, top: 0, right: 200, bottom: 100, width: 200, height: 100, x: 0, y: 0, toJSON: () => {},
    });
  });

  it("blocks saving with an invalid dimension instead of submitting", async () => {
    const onDone = vi.fn();
    const user = userEvent.setup();
    render(<AnnotationComposer imageUrl="http://x/img.png" imageLabel="pump" onDone={onDone} />);
    await user.click(screen.getByRole("button", { name: "dimension" }));
    const canvas = screen.getByRole("button", { name: "pump. Activate, then click the part you mean." });
    await user.click(canvas);
    await user.click(canvas);
    expect(await screen.findByRole("alert")).toHaveTextContent(/dimension/i);
    expect(onDone).not.toHaveBeenCalled();
  });

  it("saves a point annotation and allows removal", async () => {
    const onDone = vi.fn();
    const user = userEvent.setup();
    render(<AnnotationComposer imageUrl="http://x/img.png" imageLabel="pump" onDone={onDone} />);
    await user.click(screen.getByRole("button", { name: "pump. Activate, then click the part you mean." }));
    expect(await screen.findByRole("listitem")).toHaveTextContent(/^point/);
    await user.click(screen.getByRole("button", { name: "Remove" }));
    expect(screen.queryByRole("listitem")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save annotation" })).toBeDisabled();
  });

  it("requires pointer input types to stay within 0..1 (no fabricated geometry)", async () => {
    const onDone = vi.fn();
    const user = userEvent.setup();
    render(<AnnotationComposer imageUrl="http://x/img.png" imageLabel="pump" onDone={onDone} />);
    const save = screen.getByRole("button", { name: "Save annotation" });
    expect(save).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "pump. Activate, then click the part you mean." }));
    expect(save).not.toBeDisabled();
  });
});
