# Community Landing Page Generator — Streamlit POC

A standalone Streamlit app that lets anyone paste a builder's community URL and
get back a fully-branded landing page (same design as the main Flask app).

## What it does

1. User pastes a community URL (e.g. `https://www.branthaven.com/communities/the-preserve`)
2. Playwright opens the page in a headless browser
3. OpenAI (`gpt-4o-mini`) extracts community info + filters images + picks thumbnail
4. Images are downloaded and embedded as base64 (so the HTML file works offline)
5. A 2-paragraph marketing description is auto-generated
6. The branded landing page is rendered inline in the Streamlit UI
7. User can download the complete `.html` file

## Design

Same design as `app.py` (Flask version):
- Navy (`#0f1923`) + gold (`#c9a050`) colour palette
- Cormorant Garamond (serif) + Montserrat (sans)
- Hero section with animated zoom, eyebrow tags, pill metadata
- Two-column description layout
- Image gallery with lightbox
- Unit cards with status badges
- Registration form (static — just shows a thank-you message)

## Setup

### Local

```bash
# 1. Clone / unzip this folder
cd streamlit_poc

# 2. Create virtual env and install
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt

# 3. Install Playwright browser
playwright install chromium

# 4. Set your OpenAI key
cp .env.example .env
# edit .env and paste your key

# 5. Run
streamlit run app.py
```

Opens at <http://localhost:8501>.

### Deploy to Render (recommended for public link)

1. Push this folder to a GitHub repo
2. Go to <https://render.com> → **New** → **Web Service**
3. Connect your repo
4. Choose **Docker** runtime (it'll detect the `Dockerfile`)
5. Add environment variable: `OPENAI_API_KEY = sk-...`
6. Click **Create Web Service**
7. Wait ~5 min for first build, then you get a URL like `https://yourapp.onrender.com`

That URL is what you attach in your client emails.

### Deploy to Streamlit Community Cloud (free but limited)

Streamlit Cloud does **not** support Playwright out of the box — Chromium needs
system packages that the free tier restricts. Render / Railway / a small EC2 is
the recommended path for this app.

## File layout

```
streamlit_poc/
├── app.py               # Streamlit UI + orchestration
├── scraper_core.py      # Single-URL scraper (Playwright + OpenAI)
├── page_renderer.py     # HTML generator (same design as Flask app.py)
├── requirements.txt
├── .env.example
├── Dockerfile           # for Render / Railway / any Docker host
├── README.md
└── output/              # created at runtime
    ├── images/          # downloaded images per community
    └── pages/           # saved HTML snapshots
```

## Environment variables

| Variable | Required | Description |
|---|---|---|
| `OPENAI_API_KEY` | ✅ Yes | Your OpenAI API key |
| `OUTPUT_DIR` | No | Output folder (default: `output`) |

## Notes

- First scrape of a URL takes 30–90 seconds depending on page size
- OpenAI calls use `gpt-4o-mini` (cheap — typically $0.01–$0.03 per community)
- Generated HTML is fully self-contained (images embedded), works offline once downloaded
- No data is permanently stored between sessions on ephemeral hosts (Render free tier)
