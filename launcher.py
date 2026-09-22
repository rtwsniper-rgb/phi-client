import os
import subprocess
import minecraft_launcher_lib

# 1. Target PHICLIENTV2 on the user's Desktop
desktop_path = os.path.join(os.path.expanduser("~"), "Desktop")
minecraft_directory = os.path.join(desktop_path, "PHICLIENTV2")

# Set target game version
version = "1.21.11"

# 2. Track total download items for a clean 0%–100% progress output
max_progress = 0

def set_status(status: str):
    print(f"\n[Status] {status}")

def set_progress(progress: int):
    global max_progress
    if max_progress > 0:
        percent = int((progress / max_progress) * 100)
        print(f"Downloading... {percent}% ({progress}/{max_progress} files)", end="\r")
    else:
        print(f"Files processed: {progress}", end="\r")

def set_max_progress(max_val: int):
    global max_progress
    max_progress = max_val

callback = {
    "setStatus": set_status,
    "setProgress": set_progress,
    "setMaxProgress": set_max_progress
}

# 3. Download and install all required client files and assets
print(f"Installing Minecraft {version} into: {minecraft_directory}")
minecraft_launcher_lib.install.install_minecraft_version(
    version, 
    minecraft_directory, 
    callback=callback
)

# 4. Configure launch options (Offline / Singleplayer mode)
options = {
    "username": "Player1",
    "uuid": "",
    "token": ""
}

# 5. Build launch command and start Minecraft
command = minecraft_launcher_lib.command.get_minecraft_command(
    version, 
    minecraft_directory, 
    options
)

print("\nLaunching Minecraft...")
subprocess.run(command)