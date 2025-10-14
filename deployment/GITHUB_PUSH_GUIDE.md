# 📤 Push ORAKL Bot to GitHub - Complete Guide

**Step-by-step guide to push your bot to GitHub for cloud deployment.**

---

## ⚠️ CRITICAL: Security First

**NEVER commit secrets to GitHub!** Your `.gitignore` file is configured to prevent this.

### What Gets Excluded (Safe ✅):
- `.env` files (your API keys, tokens)
- `logs/` directory
- Local scripts (prevent_sleep.ps1, etc.)
- Python cache files

### What Gets Committed (Public):
- All Python code (`*.py`)
- `requirements.txt`
- `Dockerfile`
- Deployment configs (`render.yaml`, etc.)
- Documentation

---

## Option 1: Using GitHub Desktop (Easiest ⭐)

### Step 1: Install GitHub Desktop

1. Download: https://desktop.github.com
2. Install and launch
3. Sign in with your GitHub account

### Step 2: Add Repository

1. Click **"File"** → **"Add local repository"**
2. Click **"Choose..."**
3. Navigate to: `C:\ORAKL Bot`
4. Click **"Add Repository"**

### Step 3: Create Repository on GitHub

1. Click **"Publish repository"** (top)
2. Name: `orakl-bot` (or your preferred name)
3. Description: "ORAKL Options Flow Discord Bot"
4. ⚠️ **UNCHECK** "Keep this code private" (unless you want private)
5. Click **"Publish Repository"**

### Step 4: Verify

1. Go to GitHub.com
2. Navigate to your repositories
3. You should see `orakl-bot`
4. Click into it - code should be there!

**✅ Done! Skip to "Verify Secrets Not Committed" section below.**

---

## Option 2: Using Command Line (Traditional)

### Step 1: Install Git

**Check if Git is installed:**
```bash
git --version
```

**If not installed:**
1. Download: https://git-scm.com/download/win
2. Install with default settings
3. Restart terminal

### Step 2: Configure Git (First Time Only)

```bash
git config --global user.name "Your Name"
git config --global user.email "your.email@example.com"
```

### Step 3: Initialize Repository

```bash
# Navigate to bot directory
cd "C:\ORAKL Bot"

# Initialize Git repository
git init

# Check status (see what will be committed)
git status
```

**Expected output:**
```
On branch main
Untracked files:
  .gitignore
  Dockerfile
  main.py
  requirements.txt
  src/
  ...

.env will NOT appear (good - it's ignored!)
```

### Step 4: Stage All Files

```bash
# Add all files (excluding .gitignore items)
git add .

# Verify what's staged
git status
```

**Should show:**
```
Changes to be committed:
  new file:   .gitignore
  new file:   Dockerfile
  new file:   main.py
  ...
```

**⚠️ VERIFY `.env` is NOT listed!**

### Step 5: Create First Commit

```bash
git commit -m "Initial commit - ORAKL Discord Bot v2.0"
```

### Step 6: Create GitHub Repository

1. Go to https://github.com/new
2. Repository name: `orakl-bot`
3. Description: "ORAKL Options Flow Discord Bot"
4. Public or Private (your choice)
5. **DO NOT** initialize with README, .gitignore, or license
6. Click **"Create repository"**

### Step 7: Link and Push to GitHub

**GitHub will show you commands. Use these:**

```bash
# Add GitHub as remote (replace with YOUR repo URL)
git remote add origin https://github.com/YOUR_USERNAME/orakl-bot.git

# Rename branch to main (if needed)
git branch -M main

# Push to GitHub
git push -u origin main
```

**Enter GitHub credentials when prompted.**

### Step 8: Verify on GitHub

1. Go to your repository on GitHub
2. Verify files are there
3. **Click `.gitignore`** - should see your secrets excluded
4. **Verify `.env` is NOT in the file list** ✅

**✅ Done!**

---

## 🔒 Verify Secrets Not Committed

### Critical Check:

**On GitHub, search your repository for sensitive data:**

```
Search your repo for: "DISCORD_BOT_TOKEN"
Search your repo for: "POLYGON_API_KEY"
Search your repo for: "WEBHOOK_URL"
```

**Expected result**: ❌ No matches found

**If you find secrets:**
1. **IMMEDIATELY** delete the repository
2. **Rotate all secrets** (new Discord token, new API keys)
3. Re-push with proper `.gitignore`

---

## 📝 Your Repository Structure

Your GitHub repo will look like this:

