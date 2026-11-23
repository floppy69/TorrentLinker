from torrentlinker.feeds import Preferences, Subscription

RICH = Subscription(
    name="Rich",
    query="film",
    categories=[2030, 9999],
    interval_minutes=45,
    wait_minutes=90,
    include_current=True,
    replace_pending=True,
    download_hours=[0, 1, 2, 22, 23],
    daily_bytes=8_000_000_000,
    daily_torrents=7,
    reserve_bytes=123_456_789,
    preferences=Preferences(
        min_size=700 * 1024**2 + 5,
        max_size=8_000_000_000,
        min_seeders=3,
        required={"quality": ["1080p", "720p"], "audio": ["fr"]},
        preferred={"quality": ["1080p"], "codec": ["HEVC", "H264"]},
        excluded={"quality": ["CAM"]},
        priorities=["codec", "quality", "seeders", "audio", "subtitles", "size"],
        prefer_small=True,
    ),
)
