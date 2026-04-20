"""
scraper_core.py
===============
Single-URL scraper — reuses the core logic from smart_scraper.py but runs on
ONE community URL instead of crawling /communities.

Used by the Streamlit POC app.
"""

import asyncio
import io
import json
import logging
import os
import re
import time
from pathlib import Path
from urllib.parse import urlparse

import requests
from openai import OpenAI
from playwright.async_api import async_playwright

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

logger = logging.getLogger("ScraperCore")

SKIP_IMAGE_KEYWORDS = [
    "logo", "icon", "cookie", "favicon", "sprite", "social",
    "pixel", "tracking", "badge", "arrow", "button", "avatar",
    "headshot", "career", "desk-work", "woman-kitchen",
    "uwsc_sales", "integrity.", "pride.", "quality.", "/value.",
    "map.", "Map.",
]


def slugify(text: str) -> str:
    text = (text or "").lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    return re.sub(r"[\s_]+", "-", text)[:80] or "unnamed"


# ═════════════════════════════════════════════════════════════════════════════
#  IMAGE DOWNLOADER
# ═════════════════════════════════════════════════════════════════════════════
class ImageDownloader:
    def __init__(self, images_dir: Path):
        self.images_dir = Path(images_dir)
        self.images_dir.mkdir(parents=True, exist_ok=True)
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })

    def download(self, url, community_slug, subfolder, index):
        if not url or any(kw in url.lower() for kw in SKIP_IMAGE_KEYWORDS):
            return None
        if url.lower().endswith(".svg"):
            return None
        folder = self.images_dir / community_slug
        if subfolder:
            folder = folder / subfolder
        folder.mkdir(parents=True, exist_ok=True)
        try:
            resp = self.session.get(url, timeout=30, stream=True)
            if resp.status_code != 200:
                return None

            data = resp.content
            if len(data) < 2048:
                return None

            ct = resp.headers.get("Content-Type", "").lower()
            is_webp = "webp" in ct or url.lower().endswith(".webp")

            if is_webp and HAS_PIL:
                try:
                    img = Image.open(io.BytesIO(data))
                    if img.mode in ("RGBA", "P"):
                        img = img.convert("RGB")
                    buf = io.BytesIO()
                    img.save(buf, format="JPEG", quality=85)
                    data = buf.getvalue()
                    ext = ".jpg"
                except Exception:
                    ext = ".webp"
            elif "png" in ct:
                ext = ".png"
            elif is_webp:
                ext = ".webp"
            else:
                ext = ".jpg"

            fp = folder / f"img_{index:03d}{ext}"
            with open(fp, "wb") as f:
                f.write(data)

            return str(fp).replace("\\", "/")
        except Exception as e:
            logger.warning("Image download failed (%s): %s", url, e)
            return None


