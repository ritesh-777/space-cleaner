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
USER_NAME = os.environ.get("USER") or os.path.basename(HOME)
CACHE_HOME = os.environ.get("XDG_CACHE_HOME", os.path.join(HOME, ".cache"))
DATA_HOME = os.environ.get("XDG_DATA_HOME", os.path.join(HOME, ".local/share"))
NPM_CACHE_DIR = os.environ.get("npm_config_cache", os.path.join(HOME, ".npm"))
TRASH_DIR = os.path.join(DATA_HOME, "Trash")
THUMBNAILS_DIR = os.path.join(CACHE_HOME, "thumbnails")
FONTCONFIG_CACHE_DIR = os.path.join(CACHE_HOME, "fontconfig")
FLATPAK_CACHE_DIR = os.path.join(CACHE_HOME, "flatpak")
PACMAN_CACHE_DIR = "/var/cache/pacman/pkg"
COREDUMP_DIR = "/var/lib/systemd/coredump"
JOURNAL_VACUUM_TARGET_BYTES = 50 * 1024 * 1024
FIREFOX_CACHE_ROOTS = [
    os.path.join(CACHE_HOME, "mozilla/firefox"),
]
CHROMIUM_CACHE_ROOTS = [
    os.path.join(CACHE_HOME, "chromium"),
    os.path.join(CACHE_HOME, "google-chrome"),
    os.path.join(CACHE_HOME, "google-chrome-beta"),
    os.path.join(CACHE_HOME, "google-chrome-unstable"),
    os.path.join(CACHE_HOME, "BraveSoftware/Brave-Browser"),
    os.path.join(CACHE_HOME, "microsoft-edge"),
    os.path.join(CACHE_HOME, "vivaldi"),
]
CHROMIUM_CACHE_DIR_NAMES = [
    "Cache",
    "Code Cache",
    "GPUCache",
    "DawnCache",
    "GrShaderCache",
    "ShaderCache",
]
SHADER_CACHE_DIRS = [
    os.path.join(CACHE_HOME, "mesa_shader_cache"),
    os.path.join(CACHE_HOME, "mesa_shader_cache_db"),
    os.path.join(CACHE_HOME, "vulkan"),
    os.path.join(CACHE_HOME, "nvidia/GLCache"),
    os.path.join(CACHE_HOME, "nvidia/ComputeCache"),
    os.path.join(CACHE_HOME, "NVIDIA/GLCache"),
    os.path.join(CACHE_HOME, "NVIDIA/ComputeCache"),
]
AUR_CACHE_ROOTS = [
    os.path.join(CACHE_HOME, "yay"),
    os.path.join(CACHE_HOME, "paru/clone"),
    os.path.join(CACHE_HOME, "pikaur/pkg"),
    os.path.join(CACHE_HOME, "pikaur/build"),
    os.path.join(CACHE_HOME, "trizen"),
    os.path.join(CACHE_HOME, "pacaur"),
    os.path.join(CACHE_HOME, "aurman"),
    os.path.join(CACHE_HOME, "pamac"),
    os.path.join("/var/tmp", f"pamac-build-{USER_NAME}"),
    os.path.join("/tmp", f"pamac-build-{USER_NAME}"),
]
PAMAC_BUILD_BASE_FALLBACKS = [
    "/var/tmp",
    "/tmp",
]

def list_dir_entries(path):
    """
    Returns absolute child paths for a directory, or an empty list if inaccessible.
    """
    try:
        return [os.path.join(path, entry) for entry in os.listdir(path)]
    except Exception:
        return []

def remove_path_contents(path):
    """
    Removes all direct children of a directory and returns bytes removed.
    """
    freed = get_dir_size(path)
    for item_path in list_dir_entries(path):
        try:
            if os.path.isdir(item_path) and not os.path.islink(item_path):
                shutil.rmtree(item_path)
            else:
                os.remove(item_path)
        except Exception as err:
            raise RuntimeError(f"Failed to remove {item_path}: {err}") from err
    return freed

def run_checked(cmd):
    """
    Runs a command and raises an actionable error if it fails.
    """
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        details = (result.stderr or result.stdout or "Command failed.").strip()
        raise RuntimeError(details)
    return result

