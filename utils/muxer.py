import subprocess
import os
import shutil
import sys
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
    video_3d_mkv_path = os.path.join(work_dir, 'video_3d.mkv')
    left_eye_path = os.path.join(work_dir, 'left_eye.264')
    right_eye_path = os.path.join(work_dir, 'right_eye.264')
    clean_source_path = os.path.join(work_dir, 'clean_remux.mkv')
    final_meta_path = os.path.join(work_dir, 'muxer_final.meta')

    # This list will hold paths to all temporary files and folders for final cleanup
    files_to_cleanup = [final_meta_path, clean_source_path, video_3d_mkv_path, left_eye_path, right_eye_path]

    if not os.path.exists(video_3d_mkv_path):
        print(f"ERROR: Encoded 3D MKV stream not found in {work_dir}", file=sys.stderr)
        sys.exit(1)

    try:
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

        # --- Step 2c: Extract synchronized elementary streams using the reliable mkvextract tool ---
        print("\n--- Step 2c: Extracting synchronized elementary streams from 3D MKV ---")
        try:
            # mkvextract is the industry standard for reliably extracting tracks from MKV
            # without introducing timing errors, which is a known issue with ffmpeg's -c copy.
            # The syntax is: mkvextract tracks <source_mkv> <trackID>:"<output_file>"
            mkvextract_cmd = ['mkvextract', 'tracks', video_3d_mkv_path, f'0:"{left_eye_path}"', f'1:"{right_eye_path}"']
            subprocess.run(mkvextract_cmd, check=True, shell=True) # shell=True helps with path quoting on Windows
            print("  [✓] Synchronized elementary streams extracted successfully.")
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            print(f"ERROR: Failed to extract video streams using mkvextract: {e}", file=sys.stderr)
            print("Please ensure MKVToolNix is installed and 'mkvextract.exe' is in your PATH.", file=sys.stderr)
            sys.exit(1)

        # --- Step 2d: Final Mux - Combine all elementary streams ---
        print("\n--- Step 2d: Muxing all streams into the final Blu-ray structure ---")
        base_name = os.path.splitext(os.path.basename(output_path))[0]
        disk_label = ''.join(c for c in base_name if c.isalnum() or c in ' _-').strip() or "BLURAY_3D_DISC"
        final_mux_options = [f'--blu-ray-3d', f'--label={disk_label}']
        chapters = properties.get('chapters', [])
        if chapters:
            final_mux_options.append(f'--custom-chapters={";".join(chapters)}')

        final_meta_content = [
            f'MUXOPT {" ".join(final_mux_options)}',
            # Per your research, we are removing 'insertSEI' and 'contSPS' to prevent
            # tsMuxeR from modifying the already compliant stream from ffmpeg.
            f'V_MPEG4/ISO/AVC, "{left_eye_path}", ssif',
            f'V_MPEG4/ISO/AVC, "{right_eye_path}", subTrack, mvc',
        ]
        
        final_meta_content.extend(audio_track_lines_for_meta)
        final_meta_content.extend(subtitle_track_lines_for_meta)

        with open(final_meta_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(final_meta_content))
        
        tsmuxer_cmd_final = ['tsmuxer', final_meta_path, output_path]
        subprocess.run(tsmuxer_cmd_final, check=True)
        
        output_type = "ISO file" if output_path.lower().endswith('.iso') else "BDMV folder structure"
        print(f"\n--- Blu-ray 3D {output_type} created successfully! ---")
        print(f"Location: {output_path}")

    except (IOError, subprocess.CalledProcessError, FileNotFoundError, OSError) as e:
        print("\nFATAL ERROR: Muxing process failed.", file=sys.stderr)
        print(f"Error details: {e}", file=sys.stderr)
        print("Please check the output from tsMuxeR/ffmpeg above for specific error messages. Ensure write permissions are correct.", file=sys.stderr)
        sys.exit(1)
    finally:
        # --- Cleanup of internal temporary files ---
        print("\n  [i] Cleaning up internal muxer temporary files...")
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