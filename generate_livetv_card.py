#!/usr/bin/env python3
"""
jellyfin-livetv-card

Generates a library card image for Jellyfin's "Live TV" view that matches
the auto-generated cards Jellyfin builds for every other library (Movies,
Shows, Collections, etc.) -- then uploads it directly to your server.

Why this exists: Jellyfin's own card-image generator
(Emby.Server.Implementations.Images.CollectionFolderImageProvider) only
runs for CollectionFolder-type libraries. Live TV is a different item type
(UserView) that provider explicitly does not support, so it's stuck with a
generic default icon forever -- confirmed straight from Jellyfin's own
source, not guessed. This script reimplements that exact algorithm (same
960x540 canvas, same semi-transparent black scrim, same centered bold-text
logic) from Jellyfin.Drawing.Skia/StripCollageBuilder.cs, using a photo you
provide (or the bundled default), and uploads the result with Jellyfin's own
public REST API -- the same endpoint (`/Items/{id}/Images/Primary`) Jellyfin
itself uses to save any item's image. No plugin required.

Setup:
    pip install -r requirements.txt

Configuration (environment variables, or a .env file in this directory):
    JELLYFIN_URL       e.g. https://jellyfin.example.com  (no trailing slash)
    JELLYFIN_API_KEY   an admin API key -- Dashboard > API Keys > +

Optional:
    LIBRARY_NAME       text to overlay (default: "Live TV")
    SOURCE_IMAGE       path to your own photo (default: looks for
                       ./source_image.jpg or ./source_image.png in this
                       directory; falls back to the bundled default if
                       neither exists)
    JELLYFIN_VERIFY_SSL  set to "false" if your server uses a self-signed
                       certificate or plain HTTP (common for LAN-only
                       installs) -- defaults to "true"

Usage:
    python3 generate_livetv_card.py
    python3 generate_livetv_card.py --dry-run   # save the image locally, don't upload

Requires Python 3.8+.
"""
from __future__ import annotations

import argparse
import base64
import os
import sys
from io import BytesIO
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFont

SCRIPT_DIR = Path(__file__).resolve().parent
FONT_PATH = SCRIPT_DIR / "assets" / "OpenSans-Bold.ttf"
DEFAULT_BACKDROP = SCRIPT_DIR / "assets" / "default_backdrop_source.jpg"

# Matches CollectionFolderImageProvider.CreateThumbCollage(item, itemsWithImages,
# outputPath, 960, 540) -- the exact canvas size Jellyfin uses for every other
# library's card image.
CANVAS_WIDTH = 960
CANVAS_HEIGHT = 540

# Matches StripCollageBuilder.BuildThumbCollageBitmap: SKColors.Black.WithAlpha(0x78)
SCRIM_ALPHA = 0x78

# Matches BuildThumbCollageBitmap: textFont.Size = 112, scaled down if the
# measured text width exceeds 95% of the canvas width.
BASE_FONT_SIZE = 112
MAX_WIDTH_FRACTION = 0.95
SCALE_TARGET_FRACTION = 0.90


def load_env_file():
    """Tiny .env loader -- avoids adding python-dotenv as a dependency for
    one optional convenience file."""
    env_path = SCRIPT_DIR / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def find_source_image(explicit_path: str | None) -> Path:
    if explicit_path:
        path = Path(explicit_path)
        if not path.exists():
            sys.exit(f"SOURCE_IMAGE was set to '{path}' but that file doesn't exist.")
        return path

    for candidate in ("source_image.jpg", "source_image.jpeg", "source_image.png"):
        path = SCRIPT_DIR / candidate
        if path.exists():
            return path

    print(
        f"No source_image.jpg/.png found in {SCRIPT_DIR} -- using the bundled "
        f"default (a CC0/public-domain broadcast studio photo, see README for "
        f"credit). Drop your own 16:9 photo in as 'source_image.jpg' and "
        f"re-run to replace it."
    )
    return DEFAULT_BACKDROP