def is_arch_based():
    """
    Detects Arch and Arch-derived distributions.
    """
    os_release = {}
    try:
        with open("/etc/os-release", "r", encoding="utf-8") as release_file:
            for line in release_file:
                if "=" not in line:
                    continue
                key, value = line.rstrip().split("=", 1)
                os_release[key] = value.strip('"')
    except Exception:
        pass

    distro_id = os_release.get("ID", "").lower()
    id_like = os_release.get("ID_LIKE", "").lower().split()
    return distro_id == "arch" or "arch" in id_like or shutil.which("pacman") is not None

def is_package_artifact(path):
    """
    Identifies built Arch package artifacts and their detached signatures.
    """
    name = os.path.basename(path)
    return ".pkg.tar" in name

def iter_aur_package_artifacts():
    """
    Yields built AUR package files from common AUR helper cache directories.
    """
    if not is_arch_based():
        return

    for cache_root in AUR_CACHE_ROOTS:
        if not os.path.exists(cache_root):
            continue
        try:
            for root, dirs, files in os.walk(cache_root):
                for filename in files:
                    path = os.path.join(root, filename)
                    if not os.path.islink(path) and is_package_artifact(path):
                        yield path
        except Exception:
            continue

def get_pamac_build_bases():
    """
    Returns Pamac build base directories from config plus common fallbacks.
    """
    bases = []
    try:
        with open("/etc/pamac.conf", "r", encoding="utf-8") as config_file:
            for line in config_file:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = [part.strip() for part in line.split("=", 1)]
                if key == "BuildDirectory" and value:
                    bases.append(os.path.expanduser(value))
    except Exception:
        pass

    bases.extend(PAMAC_BUILD_BASE_FALLBACKS)
    return unique_existing_paths(bases)

def get_pamac_build_roots():
    """
    Returns Pamac per-user AUR build roots, such as /var/tmp/pamac-build-user.
    """
    roots = [
        os.path.join(base, f"pamac-build-{USER_NAME}")
        for base in get_pamac_build_bases()
    ]
    return unique_existing_paths(roots)

def get_pamac_build_package_dirs():
    """
    Returns package build directories managed by Pamac.
    """
    dirs = []
    for root in get_pamac_build_roots():
        for path in list_dir_entries(root):
            if os.path.isdir(path) and not os.path.islink(path):
                dirs.append(path)
    return unique_existing_paths(dirs, get_pamac_build_roots())

def is_path_inside(path, base_dir):
    """
    Checks realpath containment to avoid following cache symlinks elsewhere.
    """
    try:
        real_path = os.path.realpath(path)
        real_base = os.path.realpath(base_dir)
        return real_path == real_base or real_path.startswith(real_base + os.sep)
    except Exception:
        return False

def unique_existing_paths(paths, base_dirs=None):
    """
    Returns existing paths once, preserving input order.
    """
    seen = set()
    result = []
    for path in paths:
        normalized = os.path.abspath(path)
        if normalized in seen or not os.path.exists(normalized) or os.path.islink(normalized):
            continue
        if base_dirs and not any(is_path_inside(normalized, base_dir) for base_dir in base_dirs):
            continue
        seen.add(normalized)
        result.append(normalized)
    return result

def get_browser_cache_paths():
    """
    Returns known browser cache directories without touching profile data.
    """
    paths = []

    for firefox_root in FIREFOX_CACHE_ROOTS:
        if not os.path.isdir(firefox_root):
            continue
        for profile in list_dir_entries(firefox_root):
            if os.path.isdir(profile) and not os.path.islink(profile):
                paths.append(os.path.join(profile, "cache2"))
                paths.append(os.path.join(profile, "startupCache"))

    for browser_root in CHROMIUM_CACHE_ROOTS:
        if not os.path.isdir(browser_root):
            continue
        candidate_profiles = [browser_root]
        candidate_profiles.extend(
            path for path in list_dir_entries(browser_root)
            if os.path.isdir(path) and not os.path.islink(path)
        )
        for profile in candidate_profiles:
            for cache_name in CHROMIUM_CACHE_DIR_NAMES:
                paths.append(os.path.join(profile, cache_name))

    return unique_existing_paths(paths, [CACHE_HOME])

