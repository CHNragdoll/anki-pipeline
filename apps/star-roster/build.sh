#!/bin/bash
set -euo pipefail
source_dir="$(cd "$(dirname "$0")" && pwd)"
build_dir="$(mktemp -d)"
trap 'rm -rf "$build_dir"' EXIT
app="$build_dir/Star 记录.app"
mkdir -p "$app/Contents/MacOS" "$app/Contents/Resources" "$build_dir/AppIcon.iconset"
cp "$source_dir/Info.plist" "$app/Contents/Info.plist"
cp "$source_dir/google_reports.py" "$app/Contents/Resources/google_reports.py"
if [[ -n "${STAR_METRICS_PREVIEW_HTML:-}" ]]; then
    cp "$STAR_METRICS_PREVIEW_HTML" "$app/Contents/Resources/ProjectMetricsPreview.html"
fi
swiftc -swift-version 5 -target "$(uname -m)-apple-macos14.0" -O \
    "$source_dir/Roster.swift" "$source_dir/AvatarView.swift" "$source_dir/StarApp.swift" \
    "$source_dir/AcquisitionView.swift" "$source_dir/ProjectMetrics.swift" "$source_dir/MetricsWorkflow.swift" "$source_dir/ProjectDashboard.swift" "$source_dir/ForksView.swift" "$source_dir/main.swift" \
    "$source_dir/GitHistory.swift" "$source_dir/GitAuthorAvatar.swift" "$source_dir/GitHistoryView.swift" \
    -o "$app/Contents/MacOS/StarRoster"
swift "$source_dir/make-icon.swift" "$build_dir/AppIcon.iconset"
iconutil --convert icns "$build_dir/AppIcon.iconset" --output "$app/Contents/Resources/AppIcon.icns"
codesign --force --sign - "$app"
destination="${1:-$source_dir/Star 记录.app}"
if [[ -e "$destination" ]]; then
    bundle_id=$(/usr/libexec/PlistBuddy -c 'Print CFBundleIdentifier' "$destination/Contents/Info.plist")
    [[ "$bundle_id" == "local.anki-pipeline.star-roster" ]] || exit 1
fi
ditto "$app" "$destination"
codesign --verify --strict "$destination"
