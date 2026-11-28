# Project : Entropy

A local Windows backdrop simulator. Choose an effect, shape the light and motion, then export a seamless MP4 loop. The application source is independent of the Nexus app.

## Use Entropy

1. Open `dist/Project Entropy Studio v7.exe`.
2. Choose **Prismatic aura**, **Iridescent oil**, **Glass caustics**, **Pool reflections**, **Prism refraction**, or **Cinematic bokeh**. The simulation starts immediately.
3. Use **Light** for palette, hue, spectrum width, saturation, dispersion, glow, intensity, background, and blend. Use **Motion** for scatteredness, compactness, cycles, and the repeatable seed. Scrub the timeline to inspect a still, then press **Play**.
4. Under **Export**, set the aspect, resolution, frame rate, duration, and render detail. **Estimate render time** samples the current settings before encoding. While exporting, the app measures throughput and updates its remaining-time estimate.
5. Use **Save preset** in the main toolbar to name and save the current look and export settings. Open **Presets** to reuse it.

Switching effects keeps the current Light, Motion, Rotation, Style, Textures, palette, and Export settings.
Choose **Effect defaults** to load the selected effect’s original Light and Motion values.

## Preview and export

- **Auto** adapts the preview resolution and coalesces work when rendering takes longer than the target frame interval. **Eco** and **Sharp** set a fixed preview cap. The status below the preview shows the delivered fps, frame latency, working dimensions, and skipped preview slots.
- Export writes every frame of the loop in order, independent of preview performance. Aspect ratios are 16:9, 9:16, 1:1, 4:5, 4:3, and 21:9. Choose a 720, 1080, or 1440 px short edge and 24, 30, or 60 fps. Loops can run from 1 second to 30 minutes. Pick a duration or enter whole seconds or m:ss in **Export**. Balanced and Fine limit the simulation to 960 and 1600 pixels on the long edge, then scale to the selected output. Native renders at the final dimensions.
- Exports are silent MP4s. Cancellation discards the temporary output. The app checks the size, number of frames, and opening and closing frames before publishing the file.
- The four clips in `examples` are rendered samples. The preview and export engine use seeded, CPU-based procedural light fields.

## Development

Use Python 3.12 or later on Windows with Tk available. Install `requirements.txt` in your own environment, then run `python entropy_app.py`. To build a standalone Windows executable, install PyInstaller in that environment and run `build.ps1` with `-Python` pointing to its interpreter. The packaged app does not require a Python installation.

- `entropy_engine.py` contains palettes, look and output settings, and six renderers.
- `entropy_bokeh.py` contains the procedural light field and bokeh camera.
- `entropy_style.py` and `entropy_texture.py` implement the optional style and texture stacks.
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
- **Textures → Surface** adds paper fibers, film scratches, and scanlines. Adjust fiber fineness, scratch count, and line spacing independently.
- Open **Palettes** to choose or enter up to ten ordered colors. Save them under a name to use in other simulations. The editor lets you reorder colors or load and rename a saved palette.
- Open **Presets** to save, apply, rename, or update a named look. Each preset includes the simulation, style, textures, custom colors, and export settings. JSON files remain available for transfer.
- Named palettes and presets are saved in `.entropy-data/library.sqlite3`. Rendered samples and two portable JSON presets are in `examples/textures`.

## Motion speed and rotation

**Motion → Motion speed %** sets the speed independently of the exported duration.
**Base cycles** controls how many effect cycles run at 100% during a six-second clip or a shorter clip. Longer clips repeat the same movement instead of stretching a single cycle over the entire export.

**Rotation** sets a starting angle, rotation rate in degrees per second, and clockwise or counterclockwise direction. Rotation still works when the effect motion is frozen.

**Motion → Clip timing** defaults to **Seamless clip**, which fits whole motion cycles and turns into the exported clip. The Motion and Rotation tabs show the resulting rates. **Exact speed** keeps the requested rates, so the final clip can end partway through a cycle or turn. Preview and export use the same timing.

## Style

Open **Style** and choose **Opal ribbons**, **Prism bloom**, or **Stardust** in the recipe menu for a starting point. The tabs work with every simulation.

