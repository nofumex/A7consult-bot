# Security Notes

- Never commit `.env`, Google service account JSON files, local databases, logs, or private keys.
- Use `.env.example` as the public configuration template.
- Rotate any token that was pasted into chat, logs, screenshots, or a repository by mistake.
- Give amoCRM tokens the minimum permissions needed for deals, contacts, pipelines, and notes.
- Keep production data in a server-side database backup, not in the Git repository.
