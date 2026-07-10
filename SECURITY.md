# Security policy

## Supported version

Security fixes are applied to the latest code on the `main` branch.

## Reporting a vulnerability

Please do not open a public issue for a vulnerability, leaked secret, authorization bypass,
or a report containing private user data.

Use GitHub's private vulnerability reporting flow:

1. Open the repository's **Security** tab.
2. Select **Advisories**.
3. Choose **Report a vulnerability**.

Include a concise description, affected code paths, reproduction steps, impact, and any
suggested fix. Remove real tokens, API keys, Telegram messages, database contents, and other
personal data from the report.

You should receive an acknowledgement within seven days. Please allow time for a fix before
public disclosure.

## Deployment notes

- Store credentials only in `.env`, Docker secrets, or protected GitHub environment secrets.
- Do not expose the admin panel directly to the public internet. It is designed for an SSH
  tunnel and binds to `127.0.0.1` in the provided Compose configuration.
- Rotate a token immediately if it is accidentally committed or posted in an issue.
