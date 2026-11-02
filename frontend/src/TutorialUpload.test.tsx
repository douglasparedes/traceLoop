import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import TutorialUpload from "./TutorialUpload";

beforeEach(() => {
  vi.restoreAllMocks();
});

function mp4(name = "clip.mp4", size = 1000): File {
  const blob = new Blob([new Uint8Array(size)], { type: "video/mp4" });
  return new File([blob], name, { type: "video/mp4" });
}

describe("TutorialUpload", () => {
  it("offers the three analysis modes with automatic by default", async () => {
    const onMode = vi.fn();
    render(<TutorialUpload mode="auto" onModeChange={onMode} onOpenStudio={() => undefined} onUploaded={() => undefined} />);
    for (const label of ["Automatic", "Narrated", "Visual-First"]) {
      expect(screen.getByRole("button", { name: new RegExp(label) })).toBeInTheDocument();
    }
    expect(screen.getByRole("button", { name: /Automatic/ })).toHaveAttribute("aria-pressed", "true");
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /Visual-First/ }));
    expect(onMode).toHaveBeenCalledWith("visual_first");
  });

  it("rejects unsupported files with format and size guidance", () => {
    render(<TutorialUpload mode="auto" onModeChange={() => undefined} onOpenStudio={() => undefined} onUploaded={() => undefined} />);
    const input = screen.getByLabelText(/Choose an existing tutorial video/) as HTMLInputElement;
    const txt = new File(["x"], "notes.txt", { type: "text/plain" });
    Object.defineProperty(input, "files", { value: [txt], configurable: true });
    fireEvent.change(input);
    expect(screen.getByRole("alert")).toHaveTextContent(/MP4.*WebM.*MOV.*MKV/);
  });

  it("previews a valid file and enables upload only with a title", async () => {
    const user = userEvent.setup();
    const onUploaded = vi.fn();
    render(<TutorialUpload mode="narrated" onModeChange={() => undefined} onOpenStudio={() => undefined} onUploaded={() => undefined} />);
    const input = screen.getByLabelText(/Choose an existing tutorial video/) as HTMLInputElement;
    Object.defineProperty(input, "files", { value: [mp4("clip.mp4", 2048)], configurable: true });
    fireEvent.change(input);
    expect(await screen.findByLabelText(/Tutorial title/)).toBeInTheDocument();
    expect(screen.getByText("2 KB · video/mp4", { exact: false })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Upload & generate guide/ })).toBeEnabled();
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
    expect(onUploaded).not.toHaveBeenCalled();
  });
});
