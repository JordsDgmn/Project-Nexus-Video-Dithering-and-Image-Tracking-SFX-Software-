# PROJECT NEXUS

Project Nexus is a Windows desktop app for image and object tracking in local video. Drop in a clip, tell Nexus what to follow, and watch the track before exporting it. Run offline on the target laptop, with no terminal commands in the normal workflow. Effects such as dither are optional tools that can use tracking data.

## Current state

- `track.py` runs a CPU-based OpenCV CSRT tracker and writes one CSV row per decoded frame. The CLI takes a rectangle on the first frame and records a box or a lost status. A short synthetic translation clip and simulated loss have been exercised. Accuracy and speed on representative real footage are still unmeasured.
- `nexus_app.py` and the packaged Windows executable provide drag-and-drop loading and MP4 export for whole-frame dither. The separate Project Nexus Tracking executable uses the shared CSRT core. It opens a video, accepts one on-screen box, exports a tracking-box or tracked-dither MP4 with CSV, and plays the result in the desktop window. Both modes passed the synthetic translation test. Real-footage and laptop performance verification remain pending.
- The release order below reflects current project priorities. TASKS.md and HANDOFF.md hold ownership and handoff records. Their initial implementation status predates the CLI and desktop build.

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
