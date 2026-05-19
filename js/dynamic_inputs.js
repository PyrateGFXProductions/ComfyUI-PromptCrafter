import { app } from "../../../scripts/app.js";

// =================================================================================
// This script provides dynamic input capabilities for specific nodes.
// It now handles two types of nodes:
// 1. Creator Nodes: Complex nodes with dynamic images, weights, and reference outputs.
// 2. Switcher Nodes: Simpler nodes with only dynamic image inputs.
// =================================================================================

const DYNAMIC_CREATOR_NODE_CONFIG = {
    PromptCrafter_BaseCreator: { numStandardOutputs: 6 },
    PromptCrafter_VisualCreator: { numStandardOutputs: 6 },
    PromptCrafter_VisualCreatorEasy: { numStandardOutputs: 6 },
    PGFX_LogoDesignerAgent: { numStandardOutputs: 16 },
    PGFX_MultiImagePreview: { numStandardOutputs: 0 },
    PromptCrafter_LyricsCreator: {
        numStandardOutputs: 20,
        trailingFixedOutputs: [{ name: "schedule_json", type: "STRING" }],
    },
    PromptCrafter_LyricsCreatorEasy: {
        numStandardOutputs: 20,
        trailingFixedOutputs: [{ name: "schedule_json", type: "STRING" }],
    },
};

const DYNAMIC_CREATOR_NODE_CLASSES = Object.keys(DYNAMIC_CREATOR_NODE_CONFIG);

const DYNAMIC_SWITCHER_NODE_CLASSES = [
    "PromptCrafter_ImageSwitcher",
];

