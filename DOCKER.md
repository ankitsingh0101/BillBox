# Running BillBox with Docker

## What Docker is, in plain words
Docker packs an app and everything it needs into a sealed box (a "container"), so it runs the same on any
computer. Nobody has to install Python or libraries. They install **Docker Desktop** once and run one command.

BillBox needs two boxes:
1. **app**: the BillBox web page and checks (built from the `Dockerfile`)
2. **ollama**: the AI model runner (a ready-made image from the Ollama team)

`docker-compose.yml` starts both and connects them.

## Option A: everything inside Docker (best for sharing with others)
1. Install Docker Desktop (https://www.docker.com/products/docker-desktop) and start it.
2. In the BillBox folder:
   ```powershell
   docker compose up -d --build
   docker compose exec ollama ollama pull gemma3:4b
   ```
   The model download (about 3 GB) happens once and is kept in a Docker volume.
3. Open http://localhost:8000. The top-right pill should say "Local model ready: gemma3:4b".

Stop it: `docker compose down`   (add `-v` to also delete the downloaded model)

## Option B: reuse the Ollama you already installed (no 3 GB re-download)
```powershell
docker compose -f docker-compose.host-ollama.yml up -d --build
```
Open http://localhost:8000. If the pill stays red, Ollama is not accepting connections from Docker. Close
Ollama from the system tray, then run this and start Ollama again:
```powershell
setx OLLAMA_HOST 0.0.0.0
```

## Speed
Inside Docker, Ollama runs on the CPU unless you set up GPU access, so each bill can take a minute or more.
Option B is usually faster on a Windows PC with an NVIDIA card, because it uses the Ollama already on your machine.

## Privacy
The port is bound to 127.0.0.1, so only the same computer can open the page. Do not publish it to a network
without adding a login.

## Useful commands
| Command | What it does |
|---|---|
| `docker compose ps` | Show what is running |
| `docker compose logs -f app` | Watch BillBox's messages (errors appear here) |
| `docker compose up -d --build` | Rebuild after you change the code |
| `docker compose down` | Stop everything |
