# PROJECT NEXUS

Build a Windows-first, offline Python CLI for video effects. The first milestone is tracking one user-selected region in a local video. The baseline uses conventional OpenCV on CPU. AI acceleration and models can be evaluated after the baseline. GUI, browser interfaces, and hosting are outside this scope.

## First milestone

- Accept a local video path, an initial bounding box specified as x y width height on the first decoded frame, and a local output path.
- Decode frames sequentially and initialize a conventional OpenCV tracker, with CSRT as the initial candidate. Confirm tracker availability in the selected OpenCV build.
- Produce a CSV row for every decoded frame. Use zero-based frame indices, a status of tracked or lost, and pixel coordinates in source-frame space. Use empty coordinate fields for lost frames. Define frame coordinates with a top-left origin.
- Reject invalid or out-of-frame boxes and unreadable inputs with clear errors and a nonzero exit code. Keep the source intact and reject output paths that alias it. Publish the final CSV only after processing succeeds.
- Explicitly mark tracker failures. Automatic reacquisition and mandatory preview rendering are deferred.

## Target machine

Intel Core i5-11400H, 24 GB RAM, NVIDIA RTX 3050 with 4 GB VRAM. Keep processing streaming and measure CPU throughput and peak memory on representative 720p and 1080p footage before setting performance targets. The baseline must run without CUDA, network access, or model downloads once dependencies are installed.
