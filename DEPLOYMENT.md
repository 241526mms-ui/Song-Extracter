# Deployment Guide: CineTracks

This guide explains how to deploy **CineTracks** online so anyone can access it over the public internet.

---

## Option 1: Free Cloud Hosting on Render.com (Recommended & Easiest)

[Render](https://render.com) offers free web hosting with automatic HTTPS and Docker support.

### Steps:
1. **Push your code to GitHub**:
   ```bash
   git init
   git add .
   git commit -m "Initial commit for CineTracks"
   git branch -M main
   git remote add origin https://github.com/YOUR_USERNAME/cinetracks.git
   git push -u origin main
   ```
2. Go to **[dashboard.render.com](https://dashboard.render.com)** and click **New + $\rightarrow$ Web Service**.
3. Select your GitHub repository.
4. Set the following settings:
   - **Name**: `cinetracks` (or your preferred name)
   - **Environment**: **Docker** (Render will automatically detect the [Dockerfile](Dockerfile))
   - **Region**: Choose the closest region (e.g., Singapore, Frankfurt, Oregon)
   - **Instance Type**: **Free**
5. Click **Create Web Service**.
6. Render will build the container with Python, FFmpeg, and start the app at `https://cinetracks-xxxx.onrender.com`.

---

## Option 2: Railway.app (High Performance & Simple)

[Railway](https://railway.app) is another modern cloud platform that natively supports Docker.

### Steps:
1. Push your repository to GitHub.
2. Sign in to **[railway.app](https://railway.app)** and click **New Project $\rightarrow$ Deploy from GitHub repo**.
3. Select your repository.
4. Railway will automatically detect the `Dockerfile`, install FFmpeg, and launch the app.
5. In **Settings $\rightarrow$ Networking**, click **Generate Domain** to get a free public HTTPS address (`https://cinetracks.up.railway.app`).

---

## Option 3: Docker & Docker Compose (Self-Hosted / VPS)

If you have a Linux server or want to run it containerized:

```bash
# Build and run in the background
docker compose up -d --build

# View logs
docker compose logs -f

# Stop the container
docker compose down
```

The app will be running at `http://YOUR_SERVER_IP:8000`.

---

## Option 4: Linux VPS (Ubuntu / Debian / DigitalOcean / Linode / EC2)

Deploy directly on a Linux virtual machine:

### 1. Install System Dependencies
```bash
sudo apt update && sudo apt install -y python3-venv python3-pip ffmpeg nginx certbot python3-certbot-nginx
```

### 2. Clone and Setup
```bash
git clone https://github.com/YOUR_USERNAME/cinetracks.git /var/www/cinetracks
cd /var/www/cinetracks
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

### 3. Setup Systemd Service (Keep running in background)
Copy the service file:
```bash
sudo cp cinetracks.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now cinetracks
sudo systemctl status cinetracks
```

### 4. Configure Nginx Reverse Proxy
Create `/etc/nginx/sites-available/cinetracks`:
```nginx
server {
    server_name yourdomain.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```
Enable the site and obtain free SSL:
```bash
sudo ln -s /etc/nginx/sites-available/cinetracks /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d yourdomain.com
```

---

## Option 5: Instant Public URL from Your Local PC (Cloudflare Tunnel)

To share your currently running local app with friends or test it on your mobile phone without paying for hosting:

```bash
# Install cloudflared (on Arch/Linux):
sudo pacman -S cloudflared
# Or download binary: https://github.com/cloudflare/cloudflared/releases

# Start instant public tunnel to your local server:
cloudflared tunnel --url http://localhost:8000
```
Cloudflare will give you an instant public HTTPS URL (like `https://random-words.trycloudflare.com`) pointing directly to your local CineTracks app!

