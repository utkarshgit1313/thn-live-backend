import os
import json
import re
import difflib
import subprocess
import urllib.request
import internetarchive as ia

PLAYLIST_URL = os.environ.get("PLAYLIST_URL", "").strip()
EPISODES_FILE = "episodes.json"
IA_CREATOR_SEARCH = "uploader:utkarsh_prajapati383" # आपका Archive यूज़रनेम

def clean_text(text):
    # मिलान आसान बनाने के लिए स्पेशल कैरेक्टर और एक्स्ट्रा स्पेस हटाएं
    return re.sub(r'\s+', ' ', re.sub(r'[^\w\s\u0900-\u097F]', '', text)).strip().lower()

# 1. YouTube प्लेलिस्ट से केवल मेटाडेटा (Title, Thumbnail, Duration) लें (इसमें YouTube कभी ब्लॉक नहीं करता)
yt_videos = []
if PLAYLIST_URL:
    cmd = ["yt-dlp", "--flat-playlist", "--playlist-end", "30", "-J", PLAYLIST_URL]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode == 0:
        data = json.loads(res.stdout)
        for entry in data.get("entries", []):
            vid = entry.get("id")
            if not vid:
                continue
            # प्लेलिस्ट से थंबनेल और ड्यूरेशन निकालें
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

# 2. आपके Internet Archive अकाउंट से सभी अपलोड किए गए ऑडियो आइटम्स निकालें
search = ia.search_items(IA_CREATOR_SEARCH, fields=["identifier", "title", "date", "addeddate"], sorts=["addeddate desc"])
episodes = []

for item in search:
    identifier = item.get("identifier")
    ia_title = item.get("title", identifier)
    raw_date = item.get("date") or item.get("addeddate", "")
    formatted_date = raw_date[:10] if len(raw_date) >= 10 else ""

    # Archive आइटम के अंदर से असली MP3/ऑडियो फाइल का डायरेक्ट लिंक खोजें
    try:
        ia_item = ia.get_item(identifier)
        audio_file = None
        for f in ia_item.files:
            name = f.get("name", "")
            if name.lower().endswith((".mp3", ".m4a", ".ogg", ".wav")):
                audio_file = name
                break
        if not audio_file:
            continue

        encoded_file = urllib.parse.quote(audio_file)
        audio_url = f"https://archive.org/download/{identifier}/{encoded_file}"
    except Exception as e:
        print(f"Skipping {identifier}: {e}")
        continue

    # 3. YouTube प्लेलिस्ट के टाइटल से मैच करें ताकि सही Thumbnail और Duration मिल सके
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

    # अगर 60% से ज़्यादा टाइटल मैच होता है, तो YouTube का थंबनेल और ड्यूरेशन लगाएं
    if best_match and best_score >= 0.60:
        thumbnail = best_match["thumbnail"]
        duration = best_match["duration"]
        vid = best_match["video_id"]
        print(f"Matched '{ia_title}' -> YouTube ID {vid} (Score: {best_score:.2f})")
    else:
        # मैच न होने पर Archive का डिफ़ॉल्ट थंबनेल इस्तेमाल करें
        thumbnail = f"https://archive.org/services/img/{identifier}"
        duration = ""
        vid = identifier
        print(f"No YT match for '{ia_title}', using Archive defaults.")

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
