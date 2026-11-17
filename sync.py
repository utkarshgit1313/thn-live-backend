import os
import json
import re
import difflib
import subprocess
import urllib.parse
import internetarchive as ia

PLAYLIST_URL = os.environ.get("PLAYLIST_URL", "").strip()
ACCESS_KEY = os.environ.get("ARCHIVE_ACCESS_KEY", "").strip()
SECRET_KEY = os.environ.get("ARCHIVE_SECRET_KEY", "").strip()
EPISODES_FILE = "episodes.json"

# आपकी Archive प्रोफ़ाइल और अपलोड्स को खोजने के लिए सर्च क्वेरी
IA_SEARCH_QUERY = 'uploader:"utkarsh_prajapati383" OR creator:"The Humility Nirankari" OR title:"The Humility Nirankari" OR title:"Nirankari Story Time"'

def clean_text(text):
    # || और अन्य स्पेशल कैरेक्टर हटाकर साफ टेक्स्ट बनाएं ताकि टाइटल आसानी से मैच हो
    return re.sub(r'\s+', ' ', re.sub(r'[^\w\s\u0900-\u097F]', ' ', text)).strip().lower()

# 1. YouTube प्लेलिस्ट से मेटाडेटा लें
yt_videos = []
if PLAYLIST_URL:
    cmd = ["yt-dlp", "--flat-playlist", "--playlist-end", "50", "-J", PLAYLIST_URL]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode == 0:
        data = json.loads(res.stdout)
        for entry in data.get("entries", []):
            vid = entry.get("id")
            if not vid:
                continue
            thumbs = entry.get("thumbnails") or []
            thumb_url = thumbs[-1]["url"] if thumbs else f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"
            dur_sec = entry.get("duration")
            duration_str = ""
            if dur_sec:
                m, s = divmod(int(dur_sec), 60)
                h, m = divmod(m, 60)
                duration_str = f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"

            yt_videos.append({
                "video_id": vid,
                "title": entry.get("title", ""),
                "clean_title": clean_text(entry.get("title", "")),
                "thumbnail": thumb_url,
                "duration": duration_str
            })

print(f"Fetched {len(yt_videos)} videos metadata from YouTube playlist.")

# 2. Internet Archive से आइटम्स खोजें (Authentication के साथ)
session = ia.get_session(config={"s3": {"access": ACCESS_KEY, "secret": SECRET_KEY}})
search = session.search_items(IA_SEARCH_QUERY, fields=["identifier", "title", "date", "addeddate"], sorts=["addeddate desc"])

episodes = []
seen_identifiers = set()

for item in search:
    identifier = item.get("identifier")
    if not identifier or identifier in seen_identifiers:
        continue
    seen_identifiers.add(identifier)

    ia_title = item.get("title", identifier)
    if isinstance(ia_title, list):
        ia_title = ia_title[0]

    raw_date = item.get("date") or item.get("addeddate", "")
    formatted_date = raw_date[:10] if len(raw_date) >= 10 else ""

    try:
        ia_item = session.get_item(identifier)
        audio_file = None
        for f in ia_item.files:
            name = f.get("name", "")
            if name.lower().endswith((".mp3", ".m4a", ".ogg", ".wav")):
                audio_file = name
                break
        if not audio_file:
            print(f"No audio file found in {identifier}, skipping.")
            continue

        encoded_file = urllib.parse.quote(audio_file)
        audio_url = f"https://archive.org/download/{identifier}/{encoded_file}"
    except Exception as e:
        print(f"Skipping {identifier}: {e}")
        continue

    # 3. टाइटल मैचिंग (भले ही || न लगा हो, साफ किए गए शब्दों से मैच करेगा)
    clean_ia = clean_text(ia_title)
    best_match = None
    best_score = 0.0

    for yt in yt_videos:
        if not yt["clean_title"]:
            continue
        score = difflib.SequenceMatcher(None, clean_ia, yt["clean_title"]).ratio()
        if score > best_score:
            best_score = score
            best_match = yt

    if best_match and best_score >= 0.50:
        thumbnail = best_match["thumbnail"]
        duration = best_match["duration"]
        vid = best_match["video_id"]
        print(f"Matched '{ia_title}' -> YT ID {vid} (Score: {best_score:.2f})")
    else:
        thumbnail = f"https://archive.org/services/img/{identifier}"
        duration = ""
        vid = identifier
        print(f"No YT match for '{ia_title}' (Best score: {best_score:.2f}), using Archive defaults.")

    episodes.append({
        "video_id": vid,
        "title": ia_title,
        "date": formatted_date,
        "duration": duration,
        "thumbnail": thumbnail,
        "audio_url": audio_url
    })

with open(EPISODES_FILE, "w", encoding="utf-8") as f:
    json.dump(episodes, f, ensure_ascii=False, indent=2)

print(f"Successfully saved {len(episodes)} episodes to {EPISODES_FILE}!")
