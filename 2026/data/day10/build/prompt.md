# The prompt

Asked of: Claude, model Opus 5.5 (`claude-opus-5-5`)
Asked on: 1 November 2026
Rules: no tools, no web, no map data, no station lists. Memory only. The answer is saved
verbatim and never corrected afterwards.

---

Draw Singapore from memory.

Without looking anything up, answer with one JSON object that holds:

1. **The main island.** Singapore's main-island coastline as one closed polygon of about
   40 to 80 vertices, each as `[longitude, latitude]` in WGS84 degrees, going
   anticlockwise.
2. **Four smaller islands.** Sentosa, Pulau Ubin, Pulau Tekong and Jurong Island, each as
   a closed polygon in the same format.
3. **Every MRT and LRT station you can recall** that is open today, each with its name,
   its line code or codes (for example `NS1`, `EW24`) and its position as
   `[longitude, latitude]`.
4. **Each line's station order**, from one end to the other (or round the loop).

Give your best guess even when unsure. Leave out what you cannot recall rather than
padding. Mistakes are welcome; they are the point.
