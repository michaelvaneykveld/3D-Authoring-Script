# 3D Blu-ray Authoring Script

An automated pipeline for converting 3D Side-by-Side (SBS) video files into fully compliant Blu-ray 3D (BDMV or ISO) structures.

## Overview

This project addresses the complex and often manual process of creating a proper 3D Blu-ray from common 3D video formats (like those found online). It provides a guided, step-by-step workflow that automates video analysis, 3D encoding, audio/subtitle track selection, and final muxing into a playable disc format.

The script is designed to be robust, with extensive logging and validation at every critical step to ensure a high-quality, compliant final product and to simplify debugging when issues arise.

## Key Features

- **Automated SBS to MVC Conversion**: Correctly converts Full or Half Side-by-Side source material into the official Blu-ray 3D AVC+MVC format.
- **User-Friendly GUI**: Uses simple graphical dialogs for file and folder selection, making it accessible to users who are not command-line experts.
- **Flexible Output**: Allows the user to choose between creating a standard BDMV folder structure (for playback from a hard drive) or a single, portable `.iso` file.
- **Intelligent Track Selection**: Analyzes the source file for all audio and subtitle streams and allows the user to interactively select which ones to include.
- **Automatic Chapter Extraction**: Detects and preserves chapter markers from the source file, embedding them into the final Blu-ray structure.
- **Resource-Efficient Encoding**: Processes the video in small, manageable chunks to keep temporary disk usage low, making it possible to work with large files on systems with limited space.
- **Extensive Validation & Logging**: Performs numerous checks throughout the process and generates detailed, timestamped log files for all external tools, making troubleshooting transparent and effective.

---

## The Workflow in Detail

The script executes a multi-phase pipeline, with each step building upon the last.

### Phase 1: Analysis & Preparation

1.  **Dependency Check (`check_dependencies.py`)**: Before starting, the script verifies that all required external tools (`ffmpeg`, `ffprobe`, `tsMuxeR`, `mkvextract`, and `FRIMEncode`) are installed and accessible in the system's PATH.

2.  **Source File Analysis (`video_analyzer.py`)**:
    - The user selects a source video file via a file dialog.
    - `ffprobe` is used to extract critical metadata: resolution, framerate (both as a float and a fraction), duration, total frame count, and a list of all available audio and subtitle streams.
    - `ffmpeg`'s `cropdetect` filter is run on a sample of the video to automatically detect and measure any black bars (letterboxing/pillarboxing). This ensures that only the active video area is encoded.
    - The script determines if the source is **Full SBS** or **Half SBS** based on its storage aspect ratio.
    - Chapter markers are extracted from the source container if they exist.

3.  **Track Selection (`track_selector.py`)**:
    - The user is presented with a list of all found audio and subtitle tracks.
    - Through a simple command-line prompt, the user can specify which tracks to keep (e.g., `1,3` for the first and third audio tracks, or `all`/`none`).

### Phase 2: 3D Encoding (`encoder.py`)

This is the most critical phase, where the 2D SBS source is converted into a true stereoscopic 3D stream.

1.  **Chunk-Based Processing**: To manage memory and disk space, the video is processed in 300-frame chunks.

2.  **Per-Chunk Workflow**: For each chunk, the following occurs:
    - **View Extraction**: `ffmpeg` is used to crop the left and right eye views from the SBS source, creating two separate, temporary raw YUV video files.
    - **Integrity Check**: A SHA256 hash of both YUV files is calculated to ensure they are not identical. This prevents `FRIMEncode` from failing if the source video is not actually 3D.
    - **FRIMEncode Execution**: `FRIMEncode` is called with the left and right YUV files as input. It is configured to:
        - Output a **single, combined `.264` stream** containing both the AVC base view (left eye) and the MVC dependent view (right eye).
        - Generate VUI/SEI timing information to ensure stream compliance.
        - Disable B-pyramids, which are incompatible with the Blu-ray 3D standard.
    - **FRIMEncode Validation**: The script captures all console output from `FRIMEncode` and immediately checks for:
        - The presence of the string `"Encoder MVC"`, confirming it has entered 3D mode.
        - Any lines containing `"WARNING:"`, `"dropped frame"`, or `"duplicate frame"`.
        - A non-zero exit code.
        If any of these checks fail, the script stops immediately with a detailed error.

