"""
app.py — Streamlit POC (Streamlit Cloud ready)
==============================================
Paste a community URL → scrape it → render the branded landing page inline.

Secrets handling:
  - Streamlit Cloud: reads OPENAI_API_KEY from st.secrets (set via Streamlit UI)
  - Local dev: reads OPENAI_API_KEY from .env file

Run:
    streamlit run app.py
"""

import asyncio
import base64
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import streamlit as st
import streamlit.components.v1 as components

# Load .env file if present (local dev only — ignored on Streamlit Cloud)
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

from scraper_core import ImageDownloader, LLMAgent, scrape_single_url, slugify
from page_renderer import render_community_page

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("app")

OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "output"))
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
IMAGES_DIR = OUTPUT_DIR / "images"
IMAGES_DIR.mkdir(parents=True, exist_ok=True)
PAGES_DIR = OUTPUT_DIR / "pages"
PAGES_DIR.mkdir(parents=True, exist_ok=True)

LOGO_PATH = Path(__file__).parent / "logo.png"


def get_api_key() -> str:
    try:
        if hasattr(st, "secrets") and "OPENAI_API_KEY" in st.secrets:
            key = str(st.secrets["OPENAI_API_KEY"]).strip()
            if key:
                return key
    except Exception:
        pass
    return os.getenv("OPENAI_API_KEY", "").strip()


def _logo_as_base64() -> str:
    if LOGO_PATH.exists():
        try:
            with open(LOGO_PATH, "rb") as f:
                b64 = base64.b64encode(f.read()).decode("ascii")
            return f"data:image/png;base64,{b64}"
        except Exception:
            return ""
    return ""


LOGO_URI = _logo_as_base64()


