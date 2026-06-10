# Sound Effects Plan

This quiz template should use a tight sound-effects set: loud and arcade-like for the intro/outro, then restrained during the math sections so the questions stay readable.

## Needed SFX

Place these files in `assets/sfx/`. The renderer prefers `.wav`, then `.mp3`, then `.m4a` for each cue name.

- Intro arcade hit/stinger at `0:00` for the loud title reveal.
- Small UI pops for intro chips like "3 Questions", "Timer on", and "Lock in".
- Transition whoosh/wipe at `0:02.4` into quiz mode.
- Answer choice slide-in ticks/pops as A/B/C/D appear for each question.
- Subtle countdown tick once per second.
- Urgency ticks or pulse only for the final 3 seconds of each question.
- Time-up / reveal hit when the answer reveal starts.
- Correct answer chime when the green answer appears.
- Explanation panel soft pop during each reveal.
- Transition whoosh at `0:35.45` into the recap/outro.
- Outro recap stinger at `0:36.10`.
- Recap row pops for Q1/Q2/Q3 summary rows.
- Final CTA sparkle/pop for "Replay", "Share", and "Review".

```text
intro_stinger.wav
ui_pop.wav
transition_whoosh.wav
choice_pop.wav
countdown_tick.wav
urgency_tick.wav
reveal_hit.wav
correct_chime.wav
explanation_pop.wav
outro_stinger.wav
recap_pop.wav
cta_pop.wav
```

## Current Cue Times

These timings come from the current render script and `data/mcr3u-quiz-001.json`.

```text
0:00    Intro stinger
2.40    Transition to quiz
3.05    Q1 starts
9.05    Q1 reveal
12.85   Q2 starts
20.85   Q2 reveal
24.65   Q3 starts
31.65   Q3 reveal
35.45   Transition to outro
36.10   Outro/recap starts
41.70   End
```

## Direction

Avoid heavy arcade noise during the actual math sections. The visual style guide keeps the quiz portion calm and focused, so sound should follow the same split: energetic bookends, clean transitions, subtle timer feedback, and clear answer-reveal confirmation.
