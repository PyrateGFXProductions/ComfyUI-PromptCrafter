import json
import os
import re
import hashlib
import wave
import subprocess
import shutil
import tempfile
from typing import Tuple, Dict, Any, List, Optional

import torch

# ------------------------------------------------------------------------------------
# Helper function to read node descriptions from HELP.md
# ------------------------------------------------------------------------------------
def get_node_description(node_name):
    """Parses HELP.md and extracts the description for a given node class name."""
    try:
        help_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "HELP.md")
        if not os.path.exists(help_path):
            return f"Help file not found for {node_name}."

        with open(help_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Match either ## `NodeName` or ## `NodeName` (Alternate Name)
        pattern = re.compile(rf"##\s*`({node_name})(?:`|\s*\(.*?\)`)\n(.*?)(?=\n##\s*`|\Z)", re.DOTALL)
        match = pattern.search(content)

        if match:
            return match.group(2).strip()
        return f"No description found in HELP.md for {node_name}."
    except Exception as e:
        return f"Error reading help file: {e}"

class PGFX_FilmProjectController:
    """
    PGFX Film - Project Controller
    Deterministic, stateless project initializer for film production workflows.
    """
    DESCRIPTION = get_node_description("PGFX_FilmProjectController")

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "audio_filename": ("STRING", {"multiline": False}),
                "context_text": ("STRING", {"multiline": True}),
                "style_preset": (
                    [
                        "Cinematic Realism",
                        "Neo-Noir",
                        "Stage Performance",
                        "Dreamscape",
                    ],
                ),
                "vram_mode": (["Low", "Balanced", "Cinema"],),
            },
            "optional": {
                "reference_image": ("IMAGE",),
            },
        }

    RETURN_TYPES = ("DICT", "DICT", "DICT")
    RETURN_NAMES = (
        "project_config",
        "initial_character_list",
        "project_state",
    )

    FUNCTION = "execute"
    CATEGORY = "☠️PGFX /Film"

    def execute(
        self,
        audio_filename: str,
        context_text: str,
        style_preset: str,
        vram_mode: str,
        reference_image=None,
    ) -> Tuple[dict, dict, dict]:
        hash_input = f"{audio_filename}|{context_text}|{style_preset}|{vram_mode}"
        sha = hashlib.sha256(hash_input.encode("utf-8")).hexdigest()
        project_id = int(sha[:12], 16)

        resolution, steps, frames_per_shot, max_shots = self._vram_config(vram_mode)

        project_config = {
            "project_id": project_id,
            "resolution": resolution,
            "steps": steps,
            "cfg": 1.5,
            "frames_per_shot": frames_per_shot,
            "max_shots": max_shots,
            "style_preset": style_preset,
            "context": context_text,
            "has_reference_image": reference_image is not None,
        }

        initial_characters = self._extract_characters(context_text)

        project_state = {
            "project_id": project_id,
            "audio_filename": audio_filename,
            "config": project_config,
            "characters": initial_characters,
            "render_progress": {"current_shot_index": 0, "completed_shots": []},
            "hash_signature": sha,
        }

        return (
            project_config,
            {"characters": initial_characters},
            project_state,
        )

    def _vram_config(self, vram_mode: str) -> Tuple[Tuple[int, int], int, int, int]:
        match vram_mode:
            case "Low":
                return (768, 432), 6, 48, 3
            case "Balanced":
                return (832, 480), 6, 48, 5
            case "Cinema":
                return (1024, 576), 8, 72, 7
            case _:
                return (832, 480), 6, 48, 5

    def _extract_characters(self, context_text: str) -> List[Dict[str, Any]]:
        words = context_text.split()
        capitalized = [w.strip(".,!?") for w in words if w.istitle()]

        unique_names = []
        for name in capitalized:
            if name not in unique_names:
                unique_names.append(name)

        characters = []

        if len(unique_names) == 0:
            characters = [
                {
                    "character_id": "lead",
                    "role_weight": 1.0,
                    "description_seed_basis": context_text[:50],
                },
                {
                    "character_id": "support_1",
                    "role_weight": 0.8,
                    "description_seed_basis": context_text[:50],
                },
            ]
        else:
            weights = [1.0, 0.85, 0.7]
            for i, name in enumerate(unique_names[:3]):
                characters.append(
                    {
                        "character_id": name.lower(),
                        "role_weight": weights[i] if i < len(weights) else 0.6,
                        "description_seed_basis": name,
                    }
                )

        return characters


class PGFX_FilmCharacterRegistry:
    """
    PGFX Film - Ensemble Character Registry
    Strong Continuity Version - Deterministic, Stateless, JSON-based.
    """
    DESCRIPTION = get_node_description("PGFX_FilmCharacterRegistry")

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "project_state": ("DICT",),
            },
            "optional": {
                "reference_image": ("IMAGE",),
            },
        }

    RETURN_TYPES = ("DICT", "DICT")
    RETURN_NAMES = (
        "character_registry",
        "project_state",
    )

    FUNCTION = "execute"
    CATEGORY = "☠️PGFX /Film"

    def execute(
        self,
        project_state: dict,
        reference_image=None,
    ) -> Tuple[dict, dict]:

        if not project_state:
            raise ValueError(
                "PGFX_FilmCharacterRegistry: 'project_state' is empty. Connect it to ProjectController."
            )

        project_id = project_state["project_id"]
        initial_characters = project_state["characters"]

        registry = {"characters": []}

        for char in initial_characters:
            character_id = char["character_id"]
            role_weight = char["role_weight"]
            seed_basis = char["description_seed_basis"]

            base_seed = self._generate_seed(project_id, character_id, seed_basis)

            identity_stub = {
                "gender": None,
                "age_range": None,
                "ethnicity": None,
                "visual_markers": [],
            }

            character_entry = {
                "character_id": character_id,
                "base_seed": base_seed,
                "role_weight": role_weight,
                "identity_stub": identity_stub,
                "continuity_lock": True,
                "reference_bound": (
                    True
                    if reference_image is not None and character_id == "lead"
                    else False
                ),
            }

            registry["characters"].append(character_entry)

        project_state["character_registry"] = registry

        return (
            registry,
            project_state,
        )

    def _generate_seed(
        self, project_id: int, character_id: str, seed_basis: str
    ) -> int:
        seed_input = f"{project_id}|{character_id}|{seed_basis}"
        sha = hashlib.sha256(seed_input.encode("utf-8")).hexdigest()
        return int(sha[:12], 16)