# ═════════════════════════════════════════════════════════════════════════════
#  LLM AGENT
# ═════════════════════════════════════════════════════════════════════════════
class LLMAgent:
    def __init__(self, api_key: str):
        self.client = OpenAI(api_key=api_key)
        self.calls = 0

    def _call(self, system: str, user: str, max_tokens: int = 4096):
        self.calls += 1
        last_err = None
        for attempt in range(4):
            try:
                resp = self.client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user[:28000]},
                    ],
                    temperature=0,
                    max_tokens=max_tokens,
                    timeout=60,
                )
                raw = resp.choices[0].message.content.strip()
                if "```json" in raw:
                    raw = raw.split("```json")[1].split("```")[0].strip()
                elif "```" in raw:
                    raw = raw.split("```")[1].split("```")[0].strip()
                return json.loads(raw)
            except json.JSONDecodeError as e:
                logger.warning("LLM JSON error: %s", e)
                return None
            except Exception as e:
                last_err = e
                wait = 2 ** attempt
                logger.warning("LLM attempt %d: %s — retry in %ds", attempt + 1, e, wait)
                time.sleep(wait)
        logger.error("LLM failed after 4 attempts: %s", last_err)
        return None

    def extract_community(self, text: str, url: str) -> dict | None:
        """Extract EVERY piece of information from a community page — thorough mode."""
        system = f"""Extract EVERY piece of information from this real-estate community page.
Be extremely thorough — capture ALL data visible on the page.

Return JSON:
{{
    "community_name": "Development Name",
    "location": "Full address or City, Province",
    "builder": "Builder/Developer Name",
    "status": "NOW SELLING / COMING SOON / QUICKSTART",
    "url": "{url}",
    "description": "FULL description — combine ALL text paragraphs from the page into one detailed description",
    "price_range": "From $XXX to $XXX or starting from $XXX",
    "completion_date": "Expected completion/occupancy dates",
    "total_units": "Total number of homes",
    "deposit_structure": "Full deposit structure if mentioned",
    "incentives": ["All incentives, promotions, included items"],
    "features": ["EVERY feature and finish mentioned — flooring, countertops, appliances, smart home, etc."],
    "amenities": ["ALL amenities — parks, trails, schools, transit, shopping nearby"],
    "property_types": ["Each home type with size range, e.g. 3-Storey Townhome 1250-2305 sqft"],
    "contact_phone": "Phone number",
    "contact_email": "Email if shown",
    "sales_centre": "Sales centre address if shown",
    "properties": [
        {{
            "address": "Address or collection name",
            "floorplan": "Model/floor plan name",
            "price": "Price or starting price",
            "status": "Status",
            "bedrooms": "Bedroom range e.g. 3-6",
            "bathrooms": "Bathroom count or range",
            "sqft": "Square footage range e.g. 1250-2305",
            "garage": "Garage type and capacity",
            "lot_width": "Lot width if shown e.g. 20ft, 21ft, 23ft",
            "stories": "Number of stories",
            "description": "Full description of this home type",
            "features": ["Specific features for this type"],
            "image_url": "URL of the image shown for this collection/model if visible"
        }}
    ]
}}

IMPORTANT: Extract EVERYTHING. Include ALL floor plan types, ALL features, ALL finishes,
ALL incentives, ALL nearby amenities. Do not summarize — capture every detail.
If the page mentions specific models or collections, list each one as a separate property."""

        result = self._call(system, text[:22000])
        if isinstance(result, dict) and result.get("community_name"):
            return result
        return None

    def extract_property(self, text: str, url: str) -> dict | None:
        system = f"""Extract ALL details from this individual property/unit page.

Return JSON:
{{
    "address": "Full address or Unit/Lot number",
    "floorplan": "Floor plan or model name",
    "price": "Price",
    "status": "Availability status",
    "bedrooms": "Number",
    "bathrooms": "Number",
    "sqft": "Square footage",
    "garage": "Garage info",
    "lot_size": "Lot size",
    "stories": "Number of stories",
    "description": "Full description",
    "features": ["All features, upgrades, finishes"],
    "specifications": {{}}
}}

Extract ALL details. Do not invent data. URL: {url}"""

        result = self._call(system, text[:22000])
        return result if isinstance(result, dict) else None

    def find_property_links(self, links: list[dict], page_text: str, community_url: str) -> list[str]:
        community_path = urlparse(community_url).path.rstrip("/")
        system = f"""From these links on a community page, find links to INDIVIDUAL property/unit/lot detail pages.

The current community page is: {community_url}

INCLUDE:
- Links to specific units, lots, homes that are SUB-PAGES of this community
- URLs that extend the current community path (e.g. {community_path}/lot-38)
- "View Details", "Learn More", "View Home" for specific properties

EXCLUDE:
- Links to OTHER communities
- The community page itself: {community_url}
- PDF files (any URL ending in .pdf)
- Links with # fragments (same-page anchors)
- Menu/navigation links to other sections of the site
- Contact, register, email, phone links
- Gallery links, "Download" links
- Any link whose URL path does NOT start with {community_path}

Return JSON array of absolute URLs. Max 25. Return [] if no property detail pages exist."""

        lines = [f"{l['url']} | {l['text']}" for l in links if not l['url'].lower().endswith('.pdf')]
        user = f"Community page text:\n{page_text[:2000]}\n\nLinks:\n" + "\n".join(lines)
        result = self._call(system, user, max_tokens=1024)
        if not isinstance(result, list):
            return []
        community_base = community_url.split("#")[0].rstrip("/")
        cleaned = []
        seen = set()
        for link in result:
            if not isinstance(link, str):
                continue
            clean = link.split("#")[0].rstrip("/")
            if (clean and clean not in seen and clean != community_base
                    and not clean.lower().endswith('.pdf')):
                clean_path = urlparse(clean).path.rstrip("/")
                if (clean_path.startswith(community_path + "/")
                        or clean_path.startswith(
                            community_path.replace("/communities/", "/quickstart/") + "/")):
                    seen.add(clean)
                    cleaned.append(clean)
        return cleaned

    def filter_images(self, images: list[dict], name: str, url: str) -> list[dict]:
        if not images or len(images) <= 2:
            return images

        entries = []
        for i, img in enumerate(images):
            w = img.get("width", 0) or 0
            h = img.get("height", 0) or 0
            entries.append(f"{i}: url={img.get('src','')} | {w}x{h} | alt={img.get('alt','')}")

        system = f"""You are classifying images for the real-estate community: "{name}"
URL: {url}

For each image, decide if it should be KEPT or REJECTED based on its URL and alt text.

KEEP these types:
- Exterior renderings of homes/townhomes/buildings
- Interior photos (kitchens, bedrooms, bathrooms, living rooms)
- Lifestyle renders showing the community
- Floor plan images
- Streetscape or aerial views of the community
- Gallery/showcase images specific to this community

REJECT these types:
- Maps, location maps, site maps (URL contains 'map' or 'Map')
- Generic stock photos not specific to this community
- Company logos, icons, badges
- Images from OTHER communities (different community name in URL)
- Career/about page images
- Very small decorative elements

Return JSON: {{"keep": [list of indices to keep], "thumbnail": index_of_best_hero_image}}

The thumbnail should be the best EXTERIOR rendering or photo — wide/landscape, showing homes."""

        result = self._call(system, "\n".join(entries), max_tokens=1024)

        if isinstance(result, dict):
            keep_indices = result.get("keep", [])
            if isinstance(keep_indices, list) and keep_indices:
                filtered = [images[i] for i in keep_indices
                            if isinstance(i, int) and 0 <= i < len(images)]
                if filtered:
                    thumb_idx = result.get("thumbnail")
                    if isinstance(thumb_idx, int) and 0 <= thumb_idx < len(images):
                        thumb_img = images[thumb_idx]
                        if thumb_img in filtered:
                            filtered.remove(thumb_img)
                            filtered.insert(0, thumb_img)
                    return filtered

        filtered = []
        for img in images:
            src = (img.get("src") or "").lower()
            if "map" in src:
                continue
            filtered.append(img)
        return filtered if filtered else images

    def pick_thumbnail(self, images: list[dict], name: str) -> int:
        if not images:
            return 0
        if len(images) == 1:
            return 0

        skip_words = ["lifestyle", "kitchen", "bedroom", "bathroom", "garage",
                      "backyard", "outdoor", "interior", "ensuite", "amenit",
                      "person", "people", "family"]
        prefer_words = ["exterior", "front", "streetscape", "facade", "elevation",
                        "rendering", "collections", "building", "townhome", "town-"]

        scored = []
        for i, img in enumerate(images):
            src = (img.get("url") or img.get("src", "")).lower()
            score = 0
            for kw in prefer_words:
                if kw in src:
                    score += 10
            for kw in skip_words:
                if kw in src:
                    score -= 10
            w = img.get("width", 0) or 0
            h = img.get("height", 0) or 0
            if w > h:
                score += 2
            scored.append((i, score))

        scored.sort(key=lambda x: -x[1])
        candidate_indices = [s[0] for s in scored[:8]]
        candidates = [(idx, images[idx]) for idx in candidate_indices]

        self.calls += 1
        try:
            content = [
                {"type": "text", "text": f"""You are selecting the BEST thumbnail for a real-estate community called "{name}".

Look at these images and pick the ONE that shows the PROPERTY EXTERIOR — the OUTSIDE of homes/townhomes/buildings.

PICK: exterior rendering showing the FRONT of homes, streetscape, building facade, community entrance.
DO NOT PICK: interior photos (kitchens, bedrooms, bathrooms), lifestyle photos with people, backyards, garages, parks, amenities.

Reply ONLY with JSON: {{"pick": <number>, "reason": "brief reason"}}
where <number> is the label number shown before each image."""}
            ]
            for idx, img in candidates:
                src = img.get("url") or img.get("src", "")
                if src:
                    content.append({"type": "text", "text": f"Image {idx}:"})
                    content.append({"type": "image_url",
                                    "image_url": {"url": src, "detail": "low"}})

            resp = self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": content}],
                max_tokens=100,
                temperature=0,
                timeout=30,
            )
            raw = resp.choices[0].message.content.strip()
            if "```json" in raw:
                raw = raw.split("```json")[1].split("```")[0].strip()
            elif "```" in raw:
                raw = raw.split("```")[1].split("```")[0].strip()
            result = json.loads(raw)
            idx = result.get("pick") or result.get("index")
            if isinstance(idx, int) and 0 <= idx < len(images):
                return idx
        except Exception as e:
            logger.warning("Vision thumbnail failed: %s", e)

        for idx, score in scored:
            if score > 0:
                return idx

        best, best_score = 0, 0
        for i, img in enumerate(images):
            w = img.get("width", 0) or 0
            h = img.get("height", 0) or 0
            if w > h:
                s = w * h
                if s > best_score:
                    best_score = s
                    best = i
        return best

    def generate_description(self, community: dict) -> str:
        """Generate a 2-paragraph marketing description."""
        existing = (community.get("description") or "").strip()
        if existing and len(existing) > 50 and existing.lower() not in (
                "not specified", "n/a", "none"):
            return existing

        name = community.get("community_name", "This community")
        location = community.get("location", "")
        builder = community.get("builder") or "the developer"
        units = community.get("properties") or []

        unit_lines = "\n".join(
            f"- {u.get('address','')} | {u.get('floorplan','')} | "
            f"{u.get('price','')} | {u.get('status','')} | {u.get('description','')[:100]}"
            for u in units[:10]
        )

        prompt = f"""You are a luxury real-estate copywriter for {builder}.
Write a compelling 2-paragraph marketing description for this new community.

Paragraph 1: evoke the lifestyle, neighbourhood feel, and location appeal of {name} in {location}.
Paragraph 2: highlight the available homes — sizes, prices, and move-in timelines — in an enticing but factual way.

Keep the tone warm, aspirational, and specific. No generic filler. No headings or bullet points.

Community  : {name}
Location   : {location}
Builder    : {builder}

Available units:
{unit_lines}

Output only the two paragraphs separated by a blank line."""

        try:
            resp = self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=400,
                temperature=0.75,
            )
            return resp.choices[0].message.content.strip()
        except Exception as e:
            logger.warning("Description generation failed: %s", e)
            return (
                f"{name} is an exceptional new community by {builder} in {location}. "
                f"Thoughtfully designed for modern living, this development offers an ideal blend "
                f"of comfort, style, and convenience.\n\n"
                f"Register your interest today for priority access and exclusive updates on "
                f"floor plans, pricing, and launch events."
            )


