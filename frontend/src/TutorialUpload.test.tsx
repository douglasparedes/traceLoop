import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import TutorialUpload from "./TutorialUpload";

const queueMocks = {
  checkStorageFor: vi.fn(),
  listQueuedUploads: vi.fn(),
  findReusableUpload: vi.fn(),
  queueTutorialUpload: vi.fn(),
  refreshQueuedUpload: vi.fn(),
  runQueuedUpload: vi.fn(),
};

vi.mock("./uploadQueue", async (importOriginal) => {
  const mod = await importOriginal<typeof import("./uploadQueue")>();
  return {
    ...mod,
    checkStorageFor: (...args: unknown[]) => queueMocks.checkStorageFor(...args),
    listQueuedUploads: (...args: unknown[]) => queueMocks.listQueuedUploads(...args),
    findReusableUpload: (...args: unknown[]) => queueMocks.findReusableUpload(...args),
    queueTutorialUpload: (...args: unknown[]) => queueMocks.queueTutorialUpload(...args),
    refreshQueuedUpload: (...args: unknown[]) => queueMocks.refreshQueuedUpload(...args),
    runQueuedUpload: (...args: unknown[]) => queueMocks.runQueuedUpload(...args),
  };
});

beforeEach(() => {
  Object.values(queueMocks).forEach((m) => m.mockReset());
  queueMocks.checkStorageFor.mockResolvedValue({ ok: true, message: "" });
  queueMocks.listQueuedUploads.mockResolvedValue([]);
  queueMocks.findReusableUpload.mockReturnValue(null);
  queueMocks.queueTutorialUpload.mockResolvedValue({ key: "k1" });
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

  describe("duplicate upload handling", () => {
    const job = (cached?: boolean) => ({
      id: "job-1", title: "Clip", status: "done", progress: 100,
      access_token: "tok", ...(cached ? { cached: true } : {}),
    });

    it("shows the cached notice and opens the existing tutorial", async () => {
      queueMocks.runQueuedUpload.mockResolvedValue(job(true));
      const onOpenStudio = vi.fn();
      render(<TutorialUpload mode="auto" onModeChange={() => undefined} onOpenStudio={onOpenStudio} onUploaded={() => undefined} />);
      const input = screen.getByLabelText(/Choose an existing tutorial video/) as HTMLInputElement;
      Object.defineProperty(input, "files", { value: [mp4("clip.mp4", 2048)], configurable: true });
      fireEvent.change(input);
      fireEvent.click(await screen.findByRole("button", { name: /Upload & generate guide/ }));
      expect(await screen.findByText(/already processed/)).toBeInTheDocument();
      fireEvent.click(screen.getByRole("button", { name: /Open in Tutorial Studio/ }));
      expect(onOpenStudio).toHaveBeenCalledWith(expect.objectContaining({ id: "job-1", access_token: "tok" }));
    });

    it("uploads as new with forceNew when the user chooses to", async () => {
      queueMocks.runQueuedUpload
        .mockResolvedValueOnce(job(true))
        .mockResolvedValueOnce(job(false));
      render(<TutorialUpload mode="auto" onModeChange={() => undefined} onOpenStudio={() => undefined} onUploaded={() => undefined} />);
      const input = screen.getByLabelText(/Choose an existing tutorial video/) as HTMLInputElement;
      Object.defineProperty(input, "files", { value: [mp4("clip.mp4", 2048)], configurable: true });
      fireEvent.change(input);
      fireEvent.click(await screen.findByRole("button", { name: /Upload & generate guide/ }));
      expect(await screen.findByText(/already processed/)).toBeInTheDocument();
      fireEvent.click(screen.getByRole("button", { name: /Upload as new instead/ }));
      await screen.findByRole("button", { name: /Open in Tutorial Studio/ });
      expect(queueMocks.runQueuedUpload).toHaveBeenLastCalledWith(expect.anything(), expect.anything(), expect.anything(), { forceNew: true });
      expect(screen.queryByText(/already processed/)).not.toBeInTheDocument();
    });
  });
});
