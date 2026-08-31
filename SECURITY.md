# Security Policy

## Supported versions

Security fixes are made for the current release line.

| Version | Supported |
| --- | --- |
| 2.1.x | Yes |
| 2.0.x and earlier | No |

Update to the newest release before reporting an issue when possible.

## Report a vulnerability privately

Do not open a public issue for a suspected vulnerability. Use the repository's
**Security** tab and choose **Report a vulnerability** to create a private
security advisory. If private vulnerability reporting is not enabled, contact
the repository owner through a private contact method listed on their GitHub
profile and ask for a secure reporting channel before sending details.

Include:

- the affected TubePort version and Windows version;
- whether the issue affects source mode or the portable package;
- a concise impact statement;
- reproducible steps or a minimal proof of concept;
- relevant diagnostic excerpts after reviewing and redacting them;
- any suggested mitigation, if known.

Never send real cookies, passwords, two-factor codes, tokens, private media,
browser databases, or an entire browser profile. Use synthetic data in a proof
of concept.

Maintainers aim to acknowledge a complete report within seven days. Please
allow time to investigate and prepare a coordinated fix before public
disclosure.

## Security boundaries

TubePort:

- accepts only recognized YouTube video and Instagram Reel URL shapes;
- invokes bundled or locally discovered media tools without a shell command
  string;
- can ask yt-dlp to read a detected Mozilla Firefox profile or a selected
  Netscape `cookies.txt` file;
- does not provide an embedded account login form;
- stores local diagnostic information and attempts to redact cookie-like values
  and media identifiers.

Cookies are still credentials. Anyone who obtains a valid cookie export may be
able to act as the associated session. Users should protect and delete exports,
and revoke exposed sessions.

## Upstream vulnerabilities

Portable releases include third-party components. If the vulnerability exists
unchanged in yt-dlp, FFmpeg, the JavaScript runtime, Python, or another upstream
dependency, report it through that project's private security channel as well.
Please still notify TubePort privately when a bundled release is affected so it
can be updated.

## Out of scope

- Attempts to access media without the rights or authorization to do so
- Credential stuffing, account takeover attempts, or bypassing source-site
  controls
- Reports that require publishing active credentials or private user data
- Availability changes or rate limits imposed by YouTube or Instagram, unless
  TubePort handles the resulting error unsafely
