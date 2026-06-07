"""Generate PGFX_Studio_MusicVideo_Master.json — Complete pipeline."""
import json, os

COL = {
    "notes": -180, "concept": 0, "audio": 420, "script": 840,
    "creative": 1260, "production": 1680, "ltx": 2100, "assembly": 2680,
}
ROW = {"t": 0, "r0": 100, "r1": 280, "r2": 460, "r3": 640, "r4": 820,
       "r5": 1000, "r6": 1180, "r7": 1360, "r8": 1540, "r9": 1720}

N = [0]; L = [0]
def nid(): N[0] += 1; return N[0]
def lid(): L[0] += 1; return L[0]

class ND:
    def __init__(self, type, x, y, title=None, widgets=None, size=None):
        self.id = nid()
        self.type = type
        self.pos = [x, y]
        self.title = title
        self.widgets = widgets or []
        self.size = size or [320, 100]
        self.inputs = []; self.outputs = []
        self.output_node = False

    def inp(self, name, typ):
        self.inputs.append({"name": name, "type": typ, "link": None})
        return len(self.inputs) - 1

    def out(self, name, typ):
        self.outputs.append({"name": name, "type": typ, "links": []})
        return len(self.outputs) - 1

def wire(src, s_slot, dst, d_slot, typ):
    lid_val = lid()
    src.outputs[s_slot]["links"].append(lid_val)
    dst.inputs[d_slot]["link"] = lid_val
    return [lid_val, src.id, s_slot, dst.id, d_slot, typ]

def note(text, x, y, w=700, h=70):
    n = ND("Note", x, y, widgets=[text], size=[w, h])
    return n

# ============================================================
# NOTES
# ============================================================
notes_top = note(
    "☠️ PGFX STUDIO MASTER MUSIC VIDEO PIPELINE\n"
    "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    "AUDIO+LYRICS+CONCEPT → Screenwriter → CreativeDirector → Director → Cinematographer → LTX-2.3 Video → Editor → PostMaster\n\n"
    "USAGE: 1) Fill concept inputs + set LoadAudio path.  2) Queue Prompt → generates Scene 0.  "
    "3) Re-queue N times (Auto-Increment selects next scene each time).  "
    "4) Last queue triggers PostMaster auto-stitch → FINAL_MUSIC_VIDEO.mp4",
    COL["notes"], ROW["t"], w=880, h=90)

n_setup = note("① CONCEPT & AUDIO INPUT", COL["notes"], ROW["r0"]-10, w=300, h=40)
n_apip = note("② AUDIO → SCREENPLAY", COL["audio"], ROW["r0"]-10, w=300, h=40)
n_cdir = note("③ CREATIVE DIRECTION", COL["creative"], ROW["r0"]-10, w=300, h=40)
n_prod = note("④ PRODUCTION (per-scene)", COL["production"], ROW["r0"]-10, w=300, h=40)
n_vid  = note("⑤ LTX-2.3 VIDEO GENERATION", COL["ltx"], ROW["r0"]-10, w=300, h=40)
n_asmb = note("⑥ SAVE & STITCH", COL["assembly"], ROW["r0"]-10, w=300, h=40)
n_how = note(
    "HOW THIS PIPELINE WORKS:\n"
    "• Phase 1 (first queue): The Studio chain runs — Screenwriter transcribes audio, CreativeDirector "
    "analyzes lyrics+concept, Director builds Shot List. These nodes cache their results, so they "
    "only run their LLM calls ONCE per project.\n"
    "• Phase 2 (each queue, N times): Cinematographer auto-increments to the next scene, feeding "
    "its prompt + frame count + audio chunk into the LTX video pipeline.\n"
    "• Phase 3 (last queue): Editor saves the clip. PostMaster detects remaining_scenes=0 and "
    "stitches all clips + master audio → final video.",
    COL["notes"], ROW["r2"]+60, w=1800, h=120)

