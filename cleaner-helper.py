#!/usr/bin/env python3
"""
GNOME Space Cleaner - System Cache and Trash Cleaning Backend
============================================================
Author: Ritesh (GitHub: ritesh-777)
License: GNU GPLv3

This script acts as the lightweight, asynchronous backend for the GNOME Space Cleaner
extension. It calculates directory storage usage and performs cleanups safely.

Design Architecture:
-------------------
To prevent the GNOME Shell thread from freezing during heavy disk input/output,
this helper script is executed asynchronously via GJS `Gio.Subprocess` and outputs
structured JSON.

Supported Categories & Clean Actions:
-------------------------------------
1. User-Space (No root elevation required):
   - Trash Bin: ~/.local/share/Trash
   - Thumbnail Cache: ~/.cache/thumbnails
   - Flatpak Cache: ~/.cache/flatpak and ~/.var/app/*/cache
   - Developer Caches: ~/.cache/pip, ~/.npm/_cacache, ~/.cache/yarn
2. System-Space (Root elevation via `pkexec` triggered only during cleanup):
   - OS Package Manager caches (APT, DNF/DNF5, Pacman, Zypper, Portage)
   - Snap Cache & Inactive Snap Revisions (/var/lib/snapd/cache)
   - Systemd Journal logs (/var/log/journal)
"""

import os
import sys
import json
import shutil
import subprocess

# Standard User Home directory path resolution
HOME = os.path.expanduser("~")

def get_dir_size(path):
    """
    Recursively calculates the total storage size of a directory in bytes.
    
    Safety features:
    - Gracefully handles and skips directories with restricted permissions.
    - Excludes symbolic links (islink) to prevent circular referencing/infinite loops.
    
    Args:
        path (str): The absolute path of the directory to scan.
        
    Returns:
        int: Total size in bytes.
    """
    total_size = 0
    if not os.path.exists(path):
        return 0
    if os.path.isfile(path) or os.path.islink(path):
        try:
            return os.path.getsize(path)
        except Exception:
            return 0

    try:
        for root, dirs, files in os.walk(path):
            for f in files:
                fp = os.path.join(root, f)
                if not os.path.islink(fp):
                    try:
                        total_size += os.path.getsize(fp)
                    except Exception:
                        pass
    except Exception:
        pass
    return total_size

def get_trash_size():
    """
    Calculates the current size of the user's desktop Trash Bin.
    
    Returns:
        int: Total trash size in bytes.
    """
    trash_path = os.path.join(HOME, ".local/share/Trash")
    return get_dir_size(trash_path)

def get_thumbnails_size():
    """
    Calculates the size of the GNOME thumbnail icon preview cache.
    
    Returns:
        int: Total thumbnail cache size in bytes.
    """
    thumb_path = os.path.join(HOME, ".cache/thumbnails")
    return get_dir_size(thumb_path)

def get_flatpak_size():
    """
    Calculates size of user-level Flatpak runtime caches and app caches.
    Scans standard local cache and application-specific sandboxed directories.
    
    Returns:
        int: Total Flatpak cache size in bytes.
    """
    size = get_dir_size(os.path.join(HOME, ".cache/flatpak"))
    var_app = os.path.join(HOME, ".var/app")
    if os.path.exists(var_app):
        for app in os.listdir(var_app):
            app_cache = os.path.join(var_app, app, "cache")
            if os.path.exists(app_cache):
                size += get_dir_size(app_cache)
    return size

def get_dev_caches_size():
    """
    Aggregates size of local libraries and indices downloaded by development tools:
    - Python Pip download cache
    - Node NPM cache
    - Yarn caches (Classic yarn and modern Berry yarn caches)
    
    Returns:
        int: Total developer caches size in bytes.
    """
    size = 0
    size += get_dir_size(os.path.join(HOME, ".cache/pip"))
    size += get_dir_size(os.path.join(HOME, ".npm/_cacache"))
    size += get_dir_size(os.path.join(HOME, ".cache/yarn"))
    size += get_dir_size(os.path.join(HOME, ".yarn/berry/cache"))
    return size

def get_journal_size():
    """
    Calculates size of Systemd Journal logs in /var/log/journal.
    Since journals are usually world-readable, we can scan them without root.
    
    Returns:
        int: Total journal logs size in bytes.
    """
    return get_dir_size("/var/log/journal")

