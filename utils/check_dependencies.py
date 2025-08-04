import shutil
import sys
import subprocess
import re

def check_system_dependencies():
    """
    Checks if required command-line tools are available and up-to-date.
    Exits with a non-zero status code if any dependency is missing or outdated.
    """
    # Add other command-line tools your project requires here.
    dependencies = [
        'ffmpeg',
        'ffprobe',
        'tsmuxer',
        'mkvextract' # For reliably extracting streams from MKV containers
    ]

    print("Checking for required system dependencies...")
    all_found = True
    version_ok = True

    for dep in dependencies:
        path = shutil.which(dep)
        if path:
            print(f"  [✓] Found '{dep}' at: {path}")
            # Specifically check the version of tsMuxeR, as old versions cause issues.
            if dep == 'tsmuxer':
                try:
                    # Run tsmuxer with no args to get version info, which it prints to stdout/stderr
                    result = subprocess.run([path], capture_output=True, text=True, timeout=5, encoding='utf-8', errors='ignore')
                    output = result.stdout + result.stderr

                    # We need a recent version of the justdan96 fork (from 2023 or later).
                    # We can identify this by the git datestamp (e.g., git-2024-...) or by the
                    # version number (e.g., 2.7.0, where v2.0.0+ is from mid-2023 or newer).
                    is_justdan96_fork = 'github.com/justdan96/tsMuxer' in output
                    is_modern = False

                    if is_justdan96_fork:
                        # First, try to find the git datestamp, which is the most reliable.
                        git_match = re.search(r'git-(\d{4})', output)
                        if git_match:
                            year = int(git_match.group(1))
                            if year >= 2023:
                                is_modern = True
                                print(f"    [i] Version looks modern (git {year}, OK).")
                        
                        # If git datestamp is not found, fall back to parsing the version number.
                        if not is_modern:
                            version_match = re.search(r'version\s+(\d+)\.(\d+)', output, re.IGNORECASE)
                            if version_match:
                                major, minor = map(int, version_match.groups())
                                if major >= 2: # Version 2.0.0+ is from mid-2023 or newer.
                                    is_modern = True
                                    print(f"    [i] Version looks modern (v{major}.{minor}, OK).")

                    if not is_modern:
                         print(f"    [✗] ERROR: Your tsMuxeR version is outdated or unsupported.")
                         print(f"       The script requires a recent version from 'justdan96' (from 2023 or later).")
                         print(f"       Please download the latest release from 'github.com/justdan96/tsMuxer' and")
                         print(f"       ensure it replaces the old version found at: {path}")
                         if output.strip():
                            print(f"       --- Detected Version Output ---")
                            for line in output.strip().split('\n'):
                                print(f"         {line.strip()}")
                            print(f"       -----------------------------")
                         version_ok = False
                except (subprocess.TimeoutExpired, FileNotFoundError):
                    print(f"    [!] WARNING: Could not execute '{dep}' to check its version. Please ensure it's a modern version.")
        else:
            print(f"  [✗] '{dep}' not found in PATH.")
            all_found = False

    print("-" * 40)
    if all_found and version_ok:
        print("✅ All essential dependencies were found and are up-to-date.")
    else:
        if not all_found:
            print("⚠️ Some dependencies are missing. Please ensure they are installed and in your system's PATH.")
        if not version_ok:
            print("⚠️ An outdated version of a dependency was found (tsMuxeR). Please follow the instructions above to update it.")
        print("\n   If you have just installed or updated a dependency, you may need to RESTART your terminal/CMD window.")
        sys.exit(1)

if __name__ == "__main__":
    check_system_dependencies()