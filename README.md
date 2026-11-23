# The Daily Read

A free, self-updating article reader. It pulls from ~35 newspapers and magazines (RSS/Atom), removes duplicates, ranks by source quality + freshness, and publishes a fast static website. No server, no database, no cost.

```
feeds.json        ← the list of sources (edit this to add/remove)
fetch_feeds.py    ← downloads feeds, merges into the archive
docs/index.html   ← the reader (search, filters, save, read/unread, dark mode)
docs/articles.json← generated data (updated automatically)
.github/workflows/update.yml ← runs the fetcher every 3 hours
```

## Put it online (free, ~5 minutes)

1. Create a new **public** GitHub repository and upload everything in this folder (keep the `.github` folder).
2. Repo **Settings → Pages → Build and deployment**: Source = *Deploy from a branch*, Branch = `main`, Folder = `/docs`.
3. Repo **Settings → Actions → General → Workflow permissions**: choose *Read and write permissions*.
4. Go to the **Actions** tab → *Update articles* → **Run workflow** (first run; after that it runs every 3 hours by itself).
5. Your reader is at `https://<your-username>.github.io/<repo-name>/`. Add it to your phone's home screen.

## Run it on your own computer

```bash
pip install -r requirements.txt
python fetch_feeds.py            # prints which feeds worked / failed
cd docs && python -m http.server 8000   # open http://localhost:8000
```
(Re-run `fetch_feeds.py` whenever you want fresh articles, or schedule it with cron / Task Scheduler.)

## Customising

Each feed in `feeds.json` takes:

| key | meaning |
|---|---|
| `name`, `category`, `url` | required |
| `weight` | 1–3 — how much you trust the source; drives "Top picks" ranking |
| `max_items` | per-feed cap (default 15) |
| `include` / `exclude` | regex on title+summary, e.g. `"exclude": "cricket|celebrity"` |

Global `settings`: `keep_days` (archive length, default 30), `max_items_per_feed`, `max_total`.

To add a source, find its RSS link (try `/feed`, `/rss`, or look for the RSS icon) and add a line. The run log tells you if a URL is dead; the site's **Sources** footer also lists unreachable feeds.

## Good to know

- Articles link to the publisher's own site. Paywalled outlets (Atlantic, New Yorker, Economist) show headline + teaser in their feeds; you'll need a subscription to read the full piece. Keep them or delete them in `feeds.json`.
- Feed URLs change now and then — if a source shows "unavailable", look up its current RSS link.
- Saved/read marks are stored in your browser only (per device).
- GitHub pauses scheduled workflows on repos with no activity for ~60 days; the bot's own commits normally count as activity, but if updates stop, press *Run workflow* once.
- This is for personal reading. Respect each site's terms; the app only uses their public RSS feeds and links back to them.
