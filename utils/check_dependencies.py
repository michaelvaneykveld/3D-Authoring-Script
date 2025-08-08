import sys
import shutil
import importlib.util

def run_all_checks():
    """
    Checks for all system and Python dependencies.
    Exits with a non-zero status code if any dependency is missing.
    """
    # --- Check for command-line tools ---
    print("--- Checking System Dependencies ---")
    required_tools = ['ffmpeg', 'ffprobe', 'tsMuxer', 'FRIMEncode64']
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
        print("  - FFmpeg (provides ffmpeg, ffprobe): https://www.gyan.dev/ffmpeg/builds/")
        print("  - tsMuxeR: https://github.com/justdan96/tsMuxer/releases")
        print("  - FRIM (provides FRIMEncode64): https://www.videohelp.com/software/FRIM")
        sys.exit(1)
    
    # --- Check for required Python packages ---
    print("\n--- Checking Python Package Dependencies ---")
    required_packages = ['bitstring']
    missing_packages = []

    for package in required_packages:
        spec = importlib.util.find_spec(package)
        if spec is None:
            print(f"  [✗] Package '{package}' not found.")
            missing_packages.append(package)
        else:
            print(f"  [✓] Found package: '{package}'")

    if missing_packages:
        print("\n--- ERROR: Missing Python Packages ---")
        print("Please install the missing packages using pip:")
        for package in missing_packages:
            print(f"    pip install {package}")
        sys.exit(1)
