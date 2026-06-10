# Sound Effects Assets

Drop sound-effect files in this folder before rendering. The renderer looks for each cue name in this order:

1. `.wav`
2. `.mp3`
3. `.m4a`

## Supported Filenames

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

If a file is missing, rendering continues and that cue is skipped.
