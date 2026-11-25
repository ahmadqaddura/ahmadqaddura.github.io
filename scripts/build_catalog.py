#!/usr/bin/env python3
"""
Builds cartoons.json, static SEO/social-shareable cartoon pages under c/*.html,
and updates sitemap.xml from the files in cartoons/.
Zero external dependencies (Python 3 standard library only).
"""

import html
import json
import os
import re
import struct
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parent.parent
CARTOONS_DIR = ROOT / "cartoons"
OUT_DIR = ROOT / "c"
SITE_URL = "https://ahmadqaddura.com"
IMG_RE = re.compile(r"\.(webp|jpe?g|png|gif)$", re.IGNORECASE)

MONTHS = {
    "01": "January", "02": "February", "03": "March", "04": "April",
    "05": "May", "06": "June", "07": "July", "08": "August",
    "09": "September", "10": "October", "11": "November", "12": "December",
}


def get_image_size(path: Path):
    """Read (width, height) for WebP, PNG, GIF, or JPEG using stdlib only."""
    try:
        with open(path, "rb") as f:
            header = f.read(64)
            # PNG
            if header.startswith(b"\x89PNG\r\n\x1a\n") and len(header) >= 24:
                w, h = struct.unpack(">II", header[16:24])
                return int(w), int(h)
            # GIF
            if header[:6] in (b"GIF87a", b"GIF89a") and len(header) >= 10:
                w, h = struct.unpack("<HH", header[6:10])
                return int(w), int(h)
            # WebP
            if header[:4] == b"RIFF" and header[8:12] == b"WEBP":
                chunk = header[12:16]
                if chunk == b"VP8X" and len(header) >= 30:
                    w = 1 + int.from_bytes(header[24:27], "little")
                    h = 1 + int.from_bytes(header[27:30], "little")
                    return w, h
                if chunk == b"VP8 " and len(header) >= 30:
                    w, h = struct.unpack("<HH", header[26:30])
                    return w & 0x3FFF, h & 0x3FFF
                if chunk == b"VP8L" and len(header) >= 25:
                    b0, b1, b2, b3 = header[21:25]
                    w = 1 + (((b1 & 0x3F) << 8) | b0)
                    h = 1 + (((b3 & 0x0F) << 10) | (b2 << 2) | ((b1 & 0xC0) >> 6))
                    return w, h
            # JPEG
            if header[:2] == b"\xff\xd8":
                f.seek(2)
                while True:
                    byte = f.read(1)
                    if not byte:
                        break
                    while byte == b"\xff":
                        byte = f.read(1)
                    if not byte:
                        break
                    marker = byte[0]
                    if marker in (0xD8, 0xD9, 0x01) or (0xD0 <= marker <= 0xD7):
                        continue
                    seg_len_bytes = f.read(2)
                    if len(seg_len_bytes) < 2:
                        break
                    seg_len = struct.unpack(">H", seg_len_bytes)[0]
                    if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                        data = f.read(5)
                        if len(data) == 5:
                            h, w = struct.unpack(">HH", data[1:5])
                            return int(w), int(h)
                        break
                    f.seek(seg_len - 2, os.SEEK_CUR)
    except Exception:
        pass
    return None, None


def format_date(d: str) -> str:
    parts = d.split("-")
    if len(parts) == 3:
        return f"{int(parts[2])} {MONTHS.get(parts[1], parts[1])} {parts[0]}"
    if len(parts) == 2:
        return f"{MONTHS.get(parts[1], parts[1])} {parts[0]}"
    return d


