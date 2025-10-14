#!/usr/bin/env python3
"""
ORAKL Bot Auto-Setup Script
Automatically configures and sets up the bot to run on startup
"""

import os
import sys
import platform
import subprocess
import shutil
from pathlib import Path
import json

class ORAKLSetup:
    def __init__(self):
        self.system = platform.system()
        self.bot_dir = Path.cwd()
        self.python_path = sys.executable
        
    def print_banner(self):
        print("""
╔══════════════════════════════════════════════╗
║          ORAKL Options Flow Bot             ║
║           Auto-Setup Installer               ║
╚══════════════════════════════════════════════╝
        """)
        print(f"System: {self.system}")
        print(f"Python: {self.python_path}")
        print(f"Bot Directory: {self.bot_dir}\n")
    
    def install_dependencies(self):
        """Install Python dependencies"""
        print("📦 Installing dependencies...")
        try:
            subprocess.check_call([
                self.python_path, "-m", "pip", "install", "-r", "requirements.txt"
            ])
            print("✅ Dependencies installed successfully")
            return True
        except subprocess.CalledProcessError:
            print("❌ Failed to install dependencies")
            return False
    
    def create_env_file(self):
        """Create .env file from template"""
        if not Path('.env').exists():
            print("📝 Creating .env file...")
            if Path('config.env').exists():
                shutil.copy('config.env', '.env')
                print("✅ Created .env from config.env")
                print("⚠️  Please add your Discord Bot Token to .env file")
                return False
            elif Path('env.example').exists():
                shutil.copy('env.example', '.env')
                print("⚠️  Please edit .env file with your API keys")
                return False
            else:
                print("❌ No env template found")
                return False
        else:
            print("✅ .env file exists")
            return True
    
    def setup_windows_autostart(self):
        """Setup Windows Task Scheduler"""
        print("🪟 Setting up Windows auto-start...")
        
        # Create batch file
        batch_content = f"""@echo off
cd /d "{self.bot_dir}"
"{self.python_path}" main.py
if %errorlevel% neq 0 (
    echo ORAKL Bot crashed. Restarting in 10 seconds...
    timeout /t 10 /nobreak
    goto :start
)
"""
        
        batch_file = self.bot_dir / "orakl_bot.bat"
        batch_file.write_text(batch_content)
        
        # Create VBS file for hidden startup
        vbs_content = f"""
Set WshShell = CreateObject("WScript.Shell")
WshShell.Run chr(34) & "{batch_file}" & Chr(34), 0
Set WshShell = Nothing
"""
        vbs_file = self.bot_dir / "orakl_bot_hidden.vbs"
        vbs_file.write_text(vbs_content)
        
        # Add to startup folder
        startup_folder = Path.home() / "AppData/Roaming/Microsoft/Windows/Start Menu/Programs/Startup"
        startup_shortcut = startup_folder / "ORAKL_Bot.vbs"
        shutil.copy(vbs_file, startup_shortcut)
        
        # Create Task Scheduler task
        task_xml = f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>ORAKL Options Flow Bot</Description>
  </RegistrationInfo>
  <Triggers>
    <LogonTrigger>
      <Enabled>true</Enabled>
    </LogonTrigger>
    <BootTrigger>
      <Enabled>true</Enabled>
    </BootTrigger>
  </Triggers>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <RestartOnFailure>
      <Interval>PT1M</Interval>
      <Count>999</Count>
    </RestartOnFailure>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{self.python_path}</Command>
      <Arguments>main.py</Arguments>
      <WorkingDirectory>{self.bot_dir}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>"""
        
        task_file = self.bot_dir / "orakl_task.xml"
        task_file.write_text(task_xml)
        
        try:
            # Import task to Task Scheduler
            subprocess.run([
                "schtasks", "/create", "/tn", "ORAKL_Bot", 
                "/xml", str(task_file), "/f"
            ], check=True)
            print("✅ Windows Task Scheduler configured")
            print("✅ Bot will start automatically on Windows startup")
        except:
            print("⚠️  Manual Task Scheduler setup may be required")
        
        return True
    
    def setup_macos_autostart(self):
        """Setup macOS launchd"""
        print("🍎 Setting up macOS auto-start...")
        
        plist_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.orakl.bot</string>
    <key>ProgramArguments</key>
    <array>
        <string>{self.python_path}</string>
        <string>{self.bot_dir}/main.py</string>
    </array>
    <key>WorkingDirectory</key>
    <string>{self.bot_dir}</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <dict>
        <key>SuccessfulExit</key>
        <false/>
        <key>Crashed</key>
        <true/>
    </dict>
    <key>StandardOutPath</key>
    <string>{self.bot_dir}/logs/orakl.log</string>
    <key>StandardErrorPath</key>
    <string>{self.bot_dir}/logs/orakl_error.log</string>
    <key>StartInterval</key>
    <integer>300</integer>
</dict>
</plist>"""
        
        # Create logs directory
        logs_dir = self.bot_dir / "logs"
        logs_dir.mkdir(exist_ok=True)
        
        # Save plist file
        plist_path = Path.home() / "Library/LaunchAgents/com.orakl.bot.plist"
        plist_path.parent.mkdir(exist_ok=True)
        plist_path.write_text(plist_content)
        
        try:
            # Load the launch agent
            subprocess.run(["launchctl", "unload", str(plist_path)], capture_output=True)
            subprocess.run(["launchctl", "load", str(plist_path)], check=True)
            print("✅ macOS LaunchAgent configured")
            print("✅ Bot will start automatically on macOS startup")
        except:
            print("⚠️  Manual launchctl setup may be required")
            print(f"   Run: launchctl load {plist_path}")
        
        return True
    
    def setup_linux_autostart(self):
        """Setup Linux systemd"""
        print("🐧 Setting up Linux auto-start...")
        
        service_content = f"""[Unit]
Description=ORAKL Options Flow Bot
After=network.target network-online.target
Wants=network-online.target

[Service]
Type=simple
User={os.getenv('USER')}
WorkingDirectory={self.bot_dir}
ExecStart={self.python_path} {self.bot_dir}/main.py
Restart=always
RestartSec=10
StandardOutput=append:{self.bot_dir}/logs/orakl.log
StandardError=append:{self.bot_dir}/logs/orakl_error.log

[Install]
WantedBy=multi-user.target"""
        
        # Create logs directory
        logs_dir = self.bot_dir / "logs"
        logs_dir.mkdir(exist_ok=True)
        
        service_file = self.bot_dir / "orakl.service"
        service_file.write_text(service_content)
        
        try:
            # Copy to systemd and enable
            subprocess.run([
                "sudo", "cp", str(service_file), 
                "/etc/systemd/system/orakl.service"
            ], check=True)
            subprocess.run(["sudo", "systemctl", "daemon-reload"], check=True)
            subprocess.run(["sudo", "systemctl", "enable", "orakl.service"], check=True)
            subprocess.run(["sudo", "systemctl", "start", "orakl.service"], check=True)
            print("✅ Linux systemd service configured")
            print("✅ Bot will start automatically on Linux startup")
        except:
            print("⚠️  Manual systemd setup required. Run:")
            print(f"   sudo cp {service_file} /etc/systemd/system/")
            print("   sudo systemctl enable orakl.service")
            print("   sudo systemctl start orakl.service")
        
        return True
    
    def setup_pm2(self):
        """Setup PM2 (cross-platform)"""
        print("🔄 Checking for PM2...")
        
        try:
            # Check if npm is installed
            subprocess.run(["npm", "--version"], capture_output=True, check=True)
            
            # Install PM2 globally
            print("Installing PM2...")
            subprocess.run(["npm", "install", "-g", "pm2"], check=True)
            
            # Create PM2 ecosystem file
            ecosystem = {
                "apps": [{
                    "name": "ORAKL-Bot",
                    "script": "main.py",
                    "interpreter": self.python_path,
                    "cwd": str(self.bot_dir),
                    "autorestart": True,
                    "watch": False,
                    "max_restarts": 10,
                    "min_uptime": "10s",
                    "error_file": "logs/pm2-error.log",
                    "out_file": "logs/pm2-out.log",
                    "log_date_format": "YYYY-MM-DD HH:mm:ss Z"
                }]
            }
            
            with open("ecosystem.config.json", "w") as f:
                json.dump(ecosystem, f, indent=2)
            
            # Start with PM2
            subprocess.run(["pm2", "start", "ecosystem.config.json"], check=True)
            subprocess.run(["pm2", "save"], check=True)
            subprocess.run(["pm2", "startup"], capture_output=True)
            
            print("✅ PM2 configured successfully")
            return True
        except:
            print("⚠️  PM2 not available (requires Node.js)")
            return False
    
    def run(self):
        """Run the complete setup"""
        self.print_banner()
        
        # Step 1: Install dependencies
        if not self.install_dependencies():
            print("❌ Setup failed: Could not install dependencies")
            return False
        
        # Step 2: Create .env file
        env_ready = self.create_env_file()
        
        # Step 3: Setup auto-start based on OS
        print("\n🚀 Configuring auto-start...")
        
        # Try PM2 first (works on all platforms)
        if self.setup_pm2():
            print("✅ Using PM2 for auto-start")
        else:
            # Fall back to OS-specific methods
            if self.system == "Windows":
                self.setup_windows_autostart()
            elif self.system == "Darwin":  # macOS
                self.setup_macos_autostart()
            elif self.system == "Linux":
                self.setup_linux_autostart()
            else:
                print(f"⚠️  Unknown system: {self.system}")
                print("   Manual startup configuration required")
        
        print("\n" + "="*50)
        print("✅ ORAKL Bot setup complete!")
        print("="*50)
        
        if not env_ready:
            print("\n⚠️  IMPORTANT: Edit the .env file with your API keys")
            print("   1. Add your Polygon API key")
            print("   2. Add your Discord bot token")
            print("   3. Add your Discord webhook URL")
        
        print("\n📝 Next steps:")
        print("   1. Edit .env file with your credentials")
        print("   2. Restart your computer to test auto-start")
        print("   3. Or run manually: python main.py")
        print("\n💡 Commands:")
        print("   Check status: pm2 status (if using PM2)")
        print("   View logs: pm2 logs ORAKL-Bot")
        print("   Stop bot: pm2 stop ORAKL-Bot")
        
        return True

if __name__ == "__main__":
    setup = ORAKLSetup()
    setup.run()
