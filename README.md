# Pawchy Downloader

A Windows downloader for Pawchive creator and post URLs. It uses Pawchive's public API and downloads covers and attachments concurrently.

## Windows app

Download `Pawchy Downloader.exe` and run it. The app opens a local page in your browser; no data is sent anywhere except Pawchive.

Paste one or more Pawchive URLs, choose an output folder, and press **Start download**. The dashboard shows completed, failed, skipped, and queued files while the job is running.

**Stop download** cancels the current job without deleting partial files. Running the same download again resumes those files.

Files are saved in one folder per creator. Post IDs are added to filenames to prevent collisions.

## Supported URLs

```text
https://pawchive.pw/{service}/user/{creator_id}
https://pawchive.pw/{service}/user/{creator_id}/post/{post_id}
```

## Install from source

Python 3.10 or newer is required.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e .
```

## Command line

Download a post:

```powershell
pawchy "https://pawchive.pw/fanbox/user/22291115/post/12511018"
```

Download a creator profile:

```powershell
pawchy "https://pawchive.pw/fanbox/user/22291115" -o "D:\Pawchive"
```

Read URLs from a file:

```powershell
pawchy -i urls.txt --concurrency 8
```

Useful options:

- `--max-posts 100` limits the number of posts per creator.
- `--after 2025-01-01` and `--before 2025-12-31` filter by publish date.
- `--no-cover` or `--no-attachments` selects which files to download.
- `--overwrite` downloads existing files again.
- `--metadata` saves the API response for each post.
- `--dry-run` prints the download plan without writing files.

## Build the EXE

```powershell
python -m pip install -e ".[build]"
.\build_exe.ps1
```

## Tests

```powershell
python -m unittest discover -s tests -v
```

Only download content you are allowed to access. Keep concurrency at a reasonable value to avoid unnecessary load on Pawchive.
