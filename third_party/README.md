# Third-party components

`COMPONENTS.json` records the primary runtime and build components,
`TOOLS.lock.json` pins
the external Windows tools and their SHA-256 digests, and
`THIRD_PARTY_NOTICES.txt` summarizes their upstream terms. Complete license
texts retained for the application package are under `licenses/`. The package's
generated `SHA256SUMS.txt` is the exhaustive per-file integrity inventory.

The public TubePort bootstrap archive does not contain the yt-dlp, Deno, or
FFmpeg executables. `Setup-Tools.ps1` downloads those unmodified files directly
from the pinned upstream release URLs and refuses to install a digest mismatch.

Updating a URL or version requires reviewing the upstream license and release,
recording the new archive and executable hashes, refreshing the notices, and
testing setup in a clean directory. Do not replace a pinned URL with a moving
`latest` URL.