st.set_page_config(
    page_title="Team La·Casa — Landing Page Generator",
    page_icon="🏡",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown("""
<style>
  @import url('https://fonts.googleapis.com/css2?family=Cormorant+Garamond:wght@300;400;600&family=Montserrat:wght@300;400;500;600&display=swap');

  header[data-testid="stHeader"] { background: transparent !important; height: 0 !important; }
  .stApp > header { display: none !important; }
  [data-testid="stToolbar"] { display: none !important; }
  #MainMenu { display: none !important; }
  footer { display: none !important; }

  .stApp { background: #f5f0e8; }
  .block-container {
    padding-top: 0 !important;
    padding-bottom: 2rem !important;
    max-width: 1100px;
  }

  /* ── Top branding bar — WHITE background so navy logo is visible ──── */
  .brand-bar {
    background: #ffffff;
    margin: 0 -1rem 48px -1rem;
    padding: 28px 56px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    border-bottom: 3px solid #c9a050;
    box-shadow: 0 2px 12px rgba(15, 25, 35, 0.06);
  }
  .brand-bar .brand-logo-wrap {
    display: flex;
    align-items: center;
    gap: 20px;
  }
  .brand-bar img {
    height: 80px;
    width: auto;
    display: block;
    transition: transform 0.3s ease;
  }
  .brand-bar img:hover {
    transform: scale(1.02);
  }
  .brand-bar .brand-tagline {
    color: #0f1923;
    font-family: 'Montserrat', sans-serif;
    font-size: 11px;
    letter-spacing: 4px;
    text-transform: uppercase;
    font-weight: 600;
    padding: 8px 18px;
    border: 1px solid #c9a050;
    border-radius: 2px;
    background: linear-gradient(135deg, #fdf9f2, #f5f0e8);
  }
  .brand-bar .brand-text-fallback {
    color: #0f1923;
    font-family: 'Cormorant Garamond', serif;
    font-size: 36px;
    font-weight: 400;
    letter-spacing: 1px;
  }
  .brand-bar .brand-text-fallback em {
    color: #c9a050;
    font-style: italic;
  }

  h1.app-title {
    font-family: 'Cormorant Garamond', serif !important;
    font-weight: 300 !important;
    font-size: 42px !important;
    color: #0f1923 !important;
    margin: 0 0 12px 0 !important;
    letter-spacing: -0.5px;
    line-height: 1.15 !important;
  }
  h1.app-title em { color: #c9a050; font-style: italic; }
  .app-sub {
    font-family: 'Montserrat', sans-serif;
    font-size: 11px;
    letter-spacing: 3px;
    text-transform: uppercase;
    color: #c9a050;
    margin-bottom: 8px;
    font-weight: 600;
  }
  .app-desc {
    color: #555;
    font-size: 13px;
    line-height: 1.75;
    margin-bottom: 28px;
    max-width: 720px;
  }

  .stTextInput input {
    font-family: 'Montserrat', sans-serif !important;
    font-size: 14px !important;
    padding: 12px 16px !important;
    border-radius: 3px !important;
    border: 1px solid #d9d0c3 !important;
    background: #fff !important;
    height: 46px !important;
  }
  .stTextInput input:focus {
    border-color: #c9a050 !important;
    box-shadow: 0 0 0 2px rgba(201,160,80,.15) !important;
  }
  .stTextInput label { display: none !important; }

  .stButton button {
    background: #0f1923 !important;
    color: #c9a050 !important;
    font-family: 'Montserrat', sans-serif !important;
    font-size: 11px !important;
    font-weight: 600 !important;
    letter-spacing: 3px !important;
    text-transform: uppercase !important;
    padding: 12px 24px !important;
    border-radius: 3px !important;
    border: none !important;
    height: 46px !important;
    transition: all .2s !important;
  }
  .stButton button:hover {
    background: #1a2a3d !important;
    transform: translateY(-1px);
  }
  .stButton button:disabled { opacity: 0.5 !important; }

  [data-testid="stStatusWidget"] { font-family: 'Montserrat', sans-serif !important; }
  .stAlert {
    font-family: 'Montserrat', sans-serif !important;
    border-radius: 3px !important;
  }
  .divider {
    height: 1px;
    background: linear-gradient(90deg, transparent, #c9a050, transparent);
    margin: 40px 0 24px;
    opacity: 0.4;
  }
  .preview-header {
    background: #0f1923;
    padding: 14px 24px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    border-radius: 3px 3px 0 0;
    margin-bottom: 0;
  }
  .preview-header-title {
    color: #c9a050;
    font-family: 'Cormorant Garamond', serif;
    font-size: 18px;
    font-weight: 400;
  }
  .preview-header-sub {
    color: rgba(255,255,255,0.5);
    font-size: 10px;
    letter-spacing: 2px;
    text-transform: uppercase;
    font-family: 'Montserrat', sans-serif;
  }

  .app-footer {
    text-align:center;
    color:#999;
    font-size:11px;
    letter-spacing:1px;
    font-family:'Montserrat',sans-serif;
    padding:20px 0;
  }

  [data-testid="stMetricValue"] {
    font-family: 'Cormorant Garamond', serif !important;
    color: #0f1923 !important;
    font-weight: 400 !important;
  }
  [data-testid="stMetricLabel"] {
    font-family: 'Montserrat', sans-serif !important;
    font-size: 10px !important;
    letter-spacing: 2px !important;
    text-transform: uppercase !important;
    color: #7a7a7a !important;
  }

  .config-error {
    background: #fff;
    border-left: 4px solid #8b0000;
    padding: 20px 24px;
    border-radius: 3px;
    margin: 20px 0;
    font-family: 'Montserrat', sans-serif;
    font-size: 13px;
    color: #333;
    line-height: 1.7;
  }
  .config-error strong { color: #8b0000; display: block; margin-bottom: 8px; font-size: 14px; }
  .config-error code {
    background: #f5f0e8;
    padding: 2px 6px;
    border-radius: 2px;
    font-family: 'Courier New', monospace;
    font-size: 12px;
    color: #0f1923;
  }

  /* Responsive — smaller on mobile */
  @media (max-width: 768px) {
    .brand-bar {
      padding: 20px 24px;
      flex-direction: column;
      gap: 16px;
      text-align: center;
    }
    .brand-bar img { height: 60px; }
    .brand-bar .brand-tagline { font-size: 9px; padding: 6px 14px; }
  }
</style>
""", unsafe_allow_html=True)


# ═════════════════════════════════════════════════════════════════════════════
#  BRANDING BAR — white background, logo prominently displayed
# ═════════════════════════════════════════════════════════════════════════════
if LOGO_URI:
    st.markdown(f"""
<div class="brand-bar">
  <div class="brand-logo-wrap">
    <img src="{LOGO_URI}" alt="Team La·Casa">
  </div>
  <span class="brand-tagline">Landing Page Generator</span>
</div>
""", unsafe_allow_html=True)
else:
    st.markdown("""
<div class="brand-bar">
  <span class="brand-text-fallback">Team <em>La·Casa</em></span>
  <span class="brand-tagline">Landing Page Generator</span>
</div>
""", unsafe_allow_html=True)


# ═════════════════════════════════════════════════════════════════════════════
#  SESSION STATE
# ═════════════════════════════════════════════════════════════════════════════
if "result_html" not in st.session_state:
    st.session_state.result_html = None
if "result_data" not in st.session_state:
    st.session_state.result_data = None
if "result_filename" not in st.session_state:
    st.session_state.result_filename = None
if "error_msg" not in st.session_state:
    st.session_state.error_msg = None
if "push_url" not in st.session_state:
    st.session_state.push_url = None


# ═════════════════════════════════════════════════════════════════════════════
#  HEADER
# ═════════════════════════════════════════════════════════════════════════════
st.markdown('<div class="app-sub">Paste a URL — we\'ll handle the rest</div>', unsafe_allow_html=True)
st.markdown('<h1 class="app-title">Generate a <em>branded</em> landing page in seconds</h1>', unsafe_allow_html=True)
st.markdown(
    '<div class="app-desc">Enter the URL of any builder\'s community page and we\'ll scrape the '
    'content, download images, generate a marketing description, and render a complete landing page '
    'you can preview and download.</div>',
    unsafe_allow_html=True
)


# ═════════════════════════════════════════════════════════════════════════════
#  API KEY CHECK
# ═════════════════════════════════════════════════════════════════════════════
api_key = get_api_key()

if not api_key:
    st.markdown("""
<div class="config-error">
  <strong>⚠️ OpenAI API key is not configured</strong>
  <div>This app needs an OpenAI API key to function. To fix:</div>
  <br>
  <div><b>On Streamlit Cloud:</b> Go to your app settings → Secrets → add this line:</div>
  <div style="margin-left:18px;margin-top:4px;"><code>OPENAI_API_KEY = "sk-your-key-here"</code></div>
  <br>
  <div><b>Locally:</b> Create a <code>.env</code> file in the project folder with:</div>
  <div style="margin-left:18px;margin-top:4px;"><code>OPENAI_API_KEY=sk-your-key-here</code></div>
</div>
""", unsafe_allow_html=True)
    st.stop()


# ═════════════════════════════════════════════════════════════════════════════
#  INPUT FORM
# ═════════════════════════════════════════════════════════════════════════════
col1, col2 = st.columns([4, 1])
with col1:
    url_input = st.text_input(
        "Community URL",
        placeholder="https://www.builder.com/communities/your-community-name",
        label_visibility="collapsed",
        key="url_input",
    )
with col2:
    generate_clicked = st.button("Generate Page", use_container_width=True)


# ═════════════════════════════════════════════════════════════════════════════
#  SCRAPE + RENDER
# ═════════════════════════════════════════════════════════════════════════════
def run_scrape(url: str):
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        st.session_state.error_msg = "Please enter a valid URL (must include https://)."
        return

    st.session_state.error_msg = None
    st.session_state.result_html = None
    st.session_state.result_data = None

    agent = LLMAgent(api_key)
    downloader = ImageDownloader(IMAGES_DIR)

    with st.status("Starting scrape…", expanded=True) as status_box:
        def progress_cb(stage: str, detail: str):
            status_box.update(label=f"🔄 {detail}" if detail else f"🔄 {stage}")
            status_box.write(f"**{stage.upper()}** — {detail}")

        try:
            try:
                loop = asyncio.get_event_loop()
                if loop.is_closed():
                    raise RuntimeError("loop closed")
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)

            data = loop.run_until_complete(
                scrape_single_url(
                    url, agent, downloader,
                    progress_cb=progress_cb,
                    scrape_sub_pages=True,
                    max_images=20,
                    max_sub_pages=6,
                )
            )

            if not data:
                status_box.update(label="❌ Scrape failed", state="error")
                st.session_state.error_msg = (
                    "Could not extract community data from this URL. "
                    "The page may be blocked, require login, or have an unusual structure."
                )
                return

            progress_cb("render", "Building landing page HTML")
            html = render_community_page(data, embed_local=True)

            slug = slugify(data.get("community_name", "")) or "community"
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{slug}_{timestamp}.html"
            try:
                filepath = PAGES_DIR / filename
                filepath.write_text(html, encoding="utf-8")
                json_path = PAGES_DIR / f"{slug}_{timestamp}.json"
                json_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            except Exception as e:
                logger.warning("Could not save local snapshot: %s", e)

            st.session_state.result_html = html
            st.session_state.result_data = data
            st.session_state.result_filename = filename

            status_box.update(
                label=f"✅ Landing page generated — {len(data.get('properties', []))} units, "
                      f"{len(data.get('all_images', []))} images",
                state="complete",
            )

        except Exception as e:
            logger.exception("Scrape failed")
            status_box.update(label=f"❌ Error: {type(e).__name__}", state="error")
            st.session_state.error_msg = (
                f"Unexpected error while scraping — {type(e).__name__}. "
                "Please try again or use a different URL."
            )


