# CadVerify → AWS deploy kit

Puts the whole CadVerify stack (backend API, worker, Postgres, Redis, Next.js
frontend) on a single small AWS EC2 box running Docker Compose. Reached by IP
over plain HTTP. Cheapest thing that actually runs this app: ~$15/month on a
`t3.small`. One command up, one command down.

This runs from **your Mac's Terminal** (it has internet + your AWS keys). The
Claude cloud session can't reach AWS, so it can't run these for you from there.

## One-time setup

1. **Create an AWS account** at https://aws.amazon.com if you don't have one
   (free to open; needs a card + phone verification).

2. **Install the AWS CLI** (Macs already have `ssh`/`scp`):
   ```bash
   brew install awscli        # or: https://aws.amazon.com/cli/
   ```

3. **Make an access key** and give it to the CLI:
   - AWS Console → search **IAM** → **Users** → **Create user** (name it
     `deploy`) → attach policy **AdministratorAccess** → create.
   - Open the user → **Security credentials** → **Create access key** →
     "Command Line Interface (CLI)" → copy the **Access key** + **Secret**.
   - In Terminal:
     ```bash
     aws configure
     # AWS Access Key ID:     <paste>
     # AWS Secret Access Key: <paste>
     # Default region name:   us-east-1
     # Default output format:  (press Enter)
     ```

## Deploy

From the repo root:
```bash
cd deploy
bash up.sh
```
It provisions the box, then builds and starts everything on it. First run takes
~10–15 minutes (mostly the image build on the server). When it finishes it
prints your URL:
```
Frontend : http://<your-ip>:3000
API      : http://<your-ip>:8000
```

## Tear it down (stop all charges)
```bash
cd deploy
bash teardown.sh
```

## Handy
- SSH to the box:      `ssh -i cadverify-deploy.pem ubuntu@<your-ip>`
- See logs:            `ssh -i cadverify-deploy.pem ubuntu@<your-ip> 'cd /opt/cadverify && docker compose logs -f'`
- Redeploy new code:   `bash deploy.sh`  (after `provision.sh` already ran)

## Notes
- **No HTTPS yet** — it's plain HTTP by IP, which is fine for testing but not for
  real users or real logins. When you're ready, point a domain at the IP and add
  a TLS cert; I can wire that up (it's a small add: a reverse proxy + free cert).
- **Cost control** — everything lives under one instance + one Elastic IP.
  `teardown.sh` removes all of it. While running: ~$15/mo (`t3.small`) + a few
  cents for storage.
- **Bigger box** — if the build runs out of memory, edit the top of
  `provision.sh`: `INSTANCE_TYPE=t3.medium`, then `teardown.sh` and `up.sh` again.
- **Secrets** — generated fresh on your Mac at first deploy into
  `deploy/.secrets.env` (gitignored, never committed) and reused on redeploys.