class PGFX_FilmShotArchitect:
    """
    PGFX Film - Structured Cinema Shot Architect
    Dynamic per-shot generator. Deterministic. Strong Continuity.
    """
    DESCRIPTION = get_node_description("PGFX_FilmShotArchitect")

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "project_state": ("DICT",),
                "character_registry": ("DICT",),
                "audio_filename": ("STRING",),
                "shot_index": ("INT", {"default": 0, "min": 0}),
            }
        }

    RETURN_TYPES = ("DICT",)
    RETURN_NAMES = ("shot_config",)

    FUNCTION = "execute"
    CATEGORY = "☠️PGFX /Film"

    def execute(
        self,
        project_state: dict,
        character_registry: dict,
        audio_filename: str,
        shot_index: int,
    ) -> Tuple[dict]:

        if not project_state:
            raise ValueError(
                "PGFX_FilmShotArchitect: 'project_state' is empty. Connect it to CharacterRegistry or ProjectController."
            )

        if not character_registry:
            raise ValueError(
                "PGFX_FilmShotArchitect: 'character_registry' is empty. Connect it to CharacterRegistry."
            )

        config = project_state["config"]
        max_shots = config["max_shots"]
        frames = config["frames_per_shot"]

        total_duration = self._get_audio_duration(audio_filename)

        if shot_index >= max_shots:
            shot_index = max_shots - 1

        shot_duration_sec = total_duration / max_shots
        start_sec = shot_index * shot_duration_sec
        end_sec = start_sec + shot_duration_sec

        characters = character_registry["characters"]

        shot_type = self._determine_shot_type(shot_index, len(characters))
        characters_in_shot = self._select_characters(characters, shot_type)

        dominant_character = max(
            characters_in_shot,
            key=lambda cid: next(c for c in characters if c["character_id"] == cid)[
                "role_weight"
            ],
        )

        dominant_seed = next(
            c for c in characters if c["character_id"] == dominant_character
        )["base_seed"]

        camera_block = self._rotate_block(
            shot_index,
            [
                "close_up_85mm",
                "medium_50mm",
                "wide_35mm",
                "tracking_side",
                "overhead_crane",
            ],
        )

        lighting_block = self._rotate_block(
            shot_index,
            [
                "moody_low_key",
                "high_key_stage",
                "sunset_backlight",
                "neon_night",
                "soft_window_light",
            ],
        )

        motion_block = self._rotate_block(
            shot_index,
            [
                "static",
                "slow_dolly_push",
                "handheld_subtle",
                "tracking_motion",
                "crane_descend",
            ],
        )

        shot_config = {
            "shot_index": shot_index,
            "shot_type": shot_type,
            "dominant_character": dominant_character,
            "characters_in_shot": characters_in_shot,
            "camera_block": camera_block,
            "lighting_block": lighting_block,
            "motion_block": motion_block,
            "frames": frames,
            "seed": dominant_seed,
            "audio_window": {
                "start_sec": round(start_sec, 3),
                "end_sec": round(end_sec, 3),
            },
        }

        return (shot_config,)

    def _get_audio_duration(self, audio_filename: str) -> float:
        try:
            with wave.open(audio_filename, "rb") as wf:
                frames = wf.getnframes()
                rate = wf.getframerate()
                return frames / float(rate)
        except Exception:
            return 60.0

    def _determine_shot_type(self, shot_index: int, num_characters: int) -> str:
        if num_characters == 1:
            return "solo"

        pattern = ["solo", "duo", "solo", "group", "solo"]
        return pattern[shot_index % len(pattern)]

    def _select_characters(self, characters: list, shot_type: str) -> list:
        ids = [c["character_id"] for c in characters]

        if shot_type == "solo":
            return [ids[0]]
        if shot_type == "duo" and len(ids) >= 2:
            return ids[:2]
        if shot_type == "group":
            return ids
        return [ids[0]]

    def _rotate_block(self, shot_index: int, options: list) -> str:
        return options[shot_index % len(options)]