def get_shader_cache_paths():
    """
    Returns known graphics shader cache directories.
    """
    return unique_existing_paths(SHADER_CACHE_DIRS, [CACHE_HOME])

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

def get_dir_disk_usage(path):
    """
    Calculates allocated disk usage for files under a path.
    Sparse files, including systemd journals, can have a much larger apparent
    size than the real disk space they currently consume.
    """
    total_size = 0
    if not os.path.exists(path):
        return 0

    paths = []
    if os.path.isfile(path) or os.path.islink(path):
        paths.append(path)
    else:
        try:
            for root, dirs, files in os.walk(path):
                paths.append(root)
                paths.extend(os.path.join(root, f) for f in files)
        except Exception:
            return 0

    for item_path in paths:
        try:
            stat_result = os.lstat(item_path)
            total_size += getattr(stat_result, "st_blocks", 0) * 512
        except Exception:
            pass

    return total_size

def get_trash_size():
    """
    Calculates the current size of the user's desktop Trash Bin.
    
    Returns:
        int: Total trash size in bytes.
    """
    return get_dir_size(TRASH_DIR)

def get_thumbnails_size():
    """
    Calculates the size of the GNOME thumbnail icon preview cache.
    
    Returns:
        int: Total thumbnail cache size in bytes.
    """
    return get_dir_size(THUMBNAILS_DIR)

def get_font_cache_size():
    """
    Calculates the size of fontconfig's generated font cache.
    """
    return get_dir_size(FONTCONFIG_CACHE_DIR)

def get_flatpak_size():
    """
    Calculates size of user-level Flatpak runtime caches and app caches.
    Scans standard local cache and application-specific sandboxed directories.
    
    Returns:
        int: Total Flatpak cache size in bytes.
    """
    size = get_dir_size(FLATPAK_CACHE_DIR)
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
    size += get_dir_size(os.path.join(CACHE_HOME, "pip"))
    size += get_dir_size(os.path.join(NPM_CACHE_DIR, "_cacache"))
    size += get_dir_size(os.path.join(NPM_CACHE_DIR, "_npx"))
    size += get_dir_size(os.path.join(NPM_CACHE_DIR, "_logs"))
    size += get_dir_size(os.path.join(CACHE_HOME, "yarn"))
    size += get_dir_size(os.path.join(HOME, ".yarn/berry/cache"))
    return size

def get_aur_packages_size():
    """
    Calculates the size of built AUR package artifacts and Pamac build files.
    """
    size = 0
    pamac_build_dirs = get_pamac_build_package_dirs()
    for path in pamac_build_dirs:
        size += get_dir_size(path)

    for path in iter_aur_package_artifacts():
        if any(is_path_inside(path, build_dir) for build_dir in pamac_build_dirs):
            continue
        try:
            size += os.path.getsize(path)
        except Exception:
            pass
    return size

def get_journal_size():
    """
    Calculates currently reclaimable Systemd Journal disk usage.
    The cleaner vacuums journals to 50MB, so usage below that threshold should
    not be shown as cleanable space.
    
    Returns:
        int: Reclaimable journal size in bytes.
    """
    usage = get_dir_disk_usage("/var/log/journal")
    return max(usage - JOURNAL_VACUUM_TARGET_BYTES, 0)

def get_coredumps_size():
    """
    Calculates the size of systemd coredump files.
    """
    return get_dir_size(COREDUMP_DIR)

def get_browser_cache_size():
    """
    Calculates the size of browser cache directories.
    """
    return sum(get_dir_size(path) for path in get_browser_cache_paths())

def get_shader_cache_size():
    """
    Calculates the size of graphics shader cache directories.
    """
    return sum(get_dir_size(path) for path in get_shader_cache_paths())

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
        size += get_dir_size(PACMAN_CACHE_DIR)
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
        "font_cache": get_font_cache_size(),
        "flatpak": get_flatpak_size(),
        "snap": get_snap_size(),
        "packages": pkg_size,
        "packages_mgr": pkg_mgr,
        "arch_based": is_arch_based(),
        "aur_packages": get_aur_packages_size(),
        "journal": get_journal_size(),
        "coredumps": get_coredumps_size(),
        "dev_caches": get_dev_caches_size(),
        "browser_cache": get_browser_cache_size(),
        "shader_cache": get_shader_cache_size(),
    }
    print(json.dumps(data))

