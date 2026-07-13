"""
ComfyUI custom node: Extract Lights for C4D
Extracts dominant light sources from an HDRI (e.g. produced by
DiffusionLight) and saves a lights.json file that the C4D Lighting
Bridge plugin (or the manual C4D script) reads to build the scene.

Install: drop this file into ComfyUI/custom_nodes/ and restart ComfyUI.
Node location: Add Node > C4D Lighting > Extract Lights for C4D
"""
import os
import glob
import json
import math

import numpy as np

try:
    import cv2
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False

try:
    import folder_paths
    OUTPUT_DIR = folder_paths.get_output_directory()
except Exception:
    OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "output")

def get_bridge_dir():
    """Shared rendezvous folder that both ComfyUI and the C4D plugin
    can locate without any user configuration.
    Override with the C4D_LIGHTING_BRIDGE_DIR environment variable."""
    d = os.environ.get("C4D_LIGHTING_BRIDGE_DIR")
    if not d:
        d = os.path.join(os.path.expanduser("~"),
                         "Documents", "C4D_Lighting_Bridge")
    os.makedirs(d, exist_ok=True)
    return d


# ---------- Light extraction logic ----------

def luminance(img):
    return 0.2126 * img[:, :, 0] + 0.7152 * img[:, :, 1] + 0.0722 * img[:, :, 2]


def direction_map(h, w):
    us = (np.arange(w, dtype=np.float32) + 0.5) / w
    vs = (np.arange(h, dtype=np.float32) + 0.5) / h
    az = us * 2.0 * np.pi - np.pi
    pol = vs * np.pi
    sin_p = np.sin(pol)[:, None]
    x = sin_p * np.sin(az)[None, :]
    y = np.repeat(np.cos(pol)[:, None], w, axis=1)
    z = sin_p * np.cos(az)[None, :]
    return np.stack([x, y, z], axis=-1)


def blur(lum, w):
    if HAS_CV2:
        return cv2.GaussianBlur(lum, (0, 0), sigmaX=w / 128.0)
    # Approximate blur via down/up-sampling when cv2 is unavailable
    small = lum[::8, ::8]
    return np.kron(small, np.ones((8, 8)))[: lum.shape[0], : lum.shape[1]]


def find_peaks(lum, num_peaks, min_sep_deg=30.0):
    h, w = lum.shape
    blurred = blur(lum, w)
    dirs = direction_map(h, w)
    work = blurred.copy()
    cos_thresh = math.cos(math.radians(min_sep_deg))
    peaks = []
    for _ in range(num_peaks):
        idx = np.unravel_index(np.argmax(work), work.shape)
        v, u = int(idx[0]), int(idx[1])
        val = float(work[v, u])
        if val <= 1e-6:
            break
        peaks.append((u, v, val))
        peak_dir = dirs[v, u]
        mask = (dirs @ peak_dir) > cos_thresh
        work[mask] = 0.0
    return peaks


def pixel_to_direction(u, v, w, h):
    azimuth = (u / w) * 2.0 * math.pi - math.pi
    polar = (v / h) * math.pi
    return [
        math.sin(polar) * math.sin(azimuth),
        math.cos(polar),
        math.sin(polar) * math.cos(azimuth),
    ]


def sample_color(img, u, v, radius=6):
    h, w = img.shape[:2]
    y0, y1 = max(0, v - radius), min(h, v + radius)
    x0, x1 = max(0, u - radius), min(w, u + radius)
    patch = img[y0:y1, x0:x1].reshape(-1, 3)
    c = patch.mean(axis=0)
    m = max(float(c.max()), 1e-6)
    lum = float((0.2126 * patch[:, 0] + 0.7152 * patch[:, 1]
                 + 0.0722 * patch[:, 2]).mean())
    return (c / m).tolist(), lum


def label_lights(lights):
    if not lights:
        return lights
    lights.sort(key=lambda L: L["intensity"], reverse=True)
    lights[0]["role"] = "key"
    key_dir = np.array(lights[0]["direction"])
    counts = {}
    for L in lights[1:]:
        d = np.array(L["direction"])
        if d[2] < -0.2:
            base = "rim"
        elif float(np.dot(d, key_dir)) < 0:
            base = "fill"
        else:
            base = "sub"
        counts[base] = counts.get(base, 0) + 1
        L["role"] = base if counts[base] == 1 else f"{base}{counts[base]}"
    return lights