class PGFX_FilmSaveShotVideo:
    """
    PGFX Film - Shot Video Saver
    Saves IMAGE frames to mp4 via ffmpeg pipe and outputs absolute path STRING.
    """
    DESCRIPTION = get_node_description("PGFX_FilmSaveShotVideo")

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": ("IMAGE",),
                "project_state": ("DICT",),
                "shot_index": ("INT", {"default": 0, "min": 0}),
                "fps": ("INT", {"default": 24, "min": 1}),
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("clip_path",)
    FUNCTION = "execute"
    CATEGORY = "☠️PGFX /Film"

    def execute(
        self,
        images: torch.Tensor,
        project_state: dict,
        shot_index: int,
        fps: int = 24,
    ) -> Tuple[str]:

        if not project_state:
            raise ValueError("PGFX_FilmSaveShotVideo: 'project_state' is empty.")

        project_id = project_state["project_id"]

        output_root = "AI_FilmStudio_Output"
        project_dir = os.path.join(output_root, f"project_{project_id}")
        shots_dir = os.path.join(project_dir, "shots")
        os.makedirs(shots_dir, exist_ok=True)

        target_filename = f"shot_{shot_index:03d}_raw.mp4"
        target_path = os.path.abspath(os.path.join(shots_dir, target_filename))

        ffmpeg_path = shutil.which("ffmpeg")
        if not ffmpeg_path:
            raise RuntimeError("ffmpeg not found in system PATH.")

        batch, height, width, channels = images.shape

        cmd = [
            ffmpeg_path,
            "-y",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-s",
            f"{width}x{height}",
            "-r",
            str(fps),
            "-i",
            "-",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-crf",
            "18",
            target_path,
        ]

        try:
            raw_data = (images.cpu().clamp(0, 1) * 255).to(torch.uint8).numpy()

            process = subprocess.Popen(
                cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE
            )
            _, stderr = process.communicate(input=raw_data.tobytes())

            if process.returncode != 0:
                raise RuntimeError(
                    f"FFmpeg failed with return code {process.returncode}: {stderr.decode()}"
                )

        except Exception as e:
            raise RuntimeError(f"Failed to save video: {str(e)}")

        return (target_path,)


class PGFX_FilmAudioLoader:
    """
    PGFX Film - Audio Loader
    Loads an audio file from a string path into ComfyUI's AUDIO format.
    """
    DESCRIPTION = get_node_description("PGFX_FilmAudioLoader")

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "audio_path": ("STRING", {"default": ""}),
            }
        }

    RETURN_TYPES = ("AUDIO",)
    RETURN_NAMES = ("audio",)

    FUNCTION = "execute"
    CATEGORY = "☠️PGFX /Film"

    def execute(self, audio_path: str) -> Tuple[dict]:
        if not audio_path or not isinstance(audio_path, str):
            raise ValueError(f"PGFX_FilmAudioLoader: Invalid audio_path: {audio_path}")

        try:
            import torchaudio
        except ImportError:
            raise ImportError(
                "torchaudio is required for PGFX_FilmAudioLoader. Install it with: pip install torchaudio"
            )

        try:
            torchaudio.set_audio_backend("soundfile")
        except Exception:
            pass
        waveform, sample_rate = torchaudio.load(audio_path)

        audio = {
            "waveform": waveform.unsqueeze(0) if waveform.dim() == 2 else waveform,
            "sample_rate": sample_rate,
        }

        return (audio,)


