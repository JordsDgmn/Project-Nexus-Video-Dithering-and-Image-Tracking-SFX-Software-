# Project : Entropy

A local Windows backdrop simulator. Choose an effect, shape the light and motion, then export a seamless MP4 loop. The application source is independent of the Nexus app.

## Use Entropy

1. Open `dist/Project Entropy Recovery.exe`.
2. Choose **Prismatic aura**, **Iridescent oil**, **Glass caustics**, or **Pool reflections**. The simulation starts immediately.
3. Use **Light** for palette, hue, spectrum width, saturation, dispersion, glow, intensity, background, and blend. Use **Motion** for scatteredness, compactness, cycles, and the repeatable seed. Scrub the timeline to inspect a still, then press **Play**.
4. Under **Export**, set the aspect, resolution, frame rate, duration, and render detail. **Estimate render time** samples the current settings before encoding. While exporting, the app measures throughput and updates its remaining-time estimate.
5. Use **Save preset** to store the look and export settings together.

## Preview and export

- **Auto** adapts the preview resolution and coalesces work when rendering takes longer than the target frame interval. **Eco** and **Sharp** set a fixed preview cap. The status below the preview shows the delivered fps, frame latency, working dimensions, and skipped preview slots.
- Export writes every frame of the loop in order, independent of preview performance. Aspect ratios are 16:9, 9:16, 1:1, 4:5, 4:3, and 21:9. Choose a 720, 1080, or 1440 px short edge and 24, 30, or 60 fps. Loops can run 1–30 seconds. Balanced and Fine limit the simulation to 960 and 1600 pixels on the long edge, then scale to the selected output. Native renders at the final dimensions.
- Exports are silent MP4s. Cancellation discards the temporary output. The app checks the size, number of frames, and opening and closing frames before publishing the file.
- The four clips in `examples` are rendered samples. The preview and export engine use seeded, CPU-based procedural light fields.

## Development

Use Python 3.12 or later on Windows with Tk available. Install `requirements.txt` in your own environment, then run `python entropy_app.py`. To build a standalone Windows executable, install PyInstaller in that environment and run `build.ps1` with `-Python` pointing to its interpreter. The packaged app does not require a Python installation.

- `entropy_engine.py` contains palettes, look and output settings, and four renderers.
- `entropy_runtime.py` manages preview buffering, video export, and presets.
- `entropy_app.py` contains the Windows interface.
- `references/stash-oil-reference.txt` is the original TSX excerpt supplied for visual reference. The Entropy engine is written separately in Python.

References used for the material and light behavior. [Stash Effects](https://stash.style/effects) · [WaterCaustics Python experiments](https://github.com/pabennett/WaterCaustics) · [Rendering Water Caustics](https://developer.nvidia.com/gpugems/gpugems/part-i-natural-effects/chapter-2-rendering-water-caustics)

## Diagnostics and recovery

The **Diagnostics** button stays compact when the app is healthy and shows the active issue count when a problem occurs. Open it for the current issue and recent session events. **Open log folder** opens the local `.entropy-data/logs` directory, including previous sessions.

If Seed or Duration is temporarily empty or invalid, Entropy keeps its last valid value for preview and continues applying other controls. Correct the highlighted field before exporting, estimating, or saving a preset.

**Restart preview** starts a fresh renderer while keeping the look and timeline. **Restart app** reopens Entropy using the last valid settings, preview quality, and timeline position. Complete or cancel an export before restarting the app.

Run the focused settings checks with `python -m unittest discover -s tests`.
