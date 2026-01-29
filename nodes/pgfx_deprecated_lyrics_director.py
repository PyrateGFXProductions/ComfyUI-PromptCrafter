import json

class PromptCrafter_LyricsDirector:
    """A specialized talent director for creating prompts from lyrics."""

    def __init__(self, base_creator):
        self.base_creator = base_creator

    def _enhance_lyrics_schedule_with_talent_direction(self, schedule_json, lyrics_text, model, timed_segments):
        """Enhance lyrics schedule with talent direction and timing awareness."""
        try:
            schedule_data = json.loads(schedule_json)
            enhanced_schedule = {}
            
            emotional_arc = self._analyze_lyrics_emotional_progression(lyrics_text, timed_segments)
            
            for frame, prompt in schedule_data.items():
                if isinstance(prompt, str) and prompt.strip():
                    timing_context = self._get_timing_context_for_frame(int(frame), timed_segments)
                    
                    enhanced_prompt = self.base_creator._enhance_prompt_with_talent_direction(
                        prompt, lyrics_text, model
                    )
                    
                    if timing_context:
                        emotional_context = emotional_arc.get(int(frame), "neutral")
                        context_tags = f"[{timing_context['scene_type']}, {emotional_context} mood]"
                        enhanced_prompt = f"{context_tags} {enhanced_prompt}"
                    
                    enhanced_schedule[frame] = enhanced_prompt
                else:
                    enhanced_schedule[frame] = prompt
                    
            return json.dumps(enhanced_schedule, indent=4)
        except json.JSONDecodeError:
            return schedule_json

    def _analyze_lyrics_emotional_progression(self, lyrics_text, timed_segments):
        """Analyze emotional progression throughout the lyrics."""
        if not lyrics_text:
            return {}
        
        emotional_progression = {}
        lines = lyrics_text.split('\n')
        
        for i, line in enumerate(lines):
            if line.strip():
                analysis = self.base_creator._analyze_content_for_direction(line, "lyrics_line")
                emotional_tone = analysis.get("emotional_tone", "neutral")
                
                if timed_segments and i < len(timed_segments):
                    start_frame = int(timed_segments[i][0] * 16)
                    emotional_progression[start_frame] = emotional_tone
                else:
                    frame_number = i * 80
                    emotional_progression[frame_number] = emotional_tone
                    
        return emotional_progression

    def _get_timing_context_for_frame(self, frame_number, timed_segments):
        """This method would determine timing context like intro, verse, climax."""
        # This is a placeholder for the full implementation from your context.
        return {"scene_type": "verse", "position": "middle"}