class PGFX_FilmAssembler:
    """
    PGFX Film - Video Assembler
    Stitches shots based on the PROJECT_CONFIG's completed_shots list.
    """
    DESCRIPTION = get_node_description("PGFX_FilmAssembler")

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "PROJECT_CONFIG": ("DICT",),
                "is_complete": ("BOOLEAN",),
                "output_filename": ("STRING", {"default": "final_video.mp4"}),
            },
            "optional": {
                "custom_ffmpeg_path": ("STRING", {"default": ""}),
                "original_audio": ("AUDIO",),
            },
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("final_video_path",)

    FUNCTION = "execute"
    CATEGORY = "☠️PGFX /Film"
    OUTPUT_NODE = True

    def _resolve_project_dir(self, PROJECT_CONFIG: Dict[str, Any], shots: list) -> str:
        project_dir = str(PROJECT_CONFIG.get("project_dir", "")).strip()
        if project_dir:
            return project_dir

        if shots:
            first = shots[0].get("clip_path", "")
            if first:
                p = os.path.abspath(str(first))
                parent = os.path.dirname(p)
                if os.path.basename(parent).lower() == "shots":
                    return os.path.dirname(parent)
                return parent

        project_name = str(PROJECT_CONFIG.get("project_name", "Untitled"))
        root_path = (
            str(PROJECT_CONFIG.get("root_path", "AI_FilmStudio_Output")).strip()
            or "AI_FilmStudio_Output"
        )
        if os.path.isabs(root_path):
            base_dir = root_path
        else:
            try:
                import folder_paths

                base_dir = os.path.join(folder_paths.get_output_directory(), root_path)
            except Exception:
                base_dir = os.path.abspath(root_path)
        return os.path.join(base_dir, project_name)

    def _concat_video(
        self, ffmpeg_path: str, concat_path: str, output_path: str
    ) -> Tuple[bool, str]:
        copy_cmd = [
            ffmpeg_path,
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            concat_path,
            "-c",
            "copy",
            output_path,
        ]
        try:
            subprocess.run(copy_cmd, check=True, capture_output=True)
            return (True, "")
        except subprocess.CalledProcessError as e:
            reencode_cmd = [
                ffmpeg_path,
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                concat_path,
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                output_path,
            ]
            try:
                subprocess.run(reencode_cmd, check=True, capture_output=True)
                return (True, "")
            except subprocess.CalledProcessError as e2:
                err = (
                    e2.stderr.decode()
                    if e2.stderr
                    else (e.stderr.decode() if e.stderr else str(e2))
                )
                return (False, err)

    def _save_original_audio(
        self, original_audio: Dict[str, Any], wav_path: str
    ) -> bool:
        if not isinstance(original_audio, dict):
            return False
        waveform = original_audio.get("waveform")
        sample_rate = int(original_audio.get("sample_rate", 0) or 0)
        if sample_rate <= 0 or waveform is None:
            return False
        try:
            if not torch.is_tensor(waveform):
                return False
            if waveform.ndim == 3:
                waveform = waveform.squeeze(0)
            elif waveform.ndim == 1:
                waveform = waveform.unsqueeze(0)
            waveform = waveform.detach().cpu().float()
            if waveform.numel() == 0:
                return False

            if waveform.ndim != 2:
                return False
            channels = int(waveform.shape[0])
            if channels < 1:
                return False

            import numpy as np

            pcm = waveform.clamp(-1.0, 1.0).numpy()
            pcm16 = (pcm.T * 32767.0).astype(np.int16)
            with wave.open(wav_path, "wb") as wf:
                wf.setnchannels(channels)
                wf.setsampwidth(2)
                wf.setframerate(sample_rate)
                wf.writeframes(pcm16.tobytes())
            return True
        except Exception:
            return False

    def _normalize_output_filename(self, output_filename: str) -> str:
        name = str(output_filename or "").strip()
        if not name:
            name = "final_music_video.mp4"
        base, ext = os.path.splitext(name)
        if not ext:
            name = f"{name}.mp4"
        return name

    def execute(
        self,
        PROJECT_CONFIG: Dict[str, Any],
        is_complete: bool,
        output_filename: str,
        custom_ffmpeg_path: str = "",
        original_audio: Dict[str, Any] = None,
    ) -> Tuple[str]:

        if not is_complete:
            return ("Rendering in progress...",)

        render_progress = PROJECT_CONFIG.get("render_progress", {})
        shots = render_progress.get("completed_shots", [])

        if not shots:
            return ("No completed shots found to assemble.",)

        project_dir = self._resolve_project_dir(PROJECT_CONFIG, shots)
        os.makedirs(project_dir, exist_ok=True)

        ffmpeg_path = custom_ffmpeg_path.strip() or shutil.which("ffmpeg")
        if not ffmpeg_path:
            return ("FFmpeg not found. Please install it.",)

        shots.sort(key=lambda x: x["shot_index"])
        concat_path = os.path.join(project_dir, "concat_list.txt")
        valid_shots = 0
        with open(concat_path, "w", encoding="utf-8") as f:
            for shot in shots:
                abs_path = os.path.abspath(shot["clip_path"])
                if os.path.exists(abs_path):
                    f.write(f"file '{abs_path}'\n")
                    valid_shots += 1

        if valid_shots == 0:
            return ("No valid shot files found to assemble.",)

        output_filename = self._normalize_output_filename(output_filename)
        if os.path.isabs(output_filename):
            final_video_path = output_filename
        else:
            final_video_path = os.path.join(project_dir, output_filename)
        base_concat_path = os.path.join(project_dir, "__concat_video.mp4")

        ok, err = self._concat_video(ffmpeg_path, concat_path, base_concat_path)
        if not ok:
            return (f"FFmpeg concat error: {err}",)

        used_original_audio = False
        temp_audio_wav = os.path.join(project_dir, "__original_audio.wav")
        try:
            used_original_audio = self._save_original_audio(
                original_audio, temp_audio_wav
            )
            if used_original_audio:
                merge_cmd = [
                    ffmpeg_path,
                    "-y",
                    "-i",
                    base_concat_path,
                    "-i",
                    temp_audio_wav,
                    "-map",
                    "0:v:0",
                    "-map",
                    "1:a:0",
                    "-c:v",
                    "copy",
                    "-c:a",
                    "aac",
                    "-b:a",
                    "192k",
                    "-shortest",
                    final_video_path,
                ]
                try:
                    subprocess.run(merge_cmd, check=True, capture_output=True)
                except subprocess.CalledProcessError:
                    merge_cmd_fallback = [
                        ffmpeg_path,
                        "-y",
                        "-i",
                        base_concat_path,
                        "-i",
                        temp_audio_wav,
                        "-map",
                        "0:v:0",
                        "-map",
                        "1:a:0",
                        "-c:v",
                        "libx264",
                        "-pix_fmt",
                        "yuv420p",
                        "-c:a",
                        "aac",
                        "-b:a",
                        "192k",
                        "-shortest",
                        final_video_path,
                    ]
                    subprocess.run(merge_cmd_fallback, check=True, capture_output=True)
            else:
                shutil.move(base_concat_path, final_video_path)

            print(
                f"[PGFX_FilmAssembler] Assembled {valid_shots} shots -> {final_video_path}"
            )
            return (final_video_path,)
        except subprocess.CalledProcessError as e:
            err = e.stderr.decode() if e.stderr else str(e)
            return (f"FFmpeg error: {err}",)
        finally:
            try:
                if os.path.exists(base_concat_path):
                    os.remove(base_concat_path)
            except Exception:
                pass
            if used_original_audio:
                try:
                    if os.path.exists(temp_audio_wav):
                        os.remove(temp_audio_wav)
                except Exception:
                    pass


