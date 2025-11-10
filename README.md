# Dispatcharr IPTV Checker Plugin

**Description:** Check IPTV stream status, analyze stream quality, and manage channels based on results

## Features

- **Stream Status Checking:** Verify if IPTV streams are alive or dead with smart retry logic
- **Technical Analysis:** Extract resolution, framerate, and video format information
- **Dispatcharr Integration:** Direct API communication with automatic authentication
- **Channel Management:** Automated renaming and moving of channels based on analysis results
- **Group-Based Operations:** Work with existing Dispatcharr channel groups
- **Real-Time Progress Tracking:** Live ETA calculations with persistent progress state
- **Parallel Processing:** Optional multi-threaded checking for faster results
- **Enhanced CSV Exports:** Detailed statistics and plugin settings in export headers
- **Cancellable Operations:** Stop long-running checks while preserving partial results

## Requirements

### System Dependencies
This plugin requires **ffmpeg** and **ffprobe** to be installed in the Dispatcharr container for stream analysis.

**Default Locations:**
- **ffprobe:** `/usr/local/bin/ffprobe` (plugin default)
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

## Settings Reference

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| Dispatcharr URL | string | - | Full URL of your Dispatcharr instance |
| Dispatcharr Username | string | - | Username for API authentication |
| Dispatcharr Password | password | - | Password for API authentication |
| Groups to Check | string | - | Comma-separated group names, empty = all groups |
| Connection Timeout | number | 10 | Seconds to wait for stream connection |
| Dead Connection Retries | number | 3 | Number of retry attempts for failed streams |
| Dead Channel Rename Format | string | "{name} [DEAD]" | Format for renaming dead channels. Use {name} as placeholder |
| Move Dead Channels to Group | string | "Graveyard" | Group to move dead channels to |
| Low Framerate Rename Format | string | "{name} [Slow]" | Format for renaming low FPS channels. Use {name} as placeholder |
| Move Low Framerate Group | string | "Slow" | Group to move low framerate channels to |
| Video Format Suffixes | string | "4k, FHD, HD, SD, Unknown" | Formats to add as suffixes |
| Enable Parallel Checking | boolean | false | Check multiple streams simultaneously for faster processing |
| Number of Parallel Workers | number | 2 | How many streams to check at once (when parallel enabled) |

## Usage Guide

### Step-by-Step Workflow