def make_slug(base: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", base).strip("-")
    return slug or "cartoon"


def suffix_sort_key(item: dict):
    base = item["base"]
    date = item["date"]
    m = re.match(r"^(\d{4}-\d{2}-\d{2})(?:[_-](.+)|([a-zA-Z]))?$", base)
    if not m:
        return (date, 0, base.lower())
    suffix = (m.group(2) or m.group(3) or "").strip()
    if not suffix:
        return (date, 0, "")
    if re.fullmatch(r"\d+", suffix):
        return (date, int(suffix), "")
    if re.fullmatch(r"[a-zA-Z]", suffix):
        return (date, ord(suffix.lower()) - ord("a") + 1, suffix.lower())
    return (date, 1, suffix.lower())


def load_cartoons():
    items = []
    if not CARTOONS_DIR.is_dir():
        return items

    for p in sorted(CARTOONS_DIR.iterdir()):
        if not p.is_file() or not IMG_RE.search(p.name):
            continue
        base = IMG_RE.sub("", p.name)
        m = re.match(r"^(\d{4}-\d{2}-\d{2})(?:[_-](.+)|([a-zA-Z]))?$", base)
        date = m.group(1) if m else "2026-01-01"
        suffix = (m.group(2) or m.group(3) or "").strip() if m else ""
        fallback_title = ""
        if suffix and not re.fullmatch(r"(?:\d+|[a-zA-Z])", suffix):
            fallback_title = re.sub(r"[-_]+", " ", suffix).strip()

        title = fallback_title
        tags = []
        desc = ""
        txt_path = None
        for cand in (CARTOONS_DIR / f"{base}.txt", CARTOONS_DIR / f"{base}.TXT"):
            if cand.is_file():
                txt_path = cand
                break
        if txt_path is None:
            base_lower = base.lower()
            for entry in CARTOONS_DIR.iterdir():
                if entry.is_file() and entry.suffix.lower() == ".txt" and entry.stem.lower() == base_lower:
                    txt_path = entry
                    break
        if txt_path is not None:
            raw_lines = txt_path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
            # Drop leading blank lines
            while raw_lines and not raw_lines[0].strip():
                raw_lines.pop(0)
            if raw_lines:
                title = raw_lines[0].strip()
                rest = raw_lines[1:]
                tag_line_idx = None
                for idx, line in enumerate(rest):
                    stripped = line.strip()
                    if stripped and stripped.startswith("#"):
                        tokens = re.split(r"[\s,]+", stripped)
                        if tokens and all(t.startswith("#") for t in tokens):
                            tag_line_idx = idx
                            break
                if tag_line_idx is not None:
                    raw_tags = re.split(r"[\s,]+", rest[tag_line_idx].strip())
                    tags = [t.lstrip("#").strip() for t in raw_tags if t.lstrip("#").strip()]
                    desc_lines = [l for i, l in enumerate(rest) if i != tag_line_idx]
                    desc = "\n".join(desc_lines).strip()
                else:
                    while rest and not rest[0].strip():
                        rest.pop(0)
                    if rest:
                        candidate_tags = rest[0].strip()
                        if candidate_tags.startswith("#") or (len(rest) >= 2 and len(candidate_tags.split()) <= 10 and not candidate_tags.endswith(".")):
                            raw_tags = re.split(r"[\s,]+", candidate_tags)
                            tags = [t.lstrip("#").strip() for t in raw_tags if t.lstrip("#").strip()]
                            desc = "\n".join(rest[1:]).strip()
                        else:
                            desc = "\n".join(rest).strip()

        w, h = get_image_size(p)
        slug = make_slug(base)
        items.append({
            "name": p.name,
            "base": base,
            "slug": slug,
            "date": date,
            "title": title,
            "tags": tags,
            "desc": desc,
            "image": f"cartoons/{quote(p.name)}",
            "page": f"c/{quote(slug)}.html",
            "width": w,
            "height": h,
        })

    # Ensure unique slugs
    seen = {}
    for item in items:
        s = item["slug"]
        if s in seen:
            seen[s] += 1
            item["slug"] = f"{s}-{seen[s]}"
            item["page"] = f"c/{quote(item['slug'])}.html"
        else:
            seen[s] = 1

    items.sort(key=suffix_sort_key, reverse=True)
    return items


def render_cartoon_page(items, idx: int) -> str:
    c = items[idx]
    title_raw = c["title"] or format_date(c["date"])
    title_esc = html.escape(title_raw, quote=True)
    date_formatted = format_date(c["date"])
    desc_raw = c["desc"]
    desc_meta = (
        re.sub(r"\s+", " ", desc_raw).strip()
        if desc_raw
        else f"Editorial cartoon '{title_raw}' by Ahmad Qaddura ({date_formatted})."
    )
    if len(desc_meta) > 160:
        desc_meta = desc_meta[:157].rstrip() + "..."
    desc_meta_esc = html.escape(desc_meta, quote=True)

    canonical = f"{SITE_URL}/{c['page']}"
    img_abs = f"{SITE_URL}/{c['image']}"
    img_rel = f"../{c['image']}"

    newer_href = f"{quote(items[idx - 1]['slug'])}.html" if idx > 0 else "#"
    older_href = f"{quote(items[idx + 1]['slug'])}.html" if idx < len(items) - 1 else "#"
    newer_cls = "" if idx > 0 else ' class="disabled" aria-disabled="true"'
    older_cls = "" if idx < len(items) - 1 else ' class="disabled" aria-disabled="true"'

    tags_html = ""
    if c["tags"]:
        pills = "".join(
            f'<a class="tag-pill" href="../gallery.html?q={quote(t)}">#{html.escape(t)}</a>'
            for t in c["tags"]
        )
        tags_html = f'<div class="tags-wrap">{pills}</div>'

    desc_html = f'<div class="cartoon-desc">{html.escape(desc_raw)}</div>' if desc_raw else ""

    share_text = f"{title_raw} — Cartoon by Ahmad Qaddura"
    x_share = f"https://twitter.com/intent/tweet?text={quote(share_text)}&url={quote(canonical)}&via=qadduracartoon"
    wa_share = f"https://api.whatsapp.com/send?text={quote(share_text + ' ' + canonical)}"
    fb_share = f"https://www.facebook.com/sharer/sharer.php?u={quote(canonical)}"

    others = [it for i, it in enumerate(items) if i != idx][:4]
    more_html = ""
    if others:
        cards = "".join(
            f'''<a class="more-item" href="{quote(o['slug'])}.html">
                <img src="../{o['image']}" alt="{html.escape(o['title'] or o['date'], quote=True)}" loading="lazy">
                <div class="more-item-title">{html.escape(o['title'] or format_date(o['date']))}</div>
            </a>'''
            for o in others
        )
        more_html = f'''
            <section class="more-section">
                <div class="more-header">
                    <h3>More from the Gallery</h3>
                    <a href="../gallery.html">See all</a>
                </div>
                <div class="more-grid">{cards}</div>
            </section>'''

    ld_json = json.dumps({
        "@context": "https://schema.org",
        "@type": "VisualArtwork",
        "name": title_raw,
        "description": desc_meta,
        "image": img_abs,
        "url": canonical,
        "datePublished": c["date"],
        "artform": "Editorial Cartoon",
        "creator": {
            "@type": "Person",
            "name": "Ahmad Qaddura",
            "url": f"{SITE_URL}/",
        },
        "keywords": ", ".join(c["tags"]),
    }, ensure_ascii=False, indent=2)

    return f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title_esc} — Ahmad Qaddura</title>
    <meta name="description" content="{desc_meta_esc}">
    <link rel="canonical" href="{canonical}">
    <link rel="icon" type="image/png" href="../avatar.png">
    <link rel="apple-touch-icon" href="../avatar.png">
    <meta property="og:type" content="article">
    <meta property="og:site_name" content="Ahmad Qaddura">
    <meta property="og:url" content="{canonical}">
    <meta property="og:title" content="{title_esc} — Ahmad Qaddura">
    <meta property="og:description" content="{desc_meta_esc}">
    <meta property="og:image" content="{img_abs}">
    <meta name="twitter:card" content="summary_large_image">
    <meta name="twitter:site" content="@qadduracartoon">
    <meta name="twitter:title" content="{title_esc} — Ahmad Qaddura">
    <meta name="twitter:description" content="{desc_meta_esc}">
    <meta name="twitter:image" content="{img_abs}">
    <script type="application/ld+json">
{ld_json}
    </script>
    <link rel="stylesheet" href="../style.css">
