import os
import json
import time
import subprocess
import internetarchive as ia

PLAYLIST_URL = os.environ.get("PLAYLIST_URL", "").strip()
ACCESS_KEY = os.environ.get("ARCHIVE_ACCESS_KEY", "").strip()
SECRET_KEY = os.environ.get("ARCHIVE_SECRET_KEY", "").strip()
EPISODES_FILE = "episodes.json"

cookie_exists = os.path.exists("cookies.txt") and os.path.getsize("cookies.txt") > 10
print(f"Cookie file ready: {cookie_exists}")

BASE_ARGS = [
    "yt-dlp",
    "--sleep-requests", "2",
    "--sleep-interval", "5",
    "--max-sleep-interval", "10",
]
if cookie_exists:
    BASE_ARGS += ["--cookies", "cookies.txt"]

if os.path.exists(EPISODES_FILE):
    with open(EPISODES_FILE, "r", encoding="utf-8") as f:
        episodes = json.load(f)
else:
    episodes = []

uploaded_ids = {ep["video_id"] for ep in episodes}

cmd = [
    *BASE_ARGS,
    "--flat-playlist",
    "--playlist-end", "3",
    "-J",
    PLAYLIST_URL
]
result = subprocess.run(cmd, capture_output=True, text=True)
if result.returncode != 0:
    print("ERROR fetching playlist:", result.stderr)
    exit(1)

playlist_data = json.loads(result.stdout)
entries = playlist_data.get("entries", [])
print(f"Total entries found in playlist: {len(entries)}")

for entry in reversed(entries):
    vid = entry.get("id")
    if not vid or vid in uploaded_ids:
        continue

    video_url = f"https://www.youtube.com/watch?v={vid}"
    print(f"Processing new video: {video_url}")
    time.sleep(5)

    info_cmd = [*BASE_ARGS, "-j", video_url]
    info_res = subprocess.run(info_cmd, capture_output=True, text=True)
    if info_res.returncode != 0:
        print(f"ERROR getting video info for {vid}: {info_res.stderr}")
        continue

    info = json.loads(info_res.stdout)
    title = info.get("title", f"Episode {vid}")
    upload_date = info.get("upload_date", "")
    formatted_date = f"{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:]}" if len(upload_date) == 8 else ""
    duration = info.get("duration_string", "")
    thumbnail = info.get("thumbnail", "")

    mp3_filename = f"{vid}.mp3"
    dl_cmd = [
        *BASE_ARGS,
        "-x",
        "--audio-format", "mp3",
        "--audio-quality", "128K",
        "-o", f"{vid}.%(ext)s",
        video_url
    ]
    dl_res = subprocess.run(dl_cmd, capture_output=True, text=True)
    if dl_res.returncode != 0:
        print(f"ERROR downloading {vid}: {dl_res.stderr}")
        continue

    identifier = f"thn-live-{vid}"
    metadata = {
        "title": title,
        "mediatype": "audio",
        "creator": "The Humility Nirankari",
        "date": formatted_date,
        "description": f"Archived audio from YouTube: {video_url}"
    }

    print(f"Uploading {mp3_filename} to Archive.org as {identifier}...")
    ia.upload(
        identifier,
        files=[mp3_filename],
        metadata=metadata,
        access_key=ACCESS_KEY,
        secret_key=SECRET_KEY
    )

    audio_url = f"https://archive.org/download/{identifier}/{mp3_filename}"

    episodes.insert(0, {
        "video_id": vid,
        "title": title,
        "date": formatted_date,
        "duration": duration,
        "thumbnail": thumbnail,
        "audio_url": audio_url
    })

    if os.path.exists(mp3_filename):
        os.remove(mp3_filename)

with open(EPISODES_FILE, "w", encoding="utf-8") as f:
    json.dump(episodes, f, ensure_ascii=False, indent=2)

print("Sync completed successfully!")