class PGFX_FilmRenderProject:
    """
    PGFX Film - Render Orchestrator
    Manages incremental file persistence for PGFX-driven projects.
    """
    DESCRIPTION = get_node_description("PGFX_FilmRenderProject")

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "PROJECT_CONFIG": ("DICT",),
                "clip_path": ("STRING",),
                "shot_index": ("INT", {"default": 0, "min": 0}),
            }
        }

    RETURN_TYPES = ("DICT", "BOOLEAN")
    RETURN_NAMES = ("PROJECT_CONFIG", "is_complete")

    FUNCTION = "execute"
    CATEGORY = "☠️PGFX /Film"

    def _resolve_project_dir(
        self, PROJECT_CONFIG: Dict[str, Any], clip_path: str
    ) -> str:
        clip_path = str(clip_path or "").strip()
        if clip_path:
            abs_clip = os.path.abspath(clip_path)
            clip_dir = os.path.dirname(abs_clip)
            if os.path.basename(clip_dir).lower() == "shots":
                return os.path.dirname(clip_dir)
            return clip_dir

        project_name = str(PROJECT_CONFIG.get("project_name", "Untitled"))
        root_path = (
            str(PROJECT_CONFIG.get("root_path", "AI_FilmStudio_Output")).strip()
            or "AI_FilmStudio_Output"
        )

        if os.path.isabs(root_path):
            base_dir = root_path
        else:
            try:
                import folder_paths

                base_dir = os.path.join(folder_paths.get_output_directory(), root_path)
            except Exception:
                base_dir = os.path.abspath(root_path)

        return os.path.join(base_dir, project_name)

    def _to_json_safe(self, value: Any) -> Any:
        if isinstance(value, dict):
            return {str(k): self._to_json_safe(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [self._to_json_safe(v) for v in value]
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        if hasattr(value, "device"):
            return f"<tensor:{getattr(value, 'shape', 'unknown')}>"
        return str(value)

    def execute(
        self,
        PROJECT_CONFIG: Dict[str, Any],
        clip_path: str,
        shot_index: int,
    ) -> Tuple[Dict[str, Any], bool]:

        render_plan = PROJECT_CONFIG.get("render_plan", {})
        total_shots = render_plan.get("total_jobs", 1)

        project_dir = self._resolve_project_dir(PROJECT_CONFIG, clip_path)
        PROJECT_CONFIG["project_dir"] = project_dir
        shots_dir = os.path.join(project_dir, "shots")
        os.makedirs(shots_dir, exist_ok=True)

        target_filename = f"shot_{shot_index:03d}.mp4"
        target_path = os.path.join(shots_dir, target_filename)

        source_path = os.path.abspath(str(clip_path or ""))
        if source_path and os.path.exists(source_path):
            if os.path.abspath(source_path) != os.path.abspath(target_path):
                shutil.copy2(source_path, target_path)
            else:
                target_path = source_path
            print(f"[PGFX_FilmRenderProject] Saved shot {shot_index} to: {target_path}")
        else:
            print(
                f"[PGFX_FilmRenderProject] Warning: clip path missing for shot {shot_index}: {clip_path}"
            )

        state_path = os.path.join(project_dir, "project_metadata.json")
        if "render_progress" not in PROJECT_CONFIG:
            try:
                if os.path.exists(state_path):
                    with open(state_path, "r", encoding="utf-8") as f:
                        persisted = json.load(f)
                    if isinstance(persisted, dict) and isinstance(
                        persisted.get("render_progress"), dict
                    ):
                        PROJECT_CONFIG["render_progress"] = persisted["render_progress"]
            except Exception as e:
                print(f"[PGFX_FilmRenderProject] Metadata restore warning: {e}")

        if "render_progress" not in PROJECT_CONFIG:
            PROJECT_CONFIG["render_progress"] = {"completed_shots": []}

        completed = PROJECT_CONFIG["render_progress"]["completed_shots"]

        completed = [s for s in completed if s["shot_index"] != shot_index]
        completed.append({"shot_index": shot_index, "clip_path": target_path})
        completed.sort(key=lambda x: x["shot_index"])

        PROJECT_CONFIG["render_progress"]["completed_shots"] = completed

        is_complete = shot_index >= (total_shots - 1)

        try:
            with open(state_path, "w", encoding="utf-8") as f:
                json.dump(self._to_json_safe(PROJECT_CONFIG), f, indent=2)
        except Exception as e:
            print(f"[PGFX_FilmRenderProject] Metadata persistence warning: {e}")

        return (PROJECT_CONFIG, is_complete)


class PGFX_FilmShotConfigExtractor:
    """
    PGFX Film - Shot Config Extractor (Unified)
    Matched to legacy slot signature for drop-in workflow replacement.
    """
    DESCRIPTION = get_node_description("PGFX_FilmShotConfigExtractor")

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "SHOT_LIST": ("DICT",),
                "TIMING_MAP": ("DICT",),
                "shot_index": ("INT", {"default": 0, "min": 0, "max": 999}),
                "PROJECT_CONFIG": ("DICT",),
            },
            "optional": {
                "reference_image": ("IMAGE",),
            },
        }

    RETURN_TYPES = (
        "STRING",
        "INT",
        "INT",
        "INT",
        "INT",
        "INT",
        "FLOAT",
        "AUDIO",
        "IMAGE",
    )
    RETURN_NAMES = (
        "prompt",
        "seed",
        "num_frames",
        "width",
        "height",
        "steps",
        "cfg",
        "AUDIO",
        "IMAGE",
    )

    FUNCTION = "execute"
    CATEGORY = "☠️PGFX /Film"

    def _entry_index(self, entry: Dict[str, Any], fallback: int = -1) -> int:
        try:
            return int(entry.get("index", fallback))
        except Exception:
            return fallback

    def _find_entry(
        self, entries: Any, target_index: int
    ) -> Tuple[Optional[Dict[str, Any]], str]:
        if not isinstance(entries, list) or not entries:
            return None, "none"

        for entry in entries:
            if isinstance(entry, dict) and self._entry_index(entry, -1) == target_index:
                return entry, "index"

        if 0 <= target_index < len(entries) and isinstance(entries[target_index], dict):
            return entries[target_index], "position"

        return None, "none"

    def _to_int(self, value: Any, default: int) -> int:
        try:
            return int(value)
        except Exception:
            return default

    def _to_float(self, value: Any, default: float) -> float:
        try:
            return float(value)
        except Exception:
            return default

    def _normalize_audio(self, audio: Any) -> Dict[str, Any]:
        empty = {
            "waveform": torch.zeros((1, 1, 16000), dtype=torch.float32),
            "sample_rate": 16000,
        }
        if not isinstance(audio, dict):
            return empty

        waveform = audio.get("waveform")
        sample_rate = self._to_int(audio.get("sample_rate", 16000), 16000)
        if not torch.is_tensor(waveform):
            return empty

        wf = waveform.detach().cpu().float()
        if wf.ndim == 1:
            wf = wf.unsqueeze(0).unsqueeze(0)
        elif wf.ndim == 2:
            wf = wf.unsqueeze(0)
        elif wf.ndim != 3:
            return empty

        return {"waveform": wf, "sample_rate": sample_rate}

    def _normalize_reference_image(
        self, reference_image: Any
    ) -> Optional[torch.Tensor]:
        if not torch.is_tensor(reference_image):
            return None

        img = reference_image.detach().cpu().float()
        if img.ndim == 3:
            img = img.unsqueeze(0)
        if img.ndim != 4:
            return None
        if img.shape[0] > 1:
            img = img[:1]
        return img

    def _build_blank_image(self, width: int, height: int) -> torch.Tensor:
        h = max(1, int(height))
        w = max(1, int(width))
        return torch.zeros((1, h, w, 3), dtype=torch.float32)

    def _fit_image_to_resolution(
        self, image: torch.Tensor, width: int, height: int
    ) -> torch.Tensor:
        if not torch.is_tensor(image):
            return self._build_blank_image(width, height)

        target_w = max(1, int(width))
        target_h = max(1, int(height))

        img = image.detach().cpu().float()
        if img.ndim == 3:
            img = img.unsqueeze(0)
        if img.ndim != 4:
            return self._build_blank_image(target_w, target_h)
        if img.shape[0] > 1:
            img = img[:1]

        cur_h = int(img.shape[1])
        cur_w = int(img.shape[2])
        if cur_w == target_w and cur_h == target_h:
            return img

        bchw = img.permute(0, 3, 1, 2)
        resized = torch.nn.functional.interpolate(
            bchw,
            size=(target_h, target_w),
            mode="bilinear",
            align_corners=False,
        )
        return resized.permute(0, 2, 3, 1).contiguous()

    def _is_hard_cut(self, active_shot: Optional[Dict[str, Any]]) -> bool:
        if not isinstance(active_shot, dict):
            return False

        for key in ("hard_cut", "is_hard_cut", "scene_change"):
            value = active_shot.get(key)
            if isinstance(value, bool):
                return value
            if isinstance(value, (int, float)):
                return bool(value)
            if isinstance(value, str) and value.strip().lower() in {
                "1",
                "true",
                "yes",
                "hard_cut",
                "hard-cut",
                "cut",
            }:
                return True

        for key in ("continuity_mode", "transition_type", "cut_type"):
            value = str(active_shot.get(key, "") or "").strip().lower()
            if value in {"hard_cut", "hard-cut", "cut", "scene_change", "scene-change"}:
                return True

        return False

    def _resolve_project_dir(self, PROJECT_CONFIG: Dict[str, Any]) -> Optional[str]:
        project_dir = str(PROJECT_CONFIG.get("project_dir", "") or "").strip()
        if project_dir:
            return project_dir

        root_path = str(PROJECT_CONFIG.get("root_path", "") or "").strip()
        project_name = str(PROJECT_CONFIG.get("project_name", "") or "").strip()

        if not root_path and not project_name:
            return None

        if root_path:
            if os.path.isabs(root_path):
                base_dir = root_path
            else:
                try:
                    import folder_paths

                    base_dir = os.path.join(
                        folder_paths.get_output_directory(), root_path
                    )
                except Exception:
                    base_dir = os.path.abspath(root_path)
        else:
            base_dir = ""

        if project_name:
            base_tail = os.path.basename(os.path.normpath(base_dir)) if base_dir else ""
            if not base_dir:
                return os.path.abspath(project_name)
            if base_tail == project_name:
                return base_dir
            return os.path.join(base_dir, project_name)

        return base_dir if base_dir else None

    def _candidate_previous_video_paths(
        self, PROJECT_CONFIG: Dict[str, Any], shot_index: int
    ) -> List[str]:
        prev_index = int(shot_index) - 1
        if prev_index < 0:
            return []

        candidates: List[str] = []

        render_progress = PROJECT_CONFIG.get("render_progress", {})
        completed = (
            render_progress.get("completed_shots", [])
            if isinstance(render_progress, dict)
            else []
        )
        if isinstance(completed, list):
            for item in completed:
                if not isinstance(item, dict):
                    continue
                if self._to_int(item.get("shot_index", -1), -1) != prev_index:
                    continue
                clip_path = str(item.get("clip_path", "") or "").strip()
                if clip_path:
                    candidates.append(os.path.abspath(clip_path))

        project_dir = self._resolve_project_dir(PROJECT_CONFIG)
        if project_dir:
            shots_dir = os.path.join(project_dir, "shots")
            candidates.extend(
                [
                    os.path.join(shots_dir, f"shot_{prev_index:03d}.mp4"),
                    os.path.join(shots_dir, f"Scene_{prev_index:03d}.mp4"),
                    os.path.join(shots_dir, f"scene_{prev_index:03d}.mp4"),
                ]
            )

        deduped = []
        seen = set()
        for path in candidates:
            abs_path = os.path.abspath(path)
            if abs_path in seen:
                continue
            seen.add(abs_path)
            if os.path.exists(abs_path):
                deduped.append(abs_path)
        return deduped

    def _tensor_from_rgb_frame(self, frame: Any) -> Optional[torch.Tensor]:
        try:
            import numpy as np
        except Exception:
            return None

        if frame is None:
            return None

        arr = frame
        if not isinstance(arr, np.ndarray):
            try:
                arr = np.asarray(arr)
            except Exception:
                return None

        if arr.ndim == 2:
            arr = np.stack([arr, arr, arr], axis=-1)
        if arr.ndim != 3:
            return None
        if arr.shape[-1] > 3:
            arr = arr[..., :3]

        if arr.dtype != np.float32:
            arr = arr.astype(np.float32)
            if arr.max() > 1.0:
                arr /= 255.0

        tensor = torch.from_numpy(arr)
        if tensor.ndim == 3:
            tensor = tensor.unsqueeze(0)
        return tensor.float()

    def _load_last_frame_via_ffmpeg(self, video_path: str) -> Optional[torch.Tensor]:
        ffmpeg_path = shutil.which("ffmpeg")
        if not ffmpeg_path:
            return None

        tmp_file = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                tmp_file = tmp.name

            cmd = [
                ffmpeg_path,
                "-y",
                "-sseof",
                "-0.08",
                "-i",
                video_path,
                "-frames:v",
                "1",
                tmp_file,
            ]
            proc = subprocess.run(cmd, capture_output=True, check=False)

            if (
                proc.returncode != 0
                or not os.path.exists(tmp_file)
                or os.path.getsize(tmp_file) == 0
            ):
                cmd_fallback = [
                    ffmpeg_path,
                    "-y",
                    "-sseof",
                    "-0.5",
                    "-i",
                    video_path,
                    "-frames:v",
                    "1",
                    tmp_file,
                ]
                subprocess.run(cmd_fallback, capture_output=True, check=False)

            if not os.path.exists(tmp_file) or os.path.getsize(tmp_file) == 0:
                return None

            try:
                from PIL import Image
            except Exception:
                return None

            with Image.open(tmp_file) as im:
                rgb = im.convert("RGB")
                return self._tensor_from_rgb_frame(rgb)
        except Exception:
            return None
        finally:
            if tmp_file and os.path.exists(tmp_file):
                try:
                    os.remove(tmp_file)
                except Exception:
                    pass

    def _load_last_frame_from_video(self, video_path: str) -> Optional[torch.Tensor]:
        frame = self._load_last_frame_via_ffmpeg(video_path)
        if frame is not None:
            return frame

        try:
            import cv2

            cap = cv2.VideoCapture(video_path)
            if cap is not None and cap.isOpened():
                frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
                if frame_count > 1:
                    cap.set(cv2.CAP_PROP_POS_FRAMES, frame_count - 1)
                ok, frame = cap.read()
                if not ok and frame_count > 1:
                    cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, frame_count - 2))
                    ok, frame = cap.read()
                cap.release()
                if ok and frame is not None:
                    frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    return self._tensor_from_rgb_frame(frame)
        except Exception:
            pass

        try:
            import imageio.v3 as iio

            last = None
            for frm in iio.imiter(video_path):
                last = frm
            if last is not None:
                return self._tensor_from_rgb_frame(last)
        except Exception:
            pass

        return None

    def _select_scene_image(
        self,
        PROJECT_CONFIG: Dict[str, Any],
        shot_index: int,
        hard_cut: bool,
        reference_image: Any,
        width: int,
        height: int,
    ) -> Tuple[torch.Tensor, str]:
        ref_img = self._normalize_reference_image(reference_image)

        if shot_index <= 0:
            if ref_img is not None:
                return self._fit_image_to_resolution(
                    ref_img, width, height
                ), "reference:first_shot"
            return self._build_blank_image(width, height), "blank:first_shot"

        if hard_cut:
            if ref_img is not None:
                return self._fit_image_to_resolution(
                    ref_img, width, height
                ), "reference:hard_cut"
            return self._build_blank_image(width, height), "blank:hard_cut"

        for path in self._candidate_previous_video_paths(PROJECT_CONFIG, shot_index):
            frame = self._load_last_frame_from_video(path)
            if frame is not None:
                return self._fit_image_to_resolution(
                    frame, width, height
                ), f"previous_last_frame:{path}"

        if ref_img is not None:
            return self._fit_image_to_resolution(
                ref_img, width, height
            ), "reference:fallback_no_prev_frame"
        return self._build_blank_image(width, height), "blank:fallback_no_prev_frame"

    def execute(
        self,
        SHOT_LIST: Dict[str, Any],
        TIMING_MAP: Dict[str, Any],
        shot_index: int,
        PROJECT_CONFIG: Dict[str, Any],
        reference_image: Any = None,
    ) -> Tuple[str, int, int, int, int, int, float, Dict[str, Any], torch.Tensor]:

        shot_data = SHOT_LIST.get("data", [])
        timing_data = TIMING_MAP.get("data", [])
        try:
            effective_shot_index = int(shot_index)
        except Exception:
            effective_shot_index = 0

        active_shot, shot_source = self._find_entry(shot_data, effective_shot_index)
        if isinstance(active_shot, dict):
            prompt = str(active_shot.get("positive", "") or "").strip()
            seed = self._to_int(active_shot.get("seed", 42), 42)
        else:
            prompt = ""
            seed = 42
        if not prompt:
            prompt = "cinematic music video"

        active_timing, timing_source = self._find_entry(
            timing_data, effective_shot_index
        )
        if isinstance(active_timing, dict):
            num_frames = self._to_int(
                active_timing.get("num_frames", active_timing.get("frames", 24)), 24
            )
            audio = self._normalize_audio(
                active_timing.get("audio_dict", active_timing.get("audio"))
            )
        else:
            num_frames = 24
            audio = self._normalize_audio(None)
        if num_frames < 1:
            num_frames = 1

        width = self._to_int(PROJECT_CONFIG.get("width", 854), 854)
        height = self._to_int(PROJECT_CONFIG.get("height", 480), 480)
        steps = self._to_int(PROJECT_CONFIG.get("steps", 6), 6)
        cfg = self._to_float(PROJECT_CONFIG.get("cfg", 1.5), 1.5)

        hard_cut = self._is_hard_cut(active_shot)
        scene_image, image_source = self._select_scene_image(
            PROJECT_CONFIG=PROJECT_CONFIG,
            shot_index=effective_shot_index,
            hard_cut=hard_cut,
            reference_image=reference_image,
            width=width,
            height=height,
        )

        if shot_source != "index" or timing_source != "index":
            print(
                f"[PGFX_FilmShotConfigExtractor] scene={effective_shot_index} "
                f"lookup fallback used (shot={shot_source}, timing={timing_source})"
            )
        print(
            f"[PGFX_FilmShotConfigExtractor] scene={effective_shot_index} "
            f"hard_cut={hard_cut} image_source={image_source}"
        )

        return (prompt, seed, num_frames, width, height, steps, cfg, audio, scene_image)


