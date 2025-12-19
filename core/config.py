"""Configuration constants for the Deep Work script."""

import os

# Websites to block (add more if needed)
WEBSITES_TO_BLOCK = [
    "facebook.com",
    "www.facebook.com",
    "linkedin.com",
    "www.linkedin.com",
    "www.facebook.com",
    "facebook.com",
    "www.discord.com",
    "discord.com",
    "reddit.com",
    "www.reddit.com",
    "boards.4chan.org",
    "www.4chan.org",
    "news.ycombinator.com",
    "www.ycombinator.com",
    "ycombinator.com",
    "www.ycombinator.com",
    "linkedin.com",
    "www.linkedin.com",
    "lesswrong.com",
    "www.lesswrong.com",
    "alignmentforum.org",
    "www.alignmentforum.org",
    "bsky.app",
    "www.bsky.app",
    "www.x.com",
    "x.com",
    "www.twitter.com",
    "www.twittter.com",
    "www.twttr.com",
    "www.twitter.fr",
    "www.twitter.jp",
    "www.twitter.rs",
    "www.twitter.uz",
    "twitter.biz",
    "twitter.dk",
    "twitter.events",
    "twitter.ie",
    "twitter.je",
    "twitter.mobi",
    "twitter.nu",
    "twitter.pro",
    "twitter.su",
    "twitter.vn",
    "twitter.com",
    "*.twitter.com",
    "twitter.gd",
    "twitter.im",
    "twitter.hk",
    "twitter.jp",
    "twitter.ch",
    "twitter.pt",
    "twitter.rs",
    "www.twitter.com.br",
    "twitter.ae",
    "twitter.eus",
    "twitter.hk",
    "ns1.p34.dynect.net",
    "ns2.p34.dynect.net",
    "ns3.p34.dynect.net",
    "ns4.p34.dynect.net",
    "d01-01.ns.twtrdns.net",
    "d01-02.ns.twtrdns.net",
    "a.r06.twtrdns.net",
    "b.r06.twtrdns.net",
    "c.r06.twtrdns.net",
    "d.r06.twtrdns.net",
    "api-34-0-0.twitter.com",
    "api-47-0-0.twitter.com",
    "cheddar.twitter.com",
    "goldenglobes.twitter.com",
    "mx003.twitter.com",
    "pop-api.twitter.com",
    "spring-chicken-an.twitter.com",
    "spruce-goose-ae.twitter.com",
    "takeflight.twitter.com",
    "www2.twitter.com",
    "m.twitter.com",
    "mobile.twitter.com",
    "api.twitter.com",
]

# Applications to block (Executable Name: Full Path)
# !! IMPORTANT !! Update these paths if your installations are different!
# Common locations are used below. Check your system.
# Note: The key (e.g., "Discord") is only used for logging/display.
# The script now uses the *filename* from the path to kill the process.
APP_PATHS = {
    "Discord": os.path.expandvars(r"%LocalAppData%\Discord\Discord.exe"),
    # Alternative Discord path if Update.exe doesn't work: find the latest app-X.Y.Z\Discord.exe
    # "DiscordApp": os.path.expandvars(r"%LocalAppData%\Discord\app-X.Y.Z\Discord.exe"), # Replace X.Y.Z
    "Telegram": os.path.expandvars(r"%AppData%\Telegram Desktop\Telegram.exe"),
    "Steam": r"C:\Program Files (x86)\Steam\Steam.exe",
}

# Hosts file path
HOSTS_FILE_PATH = r"C:\Windows\System32\drivers\etc\hosts"
REDIRECT_IP = "127.0.0.1"  # Or "0.0.0.0"
HOSTS_MARKER = "# BLOCKED_BY_SCRIPT"  # Marker to identify lines added by this script

# Confirmation phrase for off/break commands
CONFIRMATION_PHRASE = "I will not stop cool deepwork session"
