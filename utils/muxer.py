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

    # --- Define all paths ---
    left_eye_path = os.path.join(work_dir, 'left_eye.264')
    # Find all the dependent view chunk files, sorted numerically
    dep_chunk_files = sorted(
        [os.path.join(work_dir, f) for f in os.listdir(work_dir) if f.startswith('temp_chunk_') and f.endswith('_dep.264')],
        key=lambda x: int(re.search(r'temp_chunk_(\d+)_dep\.264', x).group(1))
    )
    clean_source_path = os.path.join(work_dir, 'clean_remux_for_audio.mkv')
    final_meta_path = os.path.join(work_dir, 'muxer_final.meta')
    tsmuxer_log_path = os.path.join(work_dir, 'tsmuxer_output.log')

    # This list will hold paths to all temporary files and folders for final cleanup
    files_to_cleanup = [final_meta_path, tsmuxer_log_path, clean_source_path, left_eye_path] + dep_chunk_files

    if not os.path.exists(left_eye_path):
        print(f"ERROR: Base view stream (left_eye.264) not found in {work_dir}", file=sys.stderr)
        sys.exit(1)
    if not dep_chunk_files:
        print(f"ERROR: Dependent view chunks (*_dep.264) not found in {work_dir}", file=sys.stderr)
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

        if clean_source_path and os.path.exists(clean_source_path):
            extracted_streams_to_cleanup = []
            audio_streams = properties.get('audio_streams', [])
            for i, stream in enumerate(audio_streams):
                ts_codec = TSMUXER_CODEC_MAP.get(stream['codec'])
                if not ts_codec: continue
                temp_audio_path = os.path.join(work_dir, f'clean_audio_{i}.{stream["codec"]}')
                ffmpeg_cmd = ['ffmpeg', '-y', '-hide_banner', '-loglevel', 'error', '-i', clean_source_path, '-map', f'0:a:{i}', '-c', 'copy', temp_audio_path]
                subprocess.run(ffmpeg_cmd, check=True)
                extracted_streams_to_cleanup.append(temp_audio_path)
                audio_track_lines_for_meta.append(f'{ts_codec}, "{temp_audio_path}", lang={stream["lang"]}')

            subtitle_streams = properties.get('subtitle_streams', [])
            for i, stream in enumerate(subtitle_streams):
                stream_codec, fps = stream['codec'], properties.get('fps_string', '23.976')
                ts_codec = TSMUXER_CODEC_MAP.get(stream_codec)
                if not ts_codec: continue
                file_extension = 'srt' if stream_codec == 'subrip' else 'sup'
                temp_sub_path = os.path.join(work_dir, f'clean_sub_{i}.{file_extension}')
                subtitle_index_in_remux = len(audio_streams) + i
                ffmpeg_cmd = ['ffmpeg', '-y', '-hide_banner', '-loglevel', 'error', '-i', clean_source_path, '-map', f'0:{subtitle_index_in_remux}', '-c', 'copy', temp_sub_path]
                subprocess.run(ffmpeg_cmd, check=True)
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
        base_name = os.path.splitext(os.path.basename(output_path))[0]
        disk_label = ''.join(c for c in base_name if c.isalnum() or c in ' _-').strip() or "BLURAY_3D_DISC"

        # Use decimal representation to ensure consistency with the encoder.
        fps_for_muxer = f"{properties.get('fps_float', 23.976):.3f}"

        # Build MUXOPT line according to new requirements for full compatibility.
        final_mux_options = [
            '--blu-ray-3d', '--vbr', '--insertSEI', '--contSPS',
            f'--label={disk_label}', f'--fps={fps_for_muxer}'
        ]
        chapters = properties.get('chapters', [])
        if chapters:
            final_mux_options.append(f'--custom-chapters={";".join(chapters)}')

        # Format the dependent view files for the meta file string, e.g., "file1"+"file2"
        right_eye_files_str = '+'.join([f'"{f}"' for f in dep_chunk_files])

        final_meta_content = [
            f'MUXOPT {" ".join(final_mux_options)}',
            f'V_MPEG4/ISO/AVC, "{left_eye_path}", ssif',
            f'V_MPEG4/ISO/MVC, {right_eye_files_str}, track=4113',
        ]
        
        final_meta_content.extend(audio_track_lines_for_meta)
        final_meta_content.extend(subtitle_track_lines_for_meta)

        with open(final_meta_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(final_meta_content))
        
        # Ensure the final output directory exists before running tsMuxeR.
        if output_path:
            os.makedirs(output_path, exist_ok=True)
            print(f"  [i] Ensured output directory exists: {output_path}")

        print(f"  [i] Running tsMuxeR. Output will be logged to: {os.path.basename(tsmuxer_log_path)}")
        # Normalize paths for better cross-platform compatibility and to avoid mixed slashes.
        tsmuxer_cmd_final = ['tsmuxer', os.path.normpath(final_meta_path), os.path.normpath(output_path)]
        with open(tsmuxer_log_path, "w", encoding='utf-8') as log:
            subprocess.run(tsmuxer_cmd_final, stdout=log, stderr=subprocess.STDOUT, check=True)

        # --- Post-Mux Validation ---
        print("  [i] Verifying that tsMuxeR created essential output files...")
        mpls_path = os.path.join(output_path, "BDMV", "PLAYLIST", "00000.mpls")
        clpi_path = os.path.join(output_path, "BDMV", "CLIPINF", "00000.clpi")

        if not os.path.exists(mpls_path) or os.path.getsize(mpls_path) < 100:
            raise IOError("tsMuxeR failed to generate a valid .mpls file. Check tsmuxer_output.log for details.")
        if not os.path.exists(clpi_path) or os.path.getsize(clpi_path) < 100:
            raise IOError("tsMuxeR failed to generate a valid .clpi file. Check tsmuxer_output.log for details.")
        print("  [✓] Basic validation passed: Key BDMV files were created by tsMuxeR.")
        
        output_type = "ISO file" if output_path.lower().endswith('.iso') else "BDMV folder structure"
        print(f"\n--- Blu-ray 3D {output_type} created successfully! ---")
        print(f"Location: {output_path}")
        success = True

    except (IOError, subprocess.CalledProcessError, FileNotFoundError, OSError) as e:
        print("\nFATAL ERROR: Muxing process failed.", file=sys.stderr)
        print(f"Error details: {e}", file=sys.stderr)
        print(f"\n[!] The detailed tsMuxeR log has been preserved for debugging at:\n    {tsmuxer_log_path}", file=sys.stderr)
        sys.exit(1)
    finally:
        # --- Cleanup of internal temporary files ---
        print("\n  [i] Cleaning up internal muxer temporary files...")

        # If the process failed, do not delete the tsMuxeR log file.
        if not success and tsmuxer_log_path in files_to_cleanup:
            files_to_cleanup.remove(tsmuxer_log_path)

        for f_path in files_to_cleanup:
            if not f_path or not os.path.exists(f_path): continue
            
            # Retry mechanism for deletion to handle potential file locks from external processes.
            for attempt in range(3):
                try:
                    os.remove(f_path)
                    print(f"    [✓] Removed temporary file: {os.path.basename(f_path)}")
                    break # Success, exit the retry loop
                except OSError as e:
                    if attempt < 2: # If not the last attempt
                        print(f"    [!] Could not delete {os.path.basename(f_path)}, retrying in 1 second... (Error: {e})")
                        time.sleep(1)
                    else:
                        print(f"    [✗] WARNING: Could not delete temp file {os.path.basename(f_path)} after multiple attempts: {e}. May require manual deletion.", file=sys.stderr)