def clean_trash():
    """
    Empties the desktop Trash Bin by deleting files and metadata.
    
    Returns:
        int: Number of bytes freed.
    """
    freed = get_trash_size()
    if os.path.exists(TRASH_DIR):
        for sub in ["files", "info"]:
            p = os.path.join(TRASH_DIR, sub)
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
    freed = get_thumbnails_size()
    if os.path.exists(THUMBNAILS_DIR):
        for root, dirs, files in os.walk(THUMBNAILS_DIR):
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

def clean_font_cache():
    """
    Deletes generated fontconfig cache files.
    """
    before = get_font_cache_size()
    if os.path.exists(FONTCONFIG_CACHE_DIR):
        for item_path in list_dir_entries(FONTCONFIG_CACHE_DIR):
            try:
                if os.path.isdir(item_path) and not os.path.islink(item_path):
                    shutil.rmtree(item_path)
                else:
                    os.remove(item_path)
            except Exception:
                pass
    after = get_font_cache_size()
    return max(before - after, 0)

def clean_flatpak():
    """
    Deletes local Flatpak caches and application-specific caches.
    
    Returns:
        int: Number of bytes freed.
    """
    before = get_flatpak_size()
    if os.path.exists(FLATPAK_CACHE_DIR):
        try:
            shutil.rmtree(FLATPAK_CACHE_DIR)
            os.makedirs(FLATPAK_CACHE_DIR, exist_ok=True)
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
    after = get_flatpak_size()
    return max(before - after, 0)

def clean_dev_caches():
    """
    Deletes local caches generated by Pip, NPM, and Yarn.
    
    Returns:
        int: Number of bytes freed.
    """
    before = get_dev_caches_size()
    paths = [
        os.path.join(CACHE_HOME, "pip"),
        os.path.join(NPM_CACHE_DIR, "_cacache"),
        os.path.join(NPM_CACHE_DIR, "_npx"),
        os.path.join(NPM_CACHE_DIR, "_logs"),
        os.path.join(CACHE_HOME, "yarn"),
        os.path.join(HOME, ".yarn/berry/cache"),
    ]
    for p in paths:
        if os.path.exists(p):
            try:
                shutil.rmtree(p)
            except Exception:
                pass
    after = get_dev_caches_size()
    return max(before - after, 0)

def clean_aur_packages():
    """
    Deletes built AUR package artifacts and Pamac AUR build files.
    """
    before = get_aur_packages_size()
    for path in get_pamac_build_package_dirs():
        try:
            shutil.rmtree(path)
        except Exception:
            pass

    pamac_build_dirs = get_pamac_build_package_dirs()
    for path in list(iter_aur_package_artifacts()):
        if any(is_path_inside(path, build_dir) for build_dir in pamac_build_dirs):
            continue
        try:
            os.remove(path)
        except Exception:
            pass
    after = get_aur_packages_size()
    return max(before - after, 0)

def clean_snap():
    """
    Elevates permissions via pkexec to clear snap caches and inactive snap packages.
    
    Returns:
        int: Number of bytes freed.
    """
    freed = get_snap_size()
    commands = []
    
    snap_cache_entries = list_dir_entries("/var/lib/snapd/cache")
    if snap_cache_entries:
        commands.append(["pkexec", "rm", "-rf", *snap_cache_entries])
        
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
        helper_path = os.path.abspath(__file__)
        cmd = ["pkexec", "python3", helper_path, "clean-pacman-cache-root"]
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
                cache_entries = (
                    list_dir_entries("/var/cache/distfiles") +
                    list_dir_entries("/var/cache/binpkgs")
                )
                if cache_entries:
                    subprocess.run(["pkexec", "rm", "-rf", *cache_entries], check=False)
            except Exception:
                pass
            
    if cmd:
        run_checked(cmd)
            
    return freed

def clean_pacman_cache_root():
    """
    Root-only Pacman cache cleanup used through pkexec.
    """
    if os.geteuid() != 0:
        raise RuntimeError("Pacman cache cleanup requires administrator privileges.")
    freed = remove_path_contents(PACMAN_CACHE_DIR)
    print(json.dumps({"category": "packages", "freed": freed}))

