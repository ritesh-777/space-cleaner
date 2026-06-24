# GNOME Space Cleaner

[![GNOME Version](https://img.shields.io/badge/GNOME-45%20%7C%2046%20%7C%2047%20%7C%2048%20%7C%2049%20%7C%2050%20%7C%2051-blue.svg)](https://gjs.guide)
[![License](https://img.shields.io/badge/License-GPLv3-red.svg)](LICENSE)

A gorgeous, native-integrated GNOME Shell extension that acts as a central **Mission Control** to monitor and clean up temporary files, logs, package caches, developer caches, browser caches, graphics shader caches, and system clutter directly from your top panel.

The extension is designed for public release, fully **distribution-agnostic**, and completely **asynchronous**—meaning your desktop will remain 100% lag-free and responsive during scanning and file cleaning.

---

## Key Features

*   **⚡ Silk-Smooth Performance**: Disk scans and deletes are offloaded to an asynchronous Python helper (`cleaner-helper.py`) executed via GJS `Gio.Subprocess`, preventing UI freezes or locks.
*   **🎨 Consistent GNOME Integration**: Built entirely using GNOME Shell's native `PopupSubMenuMenuItem` collapsible menus. It automatically adapts to light/dark modes and active shell themes.
*   **📦 Dynamic Multi-Distribution Support**: The backend automatically detects the active package manager in your system path and adjusts target cache paths and UI labels dynamically:
    *   **Fedora/RHEL**: Displays **"DNF5 Cache"** (or **"DNF Cache"**) pointing to `/var/cache/libdnf5` or `/var/cache/dnf`.
    *   **Ubuntu/Debian**: Displays **"APT Cache"** pointing to `/var/cache/apt/archives`.
    *   **Arch Linux**: Displays **"Pacman Cache"** pointing to `/var/cache/pacman/pkg`.
    *   **openSUSE**: Displays **"Zypper Cache"** pointing to `/var/cache/zypp/packages`.
    *   **Gentoo**: Displays **"Portage Cache"** pointing to `/var/cache/distfiles` and `/var/cache/binpkgs`.
*   **🛡️ Password Prompt Elevation only when needed**: The extension scans system directories inside user-space without any passwords (they are world-readable!). A graphical admin password prompt (`pkexec`) is triggered **only when the user clicks the "Clean" button** for system-space folders.
*   **📝 Systemd Journal Vacuuming**: Safely rotates and vacuums large service logging caches inside `/var/log/journal` down to a secure 50MB threshold, retaining recent logs for diagnostic safety.
*   **🧩 Arch, Manjaro, and AUR Awareness**: On Arch-based systems, Space Cleaner shows an AUR package cleanup row for built package artifacts from helpers such as Yay, Paru, Pikaur, Trizen, and Pamac build directories.
*   **🧹 Safe Clean All Scope**: Clean All includes low-surprise cleanup targets such as trash, thumbnails, font cache, Flatpak cache, package cache, AUR package artifacts, journal cleanup, coredumps, Snap cleanup, and developer caches.
*   **⚠️ Separate Browser & Shader Cleanup**: Browser and shader caches are shown as separate categories and excluded from Clean All because they can cause slower first page loads or temporary graphics/game stutter while caches rebuild.
*   **🛠️ Developer Caches Support**: Easily reclaims gigabytes of forgotten local caches created by Python's **Pip**, Node's **NPM**, and **Yarn** package managers.
*   **📁 XDG-Aware User Paths**: User cache/data paths respect `XDG_CACHE_HOME` and `XDG_DATA_HOME` where applicable.

---

## Collapsible Detailed Categories

<details>
<summary><b>🗑️ User Trash Bin</b> (Safe to clean)</summary>
Removes files inside `~/.local/share/Trash`. Emptying this permanently deletes files you have sent to the trash.
</details>

<details>
<summary><b>🖼️ Thumbnail Cache</b> (Safe to clean)</summary>
Removes file preview images in `~/.cache/thumbnails`. Cleaning this is safe; GNOME will automatically recreate thumbnails when you browse directories.
</details>

<details>
<summary><b>🔤 Font Cache</b> (Safe to clean)</summary>
Removes generated fontconfig cache files in `~/.cache/fontconfig` or `$XDG_CACHE_HOME/fontconfig`. Applications and fontconfig rebuild these files automatically when fonts are needed.
</details>

<details>
<summary><b>📱 Flatpak & Snap Caches</b> (Safe to clean)</summary>
Cleans local caches in `~/.cache/flatpak` and individual flatpak container caches. For Snaps, it cleans downloaded archives in `/var/lib/snapd/cache` and purges <b>disabled/inactive revisions</b> of installed Snap packages (which normally accumulate and consume massive space!).
</details>

<details>
<summary><b>💻 OS Package Cache</b> (Safe to clean)</summary>
Cleans compiled package files (`.rpm`, `.deb`, `.pkg.tar.zst`) left behind in `/var/cache/` after installing updates or software. Package managers will easily fetch package indexes fresh from online mirrors when needed.
</details>

<details>
<summary><b>📦 AUR Packages</b> (Arch-based systems only)</summary>
Removes built AUR package artifacts (`*.pkg.tar*`) from common helper caches including Yay, Paru, Pikaur, Trizen, Pacaur, Aurman, and Manjaro Pamac build locations such as `/var/tmp/pamac-build-$USER`. It keeps source/build directories and PKGBUILDs intact.
</details>

<details>
<summary><b>⚙️ System Journal Logs</b> (Safe to clean)</summary>
Cleans large log archives by rotating active journals and vacuuming archived journals. Keeps your logs within a safe, manageable 50MB threshold so your disk never fills up with old background service records.
</details>

<details>
<summary><b>💥 System Coredumps</b> (Safe to clean)</summary>
Removes crash dump files in `/var/lib/systemd/coredump`. These are useful only when debugging old crashes; deleting them does not remove applications or settings.
</details>

<details>
<summary><b>☕ Developer Caches</b> (Safe to clean)</summary>
Cleans package manager folders used by programmers, including Pip cache, NPM `_cacache`, `_npx`, `_logs`, and Yarn caches. Caches are safely deleted; package managers will fetch dependencies from online registries on the next build.
</details>

<details>
<summary><b>🌐 Browser Cache</b> (Separate cleanup; excluded from Clean All)</summary>
Removes cache-only directories for Firefox and Chromium-family browsers. Cookies, history, bookmarks, saved logins, and browser profiles are not cleaned. This category is separate because pages can load slower after cleaning and offline web caches may need to rebuild.
</details>

<details>
<summary><b>🎮 Shader Cache</b> (Separate cleanup; excluded from Clean All)</summary>
Removes graphics shader cache directories such as Mesa, Vulkan, and NVIDIA shader caches. This category is separate because games and graphics-heavy apps may stutter temporarily while shaders rebuild.
</details>

---

## Graphical Installer (One-Click Curl Installation)

You can install this GNOME Extension directly from GitHub using a single automated terminal command. 

Open your terminal and run:

```bash
curl -fsSL https://raw.githubusercontent.com/ritesh-777/space-cleaner/main/install.sh | bash
```

### Post-Installation Setup:
1. **Save your work** and **Log out of your Linux session, then log back in** to force GNOME Shell to index the new extension directory.
2. Enable the extension using your terminal:
   ```bash
   gnome-extensions enable space-cleaner@ritesh
   ```
   *(Or open your pre-installed **Extensions** graphical manager app and toggle it on).*

---

## Local Development

To set up a local development environment:

1. **Clone the repository** to any folder on your machine:
   ```bash
   git clone https://github.com/ritesh-777/space-cleaner.git
   cd space-cleaner
   ```

2. **Link the repository** to your local GNOME Shell extensions directory:
   ```bash
   mkdir -p ~/.local/share/gnome-shell/extensions/
   ln -s "$(pwd)" ~/.local/share/gnome-shell/extensions/space-cleaner@ritesh
   ```

3. **Verify the backend** works correctly by running the Python helper script standalone in your terminal:
   ```bash
   python3 cleaner-helper.py scan
   ```

4. **Reload GNOME Shell** (log out and back in) and enable the extension to start testing!

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## License

This project is licensed under the GNU General Public License v3.0 — see the [LICENSE](LICENSE) file for details.