# ═════════════════════════════════════════════════════════════════════════════
#  BROWSER HELPERS
# ═════════════════════════════════════════════════════════════════════════════
class PopupHandler:
    def __init__(self, page):
        self.page = page

    async def setup(self):
        self.page.context.on("page", lambda p: asyncio.create_task(self._close(p)))
        await self.page.add_init_script("""
            window.open = () => null;
            window.alert = () => {};
            window.confirm = () => true;
        """)

    async def _close(self, popup):
        try:
            await popup.close()
        except Exception:
            pass

    async def dismiss(self):
        for sel in ['button:has-text("Accept")', 'button:has-text("Accept All")',
                    'button:has-text("Agree")', '#onetrust-accept-btn-handler']:
            try:
                btn = await self.page.query_selector(sel)
                if btn and await btn.is_visible():
                    await btn.click(timeout=2000)
                    await self.page.wait_for_timeout(400)
                    break
            except Exception:
                continue
        for sel in ['button[aria-label*="close" i]', 'button.close',
                    '.modal-close', '[data-dismiss="modal"]']:
            try:
                for b in await self.page.query_selector_all(sel):
                    if await b.is_visible():
                        await b.click(timeout=1000)
                        await self.page.wait_for_timeout(200)
            except Exception:
                continue
        try:
            await self.page.keyboard.press("Escape")
        except Exception:
            pass


