# Face Mask entrance test — shot list

This test is assembled from real short clips. Do not draw or generate people: the Face Mask detectors need real human appearance.

## Camera setup

- Put the phone high above head height, looking down a hallway or doorway like an overhead CCTV camera. Keep the camera steady.
- Start each person 2–4 m away. Use a plain corridor/background and bright, even light without a window directly behind the person.
- Film landscape at 1080p or better. Keep the face large in frame; at the final 720p output the head should be at least about 80 px tall.
- Have each individual walk straight toward the camera at normal speed for about 8 seconds, then stop outside the frame. Leave 3–4 seconds of empty hallway between groups when filming a continuous reference, but the assembler adds those gaps itself.
- Film only people who have agreed. Do not publish the clips; keep them in the local `backend/use_cases/face_mask/clips` folder.

## Files to record

| Filename | Person/action | Expected result |
|---|---|---|
| `01_normal_a.mp4` | Normal face, person A | Visible, no alert |
| `02_normal_b.mp4` | Normal face, person B | Visible, no alert |
| `03_normal_c.mp4` | Normal face, person C | Visible, no alert |
| `04_mask_a.mp4` | Surgical or cloth mask covering nose and mouth | Concealed, alert |
| `05_mask_b.mp4` | Surgical or cloth mask covering nose and mouth | Concealed, alert |
| `06_mask_c.mp4` | Surgical or cloth mask covering nose and mouth | Concealed, alert |
| `07_helmet.mp4` | Helmet obscuring the face | Concealed, alert; helmet |
| `08_mask_d.mp4` | Surgical or cloth mask | Concealed, alert; mask |
| `09_kerchief.mp4` | Kerchief/scarf/cloth over nose and mouth | Concealed, alert; scarf/kerchief |
| `10_group_mask.mp4` | Three or four people walking in together, all masked | One alert per person/track |

Optional, clearly separated from the required scenario:

- `11_sunglasses.mp4`: sunglasses only; expected Visible and no alert.
- `12_cap_down.mp4`: cap pulled low while looking down; expected Concealed and an alert.

## Assemble

From `backend/use_cases/face_mask`, place the files in `clips/` and run:

```powershell
uv run --with imageio-ffmpeg python tools/make_test_video.py --dry-run
uv run --with imageio-ffmpeg python tools/make_test_video.py
```

Use `clips/clips.yaml` to trim a clip, for example:

```yaml
clips:
  04_mask_a.mp4:
    start: 1.5
    end: 9.5
    head_height_px: 105
```

