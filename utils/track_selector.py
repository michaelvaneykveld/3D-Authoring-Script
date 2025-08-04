import sys

def _select_streams_by_type(streams, stream_type_name):
    """
    Generic helper function to display a list of streams and prompt the user for selection.

    Args:
        streams (list): A list of stream dictionaries (audio or subtitle).
        stream_type_name (str): The name of the stream type for prompts (e.g., "Audio", "Subtitle").

    Returns:
        list: A list of the selected stream dictionaries.
    """
    if not streams:
        print(f"  [i] No {stream_type_name.lower()} streams found.")
        return []

    print(f"\n--- Select {stream_type_name} Tracks to Include ---")
    for i, stream in enumerate(streams):
        print(f"  [{i+1}] - Codec: {stream.get('codec', 'N/A')}, Language: {stream.get('lang', 'N/A')}")

    while True:
        prompt = f"Enter the numbers of the {stream_type_name.lower()} tracks to include (e.g., '1,3'), 'all', or 'none'.\nPress Enter for default (all): "
        user_input = input(prompt).lower().strip()

        if not user_input or user_input == 'all':
            print(f"  [✓] Including all {len(streams)} {stream_type_name.lower()} track(s).")
            return streams

        if user_input == 'none':
            print(f"  [✓] Including no {stream_type_name.lower()} tracks.")
            return []

        try:
            selected_indices = [int(x.strip()) - 1 for x in user_input.split(',')]
            
            # Validate indices
            if any(i < 0 or i >= len(streams) for i in selected_indices):
                print(f"  [✗] ERROR: Invalid number. Please only use numbers from 1 to {len(streams)}.", file=sys.stderr)
                continue

            selected_streams = [streams[i] for i in selected_indices]
            print(f"  [✓] Selected {stream_type_name.lower()} tracks: {[i+1 for i in selected_indices]}")
            return selected_streams

        except ValueError:
            print("  [✗] ERROR: Invalid format. Please enter numbers separated by commas (e.g., 1,2).", file=sys.stderr)

def select_tracks(properties):
    """
    Interactively prompts the user to select which audio and subtitle tracks to
    include in the final Blu-ray.

    Args:
        properties (dict): The full properties dictionary from the video analyzer.

    Returns:
        dict: A new properties dictionary containing only the user-selected streams.
    """
    print("\n--- Optional: Select Audio and Subtitle Tracks ---")
    
    audio_streams = properties.get('audio_streams', [])
    subtitle_streams = properties.get('subtitle_streams', [])

    selected_audio = _select_streams_by_type(audio_streams, "Audio")
    selected_subtitles = _select_streams_by_type(subtitle_streams, "Subtitle")

    # Create a copy of the original properties and update it with the selections
    new_properties = properties.copy()
    new_properties['audio_streams'] = selected_audio
    new_properties['subtitle_streams'] = selected_subtitles

    return new_properties

if __name__ == '__main__':
    # Example usage for direct testing of this script
    mock_properties = {
        'audio_streams': [
            {'index': 1, 'codec': 'eac3', 'lang': 'eng'},
            {'index': 2, 'codec': 'ac3', 'lang': 'spa'},
            {'index': 3, 'codec': 'dts', 'lang': 'fre'}
        ],
        'subtitle_streams': [
            {'index': 4, 'codec': 'subrip', 'lang': 'eng'},
            {'index': 5, 'codec': 'hdmv_pgs_subtitle', 'lang': 'spa'}
        ]
    }
    selected_props = select_tracks(mock_properties)
    print("\n--- Final Selected Properties ---")
    print(selected_props)