app.registerExtension({
    name: "PromptCrafter.DynamicInputs",
    async beforeRegisterNodeDef(nodeType, nodeData, app) {
        const className = nodeData.name;

        // --- Handler for Switcher Nodes ---
        if (DYNAMIC_SWITCHER_NODE_CLASSES.includes(className)) {
            
            const updateImageSwitcherInputs = function(targetCount) {
                const count = parseInt(targetCount, 10);
                if (isNaN(count)) return;
                
                const inputPrefix = "image_";
                const currentInputs = this.inputs?.filter(input => /^image_\d+$/.test(input.name)) || [];
                let currentInputCount = currentInputs.length;

                if (count < currentInputCount) {
                    for (let i = currentInputCount; i > count; i--) {
                        this.removeInput(this.findInputSlot(`${inputPrefix}${i}`)); 
                    }
                } else if (count > currentInputCount) {
                    for (let i = currentInputCount; i < count; i++) {
                        this.addInput(`${inputPrefix}${i + 1}`, "IMAGE");
                    }
                }

                this.computeSize(); 
                this.setDirtyCanvas(true, true);
            };

            const addManualRefreshButton = function() {
                const imageCountWidget = this.widgets?.find(w => w.name === "image_count");
                if (!imageCountWidget) return;

                // Avoid adding multiple buttons
                const existingButton = this.widgets?.find(w => w.name === "Manual Refresh");
                if (existingButton) return;

                this.addWidget("button", "Manual Refresh", null, () => {
                    updateImageSwitcherInputs.call(this, imageCountWidget.value);
                }, { serialize: false });
            };

            const onCreated = nodeType.prototype.onCreated;
            nodeType.prototype.onCreated = function () {
                onCreated?.apply(this, arguments);

                // Force correct output configuration
                if (this.outputs && this.outputs.length > 2) {
                    // Keep only the first 2 outputs (IMAGE and INT)
                    this.outputs = this.outputs.slice(0, 2);
                }

                // Delay button addition to ensure widgets are loaded
                setTimeout(() => {
                    addManualRefreshButton.call(this);
                    const imageCountWidget = this.widgets?.find(w => w.name === "image_count");
                    if (imageCountWidget) {
                        updateImageSwitcherInputs.call(this, imageCountWidget.value);
                    }
                }, 50);
            };

            const onConfigure = nodeType.prototype.onConfigure;
            nodeType.prototype.onConfigure = function() {
                onConfigure?.apply(this, arguments);

                // Force correct output configuration on load
                if (this.outputs && this.outputs.length > 2) {
                    this.outputs = this.outputs.slice(0, 2);
                }

                setTimeout(() => {
                    addManualRefreshButton.call(this);
                    const imageCountWidget = this.widgets?.find(w => w.name === "image_count");
                    if (imageCountWidget) {
                        updateImageSwitcherInputs.call(this, imageCountWidget.value);
                    }
                }, 50);
            };

            // Add this to ensure outputs are correct when node is executed
            const onExecutionStart = nodeType.prototype.onExecutionStart;
            nodeType.prototype.onExecutionStart = function() {
                onExecutionStart?.apply(this, arguments);
                
                // Ensure we only have 2 outputs
                if (this.outputs && this.outputs.length > 2) {
                    this.outputs = this.outputs.slice(0, 2);
                }
            };
        }



        // --- Handler for Creator Nodes (Original Logic) ---
        if (DYNAMIC_CREATOR_NODE_CLASSES.includes(className)) {
            console.log(`[PromptCrafter] Attaching dynamic inputs to ${className}`);
            const creatorConfig = DYNAMIC_CREATOR_NODE_CONFIG[className] ?? {};
            const numStandardOutputs = creatorConfig.numStandardOutputs ?? 6;
            const trailingFixedOutputs = creatorConfig.trailingFixedOutputs ?? [];
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
                const dynamicOutputRegex = /^reference_image_\d+$/;

                // Preserve fixed trailing outputs like schedule_json before
                // adjusting the dynamic reference image outputs.
                const preservedTrailingOutputs = trailingFixedOutputs.map((def) => {
                    const outputIndex = this.outputs.findIndex(output => output.name === def.name);
                    if (outputIndex !== -1) {
                        return this.outputs.splice(outputIndex, 1)[0];
                    }
                    return { name: def.name, type: def.type, links: null };
                });

                // Count existing image inputs (excluding other inputs)
                const currentInputs = this.inputs?.filter(input => /^image_\d+$/.test(input.name)) || [];
                let currentInputCount = currentInputs.length;

                // Handle inputs
                if (targetCount < currentInputCount) {
                    for (let i = currentInputCount; i > targetCount; i--) {
                        const slotToRemove = this.findInputSlot(`${inputPrefix}${i}`);
                        if (slotToRemove !== -1) {
                            this.removeInput(slotToRemove);
                        }
                    }
                } else if (targetCount > currentInputCount) {
                    for (let i = currentInputCount; i < targetCount; i++) {
                        this.addInput(`${inputPrefix}${i + 1}`, "IMAGE");
                    }
                }

                // Handle widgets (Weights)
                // Filter specifically for our dynamic weights to avoid confusion
                const currentWidgets = this.widgets.filter(w => w.name?.startsWith(weightPrefix));
                let currentWidgetCount = currentWidgets.length;

                if (targetCount < currentWidgetCount) {
                    // Remove excess widgets
                    for (let i = currentWidgetCount; i > targetCount; i--) {
                        const widgetName = `${weightPrefix}${i}`;
                        const widgetIndex = this.widgets.findIndex(w => w.name === widgetName);
                        if (widgetIndex !== -1) {
                             // Properly remove widget from the array and clean up linked DOM elements if any
                            this.widgets.splice(widgetIndex, 1);
                        }
                    }
                } else if (targetCount > currentWidgetCount) {
                    // Add new widgets
                    for (let i = currentWidgetCount; i < targetCount; i++) {
                        this.addWidget("number", `${weightPrefix}${i + 1}`, 1.0, (value) => {
                            updateWeightsJSON(this);
                        }, { min: 0.0, max: 2.0, step: 0.01 });
                    }
                }
                
                updateWeightsJSON(this);

                // Handle dynamic outputs (reference images)
                const validDynamicOutputs = this.outputs.filter(
                    output => dynamicOutputRegex.test(output.name)
                ).length;


                if (targetCount < validDynamicOutputs) {
                    // Remove excess dynamic outputs from the end
                    for (let i = validDynamicOutputs; i > targetCount; i--) {
                         const slotToRemove = this.outputs.findIndex(output => output.name === `${outputPrefix}${i}`);
                         if (slotToRemove !== -1) {
                             this.removeOutput(slotToRemove);
                         }
                    }
                } else if (targetCount > validDynamicOutputs) {
                    // Add missing dynamic outputs
                    for (let i = validDynamicOutputs; i < targetCount; i++) {
                        const name = `${outputPrefix}${i + 1}`;
                        // Avoid duplicates
                        if (!this.outputs.find(output => output.name === name)) {
                            this.addOutput(name, "IMAGE");
                        }
                    }
                }

                // Re-append any preserved fixed trailing outputs in a stable order.
                for (const def of trailingFixedOutputs) {
                    const existingIndex = this.outputs.findIndex(output => output.name === def.name);
                    if (existingIndex !== -1) {
                        this.outputs.splice(existingIndex, 1);
                    }
                }
                for (const output of preservedTrailingOutputs) {
                    this.outputs.push(output);
                }

                this.computeSize();
                this.setDirtyCanvas(true, true);
            };

            // Initialization Logic (Wrapped in function for reuse)
            const setupDynamicInputs = function(node) {
                 if (!node.widgets) return;

                 const imageCountWidget = node.widgets.find(w => w.name === "image_count");
                 if (!imageCountWidget) return;

                 // Idempotency: Check if button already exists
                 const existingBtn = node.widgets.find(w => w.name === "Update Image Inputs");
                 if (!existingBtn) {
                     // Add the update button if missing
                     node.addWidget("button", "Update Image Inputs", null, () => {
                         updateNodeImageInputs.call(node, imageCountWidget.value);
                     });
                 }

                 // Hide JSON widget if present
                 const jsonWidget = node.widgets.find(w => w.name === "image_weights_json");
                 if (jsonWidget && jsonWidget.inputEl) {
                     jsonWidget.inputEl.style.display = "none";
                 }
                 
                 if (!imageCountWidget.pgfx_hooked) {
                     const originalCallback = imageCountWidget.callback;
                     imageCountWidget.callback = (value) => {
                         if (originalCallback) originalCallback(value);
                         updateNodeImageInputs.call(node, value);
                     };
                     imageCountWidget.pgfx_hooked = true;
                 }
                 
                 // Trigger initial update
                 updateNodeImageInputs.call(node, imageCountWidget.value || 1);
            };

            const onNodeCreated = nodeType.prototype.onNodeCreated;
            nodeType.prototype.onNodeCreated = function () {
                onNodeCreated?.apply(this, arguments);
                // Delay setup to ensure widgets are ready
                setTimeout(() => {
                    setupDynamicInputs(this);
                }, 50);
            };

            const onConfigure = nodeType.prototype.onConfigure;
            nodeType.prototype.onConfigure = function() {
                onConfigure?.apply(this, arguments);
                // Delay setup for loaded workflows
                setTimeout(() => {
                    setupDynamicInputs(this);
                }, 50);
            };


            nodeType.prototype.numStandardOutputs = numStandardOutputs;

            // --- Multi-Image Preview Specialization ---
            if (className === "PGFX_MultiImagePreview") {
                const onExecuted = nodeType.prototype.onExecuted;
                nodeType.prototype.onExecuted = function (message) {
                    onExecuted?.apply(this, arguments);
                    if (message?.images) {
                        this.imgs = message.images.map(img => {
                            const url = `./view?filename=${encodeURIComponent(img.filename)}&type=${img.type}&subfolder=${encodeURIComponent(img.subfolder)}&t=${+new Date()}`;
                            const i = new Image();
                            i.src = url;
                            return i;
                        });
                        this.setDirtyCanvas(true);
                    }
                };
            }
        }
    },
});
