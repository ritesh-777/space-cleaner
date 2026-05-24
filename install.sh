#!/usr/bin/env bash
#
# GNOME Space Cleaner - Automated Installer Script
# 
# Clones or updates the GNOME Space Cleaner extension directly into your local GNOME Shell directory.
#

set -e

EXT_DIR="$HOME/.local/share/gnome-shell/extensions/space-cleaner@ritesh"

echo "Installing GNOME Space Cleaner..."

if [ -d "$EXT_DIR" ]; then
    if [ -d "$EXT_DIR/.git" ]; then
        echo "Updating existing installation from GitHub..."
        (cd "$EXT_DIR" && git pull)
    else
        echo "Replacing existing manual installation..."
        rm -rf "$EXT_DIR"
        git clone https://github.com/ritesh-777/space-cleaner.git "$EXT_DIR"
    fi
else
    echo "Cloning repository to local extensions folder..."
    git clone https://github.com/ritesh-777/space-cleaner.git "$EXT_DIR"
fi

echo ""
echo "--------------------------------------------------------"
echo "Installed successfully!"
echo "--------------------------------------------------------"
echo "1. Restart your GNOME Shell session (Log out and log back in)."
echo "2. Enable the extension via: gnome-extensions enable space-cleaner@ritesh"
echo "   (or use the graphical Extensions manager app)."
echo ""
