import { app } from "../../../scripts/app.js";

// =================================================================================
// PGFX Genre Picker — MiniMax Music 3
// Watches the native 'genre_add' COMBO dropdown.
// When the user picks a genre from it:
//   1. Appends it to the 'genres' STRING widget (comma-separated list)
//   2. Resets the dropdown back to the placeholder
// =================================================================================

const TARGET_NODE = "PromptCrafter_MiniMaxMusic3Creator";
const PLACEHOLDER = "\u2500\u2500 pick genre to add \u2500\u2500";

function parseGenres(val) {
    if (!val || !val.trim()) return [];
    return val.split(",").map(s => s.trim()).filter(Boolean);
}

function setWidgetValue(widget, value) {
    widget.value = value;
    if (typeof widget.callback === "function") widget.callback(value);
    app.graph.setDirtyCanvas(true);
}

// ---------------------------------------------------------------------------
// Install behaviour on a node instance
// ---------------------------------------------------------------------------
function install(node) {
    if (node._pgfx_genre_installed) return;
    node._pgfx_genre_installed = true;

    const pickerW = node.widgets && node.widgets.find(w => w.name === "genre_add");
    const listW   = node.widgets && node.widgets.find(w => w.name === "genres");
    const clearW  = node.widgets && node.widgets.find(w => w.name === "clear_genres");

    if (!pickerW || !listW) return;

    // Wrap genre_add callback: on selection → append to genres list → reset picker
    const origCallback = pickerW.callback;
    pickerW.callback = function(value) {
        if (origCallback) origCallback.call(this, value);
        if (!value || value === PLACEHOLDER) return;

        const current = parseGenres(listW.value);
        if (!current.includes(value)) {
            current.push(value);
            setWidgetValue(listW, current.join(", "));
        }

        // Reset picker to placeholder
        setTimeout(() => {
            pickerW.value = PLACEHOLDER;
            app.graph.setDirtyCanvas(true);
        }, 50);
    };

    // Wrap clear_genres toggle: on true → wipe list → auto-reset toggle
    if (clearW) {
        const origClearCb = clearW.callback;
        clearW.callback = function(value) {
            if (origClearCb) origClearCb.call(this, value);
            if (value === true) {
                setWidgetValue(listW, "");
                setTimeout(() => {
                    clearW.value = false;
                    app.graph.setDirtyCanvas(true);
                }, 200);
            }
        };
    }
}

// ---------------------------------------------------------------------------
// ComfyUI Extension Registration
// ---------------------------------------------------------------------------
app.registerExtension({
    name: "PGFX.GenrePicker",

    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== TARGET_NODE) return;
        const orig = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function() {
            const r = orig ? orig.apply(this, arguments) : undefined;
            install(this);
            return r;
        };
    },

    async loadedGraphNode(node) {
        if (node.type !== TARGET_NODE) return;
        install(node);
    },
});