def get_snap_size():
    """
    Measures space consumed by Snap packages.
    - Scans downloaded Snap package archives (/var/lib/snapd/cache)
    - Measures size of unused/disabled snaps retained by snapd in /var/lib/snapd/snaps
    
    Returns:
        int: Total Snap cache size in bytes.
    """
    size = 0
    size += get_dir_size("/var/lib/snapd/cache")
    if shutil.which("snap") and os.path.exists("/var/lib/snapd/snaps"):
        try:
            result = subprocess.run(["snap", "list", "--all"], capture_output=True, text=True, check=False)
            if result.returncode == 0:
                for line in result.stdout.splitlines()[1:]:
                    parts = line.split()
                    if len(parts) >= 6 and "disabled" in parts:
                        snap_name = parts[0]
                        rev = parts[2]
                        snap_file = f"/var/lib/snapd/snaps/{snap_name}_{rev}.snap"
                        if os.path.exists(snap_file):
                            size += os.path.getsize(snap_file)
        except Exception:
            pass
    return size

def get_package_cache_details():
    """
    Detects which Linux distribution package manager is installed on the current OS
    and scans its corresponding local cache directory.
    
    Supports: DNF5, DNF, APT, Pacman, Zypper, Portage.
    
    Returns:
        tuple (str, int): (Detected Package Manager Name, Total Cache Size in Bytes)
    """
    size = 0
    detected = "None"
    
    if shutil.which("dnf5"):
        detected = "DNF5"
        size += get_dir_size("/var/cache/libdnf5")
    elif shutil.which("dnf"):
        detected = "DNF"
        size += get_dir_size("/var/cache/dnf")
    elif shutil.which("apt-get") or shutil.which("apt"):
        detected = "APT"
        size += get_dir_size("/var/cache/apt/archives")
    elif shutil.which("pacman"):
        detected = "Pacman"
        size += get_dir_size("/var/cache/pacman/pkg")
    elif shutil.which("zypper"):
        detected = "Zypper"
        size += get_dir_size("/var/cache/zypp/packages")
    elif shutil.which("emerge") or os.path.exists("/var/cache/distfiles"):
        detected = "Portage"
        size += get_dir_size("/var/cache/distfiles")
        size += get_dir_size("/var/cache/binpkgs")
        
    return detected, size

def scan():
    """
    Scans all categories and outputs their current sizes in structured JSON format.
    """
    pkg_mgr, pkg_size = get_package_cache_details()
    data = {
        "trash": get_trash_size(),
        "thumbnails": get_thumbnails_size(),
        "flatpak": get_flatpak_size(),
        "snap": get_snap_size(),
        "packages": pkg_size,
        "packages_mgr": pkg_mgr,
        "journal": get_journal_size(),
        "dev_caches": get_dev_caches_size(),
    }
    print(json.dumps(data))

def clean_trash():
    """
    Empties the desktop Trash Bin by deleting files and metadata.
    
    Returns:
        int: Number of bytes freed.
    """
    trash_path = os.path.join(HOME, ".local/share/Trash")
    freed = get_trash_size()
    if os.path.exists(trash_path):
        for sub in ["files", "info"]:
            p = os.path.join(trash_path, sub)
            if os.path.exists(p):
                for item in os.listdir(p):
                    item_path = os.path.join(p, item)
                    try:
                        if os.path.isdir(item_path) and not os.path.islink(item_path):
                            shutil.rmtree(item_path)
                        else:
                            os.remove(item_path)
                    except Exception:
                        pass
    return freed

def clean_thumbnails():
    """
    Deletes cached thumbnail previews. GNOME automatically regenerates them as needed.
    
    Returns:
        int: Number of bytes freed.
    """
    thumb_path = os.path.join(HOME, ".cache/thumbnails")
    freed = get_thumbnails_size()
    if os.path.exists(thumb_path):
        for root, dirs, files in os.walk(thumb_path):
            for f in files:
                try:
                    os.remove(os.path.join(root, f))
                except Exception:
                    pass
            for d in dirs:
                try:
                    shutil.rmtree(os.path.join(root, d))
                except Exception:
                    pass
    return freed

def clean_flatpak():
    """
    Deletes local Flatpak caches and application-specific caches.
    
    Returns:
        int: Number of bytes freed.
    """
    freed = get_flatpak_size()
    p = os.path.join(HOME, ".cache/flatpak")
    if os.path.exists(p):
        try:
            shutil.rmtree(p)
            os.makedirs(p, exist_ok=True)
        except Exception:
            pass
    var_app = os.path.join(HOME, ".var/app")
    if os.path.exists(var_app):
        for app in os.listdir(var_app):
            app_cache = os.path.join(var_app, app, "cache")
            if os.path.exists(app_cache):
                try:
                    shutil.rmtree(app_cache)
                    os.makedirs(app_cache, exist_ok=True)
                except Exception:
                    pass
    return freed

def clean_dev_caches():
    """
    Deletes local caches generated by Pip, NPM, and Yarn.
    
    Returns:
        int: Number of bytes freed.
    """
    freed = get_dev_caches_size()
    p = os.path.join(HOME, ".cache/pip")
    if os.path.exists(p):
        try:
            shutil.rmtree(p)
        except Exception:
            pass
    p = os.path.join(HOME, ".npm/_cacache")
    if os.path.exists(p):
        try:
            shutil.rmtree(p)
        except Exception:
            pass
    for p in [os.path.join(HOME, ".cache/yarn"), os.path.join(HOME, ".yarn/berry/cache")]:
        if os.path.exists(p):
            try:
                shutil.rmtree(p)
            except Exception:
                pass
    return freed

