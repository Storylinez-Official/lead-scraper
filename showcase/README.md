# LeadScraper showcase

Scripts that capture the dashboard and build a presentation from real runs.

The generated files below are not in the repository (they show real contact details); run the steps under *Regenerating* to produce them locally.

| File | What it is |
|---|---|
| `LeadScraper-Showcase.pdf` | 19-slide deck (16:9). Present it directly or send it. |
| `LeadScraper-Showcase.pptx` | The same deck as PowerPoint, with the videos embedded on the recording slides. |
| `videos/01-dashboard-tour.mp4` | 1:32. A saved run: pipeline, leads tabs, a full dossier, a dropped lead, dark mode. |
| `videos/03-live-single-site-audit.mp4` | 1:30. Typing svix.com, pressing Audit, watching all six steps finish live. Best short demo. |
| `videos/04-live-pipeline-run-4x-speed.mp4` | 0:52. A real batch run across all three sources at 4x speed. |
| `videos/04-live-pipeline-run.mp4` | The same run in real time (about 3.5 min). |
| `videos/02-mobile.mp4` | 0:15. The dashboard at phone width. |
| `screenshots/` | Every screenshot at 2x resolution (PNG). `panels/` and `_web/` are crops and compressed copies used by the deck. |

Suggested order for a live talk: slides 1-4, play `03-live-single-site-audit.mp4`
(or run a real audit), slides 5-12, play `04-live-pipeline-run-4x-speed.mp4`, slides 13-19.

## Regenerating

With the dashboard running (`python -m leadscraper serve`):

```bash
python showcase/capture.py tour                 # screenshots + tour/mobile videos (no API cost)
python showcase/capture.py audit https://...    # live single-site audit (uses OpenAI)
python showcase/capture.py run                  # live batch run (uses OpenAI, ~3-5 min)
python showcase/build.py                        # MP4s, PDF and PPTX from the captures
```

The results slide uses the newest multi-lead run in `output/`.
