# 🖥️ VPS Deployment Guide - ORAKL Bot (DigitalOcean/Linode)

**For users who want maximum control and reliability.**

---

## Overview

This guide covers deploying ORAKL Bot to a Linux VPS (Virtual Private Server) with:
- ✅ Full root access
- ✅ Systemd service for auto-restart
- ✅ Nginx reverse proxy (optional)
- ✅ SSL/TLS (optional)
- ✅ Monitoring and logs

**Time**: 1-2 hours
**Skill Level**: Intermediate (basic Linux knowledge required)

---

## Part 1: VPS Setup

### 1.1 Create VPS

**DigitalOcean:**
1. Go to https://digitalocean.com
2. Create account (get $200 free credit)
3. Click **"Create Droplet"**
4. Choose:
   - **OS**: Ubuntu 22.04 LTS
   - **Plan**: Basic ($6/mo - 1GB RAM, 1 vCPU)
   - **Region**: Closest to you
   - **Authentication**: SSH Key (recommended) or Password

**Linode:**
1. Go to https://linode.com
2. Create account (get $100 free credit)
3. Click **"Create Linode"**
4. Choose:
   - **Distribution**: Ubuntu 22.04 LTS
   - **Plan**: Nanode 1GB ($5/mo)
   - **Region**: Closest to you

### 1.2 Connect to VPS

```bash
# SSH into your server (replace with your IP)
ssh root@YOUR_VPS_IP

# First-time setup (if using password)
# Change root password immediately
passwd
```

---

## Part 2: Server Configuration

### 2.1 Update System

```bash
# Update package lists
apt update

# Upgrade all packages
apt upgrade -y

# Install essential tools
apt install -y git python3 python3-pip python3-venv curl wget ufw
```

### 2.2 Create Bot User (Security Best Practice)

```bash
# Create dedicated user for bot
adduser oraklbot

# Add to sudo group (optional)
usermod -aG sudo oraklbot

# Switch to bot user
su - oraklbot
```

### 2.3 Setup Firewall

```bash
# Exit to root user first (if you switched)
exit

# Allow SSH (important!)
ufw allow 22/tcp

# Enable firewall
ufw enable

# Check status
ufw status
```

---

## Part 3: Deploy Bot

### 3.1 Clone Repository

```bash
# Switch to bot user
su - oraklbot

# Create app directory
mkdir -p /home/oraklbot/apps
cd /home/oraklbot/apps

# Clone your bot (use your GitHub repo)
git clone https://github.com/YOUR_USERNAME/orakl-bot.git
cd orakl-bot
```

### 3.2 Setup Python Environment

```bash
# Create virtual environment
python3 -m venv venv

# Activate virtual environment
source venv/bin/activate

# Upgrade pip
pip install --upgrade pip

# Install dependencies
pip install -r requirements.txt
```

### 3.3 Configure Environment

```bash
# Create .env file
nano .env

# Add your secrets (paste from local .env):
DISCORD_BOT_TOKEN=your_token_here
DISCORD_WEBHOOK_URL=your_webhook_url_here
POLYGON_API_KEY=your_api_key_here

# Save: Ctrl+X, then Y, then Enter
```

### 3.4 Test Bot

```bash
# Test run (should start without errors)
python main.py

# Stop with Ctrl+C after confirming it works
```

---

## Part 4: Systemd Service (Auto-Restart)

### 4.1 Create Service File

```bash
# Exit bot user, switch to root
exit

# Create systemd service file
nano /etc/systemd/system/oraklbot.service
```

**Paste this configuration:**

```ini
[Unit]
Description=ORAKL Discord Bot
After=network.target

[Service]
Type=simple
User=oraklbot
WorkingDirectory=/home/oraklbot/apps/orakl-bot
Environment="PATH=/home/oraklbot/apps/orakl-bot/venv/bin"
ExecStart=/home/oraklbot/apps/orakl-bot/venv/bin/python main.py

# Restart configuration
Restart=always
RestartSec=10
StartLimitBurst=5
StartLimitIntervalSec=300

# Logging
StandardOutput=journal
StandardError=journal
SyslogIdentifier=oraklbot

[Install]
WantedBy=multi-user.target
```

**Save**: Ctrl+X, then Y, then Enter

### 4.2 Enable and Start Service

```bash
# Reload systemd
systemctl daemon-reload

# Enable service (start on boot)
systemctl enable oraklbot

# Start service now
systemctl start oraklbot

# Check status
systemctl status oraklbot

# Should show "active (running)" in green
```

---

## Part 5: Monitoring & Logs

### 5.1 View Logs

```bash
# Real-time logs (follow)
journalctl -u oraklbot -f

# Last 100 lines
journalctl -u oraklbot -n 100

# Logs from today
journalctl -u oraklbot --since today

# Search for errors
journalctl -u oraklbot | grep -i error
```

### 5.2 Service Management

```bash
# Restart bot
systemctl restart oraklbot

# Stop bot
systemctl stop oraklbot

# Start bot
systemctl start oraklbot

# Check status
systemctl status oraklbot

# Disable auto-start
systemctl disable oraklbot
```

---

## Part 6: Updates & Maintenance

### 6.1 Update Bot Code