def build_card_image(source_path: Path, library_name: str) -> bytes:
    src = Image.open(source_path).convert("RGB")

    # Resize to the canvas width, preserving aspect ratio (same math as
    # StripCollageBuilder: `backdropHeight = width * backdrop.Height / backdrop.Width`),
    # then center-crop or pad to exactly fill the canvas so arbitrary source
    # photos (not exactly 16:9) still produce a clean result -- Jellyfin's own
    # backdrops are almost always already 16:9 so its code doesn't need this,
    # but a script accepting arbitrary user photos does.
    new_height = round(CANVAS_WIDTH * src.height / src.width)
    resized = src.resize((CANVAS_WIDTH, new_height), Image.LANCZOS)

    canvas = Image.new("RGB", (CANVAS_WIDTH, CANVAS_HEIGHT), (0, 0, 0))
    if new_height > CANVAS_HEIGHT:
        top = (new_height - CANVAS_HEIGHT) // 2
        resized = resized.crop((0, top, CANVAS_WIDTH, top + CANVAS_HEIGHT))
        canvas.paste(resized, (0, 0))
    else:
        canvas.paste(resized, (0, (CANVAS_HEIGHT - new_height) // 2))

    # Semi-transparent black scrim over the whole canvas, matching
    # SKColors.Black.WithAlpha(0x78) exactly.
    canvas = canvas.convert("RGBA")
    scrim = Image.new("RGBA", (CANVAS_WIDTH, CANVAS_HEIGHT), (0, 0, 0, SCRIM_ALPHA))
    canvas = Image.alpha_composite(canvas, scrim).convert("RGB")

    draw = ImageDraw.Draw(canvas)
    font_size = BASE_FONT_SIZE
    font = ImageFont.truetype(str(FONT_PATH), font_size)
    if hasattr(font, "get_variation_axes"):
        # Open Sans is a variable font; axes are [Weight, Width] -- select
        # Bold (700) at normal width (100), matching Jellyfin's own
        # SKFontStyleWeight.Bold / SKFontStyleWidth.Normal request.
        try:
            font.set_variation_by_axes([700, 100])
        except OSError:
            pass  # non-variable build of the font; already bold-only

    bbox = draw.textbbox((0, 0), library_name, font=font)
    text_width = bbox[2] - bbox[0]

    # Matches BuildThumbCollageBitmap's overflow rule exactly: if the text is
    # wider than 95% of the canvas, scale down to target 90% of the width.
    if text_width > CANVAS_WIDTH * MAX_WIDTH_FRACTION:
        font_size = int(SCALE_TARGET_FRACTION * CANVAS_WIDTH * font_size / text_width)
        font = ImageFont.truetype(str(FONT_PATH), font_size)
        if hasattr(font, "get_variation_axes"):
            try:
                font.set_variation_by_axes([700, 100])
            except OSError:
                pass

    draw.text(
        (CANVAS_WIDTH / 2, CANVAS_HEIGHT / 2),
        library_name,
        font=font,
        fill=(255, 255, 255),
        anchor="mm",
    )

    buf = BytesIO()
    canvas.save(buf, format="PNG")
    return buf.getvalue()


def find_live_tv_item_id(jellyfin_url: str, api_key: str, collection_type: str, verify_ssl: bool) -> str:
    """Live TV (and any other UserView-type library) doesn't show up in
    /Library/MediaFolders -- confirmed live against a real server, not
    assumed -- so this has to go through a real user's /Views instead."""
    users = requests.get(
        f"{jellyfin_url}/Users", params={"api_key": api_key}, timeout=15, verify=verify_ssl
    )
    users.raise_for_status()
    admin_users = [u for u in users.json() if u.get("Policy", {}).get("IsAdministrator")]
    if not admin_users:
        sys.exit(
            "No administrator user found on this server -- can't enumerate "
            "library views. Create/confirm an admin user and try again."
        )

    for user in admin_users:
        views = requests.get(
            f"{jellyfin_url}/Users/{user['Id']}/Views",
            params={"api_key": api_key},
            timeout=15,
            verify=verify_ssl,
        )
        views.raise_for_status()
        for item in views.json().get("Items", []):
            if item.get("CollectionType") == collection_type:
                return item["Id"]

    sys.exit(
        f"No library with CollectionType='{collection_type}' found in any "
        f"admin user's views. Is Live TV actually configured on this server?"
    )


def upload_image(jellyfin_url: str, api_key: str, item_id: str, png_bytes: bytes, verify_ssl: bool):
    # Jellyfin's Images/{type} upload endpoint expects the body base64-encoded,
    # not raw binary -- confirmed empirically (raw bytes get the connection
    # reset outright), not documented clearly anywhere obvious.
    response = requests.post(
        f"{jellyfin_url}/Items/{item_id}/Images/Primary",
        params={"api_key": api_key},
        headers={"Content-Type": "image/png"},
        data=base64.b64encode(png_bytes),
        timeout=30,
        verify=verify_ssl,
    )
    response.raise_for_status()


def main():
    load_env_file()

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Save the generated card to ./output_card.png instead of uploading it.",
    )
    parser.add_argument(
        "--collection-type", default="livetv",
        help="Which UserView CollectionType to target (default: livetv). "
             "Advanced use only -- lets this same tool patch a different "
             "unsupported library type if you have one.",
    )
    args = parser.parse_args()

    jellyfin_url = os.environ.get("JELLYFIN_URL", "").rstrip("/")
    api_key = os.environ.get("JELLYFIN_API_KEY", "")
    library_name = os.environ.get("LIBRARY_NAME", "Live TV")
    source_image_env = os.environ.get("SOURCE_IMAGE")
    verify_ssl = os.environ.get("JELLYFIN_VERIFY_SSL", "true").strip().lower() not in ("false", "0", "no")

    if not verify_ssl:
        # The user explicitly opted out (self-signed cert / plain HTTP, common
        # for LAN-only installs) -- don't spam them with a warning about the
        # choice they just deliberately made.
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    if not args.dry_run and (not jellyfin_url or not api_key):
        sys.exit(
            "JELLYFIN_URL and JELLYFIN_API_KEY are required (set them as "
            "environment variables or in a .env file next to this script -- "
            "see README.md). Use --dry-run to generate the image without "
            "needing either, for a quick preview."
        )

    source_path = find_source_image(source_image_env)
    print(f"Using source image: {source_path}")

    png_bytes = build_card_image(source_path, library_name)

    if args.dry_run:
        out_path = SCRIPT_DIR / "output_card.png"
        out_path.write_bytes(png_bytes)
        print(f"Dry run -- saved to {out_path}, nothing uploaded.")
        return

    print(f"Looking up the '{args.collection_type}' library on {jellyfin_url} ...")
    item_id = find_live_tv_item_id(jellyfin_url, api_key, args.collection_type, verify_ssl)
    print(f"Found it (item id {item_id}). Uploading the generated card ...")
    upload_image(jellyfin_url, api_key, item_id, png_bytes, verify_ssl)
    print("Done. The new card should appear next time the home screen refreshes.")


if __name__ == "__main__":
    main()