def load_hdri_file(path):
    if HAS_CV2:
        img = cv2.imread(path, cv2.IMREAD_UNCHANGED)
        if img is not None:
            if img.ndim == 2:
                img = np.stack([img] * 3, axis=-1)
            img = img[:, :, :3].astype(np.float32)
            return img[:, :, ::-1].copy()  # BGR → RGB
    import imageio.v3 as iio
    img = np.asarray(iio.imread(path)).astype(np.float32)
    if img.ndim == 2:
        img = np.stack([img] * 3, axis=-1)
    return img[:, :, :3]


def smooth_blind_spot(img):
    """Soften the chrome-ball blind spot (the seam at azimuth +/-180)
    and the pole regions, where unwrapping smears edge pixels into
    radial streaks. Blends in a heavy blur with a feathered mask so
    the back of the environment reads as a soft out-of-focus wash
    instead of streak artifacts. Light peaks are extracted AFTER this,
    which also suppresses fake symmetric peaks born from the smear."""
    if not HAS_CV2:
        return img
    h, w = img.shape[:2]
    blurred = cv2.GaussianBlur(img, (0, 0), sigmaX=w / 48.0)
    xs = (np.arange(w, dtype=np.float32) + 0.5) / w
    az = np.abs(xs * 2.0 - 1.0)          # 0 = front (center), 1 = back seam
    w_az = np.clip((az - 0.60) / (0.90 - 0.60), 0.0, 1.0)
    ys = (np.arange(h, dtype=np.float32) + 0.5) / h
    el = np.abs(ys * 2.0 - 1.0)          # 0 = horizon, 1 = poles
    w_el = np.clip((el - 0.72) / (0.95 - 0.72), 0.0, 1.0)
    mask = np.maximum(w_az[None, :], w_el[:, None])[..., None]
    return (img * (1.0 - mask) + blurred * mask).astype(np.float32)


def find_latest_hdri(directory):
    files = []
    for ext in ("*.hdr", "*.exr"):
        files += glob.glob(os.path.join(directory, ext))
    if not files:
        return None
    return max(files, key=os.path.getmtime)


# ---------- ComfyUI node ----------