class PGFX_FilmAudioSegmenter:
    """
    PGFX Film - Audio Segmenter
    Extracts the audio segment for a specific shot from the TIMING_MAP.
    """
    DESCRIPTION = get_node_description("PGFX_FilmAudioSegmenter")

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "TIMING_MAP": ("DICT",),
                "shot_index": ("INT", {"default": 0, "min": 0, "max": 999}),
            }
        }

    RETURN_TYPES = ("AUDIO",)
    RETURN_NAMES = ("AUDIO",)

    FUNCTION = "execute"
    CATEGORY = "☠️PGFX /Film"

    def execute(
        self, TIMING_MAP: Dict[str, Any], shot_index: int
    ) -> Tuple[Dict[str, Any]]:
        timing_data = TIMING_MAP.get("data", [])

        active_timing = next(
            (t for t in timing_data if t.get("index") == shot_index), None
        )

        if active_timing is None:
            return ({"waveform": torch.zeros((1, 1, 16000)), "sample_rate": 16000},)

        audio = active_timing.get("audio_dict")
        if audio is None:
            return ({"waveform": torch.zeros((1, 1, 16000)), "sample_rate": 16000},)
        return (audio,)


class PGFX_FilmAutoShotIndex:
    """
    PGFX Film - Auto Shot Index
    Synchronizes with the PGFX Queue Manager to provide the current active shot index.
    """
    DESCRIPTION = get_node_description("PGFX_FilmAutoShotIndex")

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "PROJECT_CONFIG": ("DICT",),
            },
            "optional": {
                "manual_override": ("INT", {"default": -1, "min": -1}),
            },
        }

    RETURN_TYPES = ("INT", "INT", "BOOLEAN")
    RETURN_NAMES = ("shot_index", "total_shots", "is_complete")

    FUNCTION = "execute"
    CATEGORY = "☠️PGFX /Film"

    def execute(
        self, PROJECT_CONFIG: Dict[str, Any], manual_override: int = -1
    ) -> Tuple[int, int, bool]:
        if manual_override != -1:
            return (manual_override, 1, False)

        render_plan = PROJECT_CONFIG.get("render_plan", {})
        shot_index = render_plan.get("active_job_index", 0)
        total_shots = render_plan.get("total_jobs", 1)

        is_complete = shot_index >= (total_shots - 1)

        return (shot_index, total_shots, is_complete)


