"""
page_renderer.py
================
Renders a community landing page using the SAME design as new_app.py on the server.
Dark navy (#101d42) + white + light blue (#c8d8ea) theme.
Playfair Display + Inter fonts.
Includes smart image scoring so unit cards get EXTERIOR/PROPERTY images.
"""

import base64
import mimetypes
from datetime import datetime
from pathlib import Path

from jinja2 import Template


# ═════════════════════════════════════════════════════════════════════════════
#  HELPERS
# ═════════════════════════════════════════════════════════════════════════════
def _clean(val) -> str:
    if val is None:
        return ""
    s = str(val).strip()
    if s.lower() in ("not specified", "n/a", "none", "null", "inquire",
                     "inquire for pricing", "available upon request", "tbd",
                     "not available", "unknown", "not mentioned"):
        return ""
    return s


def _file_to_data_uri(path: str) -> str:
    """Convert a local image file to a base64 data URI."""
    try:
        p = Path(path)
        if not p.exists():
            return ""
        mime, _ = mimetypes.guess_type(str(p))
        if not mime:
            mime = "image/jpeg"
        with open(p, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("ascii")
        return f"data:{mime};base64,{b64}"
    except Exception:
        return ""


def _img_src(img_dict: dict, embed_local: bool = True) -> str:
    """Prefer base64-embedded local image, fall back to remote URL."""
    if embed_local:
        local = img_dict.get("local_path") or ""
        if local:
            uri = _file_to_data_uri(local)
            if uri:
                return uri
    return img_dict.get("url", "") or img_dict.get("src", "")



def _score_image_for_property_card(img_dict: dict) -> int:
    """
    Score how well an image fits as a property/unit card thumbnail.
    Higher score = better fit. Exterior renderings > interiors > lifestyle > people.
    """
    url = (img_dict.get("url") or img_dict.get("src", "") or "").lower()
    alt = (img_dict.get("alt", "") or "").lower()
    text = url + " " + alt

    score = 0

    penalty_terms = [
        "lifestyle", "family", "people", "person", "child", "kid", "couple",
        "man", "woman", "girl", "boy", "dog", "pet", "baby", "group",
        "fishing", "cooking", "dining", "eating", "meal", "pancake", "food",
        "drinking", "wine", "picnic", "party", "celebration",
        "smiling", "laughing", "portrait", "headshot", "team_", "staff",
        "grandparent", "parent", "friends", "gathering",
    ]
    for term in penalty_terms:
        if term in text:
            score -= 30

    interior_terms = [
        "kitchen", "bedroom", "bathroom", "ensuite", "dining_room",
        "living_room", "closet", "laundry", "mudroom", "pantry",
        "garage_interior", "basement",
    ]
    for term in interior_terms:
        if term in text:
            score -= 5

    exterior_terms = [
        "exterior", "elevation", "streetscape", "facade", "front",
        "rendering", "render_", "townhome", "townhouse", "home_",
        "building", "architecture", "collection", "model",
        "backyard", "yard", "outdoor_home",
    ]
    for term in exterior_terms:
        if term in text:
            score += 20

    if any(t in text for t in ["3-storey", "3storey", "2-storey", "2storey",
                                "back-to-back", "backtoback", "rear-lane",
                                "rearlane", "detached"]):
        score += 30

    w = img_dict.get("width", 0) or 0
    h = img_dict.get("height", 0) or 0
    if w and h:
        if w > h * 1.3:
            score += 10
        elif w > h:
            score += 3
        elif h > w * 1.3:
            score -= 5

    if w * h > 500000:
        score += 5

    return score


def _get_hero_image(community: dict, embed_local: bool = True) -> str:
    tlocal = community.get("thumbnail_local")
    turl = community.get("thumbnail_url")
    if embed_local and tlocal:
        uri = _file_to_data_uri(tlocal)
        if uri:
            return uri
    if turl:
        return turl
    for img in (community.get("all_images") or []):
        src = _img_src(img, embed_local)
        if src:
            return src
    for unit in (community.get("properties") or []):
        if unit.get("image_url"):
            return unit["image_url"]
        for img in (unit.get("property_images") or []):
            src = _img_src(img, embed_local)
            if src:
                return src
    return ""


def _get_unit_image(unit: dict, embed_local: bool = True, fallback_pool: list = None) -> str:
    local = unit.get("local_image") or ""
    if embed_local and local:
        uri = _file_to_data_uri(local)
        if uri:
            return uri
    raw_url = (unit.get("image_url") or "").strip()
    if raw_url and raw_url.startswith(("http://", "https://", "data:")):
        return raw_url
    for img in (unit.get("property_images") or []):
        src = _img_src(img, embed_local)
        if src:
            return src
    if fallback_pool:
        idx = unit.get("_fallback_idx", 0)
        if 0 <= idx < len(fallback_pool):
            return fallback_pool[idx]
        return fallback_pool[0]
    return ""


def _get_gallery_images(community: dict, embed_local: bool = True, limit: int = 12) -> list:
    out = []
    seen = set()
    for img in (community.get("all_images") or []):
        src = _img_src(img, embed_local)
        key = img.get("url") or img.get("local_path") or src[:200]
        if src and key not in seen:
            seen.add(key)
            out.append(src)
        if len(out) >= limit:
            return out
    for unit in (community.get("properties") or []):
        for img in (unit.get("property_images") or []):
            src = _img_src(img, embed_local)
            key = img.get("url") or img.get("local_path") or src[:200]
            if src and key not in seen:
                seen.add(key)
                out.append(src)
            if len(out) >= limit:
                return out
    return out


def _build_scored_fallback_pool(community: dict, embed_local: bool, hero_url: str) -> list:
    """Build a sorted fallback list: best property-looking images first."""
    scored = []
    seen_keys = set()

    for img in (community.get("all_images") or []):
        key = img.get("url") or img.get("local_path") or ""
        if key in seen_keys:
            continue
        seen_keys.add(key)
        src = _img_src(img, embed_local)
        if not src or src == hero_url:
            continue
        score = _score_image_for_property_card(img)
        scored.append((score, src, img))

    for unit in (community.get("properties") or []):
        for img in (unit.get("property_images") or []):
            key = img.get("url") or img.get("local_path") or ""
            if key in seen_keys:
                continue
            seen_keys.add(key)
            src = _img_src(img, embed_local)
            if not src or src == hero_url:
                continue
            score = _score_image_for_property_card(img)
            scored.append((score, src, img))

    scored.sort(key=lambda x: -x[0])
    good = [src for score, src, _ in scored if score >= 0]
    if not good:
        good = [src for _, src, _ in scored]
    if not good and hero_url:
        good = [hero_url]
    return good



# ═════════════════════════════════════════════════════════════════════════════
#  HTML TEMPLATE — matches new_app.py server design exactly
# ═════════════════════════════════════════════════════════════════════════════
PAGE_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{{ name }} – {{ builder }}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:ital,wght@0,400;0,600;0,700;1,400&family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{
  --navy:#101d42;--navy2:#152452;--navy3:#1a2d5e;
  --accent:#c8d8ea;--accent2:#9bb5d0;
  --white:#ffffff;--offwhite:#f4f7fa;--light:#e4e9f0;
  --text:#1a202c;--muted:#64748b;
}
html{scroll-behavior:smooth}
body{font-family:'Inter',sans-serif;color:var(--text);background:var(--white)}

/* ═══ TOP BANNER ═══ */
.top-banner{background:var(--navy2);text-align:center;padding:10px 20px}
.top-banner p{font-size:11px;color:var(--accent);letter-spacing:1px;font-weight:500}
.top-banner a{color:var(--white);text-decoration:underline;font-weight:600;margin-left:8px}

/* ═══ HERO ═══ */
.hero{position:relative;height:50vh;min-height:320px;display:flex;align-items:flex-end;justify-content:center;
  background-size:100% 100%;background-position:center;background-repeat:no-repeat}
.hero-overlay{position:absolute;top:0;left:0;right:0;bottom:0;
  background:linear-gradient(to top,rgba(16,29,66,.6) 0%,rgba(16,29,66,.05) 50%,transparent 100%);z-index:1}
.hero-content{position:relative;z-index:2;text-align:center;max-width:800px;padding:0 24px 28px}
.hero-badge{display:inline-block;font-size:10px;letter-spacing:3px;text-transform:uppercase;
  color:var(--accent);border:1px solid rgba(197,213,228,.3);padding:5px 16px;border-radius:30px;
  margin-bottom:14px;font-weight:600}
.hero h1{font-family:'Playfair Display',serif;font-size:clamp(32px,5.5vw,56px);color:var(--white);
  font-weight:700;line-height:1.05;margin-bottom:0}
.hero h1 em{font-style:italic;color:var(--accent)}

/* ═══ HERO DETAILS ═══ */
.hero-details{background:var(--navy);padding:20px 24px;text-align:center;position:relative;z-index:2}
.hero-sub{font-size:13px;color:rgba(255,255,255,.65);line-height:1.6;margin-bottom:20px;max-width:650px;margin-left:auto;margin-right:auto}
.hero-prices{display:flex;gap:12px;justify-content:center;flex-wrap:wrap;margin-bottom:20px}
.hero-price-tag{background:rgba(255,255,255,.08);backdrop-filter:blur(8px);border:1px solid rgba(255,255,255,.12);
  padding:10px 22px;border-radius:6px;text-align:center}
.hero-price-tag .label{font-size:9px;letter-spacing:2.5px;text-transform:uppercase;color:var(--accent);margin-bottom:3px}
.hero-price-tag .value{font-family:'Playfair Display',serif;font-size:18px;color:var(--white);font-weight:600}
.hero-cta{display:inline-block;background:var(--white);color:var(--navy);font-size:11px;font-weight:700;
  letter-spacing:3px;text-transform:uppercase;padding:12px 32px;border-radius:4px;text-decoration:none;
  transition:all .2s;border:none;cursor:pointer}
.hero-cta:hover{background:var(--accent);transform:translateY(-2px);box-shadow:0 8px 30px rgba(0,0,0,.3)}

/* ═══ SECTION COMMON ═══ */
.section{padding:32px 24px}
.section-dark{background:var(--navy);color:var(--white)}
.section-light{background:var(--offwhite)}
.section-white{background:var(--white)}
.wrap{max-width:1100px;margin:0 auto}
.section-label{font-size:10px;letter-spacing:4px;text-transform:uppercase;color:var(--accent2);font-weight:600;margin-bottom:8px}
.section-dark .section-label{color:var(--accent)}
.section-title{font-family:'Playfair Display',serif;font-size:clamp(24px,3.5vw,36px);font-weight:700;line-height:1.15;margin-bottom:14px}
.section-dark .section-title{color:var(--white)}

/* ═══ ABOUT ═══ */
.about-section{max-width:780px;margin:0 auto;position:relative}
.about-card{background:var(--white);border-radius:12px;padding:24px 28px;
  box-shadow:0 4px 30px rgba(16,29,66,.08);border:1px solid rgba(16,29,66,.06);
  position:relative;overflow:hidden}
.about-card::before{content:'';position:absolute;top:0;left:0;right:0;height:4px;
  background:linear-gradient(90deg,var(--navy) 0%,var(--accent2) 100%)}
.about-card .section-label{text-align:center}
.about-card .section-title{text-align:center;margin-bottom:16px}
.about-card .about-text{font-size:13px;color:#4a5568;line-height:1.8;text-align:center}
.about-card .about-text p{margin-bottom:12px}
.about-card .about-text p:last-child{margin-bottom:0}
.about-card .about-divider{width:60px;height:2px;background:var(--accent2);margin:0 auto 16px;border-radius:2px}

/* ═══ QUICK FACTS ═══ */
.facts-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:14px;margin-top:20px}
.fact-card{background:rgba(255,255,255,.05);border:1px solid rgba(255,255,255,.1);border-radius:6px;padding:14px 20px}
.fact-label{font-size:9px;letter-spacing:2px;text-transform:uppercase;color:var(--accent);margin-bottom:4px;font-weight:600}
.fact-value{font-size:13px;color:var(--white);line-height:1.5}

/* ═══ GALLERY ═══ */
.gallery-wrap{position:relative;margin-top:14px}
.gallery-grid{display:flex;gap:8px;overflow-x:auto;scroll-behavior:smooth;padding:8px 0;-webkit-overflow-scrolling:touch}
.gallery-grid::-webkit-scrollbar{height:6px}
.gallery-grid::-webkit-scrollbar-track{background:var(--light);border-radius:3px}
.gallery-grid::-webkit-scrollbar-thumb{background:var(--accent2);border-radius:3px}
.gallery-grid img{flex-shrink:0;width:240px;height:160px;object-fit:cover;border-radius:4px;cursor:zoom-in;
  transition:transform .3s,box-shadow .3s}
.gallery-grid img:hover{transform:scale(1.02);box-shadow:0 8px 24px rgba(0,0,0,.15)}
.gallery-arrow{position:absolute;top:50%;transform:translateY(-50%);z-index:5;width:36px;height:36px;
  background:var(--navy);color:var(--white);border:none;border-radius:50%;cursor:pointer;
  font-size:18px;display:flex;align-items:center;justify-content:center;
  box-shadow:0 2px 10px rgba(0,0,0,.2);transition:background .2s}
.gallery-arrow:hover{background:var(--navy2)}
.gallery-arrow-left{left:-12px}
.gallery-arrow-right{right:-12px}

/* ═══ UNITS ═══ */
.units-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:16px;margin-top:20px}
.unit-card{background:var(--white);border-radius:6px;overflow:hidden;box-shadow:0 2px 12px rgba(0,0,0,.06);
  transition:transform .3s,box-shadow .3s}