class ExtractLightsForC4D:
    """HDRI -> light decomposition -> lights.json. Supports an optional gobo image input."""

    CATEGORY = "C4D Lighting"
    OUTPUT_NODE = True
    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("json_path", "summary")
    FUNCTION = "run"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "hdri_path": ("STRING", {
                    "default": "",
                    "tooltip": "Leave empty to auto-use the newest .hdr/.exr in the output folder",
                }),
                "max_lights": ("INT", {"default": 6, "min": 1, "max": 10,
                    "tooltip": "Upper limit of extracted lights"}),
                "min_ev": ("FLOAT", {"default": -8.0, "min": -20.0, "max": 0.0,
                    "step": 0.5,
                    "tooltip": "Discard lights dimmer than the key by this many "
                               "stops (e.g. -8 = keep lights within 8 EV of key)"}),
                "json_name": ("STRING", {"default": "lights.json"}),
            },
            "optional": {
                "hdri_image": ("IMAGE", {
                    "tooltip": "Connect the hdr_image output of 'Exposure to HDR' "
                               "here. Saves it as .hdr and analyzes it directly.",
                }),
                "gobo_image": ("IMAGE",),
                "gobo_target": (["key", "rim", "fill", "sub"],
                                {"default": "key"}),
            },
        }

    def _save_hdr(self, arr):
        """Save a float HDR array (RGB) to the bridge folder as .hdr.
        A unique filename per run forces C4D to load a fresh texture
        (C4D caches bitmaps by path, so overwriting the same file can
        show a stale image). Older files are cleaned up, keeping the
        most recent few."""
        import time
        d = get_bridge_dir()
        path = os.path.join(d, time.strftime("c4d_hdri_%Y%m%d_%H%M%S.hdr"))
        for f in sorted(glob.glob(os.path.join(d, "c4d_hdri_*.hdr")),
                        key=os.path.getmtime)[:-4]:
            try:
                os.remove(f)
            except OSError:
                pass
        if HAS_CV2:
            bgr = arr[:, :, ::-1].astype(np.float32)
            if not cv2.imwrite(path, bgr):
                raise RuntimeError(f"Failed to write HDR file: {path}")
        else:
            import imageio.v3 as iio
            iio.imwrite(path, arr.astype(np.float32))
        return path

    def run(self, hdri_path, max_lights, min_ev, json_name,
            hdri_image=None, gobo_image=None, gobo_target="key"):
        if hdri_image is not None:
            # Direct tensor input from 'Exposure to HDR' (preferred)
            img = hdri_image[0].cpu().numpy().astype(np.float32)[:, :, :3]
            img = smooth_blind_spot(img)
            path = self._save_hdr(img)
        else:
            path = hdri_path.strip()
            if not path:
                path = find_latest_hdri(OUTPUT_DIR)
                if not path:
                    raise RuntimeError(
                        f"No .hdr/.exr file found in output folder: {OUTPUT_DIR}")
            if not os.path.exists(path):
                raise RuntimeError(f"HDRI file does not exist: {path}")
            img = load_hdri_file(path)
        lum = luminance(img)
        h, w = lum.shape

        peaks = find_peaks(lum, max_lights)
        lights = []
        for (u, v, _) in peaks:
            color, inten = sample_color(img, u, v)
            d = pixel_to_direction(u + 0.5, v + 0.5, w, h)
            lights.append({
                "direction": d,
                "azimuth_deg": round(math.degrees(math.atan2(d[0], d[2])), 1),
                "elevation_deg": round(math.degrees(math.asin(
                    max(-1.0, min(1.0, d[1])))), 1),
                "color": color,
                "intensity": inten,
            })

        # The chrome ball cannot see the region directly behind it
        # (azimuth near +/-180) or the extreme poles; peaks found there
        # are unwrap artifacts, not real lights.
        lights = [L for L in lights
                  if abs(L["azimuth_deg"]) <= 150.0
                  and abs(L["elevation_deg"]) <= 65.0]

        if lights:
            peak = max(L["intensity"] for L in lights)
            for L in lights:
                ratio = max(L["intensity"] / peak, 1e-8)
                L["intensity"] = float(f"{ratio:.3g}")
                L["ev"] = round(math.log2(ratio), 2)
            # adaptive count: drop peaks too dim to matter
            lights = [L for L in lights if L["ev"] >= min_ev]

        lights = label_lights(lights)

        # Gobo mask: save the IMAGE tensor as a grayscale PNG and attach it to the target light
        gobo_path = None
        if gobo_image is not None:
            arr = gobo_image[0].cpu().numpy()  # [H, W, C], 0~1
            gray = (luminance(arr) * 255.0).clip(0, 255).astype(np.uint8)
            gobo_path = os.path.join(
                get_bridge_dir(), "gobo_" + gobo_target + ".png")
            if HAS_CV2:
                cv2.imwrite(gobo_path, gray)
            else:
                from PIL import Image
                Image.fromarray(gray).save(gobo_path)
            for L in lights:
                if L["role"] == gobo_target:
                    L["gobo"] = os.path.abspath(gobo_path)
                    break

        result = {"hdri": os.path.abspath(path), "lights": lights}
        json_path = os.path.join(get_bridge_dir(), json_name)
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)

        lines = [f"HDRI: {os.path.basename(path)}",
                 f"Bridge folder: {get_bridge_dir()}"]
        for L in lights:
            d = ", ".join(f"{x:.2f}" for x in L["direction"])
            lines.append(
                f"[{L['role']}] az={L['azimuth_deg']}\u00b0 "
                f"el={L['elevation_deg']}\u00b0 {L['ev']} EV"
                + (" +gobo" if L.get("gobo") else ""))
        summary = "\n".join(lines)
        print("[ExtractLightsForC4D]\n" + summary)
        return (json_path, summary)


NODE_CLASS_MAPPINGS = {"ExtractLightsForC4D": ExtractLightsForC4D}
NODE_DISPLAY_NAME_MAPPINGS = {"ExtractLightsForC4D": "Extract Lights for C4D"}