if generate_clicked:
    if not url_input.strip():
        st.warning("Please enter a URL first.")
    else:
        run_scrape(url_input.strip())


# ═════════════════════════════════════════════════════════════════════════════
#  ERROR DISPLAY
# ═════════════════════════════════════════════════════════════════════════════
if st.session_state.error_msg:
    st.error(st.session_state.error_msg)


# ═════════════════════════════════════════════════════════════════════════════
#  RESULT DISPLAY
# ═════════════════════════════════════════════════════════════════════════════
if st.session_state.result_html:
    data = st.session_state.result_data
    html = st.session_state.result_html
    fname = st.session_state.result_filename

    st.markdown('<div class="divider"></div>', unsafe_allow_html=True)

    name = data.get("community_name", "Community")
    status_val = data.get("status", "")
    units = data.get("properties", [])
    imgs = data.get("all_images", [])

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Community", name[:30] + ("…" if len(name) > 30 else ""))
    m2.metric("Status", status_val or "—")
    m3.metric("Units", len(units))
    m4.metric("Images", len(imgs))

    dc1, dc2, dc3, dc4 = st.columns([2, 1, 1, 1])
    with dc1:
        st.markdown(
            f'<div class="preview-header">'
            f'<span class="preview-header-title">{name}</span>'
            f'<span class="preview-header-sub">Live Preview</span>'
            f'</div>',
            unsafe_allow_html=True,
        )
    with dc2:
        st.download_button(
            "⬇ Download HTML",
            data=html,
            file_name=fname,
            mime="text/html",
            use_container_width=True,
        )
    with dc3:
        ec2_ip = os.getenv("EC2_IP", "")
        ec2_port = os.getenv("EC2_PORT", "8000")
        if ec2_ip and st.button("🚀 Push to Server", use_container_width=True):
            slug = slugify(name)
            try:
                import requests as req
                resp = req.post(
                    f"http://{ec2_ip}:{ec2_port}/push-page",
                    json={"slug": slug, "html": html, "name": name},
                    timeout=30,
                )
                if resp.status_code == 200:
                    result = resp.json()
                    edit_url = f"http://{ec2_ip}:{ec2_port}{result.get('edit_url', f'/draft/{slug}')}"
                    st.session_state.push_url = edit_url
                    st.success(f"✅ Pushed! Edit & confirm at the link below.")
                else:
                    st.error(f"Push failed: {resp.status_code} — {resp.text[:200]}")
            except Exception as e:
                st.error(f"Could not reach server: {e}")
        elif not ec2_ip:
            st.info("Set EC2_IP in .env to enable push")
    with dc4:
        if st.button("🔄 Generate Another", use_container_width=True):
            st.session_state.result_html = None
            st.session_state.result_data = None
            st.session_state.result_filename = None
            st.session_state.error_msg = None
            st.session_state.pop("push_url", None)
            st.rerun()

    # Show the live edit link if pushed
    if "push_url" in st.session_state and st.session_state.push_url:
        st.markdown(
            f'<div style="background:#0f1923;padding:16px 24px;border-radius:4px;margin:12px 0">'
            f'<span style="color:#c9a050;font-size:11px;letter-spacing:2px;text-transform:uppercase;font-family:Montserrat,sans-serif">Live Edit Link</span><br>'
            f'<a href="{st.session_state.push_url}" target="_blank" style="color:#fff;font-size:16px;text-decoration:none;font-family:Montserrat,sans-serif">'
            f'{st.session_state.push_url}</a></div>',
            unsafe_allow_html=True,
        )

    components.html(html, height=900, scrolling=True)

    with st.expander("📋 Show raw scraped data (JSON)"):
        st.json(data)


# ═════════════════════════════════════════════════════════════════════════════
#  FOOTER
# ═════════════════════════════════════════════════════════════════════════════
st.markdown('<div class="divider"></div>', unsafe_allow_html=True)
st.markdown(
    f'<div class="app-footer">'
    f'© {datetime.now().year} Team La·Casa · Landing Page Generator'
    '</div>',
    unsafe_allow_html=True,
)