def clean_coredumps():
    """
    Elevates permissions to delete stored systemd coredump files.
    """
    before = get_coredumps_size()
    helper_path = os.path.abspath(__file__)
    run_checked(["pkexec", "python3", helper_path, "clean-coredumps-root"])
    after = get_coredumps_size()
    return max(before - after, 0)

def clean_coredumps_root():
    """
    Root-only coredump cleanup used through pkexec.
    """
    if os.geteuid() != 0:
        raise RuntimeError("Coredump cleanup requires administrator privileges.")
    freed = remove_path_contents(COREDUMP_DIR)
    print(json.dumps({"category": "coredumps", "freed": freed}))

def clean_paths(paths, size_func):
    """
    Deletes a set of cache paths and returns bytes actually removed.
    """
    before = size_func()
    for path in paths:
        try:
            if os.path.isdir(path) and not os.path.islink(path):
                shutil.rmtree(path)
            elif os.path.islink(path):
                continue
            else:
                os.remove(path)
        except Exception:
            pass
    after = size_func()
    return max(before - after, 0)

def clean_browser_cache():
    """
    Deletes known browser cache directories.
    """
    return clean_paths(get_browser_cache_paths(), get_browser_cache_size)

def clean_shader_cache():
    """
    Deletes known graphics shader cache directories.
    """
    return clean_paths(get_shader_cache_paths(), get_shader_cache_size)

def clean_journal():
    """
    Elevates permissions via pkexec to vacuum systemd logs down to a safe 50MB.
    
    Returns:
        int: Number of bytes freed.
    """
    before = get_dir_disk_usage("/var/log/journal")
    run_checked(["pkexec", "journalctl", "--rotate", "--vacuum-size=50M"])
    after = get_dir_disk_usage("/var/log/journal")
    return max(before - after, 0)

def clean(category):
    """
    Cleans a specific cache category and outputs a confirmation JSON.
    """
    freed = 0
    if category == "trash":
        freed = clean_trash()
    elif category == "thumbnails":
        freed = clean_thumbnails()
    elif category == "font_cache":
        freed = clean_font_cache()
    elif category == "flatpak":
        freed = clean_flatpak()
    elif category == "dev_caches":
        freed = clean_dev_caches()
    elif category == "snap":
        freed = clean_snap()
    elif category == "packages":
        freed = clean_packages()
    elif category == "aur_packages":
        freed = clean_aur_packages()
    elif category == "journal":
        freed = clean_journal()
    elif category == "coredumps":
        freed = clean_coredumps()
    elif category == "browser_cache":
        freed = clean_browser_cache()
    elif category == "shader_cache":
        freed = clean_shader_cache()
    print(json.dumps({"category": category, "freed": freed}))

def clean_all():
    """
    Executes a sequential cleanup of all cached categories and outputs total freed space.
    """
    freed = 0
    errors = []
    categories = [
        ("trash", get_trash_size, clean_trash),
        ("thumbnails", get_thumbnails_size, clean_thumbnails),
        ("font_cache", get_font_cache_size, clean_font_cache),
        ("flatpak", get_flatpak_size, clean_flatpak),
        ("dev_caches", get_dev_caches_size, clean_dev_caches),
        ("snap", get_snap_size, clean_snap),
        ("packages", lambda: get_package_cache_details()[1], clean_packages),
        ("aur_packages", get_aur_packages_size, clean_aur_packages),
        ("journal", get_journal_size, clean_journal),
        ("coredumps", get_coredumps_size, clean_coredumps),
    ]

    for category, size_func, clean_func in categories:
        try:
            if size_func() <= 0:
                continue
            freed += clean_func()
        except Exception as err:
            errors.append({"category": category, "error": str(err)})

    print(json.dumps({"category": "all", "freed": freed, "errors": errors}))

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
    elif cmd == "clean-pacman-cache-root":
        clean_pacman_cache_root()
    elif cmd == "clean-coredumps-root":
        clean_coredumps_root()
    else:
        print(f"Unknown command or missing argument: {cmd}")
        sys.exit(1)

if __name__ == "__main__":
    main()
