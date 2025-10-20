import { app } from "../../../scripts/app.js";

// =================================================================================
// START: EXTENSION 1 (From promptcrafter_working.js)
// This is the known-working code for the dynamic image inputs.
// I have not modified it.
// =================================================================================

const DYNAMIC_INPUT_NODE_CLASSES_EXT1 = [
    "PromptCrafter_BaseCreator",
    "PromptCrafter_VisualCreator",
    "PromptCrafter_LyricsCreator",
];

app.registerExtension({
    name: "PromptCrafter.DynamicInputs.Working",
    async beforeRegisterNodeDef(nodeType, nodeData, app) {
        if (DYNAMIC_INPUT_NODE_CLASSES_EXT1.includes(nodeType.comfyClass)) {

            let numStandardOutputs;
            if (nodeType.comfyClass === "PromptCrafter_VisualCreator") {
                numStandardOutputs = 6;
            } else if (nodeType.comfyClass === "PromptCrafter_LyricsCreator") {
                numStandardOutputs = 8;
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

            const updateNodeImageInputs = function(targetCount) {
                if (targetCount === undefined) return;

                const inputPrefix = "image_";
                const weightPrefix = "image_weight_";
                const outputPrefix = "reference_image_";

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

                const numStandardOutputs = this.numStandardOutputs;
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

            nodeType.prototype.numStandardOutputs = numStandardOutputs;

            


        }
    },
});