def clean_snap():
    """
    Elevates permissions via pkexec to clear snap caches and inactive snap packages.
    
    Returns:
        int: Number of bytes freed.
    """
    freed = get_snap_size()
    commands = []
    
    if os.path.exists("/var/lib/snapd/cache") and os.listdir("/var/lib/snapd/cache"):
        commands.append(["pkexec", "rm", "-rf", "/var/lib/snapd/cache/*"])
        
    if shutil.which("snap") and os.path.exists("/var/lib/snapd/snaps"):
        try:
            result = subprocess.run(["snap", "list", "--all"], capture_output=True, text=True, check=False)
            if result.returncode == 0:
                for line in result.stdout.splitlines()[1:]:
                    parts = line.split()
                    if len(parts) >= 6 and "disabled" in parts:
                        snap_name = parts[0]
                        rev = parts[2]
                        commands.append(["pkexec", "snap", "remove", snap_name, "--revision=" + rev])
        except Exception:
            pass

    for cmd in commands:
        try:
            subprocess.run(cmd, check=False)
        except Exception:
            pass
            
    return freed

def clean_packages():
    """
    Elevates permissions via pkexec to clean cached package manager packages.
    
    Returns:
        int: Number of bytes freed.
    """
    freed = get_package_cache_details()[1]
    pkg_mgr = get_package_cache_details()[0]
    
    cmd = []
    if pkg_mgr == "DNF5":
        cmd = ["pkexec", "dnf5", "clean", "packages", "-y"]
    elif pkg_mgr == "DNF":
        cmd = ["pkexec", "dnf", "clean", "packages", "-y"]
    elif pkg_mgr == "APT":
        cmd = ["pkexec", "apt-get", "clean"]
    elif pkg_mgr == "Pacman":
        cmd = ["pkexec", "pacman", "-Sc", "--noconfirm"]
    elif pkg_mgr == "Zypper":
        cmd = ["pkexec", "zypper", "clean", "-a"]
    elif pkg_mgr == "Portage":
        if shutil.which("eclean"):
            try:
                subprocess.run(["pkexec", "eclean", "distfiles"], check=False)
                subprocess.run(["pkexec", "eclean", "binpkgs"], check=False)
            except Exception:
                pass
        else:
            try:
                subprocess.run(["pkexec", "rm", "-rf", "/var/cache/distfiles/*", "/var/cache/binpkgs/*"], check=False)
            except Exception:
                pass
            
    if cmd:
        try:
            subprocess.run(cmd, check=False)
        except Exception:
            pass
            
    return freed

def clean_journal():
    """
    Elevates permissions via pkexec to vacuum systemd logs down to a safe 50MB.
    
    Returns:
        int: Number of bytes freed.
    """
    freed = get_journal_size()
    try:
        subprocess.run(["pkexec", "journalctl", "--vacuum-size=50M"], check=False)
    except Exception:
        pass
    return freed

def clean(category):
    """
    Cleans a specific cache category and outputs a confirmation JSON.
    """
    freed = 0
    if category == "trash":
        freed = clean_trash()
    elif category == "thumbnails":
        freed = clean_thumbnails()
    elif category == "flatpak":
        freed = clean_flatpak()
    elif category == "dev_caches":
        freed = clean_dev_caches()
    elif category == "snap":
        freed = clean_snap()
    elif category == "packages":
        freed = clean_packages()
    elif category == "journal":
        freed = clean_journal()
    print(json.dumps({"category": category, "freed": freed}))

def clean_all():
    """
    Executes a sequential cleanup of all cached categories and outputs total freed space.
    """
    freed = 0
    freed += clean_trash()
    freed += clean_thumbnails()
    freed += clean_flatpak()
    freed += clean_dev_caches()
    freed += clean_snap()
    freed += clean_packages()
    freed += clean_journal()
    print(json.dumps({"category": "all", "freed": freed}))

def main():
    """
    Main entry point for command-line arguments parsing.
    """
    if len(sys.argv) < 2:
        print("Usage: cleaner-helper.py [scan|clean|clean-all] [category]")
        sys.exit(1)
        
    cmd = sys.argv[1]
    if cmd == "scan":
        scan()
    elif cmd == "clean-all":
        clean_all()
    elif cmd == "clean" and len(sys.argv) >= 3:
        clean(sys.argv[2])
    else:
        print(f"Unknown command or missing argument: {cmd}")
        sys.exit(1)

if __name__ == "__main__":
    main()