async def load_page(page, url: str, ph: PopupHandler) -> bool:
    if url.lower().endswith('.pdf'):
        return False
    for attempt in range(2):
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=45000)
            await page.wait_for_timeout(5000)
            await ph.dismiss()
            return True
        except Exception as e:
            if attempt == 0:
                logger.warning("Retry loading %s: %s", url, e)
                await asyncio.sleep(2)
            else:
                logger.error("Failed to load %s: %s", url, e)
    return False


async def smart_scroll(page, rounds=8):
    for _ in range(rounds):
        await page.mouse.wheel(0, 1400)
        await page.wait_for_timeout(700)
    await page.evaluate("window.scrollTo(0, 0)")
    await page.wait_for_timeout(500)


async def click_through_page(page):
    next_selectors = [
        '.swiper-button-next', '.slick-next', '.elementor-swiper-button-next',
        '[class*="carousel"] [class*="next"]', '[class*="slider"] [class*="next"]',
        'button[aria-label*="next" i]',
        '.owl-next', '[class*="arrow-right"]', '[class*="arrow-next"]',
    ]
    for sel in next_selectors:
        try:
            buttons = await page.query_selector_all(sel)
            for btn in buttons:
                if await btn.is_visible():
                    for _ in range(10):
                        try:
                            await btn.click(timeout=800)
                            await page.wait_for_timeout(500)
                        except Exception:
                            break
        except Exception:
            continue

    for sel in ['.swiper-pagination-bullet', '.slick-dots button', '.owl-dot',
                '[class*="pagination"] button']:
        try:
            dots = await page.query_selector_all(sel)
            for dot in dots:
                if await dot.is_visible():
                    await dot.click(timeout=800)
                    await page.wait_for_timeout(500)
        except Exception:
            continue

    for sel in ['[role="tab"]', '.tab', '[class*="tab-link"]',
                '.accordion-header', '[class*="accordion"] button',
                '.elementor-tab-title', '.elementor-toggle-title']:
        try:
            items = await page.query_selector_all(sel)
            for item in items:
                if await item.is_visible():
                    await item.click(timeout=800)
                    await page.wait_for_timeout(600)
        except Exception:
            continue

    for sel in [
        'button:has-text("Load More")', 'button:has-text("View All")',
        'button:has-text("Show More")', 'button:has-text("See More")',
        'a:has-text("View All")', 'a:has-text("See More")',
    ]:
        try:
            btn = await page.query_selector(sel)
            if btn and await btn.is_visible():
                await btn.click(timeout=2000)
                await page.wait_for_timeout(1500)
        except Exception:
            continue

    try:
        total_height = await page.evaluate("document.body.scrollHeight")
        for pos in range(0, total_height, 400):
            await page.evaluate(f"window.scrollTo(0, {pos})")
            await page.wait_for_timeout(300)
        await page.evaluate("window.scrollTo(0, 0)")
        await page.wait_for_timeout(500)
    except Exception:
        pass