1. **Configure Authentication**
   - Enter your **Dispatcharr URL** (e.g., http://127.0.0.1:9191)
   - Enter your **Dispatcharr Username** and **Password**
   - Optionally specify **Groups to Check** (leave empty to check all)
   - Configure retry and timeout settings
   - Optionally enable **Parallel Checking** for faster processing
   - Click **Save Settings**

2. **Validate Settings** *(Recommended)*
   - Click **Run** on **✅ Validate Settings**
   - Verifies connection, credentials, and group names
   - Confirms configuration before starting checks

3. **Load Channel Groups**
   - Click **Run** on **📥 Load Group(s)**
   - Review available groups and channel counts
   - Note the estimated checking time (varies by mode)
   - Tip appears if parallel mode would significantly speed up processing

4. **Check Streams**
   - Click **Run** on **▶️ Start Stream Check**
   - Processing runs in the background to prevent browser timeouts
   - Race condition protection prevents duplicate checks
   - Stream checking includes delays between checks for server stability

5. **Monitor Progress**
   - Click **📊 View Check Progress** for real-time status with ETA
   - Shows format: "Checking streams X/Y - Z% complete | ETA: N min"
   - Progress persists across page refreshes and server restarts
   - Use **🛑 Cancel Stream Check** to stop if needed (partial results saved)

6. **View Results**
   - Click **📋 View Last Results** for summary when complete
   - Shows alive/dead counts and format distribution
   - Use **📊 View Results Table** for detailed tabular format

7. **Manage Channels**
   - Use channel management actions based on results
   - All operations include confirmation dialogs
   - GUI automatically refreshes after changes

8. **Export Data**
   - Click **💾 Export Results to CSV** to save analysis data
   - CSV includes comprehensive header comments with:
     - Plugin settings used for the check
     - Cumulative statistics (alive/dead counts, percentages)
     - Format distribution and average framerate
     - Error type breakdown
   - Use **🗑️ Clear CSV Exports** to clean up old export files

## Action Reference

### Setup & Validation
- **✅ Validate Settings:** Verify API connection, credentials, and group names

### Core Stream Checking
- **📥 Load Group(s):** Load channels from specified groups
- **▶️ Start Stream Check:** Begin checking all loaded streams (with duplicate prevention)
- **📊 View Check Progress:** View real-time progress with ETA
- **🛑 Cancel Stream Check:** Stop the current check (preserves partial results)
- **📋 View Last Results:** Summary of completed check

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

## Channel Management Features

### Dead Channel Management
- **Rename Dead Channels:** Rename dead channels using customizable format string (e.g., "[DEAD] {name}")
- **Move Dead Channels:** Automatically relocate dead channels to the specified group

### Low Framerate Management (<30fps)
- **Rename Low FPS Channels:** Rename low FPS channels using customizable format string (e.g., "{name} [Slow]")
- **Move Low FPS Channels:** Automatically relocate slow channels to the specified group

### Video Format Management
- **Add Format Suffixes:** Add [4K], [FHD], [HD], [SD] tags based on resolution

### Smart Features
- **Flexible Renaming:** Use {name} placeholder in format strings for complete control over channel naming
- **Auto Group Creation:** Creates target groups if they don't exist
- **GUI Refresh:** Automatically updates Dispatcharr interface after changes
- **Confirmation Dialogs:** All destructive operations require explicit confirmation

## Output Data

### Stream Analysis Results
- **Name:** Channel name from Dispatcharr
- **Status:** Alive or Dead
- **Resolution:** Video resolution (e.g., 1920x1080)
- **Format:** Detected format (4K/FHD/HD/SD)
- **Framerate:** Frames per second (rounded to 1 decimal)
- **Error Type:** Categorized failure reason for dead streams
- **Error Details:** Specific failure reasons for dead streams

### Quality Detection Rules
- **Low Framerate:** Streams with <30fps
- **Format Detection:**
  - **4K:** 3840x2160+
  - **FHD:** 1920x1080+
  - **HD:** 1280x720+
  - **SD:** Below HD resolution

### CSV Export Enhancements
Each exported CSV includes comprehensive header comments:
- **Metadata:** Generation timestamp and settings used
- **Configuration:** All plugin settings (timeout, retries, rename formats, etc.)
- **Statistics:** Total/alive/dead stream counts with percentages
- **Format Distribution:** Breakdown of video formats among alive streams
- **Performance Metrics:** Average framerate for alive streams
- **Error Analysis:** Distribution of error types among dead streams

## File Locations

- **Results:** `/data/iptv_checker_results.json`
- **Loaded Channels:** `/data/iptv_checker_loaded_channels.json`
- **Progress State:** `/data/iptv_checker_progress.json` *(persists across restarts)*
- **CSV Exports:** `/data/exports/iptv_checker_results_YYYYMMDD_HHMMSS.csv`

## Advanced Features

### Persistent Progress Tracking
- Progress state saved to disk and survives server restarts
- Multiple plugin instances share the same progress state
- View progress from any browser or after page refresh
- Cancel functionality preserves all partial results

### Smart Retry System
- Timeout streams get retried after processing other streams (not immediately)
- Provides server recovery time between retry attempts
- Improves success rates for intermittent connection issues
- Retry queue processes every 4 streams in sequential mode

### Parallel Processing Mode
- Enable for significantly faster checking of large channel lists
- Configurable worker count (default: 2)
- Automatically handles retries for timed-out streams
- Ideal for checking 50+ streams
- Sequential mode still available for maximum reliability

### Race Condition Prevention
- Threading lock prevents duplicate checks from simultaneous button clicks
- Helpful error message if check already running
- Status displayed shows current progress percentage

### Performance Optimizations
- **Sequential Mode:** 3-second delays between checks for server stability
- **Parallel Mode:** Multiple streams checked simultaneously with overhead compensation
- **Accurate Time Estimates:** Based on real-world performance data (~8.5s per stream)
- **Server-Friendly Processing:** Reduces load on IPTV providers

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
- Check plugin folder structure

**Authentication Errors:**
- Use **✅ Validate Settings** to test configuration
- Verify Dispatcharr URL is accessible from the browser
- Ensure username and password are correct
- Check user has appropriate API access permissions
- Restart container: `docker restart dispatcharr`

**"No Groups Found" Error:**
- Check that channel groups exist in Dispatcharr
- Verify group names are spelled correctly (case-sensitive)
- Use **✅ Validate Settings** to verify group names
- Restart container: `docker restart dispatcharr`

**"No stream check is currently running" Message:**
- This should no longer occur with persistent progress tracking
- If it appears, check if `/data/iptv_checker_progress.json` exists
- Restart container: `docker restart dispatcharr`

**Stream Check Failures:**
- Increase timeout setting for slow streams
- Adjust retry count for unstable connections
- Try enabling parallel mode for better timeout handling
- Check network connectivity from the container
- Restart container: `docker restart dispatcharr`

**Progress Stuck or Not Updating:**
- Progress now persists - use **📊 View Check Progress** for current status
- Stream checking continues in the background even if browser shows timeout
- Check container logs for actual processing status
- Use **🛑 Cancel Stream Check** if truly stuck
- Restart container: `docker restart dispatcharr`

### Debugging Commands

**Check Plugin Status:**
```bash
docker exec dispatcharr ls -la /data/plugins/iptv_checker/
```

**View Progress State:**
```bash
docker exec dispatcharr cat /data/iptv_checker_progress.json
```

**Monitor Plugin Activity:**
```bash
docker logs dispatcharr | grep -i iptv
```

**Test ffprobe Installation:**
```bash
docker exec dispatcharr /usr/local/bin/ffprobe -version
```

**Check Processing Status:**
```bash
docker logs dispatcharr | tail -20
```

## Performance Notes

### Time Estimates
**Sequential Mode:**
- Based on ~8.5 seconds per stream average
- Includes 20% buffer for reliability
- Real-time ETA updates during processing based on actual speed

**Parallel Mode:**
- Divides processing time by number of workers
- Includes 10% overhead for coordination
- Significantly faster for large channel lists
- Example: 100 streams with 2 workers ≈ 8 minutes (vs 17 minutes sequential)

### Processing Speed Comparison
- **Sequential:** Safest, most reliable, 3-second delays between checks
- **Parallel:** Faster, configurable workers, ideal for 50+ streams
- **Smart Retries:** Both modes retry timeouts after other streams processed

### Recommendations
- **Small lists (<50 streams):** Sequential mode is fine
- **Large lists (50+ streams):** Enable parallel mode for time savings
- **Unstable sources:** Sequential mode with higher retry count
- **Fast, reliable sources:** Parallel mode with 3-5 workers

## Limitations

- Requires valid Dispatcharr authentication
- Limited to ffprobe-supported stream formats
- Channel management operations are permanent (backup recommended)
- Parallel mode uses more system resources than sequential mode

## Contributing

This plugin integrates deeply with Dispatcharr's API and channel management system. When reporting issues:
1. Include Dispatcharr version information
2. Provide relevant container logs
3. Test with small channel groups first
4. Document specific API error messages
5. Note if **📊 View Check Progress** shows different information than browser display
6. Check `/data/iptv_checker_progress.json` for progress state
