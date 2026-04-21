# Secrets Management

This project reads all secrets from the process environment. `.env` is a
convenience for local development only — it is in `.gitignore` and must
never be committed.

For any deployed environment (staging, production), inject secrets via
your platform's secret store. This doc covers the three most common paths.

## What counts as a secret?

Anything in `.env.example` marked with a value like `CHANGE_ME` or that
represents a credential. At minimum:

- `JWT_SECRET` — signs session tokens. Leak = session forgery.
- `SMTP_PASSWORD` — account takeover if leaked.
- `LANGCHAIN_API_KEY` — billed usage if leaked.

Non-secret configuration (`CORS_ALLOW_ORIGINS`, `LOG_LEVEL`, paths, etc.)
can live in a plain `ConfigMap` / env-var block.

## Minimum viable: `.env` + `chmod`

For a single-server deployment:

1. `cp .env.example /etc/hr-mas/env` on the target host.
2. `chmod 600 /etc/hr-mas/env && chown root:app /etc/hr-mas/env`.
3. Load it via systemd:

   ```ini
   # /etc/systemd/system/hr-mas-backend.service
   [Service]
   EnvironmentFile=/etc/hr-mas/env
   ExecStart=/opt/hr-mas/.venv/bin/uvicorn backend.server:app \
             --host 0.0.0.0 --port 8000
   User=app
   Group=app
   ```

This is fine for small deployments. It does not give you rotation or
audit logging — when you outgrow it, move to one of the options below.

## systemd `LoadCredential` (modern Linux)

For single-host deployments where you want credentials isolated from the
rest of the env:

```ini
[Service]
LoadCredential=jwt_secret:/etc/hr-mas/secrets/jwt_secret
LoadCredential=smtp_password:/etc/hr-mas/secrets/smtp_password
Environment=JWT_SECRET_FILE=%d/jwt_secret
Environment=SMTP_PASSWORD_FILE=%d/smtp_password
```

Then read the credential file in code (or with a small wrapper that
sets `JWT_SECRET` from `$JWT_SECRET_FILE` before launching uvicorn).
The credentials are mounted in a tmpfs only visible to this service.

## HashiCorp Vault

For multi-host or team-scale deployments:

1. Write secrets once:

   ```bash
   vault kv put secret/hr-mas/prod \
     JWT_SECRET="$(openssl rand -base64 48)" \
     SMTP_USER="hr-bot@company.com" \
     SMTP_PASSWORD="…"
   ```

2. Fetch at container start using either:
   - [Vault Agent](https://developer.hashicorp.com/vault/docs/agent-and-proxy/agent) rendering a `.env` file to a tmpfs, or
   - [consul-template](https://github.com/hashicorp/consul-template) with
     a sidecar pattern.

3. Rotate with `vault kv put` + a rolling restart. No application
   changes required — the app just reads `os.getenv` as always.

## AWS Secrets Manager

For anything running on AWS:

1. Store secrets:

   ```bash
   aws secretsmanager create-secret --name hr-mas/prod/jwt_secret \
     --secret-string "$(openssl rand -base64 48)"
   ```

2. On ECS/EKS, reference the ARN directly in your task definition:

   ```json
   {
     "secrets": [
       { "name": "JWT_SECRET",
         "valueFrom": "arn:aws:secretsmanager:us-east-1:…:secret:hr-mas/prod/jwt_secret" }
     ]
   }
   ```

   ECS injects these as env vars before the container starts.

3. On Lambda: use the
   [Secrets Manager extension](https://docs.aws.amazon.com/secretsmanager/latest/userguide/retrieving-secrets_lambda.html)
   to cache lookups.

4. Rotate: Secrets Manager can rotate automatically with a Lambda
   rotator; tokens issued before the rotation expire naturally after
   `JWT_EXPIRES_HOURS`.

## Kubernetes

Vanilla secrets:

```bash
kubectl create secret generic hr-mas-prod \
  --from-literal=JWT_SECRET="$(openssl rand -base64 48)" \
  --from-literal=SMTP_PASSWORD="…"
```

Mount them as env vars via `envFrom:` in the Pod spec. For anything
more serious, use [External Secrets Operator](https://external-secrets.io/)
to sync from Vault or AWS SM — this way your manifests don't contain
the secret, only a reference to it.

## Rotation checklist

When rotating `JWT_SECRET`:

1. All currently-valid tokens become invalid immediately.
2. Users get a 401 on their next request → the frontend already handles
   this by forcing logout and re-login (see `frontends/api.py`).
3. If this is disruptive, accept two secrets during a rollover window:
   add a `JWT_SECRET_PREVIOUS` env var, try it on verify failure. We
   don't implement that here by default — uncomment the guard in
   `backend/security.py::verify_token` if you need it.

## Things to never do

- Commit `.env` — `.gitignore` blocks it; double-check with
  `git log --all -- .env`.
- Log secrets — our logger never serializes the config object;
  don't add `log.info(f"{settings}")` anywhere.
- Bake secrets into Docker images — use `env_file:` / `secrets:` in
  compose, or a platform secret store.
- Share across environments — dev, staging, prod each get their own
  `JWT_SECRET`. Otherwise a dev-environment compromise yields prod tokens.
