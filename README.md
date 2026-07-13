# ComfyUI → Cinema 4D Lighting Bridge

Turn any image into a full **Redshift lighting setup in Cinema 4D** — automatically.

Give it a reference photo (or a text prompt), and within seconds your C4D scene gets:
- A **dome light** with an HDRI extracted from the image (via [DiffusionLight](https://diffusionlight.github.io/))
- Individual **area lights** (key / rim / fill / subs) decomposed from that HDRI, with correct direction, color, and relative intensity (EV)
- Optional **gobo masks** on any light for patterned shadows (blinds, foliage, window frames)

Run the workflow with C4D open, and the scene rebuilds itself live — perfect with Redshift IPR running.

## How it works

```
image ─► DiffusionLight (chrome ball inpainting, 3 exposures)
      ─► HDRI ─► light peak extraction ─► lights.json
      ─► C4D plugin watches the file ─► scene built automatically
```

The ComfyUI node and the C4D plugin share a fixed rendezvous folder
(`Documents/C4D_Lighting_Bridge/`), so **no path configuration is needed**.

## Installation

### 1. ComfyUI side

1. Install this node pack via **ComfyUI Manager** (search `C4D Lighting Bridge`),
   or clone it into `ComfyUI/custom_nodes/`:
   ```
   git clone https://github.com/othlab/comfyui-c4d-lighting
   ```
2. Restart ComfyUI.
3. Open one of the bundled workflows (drag onto the canvas):
   - `workflows/c4d_lighting_analyze_reference_image.json` — analyze your own photo
   - `workflows/c4d_lighting_generate_from_prompt.json` — generate a scene with SDXL first
4. The **Workflow Overview → Errors** panel will list missing node packs and models:
   - Click **Install All** for the node packs, restart when prompted
   - Click **Download** on each missing model (download buttons are embedded)
   - The Geowizard depth model (~4.7 GB) downloads automatically on first run

### 2. Cinema 4D side

1. Copy `c4d_plugin/c4d_lighting_bridge.pyp` into your C4D plugins folder
   (*Edit → Preferences → Open Preferences Folder → `plugins`*)
2. Restart C4D. The console should show:
   ```
   [Lighting Bridge] Watching: C:\Users\you\Documents\C4D_Lighting_Bridge\lights.json
   ```

That's it. No paths to edit.

## Usage

1. Keep C4D open (ideally with Redshift IPR running)
2. In ComfyUI: load your reference image (or edit the scene prompt) → **Run**
3. Seconds later, a `Lighting_From_Reference` group appears in C4D:
   dome + area lights + a hero sphere for previewing

Each extracted light is logged with its angles and exposure:

```
[key] az=136.2° el=38.5° 0.0 EV
[rim] az=-42.1° el=12.3° -3.2 EV
[sub] az=95.0° el=61.8° -5.7 EV
```

### Node parameters (`Extract Lights for C4D`)

| Parameter | Default | Meaning |
|---|---|---|
| `max_lights` | 6 | Upper limit of extracted lights |
| `min_ev` | -8.0 | Discard lights dimmer than the key by this many stops (adaptive count) |
| `gobo_image` | — | Optional B/W mask applied to `gobo_target`'s light texture slot |
| `hdri_image` | — | Connect `Exposure to HDR → hrd_image` here (already wired in bundled workflows) |

### Plugin settings (top of the `.pyp` file)

| Constant | Default | Meaning |
|---|---|---|
| `CUSTOM_WATCH_FILE` | "" | Override the rendezvous path if you need to |
| `AUTO_CLEAR` | True | Replace the previous lighting group on each run |
| `BUILD_SET` | True | Also create the preview sphere |
| `LIGHT_DISTANCE`, `BASE_INTENSITY`, `ROLE_SETTINGS` | — | Tune light placement/size/intensity |

## Requirements

- ComfyUI (desktop or standalone), ~12 GB VRAM recommended
- Cinema 4D 2024+ with Redshift
- Node packs (auto-installed via Manager): ComfyUI-DiffusionLight, ComfyUI-Geowizard,
  KJNodes, comfyui_essentials, FizzNodes, Advanced-ControlNet, VideoHelperSuite

## Troubleshooting

- **Nothing happens in C4D** → check the C4D console for the `Watching:` line; the plugin
  only reacts to files updated *after* C4D started, so re-run the workflow (change the seed
  to bypass caching)
- **Lights created as point lights / parameter warnings** → your Redshift version uses
  different parameter symbols; open an issue with your C4D console output
- **Geowizard "no file named diffusion_pytorch_model.bin"** → a previous auto-download was
  interrupted; delete `ComfyUI/models/diffusers/geowizard` and run again
- **BatchPromptSchedule type errors** → FizzNodes changed its widget layout across versions;
  use the bundled workflows, which are aligned with the current version

## Credits

- [DiffusionLight](https://diffusionlight.github.io/) — Phongthawee et al., CVPR 2024
- [ComfyUI-DiffusionLight](https://github.com/kijai/ComfyUI-DiffusionLight) and
  [ComfyUI-Geowizard](https://github.com/kijai/ComfyUI-Geowizard) by kijai
- [GeoWizard](https://github.com/fuxiao0719/GeoWizard) — Fu et al.

MIT License
