## Summary

Describe the user-visible change and why it is needed.

## Verification

- [ ] `python -m py_compile .\src\TubePort.pyw`
- [ ] `python .\src\TubePort.pyw --url-input-self-test`
- [ ] `python .\src\TubePort.pyw --self-test` (when local tools are available)
- [ ] Relevant UI or portable-bundle checks (when applicable)

Include the commands run and a concise result. Do not attach downloaded media.

## Safety and privacy

- [ ] No credentials, cookies, account identifiers, private media, or personal paths are included.
- [ ] User-controlled values are not interpolated into a shell command string.
- [ ] Authentication and diagnostic-redaction boundaries are unchanged, or the change is explained and reviewed.
- [ ] Documentation and `CHANGELOG.md` are updated for user-visible behavior.

## Screenshots

For UI changes, add a screenshot that contains no personal or sensitive data.
