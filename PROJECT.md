# PROJECT NEXUS

Project Nexus is a Windows desktop app for image and object tracking in local video. Drop in a clip, tell Nexus what to follow, and watch the track before exporting it. Run offline on the target laptop, with no terminal commands in the normal workflow. Effects such as dither are optional tools that can use tracking data.

## Current state

- `track.py` runs a CPU-based OpenCV CSRT tracker and writes one CSV row per decoded frame. The CLI takes a rectangle on the first frame and records a box or a lost status. A short synthetic translation clip and simulated loss have been exercised. Accuracy and speed on representative real footage are still unmeasured.
- `nexus_app.py` and the packaged Windows executable provide drag-and-drop loading and MP4 export for whole-frame dither. The separate Project Nexus Tracking executable uses the shared CSRT core. It opens a video, accepts one on-screen box, exports a tracking-box or tracked-dither MP4 with CSV, and plays the result in the desktop window. Both modes passed the synthetic translation test. Real-footage and laptop performance verification remain pending.
- The release order below reflects current project priorities. TASKS.md and HANDOFF.md hold ownership and handoff records. Their initial implementation status predates the CLI and desktop build.

### Live Studio build

Open `.nexus-runtime/release/Project Nexus Live Studio.exe` and use **Save preset…** or **Load preset…** below the preview. The preset folder starts with **softdots-bright-halftone**, using all four Soft Dots tabs from the supplied screenshots. Presets store the look, style settings, tracking mode, output size, and preview quality. The source video, timeline position, and per-clip tracking selection are picked for each job. Image overlay presets reference the image file.

Nexus offers to save changes before replacing an edited style. **Cancel** keeps the current look and settings. Soft Dots and tracking controls refresh the current frame and also work during **Play preview**. **Preview quality** offers Auto, Performance, Balanced, and High. Auto adapts the working resolution during playback. The size under **Advanced → Presets & export** controls the exported video separately.

### Tracking Lab build

Open `Project Nexus Tracking Lab.exe` for **Clean blobs**, **Line network**, **Motion vectors**, **Word scatter**, and **ASCII texture**. The first four draw graphics over the original footage. Soft Dots and the earlier looks remain in the Look menu. The new build starts with Clean blobs.

**Live controls** groups detection, marks and links, text, and ASCII. Adjust the detector, threshold, detection interval, target count, and spacing while playing or paused. Contour-based detectors offer motion, bright, and dark blobs, with area filtering. Features use a relative corner-strength threshold. Mark and link styling updates without reseeding the active track. Detection changes can re-seed IDs.

Paste any text under **Text** and split it into lines, words, or phrases. Labels are assigned by track ID and skip overlaps. Control format, font, color, density, and whether each mark is a shape, text, both, or neither. **ASCII texture** provides a custom glyph ramp, size, color, backdrop, and optional ordered dithering. ASCII without tracking marks exports just the MP4. Visual controls and pasted text are saved with Nexus presets.

