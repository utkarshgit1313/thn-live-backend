import os
import json
import re
import urllib.parse
import internetarchive as ia
import subprocess

PLAYLIST_URL = os.environ.get("PLAYLIST_URL", "").strip()
ACCESS_KEY = os.environ.get("ARCHIVE_ACCESS_KEY", "").strip()
SECRET_KEY = os.environ.get("ARCHIVE_SECRET_KEY", "").strip()
EPISODES_FILE = "episodes.json"

def clean_text(text):
    return re.sub(r'\s+', ' ', re.sub(r'[^\w\s\u0900-\u097F]', ' ', text)).strip().lower()

# 1. YouTube प्लेलिस्ट से केवल वही वीडियो निकालें जो वास्तव में उस प्लेलिस्ट में हैं (Exact Metadata के साथ)
yt_videos = []
if PLAYLIST_URL:
    cmd = ["yt-dlp", "--flat-playlist", "--playlist-end", "50", "-J", PLAYLIST_URL]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode == 0:
        data = json.loads(res.stdout)
        for entry in data.get("entries", []):
            vid = entry.get("id")
            title = entry.get("title", "")
            if not vid or not title:
                continue
            
            thumbs = entry.get("thumbnails") or []
            thumb_url = thumbs[-1]["url"] if thumbs else f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"
            
            dur_sec = entry.get("duration")
            duration_str = ""
            if dur_sec:
                m, s = divmod(int(dur_sec), 60)
                h, m = divmod(m, 60)
                duration_str = f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"

            # YouTube upload_date (YYYYMMDD) से सटीक ISO timestamp बनाएं
            raw_date = entry.get("upload_date", "")
            formatted_date = ""
            if len(raw_date) == 8:
                formatted_date = f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:]}T00:00:00Z"

            yt_videos.append({
                "video_id": vid,
                "title": title,
                "clean_title": clean_text(title),
                "thumbnail": thumb_url,
                "duration": duration_str,
                "date": formatted_date
            })

print(f"Fetched {len(yt_videos)} valid videos from YouTube playlist.")

# 2. Internet Archive से आपके अपलोड किए गए ऑडियो आइटम्स लाएं
IA_SEARCH_QUERY = 'uploader:"utkarsh_prajapati383" OR creator:"The Humility Nirankari"'
session = ia.get_session(config={"s3": {"access": ACCESS_KEY, "secret": SECRET_KEY}})
search = session.search_items(IA_SEARCH_QUERY, fields=["identifier", "title", "addeddate"], sorts=["addeddate desc"])

episodes = []
matched_video_ids = set()

for item in search:
    identifier = item.get("identifier")
    if not identifier:
        continue

    ia_title = item.get("title", identifier)
    if isinstance(ia_title, list):
        ia_title = ia_title[0]

    try:
        ia_item = session.get_item(identifier)
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

    # 3.严格匹配 (Strict Matching): केवल वही आइटम जुड़ेंगे जो YouTube प्लेलिस्ट के टाइटल से सटीक मैच होंगे
    clean_ia = clean_text(ia_title)
    best_match = None
    best_score = 0.0

    for yt in yt_videos:
        if yt["video_id"] in matched_video_ids:
            continue
        
        # शब्दों की समानता जांचें (Threshold 0.65 ताकि गलत वीडियो न आए)
        import difflib
        score = difflib.SequenceMatcher(None, clean_ia, yt["clean_title"]).ratio()
        if score > best_score:
            best_score = score
            best_match = yt

    # अगर प्लेलिस्ट के वीडियो से 65% या उससे ज़्यादा मैच हुआ तभी शामिल करें (फालतू वीडियो बाहर रहेंगे)
    if best_match and best_score >= 0.65:
        matched_video_ids.add(best_match["video_id"])
        episodes.append({
            "video_id": best_match["video_id"],
            "title": best_match["title"], # YouTube का असली साफ टाइटल
            "date": best_match["date"],   # YouTube की असली पब्लिश डेट और टाइम
            "duration": best_match["duration"],
            "thumbnail": best_match["thumbnail"],
            "audio_url": audio_url
        })
        print(f"Successfully Matched: '{ia_title}' -> YT ID {best_match['video_id']}")
    else:
        print(f"Ignored (Not in YouTube Playlist or Low Match): '{ia_title}'")

# 4. तारीख के हिसाब से सॉर्ट करें (सबसे नया सबसे ऊपर - Latest First)
episodes.sort(key=lambda x: x["date"], reverse=True)

with open(EPISODES_FILE, "w", encoding="utf-8") as f:
    json.dump(episodes, f, ensure_ascii=False, indent=2)

print(f"Successfully saved {len(episodes)} filtered & sorted episodes to {EPISODES_FILE}!")
