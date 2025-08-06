import sys
import shutil
import subprocess

def check_system_dependencies():
    """
    Checks if required command-line tools are available in the system's PATH.
    Exits with a non-zero status code if any dependency is missing.
    """
    print("--- Checking System Dependencies ---")
    required_tools = ['ffmpeg', 'ffprobe', 'tsMuxer', 'mkvextract', 'FRIMEncode64']
    missing_tools = []

    for tool in required_tools:
        path = shutil.which(tool)
        if path:
            print(f"  [✓] Found '{tool}' at: {path}")
        else:
            print(f"  [✗] '{tool}' not found in system PATH.")
            missing_tools.append(tool)

    if missing_tools:
        print("\n--- ERROR: Missing Dependencies ---")
        print("The following required tools were not found in your system's PATH:")
        for tool in missing_tools:
            print(f"  - {tool}")
        print("\nPlease install them and ensure their locations are added to the PATH environment variable.")
        print("You may need to restart your terminal/computer for the changes to take effect.")
        print("\nRecommended downloads:")
        print("  - FFmpeg (includes ffmpeg, ffprobe): https://www.gyan.dev/ffmpeg/builds/")
        print("  - tsMuxeR: https://github.com/justdan96/tsMuxer/releases")
        print("  - MKVToolNix (includes mkvextract): https://mkvtoolnix.download/downloads.html")
        print("  - FRIM (includes FRIMEncode64): https://www.videohelp.com/software/FRIM")
        sys.exit(1)
    else:
        print("-" * 50)
        print("✅ All essential dependencies were found and are ready to use.")

if __name__ == "__main__":
    check_system_dependencies()
