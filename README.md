# Dispatcharr IPTV Checker Plugin

## Check IPTV stream status, analyze stream quality, and manage channels based on results

[![Dispatcharr plugin](https://img.shields.io/badge/Dispatcharr-plugin-8A2BE2)](https://github.com/Dispatcharr/Dispatcharr)
[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/PiratesIRC/Dispatcharr-IPTV-Checker-Plugin)

[![GitHub Release](https://img.shields.io/github/v/release/PiratesIRC/Dispatcharr-IPTV-Checker-Plugin?include_prereleases&logo=github)](https://github.com/PiratesIRC/Dispatcharr-IPTV-Checker-Plugin/releases)
[![Downloads](https://img.shields.io/github/downloads/PiratesIRC/Dispatcharr-IPTV-Checker-Plugin/total?color=success&label=Downloads&logo=github)](https://github.com/PiratesIRC/Dispatcharr-IPTV-Checker-Plugin/releases)

![Top Language](https://img.shields.io/github/languages/top/PiratesIRC/Dispatcharr-IPTV-Checker-Plugin)
![Repo Size](https://img.shields.io/github/repo-size/PiratesIRC/Dispatcharr-IPTV-Checker-Plugin)
![Last Commit](https://img.shields.io/github/last-commit/PiratesIRC/Dispatcharr-IPTV-Checker-Plugin)
![License](https://img.shields.io/github/license/PiratesIRC/Dispatcharr-IPTV-Checker-Plugin)


## ⚠️ Important: Backup Your Database
Before installing or using this plugin, it is **highly recommended** that you create a backup of your Dispatcharr database. This plugin makes significant changes to your channel and stream assignments.

**[Click here for instructions on how to back up your database.](https://dispatcharr.github.io/Dispatcharr-Docs/troubleshooting/?h=backup#how-can-i-make-a-backup-of-the-database)**

## Features

- **Stream Status Checking:** Verify if IPTV streams are alive or dead with smart retry logic
- **Automated Scheduler:** Schedule stream checks using cron expressions with timezone support
- **Metadata Synchronization:** Sync technical stream data (codecs, bitrate, sample rate) back to Dispatcharr
- **Background Processing:** Stream checks run in background threads to prevent browser timeouts
- **Alternative Streams:** Option to check backup/alternative streams associated with channels
- **Technical Analysis:** Extract resolution, framerate, and video format information
- **Configurable Analysis:** Custom FFprobe path and analysis duration settings
- **Dispatcharr Integration:** Direct API communication with automatic authentication
- **Channel Management:** Automated renaming and moving of channels based on analysis results
- **Group-Based Operations:** Work with existing Dispatcharr channel groups
- **Smart Loading:** Asynchronous loading for large channel lists to prevent interface timeouts
- **Real-Time Progress Tracking:** Live ETA calculations based on actual processing speed
- **Smart Retry System:** Timeout streams queued and retried after other streams for better success rates
- **Enhanced Error Categorization:** Detailed error types (Timeout, 404, 403, Connection Refused, etc.)
- **Enhanced CSV Exports:** Includes error types and rounded framerate values

## Requirements

### System Dependencies
This plugin requires **ffmpeg** and **ffprobe** to be installed in the Dispatcharr container for stream analysis. The scheduler feature requires **pytz** (usually included).

**Default Locations:**
- **ffprobe:** `/usr/local/bin/ffprobe` (plugin default, configurable)
- **ffmpeg:** `/usr/local/bin/ffmpeg`

**Verify Installation:**
```bash
docker exec dispatcharr which ffprobe
docker exec dispatcharr which ffmpeg
```

### Dispatcharr Setup
- Active Dispatcharr installation with configured channels and groups
- Valid Dispatcharr username and password for API access
- Channel groups containing IPTV streams to analyze

## Installation

1. Log in to Dispatcharr's web UI
2. Navigate to **Plugins**
3. Click **Import Plugin** and upload the plugin zip file
4. Enable the plugin after installation

### Updating the Plugin

To update the plugin:

1. **Remove Old Plugin**
   * Navigate to **Plugins** in Dispatcharr
   * Click the trash icon next to the old plugin
   * Confirm deletion

2. **Restart Dispatcharr**
   * Log out of Dispatcharr
   * Restart the Docker container:
     ```bash
     docker restart dispatcharr
     ```

3. **Install Updated Plugin**
   * Log back into Dispatcharr
   * Navigate to **Plugins**
   * Click **Import Plugin** and upload the new plugin zip file
   * Enable the plugin after installation

4. **Verify Installation**
   * Check that the plugin appears in the plugin list
   * Reconfigure your settings if needed

## Settings Reference

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| Dispatcharr URL | string | - | Full URL of your Dispatcharr instance |
| Dispatcharr Username | string | - | Username for API authentication |
| Dispatcharr Password | password | - | Password for API authentication |
| Groups to Check | string | - | Comma-separated group names, empty = all groups |
| Check Alternative Streams | boolean | true | Check all alternative/backup streams for each channel |
| Connection Timeout | number | 10 | Seconds to wait for stream connection |
| Dead Connection Retries | number | 3 | Number of retry attempts for failed streams |
| Dead Channel Rename Format | string | "{name} [DEAD]" | Format for renaming dead channels. Use {name} as placeholder |
| Move Dead Channels to Group | string | "Graveyard" | Group to move dead channels to |
| Low Framerate Rename Format | string | "{name} [Slow]" | Format for renaming low FPS channels. Use {name} as placeholder |
| Move Low Framerate Group | string | "Slow" | Group to move low framerate channels to |
| Video Format Suffixes | string | "4k, FHD, HD, SD, Unknown" | Formats to add as suffixes |
| Enable Parallel Checking | boolean | false | Check multiple streams simultaneously for faster processing |
| Number of Parallel Workers | number | 2 | How many streams to check at once (when parallel enabled) |
| FFprobe Path | string | /usr/local/bin/ffprobe | Full path to the ffprobe executable |
| Enable Scheduled Checks | boolean | false | Enable automatic scheduled stream checks |
| Scheduled Check Times | string | - | Cron expressions (e.g., "0 4 * * *" for daily at 4 AM) |
| Scheduler Timezone | select | America/Chicago | Timezone for the scheduler |
| Export CSV for Schedule | boolean | false | Automatically export results to CSV after scheduled checks |

## Usage Guide

### Step-by-Step Workflow

1. **Configure Authentication & Preferences**
   - Enter your **Dispatcharr URL** (e.g., http://127.0.0.1:9191)
   - Enter your **Dispatcharr Username** and **Password**
   - Configure checking preferences (Groups, Alternative Streams, Retries)
   - Optionally enable **Parallel Checking** for faster processing
   - Click **Save Settings**

2. **Validate Settings** *(Recommended)*
   - Click **Run** on **✅ Validate Settings**
   - Verifies connection, credentials, group names, and tool paths

3. **Configure Schedule** *(Optional)*
   - Set **Scheduled Check Times** using cron format
   - Select your **Scheduler Timezone**
   - Enable **Export CSV for Scheduled Checks** if desired
   - Click **Run** on **📅 Update Schedule** to activate

4. **Load Channel Groups**
   - Click **Run** on **📥 Load Group(s)**
   - Review available groups and channel counts
   - Large lists (>100 channels) will load in the background to prevent timeouts

5. **Check Streams**
   - Click **Run** on **▶️ Start Stream Check**
   - Processing runs in the background
   - Returns immediately with estimated completion time
   - Technical metadata (codecs, bitrate, etc.) is automatically synced to the database during checks

6. **Monitor Progress**
   - Click **📋 View Last Results** (or **📊 View Check Progress**) for real-time status with ETA
   - Shows format: "Checking streams X/Y - Z% complete | ETA: N min"
   - Progress updates continue even if browser times out

7. **View Results**
   - Click **📋 View Last Results** for summary when complete
   - Shows alive/dead counts and format distribution
   - Use **📊 View Results Table** for detailed tabular format

8. **Manage Channels**
   - Use channel management actions based on results
   - All operations include confirmation dialogs
   - GUI automatically refreshes after changes

9. **Export Data**
   - Click **💾 Export Results to CSV** to save analysis data
   - CSV includes comprehensive header comments with settings and stats

## Action Reference

### Setup & Validation
- **✅ Validate Settings:** Verify API connection, credentials, and group names
- **📅 Update Schedule:** Apply the current schedule settings and restart the scheduler

### Core Stream Checking
- **📥 Load Group(s):** Load channels from specified groups (async for large lists)
- **▶️ Start Stream Check:** Begin checking all loaded streams in background thread
- **📊 View Check Progress:** View the current progress and ETA of the running check
- **📋 View Last Results:** View summary of the last completed stream check

### Channel Management
- **✏️ Rename Dead Channels:** Apply rename format to dead streams
- **⚰️ Move Dead Channels to Group:** Relocate dead channels
- **🐌 Rename Low Framerate Channels:** Apply rename format to slow streams (<30fps)
- **📁 Move Low Framerate Channels to Group:** Relocate slow channels
- **🎬 Add Video Format Suffix to Channels:** Apply format tags ([4K], [FHD], [HD], [SD])

### Data Export
- **📊 View Results Table:** Detailed tabular format for copy/paste
- **💾 Export Results to CSV:** Save analysis data with comprehensive statistics
- **🗑️ Clear CSV Exports:** Delete all CSV files in /data/exports/

## Advanced Features

### Automated Scheduling
- **Cron Support:** Configure checks to run automatically using standard cron syntax (e.g., `0 4 * * *`)
- **Timezone Aware:** Schedules run according to your local timezone configuration
- **Auto-Export:** Can automatically generate CSV reports after every scheduled run
- **Conflict Prevention:** Scheduler intelligently queues jobs if a manual check is already running

### Metadata Synchronization
- **Database Sync:** The plugin automatically updates the Dispatcharr database with technical stream details derived from FFprobe analysis.
- **Synced Fields:**
  - Video/Audio Codecs
  - Resolution (Width/Height)
  - Bitrates (Video/Audio)
  - Sample Rates & Audio Channels
  - Stream Types

### Smart Retry System
- Timeout streams queued and retried after processing other streams (not immediately)
- Provides server recovery time between retry attempts
- Retry queue processes every 4 streams to balance throughput and recovery time
- Multiple retry attempts per stream based on configured retry count

### Background Processing & Loading
- **Async Loading:** Large channel lists load in a background thread to prevent UI locking or timeouts.
- **Stream Checks:** Run entirely in background threads; browser connection loss does not stop the check.
- **Real-Time ETA:** Calculated dynamically based on actual processing speed.

## Troubleshooting

### First Step: Restart Container
**For any plugin issues, always try refreshing your browser (F5) and then restarting the Dispatcharr container:**
```bash
docker restart dispatcharr
```

### Common Issues

**"Plugin not found" Errors:**
- Refresh browser page (F5)
- Restart Dispatcharr container

**Scheduler Not Running:**
- Verify `pytz` is installed in the container
- Check cron syntax in settings (5 fields required: minute hour day month weekday)
- Ensure "Enable Scheduled Checks" is set to True
- Check logs: `docker logs dispatcharr | grep -i scheduler`

**Authentication Errors:**
- Use **✅ Validate Settings** to test configuration
- Verify Dispatcharr URL is accessible from the browser
- Restart container: `docker restart dispatcharr`

**Stream Check Failures:**
- Increase timeout setting for slow streams
- Adjust retry count for unstable connections
- Try enabling parallel mode for better timeout handling
- Restart container: `docker restart dispatcharr`

**Progress Stuck or Not Updating:**
- Stream checking runs in background thread and continues even if browser times out
- Use **📊 View Check Progress** to check current status
- Check container logs for actual processing status

## File Locations

- **Results:** `/data/iptv_checker_results.json`
- **Loaded Channels:** `/data/iptv_checker_loaded_channels.json`
- **Progress State:** `/data/iptv_checker_progress.json`
- **Settings:** `/data/iptv_checker_settings.json`
- **CSV Exports:** `/data/exports/iptv_checker_results_YYYYMMDD_HHMMSS.csv`

## Contributing

This plugin integrates deeply with Dispatcharr's API and channel management system. When reporting issues:
1. Include Dispatcharr version information
2. Provide relevant container logs
3. Test with small channel groups first
4. Document specific API error messages and error types
5. Note current progress from **📋 View Last Results** including ETA information
