# MCR3U Quiz Video

Reusable local video template for Instagram-style MCR3U multiple-choice quizzes.

Visual direction lives in `STYLE_GUIDE.md`. The renderer uses one theatre-marquee stage style across the intro, quiz, answer reveals, and conclusion. During active quiz questions, the background lights stay still and the countdown is the only time-based visual element.

## Workflow

1. Edit or duplicate `data/mcr3u-quiz-001.json`.
2. Run `npm run render` to export `out/mcr3u-quiz-001.mp4`.
3. For another video, pass a different JSON file:

```bash
python3 scripts/render_quiz.py data/mcr3u-quiz-002.json out/mcr3u-quiz-002.mp4
```

Each quiz has 3 questions. Every question controls its own countdown with `timeLimitSeconds`, so harder questions can run longer.

## Sound Effects

Sound effects are optional. Add audio files to `assets/sfx/` using the cue filenames listed in `assets/sfx/README.md`, then run the normal render command. Missing sound files are reported as warnings and skipped, so the video still renders without a complete SFX set.

## Math Formatting

Write all math in LaTeX-style `$...$` notation inside the quiz JSON:

```json
"prompt": "If $f(x)=2x-5$, what is $f(7)$?"
```

The renderer uses Matplotlib mathtext to draw LaTeX-style expressions, so choices and explanations can also contain math:

```json
"choices": ["$\\left(0,0\\right)$", "$\\left(0,2\\right)$", "$\\left(0,3\\right)$", "$\\left(3,0\\right)$"]
```

## Requirements

No account and no npm packages are required.

- Python 3 with Pillow
- Matplotlib
- FFmpeg
- Optional: Node/npm, only if you want to use the `npm run ...` shortcuts

## Commands

```bash
npm run render
npm run preview:frame
npm run check
```

Without npm, use:

```bash
python scripts/render_quiz.py data/mcr3u-quiz-001.json out/mcr3u-quiz-001.mp4
python scripts/render_quiz.py data/mcr3u-quiz-001.json out/style-preview.png --frame 330
python -m py_compile scripts/render_quiz.py
```

The video is `1080x1920`, 30 fps, and designed for Instagram Reels safe areas. The renderer uses local Python/Pillow frames plus FFmpeg encoding for text, boxes, countdown screens, and answer reveals.