</head>
<body>
    <header>
        <div class="container">
            <h1 class="site-title"><a href="../index.html">Ahmad Qaddura</a></h1>
            <p class="site-subtitle">Editorial Cartoonist &amp; Satirical Illustrator</p>
            <nav>
                <a href="../index.html">Home</a>
                <a href="../gallery.html" class="active">Gallery</a>
                <a href="../store.html">Store</a>
                <a href="../about.html">About &amp; Contact</a>
            </nav>
        </div>
    </header>

    <main class="container">
        <div class="cartoon-wrap">
            <div class="top-nav">
                <a href="../gallery.html">&larr; Back to Gallery</a>
                <div class="pager-links">
                    <a id="newer-link" href="{newer_href}"{newer_cls}>&larr; Newer</a>
                    <a id="older-link" href="{older_href}"{older_cls}>Older &rarr;</a>
                </div>
            </div>

            <article>
                <div class="cartoon-stage">
                    <img id="main-cartoon-img" src="{img_rel}" alt="{title_esc}" title="Click to zoom">
                    <span class="zoom-hint">Click image to zoom</span>
                </div>
                <div class="cartoon-date">{date_formatted}</div>
                <h2 class="cartoon-title">{title_esc}</h2>
                {desc_html}
                {tags_html}

                <div class="cartoon-actions">
                    <a href="../store.html" class="purchase-btn">Purchase / License Cartoon &rarr;</a>

                    <div class="share-bar" aria-label="Share this cartoon">
                        <span class="share-label">Share:</span>
                        <a href="{wa_share}" target="_blank" rel="noopener" class="share-btn" title="Share on WhatsApp">
                            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20.52 3.48A11.86 11.86 0 0 0 12.06 0C5.5 0 .16 5.34.16 11.9c0 2.1.55 4.14 1.6 5.95L0 24l6.33-1.66a11.86 11.86 0 0 0 5.73 1.46h.01c6.56 0 11.9-5.34 11.9-11.9 0-3.18-1.24-6.17-3.45-8.42zM12.07 21.8h-.01a9.87 9.87 0 0 1-5.03-1.38l-.36-.21-3.76.99 1-3.66-.24-.38a9.86 9.86 0 0 1-1.51-5.26c0-5.45 4.44-9.89 9.9-9.89 2.64 0 5.13 1.03 7 2.9a9.83 9.83 0 0 1 2.9 7c0 5.46-4.44 9.89-9.89 9.89zm5.42-7.4c-.3-.15-1.76-.87-2.03-.97-.27-.1-.47-.15-.67.15-.2.3-.77.97-.94 1.16-.17.2-.35.22-.64.08-.3-.15-1.26-.46-2.39-1.48-.88-.79-1.48-1.76-1.65-2.06-.17-.3-.02-.46.13-.6.13-.13.3-.35.45-.52.15-.17.2-.3.3-.5.1-.2.05-.37-.02-.52-.08-.15-.67-1.61-.92-2.2-.24-.58-.49-.5-.67-.51h-.57c-.2 0-.52.07-.79.37-.27.3-1.04 1.02-1.04 2.48s1.07 2.88 1.21 3.08c.15.2 2.1 3.2 5.08 4.49.71.3 1.26.49 1.69.62.71.23 1.36.2 1.87.12.57-.08 1.76-.72 2-1.41.25-.7.25-1.29.17-1.41-.07-.12-.27-.2-.57-.35z"/></svg>
                            WhatsApp
                        </a>
                        <a href="{x_share}" target="_blank" rel="noopener" class="share-btn" title="Share on X">
                            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z"/></svg>
                            X
                        </a>
                        <a href="{fb_share}" target="_blank" rel="noopener" class="share-btn" title="Share on Facebook">
                            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M22.675 0h-21.35c-.732 0-1.325.593-1.325 1.325v21.351c0 .731.593 1.324 1.325 1.324h11.495v-9.294h-3.128v-3.622h3.128v-2.671c0-3.1 1.893-4.788 4.659-4.788 1.325 0 2.463.099 2.795.143v3.24l-1.918.001c-1.504 0-1.795.715-1.795 1.763v2.313h3.587l-.467 3.622h-3.12v9.293h6.116c.73 0 1.323-.593 1.323-1.325v-21.35c0-.732-.593-1.325-1.325-1.325z"/></svg>
                            Facebook
                        </a>
                        <button type="button" id="copy-link-btn" class="share-btn" title="Copy direct link">Copy Link</button>
                        <button type="button" id="native-share-btn" class="share-btn" style="display:none;" title="More share options">Share&hellip;</button>
                    </div>
                </div>
            </article>
            {more_html}
        </div>
    </main>

    <div id="zoom-lightbox" class="zoom-lightbox" role="dialog" aria-modal="true" aria-label="Zoomed cartoon">
        <button type="button" class="zoom-close" id="zoom-close" aria-label="Close zoom">&times;</button>
        <img id="zoom-img" src="{img_rel}" alt="{title_esc}">
    </div>

    <footer>
        <div class="container">
            <div class="social-links">
                <a href="https://x.com/qadduracartoon" target="_blank" rel="noopener" aria-label="X (Twitter)" title="X (Twitter)">
                    <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z"/></svg>
                </a>
                <a href="https://www.instagram.com/ahmadqaddura2" target="_blank" rel="noopener" aria-label="Instagram" title="Instagram">
                    <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2.163c3.204 0 3.584.012 4.85.07 3.252.148 4.771 1.691 4.919 4.919.058 1.265.069 1.645.069 4.849 0 3.205-.012 3.584-.069 4.849-.149 3.225-1.664 4.771-4.919 4.919-1.266.058-1.644.07-4.85.07-3.204 0-3.584-.012-4.849-.07-3.26-.149-4.771-1.699-4.919-4.92-.058-1.265-.07-1.644-.07-4.849 0-3.204.013-3.583.07-4.849.149-3.227 1.664-4.771 4.919-4.919 1.266-.057 1.645-.069 4.849-.069zm0-2.163c-3.259 0-3.667.014-4.947.072-4.358.2-6.78 2.618-6.98 6.98-.059 1.281-.073 1.689-.073 4.948 0 3.259.014 3.668.072 4.948.2 4.358 2.618 6.78 6.98 6.98 1.281.058 1.689.072 4.948.072 3.259 0 3.668-.014 4.948-.072 4.354-.2 6.782-2.618 6.979-6.98.059-1.28.073-1.689.073-4.948 0-3.259-.014-3.667-.072-4.947-.196-4.354-2.617-6.78-6.979-6.98-1.281-.059-1.69-.073-4.949-.073zm0 5.838c-3.403 0-6.162 2.759-6.162 6.162s2.759 6.163 6.162 6.163 6.162-2.759 6.162-6.163c0-3.403-2.759-6.162-6.162-6.162zm0 10.162c-2.209 0-4-1.79-4-4 0-2.209 1.791-4 4-4s4 1.791 4 4c0 2.21-1.791 4-4 4zm6.406-11.845c-.796 0-1.441.645-1.441 1.44s.645 1.44 1.441 1.44c.795 0 1.439-.645 1.439-1.44s-.644-1.44-1.439-1.44z"/></svg>
                </a>
                <a href="https://www.facebook.com/cartoonistqaddura/" target="_blank" rel="noopener" aria-label="Facebook" title="Facebook">
                    <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M22.675 0h-21.35c-.732 0-1.325.593-1.325 1.325v21.351c0 .731.593 1.324 1.325 1.324h11.495v-9.294h-3.128v-3.622h3.128v-2.671c0-3.1 1.893-4.788 4.659-4.788 1.325 0 2.463.099 2.795.143v3.24l-1.918.001c-1.504 0-1.795.715-1.795 1.763v2.313h3.587l-.467 3.622h-3.12v9.293h6.116c.73 0 1.323-.593 1.323-1.325v-21.35c0-.732-.593-1.325-1.325-1.325z"/></svg>
                </a>
                <a href="https://www.youtube.com/@Cartoonist-Ahmad-Qaddura" target="_blank" rel="noopener" aria-label="YouTube" title="YouTube">
                    <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M23.498 6.186a3.016 3.016 0 0 0-2.122-2.136C19.505 3.545 12 3.545 12 3.545s-7.505 0-9.377.505A3.017 3.017 0 0 0 .502 6.186C0 8.07 0 12 0 12s0 3.93.502 5.814a3.016 3.016 0 0 0 2.122 2.136c1.871.505 9.376.505 9.376.505s7.505 0 9.377-.505a3.015 3.015 0 0 0 2.122-2.136C24 15.93 24 12 24 12s0-3.93-.502-5.814zM9.545 15.568V8.432L15.818 12l-6.273 3.568z"/></svg>
                </a>
            </div>
            &copy; 2026 Ahmad Qaddura. All rights reserved.
        </div>
    </footer>

    <script>
        (function () {{
            const shareUrl = {json.dumps(canonical)};
            const shareTitle = {json.dumps(share_text)};

            const copyBtn = document.getElementById("copy-link-btn");
            if (copyBtn) {{
                copyBtn.addEventListener("click", () => {{
                    const done = () => {{
                        copyBtn.classList.add("copied");
                        copyBtn.textContent = "Copied ✓";
                        setTimeout(() => {{
                            copyBtn.classList.remove("copied");
                            copyBtn.textContent = "Copy Link";
                        }}, 2200);
                    }};
                    if (navigator.clipboard && window.isSecureContext) {{
                        navigator.clipboard.writeText(shareUrl).then(done).catch(() => fallbackCopy(shareUrl, done));
                    }} else {{
                        fallbackCopy(shareUrl, done);
                    }}
                }});
            }}

            function fallbackCopy(text, cb) {{
                const ta = document.createElement("textarea");
                ta.value = text;
                ta.setAttribute("readonly", "");
                ta.style.position = "fixed";
                ta.style.left = "-9999px";
                document.body.appendChild(ta);
                ta.select();
                try {{ if (document.execCommand("copy")) cb(); }} catch (_) {{}}
                document.body.removeChild(ta);
            }}

            const nativeBtn = document.getElementById("native-share-btn");
            if (nativeBtn && navigator.share) {{
                nativeBtn.style.display = "inline-flex";
                nativeBtn.addEventListener("click", () => {{
                    navigator.share({{ title: shareTitle, url: shareUrl }}).catch(() => {{}});
                }});
            }}

            // Zoom Lightbox
            const mainImg = document.getElementById("main-cartoon-img");
            const box = document.getElementById("zoom-lightbox");
            const closeBtn = document.getElementById("zoom-close");
            function closeZoom() {{ box.classList.remove("open"); document.body.style.overflow = ""; }}
            if (mainImg && box) {{
                mainImg.addEventListener("click", () => {{
                    box.classList.add("open");
                    document.body.style.overflow = "hidden";
                }});
                closeBtn.addEventListener("click", closeZoom);
                box.addEventListener("click", (e) => {{ if (e.target === box) closeZoom(); }});
            }}

            // Keyboard navigation
            document.addEventListener("keydown", (e) => {{
                if (e.key === "Escape" && box && box.classList.contains("open")) {{
                    closeZoom();
                    return;
                }}
                if (box && box.classList.contains("open")) return;
                const newer = document.getElementById("newer-link");
                const older = document.getElementById("older-link");
                if (e.key === "ArrowLeft" && newer && !newer.classList.contains("disabled")) {{
                    window.location.href = newer.href;
                }} else if (e.key === "ArrowRight" && older && !older.classList.contains("disabled")) {{
                    window.location.href = older.href;
                }}
            }});
        }})();
    </script>
