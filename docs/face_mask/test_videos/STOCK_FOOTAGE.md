# Stock footage option

Use only footage whose individual license page permits downloading, editing, and this private/local test use. Check the license page for every chosen clip and record the title, author, source URL, and license in `clips/ATTRIBUTION.md`. Do not scrape or bulk-download.

Good places to search are the official free-media pages for [Pexels](https://www.pexels.com/license/), [Pixabay](https://pixabay.com/service/license-summary/), and [Mixkit](https://mixkit.co/license/). I checked those official license pages on 2026-11-11: Pexels permits free use and modification with no attribution required; Pixabay permits free use and adaptation subject to its prohibited-use and third-party-rights conditions; Mixkit has separate Free and Restricted stock-video licenses, so choose only an item marked **Stock Video Free License** (the [specific Free License terms](https://mixkit.co/license/modal/videoFree/) permit modification and distribution). Their terms and individual asset availability can change, so check the current license page and the individual asset page at download time; do not assume a search result is licensed merely because it appears in a search engine.

Suggested searches, one real clip per file:

| Filename | Search terms |
|---|---|
| `01_normal_a.mp4` | `person walking toward camera hallway`, `office entrance person walking` |
| `02_normal_b.mp4` | `woman walking corridor toward camera`, `man entering building hallway` |
| `03_normal_c.mp4` | `person walking indoor doorway face visible` |
| `04_mask_a.mp4` | `woman surgical mask walking corridor`, `person face mask walking toward camera` |
| `05_mask_b.mp4` | `man wearing cloth mask walking indoors` |
| `06_mask_c.mp4` | `person wearing face mask entrance camera` |
| `07_helmet.mp4` | `person wearing helmet walking indoors`, `helmeted person walking toward camera` |
| `08_mask_d.mp4` | `person wearing surgical mask walking toward camera` |
| `09_kerchief.mp4` | `person scarf covering face walking`, `kerchief over face walking` |
| `10_group_mask.mp4` | `group of people wearing face masks walking`, `masked group entering building` |

The stock clip must show the person approaching the camera, not a side profile or a distant crowd. Prefer clips with an overhead/high-angle hallway view and a face/head large enough to be about 80 px or more after 1280x720 letterboxing. Do not add captions, logos, or other people-like graphics to the downloaded footage.

There is intentionally no downloader in this repository. If you later provide a Pexels API key as the process environment variable `PEXELS_API_KEY`, an official-API downloader can be added separately; the key must never be printed or stored in the repository. This task does not use or inspect that variable.