- **Form** sets shape strength, fluidity, axis stretch, and turbulence. Turbulence detail brings out finer waves. Flow cycles controls how often the warp moves through its pattern per simulation cycle. Shuffle changes the seeded form and particle layout.
- **Particles** layers steady specks, pulsing glimmer, and star-shaped glitter. Count sets the pool of particles, with subsets used for glimmer and glitter. Size, drift, twinkle speed, and particle tint control their appearance.
- **Lens** positions a flare on the frame and adjusts its size, streaks, and optical reflections. Lens tint controls the color of the flare.
- **Strobe** applies a soft or shutter-shaped exposure pulse. It starts off and runs at one to three pulses per second when enabled, independent of the simulation and export duration.

Toggle **Enable style** to compare while keeping the sliders. Changes appear in the preview and are included in saved presets and exports. Form, particles, and animated textures reuse the motion phase, so they follow the **Seamless clip** setting.

## Cinematic bokeh camera

Choose **Cinematic bokeh**, then **Bokeh camera…** above the effect list. Start with **Cinematic camera**, **Tungsten rings**, **Festival lights**, or **Prismatic anamorphic** in the recipe menu.

- **Lights** sets arrangement, colors, count, brightness, and size range.
- **Aperture** switches between round discs, blades, and rings. It also controls blade curvature and rotation, the size of the ring opening, edge softness, rim brightness, and concentric texture.
- **Focus** controls aperture opening, near-to-far focus, depth spread, the sharp range, and an animated focus shift.
- **Movement** offers still, float, sway, dolly, and handheld motion with separate travel limits, depth parallax, and individual drift.
- **Backdrop** controls a black, solid, gradient, or hazy backdrop. Distant lights and haze can add depth to any backdrop. The backdrop color comes from **Light → Background**.
- **Lens FX** adjusts anamorphic stretch, cat-eye compression, streaks, spectral splitting, aperture fringing, flare, lens tint, and reflections. Streaks and flare follow bright lights.
- **Pulses** turns on occasional, seeded pulses in a fraction of the lights. Their pace stays tied to elapsed seconds as export duration changes. They start off in every recipe.

Camera settings survive effect changes and are saved in named and portable presets. Older bokeh presets open in **Classic** to preserve their rendering. Choose **Camera** or a recipe to start adjusting the new controls. Balanced and Fine use the working resolution listed in Export. Native renders the camera effects at the full output resolution.

### Independent lights

Choose the **Living lights** recipe or switch **Renderer** to **Independent lights** to keep your current aperture and lens settings. Separate controls appear in **Movement** and **Fades**.

- **Movement → Camera → Lock camera** is enabled by default in this renderer. It freezes the camera and focus breathing. **Rotation** remains a separate whole-frame effect.
- **Movement → Light layers** sets the path and travel limits for the bulbs. Foreground, middle, and background have separate motion and fade speeds. Set a motion speed to 0% to hold that layer in place. Set a fade speed to 0% for steady light at that depth. Distant lights follow the background speeds.
- **Fades** offers **Random fades** with staggered, varying intervals, **Swell** for eased rises and falls, **Sparks** for brief peaks, and **Rolling wave** for a sweep across the frame. Set the percentage of eligible lights, interval, variation, brightness range, and transition softness. Choose **Off** for steady lights or **Still** in Light layers to animate brightness alone.
- **Shuffle light animation** changes the timing and paths while keeping the light layout. The animation seed is saved with the preset. The same source gets the same timing when scrubbed or rendered. **Seamless clip** fits the patterns to the exported duration, and **Exact speed** keeps the requested pace.

The camera approximates depth-dependent defocus and off-axis aperture clipping. It draws on the [PBRT realistic camera model](https://pbr-book.org/3ed-2018/Camera_Models/Realistic_Cameras), the [three.js bokeh shader](https://github.com/mrdoob/three.js/blob/dev/examples/jsm/shaders/BokehShader2.js), and [Blender’s camera controls](https://docs.blender.org/manual/en/latest/render/cameras.html).

Technique references for the shared Style and Textures stacks include [TouchDesigner Noise TOP](https://derivative.ca/UserGuide/Noise_TOP) for layered roughness, [Blender Glare](https://docs.blender.org/manual/en/4.5/compositing/types/filter/glare.html) for streaks and optical reflections, and [Photoshop filter effects](https://helpx.adobe.com/photoshop/desktop/effects-filters/blur-sharpen-filters/filter-effects-reference.html) for surface treatments.
