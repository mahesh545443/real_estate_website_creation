"""
page_renderer.py
================
Renders a community landing page using the EXACT same design as app.py.
Includes smart image scoring so unit cards get EXTERIOR/PROPERTY images,
not lifestyle photos (people, pets, food, interiors).
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

    # STRONG PENALTIES — lifestyle / people / food images
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

    # PENALTIES — interior rooms
    interior_terms = [
        "kitchen", "bedroom", "bathroom", "ensuite", "dining_room",
        "living_room", "closet", "laundry", "mudroom", "pantry",
        "garage_interior", "basement",
    ]
    for term in interior_terms:
        if term in text:
            score -= 5

    # BONUSES — exterior / streetscape / rendering terms
    exterior_terms = [
        "exterior", "elevation", "streetscape", "facade", "front",
        "rendering", "render_", "townhome", "townhouse", "home_",
        "building", "architecture", "collection", "model",
        "backyard", "yard", "outdoor_home",
    ]
    for term in exterior_terms:
        if term in text:
            score += 20

    # STRONG BONUSES — property-card terms
    if any(t in text for t in ["3-storey", "3storey", "2-storey", "2storey",
                                "back-to-back", "backtoback", "rear-lane",
                                "rearlane", "detached"]):
        score += 30

    # Landscape bonus
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
#  HTML TEMPLATE
# ═════════════════════════════════════════════════════════════════════════════
PAGE_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{{ name }} – {{ builder }}</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:ital,wght@0,300;0,400;0,600;1,300&family=Montserrat:wght@300;400;500;600&display=swap" rel="stylesheet">
  <style>
    *,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
    :root{
      --navy:#0f1923;--navy2:#162030;
      --gold:#c9a050;--gold2:#e8c070;
      --cream:#f5f0e8;--warm:#ede8df;
      --text:#2a2a2a;--muted:#7a7a7a;
    }
    html{scroll-behavior:smooth}
    body{font-family:'Montserrat',sans-serif;background:var(--cream);color:var(--text);overflow-x:hidden}

    .hero{position:relative;height:90vh;min-height:520px;display:flex;align-items:flex-end;overflow:hidden}
    .hero-bg{position:absolute;inset:0;background-size:cover;background-position:center;
             animation:zoomIn 14s ease-out forwards}
    @keyframes zoomIn{from{transform:scale(1.06)}to{transform:scale(1.0)}}
    .hero-overlay{position:absolute;inset:0;
      background:linear-gradient(to top,rgba(10,16,26,.92) 0%,rgba(10,16,26,.35) 55%,rgba(10,16,26,.05) 100%)}
    .hero-content{position:relative;z-index:2;width:100%;max-width:1080px;margin:0 auto;
                  padding:0 48px 60px;animation:up .9s .2s both}
    @keyframes up{from{opacity:0;transform:translateY(30px)}to{opacity:1;transform:none}}
    .eyebrow{font-size:10px;letter-spacing:4px;color:var(--gold);text-transform:uppercase;margin-bottom:12px}
    .hero-title{font-family:'Cormorant Garamond',serif;font-size:clamp(44px,7vw,80px);
                font-weight:300;color:#fff;line-height:1.05;letter-spacing:-1px;margin-bottom:18px}
    .hero-title em{font-style:italic;color:var(--gold2)}
    .hero-pills{display:flex;gap:24px;flex-wrap:wrap}
    .pill{font-size:11px;letter-spacing:1.5px;text-transform:uppercase;color:rgba(255,255,255,.6)}
    .pill b{color:#fff}
    .sep{width:1px;height:14px;background:rgba(255,255,255,.25);align-self:center}

    .wrap{max-width:1080px;margin:0 auto;padding:0 48px}
    .s-label{font-size:10px;letter-spacing:4px;text-transform:uppercase;
             color:var(--gold);font-weight:500;margin-bottom:10px}
    .s-title{font-family:'Cormorant Garamond',serif;
             font-size:clamp(26px,4vw,40px);font-weight:300;
             color:var(--navy);line-height:1.15;letter-spacing:-.5px}

    .desc-section{padding:80px 0 56px}
    .desc-grid{display:grid;grid-template-columns:1fr 2fr;gap:64px;align-items:start}
    .desc-text{font-size:15px;color:#444;line-height:1.9}
    .desc-text p+p{margin-top:18px}

    .gallery-section{padding:16px 0 72px}
    .gallery{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));
             gap:12px;margin-top:28px}
    .gallery img{width:100%;height:190px;object-fit:cover;border-radius:3px;display:block;
                 cursor:zoom-in;transition:transform .4s,box-shadow .4s}
    .gallery img:hover{transform:scale(1.03);box-shadow:0 10px 28px rgba(0,0,0,.18)}

    .units-section{padding:0 0 80px}
    .units-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(290px,1fr));
                gap:22px;margin-top:32px}
    .card{background:#fff;border-radius:3px;overflow:hidden;box-shadow:0 2px 14px rgba(0,0,0,.06);
          transition:transform .3s,box-shadow .3s;
          opacity:0;transform:translateY(20px);animation:up .6s both}
    .card:hover{transform:translateY(-4px);box-shadow:0 14px 40px rgba(0,0,0,.12)}
    .card-img{position:relative;height:190px;overflow:hidden;background:var(--warm)}
    .card-img img{width:100%;height:100%;object-fit:cover;transition:transform .5s}
    .card:hover .card-img img{transform:scale(1.06)}
    .badge{position:absolute;top:12px;left:12px;font-size:9px;letter-spacing:2px;
           font-weight:600;text-transform:uppercase;padding:3px 9px;border-radius:2px}
    .b-ready{background:var(--gold);color:var(--navy)}
    .b-soon{background:#2d6a4f;color:#fff}
    .b-sold{background:#8b0000;color:#fff}
    .b-def{background:rgba(0,0,0,.5);color:#fff}
    .card-body{padding:20px 22px 24px}
    .card-addr{font-family:'Cormorant Garamond',serif;font-size:17px;color:var(--navy);margin-bottom:4px}
    .card-fp{font-size:11px;color:var(--muted);margin-bottom:8px}
    .card-desc{font-size:12px;color:#666;line-height:1.6;margin-bottom:12px}
    .card-price{font-family:'Cormorant Garamond',serif;font-size:24px;font-weight:600;color:var(--navy)}

    .reg-section{background:var(--navy);padding:96px 0}
    .reg-inner{display:grid;grid-template-columns:1fr 1fr;gap:72px;align-items:start}
    .reg-copy .s-label{color:var(--gold)}
    .reg-copy .s-title{color:#fff;margin-bottom:18px}
    .reg-copy p{font-size:14px;color:rgba(255,255,255,.5);line-height:1.85}
    .reg-form{background:rgba(255,255,255,.04);border:1px solid rgba(201,160,80,.18);
              border-radius:3px;padding:38px}
    .frow{display:grid;grid-template-columns:1fr 1fr;gap:14px}
    .fg{margin-bottom:16px}
    .fg label{display:block;font-size:10px;letter-spacing:2px;text-transform:uppercase;
              color:rgba(255,255,255,.4);margin-bottom:7px}
    .fg input,.fg select,.fg textarea{
      width:100%;background:rgba(255,255,255,.06);border:1px solid rgba(255,255,255,.12);
      border-radius:3px;padding:11px 14px;color:#fff;
      font-family:'Montserrat',sans-serif;font-size:13px;outline:none;
      transition:border-color .2s,background .2s}
    .fg input::placeholder,.fg textarea::placeholder{color:rgba(255,255,255,.2)}
    .fg input:focus,.fg select:focus,.fg textarea:focus{border-color:var(--gold);background:rgba(255,255,255,.09)}
    .fg select option{background:var(--navy2);color:#fff}
    .fg textarea{resize:vertical;min-height:80px}
    .btn-submit{width:100%;background:var(--gold);color:var(--navy);border:none;
                padding:14px;font-family:'Montserrat',sans-serif;font-size:11px;
                font-weight:600;letter-spacing:3px;text-transform:uppercase;
                border-radius:3px;cursor:pointer;transition:background .2s,transform .15s;margin-top:4px}
    .btn-submit:hover{background:var(--gold2);transform:translateY(-1px)}
    .form-msg{display:none;padding:12px 16px;border-radius:3px;font-size:13px;
              margin-top:14px;text-align:center}
    .form-msg.ok{background:rgba(45,106,79,.3);border:1px solid rgba(45,106,79,.5);color:#a8e6c3}

    #lb{display:none;position:fixed;inset:0;background:rgba(0,0,0,.93);z-index:999;
        align-items:center;justify-content:center;cursor:zoom-out}
    #lb.open{display:flex}
    #lb img{max-width:90vw;max-height:88vh;object-fit:contain;border-radius:3px}
    #lb-x{position:absolute;top:18px;right:24px;color:#fff;font-size:30px;
           cursor:pointer;font-weight:300;opacity:.6;transition:opacity .2s;line-height:1}
    #lb-x:hover{opacity:1}

    footer{background:#080e17;padding:28px 48px;text-align:center}
    footer p{font-size:11px;color:rgba(255,255,255,.2);letter-spacing:.5px}
    footer a{color:var(--gold);text-decoration:none}

    @media(max-width:768px){
      .hero-content,.wrap{padding-left:24px;padding-right:24px}
      .desc-grid,.reg-inner,.frow{grid-template-columns:1fr}
      footer{padding:24px}
    }
  </style>
</head>
<body>

<section class="hero">
  {% if hero_image_url %}
  <div class="hero-bg" style="background-image:url('{{ hero_image_url }}')"></div>
  {% else %}
  <div class="hero-bg" style="background:linear-gradient(135deg,#0f1923,#1a2a3d)"></div>
  {% endif %}
  <div class="hero-overlay"></div>
  <div class="hero-content">
    <p class="eyebrow">{{ builder }}{% if location %} &nbsp;·&nbsp; {{ location }}{% endif %}{% if status %} &nbsp;·&nbsp; {{ status }}{% endif %}</p>
    <h1 class="hero-title">
      {% set words = name.split() %}
      {% if words|length > 1 %}
        {{ words[0] }}<br><em>{{ words[1:] | join(' ') }}</em>
      {% else %}
        <em>{{ name }}</em>
      {% endif %}
    </h1>
    <div class="hero-pills">
      {% if status %}<span class="pill"><b>{{ status }}</b></span>{% if units|length > 0 or location %}<span class="sep"></span>{% endif %}{% endif %}
      {% if units|length > 0 %}<span class="pill"><b>{{ units|length }}</b> Unit{{ 's' if units|length != 1 else '' }}</span>{% if location %}<span class="sep"></span>{% endif %}{% endif %}
      {% if location %}<span class="pill">{{ location }}</span>{% endif %}
      {% if price_range %}<span class="sep"></span><span class="pill"><b>{{ price_range }}</b></span>{% endif %}
    </div>
  </div>
</section>

<section class="desc-section">
  <div class="wrap">
    <div class="desc-grid">
      <div>
        <p class="s-label">About</p>
        <h2 class="s-title">{{ name }}</h2>
      </div>
      <div class="desc-text">
        {% for para in description.split('\n\n') %}{% if para.strip() %}
          <p>{{ para.strip() }}</p>
        {% endif %}{% endfor %}
      </div>
    </div>
  </div>
</section>

{% if gallery_images %}
<section class="gallery-section">
  <div class="wrap">
    <p class="s-label">Gallery</p>
    <h2 class="s-title">Photos &amp; Renderings</h2>
    <div class="gallery">
      {% for img_url in gallery_images %}
      <img src="{{ img_url }}" alt="{{ name }}" loading="lazy" onclick="openLb(this.src)">
      {% endfor %}
    </div>
  </div>
</section>
{% endif %}

{% if units %}
<section class="units-section">
  <div class="wrap">
    <p class="s-label">Available Homes</p>
    <h2 class="s-title">Properties at {{ name }}</h2>
    <div class="units-grid">
      {% for unit in units %}
        {% if unit.address or unit.floorplan or unit.price %}
        {% set sl = (unit.status or '') | lower %}
        {% if 'ready' in sl or 'available' in sl %}{% set bc='b-ready' %}
        {% elif 'coming soon' in sl or 'launching' in sl %}{% set bc='b-soon' %}
        {% elif 'sold' in sl %}{% set bc='b-sold' %}
        {% else %}{% set bc='b-def' %}{% endif %}
      <div class="card" style="animation-delay:{{ loop.index0 * 0.08 }}s">
        <div class="card-img">
          {% if unit.image_url %}
          <img src="{{ unit.image_url }}" alt="{{ unit.address or unit.floorplan }}" loading="lazy" onclick="openLb(this.src)">
          {% endif %}
          {% if unit.status %}<span class="badge {{ bc }}">{{ unit.status }}</span>{% endif %}
        </div>
        <div class="card-body">
          {% if unit.address %}<h3 class="card-addr">{{ unit.address }}</h3>{% endif %}
          {% if unit.floorplan %}<p class="card-fp">{{ unit.floorplan }}</p>{% endif %}
          {% set specs = [] %}
          {% if unit.bedrooms %}{% set _ = specs.append(unit.bedrooms ~ ' bed') %}{% endif %}
          {% if unit.bathrooms %}{% set _ = specs.append(unit.bathrooms ~ ' bath') %}{% endif %}
          {% if unit.sqft %}{% set _ = specs.append(unit.sqft ~ ' sqft') %}{% endif %}
          {% if unit.garage %}{% set _ = specs.append(unit.garage) %}{% endif %}
          {% if specs %}<p class="card-fp">{{ specs | join(' · ') }}</p>{% endif %}
          {% if unit.description %}<p class="card-desc">{{ unit.description[:200] }}</p>{% endif %}
          {% if unit.price %}<p class="card-price">{{ unit.price }}</p>{% endif %}
        </div>
      </div>
        {% endif %}
      {% endfor %}
    </div>
  </div>
</section>
{% endif %}

<section class="reg-section" id="register">
  <div class="wrap">
    <div class="reg-inner">
      <div class="reg-copy">
        <p class="s-label">Register Your Interest</p>
        <h2 class="s-title">Be the <em style="font-style:italic;color:var(--gold2)">First to Know</em></h2>
        <p style="margin-top:16px">
          Register for priority access, detailed floor plans, pricing updates,
          and exclusive launch event invitations for {{ name }}{% if location %} in {{ location }}{% endif %}.
        </p>
      </div>
      <form class="reg-form" id="regForm" onsubmit="return fakeSubmit(event)">
        <div class="frow">
          <div class="fg"><label>First Name *</label>
            <input type="text" name="first_name" placeholder="John" required></div>
          <div class="fg"><label>Last Name *</label>
            <input type="text" name="last_name" placeholder="Smith" required></div>
        </div>
        <div class="fg"><label>Email *</label>
          <input type="email" name="email" placeholder="john@example.com" required></div>
        <div class="fg"><label>Phone</label>
          <input type="tel" name="phone" placeholder="+1 (416) 000-0000"></div>
        <div class="frow">
          <div class="fg"><label>Unit Interest</label>
            <select name="unit_interest">
              <option value="">Any available</option>
              {% for unit in units %}{% if unit.address %}
              <option value="{{ unit.address }}">{{ unit.address }}</option>
              {% endif %}{% endfor %}
            </select>
          </div>
          <div class="fg"><label>Timeline</label>
            <select name="timeline">
              <option value="">Select...</option>
              <option>ASAP</option>
              <option>Within 3 months</option>
              <option>Within 6 months</option>
              <option>Just exploring</option>
            </select>
          </div>
        </div>
        <div class="fg"><label>Message</label>
          <textarea name="message" placeholder="Any questions or preferences..."></textarea></div>
        <button type="submit" class="btn-submit">Register Interest</button>
        <div class="form-msg ok" id="formMsg">✓ Thank you! We will be in touch shortly.</div>
      </form>
    </div>
  </div>
</section>

<footer>
  <p>&copy; {{ year }} {{ builder }}{% if url %} &nbsp;·&nbsp; <a href="{{ url }}" target="_blank">Visit Original Listing</a>{% endif %}
    &nbsp;·&nbsp; Prices &amp; availability subject to change.
    {% if contact_phone %}&nbsp;·&nbsp; {{ contact_phone }}{% endif %}
  </p>
</footer>

<div id="lb" onclick="closeLb()">
  <span id="lb-x" onclick="closeLb()">&times;</span>
  <img id="lb-img" src="" alt="">
</div>

<script>
  function openLb(src){document.getElementById('lb-img').src=src;document.getElementById('lb').classList.add('open')}
  function closeLb(){document.getElementById('lb').classList.remove('open')}
  document.addEventListener('keydown',e=>{if(e.key==='Escape')closeLb()});
  function fakeSubmit(e){
    e.preventDefault();
    document.getElementById('formMsg').style.display='block';
    e.target.reset();
    return false;
  }
  const obs=new IntersectionObserver(entries=>{
    entries.forEach(ent=>{if(ent.isIntersecting){ent.target.style.opacity='1';ent.target.style.transform='none'}})
  },{threshold:0.1});
  document.querySelectorAll('.card').forEach(c=>obs.observe(c));
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