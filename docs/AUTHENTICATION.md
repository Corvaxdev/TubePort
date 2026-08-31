# Authentication model

TubePort deliberately has no embedded sign-in form. It never asks for a
YouTube, Google, Instagram, or Meta username, password, passkey, or two-factor
code. Interactive sign-in belongs on the service's official website in the
user's normal browser.

## Supported modes

### No authentication

Use this for media that the source site serves anonymously. A link visible in
a signed-in browser is not necessarily public to an anonymous client.

### User-selected `cookies.txt`

This is the primary authenticated mode on Windows. Sign in on the official
website in your own browser, create a fresh Netscape-format export of that
session, and select the file under **Advanced options**.

TubePort validates that the selected file resembles the Netscape cookie format
and passes its path to yt-dlp for that run. It does not copy the file into the
application directory.

A cookie export can grant the same access as an active browser session. Keep it
private, never attach it to an issue, delete it when no longer needed, and
revoke the related session if exposure is possible.

### Detected Mozilla Firefox profile

When `firefox.exe` is detected, TubePort also offers Mozilla Firefox. It passes
the selected Firefox profile identifier to yt-dlp's `--cookies-from-browser`
option. Cookie data is read locally by yt-dlp and is not copied into the
TubePort package or uploaded to a TubePort service.

### Why Chromium profiles are omitted on Windows

Google Chrome, Microsoft Edge, Brave, Vivaldi, Opera, Chromium, and Naver Whale
are intentionally absent from the Windows interface. Current Chromium browsers
can protect `v20` cookie values with App-Bound/DPAPI encryption, making direct
profile access by another process unreliable. Closing the browser does not fix
that encryption failure. Use `cookies.txt`, or an installed Firefox profile
when it is offered.

TubePort does not close browsers automatically, elevate privileges, copy raw
browser databases, or disable browser protection.

## Troubleshooting boundary

TubePort can classify common local failures, but it does not bypass a site's
authentication, age checks, privacy settings, geographic restrictions, rate
limits, or other access controls. A session can expire, and source sites can
change their behavior without a TubePort release.
