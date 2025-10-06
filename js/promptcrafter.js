import { app } from "../../../scripts/app.js";

// =================================================================================
// START: SHARED CODE (From promptcrafter_not_working.js)
// This is the helper code for the Help Dialog feature.
// =================================================================================

const HELP_TEXT_CACHE = {};

async function getHelpText() {
    console.log("[PromptCrafter] getHelpText: Starting.");
    if (Object.keys(HELP_TEXT_CACHE).length > 0) {
        console.log("[PromptCrafter] getHelpText: Cache already populated, skipping.");
        return;
    }
    try {
        const response = await fetch('/extensions/ComfyUI-PromptCrafter/HELP.md');
        console.log(`[PromptCrafter] getHelpText: Fetch response status: ${response.status}`);
        if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
        const markdown = await response.text();
        const sections = markdown.split(/\n(?=##\s)/).filter(s => s.trim());
        sections.forEach(section => {
            const lines = section.split('\n');
            const headerMatch = lines[0].match(/##\s+`([^`]+)`/);
            if (headerMatch) {
                const comfyClass = headerMatch[1];
                const content = lines.slice(1).join('\n').replace(/`([^`]+)`/g, '<code>$1</code>').replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>').replace(/\n/g, '<br>');
                HELP_TEXT_CACHE[comfyClass] = content;
            }
        });
        console.log(`[PromptCrafter] getHelpText: Parsing complete. Cache contains ${Object.keys(HELP_TEXT_CACHE).length} keys.`);
    } catch (e) {
        console.error("[PromptCrafter] Failed to load or parse HELP.md:", e);
        HELP_TEXT_CACHE['error'] = 'Could not load help file. Please check the browser console for errors.';
    }
}

function showHelpDialog(node) {
    const comfyClass = node.comfyClass;
    let helpContent;

    const cacheKeys = Object.keys(HELP_TEXT_CACHE);
    const hasError = HELP_TEXT_CACHE['error'];

    if (HELP_TEXT_CACHE[comfyClass]) {
        helpContent = HELP_TEXT_CACHE[comfyClass];
    } else {
        helpContent = `
            <div style="font-family: monospace; text-align: left;">
                <p><strong>--- PROMPTCRAFTER DEBUG ---</strong></p>
                <p>Help content for '<code>${comfyClass}</code>' not found in cache.</p>
                <p><strong>Cache Status:</strong></p>
                <ul style="list-style-type: none; padding-left: 10px;">
                    <li>- Cache Keys: <strong>${cacheKeys.length}</strong></li>
                    <li>- Keys Found: <code>${cacheKeys.join(", ") || "None"}</code></li>
                    <li>- Error Flag: <code>${hasError ? HELP_TEXT_CACHE['error'] : "Not set"}</code></li>
                </ul>
                <p><strong>Next Steps:</strong></p>
                 <p>1. Open browser dev tools (F12).<br>2. Check the Console for red errors from "[PromptCrafter]".<br>3. Refresh the page (Ctrl+F5) and check again.</p>
            </div>
        `;
    }
    
    const dialog = document.createElement("div");
    dialog.className = "promptcrafter-help-dialog";
    dialog.innerHTML = `
        <div class="promptcrafter-help-content">
            <h2 style="margin-top: 0;">${node.title}</h2>
            <div>${helpContent}</div>
            <button class="promptcrafter-help-close-button">Close</button>
        </div>
    `;
    document.body.appendChild(dialog);
    dialog.querySelector(".promptcrafter-help-close-button").onclick = () => document.body.removeChild(dialog);
    const style = document.createElement('style');
    style.textContent = `
        .promptcrafter-help-dialog { position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.6); display: flex; justify-content: center; align-items: center; z-index: 1001; }
        .promptcrafter-help-content { background: #222; border: 1px solid #444; border-radius: 8px; padding: 20px; max-width: 600px; max-height: 80vh; overflow-y: auto; color: #ccc; box-shadow: 0 4px 15px rgba(0,0,0,0.5); }
        .promptcrafter-help-content code { background: #111; padding: 2px 5px; border-radius: 4px; }
        .promptcrafter-help-close-button { float: right; margin-top: 15px; padding: 8px 15px; background: #333; border: 1px solid #555; border-radius: 5px; cursor: pointer; color: #fff; }
    `;
    dialog.appendChild(style);
}

// =================================================================================
// START: EXTENSION 1 (From promptcrafter_working.js)
// This is the known-working code for the dynamic image inputs.
// I have not modified it.
// =================================================================================

const DYNAMIC_INPUT_NODE_CLASSES_EXT1 = [
    "PromptCrafter_ImageCreator",
    "PromptCrafter_VideoCreator",
    "PromptCrafter_LyricsCreator",
];

app.registerExtension({
    name: "PromptCrafter.DynamicInputs.Working",
    async beforeRegisterNodeDef(nodeType, nodeData, app) {
        if (DYNAMIC_INPUT_NODE_CLASSES_EXT1.includes(nodeType.comfyClass)) {

            const updateWeightsJSON = function(node) {
                const weights = {};
                for (const w of node.widgets) {
                    if (w.name && w.name.startsWith("image_weight_")) {
                        weights[w.name] = w.value;
                    }
                }
                const jsonWidget = node.widgets.find(w => w.name === "image_weights_json");
                if (jsonWidget) {
                    jsonWidget.value = JSON.stringify(weights);
                }
            };

            const updateNodeImageInputs = function(targetCount) {
                if (targetCount === undefined) return;

                const inputPrefix = "image_";
                const weightPrefix = "image_weight_";
                const outputPrefix = "reference_image_";
                const numStandardOutputs = 4;

                const currentInputs = this.inputs?.filter(input => /^image_\d+$/.test(input.name)) || [];
                let currentInputCount = currentInputs.length;

                if (targetCount < currentInputCount) {
                    for (let i = currentInputCount; i > targetCount; i--) {
                        this.removeInput(this.findInputSlot(`${inputPrefix}${i}`));
                    }
                } else if (targetCount > currentInputCount) {
                    for (let i = currentInputCount; i < targetCount; i++) {
                        this.addInput(`${inputPrefix}${i + 1}`, "IMAGE");
                    }
                }

                const currentWidgets = this.widgets.filter(w => w.name?.startsWith(weightPrefix));
                let currentWidgetCount = currentWidgets.length;

                if (targetCount < currentWidgetCount) {
                    for (let i = currentWidgetCount; i > targetCount; i--) {
                        const widgetToRemove = this.widgets.find(w => w.name === `${weightPrefix}${i}`);
                        if (widgetToRemove) {
                            this.widgets.splice(this.widgets.indexOf(widgetToRemove), 1);
                        }
                    }
                } else if (targetCount > currentWidgetCount) {
                    for (let i = currentWidgetCount; i < targetCount; i++) {
                        this.addWidget("number", `${weightPrefix}${i + 1}`, 1.0, (value) => {
                            updateWeightsJSON(this);
                        }, { min: 0.0, max: 2.0, step: 0.01 });
                    }
                }
                
                updateWeightsJSON(this);

                const currentOutputCount = this.outputs.length - numStandardOutputs;

                if (targetCount < currentOutputCount) {
                    for (let i = currentOutputCount; i > targetCount; i--) {
                        this.removeOutput(this.outputs.length - 1);
                    }
                } else if (targetCount > currentOutputCount) {
                    for (let i = currentOutputCount; i < targetCount; i++) {
                        const name = `${outputPrefix}${i + 1}`;
                        this.addOutput(name, "IMAGE");
                    }
                }

                this.computeSize();
                this.setDirtyCanvas(true, true);
            };

            const onNodeCreated = nodeType.prototype.onNodeCreated;
            nodeType.prototype.onNodeCreated = function () {
                onNodeCreated?.apply(this, arguments);

                const imageCountWidget = this.widgets.find(w => w.name === "image_count");

                this.addWidget("button", "Update Image Inputs", null, () => {
                    if (imageCountWidget) {
                        updateNodeImageInputs.call(this, imageCountWidget.value);
                    }
                });

                const jsonWidget = this.widgets.find(w => w.name === "image_weights_json");
                if (jsonWidget && jsonWidget.inputEl) {
                    jsonWidget.inputEl.style.display = "none";
                }
                if (imageCountWidget) {
                    const originalCallback = imageCountWidget.callback;
                    imageCountWidget.callback = (value) => {
                        originalCallback?.(value);
                        updateNodeImageInputs.call(this, value);
                    };
                    setTimeout(() => updateNodeImageInputs.call(this, imageCountWidget.value), 10);
                }
            };

            const onConfigure = nodeType.prototype.onConfigure;
            nodeType.prototype.onConfigure = function() {
                onConfigure?.apply(this, arguments);
                const imageCountWidget = this.widgets?.find(w => w.name === "image_count");
                if (imageCountWidget) {
                    setTimeout(() => {
                        const count = parseInt(imageCountWidget.value, 10);
                        if (!isNaN(count))
                            updateNodeImageInputs.call(this, count);
                    }, 10);
                }
            };
        }
    },
});

// =================================================================================
// START: EXTENSION 2 (Feature from promptcrafter_not_working.js)
// This adds the Help button feature as a second, separate extension.
// It will not conflict with the one above.
// =================================================================================

const ALL_PROMPTCRAFTER_NODE_CLASSES_EXT2 = [
    "PromptCrafter_ImageCreator",
    "PromptCrafter_VideoCreator",
    "PromptCrafter_LyricsCreator",
    "PromptCrafter_QnA",
    "PromptCrafter_Captioner",
    "PromptCrafter_FileOrganizer",
    "PromptCrafter_ClearCache",
];

app.registerExtension({
    name: "PromptCrafter.HelpButton.Working",
    async setup() {
        await getHelpText();
    },
    async beforeRegisterNodeDef(nodeType, nodeData, app) {
        if (ALL_PROMPTCRAFTER_NODE_CLASSES_EXT2.includes(nodeType.comfyClass)) {
            const onNodeCreated = nodeType.prototype.onNodeCreated;
            nodeType.prototype.onNodeCreated = function () {
                const r = onNodeCreated ? onNodeCreated.apply(this, arguments) : undefined;
                if (typeof this.addHeaderButton === 'function') {
                    this.addHeaderButton("?", (canvas, node) => showHelpDialog(node), { x: -18, y: -2, size: 16 });
                }
                return r;
            };
        }
    }
});