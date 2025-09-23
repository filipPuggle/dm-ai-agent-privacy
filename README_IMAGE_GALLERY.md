# Image Gallery Feature for Instagram DM Webhook

## Overview
This feature adds a one-time image gallery to price offer messages in Romanian (RO) and Russian (RU) languages. When a user asks about prices, they receive the existing offer text followed by exactly 5 themed images.

## Configuration

### Environment Variable
Set the `PUBLIC_BASE_URL` environment variable to your Railway app URL:
```bash
PUBLIC_BASE_URL=https://your-app-name.up.railway.app
```

### Image Files
Place your images in the `static/offer/` directory:
- `ro_01.jpg` to `ro_05.jpg` - Romanian themed images
- `ru_01.jpg` to `ru_05.jpg` - Russian themed images

## How It Works

### One-Time Guard
- The gallery is sent only once per conversation using the `GALLERY_SENT` in-memory guard
- Even if the user asks about prices again later, no additional images are sent
- The guard persists for the lifetime of the process

### Flow
1. User asks about price (RO: "la ce preț?" or RU: "сколько стоит?")
2. Existing offer text is sent (as before)
3. If gallery hasn't been sent to this user yet:
   - Gallery flag is set immediately (prevents race conditions)
   - 5 images are sent with ~1.1s delay between each
   - Small random delay (0.8-1.6s) between text and first image

### Safety Features
- If `PUBLIC_BASE_URL` is missing or not HTTPS, images are skipped with a warning
- All network calls are wrapped in try/catch to prevent crashes
- Images are served from Flask static files (no external hosting)

## Testing
Run the test file to verify functionality:
```bash
source venv/bin/activate
python test_image_gallery.py
```

## Quick Test
Test static file serving:
```bash
curl -I $PUBLIC_BASE_URL/static/offer/ro_01.jpg
```

## Files Modified
- `webhook.py`: Added Flask static config, gallery guard, and image sending logic
- `send_message.py`: Added `send_instagram_image()` and `send_instagram_images()` functions
- `static/offer/`: Created directory with placeholder image files