.unit-card:hover{transform:translateY(-3px);box-shadow:0 10px 30px rgba(0,0,0,.1)}
.unit-img{height:160px;overflow:hidden;background:var(--light);position:relative}
.unit-img img{width:100%;height:100%;object-fit:cover;transition:transform .4s}
.unit-card:hover .unit-img img{transform:scale(1.05)}
.unit-badge{position:absolute;top:10px;left:10px;font-size:9px;letter-spacing:2px;font-weight:700;
  text-transform:uppercase;padding:4px 10px;border-radius:3px}
.badge-qs{background:var(--navy);color:var(--accent)}
.badge-cs{background:#2d6a4f;color:#fff}
.badge-avail{background:var(--accent2);color:var(--navy)}
.badge-def{background:rgba(0,0,0,.5);color:#fff}
.unit-body{padding:14px 18px 18px}
.unit-addr{font-family:'Playfair Display',serif;font-size:15px;color:var(--navy);margin-bottom:3px;font-weight:600}
.unit-fp{font-size:10px;color:var(--muted);margin-bottom:5px}
.unit-specs{font-size:10px;color:var(--muted);margin-bottom:6px}
.unit-desc{font-size:11px;color:#666;line-height:1.5;margin-bottom:10px}
.unit-price{font-family:'Playfair Display',serif;font-size:20px;font-weight:700;color:var(--navy)}

/* ═══ REGISTER ═══ */
.reg-grid{display:grid;grid-template-columns:1fr 1fr;gap:40px;align-items:start}
.reg-copy p{font-size:13px;color:rgba(255,255,255,.55);line-height:1.7;margin-top:12px}
.reg-form{background:rgba(255,255,255,.04);border:1px solid rgba(197,213,228,.15);border-radius:6px;padding:24px}
.frow{display:grid;grid-template-columns:1fr 1fr;gap:14px}
.fg{margin-bottom:14px}
.fg label{display:block;font-size:10px;letter-spacing:2px;text-transform:uppercase;
  color:rgba(255,255,255,.4);margin-bottom:6px;font-weight:600}
.fg input,.fg select,.fg textarea{width:100%;background:rgba(255,255,255,.06);
  border:1px solid rgba(255,255,255,.12);border-radius:4px;padding:11px 14px;color:#fff;
  font-family:'Inter',sans-serif;font-size:13px;outline:none;transition:border-color .2s}
.fg input::placeholder,.fg textarea::placeholder{color:rgba(255,255,255,.2)}
.fg input:focus,.fg select:focus,.fg textarea:focus{border-color:var(--accent2)}
.fg select option{background:var(--navy);color:#fff}
.fg textarea{resize:vertical;min-height:80px}
.btn-register{width:100%;background:var(--white);color:var(--navy);border:none;padding:14px;
  font-family:'Inter',sans-serif;font-size:11px;font-weight:700;letter-spacing:3px;
  text-transform:uppercase;border-radius:4px;cursor:pointer;transition:all .2s;margin-top:4px}
.btn-register:hover{background:var(--accent);transform:translateY(-1px)}
.form-msg{display:none;padding:12px;border-radius:4px;font-size:13px;margin-top:12px;text-align:center}
.form-msg.ok{background:rgba(72,187,120,.2);border:1px solid rgba(72,187,120,.4);color:#9ae6b4}

/* ═══ FOOTER ═══ */
footer{background:#0b1530;padding:28px 24px;text-align:center}
footer .brand{font-family:'Playfair Display',serif;font-size:20px;color:var(--white);font-weight:700;margin-bottom:6px}
footer p{font-size:11px;color:rgba(255,255,255,.25);line-height:1.8;letter-spacing:.5px}
footer a{color:var(--accent2);text-decoration:none}

/* Lightbox */
#lb{display:none;position:fixed;inset:0;background:rgba(0,0,0,.93);z-index:999;align-items:center;justify-content:center;cursor:zoom-out}
#lb.open{display:flex}
#lb img{max-width:90vw;max-height:88vh;object-fit:contain;border-radius:4px}
#lb-x{position:absolute;top:16px;right:24px;color:#fff;font-size:28px;cursor:pointer;opacity:.6;transition:opacity .2s}
#lb-x:hover{opacity:1}

@media(max-width:768px){
  .reg-grid,.frow{grid-template-columns:1fr}
  .hero-content{padding:28px 16px}
  .section{padding:24px 16px}
  footer{padding:20px 16px}
}
</style>
</head>
<body>

<!-- TOP BANNER -->
<div class="top-banner">
  <p>{{ status }} — {{ builder }}{% if location %} · {{ location }}{% endif %}
    <a href="#register">Register Now →</a>
  </p>
</div>

<!-- HERO -->
<section class="hero" style="background-image:url('{{ hero_image_url }}')">
  <div class="hero-overlay"></div>
  <div class="hero-content">
    <span class="hero-badge">{{ status }}</span>
    <h1>{{ name }}</h1>
  </div>
</section>

<!-- HERO DETAILS -->
<div class="hero-details">
  <p class="hero-sub">{{ description.split('\n')[0][:200] }}</p>
  {% if units %}
  <div class="hero-prices">
    {% for u in units[:3] %}
    {% if u.price %}
    <div class="hero-price-tag">
      <div class="label">{{ u.floorplan or u.address or 'Home' }}</div>
      <div class="value">{{ u.price }}</div>
    </div>
    {% endif %}
    {% endfor %}
  </div>
  {% endif %}
  <a href="#register" class="hero-cta">Register Your Interest</a>
</div>

<!-- ABOUT -->
<section class="section section-white">
  <div class="wrap">
    <div class="about-section">
      <div class="about-card">
        <p class="section-label">About</p>
        <h2 class="section-title">{{ name }}</h2>
        <div class="about-divider"></div>
        <div class="about-text">
          {% for p in description.split('\n\n') %}
          <p>{{ p }}</p>
          {% endfor %}
        </div>
      </div>
    </div>
  </div>
</section>

<!-- GALLERY -->
{% if gallery_images %}
<section class="section section-light">
  <div class="wrap">
    <p class="section-label">Gallery</p>
    <h2 class="section-title">Photos &amp; Renderings</h2>
    <div class="gallery-wrap">
      <button class="gallery-arrow gallery-arrow-left" onclick="scrollGallery(this,-300)">‹</button>
      <div class="gallery-grid" id="gallery">
        {% for img_url in gallery_images %}
        <img src="{{ img_url }}" alt="{{ name }}" loading="lazy" onclick="openLb(this.src)">
        {% endfor %}
      </div>
      <button class="gallery-arrow gallery-arrow-right" onclick="scrollGallery(this,300)">›</button>
    </div>
  </div>
</section>
{% endif %}

<!-- UNITS -->
{% if units %}
<section class="section section-white">
  <div class="wrap">
    <p class="section-label">Available Homes</p>
    <h2 class="section-title">Properties at {{ name }}</h2>
    <div class="units-grid">
      {% for u in units %}
      {% if u.address or u.floorplan or u.price %}
      {% set sl = (u.status or '')|lower %}
      {% if 'quickstart' in sl %}{% set bc='badge-qs' %}
      {% elif 'coming soon' in sl %}{% set bc='badge-cs' %}
      {% elif 'available' in sl or 'ready' in sl %}{% set bc='badge-avail' %}
      {% else %}{% set bc='badge-def' %}{% endif %}
      <div class="unit-card">
        <div class="unit-img">
          {% if u.image_url %}<img src="{{ u.image_url }}" alt="{{ u.address or u.floorplan }}" loading="lazy" onclick="openLb(this.src)">{% endif %}
          {% if u.status %}<span class="unit-badge {{ bc }}">{{ u.status }}</span>{% endif %}
        </div>
        <div class="unit-body">
          {% if u.address %}<h3 class="unit-addr">{{ u.address }}</h3>{% endif %}
          {% if u.floorplan %}<p class="unit-fp">{{ u.floorplan }}</p>{% endif %}
          {% set specs=[] %}
          {% if u.bedrooms %}{% set _=specs.append(u.bedrooms~' bed') %}{% endif %}
          {% if u.bathrooms %}{% set _=specs.append(u.bathrooms~' bath') %}{% endif %}
          {% if u.sqft %}{% set _=specs.append(u.sqft~' sqft') %}{% endif %}
          {% if u.garage %}{% set _=specs.append(u.garage) %}{% endif %}
          {% if specs %}<p class="unit-specs">{{ specs|join(' · ') }}</p>{% endif %}
          {% if u.description %}<p class="unit-desc">{{ u.description[:180] }}</p>{% endif %}
          {% if u.price %}<p class="unit-price">{{ u.price }}</p>{% endif %}
        </div>
      </div>
      {% endif %}
      {% endfor %}
    </div>
  </div>
</section>
{% endif %}

<!-- QUICK FACTS -->
<section class="section section-dark">
  <div class="wrap">
    <p class="section-label">Quick Facts</p>
    <h2 class="section-title">Community Details</h2>
    <div class="facts-grid">
      {% if builder %}<div class="fact-card"><div class="fact-label">Developer</div><div class="fact-value">{{ builder }}</div></div>{% endif %}
      {% if location %}<div class="fact-card"><div class="fact-label">Location</div><div class="fact-value">{{ location }}</div></div>{% endif %}
      {% if price_range %}<div class="fact-card"><div class="fact-label">Pricing</div><div class="fact-value">{{ price_range }}</div></div>{% endif %}
      {% if status %}<div class="fact-card"><div class="fact-label">Status</div><div class="fact-value">{{ status }}</div></div>{% endif %}
      {% if contact_phone %}<div class="fact-card"><div class="fact-label">Contact</div><div class="fact-value">{{ contact_phone }}</div></div>{% endif %}
    </div>
  </div>
</section>

<!-- REGISTER -->
<section class="section section-dark" id="register">
  <div class="wrap">
    <div class="reg-grid">
      <div class="reg-copy">
        <p class="section-label">Register Your Interest</p>
        <h2 class="section-title">Be the First to Know</h2>
        <p>Register for priority access, detailed floor plans, pricing updates,
          and exclusive launch event invitations for {{ name }}{% if location %} in {{ location }}{% endif %}.</p>
      </div>
      <form class="reg-form" id="regForm" onsubmit="return regSubmit(event)">
        <div class="frow">
          <div class="fg"><label>First Name *</label><input type="text" name="first_name" placeholder="John" required></div>
          <div class="fg"><label>Last Name *</label><input type="text" name="last_name" placeholder="Smith" required></div>
        </div>
        <div class="fg"><label>Email *</label><input type="email" name="email" placeholder="john@example.com" required></div>
        <div class="fg"><label>Phone</label><input type="tel" name="phone" placeholder="+1 (416) 000-0000"></div>
        <div class="frow">
          <div class="fg"><label>Interest</label>
            <select name="unit_interest"><option value="">Any available</option>
            {% for u in units %}<option value="{{ u.address }}">{{ u.address or u.floorplan }}</option>{% endfor %}
            </select></div>
          <div class="fg"><label>Timeline</label>
            <select name="timeline"><option value="">Select...</option>
            <option>ASAP</option><option>Within 3 months</option><option>Within 6 months</option><option>Just exploring</option>
            </select></div>
        </div>
        <div class="fg"><label>Message</label><textarea name="message" placeholder="Any questions..."></textarea></div>
        <button type="submit" class="btn-register">Register Interest</button>
        <div class="form-msg ok" id="formMsg">✓ Thank you! We will be in touch shortly.</div>
      </form>
    </div>
  </div>
</section>

<!-- FOOTER -->
<footer>
  <p>&copy; {{ year }} {{ builder }}{% if url %} · <a href="{{ url }}" target="_blank">Visit Original Listing</a>{% endif %}
    · Prices &amp; availability subject to change.
    {% if contact_phone %}<br>{{ contact_phone }}{% endif %}
  </p>
</footer>

<!-- LIGHTBOX -->
<div id="lb" onclick="closeLb()"><span id="lb-x">&times;</span><img id="lb-img" src="" alt=""></div>

<script>
function openLb(src){document.getElementById('lb-img').src=src;document.getElementById('lb').classList.add('open')}
function closeLb(){document.getElementById('lb').classList.remove('open')}
document.addEventListener('keydown',e=>{if(e.key==='Escape')closeLb()});
function scrollGallery(btn,dx){btn.parentElement.querySelector('.gallery-grid').scrollBy({left:dx,behavior:'smooth'})}
function regSubmit(e){e.preventDefault();document.getElementById('formMsg').style.display='block';e.target.reset();return false}
</script>
</body>
</html>"""



# ═════════════════════════════════════════════════════════════════════════════
#  MAIN RENDER FUNCTION
# ═════════════════════════════════════════════════════════════════════════════
def render_community_page(community: dict, embed_local: bool = True) -> str:
    """Render a community dict into a full standalone HTML page."""
    name = (community.get("community_name") or "Community").strip()
    builder = _clean(community.get("builder")) or "Builder"
    location = _clean(community.get("location"))
    status = _clean(community.get("status"))
    price_range = _clean(community.get("price_range"))
    contact_phone = _clean(community.get("contact_phone"))
    url = community.get("url", "")

    description = (community.get("marketing_description") or "").strip()
    if not description or len(description) < 50:
        description = _clean(community.get("description")) or (
            f"{name} is a new community by {builder}"
            + (f" in {location}." if location else ".")
            + " Register your interest today for priority access and exclusive updates."
        )

    hero_image_url = _get_hero_image(community, embed_local=embed_local)
    gallery_images = _get_gallery_images(community, embed_local=embed_local, limit=12)

    # Smart-scored fallback pool
    fallback_pool = _build_scored_fallback_pool(community, embed_local, hero_image_url)

    clean_units = []
    for i, unit in enumerate(community.get("properties") or []):
        if fallback_pool:
            unit["_fallback_idx"] = i % len(fallback_pool)
        clean_units.append({
            "address":     _clean(unit.get("address")),
            "floorplan":   _clean(unit.get("floorplan")),
            "price":       _clean(unit.get("price")),
            "status":      _clean(unit.get("status")),
            "bedrooms":    _clean(unit.get("bedrooms")),
            "bathrooms":   _clean(unit.get("bathrooms")),
            "sqft":        _clean(unit.get("sqft")),
            "garage":      _clean(unit.get("garage")),
            "description": _clean(unit.get("description")),
            "image_url":   _get_unit_image(unit, embed_local=embed_local, fallback_pool=fallback_pool),
        })

    tmpl = Template(PAGE_TEMPLATE)
    return tmpl.render(
        name           = name,
        location       = location,
        builder        = builder,
        status         = status,
        price_range    = price_range,
        contact_phone  = contact_phone,
        url            = url,
        units          = clean_units,
        hero_image_url = hero_image_url,
        gallery_images = gallery_images,
        description    = description,
        year           = datetime.now().year,
    )