NODE_CLASS_MAPPINGS = {
    "PGFX_FilmProjectController": PGFX_FilmProjectController,
    "PGFX_FilmCharacterRegistry": PGFX_FilmCharacterRegistry,
    "PGFX_FilmShotArchitect": PGFX_FilmShotArchitect,
    "PGFX_FilmSaveShotVideo": PGFX_FilmSaveShotVideo,
    "PGFX_FilmAudioLoader": PGFX_FilmAudioLoader,
    "PGFX_FilmAssembler": PGFX_FilmAssembler,
    "PGFX_FilmRenderProject": PGFX_FilmRenderProject,
    "PGFX_FilmShotConfigExtractor": PGFX_FilmShotConfigExtractor,
    "PGFX_FilmAudioSegmenter": PGFX_FilmAudioSegmenter,
    "PGFX_FilmAutoShotIndex": PGFX_FilmAutoShotIndex,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "PGFX_FilmProjectController": "???? Legacy \uD83C\uDFAC Film Project Controller",
    "PGFX_FilmCharacterRegistry": "???? Legacy \uD83C\uDFAC Film Character Registry",
    "PGFX_FilmShotArchitect": "???? Legacy \uD83C\uDFAC Film Shot Architect",
    "PGFX_FilmSaveShotVideo": "???? Legacy \uD83C\uDFAC Film Save Shot Video",
    "PGFX_FilmAudioLoader": "???? Legacy \uD83C\uDFAC Film Audio Loader",
    "PGFX_FilmAssembler": "???? Legacy \uD83C\uDFAC Film Assembler",
    "PGFX_FilmRenderProject": "???? Legacy \uD83C\uDFAC Film Render Project",
    "PGFX_FilmShotConfigExtractor": "???? Legacy \uD83C\uDFAC Film Shot Config Extractor",
    "PGFX_FilmAudioSegmenter": "???? Legacy \uD83C\uDFAC Film Audio Segmenter",
    "PGFX_FilmAutoShotIndex": "???? Legacy \uD83C\uDFAC Film Auto Shot Index",
}