All four detectors and five new looks were tested separately. The 540×960 synthetic demo exported all 72 frames in each mode. Demo exports and an example custom-text preset live in `.nexus-runtime/tracking-lab-demo`. For the detection controls, see [TouchDesigner's Blob Track TOP guide](https://derivative.ca/UserGuide/Blob_Track_TOP).

### Soft Dots build

`Project Nexus Soft Dots.exe` opens with **Soft Dots**, a full-frame halftone based on the supplied clip and screenshot settings. It uses a stable grid of source-colored, brightness-sized circles over a blurred image. At 2560 × 1440 the supplied export measured 13.21 px horizontally and 21.96 px vertically. The Nexus preset measured 13.19 px and 22.02 px on a clean swatch at that size.

The **Dots settings** window groups dot size, blend, opacity, coverage and grid, backdrop mode and softness, tone and final blur, and color and tint. **Reset to reference** restores the visible settings from the screenshots. **Presets & export** can save variations. The demo and reusable preset are in `.nexus-runtime/dots-demo`.

The effect applies directly to any supported clip and produces a silent MP4. **Dots only** composites over black for MP4. The pre-effect version of the supplied video was unavailable, so the measured grid and visible settings were matched independently. The reference is an output from [ASCII Magic’s Dots style](https://www.ascii-magic.com/docs/styles).

### Timeline and Inspector build

- **Advanced → Tracking & motion** controls automatic tracking response, animation speed, and the box range. The minimum is a search target based on available picture detail. The maximum is a firm cap. Setting animation speed to zero freezes the time-driven graphics while tracking continues. **Layers** holds scene switches and styling. **Presets & export** holds saved looks and output sizes.
- The main timeline previews the selected frame before export. **Original** compares it with the source at the same point. **First frame** returns to the start for manual target selection. Automatic seeks initialize tracking near the selected frame for speed, so exact IDs can differ from the sequential export. Manual tracking may need to process intervening frames, and the app shows buffering progress.
- **Inspector** shows video metadata, Windows hardware, and live resource samples. GPU engine load appears when Windows exposes the relevant counters. Render throughput and ETA come from processed frames and appeared in testing. Exports retain the existing silent MP4 and CSV formats.

### Auto Looks build

The Windows executable is `.nexus-runtime/release/Project Nexus Auto Looks.exe`. Drop a clip, choose a look, preview the first four seconds, and export. Advanced opens output size, opacity, detail, tint, presets, and the existing subject and surface tools.

- CCTV collage uses tracking chips, crop insets, and a viewfinder. Signal web adds curved links, trails, and coordinate labels. Amber archive has a warm grade, grain, and dashed connections. Thermal scan uses a blue luminance palette. Poetic traces uses a green grade, linked marks, and original short phrases.
- Automatic looks use persistent IDs on image features and track them with optical flow. Labels and box sizes are part of the design. Thermal labels report image luminance. The automatic CSV stores source-pixel centers and a visual radius, plus the stable ID.
- Tests on a generated 540×960, 72-frame clip held 27–49 IDs from beginning to end. All five modes exported successfully at 44–77 fps on that clip. The planar regression and automatic UI export also passed. Results vary with motion and source resolution.
- Visual references were supplied in chat. Technique references include [Derivative's Blob Track TOP](https://docs.derivative.ca/Blob_Track_TOP) and [Xtal's edge and blob tracking project](https://www.patreon.com/Xtalcalx/posts/project-file-toe-140808783).

### Effect Studio build

- Subject box uses CPU CSRT. Surface corners uses optical flow and a perspective transform. Select four corners clockwise from the top left on a textured flat surface. Right-click to undo the last corner.
- Tracking outline, Ordered dither, Pixel mosaic, Signal grid, and Image overlay can run against either type of track. Set opacity, detail size, and tint, or use a preset. PNG overlays can carry transparency. Image Overlay presets save a reference to the chosen image, so keep it at that location or choose it again after moving the preset. Presets omit the source clip and selection.
- Preview look shows the first-frame styling. Track & export produces a silent MP4 and a CSV in source-frame coordinates. Surface CSVs include four corner positions. Full size, Compact at 75%, and Small at 50% control output dimensions while retaining frame rate. The original stays intact. A lost surface stays lost for the rest of that run. There is no automatic reacquisition yet.
- The release artifact is `.nexus-runtime/release/Project Nexus Studio.exe`. The sample clip, overlay, and exports are in `.nexus-runtime/studio-demo`.

### Synthetic benchmark on the target laptop

| Run | Processing speed | Export size |
| --- | --- | --- |
| 720p planar Signal grid, Full | 44.8 fps | 1,808,182 bytes |
| 720p planar Signal grid, Compact | 55.3 fps | 1,259,492 bytes |
| 720p planar Signal grid, Small | 70.6 fps | 545,570 bytes |
| 1080p subject Ordered dither, Full | 7.4 fps | 8,377,080 bytes |
| 1080p planar Image overlay, Compact | 30.1 fps | 574,241 bytes |

The 720p planar test tracked all 36 frames, with median corner error of 0.29 px and maximum error of 4.62 px. On the 1080p test, CSRT decode and tracking took 2.8 fps at native resolution and 9.6 fps with the Studio's smaller working image. The maximum difference in box centers between those runs was 6.0 px. These are single-run results on synthetic clips. Real footage, long clips, and peak memory still need verification.

## Release 1 — Track a region in the Windows app

1. Make **Track** the primary workflow. Let the user drop or browse for a clip, view the first frame, and draw a box around the target once. Convert preview coordinates to source pixels, including when the preview is scaled or letterboxed.
2. Run the existing CSRT baseline automatically after the user starts tracking. Keep the UI responsive and provide progress and cancellation. Retain the existing CLI as a development and batch entry point.
3. Show a playable review with the tracking box over the original video. Mark lost frames clearly, and make it easy to find and inspect them.
4. Export a tracked preview and a CSV with frame index, status, and box coordinates. Leave the source untouched. Handle invalid inputs and output collisions clearly, and avoid publishing partial exports.
5. Package a Windows executable and verify the complete workflow on the target laptop. Test translation and scaling on synthetic ground truth and exercise representative real clips with camera motion, blur, occlusion, and targets leaving the frame. Record overlap error, loss and drift, processing speed, and peak memory at 720p and 1080p. Use the measurements to set realistic targets.

Release 1 is complete when the user can open the executable, drop in a clip, draw one box, see what the tracker followed and where it lost the target, and export the result without using a terminal.

## Later releases

| Priority | What the user can do | Scope |
| --- | --- | --- |
| 2. Correct and recover tracks | Scrub to a frame, redraw the target, and continue tracking. | Add starting from a later frame and manual re-seeding first. Evaluate reacquisition after occlusion and visibly flag uncertain matches. |
| 3. Track a supplied reference image | Drop in a reference image such as a logo alongside the clip. Nexus locates matching appearances and tracks from a verified match. | Start with conventional OpenCV matching. Evaluate automatic target suggestions separately for clips without a supplied reference. |
| 4. Attach graphics and effects | Pin an image, label, blur, or dither effect to a track. | Store position and scale first. Add rotation and planar corner tracking for signs, screens, and other flat surfaces. Define what happens to overlays when the track is lost. |
| 5. Extend tracking | Follow several targets or use a mask that follows an object's outline. | Add multiple tracks and assess optional AI for detection, re-identification, and segmentation after measuring the baseline and its limitations. |

## Target machine and constraints

Windows laptop with an Intel Core i5-11400H, 24 GB RAM, and NVIDIA RTX 3050 with 4 GB VRAM. Keep the baseline CPU-first and stream frames to control memory use. The packaged tracking workflow should run offline without model downloads or CUDA. Use GPU or AI features only if they materially improve tracking and fit the laptop.
