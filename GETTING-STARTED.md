# Run ProofShape on your computer

Works the same on **Windows, Mac, and Linux**. No accounts, no cloud — everything
runs privately on your machine.

## 1. Install Docker Desktop (one time)

Download it here and install like any normal app:
**https://www.docker.com/products/docker-desktop/**

Open it once after installing and wait until it says it's running.
(Linux servers: install Docker Engine + the compose plugin instead.)

## 2. Start ProofShape

Open the ProofShape folder (the one this file is in) and:

- **Windows:** double-click **`start-proofshape.bat`**
- **Mac:** double-click **`start-proofshape.command`**
  (first time, if macOS complains: right-click the file → Open → Open)
- **Linux:** run `bash start-proofshape.sh`

The **first start takes 10–20 minutes** — it's building the whole app. A window
shows progress; when it's done your browser opens at **http://localhost:3000**.
Every start after that takes seconds.

## 3. Sign in

Click **Sign up**, enter any email and a password (8+ characters with a letter
and a digit), and you're in. Accounts live only on your machine.

## Everyday use

| I want to…            | Do this                                              |
|-----------------------|------------------------------------------------------|
| Start the app         | Double-click the same start file again               |
| Stop the app          | In the folder, run `docker compose down`             |
| Get an app update     | Replace the folder with the new one I send, keep your old `.env` file, and start again |

Your data (accounts, parts, analyses) is stored in Docker volumes and survives
stops, restarts, and app updates.

## Something's wrong?

Run `docker compose logs --tail 50` in the folder and send me the output —
that tells me everything I need.