3.  **Stream Concatenation**: After all chunks are successfully encoded, they are concatenated into a single final `video_3d.264` file.

4.  **Final NAL Unit Check**: The final `video_3d.264` file is scanned for the presence of MVC-specific NAL unit byte sequences (`0x0F` or `0x14`), providing a definitive confirmation that the output is a valid stereoscopic stream.

### Phase 3: Muxing (`muxer.py`)

This phase combines the encoded video with the selected audio and subtitles into the final Blu-ray structure.

1.  **Output Selection**: The user chooses between a BDMV folder or an ISO file.
2.  **Track Extraction**: The selected audio and subtitle streams are extracted from the original source file into clean, elementary streams using `ffmpeg`. This "cleans" the tracks of any container-specific timing issues.
3.  **tsMuxeR Configuration**: A `.meta` file is dynamically generated. This text file contains instructions for `tsMuxeR`, telling it:
    - To use the `video_3d.264` file and to look for the `MVC` data within it.
    - The paths to all the extracted audio and subtitle streams, along with their language codes.
    - The precise fractional framerate (e.g., `24000/1001`) to avoid rounding errors.
    - The chapter markers.
    - The desired output mode (`--blu-ray` or `--blu-ray-iso`).
4.  **tsMuxeR Execution**: `tsMuxeR` is run with the `.meta` file, which muxes all the elements together into the final structure.
5.  **Muxing Validation**: The script parses the `tsMuxeR` log to confirm it successfully detected `"Views: 2"`, ensuring the 3D structure was correctly created.

### Phase 4: Final Validation (`bdmv_validator.py`)

If a BDMV folder was created, a final battery of tests is run to guarantee compliance.

1.  **File Structure Check**: Verifies that all required directories (`CLIPINF`, `PLAYLIST`, `STREAM`) and files (`index.bdmv`, `MovieObject.bdmv`, `00000.clpi`, etc.) exist.
2.  **Stream Property Check**: Uses `ffprobe` on the final `00000.m2ts` file to verify that the video stream's profile, codec, and framerate match the expected values.
3.  **Timing Jump Analysis**: Scans the video stream's timestamps (`pkt_dts_time`) to detect any significant jumps or inconsistencies that could cause stuttering playback.
4.  **Frame Count Verification**: Counts the total number of frames in the final stream and compares it to the expected count from the initial analysis.

## Prerequisites

The following command-line tools and Python packages must be installed:

- **FFmpeg**: For decoding, cropping, and track extraction. (Download)
- **tsMuxeR**: For muxing elementary streams into a Blu-ray structure. (Download)
- **FRIM**: Provides `FRIMEncode` for AVC+MVC encoding. (Download)
- **bitstring**: A Python package for parsing binary data.
  ```bash
  pip install bitstring
  ```

## How to Use

1.  Ensure all prerequisites are installed and in your PATH.
2.  Run the script from your terminal:
    ```bash
    python 3D.py
    ```
3.  Follow the prompts and select your files and options through the graphical dialogs.

## Logging & Debugging

For troubleshooting, the script generates detailed log files in the temporary working directory you select:

- `encoder_process.log`: Contains timestamped commands and full console output for `ffmpeg` (YUV extraction) and `FRIMEncode`.
- `ffmpeg_muxer.log`: Contains timestamped commands and full console output for `ffmpeg` (audio/subtitle extraction).
- `tsmuxer_output.log`: Contains the full console output from the final `tsMuxeR` process.

## Known Limitations

- **FRIMEncode on non-Intel Systems**: `FRIMEncode` is part of the Intel Media SDK. While it has a software fallback, its ability to create MVC streams on non-Intel (e.g., AMD) CPUs is not guaranteed and has been observed to fail. The script is most reliable when run on a system with an Intel CPU.