async def get_text(page) -> str:
    try:
        return await page.evaluate("document.body.innerText")
    except Exception:
        return ""


async def get_links(page) -> list[dict]:
    try:
        return await page.evaluate("""() => {
            const pageBase = location.origin + location.pathname;
            const results = [];
            const seen = new Set();
            document.querySelectorAll('a[href]').forEach(a => {
                const hrefAttr = a.getAttribute('href') || '';
                if (hrefAttr.startsWith('#') || hrefAttr.startsWith('javascript:')
                    || hrefAttr.startsWith('mailto:') || hrefAttr.startsWith('tel:')) return;
                const url = a.href.split('#')[0];
                if (!url || url === pageBase || url === pageBase + '/' || seen.has(url)) return;
                seen.add(url);
                const text = (a.innerText || a.getAttribute('aria-label')
                              || a.getAttribute('title') || '').trim().substring(0, 120);
                results.push({url, text});
            });
            return results;
        }""")
    except Exception:
        return []


async def get_content_images(page) -> list[dict]:
    try:
        return await page.evaluate("""() => {
            const skipUrl = [
                'logo','icon','cookie','favicon','sprite','social','pixel',
                'tracking','badge','arrow','button','avatar','/value.','Map','map.',
            ];
            const imgs = [], seen = new Set();
            document.querySelectorAll('img').forEach(i => {
                if (i.naturalWidth > 200 && i.naturalHeight > 100 && i.src && !seen.has(i.src)) {
                    const s = i.src.toLowerCase();
                    if (!s.endsWith('.svg') && !skipUrl.some(k => s.includes(k))) {
                        seen.add(i.src);
                        imgs.push({src:i.src, width:i.naturalWidth,
                                   height:i.naturalHeight, alt:i.alt||''});
                    }
                }
            });
            document.querySelectorAll('*').forEach(el => {
                if (el.offsetWidth < 200 || el.offsetHeight < 100) return;
                const bg = getComputedStyle(el).backgroundImage;
                if (bg && bg !== 'none' && bg.includes('url(')) {
                    const m = bg.match(/url\\(["']?([^"')]+)["']?\\)/);
                    if (m && m[1] && !seen.has(m[1])) {
                        const s = m[1].toLowerCase();
                        if (!s.endsWith('.svg') && !skipUrl.some(k => s.includes(k))
                            && s.startsWith('http')) {
                            seen.add(m[1]);
                            imgs.push({src:m[1], width:el.offsetWidth,
                                       height:el.offsetHeight, alt:''});
                        }
                    }
                }
            });
            return imgs.sort((a,b) => (b.width*b.height)-(a.width*a.height));
        }""")
    except Exception:
        return []


