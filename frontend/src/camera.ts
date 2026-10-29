// Shared camera picker: enumerate device cameras, remember the user's choice,
// and build getUserMedia constraints that prefer it.
export interface CameraDevice { id: string; label: string }

const KEY = "fg-camera-id";

export function getPreferredCameraId(): string | null {
  try { return localStorage.getItem(KEY); } catch { return null; }
}

export function setPreferredCameraId(id: string | null) {
  try {
    if (id) localStorage.setItem(KEY, id);
    else localStorage.removeItem(KEY);
  } catch { /* private mode */ }
}

export async function listCameras(): Promise<CameraDevice[]> {
  try {
    if (!navigator.mediaDevices?.enumerateDevices) return [];
    const devices = await navigator.mediaDevices.enumerateDevices();
    return devices
      .filter((d) => d.kind === "videoinput")
      .map((d, i) => ({ id: d.deviceId, label: d.label || `Camera ${i + 1}` }));
  } catch {
    return [];
  }
}

/** Constraints that prefer a specific device, falling back to a facing mode. */
export function cameraConstraints(deviceId: string | null, facing: "environment" | "user", audio = false): MediaStreamConstraints {
  if (deviceId) {
    return { video: { deviceId: { exact: deviceId }, width: { ideal: 1280 }, height: { ideal: 720 } }, audio };
  }
  return { video: { facingMode: { ideal: facing }, width: { ideal: 1280 }, height: { ideal: 720 } }, audio };
}