# ============================================================
# COLUMN 1: CONCEPT INPUT
# ============================================================
projctx = ND("PGFX_Studio_ProjectContext", COL["concept"], ROW["r1"],
    title="📋 Project Context", size=[320, 220],
    widgets=["Cyberpunk music video", "Synthwave artist", "Synthwave", "2087",
             "Neon-drenched cyberpunk cityscape, rain-slicked streets, holographic billboards"])
projctx.out("PROJECT_CONTEXT", "STRING")

stylist = ND("PGFX_Studio_Stylist", COL["concept"], ROW["r2"],
    title="🎨 Stylist", size=[320, 180],
    widgets=["Neon/Cyber", "leather jacket, cybernetic implants, neon hair", "Neon/Cyber",
             "dystopian cyberpunk, holo-displays", 1.0])
stylist.out("visual_identity_brief", "STRING")
stylist.out("lora_conditioning_text", "STRING")

producer = ND("PGFX_Studio_Producer", COL["concept"], ROW["r3"],
    title="🎬 Producer", size=[320, 200],
    widgets=["Cyberpunk_Music_Video", "1920x1080", 24, "PromptCrafter_Studio"])
producer.out("PROJECT_CONFIG", "DICT")

# ============================================================
# COLUMN 2: AUDIO INPUT
# ============================================================
load_audio = ND("LoadAudio", COL["audio"], ROW["r1"], size=[300, 80], widgets=["input/MySong.wav"])
load_audio.out("AUDIO", "AUDIO")

soundeng = ND("PGFX_Studio_SoundEngineer", COL["audio"], ROW["r2"],
    title="🔊 Sound Engineer", size=[320, 220],
    widgets=["None (Manual Input)", 4.0, True, 0.5, True])
s_aud = soundeng.inp("audio", "AUDIO")
s_cfg = soundeng.inp("PROJECT_CONFIG", "DICT")
soundeng.out("AUDIO", "AUDIO")
soundeng.out("TIMING_MAP", "DICT")
soundeng.out("SCENE_COUNT", "INT")

# ============================================================
# COLUMN 3: SCREENWRITER
# ============================================================
swriter = ND("PGFX_Studio_Screenwriter", COL["script"], ROW["r1"],
    title="📝 Screenwriter", size=[320, 260],
    widgets=["None (Manual Input)", "large-v3", "", False])
sw_t = swriter.inp("TIMING_MAP", "DICT")
sw_a = swriter.inp("audio", "AUDIO")
swriter.out("SCREENPLAY", "DICT")
swriter.out("AUDIO_META", "DICT")

# ============================================================
# COLUMN 4: CREATIVE DIRECTOR + DIRECTOR
# ============================================================
cdirector = ND("PGFX_Studio_CreativeDirector", COL["creative"], ROW["r1"],
    title="🎯 Creative Director", size=[320, 260],
    widgets=["", True, -1, False])
cd_sc = cdirector.inp("SCREENPLAY", "DICT")
cd_tm = cdirector.inp("TIMING_MAP", "DICT")
cd_pc = cdirector.inp("PROJECT_CONTEXT", "STRING")
cdirector.out("VISUAL_BRIEF", "DICT")
cdirector.out("creative_concept_log", "STRING")

director = ND("PGFX_Studio_Director", COL["creative"], ROW["r2"],
    title="🎬 Director", size=[320, 260],
    widgets=[True, False])
d_sc = director.inp("SCREENPLAY", "DICT")
d_vb = director.inp("VISUAL_BRIEF", "DICT")
director.out("SHOT_LIST", "DICT")
director.out("reasoning_log", "STRING")

# ============================================================
# COLUMN 5: CINEMATOGRAPHER + CLIP ENCODE
# ============================================================
camera = ND("PGFX_Studio_Cinematographer", COL["production"], ROW["r1"],
    title="🎥 Cinematographer (per-scene)", size=[320, 260],
    widgets=["Auto-Increment", 0])
c_sl = camera.inp("SHOT_LIST", "DICT")
c_tm = camera.inp("TIMING_MAP", "DICT")
c_cfg = camera.inp("PROJECT_CONFIG", "DICT")
camera.out("positive", "STRING")
camera.out("negative", "STRING")
camera.out("seed", "INT")
camera.out("audio_chunk", "AUDIO")
camera.out("num_frames", "INT")
camera.out("scene_index", "INT")
camera.out("remaining_scenes", "INT")

