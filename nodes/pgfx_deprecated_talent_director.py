class PromptCrafter_TalentDirector:
    """Core talent director that drives intelligent prompt creation across all creator nodes."""

    # Professional crew expertise database
    CREW_EXPERTISE = {
        "Creative Director": {
            "focus": "overall creative vision and artistic direction",
            "enhancements": ["narrative coherence", "thematic consistency", "artistic excellence"],
            "keywords": ["visionary", "auteur", "cohesive storytelling", "artistic masterpiece"]
        },
        "Director of Photography": {
            "focus": "cinematography, lighting, and visual composition",
            "enhancements": ["professional lighting", "cinematic framing", "visual composition"],
            "keywords": ["cinematographic", "dramatic lighting", "professional framing", "visual excellence"]
        },
        "Production Designer": {
            "focus": "set design, props, and environmental storytelling",
            "enhancements": ["detailed environments", "authentic props", "environmental narrative"],
            "keywords": ["production design", "set decoration", "environmental storytelling", "authentic detail"]
        },
        "Story Consultant": {
            "focus": "narrative structure and character development",
            "enhancements": ["character consistency", "narrative flow", "story arc development"],
            "keywords": ["character-driven", "narrative structure", "storytelling excellence", "character development"]
        },
        "Technical Director": {
            "focus": "AI model optimization and technical implementation",
            "enhancements": ["model compatibility", "technical precision", "quality optimization"],
            "keywords": ["technical excellence", "model optimized", "high quality output", "precision rendering"]
        }
    }

    # Cinematic intelligence system
    CINEMATIC_KNOWLEDGE = {
        "shot_types": {
            "Establishing": {"description": "Wide view showing environment and context", "usage": "scene_opening"},
            "Wide": {"description": "Full body view with environment", "usage": "action_sequences"},
            "Medium": {"description": "Waist-up view focusing on actions", "usage": "dialogue"},
            "Close-up": {"description": "Face-focused emotional capture", "usage": "emotional_moments"},
            "Extreme Close-up": {"description": "Detail emphasis", "usage": "symbolic_elements"}
        },
        "camera_movements": {
            "Static": {"mood": "stable, focused", "energy": "low"},
            "Pan": {"mood": "revealing, exploratory", "energy": "medium"},
            "Tilt": {"mood": "height perspective", "energy": "medium"},
            "Dolly": {"mood": "intimate, dramatic", "energy": "high"},
            "Tracking": {"mood": "following, dynamic", "energy": "high"},
            "Crane": {"mood": "epic, overview", "energy": "high"}
        },
        "lighting_styles": {
            "Three-Point": {"quality": "professional", "mood": "balanced"},
            "High-Key": {"quality": "bright", "mood": "positive"},
            "Low-Key": {"quality": "dramatic", "mood": "intense"},
            "Natural": {"quality": "authentic", "mood": "realistic"}
        }
    }

    # Model optimization profiles
    MODEL_PROFILES = {
        "Wan 2.2": {
            "format": "Cinematic video scene: [STYLE] [COMPOSITION] [ACTION] [MOOD]",
            "strengths": ["video motion", "cinematic quality", "narrative flow"],
            "enhancements": ["motion physics", "camera work", "temporal coherence"]
        },
        "OVI": {
            "format": "Speaking character scene: [CHARACTER] [DIALOGUE] [SETTING] [AUDIO]",
            "strengths": ["speech generation", "audio sync", "character focus"],
            "enhancements": ["dialogue clarity", "voice description", "audio quality"]
        },
        "Generic Video": {
            "format": "High-quality video: [SUBJECT] [ACTION] [SETTING] [QUALITY]",
            "strengths": ["general video", "motion clarity", "basic composition"],
            "enhancements": ["motion description", "scene clarity", "visual quality"]
        }
    }

    @classmethod
    def get_crew_expertise(cls, role):
        """Get expertise for a specific crew role."""
        return cls.CREW_EXPERTISE.get(role, cls.CREW_EXPERTISE["Creative Director"])

    @classmethod
    def get_model_profile(cls, model_name):
        """Get optimization profile for a specific AI model."""
        return cls.MODEL_PROFILES.get(model_name, cls.MODEL_PROFILES["Generic Video"])

    @classmethod
    def analyze_content_for_direction(cls, content, content_type="text"):
        """Analyze content to determine optimal creative direction."""
        analysis = {
            "emotional_tone": cls._detect_emotional_tone(content),
            "complexity_level": cls._assess_complexity(content),
            "narrative_elements": cls._identify_narrative_elements(content),
            "visual_opportunities": cls._find_visual_opportunities(content),
            "recommended_approach": cls._recommend_creative_approach(content, content_type)
        }
        return analysis

    @classmethod
    def _detect_emotional_tone(cls, content):
        """Detect emotional tone from content."""
        if not content:
            return "neutral"
        
        content_lower = content.lower()
        emotional_indicators = {
            "joy": ["happy", "joy", "celebrate", "love", "wonder", "beautiful"],
            "sadness": ["sad", "cry", "tears", "alone", "miss", "lost"],
            "anger": ["hate", "fight", "war", "rage", "mad", "furious"],
            "fear": ["scared", "afraid", "dark", "night", "danger", "threat"],
            "surprise": ["shock", "amazing", "incredible", "unexpected", "wow"],
            "neutral": ["the", "and", "of", "is", "are", "was", "were"]
        }
        
        emotion_scores = {emotion: sum(1 for keyword in keywords if keyword in content_lower) for emotion, keywords in emotional_indicators.items()}
        
        if max(emotion_scores.values()) > 0:
            return max(emotion_scores, key=emotion_scores.get)
        return "neutral"

    @classmethod
    def _assess_complexity(cls, content):
        """Assess content complexity level."""
        if not content:
            return "simple"
        
        word_count = len(content.split())
        sentence_count = len([s for s in content.split('.') if s.strip()])
        unique_words = len(set(content.lower().split()))
        
        avg_words_per_sentence = word_count / max(1, sentence_count)
        lexical_diversity = unique_words / max(1, word_count)
        
        if word_count > 200 or avg_words_per_sentence > 20 or lexical_diversity > 0.7:
            return "complex"
        elif word_count > 100 or avg_words_per_sentence > 15:
            return "moderate"
        else:
            return "simple"

    @classmethod
    def _identify_narrative_elements(cls, content):
        """Identify narrative elements in content."""
        if not content:
            return []
        
        elements = []
        content_lower = content.lower()
        
        if any(word in content_lower for word in ["person", "man", "woman", "child", "character"]):
            elements.append("character_focus")
        if any(word in content_lower for word in ["run", "jump", "move", "walk", "dance"]):
            elements.append("action_sequence")
        if any(word in content_lower for word in ["room", "house", "street", "forest", "city"]):
            elements.append("environmental_setting")
        if any(word in content_lower for word in ["feel", "emotion", "mood", "expression"]):
            elements.append("emotional_content")
            
        return elements

    @classmethod
    def _find_visual_opportunities(cls, content):
        """Find visual storytelling opportunities."""
        if not content:
            return []
        
        opportunities = []
        content_lower = content.lower()
        
        if any(word in content_lower for word in ["light", "dark", "shadow", "sun", "moon"]):
            opportunities.append("lighting_drama")
        if any(word in content_lower for word in ["red", "blue", "green", "color", "golden", "silver"]):
            opportunities.append("color_palette")
        if any(word in content_lower for word in ["move", "flow", "dance", "spin", "fly"]):
            opportunities.append("motion_dynamics")
        if any(word in content_lower for word in ["rough", "smooth", "soft", "hard", "texture"]):
            opportunities.append("textural_detail")
            
        return opportunities

    @classmethod
    def _recommend_creative_approach(cls, content, content_type):
        """Recommend optimal creative approach based on content."""
        complexity = cls._assess_complexity(content)
        emotional_tone = cls._detect_emotional_tone(content)
        elements = cls._identify_narrative_elements(content)
        
        recommendations = {
            "primary_crew": "Creative Director",
            "cinematic_style": "Narrative-Driven",
            "detail_level": "Detailed" if complexity == "complex" else "Standard",
            "emotional_approach": emotional_tone,
            "technical_focus": "General" if content_type == "text" else "Video-Specific"
        }
        
        if "character_focus" in elements:
            recommendations["primary_crew"] = "Story Consultant"
        if "action_sequence" in elements:
            recommendations["primary_crew"] = "Director of Photography"
        if "environmental_setting" in elements:
            recommendations["primary_crew"] = "Production Designer"
            
        return recommendations

    @classmethod
    def enhance_prompt_with_expertise(cls, prompt, analysis, crew_role="Creative Director", 
                                    target_model="Generic Video", preserve_original=True):
        """Enhance prompt with professional crew expertise."""
        if not prompt:
            return prompt
            
        expertise = cls.get_crew_expertise(crew_role)
        model_profile = cls.get_model_profile(target_model)
        
        enhancement_elements = []
        if expertise.get("keywords"):
            enhancement_elements.extend(expertise["keywords"])
        if analysis.get("emotional_tone") and analysis["emotional_tone"] != "neutral":
            enhancement_elements.append(f"{analysis['emotional_tone']}-driven")
        if analysis.get("complexity_level"):
            enhancement_elements.append(f"{analysis['complexity_level']} detail")
        if model_profile.get("enhancements"):
            enhancement_elements.extend(model_profile["enhancements"])
            
        if "Wan" in target_model:
            formatted_prompt = f"Cinematic video scene: {prompt}"
        elif "OVI" in target_model:
            formatted_prompt = f"Speaking character scene: {prompt}" if "saying" in prompt.lower() or "<S>" in prompt else f"Narrative scene: {prompt}"
        else:
            formatted_prompt = prompt
            
        if enhancement_elements:
            enhancement_string = ", ".join(set(enhancement_elements))
            return f"[{enhancement_string}] {formatted_prompt}" if preserve_original else f"{formatted_prompt}, {enhancement_string}"
        
        return formatted_prompt