# Reel

**A clean, Plex-style movie & TV player for Windows and Mac.**
Reel finds the video files on your computer, turns them into a proper library with posters, plots and episode names, plays anything (it uses the mpv engine), remembers where you stopped, and lets your other computers stream your library over Wi-Fi or from anywhere.

> Your videos stay on your own computers. Only small bits of data, like where you stopped and the list of titles, go to the cloud.
>
> **License:** free for personal / noncommercial use — you may not sell it or make money off it. See [LICENSE](LICENSE.md).

---

## What it does

| | |
|---|---|
| **Library** | One **Scan computer** button searches every drive (skipping Windows, Program Files, AppData, game folders and short clips) and saves the result, so the next launch is instant. |
| **Smart names** | Messy release names become clean titles: `Show.Name.S01E02.1080p.WEB…` becomes *Show Name → Season 1 → Episode 2*, and `Movie.Title.2017.BluRay…` becomes *Movie Title (2017)*. It also handles anime-style `Show - 05` names and `Show/Season 1/05.mkv` folders. |
| **Posters & info** | Pulls posters, backdrops, IMDb ratings, plots, cast and per-episode names/stills from Cinemeta (IMDb data, no API key). Only the cleaned-up title and year are sent. |
| **Home** | A Netflix-style hero, Continue Watching (including "next episode" after you finish one), Recently Added movies and TV. |
| **Player** | mpv engine (plays everything VLC does), GPU decoding (NVDEC / VideoToolbox), high-quality scaling, debanding, and auto-hiding controls. The seek bar has chapter markers and hover previews. |
| **TV features** | **Skip Intro / Skip Recap** and a Netflix-style **Up Next** countdown during the end credits, both driven by chapter markers. It auto-plays the next episode. |
| **Tracks** | One panel for audio track, subtitles (plus loading an .srt), subtitle size and speed. Remembers your subtitle choice **per show**. |
| **Resume** | Remembers where you stopped. An episode counts as watched near the end, and Continue Watching moves on to the next one. |
| **Sync** | Optional Supabase sync: where you stopped and what you've watched follow you between computers. |
| **Downloads** | Keep a copy on this computer of anything that's on your other computers, so it plays without internet. Press **Download** on a movie / show / season, or **Select to download** on Movies / TV Shows to tick several, and they queue up. One at a time in the background (also while Reel sits in the tray), resumes after a restart or a dropped connection, brings the subtitle files along, checks free space, and files episodes under the show's folder in `Reel Library`. Only your own computers (same account). |
| **Watchlists** | Everyone's watchlist reaches the owner: the owner's Reel gets a notification when someone adds a title, and Discover shows **Watchlist requests**. Anything on anyone's watchlist that's on one of the owner's computers downloads to the owner's other computers by itself (toggle on the Downloads page). Other accounts still never get files. |
| **Subtitle timing** | Subtitles too early, too late or drifting? The panel's **Subtitle timing** column moves them earlier / later (0.1 s or 1 s), changes their speed, or snaps the previous / next line to *now*. **Auto-sync** listens to the dialogue (centre channel on 5.1) and lines the subtitles up, including 23.976 ↔ 25 fps drift, and only changes anything when it's sure. New subtitle files on this computer get auto-synced on their own. Timing is remembered per title and per subtitle file. |
| **Streaming** | Every Reel shares its own library. Your other computers stream it over the same Wi-Fi or **from anywhere** through a free Cloudflare quick tunnel. There's no account, no router setup and no Tailscale, and every request needs a secret token. Closing the window keeps sharing from the tray. |

### Keyboard (player)

| Key | Action |
|---|---|
| Space / K | Play / pause |
| ← / → | −5 s / +5 s (Shift: 30 s) |
| J / L | −10 s / +10 s |
| ↑ / ↓, scroll | Volume (up to 150 %) |
| F, double-click | Fullscreen |
| S / A | Next subtitle / audio track |
| N / P | Next / previous episode |
| 0–9 | Jump to 0–90 % |
| [ / ] / = | Slower / faster / normal speed |
| G / H | Subtitles 0.1 s earlier / later (Shift: 1 s) |
| Y | Auto-sync subtitles to the dialogue |
| , / . | Frame back / forward |
| Home | Start over |
| I | Video info (resolution, codec, decoder) |
| T / Tab, right-click | Audio / subtitle panel |
| Esc / Backspace | Exit fullscreen / back to library |

---

## Install