clip_pos = ND("CLIPTextEncode", COL["production"], ROW["r2"],
    title="CLIP Encode (positive)", size=[320, 100], widgets=[""])
cp_txt = clip_pos.inp("text", "STRING")
cp_clip = clip_pos.inp("clip", "CLIP")
clip_pos.out("CONDITIONING", "CONDITIONING")

clip_neg = ND("CLIPTextEncode", COL["production"], ROW["r3"],
    title="CLIP Encode (negative)", size=[320, 100], widgets=[""])
cn_txt = clip_neg.inp("text", "STRING")
cn_clip = clip_neg.inp("clip", "CLIP")
clip_neg.out("CONDITIONING", "CONDITIONING")

# ============================================================
# COLUMN 6: LTX-2.3 VIDEO PIPELINE
# ============================================================
loader_model = ND("UnetLoaderGGUF", COL["ltx"], ROW["r1"],
    title="🧠 LTX Model", size=[300, 100],
    widgets=["ltx-video-2b-distilled.safetensors"])
loader_model.out("MODEL", "MODEL")

loader_vae = ND("VAELoader", COL["ltx"], ROW["r2"], size=[300, 100],
    widgets=["ltx-video-2b-vae.safetensors"])
loader_vae.out("VAE", "VAE")

loader_clip = ND("LTXVGemmaCLIPModelLoader", COL["ltx"], ROW["r3"], size=[300, 100],
    widgets=["gemma-2-2b-it.safetensors"])
loader_clip.out("CLIP", "CLIP")

empty_ltx = ND("EmptyLTXVLatentVideo", COL["ltx"], ROW["r4"], size=[300, 150], widgets=[1, 1024, 576, 49])
empty_ltx.inp("width", "INT")
empty_ltx.inp("height", "INT")
empty_ltx.inp("length", "INT")
empty_ltx.inp("batch_size", "INT")
empty_ltx.out("LATENT", "LATENT")

model_sampling = ND("ModelSamplingLTXV", COL["ltx"], ROW["r5"], size=[300, 80], widgets=[])
ms_m = model_sampling.inp("model", "MODEL")
model_sampling.out("MODEL", "MODEL")

stg_node = ND("LTXVApplySTG", COL["ltx"], ROW["r6"], size=[300, 80], widgets=[])
stg_m = stg_node.inp("model", "MODEL")
stg_node.out("MODEL", "MODEL")

ltxv_sched = ND("LTXVScheduler", COL["ltx"], ROW["r4"]+180, size=[300, 100], widgets=[])
ls_l = ltxv_sched.inp("latents", "LATENT")
ltxv_sched.out("SIGMAS", "SIGMAS")

sampler_sel = ND("KSamplerSelect", COL["ltx"], ROW["r5"]+180, size=[300, 80], widgets=["euler"])
sampler_sel.out("SAMPLER", "SAMPLER")

noise = ND("RandomNoise", COL["ltx"], ROW["r6"]+180, size=[300, 80], widgets=[0, "fixed"])
noise.out("NOISE", "NOISE")

guider = ND("STGGuiderAdvanced", COL["ltx"], ROW["r7"], size=[300, 120], widgets=[1, 1.0, 0.0])
g_m = guider.inp("model", "MODEL")
g_pos = guider.inp("positive", "CONDITIONING")
g_neg = guider.inp("negative", "CONDITIONING")
guider.out("GUIDER", "GUIDER")

sampler = ND("PGFX_LTXVInContextSampler", COL["ltx"], ROW["r8"],
    title="🎞️ PGFX LTX Sampler", size=[320, 340], widgets=[])
s_model = sampler.inp("model", "MODEL")
s_vae = sampler.inp("vae", "VAE")
s_pos = sampler.inp("positive", "CONDITIONING")
s_neg = sampler.inp("negative", "CONDITIONING")
s_latent = sampler.inp("latent", "LATENT")
s_sigmas = sampler.inp("sigmas", "SIGMAS")
s_guider = sampler.inp("guider", "GUIDER")
s_sampler = sampler.inp("sampler", "SAMPLER")
s_noise = sampler.inp("noise", "NOISE")
sampler.out("LATENT", "LATENT")

