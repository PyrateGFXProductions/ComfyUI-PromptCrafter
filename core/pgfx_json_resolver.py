import opentimelineio as otio
import json
import os
import argparse
from pathlib import Path

def create_resolve_timeline(json_path: str, video_dir: str, output_path: str, frame_rate: float = 24.0):
    """
    Converts a decision JSON from the DirectorAgent into a DaVinci Resolve
    compatible .fcpxml timeline.

    Args:
        json_path (str): Path to the decision_json file.
        video_dir (str): Directory containing the rendered video files (e.g., render_Style_A.mp4).
        output_path (str): Path to save the output .fcpxml file.
        frame_rate (float): The frame rate of the project.
    """
    # 1. Load the decision JSON
    try:
        with open(json_path, 'r') as f:
            decision_data = json.load(f)
        cuts = decision_data.get("cuts")
        if not cuts:
            print("Error: JSON file does not contain a 'cuts' list or is empty.")
            return
    except (json.JSONDecodeError, FileNotFoundError) as e:
        print(f"Error loading or parsing JSON file: {e}")
        return

    print(f"Found {len(cuts)} cuts in the decision file.")

    # 2. Create a new timeline and track
    timeline = otio.schema.Timeline(name="AgenticVideoDirector_Timeline")
    track = otio.schema.Track(name="V1", kind=otio.schema.TrackKind.Video)
    timeline.tracks.append(track)

    # 3. Scan for video files
    video_files = {
        Path(f).stem.replace('render_', ''): os.path.join(video_dir, f)
        for f in os.listdir(video_dir) if f.endswith(('.mp4', '.mov')) and f.startswith('render_')
    }

    if not video_files:
        print(f"Error: No video files found in '{video_dir}' with the 'render_Style_X.mp4' naming convention.")
        return
    
    print(f"Found video styles: {list(video_files.keys())}")

    # 4. Iterate through the cut list and build the timeline
    for i, cut in enumerate(cuts):
        start_time_sec = cut.get("timestamp")
        style = cut.get("style")

        if start_time_sec is None or style is None:
            print(f"Skipping invalid cut entry: {cut}")
            continue

        # Find the corresponding video file
        if style not in video_files:
            print(f"Warning: Style '{style}' found in JSON but no matching video file was found. Skipping clip.")
            continue
        
        media_path = video_files[style]

        # Calculate clip duration
        if i + 1 < len(cuts):
            next_start_time_sec = cuts[i+1].get("timestamp")
            duration_sec = next_start_time_sec - start_time_sec
        else:
            # For the last clip, we can give it a default duration or extend it.
            # Here, we'll give it a default of 5 seconds.
            duration_sec = 5.0

        start_time_otio = otio.opentime.from_seconds(start_time_sec)
        duration_otio = otio.opentime.from_seconds(duration_sec)

        # Create a reference to the media file
        media_reference = otio.schema.ExternalReference(target_url=Path(media_path).as_uri())

        # Create a clip
        clip = otio.schema.Clip(
            name=f"{style}_{i+1}",
            media_reference=media_reference,
            source_range=otio.opentime.TimeRange(start_time=start_time_otio, duration=duration_otio)
        )
        
        track.append(clip)
        print(f"Added clip: {clip.name} | Start: {start_time_sec:.2f}s | Duration: {duration_sec:.2f}s")

    # 5. Export the .fcpxml file
    otio.adapters.write_to_file(timeline, output_path)
    print(f"\nSuccessfully created DaVinci Resolve timeline at: {output_path}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Convert DirectorAgent JSON to a DaVinci Resolve FCPXML timeline.")
    parser.add_argument("json_path", type=str, help="Path to the input decision_json file.")
    parser.add_argument("video_dir", type=str, help="Directory containing the rendered video files (e.g., render_Style_A.mp4).")
    parser.add_argument("output_path", type=str, help="Path to save the output .fcpxml file.")
    parser.add_argument("--fps", type=float, default=24.0, help="Frame rate of the project (default: 24.0).")

    args = parser.parse_args()
    
    create_resolve_timeline(args.json_path, args.video_dir, args.output_path, args.fps)