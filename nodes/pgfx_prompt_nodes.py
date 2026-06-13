try:
    from comfy_api.latest import io as v3_io
    V3_AVAILABLE = True
except ImportError:
    V3_AVAILABLE = False


class BatchPromptProcessor:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "prepend_text": ("STRING", {"multiline": True, "default": ""}),
                "prompts": ("STRING", {"multiline": True}),
                "append_text": ("STRING", {"multiline": True, "default": ""}),
                "batch_size": ("INT", {"default": 1, "min": 1, "max": 1000}),
                "start_index": ("INT", {"default": 0, "min": 0}),
            }
        }

    RETURN_TYPES = ("STRING",)
    OUTPUT_IS_LIST = (True,)
    FUNCTION = "process_batch"
    CATEGORY = "☠️PGFX /Text"

    def process_batch(self, prepend_text, prompts, append_text, batch_size, start_index):
        prepend_text = prepend_text.strip()
        prompt_lines = [line.strip() for line in prompts.split("\n") if line.strip()]
        append_text = append_text.strip()
        
        if not prompt_lines:
            return ([""],)
        
        num_prompts = len(prompt_lines)
        results = []
        
        for i in range(batch_size):
            index = (start_index + i) % num_prompts
            selected_prompt = prompt_lines[index]
            
            if prepend_text:
                selected_prompt = prepend_text + " " + selected_prompt
            if append_text:
                selected_prompt = selected_prompt + " " + append_text
                
            results.append(selected_prompt)
        
        return (results,)

class KeyframePromptScheduler:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "keyframe_prompts": ("STRING", {"multiline": True, "default": '{"0": "prompt 1",\n"10": "prompt 2",\n"20": "prompt 3"}'}),
                "frame_number": ("INT", {"default": 0, "min": 0}),
                "prepend_text": ("STRING", {"multiline": True, "default": ""}),
                "append_text": ("STRING", {"multiline": True, "default": ""}),
            }
        }

    RETURN_TYPES = ("STRING",)
    FUNCTION = "get_prompt"
    CATEGORY = "☠️PGFX /Text"

    def get_prompt(self, keyframe_prompts, frame_number, prepend_text, append_text):
        import json
        
        prepend_text = prepend_text.strip()
        append_text = append_text.strip()
        
        try:
            # Parse the keyframe dictionary
            keyframes = json.loads(keyframe_prompts)
            # Convert string keys to integers
            keyframes = {int(k): v for k, v in keyframes.items()}
            
            # Find the active keyframe (latest frame <= current frame)
            active_frame = max([k for k in keyframes.keys() if k <= frame_number], default=0)
            selected_prompt = keyframes.get(active_frame, "")
            
        except:
            # Fallback to simple parsing if JSON fails
            lines = keyframe_prompts.strip().split('\n')
            keyframes = {}
            for line in lines:
                if ':' in line:
                    try:
                        frame, prompt = line.split(':', 1)
                        keyframes[int(frame.strip())] = prompt.strip()
                    except:
                        continue
            
            if keyframes:
                active_frame = max([k for k in keyframes.keys() if k <= frame_number], default=0)
                selected_prompt = keyframes.get(active_frame, "")
            else:
                selected_prompt = keyframe_prompts  # Fallback to raw text
        
        # Apply prepend/append
        if prepend_text:
            selected_prompt = prepend_text + " " + selected_prompt
        if append_text:
            selected_prompt = selected_prompt + " " + append_text
            
        return (selected_prompt.strip(),)

if V3_AVAILABLE:
    class BatchPromptProcessorV3(v3_io.ComfyNode):
        @classmethod
        def define_schema(cls):
            return v3_io.Schema(
                node_id="BatchPromptProcessorV3",
                display_name="🧰 Batch Prompt Processor (V3)",
                category="☠️PGFX /Text",
                description="Processes prompts in batches with prepend/append text.",
                inputs=[
                    v3_io.String.Input("prepend_text", multiline=True, default=""),
                    v3_io.String.Input("prompts", multiline=True),
                    v3_io.String.Input("append_text", multiline=True, default=""),
                    v3_io.Int.Input("batch_size", default=1, min=1, max=1000),
                    v3_io.Int.Input("start_index", default=0, min=0),
                ],
                outputs=[
                    v3_io.String.Output(display_name="prompts", is_output_list=True),
                ],
            )

        @classmethod
        def execute(cls, prepend_text, prompts, append_text, batch_size, start_index):
            node = BatchPromptProcessor()
            result = node.process_batch(prepend_text, prompts, append_text, batch_size, start_index)
            return v3_io.NodeOutput(*result)

    class KeyframePromptSchedulerV3(v3_io.ComfyNode):
        @classmethod
        def define_schema(cls):
            return v3_io.Schema(
                node_id="KeyframePromptSchedulerV3",
                display_name="⏱️ Keyframe Prompt Scheduler (V3)",
                category="☠️PGFX /Text",
                description="Schedules prompts based on keyframe timing.",
                inputs=[
                    v3_io.String.Input("keyframe_prompts", multiline=True, default='{"0": "prompt 1",\n"10": "prompt 2",\n"20": "prompt 3"}'),
                    v3_io.Int.Input("frame_number", default=0, min=0),
                    v3_io.String.Input("prepend_text", multiline=True, default=""),
                    v3_io.String.Input("append_text", multiline=True, default=""),
                ],
                outputs=[
                    v3_io.String.Output(display_name="prompt"),
                ],
            )

        @classmethod
        def execute(cls, keyframe_prompts, frame_number, prepend_text, append_text):
            node = KeyframePromptScheduler()
            result = node.get_prompt(keyframe_prompts, frame_number, prepend_text, append_text)
            return v3_io.NodeOutput(*result)

NODE_CLASS_MAPPINGS = {
    "BatchPromptProcessor": BatchPromptProcessor,
    "KeyframePromptScheduler": KeyframePromptScheduler,
}
if V3_AVAILABLE:
    NODE_CLASS_MAPPINGS["BatchPromptProcessorV3"] = BatchPromptProcessorV3
    NODE_CLASS_MAPPINGS["KeyframePromptSchedulerV3"] = KeyframePromptSchedulerV3

NODE_DISPLAY_NAME_MAPPINGS = {
    "BatchPromptProcessor": "🧰 Batch Prompt Processor",
    "KeyframePromptScheduler": "⏱️ Keyframe Prompt Scheduler",}