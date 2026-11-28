# Project : Entropy

A local Windows backdrop simulator. Choose an effect, shape the light and motion, then export a seamless MP4 loop. The application source is independent of the Nexus app.

## Use Entropy

1. Open `dist/Project Entropy Studio v4.exe`.
2. Choose **Prismatic aura**, **Iridescent oil**, **Glass caustics**, **Pool reflections**, **Prism refraction**, or **Cinematic bokeh**. The simulation starts immediately.
3. Use **Light** for palette, hue, spectrum width, saturation, dispersion, glow, intensity, background, and blend. Use **Motion** for scatteredness, compactness, cycles, and the repeatable seed. Scrub the timeline to inspect a still, then press **Play**.
4. Under **Export**, set the aspect, resolution, frame rate, duration, and render detail. **Estimate render time** samples the current settings before encoding. While exporting, the app measures throughput and updates its remaining-time estimate.
5. Use **Save preset** in the main toolbar to name and save the current look and export settings. Open **Presets** to reuse it.

Switching effects keeps the current Light, Motion, Texture, palette, and Export settings.
Choose **Effect defaults** to load the selected effect’s original Light and Motion values.

## Preview and export

- **Auto** adapts the preview resolution and coalesces work when rendering takes longer than the target frame interval. **Eco** and **Sharp** set a fixed preview cap. The status below the preview shows the delivered fps, frame latency, working dimensions, and skipped preview slots.
- Export writes every frame of the loop in order, independent of preview performance. Aspect ratios are 16:9, 9:16, 1:1, 4:5, 4:3, and 21:9. Choose a 720, 1080, or 1440 px short edge and 24, 30, or 60 fps. Loops can run from 1 second to 30 minutes. Pick a duration or enter whole seconds or m:ss in **Export**. Balanced and Fine limit the simulation to 960 and 1600 pixels on the long edge, then scale to the selected output. Native renders at the final dimensions.
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

## Textures, palettes, and named presets

- Choose **Prism refraction** for overlapping spectral facets or **Cinematic bokeh** for drifting circles with depth and soft edges. The six built-in simulations all support custom palettes and texture layers.
- Open **Textures** to adjust grain, halftone patterns, distortion, ripples, color separation, tattered edges, vignette, and posterization. **Film wear**, **Ink print**, and **Broken glass** are editable starting combinations. Toggle **Enable textures** to compare with the untextured simulation while keeping the sliders. Textures are applied in a fixed order and use the same loop phase as the simulation. Tattered edges reveal the selected background color.
- Open **Palettes** to choose or enter up to ten ordered colors. Save them under a name to use in other simulations. The editor lets you reorder colors or load and rename a saved palette.
- Open **Presets** to save, apply, rename, or update a named look. Each preset includes the simulation, texture stack, custom colors, and export settings. JSON files remain available for transfer.
- Named palettes and presets are saved in `.entropy-data/library.sqlite3`. Rendered samples and two portable JSON presets are in `examples/textures`.

## Motion speed and rotation

**Motion → Motion speed %** sets the speed independently of the exported duration.
**Base cycles** controls how many effect cycles run at 100% during a six-second clip or a shorter clip. Longer clips repeat the same movement instead of stretching a single cycle over the entire export.

**Rotation** sets a starting angle, rotation rate in degrees per second, and clockwise or counterclockwise direction. Rotation still works when the effect motion is frozen.

**Motion → Clip timing** defaults to **Seamless clip**, which fits whole motion cycles and turns into the exported clip. The Motion and Rotation tabs show the resulting rates. **Exact speed** keeps the requested rates, so the final clip can end partway through a cycle or turn. Preview and export use the same timing.