</body>
</html>
'''


def write_sitemap(items):
    urls = [
        (f"{SITE_URL}/", None, "weekly", "1.0"),
        (f"{SITE_URL}/gallery.html", None, "weekly", "0.9"),
        (f"{SITE_URL}/store.html", None, "monthly", "0.8"),
        (f"{SITE_URL}/about.html", None, "monthly", "0.8"),
    ]
    for c in items:
        urls.append((f"{SITE_URL}/{c['page']}", c["date"], "monthly", "0.7"))

    lines = ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for loc, lastmod, freq, prio in urls:
        lines.append("  <url>")
        lines.append(f"    <loc>{html.escape(loc)}</loc>")
        if lastmod:
            lines.append(f"    <lastmod>{lastmod}</lastmod>")
        lines.append(f"    <changefreq>{freq}</changefreq>")
        lines.append(f"    <priority>{prio}</priority>")
        lines.append("  </url>")
    lines.append("</urlset>")
    (ROOT / "sitemap.xml").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    items = load_cartoons()

    # Write cartoons.json
    (ROOT / "cartoons.json").write_text(
        json.dumps(items, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    # Write static pages c/<slug>.html and clean stale files
    OUT_DIR.mkdir(exist_ok=True)
    expected_files = set()
    for idx, c in enumerate(items):
        fname = f"{c['slug']}.html"
        expected_files.add(fname)
        (OUT_DIR / fname).write_text(render_cartoon_page(items, idx), encoding="utf-8")

    for existing in OUT_DIR.glob("*.html"):
        if existing.name not in expected_files:
            existing.unlink()

    # Update sitemap.xml
    write_sitemap(items)
    print(f"Built catalog for {len(items)} cartoons: cartoons.json, c/*.html, sitemap.xml")


if __name__ == "__main__":
    main()