### Windows
1. Download this repo (**Code → Download ZIP**) or the **Reel-Windows.zip** release, and unzip it.
2. Double-click **`Install Reel (Windows).bat`**.

   Or run: `powershell -ExecutionPolicy Bypass -File install\windows\install.ps1`
3. Enter your **Reel passphrase** when asked. It unlocks your cloud settings; press Enter to skip.

The installer finds or installs Python, creates a private environment, downloads the mpv engine and cloudflared, and adds Desktop + Start-menu shortcuts. It installs to `%LOCALAPPDATA%\Programs\Reel`.

### Mac
1. Download this repo (**Code → Download ZIP**) or the **Reel-Mac.zip** release, and unzip it.
2. In Terminal:
   ```bash
   bash ~/Downloads/Reel-Mac/install/mac/install.sh
   ```
   (Adjust the path to wherever you unzipped it.)
3. Enter your **Reel passphrase** when asked.

The installer sets up Homebrew if needed, installs `mpv`, `python@3.13` and `cloudflared`, and builds `~/Applications/Reel.app`. Re-run it any time to update.

---

## Secrets (encrypted)

Your Supabase project URL and key live in **`secrets/seed.json.enc`**, never in plain text in this repo.

- Encryption: **scrypt** (N=2¹⁵, r=8, p=1) turns the passphrase into a key, and **Fernet** (AES-128-CBC + HMAC-SHA256) encrypts and authenticates the file. See [`tools/seal.py`](tools/seal.py).
- The installers decrypt it into the app folder's `seed.json` (git-ignored). Reel copies it into its settings on first launch.
- Re-encrypt after changing keys:
  ```bash
  python tools/seal.py lock path/to/seed.json secrets/seed.json.enc
  ```
  `seed.json` looks like `{"supabase_url": "https://….supabase.co", "supabase_key": "sb_publishable_…"}`.
- Use the **publishable/anon** key only, never the secret or service-role key.

## Cloud sync setup (once per Supabase project)

1. Create a project at supabase.com.
2. In **SQL Editor**, run [`supabase.sql`](supabase.sql). It creates `reel_progress` and `reel_library`.
3. Put the Project URL and publishable key in Reel → **Library settings** (folder icon), or in an encrypted `seed.json` as above.

How it works:
- **`reel_progress`**: one row per thing you watched, keyed by *what* it is (`ep:<show>:<season>:<episode>` or `mv:<title>:<year>`), not by file path. Stopping on one computer resumes on the other, and the newest change wins.
- **`reel_library`**: each computer's list of titles plus a `server` row with its addresses and token. That's how the other computers find it and stream from it.

---

## Project layout

```
reel.pyw        app entry: window, scanning, tray, wiring
library.py      folder scan, release-name parser, progress/settings storage
media.py        frame thumbnails (libmpv), poster/backdrop cache, Cinemeta metadata
player.py       libmpv rendered into Qt (OpenGL) + the player overlay
browse.py       sidebar, Home, Movies, TV Shows, detail pages, search
theme.py        colours, fonts, vector icons, shared widgets
cloud.py        Supabase sync (progress, libraries, finding other computers)
server.py       library sharing server (HTTP + Range, token) + Cloudflare tunnel
downloads.py    download queue: other computers -> this one (resumable)
subsync.py      subtitle auto-sync (listens via libmpv, matches lines to speech)
tools/seal.py   encrypt/decrypt the secrets file
install/        Windows (PowerShell) and Mac (bash) installers
supabase.sql    database schema
```

Data lives in `%APPDATA%\Reel` (Windows) or `~/Library/Application Support/Reel` (Mac): settings, progress, the library cache, thumbnails, artwork and `reel.log`.

**Stack:** Python 3.12+, PyQt6, python-mpv (libmpv render API), cryptography, cloudflared.

## Troubleshooting

- **The other computer doesn't show up:** it needs Reel running (the window can be closed, but it must still be in the tray). Same Wi-Fi connects instantly; the internet link takes about 20 s after launch.
- **Windows firewall prompt:** click **Allow** so your other computers can stream.
- **Mac asks for Downloads/Desktop access:** click **Allow** so the scan can see your files.
- **Something broke:** check `reel.log` in the data folder.

## License

**PolyForm Noncommercial License 1.0.0** — Copyright © 2026 Yahya.

Reel is free to use, modify and share for any **noncommercial** purpose (personal use, hobby projects, study, nonprofits, schools). **You may not sell it or use it to make money.** For commercial use, contact the copyright holder. Full terms in [LICENSE.md](LICENSE.md).
