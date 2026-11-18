# Storefront footage: reviewed coverage cases

Source: `storage/sample_videos/uhd_30fps 1.mp4`. Times are approximate video seconds, not wall-clock times. These observations are calibration targets, not model training or verified automatic classifications.

| Time | Visible observation | Expected safe behavior | Current result |
| --- | --- | --- | --- |
| 1.5–2.3 s | Two people enter. The nearer person wears a purple cap and is mostly in profile; no mask can be verified in these frames. | Track both people. Do not infer a mask from a cap alone. Assess coverage only if facial parts become visible. | Both tracked; quality gate reports turned-away or low-resolution. |
| 5.5–8 s | Green-cap person at the left wears a blue mask. | Full-covering event with a box on that person and evidence from the same frame. | One full-covering event on the whole-frame replay; saved evidence reports verification IoU 1.0. |
| 10–12.5 s | Long-haired person approaches and enters the door. Hair and rear-facing pose hide most of the face. | Track the person; report unable to assess unless a usable view establishes which facial regions are covered. Hair alone must not prove partial coverage. | Tracked but not classified. |
| 17.5–18.5 s | Person exits wearing a visible blue mask, predominantly in side profile. | Detect and assess the mask if a validated profile-capable face/covering model can do so; otherwise mark unable to assess, not visible. | Person tracked around 18–19 s; quality gate reports turned-away; no event. |

Diagnostic checks on cropped frames at 1.5, 10.5, 17.5 and 18.5 s: the current YuNet detector returned no faces at its configured 0.60 confidence, and also returned none at 0.20. The heuristic analyzer without pose returned `UNABLE` on all four crops. Lowering the yaw gate alone will not recover the exiting person's mask. These cases need a validated side-profile/occlusion classifier and more representative labeled frames before alert thresholds are changed. Do not weaken the existing rule that an unassessable face cannot produce a concealment alert.
