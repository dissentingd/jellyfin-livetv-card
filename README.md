# jellyfin-livetv-card

Generates a library card image for Jellyfin's **Live TV** view that matches
the auto-generated cards Jellyfin builds for every other library (Movies,
Shows, Collections, etc.) — then uploads it straight to your server. No
plugin, no manual image editing.

## Why this exists

Jellyfin automatically builds a nice card image for every library — except
Live TV. That's not a bug you can fix in settings: Jellyfin's own card
generator ([`CollectionFolderImageProvider`][provider]) only runs for
`CollectionFolder`-type libraries, and Live TV is a different item type
(`UserView`) that provider explicitly excludes. Confirmed straight from
Jellyfin's own source, not guessed — there's no setting, plugin, or refresh
that turns this on. Live TV is stuck with the generic default icon forever.

This script closes that gap. It reimplements the exact algorithm Jellyfin
uses for every other card ([`StripCollageBuilder.BuildThumbCollageBitmap`][builder]
— same 960×540 canvas, same semi-transparent black scrim, same centered
bold-text sizing logic) using a photo you provide (or the bundled default),
then uploads the result with Jellyfin's own public REST API
(`POST /Items/{id}/Images/Primary`) — the same endpoint Jellyfin itself uses
to save any item's image. That upload API is real, documented, and requires
nothing beyond an admin API key; only the *pixel generation* step needed
reimplementing, since Jellyfin never runs it for this item type at all.

[provider]: https://github.com/jellyfin/jellyfin/blob/master/Emby.Server.Implementations/Images/CollectionFolderImageProvider.cs
[builder]: https://github.com/jellyfin/jellyfin/blob/master/src/Jellyfin.Drawing.Skia/StripCollageBuilder.cs

## Setup

1. **Clone this repo** somewhere convenient — your Jellyfin server itself,
   or any machine that can reach it over the network. It doesn't need to run
   *inside* Jellyfin's own process or container; it just needs network
   access to your server's API.

2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Get an admin API key**: Jellyfin Dashboard → API Keys → `+` (the `+`
   button in the top-right) → give it a name → copy the key.

4. **Configure it** — copy `.env.example` to `.env` and fill in your server
   URL and the API key from step 3:
   ```bash
   cp .env.example .env
   ```
   (Or just export `JELLYFIN_URL` / `JELLYFIN_API_KEY` as real environment
   variables instead, if you'd rather not use a `.env` file — either works.)

5. **(Optional) Provide your own photo** — drop a 16:9-ish photo into this
   directory named `source_image.jpg` (or `.jpeg`/`.png`). If you skip this,
   the bundled default (a real, CC0-licensed broadcast studio photo, see
   [Credits](#credits)) is used instead. Anything roughly 16:9 works best;
   other aspect ratios get center-cropped to fit.

## Usage

```bash
python3 generate_livetv_card.py
```

That's it. The script finds your Live TV library automatically, builds the
card, and uploads it. Refresh Jellyfin's home screen (a hard refresh —
Ctrl+Shift+R — if you don't see it update right away; Jellyfin's web client
caches page content more aggressively than a plain reload accounts for) and
the new card should be there.

Want to preview the result first without touching your server at all?
```bash
python3 generate_livetv_card.py --dry-run
```
This saves `output_card.png` in this directory instead of uploading it.

### Changing the overlay text

Set `LIBRARY_NAME` (in `.env` or as an environment variable) if you've
renamed your Live TV library to something other than "Live TV", or want
different text entirely.

### Using this for a different unsupported library

Jellyfin's exclusion isn't specific to Live TV — anything that's a
`UserView` rather than a `CollectionFolder` gets skipped the same way. If you
have another such library, `--collection-type <value>` targets it instead of
`livetv` (whatever value Jellyfin itself uses for that library's
`CollectionType`).

## How it works, briefly

1. Loads your source photo (or the bundled default).
2. Resizes/center-crops it to fill a 960×540 canvas — the exact size
   Jellyfin uses for every library's card image.
3. Applies a flat black overlay at 47% opacity (`0x78`/255 — Jellyfin's own
   constant, not an approximation) so the text stays readable regardless of
   the photo underneath.
4. Draws the library name in bold white text, starting at a 112px font size
   and scaling down if it would overflow 95% of the canvas width — matching
   Jellyfin's own overflow-handling rule exactly.
5. Looks up your Live TV library's real item ID (Live TV doesn't show up in
   the normal library list, since it's a virtual view — this walks an admin
   user's actual `/Views` to find it) and uploads the finished PNG as that
   item's Primary image.

## Credits

- **Default background photo**: sourced from a CC0 (public domain)
  broadcast-studio photo. Replacing it with your own photo is easy (see
  Setup step 5) but never required — the bundled default works out of the
  box.
- **Bundled font**: [Open Sans](https://github.com/googlefonts/opensans)
  Bold, © The Open Sans Project Authors, licensed under the
  [SIL Open Font License 1.1](assets/FONT-LICENSE.txt). Chosen because it's
  freely redistributable and visually close to the plain bold sans-serif
  Jellyfin's own server uses by default — bundled directly so the script
  produces a consistent result regardless of what fonts happen to be
  installed on the machine running it (most Jellyfin servers are headless
  Linux boxes with no desktop fonts at all).

## License

MIT — see [LICENSE](LICENSE). (The bundled font and default photo have their
own separate licenses, noted above — this repo's MIT license covers the
Python code only.)
