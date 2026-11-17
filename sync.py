import os
import json
import re
import difflib
import subprocess
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import internetarchive as ia

PLAYLIST_URL = os.environ.get("PLAYLIST_URL", "").strip()
ACCESS_KEY = os.environ.get("ARCHIVE_ACCESS_KEY", "").strip()
SECRET_KEY = os.environ.get("ARCHIVE_SECRET_KEY", "").strip()
EPISODES_FILE = "episodes.json"
ARCHIVE_USERNAME = "utkarsh_prajapati383"

def clean_text(text):
    return re.sub(r'\s+', ' ', re.sub(r'[^\w\s\u0900-\u097F]', ' ', text)).strip().lower()

# 1. YouTube प्लेलिस्ट के सभी वीडियो (Avtar Bani + Special Live) और उनकी Exact Date & Time लें
yt_videos = {}
if PLAYLIST_URL:
    cmd = ["yt-dlp", "--flat-playlist", "--playlist-end", "100", "-J", PLAYLIST_URL]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode == 0:
        data = json.loads(res.stdout)
        for idx, entry in enumerate(data.get("entries", [])):
            vid = entry.get("id")
            title = entry.get("title", "")
            if not vid or not title or title in ("[Private video]", "[Deleted video]"):
                continue

            thumbs = entry.get("thumbnails") or []
            thumb_url = thumbs[-1]["url"] if thumbs else f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"

            dur_sec = entry.get("duration")
            duration_str = ""
            if dur_sec:
                m, s = divmod(int(dur_sec), 60)
                h, m = divmod(m, 60)
                duration_str = f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"

            raw_date = entry.get("upload_date", "")
            iso_date = f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:]}T00:00:00Z" if len(raw_date) == 8 else ""

            yt_videos[vid] = {
                "video_id": vid,
                "title": title,
                "clean_title": clean_text(title),
                "thumbnail": thumb_url,
                "duration": duration_str,
                "date": iso_date,
                "playlist_order": idx
            }

    # YouTube RSS Feed से Exact Publish Date & Time (घंटे और मिनट सहित) निकालें
    list_match = re.search(r"list=([a-zA-Z0-9_-]+)", PLAYLIST_URL)
    if list_match:
        rss_url = f"https://www.youtube.com/feeds/videos.xml?playlist_id={list_match.group(1)}"
        try:
            xml_data = urllib.request.urlopen(rss_url, timeout=15).read()
            root = ET.fromstring(xml_data)
            ns = {"atom": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015"}
            for entry in root.findall("atom:entry", ns):
                vid_el = entry.find("yt:videoId", ns)
                pub_el = entry.find("atom:published", ns)
                if vid_el is not None and pub_el is not None and vid_el.text in yt_videos:
                    yt_videos[vid_el.text]["date"] = pub_el.text
        except Exception as e:
            print(f"RSS date fetch note: {e}")

print(f"Fetched {len(yt_videos)} valid videos from YouTube playlist.")

# 2. सीधे आपके Archive प्रोफ़ाइल पेज से सभी अपलोड्स निकालें (कोई भी नाम हो, सब आएगा)
identifiers = []
try:
    profile_url = f"https://archive.org/details/@{ARCHIVE_USERNAME}?output=json"
    req = urllib.request.Request(profile_url, headers={"User-Agent": "Mozilla/5.0"})
    profile_data = json.loads(urllib.request.urlopen(req, timeout=15).read().decode("utf-8"))
    for doc in profile_data.get("response", {}).get("docs", []):
        if doc.get("identifier"):
            identifiers.append(doc["identifier"])
except Exception as e:
    print(f"Profile JSON fetch note: {e}")

# बैकअप के लिए API सर्च भी चलाएं
session = ia.get_session(config={"s3": {"access": ACCESS_KEY, "secret": SECRET_KEY}})
for item in session.search_items(f'uploader:"{ARCHIVE_USERNAME}" OR creator:"The Humility Nirankari"'):
    if item.get("identifier") and item["identifier"] not in identifiers:
        identifiers.append(item["identifier"])

print(f"Found {len(identifiers)} total uploads on your Archive profile.")

episodes = []
matched_video_ids = set()

for identifier in identifiers:
    try:
        ia_item = session.get_item(identifier)
        ia_title = ia_item.metadata.get("title", identifier)
        if isinstance(ia_title, list):
            ia_title = ia_title[0]

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

    # 3. YouTube प्लेलिस्ट के किसी भी वीडियो (Avtar Bani या Special Live) से टाइटल मैच करें
    clean_ia = clean_text(ia_title)
    best_match = None
    best_score = 0.0

    for vid, yt in yt_videos.items():
        if vid in matched_video_ids:
            continue
        score = difflib.SequenceMatcher(None, clean_ia, yt["clean_title"]).ratio()
        if score > best_score:
            best_score = score
            best_match = yt

    if best_match and best_score >= 0.60:
        matched_video_ids.add(best_match["video_id"])
        final_date = best_match["date"] or ia_item.metadata.get("publicdate", "")
        episodes.append({
            "video_id": best_match["video_id"],
            "title": best_match["title"],
            "date": final_date,
            "duration": best_match["duration"],
            "thumbnail": best_match["thumbnail"],
            "audio_url": audio_url,
            "_order": best_match["playlist_order"]
        })
        print(f"Matched [{best_score:.2f}]: '{ia_title}' -> '{best_match['title']}'")
    else:
        print(f"Ignored (Not in playlist): '{ia_title}' (Best score: {best_score:.2f})")

# 4. Latest First सॉर्ट करें
episodes.sort(key=lambda x: (x["date"] or "", -x["_order"]), reverse=True)
for ep in episodes:
    ep.pop("_order", None)

with open(EPISODES_FILE, "w", encoding="utf-8") as f:
    json.dump(episodes, f, ensure_ascii=False, indent=2)

print(f"Successfully saved {len(episodes)} filtered & sorted episodes to {EPISODES_FILE}!")
