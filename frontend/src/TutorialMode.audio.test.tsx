import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import TutorialMode from "./TutorialMode";

function fakeStream(audioTracks: { readyState: string; muted: boolean }[]) {
  const tracks = audioTracks.map((t) => ({ ...t, kind: "audio", stop: vi.fn() }));
  return {
    getAudioTracks: () => tracks,
    getTracks: () => tracks,
  } as unknown as MediaStream;
}

beforeEach(() => {
  vi.restoreAllMocks();
  Object.defineProperty(window.HTMLMediaElement.prototype, "play", {
    value: vi.fn().mockResolvedValue(undefined),
    configurable: true,
    writable: true,
  });
  Object.defineProperty(window, "isSecureContext", { value: true, configurable: true });
});

function mockCamera(stream: MediaStream) {
  Object.defineProperty(navigator, "mediaDevices", {
    value: { getUserMedia: vi.fn().mockResolvedValue(stream), enumerateDevices: vi.fn().mockResolvedValue([]) },
    configurable: true,
  });
}

describe("TutorialMode audio guard", () => {
  it("warns when the camera stream carries no microphone track", async () => {
    mockCamera(fakeStream([]));
    const user = userEvent.setup();
    render(<TutorialMode />);
    await user.click(screen.getByRole("button", { name: "Open camera" }));
    expect(await screen.findByText(/no microphone track was granted/i)).toBeInTheDocument();
  });

  it("refuses to record a video-only stream instead of failing server-side", async () => {
    mockCamera(fakeStream([]));
    const user = userEvent.setup();
    render(<TutorialMode />);
    await user.click(screen.getByRole("button", { name: "Open camera" }));
    await screen.findByText(/no microphone track was granted/i);
    await user.click(screen.getByRole("button", { name: "Start recording" }));
    await waitFor(() =>
      expect(screen.getByText(/Cannot record: this camera stream has no live microphone track/i)).toBeInTheDocument()
    );
  });

  it("accepts a stream with a live microphone track", async () => {
    mockCamera(fakeStream([{ readyState: "live", muted: false }]));
    const user = userEvent.setup();
    render(<TutorialMode />);
    await user.click(screen.getByRole("button", { name: "Open camera" }));
    await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Start recording" })).toBeInTheDocument();
  });
});