vae_decode = ND("VAEDecode", COL["ltx"]+370, ROW["r8"], size=[300, 80], widgets=[])
vd_latent = vae_decode.inp("samples", "LATENT")
vd_vae = vae_decode.inp("vae", "VAE")
vae_decode.out("IMAGE", "IMAGE")

# ============================================================
# COLUMN 7: ASSEMBLY
# ============================================================
editor = ND("PGFX_Studio_Editor", COL["assembly"], ROW["r1"],
    title="✂️ Editor (saves clip)", size=[320, 220], widgets=[])
ed_cfg = editor.inp("PROJECT_CONFIG", "DICT")
ed_frm = editor.inp("video_frames", "IMAGE")
ed_si = editor.inp("scene_index", "INT")
ed_aud = editor.inp("audio_chunk", "AUDIO")
editor.out("clip_path", "STRING")
editor.output_node = True

vhs_out = ND("VHS_VideoCombine", COL["assembly"], ROW["r2"],
    title="📼 Preview Output", size=[320, 300],
    widgets=[24, 0, "PGFX_Scene_Preview", "video/h264-mp4", False])
vhs_img = vhs_out.inp("images", "IMAGE")
vhs_out.out("Filenames", "STRING")

postmaster = ND("PGFX_Studio_PostMaster", COL["assembly"], ROW["r3"],
    title="\U0001F3C1 PostMaster (stitch all)", size=[320, 260],
    widgets=[True, False])
pm_cfg = postmaster.inp("PROJECT_CONFIG", "DICT")        # slot 0
pm_aud = postmaster.inp("master_audio", "AUDIO")          # slot 1
pm_aut = postmaster.inp("auto_stitch_at_end", "BOOLEAN")  # slot 2 (widget)
pm_frc = postmaster.inp("force_render_now", "BOOLEAN")    # slot 3 (widget)
pm_rem = postmaster.inp("remaining_scenes", "INT")        # slot 4
pm_out = postmaster.inp("output_filename", "STRING")      # slot 5 (widget)
postmaster.out("final_file_path", "STRING")
postmaster.output_node = True

# ============================================================
# WIRING
# ============================================================
links = []

# Audio → SoundEngineer
links.append(wire(load_audio, 0, soundeng, s_aud, "AUDIO"))
links.append(wire(producer, 0, soundeng, s_cfg, "DICT"))

# SoundEngineer → Screenwriter
links.append(wire(soundeng, 1, swriter, sw_t, "DICT"))
links.append(wire(load_audio, 0, swriter, sw_a, "AUDIO"))

# Screenwriter → CreativeDirector
links.append(wire(swriter, 0, cdirector, cd_sc, "DICT"))
links.append(wire(soundeng, 1, cdirector, cd_tm, "DICT"))
# ProjectContext → CreativeDirector
links.append(wire(projctx, 0, cdirector, cd_pc, "STRING"))

# Screenwriter + CreativeDirector → Director
links.append(wire(swriter, 0, director, d_sc, "DICT"))
links.append(wire(cdirector, 0, director, d_vb, "DICT"))

# Director + SoundEngineer + Producer → Cinematographer
links.append(wire(director, 0, camera, c_sl, "DICT"))
links.append(wire(soundeng, 1, camera, c_tm, "DICT"))
links.append(wire(producer, 0, camera, c_cfg, "DICT"))

# Cinematographer → CLIP Encode
links.append(wire(camera, 0, clip_pos, cp_txt, "STRING"))
links.append(wire(camera, 1, clip_neg, cn_txt, "STRING"))

# Cinematographer → EmptyLTXLatentVideo (num_frames → length)
links.append(wire(camera, 4, empty_ltx, 2, "INT"))

# Cinematographer → Editor
links.append(wire(producer, 0, editor, ed_cfg, "DICT"))
links.append(wire(camera, 5, editor, ed_si, "INT"))
links.append(wire(camera, 3, editor, ed_aud, "AUDIO"))

