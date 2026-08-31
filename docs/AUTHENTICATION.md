# Authentication model

TubePort deliberately has no embedded sign-in form. It never asks for a
YouTube, Google, Instagram, or Meta username, password, passkey, or two-factor
code. Interactive sign-in belongs on the service's official website in the
user's normal browser.

## Supported modes

### No authentication

Use this for media that the source site serves anonymously. A link visible in
a signed-in browser is not necessarily public to an anonymous client.

### Existing browser profile

TubePort passes the selected browser and profile identifier to yt-dlp's
`--cookies-from-browser` option. Cookie data is read locally by yt-dlp and is
not copied into the TubePort package or uploaded to a TubePort service.

Supported sources are Chrome, Edge, Brave, Vivaldi, Opera, Chromium, Firefox,
and Naver Whale.

Chromium browsers on current Windows versions can expose two distinct errors:

- The browser process is still locking its cookie database. Close all browser
  windows and background processes, then retry.
- App-Bound Encryption protects `v20` cookie values. Closing the browser does
  not solve this. Use a fresh Netscape-format `cookies.txt` export or a Firefox
  profile instead.

TubePort does not close browsers automatically, elevate privileges, copy raw
browser databases, or disable browser protection.

### User-selected `cookies.txt`

TubePort validates that the selected file resembles the Netscape cookie format
and passes its path to yt-dlp for that run. It does not copy the file into the
application directory.

A cookie export can grant the same access as an active browser session. Keep it
private, never attach it to an issue, delete it when no longer needed, and
revoke the related session if exposure is possible.

## Troubleshooting boundary

TubePort can classify common local failures, but it does not bypass a site's
authentication, age checks, privacy settings, geographic restrictions, rate
limits, or other access controls. A session can expire, and source sites can
change their behavior without a TubePort release.