# ═════════════════════════════════════════════════════════════════════════════
#  MAIN ENTRY POINT — scrape a single URL
# ═════════════════════════════════════════════════════════════════════════════
async def scrape_single_url(
    target_url: str,
    agent: LLMAgent,
    downloader: ImageDownloader,
    progress_cb=None,
    scrape_sub_pages: bool = True,
    max_images: int = 25,
    max_sub_pages: int = 10,
) -> dict | None:
    """
    Scrape one community URL end-to-end.
    Returns the community dict (same shape as detailed_properties.json entries).
    progress_cb: optional callback(stage:str, detail:str) for UI updates.
    """
    def report(stage, detail=""):
        if progress_cb:
            try:
                progress_cb(stage, detail)
            except Exception:
                pass
        logger.info("[%s] %s", stage, detail)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=["--disable-popup-blocking", "--no-first-run", "--disable-extensions",
                  "--no-sandbox", "--disable-dev-shm-usage"],
        )
        ctx = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        )
        page = await ctx.new_page()
        ph = PopupHandler(page)
        await ph.setup()

        try:
            report("loading", f"Opening {target_url}")
            if not await load_page(page, target_url, ph):
                report("error", "Failed to load page")
                return None

            report("scrolling", "Loading all page content")
            await smart_scroll(page, rounds=10)
            await click_through_page(page)

            text = await get_text(page)

            report("extracting", "Asking AI to read the page")
            data = agent.extract_community(text, target_url)
            if not data:
                report("error", "AI could not extract community data")
                return None

            report("extracted", f"Community: {data.get('community_name', '?')}")

            comm_slug = slugify(data.get("community_name", "") or
                                urlparse(target_url).path.rstrip("/").split("/")[-1] or
                                "community")

            # ── Images ────────────────────────────────────────────────────
            report("images", "Collecting images from page")
            images = await get_content_images(page)
            report("images", f"Found {len(images)} raw images — filtering")
            images = agent.filter_images(images, data.get("community_name", ""), target_url)
            report("images", f"{len(images)} images after AI filter — downloading")

            downloaded = []
            for i, img in enumerate(images[:max_images]):
                local = downloader.download(img["src"], comm_slug, "", i)
                if local:
                    downloaded.append({
                        "url": img["src"], "local_path": local,
                        "alt": img.get("alt", ""),
                        "width": img.get("width"), "height": img.get("height"),
                    })
                if progress_cb and i % 3 == 0:
                    report("images", f"Downloaded {len(downloaded)}/{min(len(images), max_images)}")

            data["all_images"] = downloaded
            if downloaded:
                report("thumbnail", "AI picking best hero image")
                thumb_idx = agent.pick_thumbnail(downloaded, data.get("community_name", ""))
                data["thumbnail_url"] = downloaded[thumb_idx]["url"]
                data["thumbnail_local"] = downloaded[thumb_idx].get("local_path", "")

            # ── Sub-property pages ────────────────────────────────────────
            properties = data.get("properties") or []
            if scrape_sub_pages:
                report("sub-pages", "Looking for individual unit pages")
                page_links = await get_links(page)
                prop_urls = agent.find_property_links(page_links, text, target_url)
                report("sub-pages", f"Found {len(prop_urls)} unit pages")

                for pi, purl in enumerate(prop_urls[:max_sub_pages], 1):
                    report("sub-pages", f"[{pi}/{min(len(prop_urls), max_sub_pages)}] {purl}")
                    try:
                        if not await load_page(page, purl, ph):
                            continue
                        await smart_scroll(page, rounds=5)
                        ptxt = await get_text(page)
                        pdata = agent.extract_property(ptxt, purl)
                        if not pdata:
                            continue

                        pimgs = await get_content_images(page)
                        pname = pdata.get("address") or pdata.get("floorplan") or f"unit_{pi}"
                        pimgs = agent.filter_images(pimgs, pname, purl)
                        psub = slugify(pname)
                        pdl = []
                        for i, img in enumerate(pimgs[:10]):
                            local = downloader.download(img["src"], comm_slug, psub, i)
                            if local:
                                pdl.append({"url": img["src"], "local_path": local,
                                            "alt": img.get("alt", "")})

                        pdata["property_images"] = pdl
                        pdata["property_url"] = purl
                        if pdl:
                            pdata["local_image"] = pdl[0]["local_path"]
                        properties.append(pdata)
                        await asyncio.sleep(1)
                    except Exception as e:
                        logger.warning("Sub-page error: %s", e)

            data["properties"] = properties
            data["url"] = target_url

            # Assign community images to properties that have none
            comm_images = data.get("all_images", [])
            if comm_images:
                for prop in properties:
                    if prop.get("property_images") or prop.get("image_url"):
                        continue
                    prop["image_url"] = comm_images[0]["url"]
                    if comm_images[0].get("local_path"):
                        prop["local_image"] = comm_images[0]["local_path"]

            report("description", "Generating marketing description")
            data["marketing_description"] = agent.generate_description(data)

            report("done", f"Scrape complete: {len(properties)} units, {len(downloaded)} images")
            return data

        finally:
            try:
                await page.close()
                await ctx.close()
                await browser.close()
            except Exception:
                pass
