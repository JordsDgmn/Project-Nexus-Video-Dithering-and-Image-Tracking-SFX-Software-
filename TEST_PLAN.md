# Tracking test plan

Run on Windows with the selected Python and OpenCV versions. Record versions, input codec, resolution, frame count, command, and results. Use generated clips with known box coordinates.

| Case | Expected result |
| --- | --- |
| Static target and first-frame initialization | Row zero records the initial box and the output has one row per decoded frame. |
| Textured target translating across the frame | Compare with known boxes using intersection-over-union. Report the distribution and lost-frame count before agreeing on an accuracy threshold. |
| Fast movement, occlusion, and target leaving frame | Record drift and loss behavior. Separately simulate a tracker failure to verify lost status and blank coordinates regardless of how the real tracker behaves. |
| Missing, unsupported, and corrupt video | Opening or decoding zero frames fails clearly. Document how the selected backend handles mid-stream corruption. |
| Invalid box and unusable output path | Return a nonzero exit code and preserve the source and existing destination on failure. |
| Paths with spaces and Unicode | Verify local input and output work with quoted Windows paths. |
| Offline run at 720p and 1080p | Check without network or CUDA and record throughput and peak process memory. |

Use a temporary output next to the final CSV and verify final output is only published on success.
