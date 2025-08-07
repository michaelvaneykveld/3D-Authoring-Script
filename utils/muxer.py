import subprocess
import os
import shutil
import sys
import re
import time

TSMUXER_CODEC_MAP = {
    # Audio
    # For justdan96's tsMuxeR, A_AC3 is used for AC3, E-AC3 (DD+), and TrueHD.
    'ac3': 'A_AC3', 'eac3': 'A_AC3', 'truehd': 'A_AC3',
    # All common DTS variants map to A_DTS.
    'dts': 'A_DTS', 'dca': 'A_DTS', 'dts-hd_ma': 'A_DTS', 'dts-hd_hra': 'A_DTS',
    'pcm_bluray': 'A_LPCM',

    # Subtitles
    'subrip': 'S_TEXT/UTF8',
    'hdmv_pgs_subtitle': 'S_HDMV/PGS',
}

def create_bluray_structure(properties, source_file, work_dir, output_path):
    """
    Uses tsMuxeR to combine the encoded video streams with audio/subtitles
    into a final Blu-ray 3D structure (ISO file or BDMV folder).

    Args:
        properties (dict): The dictionary of video properties from the analyzer.
        source_file (str): The path to the original source video file (for audio/subs).
        work_dir (str): The directory containing the left/right eye .264 streams.
        output_path (str): The desired path for the final output. If it ends with .iso, an ISO is created. Otherwise, a BDMV folder is created.
    """
    print("\n--- Starting Step 2: Muxing to Blu-ray 3D ---")

    # --- Normalize work_dir to use forward slashes to prevent mixed separators ---
    work_dir = work_dir.replace('\\', '/')

    # --- Define all paths ---
    left_eye_path = f"{work_dir}/left_eye.264"
    right_eye_path = f"{work_dir}/right_eye.264"
    clean_source_path = f"{work_dir}/clean_remux_for_audio.mkv"
    final_meta_path = f"{work_dir}/muxer_final.meta"
    tsmuxer_log_path = f"{work_dir}/tsmuxer_output.log"

    # This list will hold paths to all temporary files and folders for final cleanup
    files_to_cleanup = [final_meta_path, tsmuxer_log_path, clean_source_path, left_eye_path, right_eye_path]

    if not os.path.exists(left_eye_path):
        print(f"ERROR: Base view stream (left_eye.264) not found in {work_dir}", file=sys.stderr)
        sys.exit(1)
    if not os.path.exists(right_eye_path):
        print(f"ERROR: Dependent view stream (right_eye.264) not found in {work_dir}", file=sys.stderr)
        print("This likely indicates a failure during the encoding step.", file=sys.stderr)
        sys.exit(1)

    try:
        success = False
        # --- Step 2a: Create a clean, remuxed source for audio/subtitles ---
        print("\n--- Step 2a: Creating a clean source for audio/subtitles ---")
        all_selected_streams = properties.get('audio_streams', []) + properties.get('subtitle_streams', [])
        
        if not all_selected_streams:
            print("  [i] No audio or subtitle tracks selected. Skipping remux and extract steps.")
            clean_source_path = None # Signal that there's no clean source
        else:
            remux_cmd = ['ffmpeg', '-y', '-hide_banner', '-loglevel', 'error', '-i', source_file]
            for stream in all_selected_streams:
                remux_cmd.extend(['-map', f'0:{stream["index"]}'])
            remux_cmd.extend(['-c', 'copy', clean_source_path])
            
            print("  [i] Remuxing selected tracks with ffmpeg to fix any timing issues...")
            try:
                subprocess.run(remux_cmd, check=True)
                print("  [✓] Clean source created successfully.")
            except (subprocess.CalledProcessError, FileNotFoundError) as e:
                print(f"ERROR: Failed to create the clean remuxed source file: {e}", file=sys.stderr)
                sys.exit(1)

        # --- Step 2b: Extract clean elementary streams from the remuxed file ---
        print("\n--- Step 2b: Extracting clean elementary streams for tsMuxeR ---")
        audio_track_lines_for_meta = []
        subtitle_track_lines_for_meta = []
        meta_input_files = [] # Will hold all audio/sub file paths for pre-flight check

        if clean_source_path and os.path.exists(clean_source_path):
            extracted_streams_to_cleanup = []
            audio_streams = properties.get('audio_streams', [])
            for i, stream in enumerate(audio_streams):
                ts_codec = TSMUXER_CODEC_MAP.get(stream['codec'])
                if not ts_codec: continue
                temp_audio_path = f'{work_dir}/clean_audio_{i}.{stream["codec"]}'
                ffmpeg_cmd = ['ffmpeg', '-y', '-hide_banner', '-loglevel', 'error', '-i', clean_source_path, '-map', f'0:a:{i}', '-c', 'copy', temp_audio_path]
                subprocess.run(ffmpeg_cmd, check=True)
                meta_input_files.append(temp_audio_path)
                extracted_streams_to_cleanup.append(temp_audio_path)
                audio_track_lines_for_meta.append(f'{ts_codec}, "{temp_audio_path}", lang={stream["lang"]}')

            subtitle_streams = properties.get('subtitle_streams', [])
            for i, stream in enumerate(subtitle_streams):
                stream_codec, fps = stream['codec'], properties.get('fps_string', '23.976')
                ts_codec = TSMUXER_CODEC_MAP.get(stream_codec)
                if not ts_codec: continue
                file_extension = 'srt' if stream_codec == 'subrip' else 'sup'
                temp_sub_path = f'{work_dir}/clean_sub_{i}.{file_extension}'
                subtitle_index_in_remux = len(audio_streams) + i
                ffmpeg_cmd = ['ffmpeg', '-y', '-hide_banner', '-loglevel', 'error', '-i', clean_source_path, '-map', f'0:{subtitle_index_in_remux}', '-c', 'copy', temp_sub_path]
                subprocess.run(ffmpeg_cmd, check=True)
                meta_input_files.append(temp_sub_path)
                extracted_streams_to_cleanup.append(temp_sub_path)
                track_line = f'{ts_codec}, "{temp_sub_path}", lang={stream["lang"]}'
                if stream_codec == 'subrip':
                    track_line += f', video-width=1920, video-height=1080, fps={fps}'
                subtitle_track_lines_for_meta.append(track_line)
            print("  [✓] All selected audio/subtitle streams extracted successfully.")
            files_to_cleanup.extend(extracted_streams_to_cleanup)

        print("\n--- Step 2c: Locating pre-encoded .264 streams ---")
        print("  [✓] Found synchronized .264 streams.")

        # --- Step 2d: Final Mux - Combine all elementary streams ---
        print("\n--- Step 2d: Muxing all streams into the final Blu-ray structure ---")
        is_iso_output = output_path.lower().endswith('.iso')
        base_name = os.path.splitext(os.path.basename(output_path))[0]
        disk_label = ''.join(c for c in base_name if c.isalnum() or c in ' _-').strip() or "BLURAY_3D_DISC"

        # Use decimal representation to ensure consistency with the encoder.
        fps_for_muxer = f"{properties.get('fps_float', 23.976):.3f}"

        # Build MUXOPT line. Critically, we must explicitly tell tsMuxeR whether
        # to create a BDMV folder (--blu-ray) or an ISO file (--blu-ray-iso).
        output_mode = '--blu-ray-iso' if is_iso_output else '--blu-ray'

        final_mux_options = [
            output_mode, '--blu-ray-3d', '--vbr', '--insertSEI', '--contSPS',
            f'--label={disk_label}', f'--fps={fps_for_muxer}'
        ]
        chapters = properties.get('chapters', [])
        if chapters:
            final_mux_options.append(f'--custom-chapters={";".join(chapters)}')

        final_meta_content = [
            f'MUXOPT {" ".join(final_mux_options)}',
            f'V_MPEG4/ISO/AVC, "{left_eye_path}", ssif',
            f'V_MPEG4/ISO/MVC, "{right_eye_path}", track=4113',
        ]
        
        final_meta_content.extend(audio_track_lines_for_meta)
        final_meta_content.extend(subtitle_track_lines_for_meta)

        # --- Pre-flight check for all input files before calling tsMuxeR ---
        print("\n  [i] Verifying all source files for the muxer exist and are valid...")
        all_files_ok = True
        files_to_check_in_meta = [left_eye_path, right_eye_path] + meta_input_files
        for f_path in files_to_check_in_meta:
            if not os.path.exists(f_path):
                print(f"  [✗] FATAL: Input file for meta does not exist: {os.path.basename(f_path)}", file=sys.stderr)
                all_files_ok = False
            elif os.path.getsize(f_path) == 0:
                print(f"  [✗] FATAL: Input file for meta is empty (0 bytes): {os.path.basename(f_path)}", file=sys.stderr)
                all_files_ok = False
        if not all_files_ok:
            raise IOError("Aborting mux due to missing or empty input files. This indicates a failure in a previous step (encoding or track extraction).")
        print("  [✓] All source files are present and valid.")
        print("\n--- Generated .meta file content ---")
        print('\n'.join(final_meta_content))
        print("-" * 34)

        with open(final_meta_path, 'w', encoding='utf-8') as f:
            # Ensure the file ends with a newline for tsMuxeR compatibility.
            f.write('\n'.join(final_meta_content) + '\n')
        
        # --- Proactively create the entire BDMV directory structure ---
        # This prevents partial creation issues and also acts as a write permission check.
        
        if is_iso_output:
            # For ISO files, we only need to ensure the parent directory exists.
            parent_dir = os.path.dirname(output_path)
            if parent_dir: # Check if it's not a root path like 'C:\'
                os.makedirs(parent_dir, exist_ok=True)
            print(f"  [✓] Ensured output directory exists for ISO file: {os.path.normpath(parent_dir)}")
        else:
            # For BDMV, create the full structure.
            print("  [i] Proactively creating required BDMV directory structure...")
            required_subdirs = [
                os.path.join(output_path, "BDMV", "STREAM"),
                os.path.join(output_path, "BDMV", "PLAYLIST"),
                os.path.join(output_path, "BDMV", "CLIPINF"),
                os.path.join(output_path, "BDMV", "BACKUP", "PLAYLIST"),
                os.path.join(output_path, "BDMV", "BACKUP", "CLIPINF"),
                os.path.join(output_path, "CERTIFICATE")
            ]
            for subdir in required_subdirs:
                os.makedirs(subdir, exist_ok=True)
            print(f"  [✓] Ensured output directory structure exists at: {os.path.normpath(output_path)}")

        print(f"  [i] Running tsMuxeR. Output will be logged to: {os.path.basename(tsmuxer_log_path)}")
        # Normalize paths for better cross-platform compatibility and to avoid mixed slashes.
        tsmuxer_cmd_final = ['tsmuxer', os.path.normpath(final_meta_path), os.path.normpath(output_path)]
        with open(tsmuxer_log_path, "w", encoding='utf-8') as log:
            subprocess.run(tsmuxer_cmd_final, stdout=log, stderr=subprocess.STDOUT, check=True)

        # --- Post-Mux Validation ---
        print("  [i] Verifying that tsMuxeR created essential output files...")
        if not is_iso_output:
            mpls_path = os.path.join(output_path, "BDMV", "PLAYLIST", "00000.mpls")
            clpi_path = os.path.join(output_path, "BDMV", "CLIPINF", "00000.clpi")

            if not os.path.exists(mpls_path) or os.path.getsize(mpls_path) < 100:
                raise IOError("tsMuxeR failed to generate a valid .mpls file. Check tsmuxer_output.log for details.")
            if not os.path.exists(clpi_path) or os.path.getsize(clpi_path) < 100:
                raise IOError("tsMuxeR failed to generate a valid .clpi file. Check tsmuxer_output.log for details.")
            print("  [✓] Basic validation passed: Key BDMV files were created by tsMuxeR.")
        
        output_type = "ISO file" if output_path.lower().endswith('.iso') else "BDMV folder structure"
        print(f"\n--- Blu-ray 3D {output_type} created successfully! ---")
        print(f"Output location: {os.path.normpath(output_path)}")
        success = True

    except (subprocess.CalledProcessError, FileNotFoundError, IOError) as e:
        print(f"\n--- MUXING FAILED ---", file=sys.stderr)
        print(f"An error occurred: {e}", file=sys.stderr)
        if os.path.exists(tsmuxer_log_path):
            print(f"Please check the log file for details: {tsmuxer_log_path}", file=sys.stderr)
        sys.exit(1)
    finally:
        # --- Final Cleanup ---
        if success:
            print("\n--- Cleaning up temporary muxing files ---")
            for f in files_to_cleanup:
                if os.path.exists(f):
                    try:
                        os.remove(f)
                    except OSError as e:
                        print(f"  [!] Warning: Could not remove temporary file {os.path.basename(f)}: {e}", file=sys.stderr)
            print("  [✓] Cleanup complete.")