```
orakl-bot/
├── .gitignore              ✅ Visible (protects secrets)
├── Dockerfile              ✅ Visible (for cloud deployment)
├── requirements.txt        ✅ Visible (dependencies)
├── render.yaml            ✅ Visible (Render config)
├── railway.json           ✅ Visible (Railway config)
├── main.py                ✅ Visible (entry point)
├── setup.py               ✅ Visible
├── src/                   ✅ Visible (all Python code)
│   ├── discord_bot.py
│   ├── bot_manager.py
│   ├── config.py
│   ├── bots/
│   └── utils/
├── deployment/            ✅ Visible (cloud guides)
│   ├── README.md
│   ├── RENDER_DEPLOYMENT.md
│   └── ...
├── tests/                 ✅ Visible
│
├── .env                   ❌ NOT visible (ignored ✅)
├── logs/                  ❌ NOT visible (ignored ✅)
├── ecosystem.config.js    ❌ NOT visible (ignored ✅)
```

---

## 🔄 Making Future Updates

### After Initial Push:

**Every time you make code changes:**

```bash
# Check what changed
git status

# Add changes
git add .

# Commit with message
git commit -m "Add new features / Fix bugs / etc."

# Push to GitHub
git push
```

**Cloud platforms (Render/Railway) will auto-deploy!**

---

## 🚨 Troubleshooting

### "Permission denied (publickey)"

**Solution 1: Use HTTPS instead of SSH**
```bash
git remote set-url origin https://github.com/YOUR_USERNAME/orakl-bot.git
git push
```

**Solution 2: Use Personal Access Token**
1. GitHub → Settings → Developer settings → Personal access tokens
2. Generate new token (classic)
3. Select scopes: `repo`
4. Use token as password when pushing

### "Failed to push some refs"

**Someone else pushed or you have conflicts:**
```bash
# Pull latest changes first
git pull origin main --rebase

# Then push
git push
```

### "Nothing to commit"

**You haven't made changes, or they're all ignored:**
```bash
# See what's being ignored
git status --ignored

# Force add a specific file if needed
git add -f filename.py
```

### Accidentally Committed Secrets

**⚠️ IMMEDIATE ACTION REQUIRED:**

```bash
# Remove from history (CAREFUL!)
git filter-branch --force --index-filter \
  "git rm --cached --ignore-unmatch .env" \
  --prune-empty --tag-name-filter cat -- --all

# Force push (overwrites GitHub)
git push origin --force --all
```

**Then:**
1. Rotate ALL secrets immediately
2. New Discord token, new API keys
3. Update `.env` locally only

---

## ✅ Post-Push Checklist

After pushing to GitHub, verify:

- [ ] Repository visible on GitHub.com
- [ ] `.gitignore` file present
- [ ] `.env` file NOT visible in repo
- [ ] `requirements.txt` present
- [ ] `Dockerfile` present
- [ ] `render.yaml` present
- [ ] All Python code visible
- [ ] No secrets in code (search repo)
- [ ] Ready for cloud deployment!

---

## 🚀 Next Step: Deploy to Cloud

**After pushing to GitHub:**

1. **Render Deployment**: [RENDER_DEPLOYMENT.md](RENDER_DEPLOYMENT.md)
   - Dashboard → New Background Worker
   - Connect GitHub repo
   - Add environment variables (from your local `.env`)
   - Deploy!

2. **Your GitHub repo URL will be:**
   ```
   https://github.com/YOUR_USERNAME/orakl-bot
   ```

---

## 📋 Quick Command Reference

```bash
# Clone repo to another machine
git clone https://github.com/YOUR_USERNAME/orakl-bot.git

# Check status
git status

# Add all changes
git add .

# Commit changes
git commit -m "Your message"

# Push to GitHub
git push

# Pull latest from GitHub
git pull

# View commit history
git log --oneline

# Create new branch
git checkout -b feature-name

# Switch branches
git checkout main
```

---

## 🆘 Need Help?

- **Git Basics**: https://git-scm.com/book/en/v2
- **GitHub Docs**: https://docs.github.com
- **GitHub Desktop**: https://docs.github.com/en/desktop
- **Git Cheat Sheet**: https://training.github.com/downloads/github-git-cheat-sheet/

---

**🎯 After pushing to GitHub, go to [RENDER_DEPLOYMENT.md](RENDER_DEPLOYMENT.md) for cloud deployment!**

Your bots will be 24/7 in about 30 minutes total. 🚀
