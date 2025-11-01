import { app } from "../../../scripts/app.js";

// =================================================================================
// This script provides dynamic input capabilities for specific nodes.
// It now handles two types of nodes:
// 1. Creator Nodes: Complex nodes with dynamic images, weights, and reference outputs.
// 2. Switcher Nodes: Simpler nodes with only dynamic image inputs.
// =================================================================================

const DYNAMIC_CREATOR_NODE_CLASSES = [
    "PromptCrafter_BaseCreator",
    "PromptCrafter_VisualCreator",
    "PromptCrafter_LyricsCreator",
];

const DYNAMIC_SWITCHER_NODE_CLASSES = [
    "PromptCrafter_ImageSwitcher",
];

app.registerExtension({
    name: "PromptCrafter.DynamicInputs",
    async beforeRegisterNodeDef(nodeType, nodeData, app) {

        // --- Handler for Switcher Nodes ---
        if (DYNAMIC_SWITCHER_NODE_CLASSES.includes(nodeType.comfyClass)) {
            
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
        if (DYNAMIC_CREATOR_NODE_CLASSES.includes(nodeType.comfyClass)) {
            let numStandardOutputs;
            if (nodeType.comfyClass === "PromptCrafter_VisualCreator") {
                numStandardOutputs = 6;
            } else if (nodeType.comfyClass === "PromptCrafter_LyricsCreator") {
                numStandardOutputs = 20;
            } else {
                numStandardOutputs = 6; // Default value
            }
            const updateWeightsJSON = function(node) {
                const weights = {};
                for (const w of node.widgets) {
                    if (w.name && w.name.startsWith("image_weight_")) {
                        weights[w.name] = w.value;
                    }
                }
                const jsonWidget = node.widgets.find(w => w.name === "image_weights_json");
                if (jsonWidget) {
                }
            };

            // In your updateNodeImageInputs function, fix the output management:

            const updateNodeImageInputs = function(targetCount) {
                if (targetCount === undefined) return;

                const inputPrefix = "image_";
                const weightPrefix = "image_weight_";
                const outputPrefix = "reference_image_";

                const currentInputs = this.inputs?.filter(input => /^image_\d+$/.test(input.name)) || [];
                let currentInputCount = currentInputs.length;

                // Handle inputs
                if (targetCount < currentInputCount) {
                    for (let i = currentInputCount; i > targetCount; i--) {
                        this.removeInput(this.findInputSlot(`${inputPrefix}${i}`));
                    }
                } else if (targetCount > currentInputCount) {
                    for (let i = currentInputCount; i < targetCount; i++) {
                        this.addInput(`${inputPrefix}${i + 1}`, "IMAGE");
                    }
                }

                // Handle widgets
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

                // Handle outputs - this is the key fix
                // We need to manage only the dynamic reference_image outputs
                const currentDynamicOutputs = this.outputs.length - numStandardOutputs;

                if (targetCount < currentDynamicOutputs) {
                    // Remove excess dynamic outputs
                    for (let i = currentDynamicOutputs; i > targetCount; i--) {
                        const slotToRemove = this.outputs.findIndex(output => output.name === `${outputPrefix}${i}`);
                        if (slotToRemove !== -1) {
                            this.removeOutput(slotToRemove);
                        }
                    }
                } else if (targetCount > currentDynamicOutputs) {
                    // Add missing dynamic outputs
                    for (let i = currentDynamicOutputs; i < targetCount; i++) {
                        const name = `${outputPrefix}${i + 1}`;
                        // Make sure we don't add duplicates
                        if (!this.outputs.find(output => output.name === name)) {
                            this.addOutput(name, "IMAGE");
                        }
                    }
                }

                this.computeSize();
                this.setDirtyCanvas(true, true);
            };

            // Also, in your onNodeCreated, make sure to initialize properly:
            const onNodeCreated = nodeType.prototype.onNodeCreated;
            nodeType.prototype.onNodeCreated = function () {
                onNodeCreated?.apply(this, arguments);

                const imageCountWidget = this.widgets.find(w => w.name === "image_count");

                // Add the update button
                this.addWidget("button", "Update Image Inputs", null, () => {
                    if (imageCountWidget) {
                        updateNodeImageInputs.call(this, imageCountWidget.value);
                    }
                });

                // Hide JSON widget
                const jsonWidget = this.widgets.find(w => w.name === "image_weights_json");
                if (jsonWidget && jsonWidget.inputEl) {
                    jsonWidget.inputEl.style.display = "none";
                }
                
                // Set up callback for image_count changes
                if (imageCountWidget) {
                    const originalCallback = imageCountWidget.callback;
                    imageCountWidget.callback = (value) => {
                        originalCallback?.(value);
                        updateNodeImageInputs.call(this, value);
                    };
                    // Initialize with default value (usually 1)
                    setTimeout(() => updateNodeImageInputs.call(this, imageCountWidget.value || 1), 10);
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

            nodeType.prototype.numStandardOutputs = numStandardOutputs;
        }
    },
});