```bash
# Switch to bot user
su - oraklbot

# Navigate to bot directory
cd /home/oraklbot/apps/orakl-bot

# Pull latest code
git pull

# Update dependencies (if needed)
source venv/bin/activate
pip install -r requirements.txt

# Exit to root
exit

# Restart service
systemctl restart oraklbot

# Verify restart
systemctl status oraklbot
```

### 6.2 Automatic Updates (Optional)

Create update script:

```bash
# Create update script
nano /home/oraklbot/update_bot.sh
```

**Paste:**

```bash
#!/bin/bash
cd /home/oraklbot/apps/orakl-bot
git pull
source venv/bin/activate
pip install -r requirements.txt
sudo systemctl restart oraklbot
```

**Make executable:**

```bash
chmod +x /home/oraklbot/update_bot.sh
chown oraklbot:oraklbot /home/oraklbot/update_bot.sh
```

**Run updates:**

```bash
su - oraklbot
./update_bot.sh
```

---

## Part 7: Monitoring Setup (Optional)

### 7.1 Create Health Check Script

```bash
nano /home/oraklbot/health_check.sh
```

**Paste:**

```bash
#!/bin/bash
# ORAKL Bot Health Check

BOT_STATUS=$(systemctl is-active oraklbot)

if [ "$BOT_STATUS" != "active" ]; then
    echo "ERROR: Bot is not running!"
    echo "Attempting restart..."
    sudo systemctl restart oraklbot
    sleep 5

    # Check again
    BOT_STATUS=$(systemctl is-active oraklbot)
    if [ "$BOT_STATUS" = "active" ]; then
        echo "✓ Bot restarted successfully"
    else
        echo "✗ Failed to restart bot - manual intervention required"
    fi
else
    echo "✓ Bot is running normally"
fi
```

**Make executable:**

```bash
chmod +x /home/oraklbot/health_check.sh
```

### 7.2 Setup Cron Job (Automated Health Checks)

```bash
# Edit crontab for bot user
crontab -e -u oraklbot
```

**Add this line (checks every 5 minutes):**

```
*/5 * * * * /home/oraklbot/health_check.sh >> /home/oraklbot/health_check.log 2>&1
```

---

## Part 8: Security Hardening (Recommended)

### 8.1 Disable Root Login

```bash
# Edit SSH config
nano /etc/ssh/sshd_config

# Find and change:
PermitRootLogin no

# Restart SSH
systemctl restart sshd
```

### 8.2 Setup Fail2Ban (Brute Force Protection)

```bash
apt install -y fail2ban

# Enable and start
systemctl enable fail2ban
systemctl start fail2ban

# Check status
fail2ban-client status
```

### 8.3 Enable Automatic Security Updates

```bash
apt install -y unattended-upgrades

# Enable
dpkg-reconfigure --priority=low unattended-upgrades
```

---

## Part 9: Troubleshooting

### Bot Won't Start

**Check service status:**
```bash
systemctl status oraklbot -l
```

**Check logs for errors:**
```bash
journalctl -u oraklbot -n 50 --no-pager
```

**Common issues:**
1. Missing `.env` file → Check `/home/oraklbot/apps/orakl-bot/.env`
2. Wrong file permissions → Run: `chown -R oraklbot:oraklbot /home/oraklbot/apps/orakl-bot`
3. Missing dependencies → Re-run: `pip install -r requirements.txt`

### Bot Keeps Crashing

**View crash logs:**
```bash
journalctl -u oraklbot | grep -i "error\|exception\|traceback"
```

**Increase restart delay:**
Edit `/etc/systemd/system/oraklbot.service`:
```ini
RestartSec=30  # Wait 30 seconds before restart
```

Then reload:
```bash
systemctl daemon-reload
systemctl restart oraklbot
```

### High Memory Usage

**Check memory:**
```bash
free -h
htop  # Install with: apt install htop
```

**Optimize bot:**
- Reduce `CACHE_MAX_SIZE` in config
- Upgrade VPS plan to 2GB RAM

---

## Part 10: Cost Optimization

### Monitor Usage

**DigitalOcean:**
- Dashboard → Droplet → Graphs (CPU, bandwidth, disk)

**Linode:**
- Dashboard → Linode → Analytics

### Resize VPS (If Needed)

**Upgrade:**
```bash
# Stop bot first
systemctl stop oraklbot

# Then resize from provider dashboard
# After resize, start bot
systemctl start oraklbot
```

**Downgrade** (if bot uses <30% resources):
- 1GB → $6/mo (current)
- But 512MB plans often too small for Discord bots

---

## Quick Reference Commands

```bash
# Start bot
systemctl start oraklbot

# Stop bot
systemctl stop oraklbot

# Restart bot
systemctl restart oraklbot

# View status
systemctl status oraklbot

# View logs (live)
journalctl -u oraklbot -f

# Update bot code
cd /home/oraklbot/apps/orakl-bot && git pull && systemctl restart oraklbot

# Check memory usage
free -h

# Check disk space
df -h
```

---

## Support

- **DigitalOcean Docs**: https://docs.digitalocean.com
- **Linode Docs**: https://www.linode.com/docs
- **Ubuntu Help**: https://help.ubuntu.com
- **Systemd Guide**: `man systemd.service`

---

**Your bot is now running 24/7 on a professional VPS!** 🚀