# Cinematographer → PostMaster
links.append(wire(producer, 0, postmaster, pm_cfg, "DICT"))
links.append(wire(load_audio, 0, postmaster, pm_aud, "AUDIO"))
links.append(wire(camera, 6, postmaster, pm_rem, "INT"))

# CLIP → CLIPTextEncode
links.append(wire(loader_clip, 0, clip_pos, cp_clip, "CLIP"))
links.append(wire(loader_clip, 0, clip_neg, cn_clip, "CLIP"))

# Conditioning → Sampler
links.append(wire(clip_pos, 0, sampler, s_pos, "CONDITIONING"))
links.append(wire(clip_neg, 0, sampler, s_neg, "CONDITIONING"))

# Model pipeline → STG
links.append(wire(loader_model, 0, model_sampling, ms_m, "MODEL"))
links.append(wire(model_sampling, 0, stg_node, stg_m, "MODEL"))
links.append(wire(stg_node, 0, guider, g_m, "MODEL"))

# Conditioning → STG Guider
links.append(wire(clip_pos, 0, guider, g_pos, "CONDITIONING"))
links.append(wire(clip_neg, 0, guider, g_neg, "CONDITIONING"))

# Latent → Scheduler
links.append(wire(empty_ltx, 0, ltxv_sched, ls_l, "LATENT"))

# Sampler wiring
links.append(wire(stg_node, 0, sampler, s_model, "MODEL"))
links.append(wire(loader_vae, 0, sampler, s_vae, "VAE"))
links.append(wire(guider, 0, sampler, s_guider, "GUIDER"))
links.append(wire(empty_ltx, 0, sampler, s_latent, "LATENT"))
links.append(wire(ltxv_sched, 0, sampler, s_sigmas, "SIGMAS"))
links.append(wire(sampler_sel, 0, sampler, s_sampler, "SAMPLER"))
links.append(wire(noise, 0, sampler, s_noise, "NOISE"))

# Decode
links.append(wire(sampler, 0, vae_decode, vd_latent, "LATENT"))
links.append(wire(loader_vae, 0, vae_decode, vd_vae, "VAE"))

# Output
links.append(wire(vae_decode, 0, editor, ed_frm, "IMAGE"))
links.append(wire(vae_decode, 0, vhs_out, vhs_img, "IMAGE"))

# ============================================================
# BUILD JSON
# ============================================================
all_nodes = [
    notes_top, n_setup, n_apip, n_cdir, n_prod, n_vid, n_asmb, n_how,
    projctx, stylist, producer,
    load_audio, soundeng,
    swriter,
    cdirector, director,
    camera, clip_pos, clip_neg,
    loader_model, loader_vae, loader_clip, empty_ltx,
    model_sampling, stg_node, ltxv_sched, sampler_sel, noise, guider,
    sampler, vae_decode,
    editor, vhs_out, postmaster,
]

nodes_json = []
for nd in all_nodes:
    entry = {
        "id": nd.id,
        "type": nd.type,
        "pos": nd.pos,
        "size": nd.size,
        "flags": {},
        "order": nd.id,
        "mode": 0,
        "inputs": nd.inputs,
        "outputs": nd.outputs,
        "properties": {"Node name for S&R": nd.type},
        "widgets_values": nd.widgets,
    }
    if nd.title:
        entry["title"] = nd.title
    if nd.output_node:
        entry["isOutput"] = True
    nodes_json.append(entry)

workflow = {
    "last_node_id": N[0],
    "last_link_id": L[0],
    "nodes": nodes_json,
    "links": links,
    "groups": [],
    "config": {},
    "extra": {"ds": {"scale": 0.75, "offset": [0, 0]}},
    "version": 0.4,
}

filepath = os.path.join(os.path.dirname(__file__), "PGFX_Studio_MusicVideo_Master.json")
with open(filepath, "w") as f:
    json.dump(workflow, f, indent=2)
print(f"Written: {filepath}")
print(f"   Nodes: {len(nodes_json)}, Links: {len(links)}")
