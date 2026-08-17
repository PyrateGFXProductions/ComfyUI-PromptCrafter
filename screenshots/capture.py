"""Capture screenshots of ComfyUI nodes for README."""
import time, os
from playwright.sync_api import sync_playwright

SCREENSHOTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)))
os.makedirs(SCREENSHOTS_DIR, exist_ok=True)

# (type_name, filename)
NODES = [
    ("PGFX_LogoDesignerStudio",           "logo_designer_studio.png"),
    ("PGFX_VisualFolderLoader",           "visual_folder_browser.png"),
    ("PromptCrafter_MiniMaxMusic3Creator", "minimax_music3_creator.png"),
    ("PromptCrafter_QnA",                 "qna_advanced.png"),
    ("PromptCrafter_MiniMaxMusic3APIConnector", "minimax_music3_api_connector.png"),
    ("PGFX_ComfyGuard_Shield",            "comfyguard.png"),
    ("BatchPromptProcessor",              "batch_processor.png"),
    ("KeyframePromptScheduler",           "keyframe_scheduler.png"),
    ("PromptCrafter_Captioner",           "image_captioner.png"),
    ("PGFX_UniversalSwitchBox",           "switch_box.png"),
    ("PromptCrafter_VisualCreator",       "visual_creator.png"),
    ("PromptCrafter_LyricsCreator",       "lyrics_creator.png"),
]

ADD_NODE_JS = """(typeName) => {
    try {
        const node = LiteGraph.createNode(typeName);
        if (!node) return 'createNode returned null for ' + typeName;
        node.pos = [50, 50];
        app.graph.add(node);
        app.canvas.setDirty(true, true);
        return 'ok';
    } catch(e) {
        return 'error: ' + e.message;
    }
}"""

FIT_VIEW_JS = """() => {
    const nodes = app.graph._nodes;
    if (!nodes || nodes.length === 0) return;
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    for (const n of nodes) {
        const w = n.size ? n.size[0] : 200;
        const h = n.size ? n.size[1] : 100;
        minX = Math.min(minX, n.pos[0]);
        minY = Math.min(minY, n.pos[1]);
        maxX = Math.max(maxX, n.pos[0] + w);
        maxY = Math.max(maxY, n.pos[1] + h);
    }
    const pad = 80;
    minX -= pad; minY -= pad; maxX += pad; maxY += pad;
    const bw = maxX - minX;
    const bh = maxY - minY;
    const cw = app.canvas.canvas.width;
    const ch = app.canvas.canvas.height;
    const scale = Math.min(cw / bw, ch / bh, 1.2);
    const cx = (minX + maxX) / 2;
    const cy = (minY + maxY) / 2;
    app.canvas.ds.changeScale(scale, [cw / 2, ch / 2]);
    app.canvas.ds.offset[0] = cw / 2 - cx * scale;
    app.canvas.ds.offset[1] = ch / 2 - cy * scale;
    app.canvas.setDirty(true, true);
}"""

def main():
    print("=== ComfyUI Node Screenshot Capture ===\n")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1920, "height": 1080})
        page.goto("http://127.0.0.1:8188", wait_until="networkidle", timeout=30000)
        time.sleep(4)
        page.wait_for_function(
            "typeof LiteGraph !== 'undefined' && typeof app !== 'undefined' && app.canvas",
            timeout=15000,
        )
        print("ComfyUI ready.\n")

        for type_name, filename in NODES:
            print(f"Capturing: {type_name}")
            # Clear graph
            page.evaluate("app.graph.clear()")
            time.sleep(0.3)

            # Add node
            result = page.evaluate(ADD_NODE_JS, type_name)
            if result != "ok":
                print(f"  SKIP: {result}\n")
                continue
            time.sleep(1)

            # Fit view
            page.evaluate(FIT_VIEW_JS)
            time.sleep(0.8)

            # Screenshot the canvas element
            filepath = os.path.join(SCREENSHOTS_DIR, filename)
            canvas_el = page.query_selector("canvas")
            if canvas_el:
                canvas_el.screenshot(path=filepath)
            else:
                page.screenshot(path=filepath)

            size = os.path.getsize(filepath)
            print(f"  -> {filename} ({size:,} bytes)\n")

        browser.close()
        print("=== Done ===")

if __name__ == "__main__":
    main()
