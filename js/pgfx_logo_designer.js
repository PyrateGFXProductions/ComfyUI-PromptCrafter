console.log("[PGFX] Fixed Logo Studio Loaded");
import { app } from "../../scripts/app.js";

// Load Fabric.js from CDN dynamically if it hasn't been loaded yet
const loadFabric = () => {
    return new Promise((resolve, reject) => {
        if (window.fabric) {
            resolve(window.fabric);
            return;
        }
        const script = document.createElement("script");
        script.src = "https://cdnjs.cloudflare.com/ajax/libs/fabric.js/5.3.1/fabric.min.js";
        script.onload = () => resolve(window.fabric);
        script.onerror = reject;
        document.head.appendChild(script);
    });
};

// Insert custom CSS for the Studio Overlay
const injectStyles = () => {
    if (document.getElementById("pgfx-logo-studio-styles")) return;
    const style = document.createElement("style");
    style.id = "pgfx-logo-studio-styles";
    style.textContent = `
        #pgfx-studio-overlay {
            position: fixed;
            top: 0; left: 0; width: 100vw; height: 100vh;
            background: rgba(10, 10, 11, 0.95);
            backdrop-filter: blur(10px);
            z-index: 10000;
            display: flex;
            align-items: center;
            justify-content: center;
            color: white;
            font-family: 'Inter', system-ui, sans-serif;
            opacity: 0;
            pointer-events: none;
            transition: opacity 0.3s ease;
        }
        #pgfx-studio-overlay.active {
            opacity: 1;
            pointer-events: auto;
        }
        .pgfx-studio-container {
            width: 95%;
            max-width: 1400px;
            height: 95%;
            background: #111113;
            border: 1px solid rgba(255,255,255,0.1);
            border-radius: 16px;
            display: flex;
            flex-direction: column;
            overflow: hidden;
            box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.5);
        }
        .pgfx-studio-header {
            flex-shrink: 0;
            padding: 16px 24px;
            background: #18181b;
            border-bottom: 1px solid rgba(255,255,255,0.05);
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .pgfx-studio-title {
            font-size: 18px;
            font-weight: 900;
            text-transform: uppercase;
            letter-spacing: 2px;
            color: #06b6d4;
            display: flex;
            align-items: center;
            gap: 12px;
        }
        .pgfx-studio-body {
            display: flex;
            flex: 1;
            overflow: hidden;
        }
        .pgfx-studio-sidebar {
            flex-shrink: 0;
            width: 320px;
            background: #18181b;
            border-right: 1px solid rgba(255,255,255,0.05);
            padding: 20px;
            display: flex;
            flex-direction: column;
            gap: 16px;
            overflow-y: auto;
        }
        .pgfx-studio-main {
            min-width: 0;
            flex: 1;
            display: flex;
            flex-direction: column;
            background: #09090b;
        }
        .pgfx-studio-toolbar {
            height: 48px;
            background: #18181b;
            border-bottom: 1px solid rgba(255,255,255,0.05);
            display: flex;
            align-items: center;
            padding: 0 20px;
            gap: 16px;
            z-index: 10;
        }
        .pgfx-toolbar-separator {
            width: 1px;
            height: 24px;
            background: rgba(255,255,255,0.1);
        }
        .pgfx-studio-canvas-wrapper {
            min-width: 0;
            min-height: 0;
            display: flex;
            align-items: center;
            justify-content: center;
            flex: 1;
            background-color: #1a1a1e;
            background-image:
                linear-gradient(rgba(255,255,255,0.03) 1px, transparent 1px),
                linear-gradient(90deg, rgba(255,255,255,0.03) 1px, transparent 1px);
            background-size: 50px 50px;
            overflow: hidden; /* Prevent native scrollbars from fighting canvas pan */
            position: relative;
        }
        .pgfx-studio-canvas-wrapper canvas {
            display: block;
            margin: auto;
            max-width: 100%;
            max-height: 100%;
        }
        .pgfx-btn {
            background: #27272a;
            color: white;
            border: 1px solid rgba(255,255,255,0.1);
            padding: 8px 12px;
            border-radius: 6px;
            cursor: pointer;
            font-weight: 600;
            font-size: 12px;
            text-transform: uppercase;
            letter-spacing: 1px;
            transition: all 0.2s;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 8px;
        }
        .pgfx-btn-text {
            font-size: 9px;
            padding: 6px 4px;
            letter-spacing: 0px;
            flex: 1;
        }
        .pgfx-btn:hover {
            background: #3f3f46;
            border-color: rgba(255,255,255,0.2);
        }
        .pgfx-btn-primary {
            background: #06b6d4;
            color: black;
            border: none;
        }
        .pgfx-btn-primary:hover {
            background: #0891b2;
        }
        .pgfx-btn-danger {
            background: rgba(239, 68, 68, 0.1);
            color: #ef4444;
            border-color: rgba(239, 68, 68, 0.2);
        }
        .pgfx-btn-danger:hover {
            background: #ef4444;
            color: white;
        }
        .pgfx-btn-icon {
            padding: 6px;
            width: 32px;
            height: 32px;
        }
        .pgfx-input-group {
            display: flex;
            flex-direction: column;
            gap: 8px;
            background: rgba(255,255,255,0.02);
            padding: 12px;
            border-radius: 8px;
            border: 1px solid rgba(255,255,255,0.05);
        }
        .pgfx-label {
            font-size: 10px;
            text-transform: uppercase;
            font-weight: 800;
            color: #71717a;
            display: flex;
            justify-content: space-between;
        }
        .pgfx-input, .pgfx-select {
            background: #000;
            border: 1px solid rgba(255,255,255,0.1);
            color: white;
            padding: 8px 12px;
            border-radius: 6px;
            font-size: 13px;
            outline: none;
            width: 100%;
        }
        .pgfx-input:focus, .pgfx-select:focus {
            border-color: #06b6d4;
        }
        .canvas-container {
            box-shadow: 0 10px 50px rgba(0,0,0,0.8), 0 0 0 1px rgba(255,255,255,0.1) !important;
            border: 2px solid #06b6d4 !important;
            border-radius: 8px;
            overflow: hidden;
            box-sizing: content-box;
        }
        .pgfx-row {
            display: flex;
            gap: 8px;
            align-items: center;
        }
        .hidden-file-input {
            display: none;
        }
    `;
    document.head.appendChild(style);
};

// Main Studio UI Manager
class LogoStudioUI {
    constructor(node, base64Widget, jsonWidget, textWidget) {
        this.node        = node;
        this.base64Widget = base64Widget;
        this.jsonWidget  = jsonWidget;
        this.textWidget  = textWidget;  // two-way synced with canvas IText layers
        this.canvas      = null;
        this.overlay     = null;
        this.customFonts = [];
        this.syncTimer   = null;
        this.targetWidth = 1024;
        this.targetHeight = 1024;

        // History Management
        this.history      = [];
        this.historyIdx   = -1;
        this.isProcessingHistory = false;

        // Camera Overlay properties
        this.cameraStream = null;
        this.cameraVideoEl = null;
        this.cameraAnimFrame = null;
        this.cameraActive = false;

        this.currentlyEditingPoly = null;
        this.lastCanvasText = "";

        this.initDOM();
    }

    _saveToHistory() {
        if (!this.canvas || this.isProcessingHistory) return;
        const state = JSON.stringify(this.canvas.toJSON(['name', 'pgfx_editor_background']));

        // If state hasn't changed, don't push
        if (this.history[this.historyIdx] === state) return;

        // Remove any "future" history if we were in the middle of undoing
        this.history = this.history.slice(0, this.historyIdx + 1);
        this.history.push(state);
        this.historyIdx++;

        // Limit history to 50 steps
        if (this.history.length > 50) {
            this.history.shift();
            this.historyIdx--;
        }
    }

    undo() {
        if (this.historyIdx <= 0) return;
        this.historyIdx--;
        this._loadFromHistory();
    }

    redo() {
        if (this.historyIdx >= this.history.length - 1) return;
        this.historyIdx++;
        this._loadFromHistory();
    }

    _loadFromHistory() {
        const state = this.history[this.historyIdx];
        if (!state) return;

        this.isProcessingHistory = true;
        this.canvas.loadFromJSON(JSON.parse(state), () => {
            this.canvas.renderAll();
            this.isProcessingHistory = false;
            this.scheduleNodeStateSync();
        });
    }

    async open() {
        await loadFabric();
        injectStyles();

        this.overlay.classList.add('active');

        // Fetch fonts every time the studio opens to ensure fresh data
        await this.fetchFontsFromServer();

        if (!this.canvas) {
            this.canvas = new fabric.Canvas('pgfx-design-canvas', {
                width: 1024,
                height: 1024,
                backgroundColor: 'transparent',
                preserveObjectStacking: true
            });
            this.pageBackgroundColor = '#000000';

            // â”€â”€ Restore from saved JSON if available â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
            if (this.jsonWidget.value && this.jsonWidget.value.startsWith('{')) {
                try {
                    const jsonData = JSON.parse(this.jsonWidget.value);
                    if (jsonData.customFonts) {
                        for (const font of jsonData.customFonts) {
                            await this.loadFontIntoBrowser(font.name, font.url);
                        }
                    }
                    this.canvas.loadFromJSON(jsonData, () => {
                        const restoredBg = jsonData.pgfx_editor_background || jsonData.backgroundColor || jsonData.background || '#000000';
                        this.pageBackgroundColor = restoredBg === 'transparent' ? '#000000' : restoredBg;       
                        this.canvas.backgroundColor = 'transparent';
                        this.targetWidth = jsonData.pgfx_canvas_width || 1024;       
                        this.targetHeight = jsonData.pgfx_canvas_height || 1024;    

                        // Sync UI boxes if they exist
                        const widthInput = document.getElementById('pgfx-canvas-width');
                        const heightInput = document.getElementById('pgfx-canvas-height');
                        const presetSelect = document.getElementById('pgfx-canvas-preset');
                        if (widthInput && heightInput) {
                            widthInput.value = this.canvas.getWidth();
                            heightInput.value = this.canvas.getHeight();
                            if (presetSelect) presetSelect.value = "custom";
                        }

                        this.canvas.renderAll();
                        this._syncBackgroundPicker();
                        this.updateUIForSelection();
                        this.fitCanvasToView();
                        this.lastCanvasText = this._extractCanvasText();
                        this._saveToHistory();
                        this.scheduleNodeStateSync();
                    });
                } catch (e) {
                    console.error("[PGFX Studio] Error loading canvas JSON", e);
                    this._addDefaultText();
                this.fitCanvasToView();
                    this._syncBackgroundPicker();
                    this.fitCanvasToView();
                    this._saveToHistory();
                    this.scheduleNodeStateSync();
                }
            } else {
                // â”€â”€ No saved state: seed canvas from text_input if it has content â”€
                this._addDefaultText();
                this.fitCanvasToView();
                this._syncBackgroundPicker();
                this.fitCanvasToView();
                this.lastCanvasText = this._extractCanvasText();
                this._saveToHistory();
                this.scheduleNodeStateSync();
            }

            this.setupEventHandlers();
        } else {
            // Canvas already exists â€” if text_input changed since last open, update the primary text layer   
            this._syncTextInputToCanvas();
            this._syncBackgroundPicker();
            this.scheduleNodeStateSync();
        }
    }

    // Populate the canvas with the text_input value (or a placeholder if empty)
    _addDefaultText() {
        const rawText = (this.textWidget?.value || "").trim();
        const displayText = rawText || "YOUR TEXT\nHERE";
        const text = new fabric.IText(displayText, {
            left: this.canvas.getWidth() / 2, top: this.canvas.getHeight() / 2,
            fontFamily: 'Arial', fontSize: 140,
            fill: '#ffffff', textAlign: 'center',
            originX: 'center', originY: 'center',
            fontWeight: 'bold',
            name: 'pgfx_primary_text'   // tag so we can find it later
        });
        this.canvas.add(text);
        this.canvas.setActiveObject(text);
    }

    // If text_input was edited outside the modal, push the new value into the
    // first tagged primary-text layer (non-destructively ignores other layers).
    _syncTextInputToCanvas() {
        const newText = (this.textWidget?.value || "").trim();
        if (!newText) return;
        if (newText === (this.lastCanvasText || "").trim()) return; // Skip sync if the widget value matches what we last extracted from the canvas
        const primary = this.canvas.getObjects().find(o => o.name === 'pgfx_primary_text');
        if (primary && primary.text !== newText) {
            primary.set('text', newText);
            this.canvas.requestRenderAll();
        }
    }

    // Collect ALL IText / Text objects from canvas and return as a single string
    _extractCanvasText() {
        return this.canvas.getObjects()
            .filter(o => o.type === 'i-text' || o.type === 'text')
            .map(o => o.text)
            .join('\n')
            .trim();
    }

    _syncBackgroundPicker() {
        const picker = document.getElementById('pgfx-bg-picker');
        if (!picker) return;
        const bg = this.pageBackgroundColor;
        picker.value = typeof bg === 'string' && bg.startsWith('#') ? bg : '#000000';
    }

    _captureCanvasState() {
        if (!this.canvas) return null;

        const editorBackground = this.pageBackgroundColor || '#000000';
        const prevVpt = Array.isArray(this.canvas.viewportTransform)
            ? [...this.canvas.viewportTransform]
            : [1, 0, 0, 1, 0, 0];

        // Silently hide active object controls without triggering selection events or destroying ActiveSelection groups
        const prevActive = this.canvas._activeObject;
        this.canvas._activeObject = null;

        // Hide overlay items (like the page border) from export
        this.isExporting = true;

        this.canvas.setViewportTransform([1, 0, 0, 1, 0, 0]);
        // Do NOT call renderAll() here; let toDataURL do its synchronous rendering in-memory.
        // This avoids layout flashing and jumping completely.

        const multiplier = this.targetWidth / this.canvas.getWidth();
        const dataUrl = this.canvas.toDataURL({ format: 'png', quality: 1, multiplier: multiplier });

        this.isExporting = false;

        const advSettings = {};
        const primary = this.canvas.getObjects().find(o => o.name === 'pgfx_primary_text');
        if (primary) {
            advSettings.font_family = primary.fontFamily;
            advSettings.text_align = primary.textAlign;
        }

        const jsonState = this.canvas.toJSON(['name']);
        jsonState.background = 'transparent';
        jsonState.backgroundColor = 'transparent';
        jsonState.pgfx_editor_background = editorBackground;
        jsonState.pgfx_canvas_width = this.targetWidth;
        jsonState.pgfx_canvas_height = this.targetHeight;
        jsonState.customFonts = this.customFonts;
        jsonState.pgfx_adv_settings = advSettings;

        // Restore selection and original viewport
        this.canvas._activeObject = prevActive;
        this.canvas.setViewportTransform(prevVpt);
        this.canvas.renderAll();

        return {
            dataUrl,
            jsonText: JSON.stringify(jsonState),
            canvasText: this._extractCanvasText(),
        };
    }

    applyCanvasStateToNode({ bumpSeed = false, closeAfter = false } = {}) {
        const snapshot = this._captureCanvasState();
        if (!snapshot) return;

        if (this.base64Widget) this.base64Widget.value = snapshot.dataUrl;
        if (this.jsonWidget) this.jsonWidget.value = snapshot.jsonText;
        if (this.textWidget && snapshot.canvasText) this.textWidget.value = snapshot.canvasText;
        this.lastCanvasText = snapshot.canvasText;

        this.node._pgfxPreviewImg = null;
        this.node._pgfxLastSrc = null;

        if (bumpSeed) {
            const seedWidget = this.node.widgets.find(w => w.name === "seed");
            if (seedWidget) {
                seedWidget.value = Math.floor(Math.random() * 0xffffffffffffffff);
            }
        }

        if (app.graph) {
            const newSize = this.node.computeSize();
            this.node.setSize([Math.max(this.node.size[0], newSize[0]), newSize[1]]);
            app.graph.setDirtyCanvas(true, true);
        }

        if (closeAfter) {
            this.close();
        }
    }

    scheduleNodeStateSync(delay = 250) {
        if (!this.canvas) return;

        // If the user is actively editing a text layer, don't sync.
        // Sync will resume once they exit editing mode (e.g. click away).
        const activeObject = this.canvas.getActiveObject();
        if (activeObject && activeObject.isEditing) {
            return;
        }

        if (this.syncTimer) clearTimeout(this.syncTimer);
        this.syncTimer = setTimeout(() => {
            this.syncTimer = null;
            this.applyCanvasStateToNode();
        }, delay);
    }

    close() {
        this.stopCameraStream();
        const btn = document.getElementById('pgfx-camera-toggle');
        const controlsDiv = document.getElementById('pgfx-camera-controls');
        if (btn) {
            btn.innerHTML = "📹 Enable Camera";
            btn.classList.remove('pgfx-btn-danger');
        }
        if (controlsDiv) {
            controlsDiv.style.display = 'none';
        }
        this.overlay.classList.remove('active');
    }

    fitCanvasToView() {
        if (!this.canvas) return;
        const wrapper = this.overlay.querySelector('.pgfx-studio-canvas-wrapper');
        if (!wrapper) return;
        
        // Ensure wrapper is a proper flex container with explicit dimensions
        wrapper.style.display = 'flex';
        wrapper.style.alignItems = 'center';
        wrapper.style.justifyContent = 'center';
        wrapper.style.width = '100%';
        wrapper.style.height = '100%';
        
        const padding = 40;
        const maxW = Math.max(wrapper.clientWidth - padding, 100);
        const maxH = Math.max(wrapper.clientHeight - padding, 100);

        const targetRatio = this.targetWidth / this.targetHeight;
        let displayW = maxW;
        let displayH = maxW / targetRatio;
        
        if (displayH > maxH) {
            displayH = maxH;
            displayW = maxH * targetRatio;
        }

        this.canvas.setDimensions({
            width: Math.round(displayW),
            height: Math.round(displayH)
        }, { backstoreOnly: false });

        const canvasEl = this.canvas.getElement();
        if (canvasEl) {
            canvasEl.style.display = 'block';
            canvasEl.style.width = Math.round(displayW) + 'px';
            canvasEl.style.height = Math.round(displayH) + 'px';
        }

        const zoom = displayW / this.targetWidth;
        this.canvas.setViewportTransform([1, 0, 0, 1, 0, 0]);
        this.canvas.setZoom(zoom);

        this.canvas.calcOffset();
        this.canvas.requestRenderAll();
    }

    toggleNodeEditMode() {
        const btn = document.getElementById('pgfx-tool-node');

        // If we are already editing a shape, clicking the button ends node editing cleanly
        if (this.currentlyEditingPoly) {
            this.endNodeEditMode();
            return;
        }

        const poly = this.canvas.getActiveObject();
        if (!poly) {
            alert("Please select a shape or vector path to edit nodes.");
            return;
        }

        if (poly.type === 'group') {
            alert("This element is grouped. Please click 'Ungroup' in the sidebar first to edit individual path nodes.");
            return;
        }

        const allowedTypes = ['polygon', 'polyline', 'path'];
        if (!allowedTypes.includes(poly.type)) {
            alert(`Node editing is not supported on ${poly.type} elements directly. Try editing a vector shape or drawing.`);
            return;
        }

        // Start Editing
        this.canvas.isDrawingMode = false;
        document.getElementById('pgfx-tool-draw').classList.remove('pgfx-btn-primary');
        document.getElementById('pgfx-tool-select').classList.remove('pgfx-btn-primary');
        btn.classList.add('pgfx-btn-primary');

        poly.edit = true;
        poly.hasBorders = false;
        poly.hasControls = false;
        this.currentlyEditingPoly = poly;

        if (poly.type === 'path') {
            const segments = poly.path.filter(cmd => cmd[0] !== 'Z');
            if (segments.length > 150) {
                if (!confirm(`This path is highly complex and contains ${segments.length} nodes. Displaying all nodes may slow down the editor. Do you want to proceed?`)) {
                    poly.edit = false;
                    poly.hasBorders = true;
                    poly.hasControls = true;
                    this.currentlyEditingPoly = null;
                    btn.classList.remove('pgfx-btn-primary');
                    return;
                }
            }

            this.canvas._nodeControls = segments.map((cmd, index) => {
                const xIndex = cmd.length - 2;
                const yIndex = cmd.length - 1;

                // Compute initial absolute screen coordinates of control using 2D transform matrix & pathOffset
                const matrix = poly.calcTransformMatrix();
                const canvasPoint = fabric.util.transformPoint({
                    x: cmd[xIndex] - poly.pathOffset.x,
                    y: cmd[yIndex] - poly.pathOffset.y
                }, matrix);

                const control = new fabric.Circle({
                    radius: 6,
                    fill: '#06b6d4',
                    stroke: 'white',
                    strokeWidth: 2,
                    left: canvasPoint.x,
                    top: canvasPoint.y,
                    originX: 'center',
                    originY: 'center',
                    hasBorders: false,
                    hasControls: false,
                    name: 'node_control'
                });

                control.on('moving', () => {
                    // Convert control's canvas coordinates back to path local coordinates using inverse matrix 
                    const invMatrix = fabric.util.invertTransform(poly.calcTransformMatrix());
                    const localPoint = fabric.util.transformPoint({
                        x: control.left,
                        y: control.top
                    }, invMatrix);

                    cmd[xIndex] = localPoint.x + poly.pathOffset.x;
                    cmd[yIndex] = localPoint.y + poly.pathOffset.y;

                    poly.dirty = true;
                    this.canvas.requestRenderAll();
                });

                return control;
            });
        } else {
            // Polygon / Polyline
            this.canvas._nodeControls = poly.points.map((p, index) => {
                const point = poly.points[index];
                // Compute initial absolute screen coordinates of control using 2D transform matrix & pathOffset
                const matrix = poly.calcTransformMatrix();
                const canvasPoint = fabric.util.transformPoint({
                    x: point.x - poly.pathOffset.x,
                    y: point.y - poly.pathOffset.y
                }, matrix);

                const control = new fabric.Circle({
                    radius: 6,
                    fill: '#06b6d4',
                    stroke: 'white',
                    strokeWidth: 2,
                    left: canvasPoint.x,
                    top: canvasPoint.y,
                    originX: 'center',
                    originY: 'center',
                    hasBorders: false,
                    hasControls: false,
                    name: 'node_control'
                });

                control.on('moving', () => {
                    // Convert control's canvas coordinates back to polygon local coordinates using inverse matrix
                    const invMatrix = fabric.util.invertTransform(poly.calcTransformMatrix());
                    const localPoint = fabric.util.transformPoint({
                        x: control.left,
                        y: control.top
                    }, invMatrix);

                    point.x = localPoint.x + poly.pathOffset.x;
                    point.y = localPoint.y + poly.pathOffset.y;
                    this.canvas.requestRenderAll();
                });

                return control;
            });
        }

        this.canvas.add(...this.canvas._nodeControls);
        this.canvas.requestRenderAll();
    }

    endNodeEditMode() {
        if (!this.currentlyEditingPoly) return;

        const poly = this.currentlyEditingPoly;
        poly.edit = false;
        poly.hasBorders = true;
        poly.hasControls = true;

        if (this.canvas) {
            this.canvas.remove(...(this.canvas._nodeControls || []));
            this.canvas._nodeControls = [];
        }

        const btn = document.getElementById('pgfx-tool-node');
        if (btn) {
            btn.classList.remove('pgfx-btn-primary');
        }

        // Recalculate dimensions based on final points/segments position
        poly._setPositionDimensions({});
        poly.setCoords();

        this.currentlyEditingPoly = null;

        if (this.canvas) {
            this.canvas.requestRenderAll();
        }
        this._saveToHistory();
        this.scheduleNodeStateSync();
    }

    async toggleCamera() {
        const btn = document.getElementById('pgfx-camera-toggle');
        const controlsDiv = document.getElementById('pgfx-camera-controls');

        if (this.cameraActive) {
            this.stopCameraStream();
            btn.innerHTML = "📹 Enable Camera";
            btn.classList.remove('pgfx-btn-danger');
            controlsDiv.style.display = 'none';
        } else {
            btn.innerHTML = "â³ Starting...";
            try {
                // Request camera permission
                const stream = await navigator.mediaDevices.getUserMedia({ video: true });
                // Enumerate camera sources
                await this.populateCameraSelect();

                const select = document.getElementById('pgfx-camera-select');
                const deviceId = select.value;

                // Stop initial query stream to start device-specific stream
                stream.getTracks().forEach(track => track.stop());

                await this.startCameraStream(deviceId);

                btn.innerHTML = "🚫 Disable Camera";
                btn.classList.add('pgfx-btn-danger');
                controlsDiv.style.display = 'flex';
                this.cameraActive = true;
            } catch (err) {
                console.error("[PGFX Studio] Camera access failed:", err);
                alert("Could not access camera. Please check your permissions and webcam connection.");
                btn.innerHTML = "📹 Enable Camera";
            }
        }
    }

    async populateCameraSelect() {
        const select = document.getElementById('pgfx-camera-select');
        if (!select) return;
        select.innerHTML = '';
        try {
            const devices = await navigator.mediaDevices.enumerateDevices();
            const videoDevices = devices.filter(d => d.kind === 'videoinput');
            videoDevices.forEach((device, index) => {
                const option = document.createElement('option');
                option.value = device.deviceId;
                option.text = device.label || `Camera ${index + 1}`;
                select.appendChild(option);
            });
        } catch (e) {
            console.error("[PGFX Studio] Error enumerating devices:", e);
        }
    }

    async startCameraStream(deviceId) {
        this.stopCameraStream();

        const constraints = {
            video: deviceId ? { deviceId: { exact: deviceId } } : true
        };

        const stream = await navigator.mediaDevices.getUserMedia(constraints);
        this.cameraStream = stream;

        const videoEl = document.createElement('video');
        videoEl.autoplay = true;
        videoEl.playsInline = true;
        videoEl.srcObject = stream;
        this.cameraVideoEl = videoEl;

        videoEl.addEventListener('loadedmetadata', () => {
            const fabricVideo = new fabric.Image(videoEl, {
                left: 0,
                top: 0,
                selectable: false,
                evented: false,
                originX: 'left',
                originY: 'top',
                opacity: parseFloat(document.getElementById('pgfx-camera-opacity').value || 1)
            });

            fabricVideo.scaleX = this.canvas.getWidth() / videoEl.videoWidth;
            fabricVideo.scaleY = this.canvas.getHeight() / videoEl.videoHeight;

            this.canvas.setBackgroundImage(fabricVideo, this.canvas.renderAll.bind(this.canvas));

            // Render webcam stream loop using requestAnimationFrame
            const renderLoop = () => {
                if (this.cameraStream && videoEl.readyState === videoEl.HAVE_ENOUGH_DATA) {
                    this.canvas.requestRenderAll();
                    this.cameraAnimFrame = requestAnimationFrame(renderLoop);
                }
            };
            this.cameraAnimFrame = requestAnimationFrame(renderLoop);
        });
    }

    stopCameraStream() {
        if (this.cameraAnimFrame) {
            cancelAnimationFrame(this.cameraAnimFrame);
            this.cameraAnimFrame = null;
        }
        if (this.cameraStream) {
            this.cameraStream.getTracks().forEach(track => track.stop());
            this.cameraStream = null;
        }
        if (this.cameraVideoEl) {
            this.cameraVideoEl.pause();
            this.cameraVideoEl.srcObject = null;
            this.cameraVideoEl = null;
        }
        this.cameraActive = false;
        if (this.canvas) {
            this.canvas.setBackgroundImage(null, this.canvas.renderAll.bind(this.canvas));
        }
    }

    captureCameraFrame() {
        if (!this.cameraVideoEl || !this.cameraStream) return;

        const videoEl = this.cameraVideoEl;

        // Capture active frame on offscreen canvas
        const tempCanvas = document.createElement('canvas');
        tempCanvas.width = videoEl.videoWidth;
        tempCanvas.height = videoEl.videoHeight;
        const ctx = tempCanvas.getContext('2d');
        ctx.drawImage(videoEl, 0, 0);
        const dataUrl = tempCanvas.toDataURL('image/png');

        const opacity = parseFloat(document.getElementById('pgfx-camera-opacity').value || 1);

        fabric.Image.fromURL(dataUrl, (img) => {
            img.set({
                selectable: false,
                evented: false,
                opacity: opacity
            });

            img.scaleX = this.canvas.getWidth() / img.width;
            img.scaleY = this.canvas.getHeight() / img.height;

            // Turn off webcam streaming after snapshot capture
            this.stopCameraStream();

            // Reset toggles UI state
            const btn = document.getElementById('pgfx-camera-toggle');
            const controlsDiv = document.getElementById('pgfx-camera-controls');
            if (btn) {
                btn.innerHTML = "📹 Enable Camera";
                btn.classList.remove('pgfx-btn-danger');
            }
            if (controlsDiv) {
                controlsDiv.style.display = 'none';
            }

            this.canvas.setBackgroundImage(img, () => {
                this.canvas.renderAll();
                this._saveToHistory();
                this.scheduleNodeStateSync();
            });
        });
    }

    async fetchFontsFromServer() {
        try {
            const response = await fetch('/pgfx/fonts/list');
            if (!response.ok) return;
            const data = await response.json();

            const select = document.getElementById('pgfx-font-select');
            // Keep the current selection if any
            const currentVal = select.value || 'Arial';
            select.innerHTML = ''; // Clear existing

            // System Fonts Group
            if (data.system && data.system.length > 0) {
                const optgroup = document.createElement('optgroup');
                optgroup.label = "â”€â”€ System Fonts â”€â”€";
                data.system.forEach(font => {
                    const option = document.createElement('option');
                    option.value = font;
                    option.text = font;
                    optgroup.appendChild(option);
                });
                select.appendChild(optgroup);
            }

            // Custom Fonts Group
            if (data.custom && data.custom.length > 0) {
                const optgroup = document.createElement('optgroup');
                optgroup.label = "â”€â”€ Custom Fonts â”€â”€";
                for (const font of data.custom) {
                    const option = document.createElement('option');
                    option.value = font.name;
                    option.text = font.name;
                    optgroup.appendChild(option);

                    // Pre-load the custom font into the browser
                    const fontUrl = `/pgfx/fonts/serve/${font.filename}`;
                    await this.loadFontIntoBrowser(font.name, fontUrl, false);
                }
                select.appendChild(optgroup);
            }

            // Restore selection if possible
            if (Array.from(select.options).some(o => o.value === currentVal)) {
                select.value = currentVal;
            }
        } catch (e) {
            console.error("[PGFX Studio] Error fetching fonts", e);
        }
    }

    async loadFontIntoBrowser(fontName, fontUrl, addToSelect = true) {
        if (this.customFonts.find(f => f.name === fontName)) return; // Already loaded

        const fontFace = new FontFace(fontName, `url(${fontUrl})`);
        try {
            const loadedFont = await fontFace.load();
            document.fonts.add(loadedFont);
            this.customFonts.push({ name: fontName, url: fontUrl });

            if (addToSelect) {
                const select = document.getElementById('pgfx-font-select');
                let optgroup = select.querySelector('optgroup[label="â”€â”€ Custom Fonts â”€â”€"]');
                if (!optgroup) {
                    optgroup = document.createElement('optgroup');
                    optgroup.label = "â”€â”€ Custom Fonts â”€â”€";
                    select.appendChild(optgroup);
                }
                const option = document.createElement('option');
                option.value = fontName;
                option.text = fontName;
                optgroup.appendChild(option);
                select.value = fontName;
            }
        } catch (e) {
            console.error("[PGFX Studio] Error loading custom font:", e);
        }
    }

    updateUIForSelection() {
        const active = this.canvas.getActiveObject();
        if (!active) return;

        // Common
        document.getElementById('pgfx-opacity').value = active.opacity || 1;
        document.getElementById('pgfx-rotation').value = active.angle || 0;
        document.getElementById('pgfx-skew-x').value = active.skewX || 0;

        // Colors
        if (active.fill) document.getElementById('pgfx-color-picker').value = active.fill;
        if (active.stroke) document.getElementById('pgfx-stroke-picker').value = active.stroke;
        document.getElementById('pgfx-stroke-width').value = active.strokeWidth || 0;

        // Text specific
        if (active.type === 'i-text' || active.type === 'text') {
            document.getElementById('pgfx-font-select').value = active.fontFamily || 'Arial';
            document.getElementById('pgfx-font-size').value = active.fontSize || 100;
            document.getElementById('pgfx-font-weight').value = active.fontWeight || 'normal';
            document.getElementById('pgfx-font-style').value = active.fontStyle || 'normal';
            document.getElementById('pgfx-line-spacing').value = active.lineHeight || 1.16;
            document.getElementById('pgfx-letter-spacing').value = active.charSpacing || 0;

            // Alignment buttons visual state (optional enhancement)
            const alignment = active.textAlign || 'center';
            // Logic to highlight active alignment button could go here
        }
    }

    setupEventHandlers() {
        const commitCanvasChange = () => {
            this.canvas.renderAll();
            this._saveToHistory();
            this.scheduleNodeStateSync();
        };

        // --- ADD ELEMENTS ---
        document.getElementById('pgfx-add-text').onclick = () => {
            const font = document.getElementById('pgfx-font-select').value;
            const text = new fabric.IText("NEW TEXT", {
                left: this.canvas.getWidth() / 2, top: this.canvas.getHeight() / 2,
                fontFamily: font, fontSize: 100, fill: '#ffffff', originX: 'center', originY: 'center'
            });
            this.canvas.add(text);
            this.canvas.setActiveObject(text);
            commitCanvasChange();
        };

        document.getElementById('pgfx-add-rect').onclick = () => {
            const rect = new fabric.Rect({
                left: this.canvas.getWidth() / 2, top: this.canvas.getHeight() / 2,
                width: 200, height: 200, fill: '#ffffff', originX: 'center', originY: 'center'
            });
            this.canvas.add(rect);
            this.canvas.setActiveObject(rect);
            commitCanvasChange();
        };

        document.getElementById('pgfx-add-circle').onclick = () => {
            const circle = new fabric.Circle({
                left: this.canvas.getWidth() / 2, top: this.canvas.getHeight() / 2,
                radius: 100, fill: '#ffffff', originX: 'center', originY: 'center'
            });
            this.canvas.add(circle);
            this.canvas.setActiveObject(circle);
            commitCanvasChange();
        };

        document.getElementById('pgfx-add-triangle').onclick = () => {
            const tri = new fabric.Triangle({
                left: this.canvas.getWidth() / 2, top: this.canvas.getHeight() / 2,
                width: 200, height: 200, fill: '#ffffff', originX: 'center', originY: 'center'
            });
            this.canvas.add(tri);
            this.canvas.setActiveObject(tri);
            commitCanvasChange();
        };

        document.getElementById('pgfx-add-star').onclick = () => {
            // Simple 5-point star using Polygon
            const points = [];
            const rOuter = 100;
            const rInner = 40;
            for (let i = 0; i < 10; i++) {
                const r = (i % 2 === 0) ? rOuter : rInner;
                const angle = (Math.PI * 2 * i) / 10 - Math.PI / 2;
                points.push({ x: r * Math.cos(angle), y: r * Math.sin(angle) });
            }
            const star = new fabric.Polygon(points, {
                left: this.canvas.getWidth() / 2, top: this.canvas.getHeight() / 2,
                fill: '#ffffff', originX: 'center', originY: 'center'
            });
            this.canvas.add(star);
            this.canvas.setActiveObject(star);
            commitCanvasChange();
        };

        document.getElementById('pgfx-add-hexagon').onclick = () => {
            const points = [];
            const r = 100;
            for (let i = 0; i < 6; i++) {
                const angle = (Math.PI * 2 * i) / 6;
                points.push({ x: r * Math.cos(angle), y: r * Math.sin(angle) });
            }
            const hex = new fabric.Polygon(points, {
                left: this.canvas.getWidth() / 2, top: this.canvas.getHeight() / 2,
                fill: '#ffffff', originX: 'center', originY: 'center'
            });
            this.canvas.add(hex);
            this.canvas.setActiveObject(hex);
            commitCanvasChange();
        };

        // --- INTERACTION (ZOOM & PAN) ---
        this.canvas.on('mouse:wheel', (opt) => {
            const delta = opt.e.deltaY;
            let zoom = this.canvas.getZoom();
            zoom *= 0.999 ** delta;
            if (zoom > 20) zoom = 20;
            if (zoom < 0.01) zoom = 0.01;
            this.canvas.zoomToPoint({ x: opt.e.offsetX, y: opt.e.offsetY }, zoom);
            opt.e.preventDefault();
            opt.e.stopPropagation();
        });

        this.canvas.on('mouse:down', (opt) => {
            const evt = opt.e;
            if (evt.button === 1) { // Middle mouse button
                this.canvas.isDragging = true;
                this.canvas.selection = false;
                this.canvas.lastPosX = evt.clientX;
                this.canvas.lastPosY = evt.clientY;
            }
        });

        this.canvas.on('mouse:move', (opt) => {
            if (this.canvas.isDragging) {
                const e = opt.e;
                const vpt = this.canvas.viewportTransform;
                vpt[4] += e.clientX - this.canvas.lastPosX;
                vpt[5] += e.clientY - this.canvas.lastPosY;
                this.canvas.requestRenderAll();
                this.canvas.lastPosX = e.clientX;
                this.canvas.lastPosY = e.clientY;
            }
        });

        this.canvas.on('mouse:up', () => {
            this.canvas.setViewportTransform(this.canvas.viewportTransform);
            this.canvas.isDragging = false;
            this.canvas.selection = true;
        });

        // --- ASSET IMPORTER ---
        const fileInput = document.getElementById('pgfx-import-input');
        document.getElementById('pgfx-import-btn').onclick = () => fileInput.click();
        fileInput.onchange = (e) => {
            const file = e.target.files[0];
            if(!file) return;

            const reader = new FileReader();
            const isSVG = file.type === "image/svg+xml" || file.name.endsWith('.svg');

            const url = URL.createObjectURL(file);
            if (isSVG) {
                fabric.loadSVGFromURL(url, (objects, options) => {
                    const obj = fabric.util.groupSVGElements(objects, options);
                    if (!obj) return;
                    obj.set({ left: this.canvas.getWidth() / 2, top: this.canvas.getHeight() / 2, originX: 'center', originY: 'center' });
                    if (obj.width < 10 || obj.height < 10) obj.scaleToWidth(200);
                    if (obj.width > 800) obj.scaleToWidth(800);
                    this.canvas.add(obj);
                    this.canvas.setActiveObject(obj);
                    commitCanvasChange();
                    URL.revokeObjectURL(url);
                });
            } else {
                fabric.Image.fromURL(url, (img) => {
                    img.set({ left: this.canvas.getWidth() / 2, top: this.canvas.getHeight() / 2, originX: 'center', originY: 'center' });
                    if (img.width > 800) img.scaleToWidth(800);
                    this.canvas.add(img);
                    this.canvas.setActiveObject(img);
                    commitCanvasChange();
                    URL.revokeObjectURL(url);
                });
            }
            fileInput.value = '';
        };

        // --- CUSTOM FONTS ---
        const fontInput = document.getElementById('pgfx-font-upload');
        document.getElementById('pgfx-upload-font-btn').onclick = () => fontInput.click();
        fontInput.onchange = async (e) => {
            const file = e.target.files[0];
            if(!file) return;

            const formData = new FormData();
            formData.append('font', file);

            try {
                const response = await fetch('/pgfx/fonts/upload', {
                    method: 'POST',
                    body: formData
                });

                if (response.ok) {
                    const data = await response.json();
                    const fontUrl = `/pgfx/fonts/serve/${data.filename}`;
                    await this.loadFontIntoBrowser(data.name, fontUrl, true);

                    // If text selected, apply it immediately
                    const active = this.canvas.getActiveObject();
                    if(active && active.type.includes('text')) {
                        active.set('fontFamily', data.name);
                        commitCanvasChange();
                    }
                } else {
                    console.error("[PGFX Studio] Font upload failed", await response.text());
                }
            } catch (err) {
                console.error("[PGFX Studio] Error uploading font:", err);
            }
            fontInput.value = '';
        };

        // --- STYLING ---
        document.getElementById('pgfx-color-picker').oninput = (e) => {
            const active = this.canvas.getActiveObject();
            if (active) {
                if (active.type === 'group') {
                    active.getObjects().forEach(o => o.set('fill', e.target.value));
                } else {
                    active.set('fill', e.target.value);
                }
                commitCanvasChange();
            }
        };

        document.getElementById('pgfx-stroke-picker').oninput = (e) => {
            const active = this.canvas.getActiveObject();
            if (active) {
                if (active.type === 'group') {
                    active.getObjects().forEach(o => o.set('stroke', e.target.value));
                } else {
                    active.set('stroke', e.target.value);
                }
                commitCanvasChange();
            }
        };

        document.getElementById('pgfx-stroke-width').oninput = (e) => {
            const active = this.canvas.getActiveObject();
            if (active) {
                active.set('strokeWidth', parseInt(e.target.value));
                commitCanvasChange();
            }
        };

        document.getElementById('pgfx-bg-picker').oninput = (e) => {
            this.pageBackgroundColor = e.target.value;
            this.canvas.backgroundColor = 'transparent';
            commitCanvasChange();
        };

        document.getElementById('pgfx-font-select').onchange = (e) => {
            const active = this.canvas.getActiveObject();
            if (active && active.type.includes('text')) {
                active.set('fontFamily', e.target.value);
                commitCanvasChange();
            }
        };

        document.getElementById('pgfx-font-size').oninput = (e) => {
            const active = this.canvas.getActiveObject();
            if (active && active.type.includes('text')) {
                active.set('fontSize', parseInt(e.target.value));
                commitCanvasChange();
            }
        };

        document.getElementById('pgfx-font-weight').onchange = (e) => {
            const active = this.canvas.getActiveObject();
            if (active && active.type.includes('text')) {
                active.set('fontWeight', e.target.value);
                commitCanvasChange();
            }
        };

        document.getElementById('pgfx-font-style').onchange = (e) => {
            const active = this.canvas.getActiveObject();
            if (active && active.type.includes('text')) {
                active.set('fontStyle', e.target.value);
                commitCanvasChange();
            }
        };

        document.getElementById('pgfx-letter-spacing').oninput = (e) => {
            const active = this.canvas.getActiveObject();
            if (active && active.type.includes('text')) {
                active.set('charSpacing', parseInt(e.target.value));
                commitCanvasChange();
            }
        };

        document.getElementById('pgfx-line-spacing').oninput = (e) => {
            const active = this.canvas.getActiveObject();
            if (active && active.type.includes('text')) {
                active.set('lineHeight', parseFloat(e.target.value));
                commitCanvasChange();
            }
        };

        const setTextAlign = (align) => {
            const active = this.canvas.getActiveObject();
            if (active && active.type.includes('text')) {
                active.set('textAlign', align);
                commitCanvasChange();
            }
        };
        document.getElementById('pgfx-align-left').onclick = () => setTextAlign('left');
        document.getElementById('pgfx-align-center').onclick = () => setTextAlign('center');
        document.getElementById('pgfx-align-right').onclick = () => setTextAlign('right');
        document.getElementById('pgfx-align-justify').onclick = () => setTextAlign('justify');

        document.getElementById('pgfx-rotation').oninput = (e) => {
            const active = this.canvas.getActiveObject();
            if (active) {
                active.rotate(parseInt(e.target.value));
                commitCanvasChange();
            }
        };

        document.getElementById('pgfx-skew-x').oninput = (e) => {
            const active = this.canvas.getActiveObject();
            if (active) {
                active.set('skewX', parseInt(e.target.value));
                commitCanvasChange();
            }
        };

        document.getElementById('pgfx-opacity').oninput = (e) => {
            const active = this.canvas.getActiveObject();
            if (active) {
                active.set('opacity', parseFloat(e.target.value));
                commitCanvasChange();
            }
        };

        // --- LAYER MANIPULATION ---
        document.getElementById('pgfx-layer-front').onclick = () => {
            const active = this.canvas.getActiveObject();
            if(active) { active.bringToFront(); commitCanvasChange(); }
        };
        document.getElementById('pgfx-layer-up').onclick = () => {
            const active = this.canvas.getActiveObject();
            if(active) { active.bringForward(); commitCanvasChange(); }
        };
        document.getElementById('pgfx-layer-down').onclick = () => {
            const active = this.canvas.getActiveObject();
            if(active) { active.sendBackwards(); commitCanvasChange(); }
        };
        document.getElementById('pgfx-layer-bottom').onclick = () => {
            const active = this.canvas.getActiveObject();
            if(active) { active.sendToBack(); commitCanvasChange(); }
        };
        document.getElementById('pgfx-align-h').onclick = () => {
            const active = this.canvas.getActiveObject();
            if(active) { active.centerH(); active.setCoords(); commitCanvasChange(); }
        };
        document.getElementById('pgfx-align-v').onclick = () => {
            const active = this.canvas.getActiveObject();
            if(active) { active.centerV(); active.setCoords(); commitCanvasChange(); }
        };
        document.getElementById('pgfx-clone').onclick = () => {
            const active = this.canvas.getActiveObject();
            if(active) {
                active.clone((cloned) => {
                    cloned.set({ left: active.left + 30, top: active.top + 30 });
                    this.canvas.add(cloned);
                    this.canvas.setActiveObject(cloned);
                    commitCanvasChange();
                });
            }
        };

        // --- OBJECT ACTIONS ---
        document.getElementById('pgfx-group-btn').onclick = () => {
            const active = this.canvas.getActiveObject();
            if (!active || active.type !== 'activeSelection') return;
            active.toGroup();
            this.canvas.requestRenderAll();
            this._saveToHistory();
            this.scheduleNodeStateSync();
        };

        document.getElementById('pgfx-ungroup-btn').onclick = () => {
            const active = this.canvas.getActiveObject();
            if (!active || active.type !== 'group') return;
            active.toActiveSelection();
            this.canvas.requestRenderAll();
            this._saveToHistory();
            this.scheduleNodeStateSync();
        };

        document.getElementById('pgfx-combine-btn').onclick = () => {
            const active = this.canvas.getActiveObject();
            if (!active || active.type !== 'activeSelection') return;

            const objects = active.getObjects();
            let combinedPathData = '';

            objects.forEach(obj => {
                if (obj.type === 'path') {
                    // fabric.Path.toPathData can be complex, for simple combined paths
                    // we can concatenate the commands
                    const path = obj.path;
                    fabric.util.transformPath(path, obj.calcTransformMatrix());
                    path.forEach(cmd => {
                        combinedPathData += cmd.join(' ') + ' ';
                    });
                }
            });

            if (combinedPathData) {
                const newPath = new fabric.Path(combinedPathData, {
                    fill: objects[0].fill,
                    stroke: objects[0].stroke,
                    strokeWidth: objects[0].strokeWidth,
                    fillRule: 'evenodd' // Essential for cutouts
                });
                this.canvas.remove(...objects);
                this.canvas.discardActiveObject();
                this.canvas.add(newPath);
                this.canvas.setActiveObject(newPath);
                commitCanvasChange();
            }
        };

        document.getElementById('pgfx-break-btn').onclick = () => {
            const active = this.canvas.getActiveObject();
            if (!active || active.type !== 'path') return;

            const pathData = active.path;
            const subPaths = [];
            let currentSubPath = [];

            pathData.forEach(cmd => {
                if (cmd[0] === 'M' && currentSubPath.length > 0) {
                    subPaths.push(currentSubPath);
                    currentSubPath = [];
                }
                currentSubPath.push(cmd);
            });
            if (currentSubPath.length > 0) subPaths.push(currentSubPath);

            if (subPaths.length > 1) {
                const newObjects = subPaths.map(p => {
                    return new fabric.Path(p, {
                        fill: active.fill,
                        stroke: active.stroke,
                        strokeWidth: active.strokeWidth,
                        left: active.left,
                        top: active.top
                    });
                });
                this.canvas.remove(active);
                this.canvas.add(...newObjects);
                const sel = new fabric.ActiveSelection(newObjects, { canvas: this.canvas });
                this.canvas.setActiveObject(sel);
                commitCanvasChange();
            }
        };

        // Selection and modification events
        this.canvas.on('selection:created', () => this.updateUIForSelection());
        this.canvas.on('selection:updated', () => this.updateUIForSelection());
        this.canvas.on('object:modified', () => {
            this._saveToHistory();
            this.scheduleNodeStateSync();
        });
        this.canvas.on('object:removed', () => {
            this._saveToHistory();
            this.scheduleNodeStateSync();
        });
        this.canvas.on('text:changed', () => {
            this._saveToHistory();
            this.scheduleNodeStateSync();
        });
        this.canvas.on('text:editing:exited', () => {
            this._saveToHistory();
            this.scheduleNodeStateSync();
        });
        this.canvas.on('path:created', (e) => {
            if (e.path) {
                e.path.set('name', 'pgfx_free_draw');
            }
            this._saveToHistory();
            this.scheduleNodeStateSync();
        });

        // Figma/Illustrator-style Page Background dynamic sheet draw (Bug 4)
        this.canvas.on('before:render', () => {
            const ctx = this.canvas.getContext();
            const vpt = this.canvas.viewportTransform;
            ctx.save();
            ctx.transform(vpt[0], vpt[1], vpt[2], vpt[3], vpt[4], vpt[5]); // Transform to page coordinate system

            // Soft realistic drop shadow for the design canvas sheet
            ctx.shadowColor = 'rgba(0, 0, 0, 0.5)';
            ctx.shadowBlur = 24 / this.canvas.getZoom();
            ctx.shadowOffsetX = 4 / this.canvas.getZoom();
            ctx.shadowOffsetY = 8 / this.canvas.getZoom();

            // Render actual page background fill
            ctx.fillStyle = this.pageBackgroundColor || '#000000';
            ctx.fillRect(0, 0, this.canvas.getWidth(), this.canvas.getHeight());

            ctx.restore();
        });

        // Locked page boundary dashed outline (Bug 4)
        this.canvas.on('after:render', () => {
            if (this.isExporting) return;
            const ctx = this.canvas.getContext();
            const vpt = this.canvas.viewportTransform;
            ctx.save();
            ctx.transform(vpt[0], vpt[1], vpt[2], vpt[3], vpt[4], vpt[5]); // Zoom and pan outline with page coordinates

            ctx.strokeStyle = 'rgba(6, 182, 212, 0.8)';
            const zoom = this.canvas.getZoom();
            ctx.lineWidth = 2 / zoom;
            ctx.setLineDash([4 / zoom, 4 / zoom]);
            ctx.strokeRect(0, 0, this.canvas.getWidth(), this.canvas.getHeight());

            ctx.restore();
        });

        // Keyboard Shortcuts (Delete & Tab Selection)
        window.addEventListener('keydown', (e) => {
            if(!this.overlay.classList.contains('active')) return;

            // Don't trigger if user is typing in an input, textarea or editing text on canvas
            const activeObject = this.canvas.getActiveObject();
            const isTyping = e.target instanceof HTMLInputElement ||
                             e.target instanceof HTMLTextAreaElement ||
                             (activeObject && activeObject.isEditing);

            if(isTyping && !e.ctrlKey) return; // Allow Ctrl shortcuts like Ctrl+G even when typing, but block single keys

            // DELETE / BACKSPACE: Remove object
            if (e.key === 'Delete' || e.key === 'Backspace') {
                if (activeObject) {
                    if (activeObject === this.currentlyEditingPoly) {
                        this.endNodeEditMode();
                    }
                    this.canvas.remove(activeObject);
                    this.canvas.discardActiveObject();
                    commitCanvasChange();
                }
            }

            // TAB: Cycle through objects
            if (e.key === 'Tab') {
                e.preventDefault(); // Prevent focus switching out of browser
                const objects = this.canvas.getObjects();
                if (objects.length === 0) return;

                let nextIndex = 0;
                if (activeObject) {
                    const currentIndex = objects.indexOf(activeObject);
                    nextIndex = (currentIndex + (e.shiftKey ? -1 : 1) + objects.length) % objects.length;       
                }

                this.canvas.setActiveObject(objects[nextIndex]);
                this.canvas.requestRenderAll();
                this.updateUIForSelection();
            }

            // TOOL SHORTCUTS
            if (e.key.toLowerCase() === 's') {
                document.getElementById('pgfx-tool-select').click();
            }
            if (e.key.toLowerCase() === 'd') {
                document.getElementById('pgfx-tool-draw').click();
            }

            // Group / Ungroup Shortcuts
            if (e.ctrlKey && e.key.toLowerCase() === 'g') {
                e.preventDefault();
                if (e.shiftKey) {
                    document.getElementById('pgfx-ungroup-btn').click();
                } else {
                    document.getElementById('pgfx-group-btn').click();
                }
            }

            // Undo / Redo Shortcuts
            if (e.ctrlKey && e.key.toLowerCase() === 'z') {
                e.preventDefault();
                this.undo();
            }
            if (e.ctrlKey && e.key.toLowerCase() === 'y') {
                e.preventDefault();
                this.redo();
            }
        });

        document.getElementById('pgfx-fit-btn').onclick = () => this.fitCanvasToView();

        document.getElementById('pgfx-canvas-preset').onchange = (e) => {
            const val = e.target.value;
            if (val === 'custom') {
                document.getElementById('pgfx-canvas-width').disabled = false;
                document.getElementById('pgfx-canvas-height').disabled = false;
            } else {
                document.getElementById('pgfx-canvas-width').disabled = true;
                document.getElementById('pgfx-canvas-height').disabled = true;
                const [w, h] = val.split('x').map(Number);
                this.targetWidth = w;
                this.targetHeight = h;
                document.getElementById('pgfx-canvas-width').value = w;
                document.getElementById('pgfx-canvas-height').value = h;
                this.fitCanvasToView();
                commitCanvasChange();
            }
        };

        document.getElementById('pgfx-canvas-width').oninput = (e) => {
            const val = parseInt(e.target.value);
            if (val > 0) {
                this.targetWidth = val;
                this.fitCanvasToView();
                commitCanvasChange();
            }
        };

        document.getElementById('pgfx-canvas-height').oninput = (e) => {
            const val = parseInt(e.target.value);
            if (val > 0) {
                this.targetHeight = val;
                this.fitCanvasToView();
                commitCanvasChange();
            }
        };
        document.getElementById('pgfx-canvas-swap').onclick = () => {
            const temp = this.targetWidth;
            this.targetWidth = this.targetHeight;
            this.targetHeight = temp;
            document.getElementById('pgfx-canvas-width').value = this.targetWidth;
            document.getElementById('pgfx-canvas-height').value = this.targetHeight;
            document.getElementById('pgfx-canvas-preset').value = "custom";
            this.fitCanvasToView();
            commitCanvasChange();
        };

        // --- SAVE ACTION ---
        document.getElementById('pgfx-undo-btn').onclick = () => this.undo();
        document.getElementById('pgfx-redo-btn').onclick = () => this.redo();

        document.getElementById('pgfx-save-btn').onclick = () => {
            this.applyCanvasStateToNode({ bumpSeed: true, closeAfter: true });
        };

        document.getElementById('pgfx-cancel-btn').onclick = () => this.close();

        // --- EXPORT SVG ACTION ---
        document.getElementById('pgfx-export-svg-btn').onclick = () => {
            if (!this.canvas) return;
            const svgData = this.canvas.toSVG();
            const blob = new Blob([svgData], { type: 'image/svg+xml;charset=utf-8' });
            const url = URL.createObjectURL(blob);
            const link = document.createElement('a');
            link.href = url;
            link.download = `PGFX_Design_${+new Date()}.svg`;
            document.body.appendChild(link);
            link.click();
            document.body.removeChild(link);
            URL.revokeObjectURL(url);
        };

        // --- DRAWING TOOLBAR LOGIC ---
        const btnSelect = document.getElementById('pgfx-tool-select');
        const btnDraw   = document.getElementById('pgfx-tool-draw');
        const brushType = document.getElementById('pgfx-brush-type');
        const brushSize = document.getElementById('pgfx-brush-size');
        const brushCol  = document.getElementById('pgfx-brush-color');
        const brushOpac = document.getElementById('pgfx-brush-opacity');

        const updateBrush = () => {
            if (!this.canvas) return;
            const type = brushType.value;
            const color = brushCol.value;
            const size = parseInt(brushSize.value);
            const opacity = parseFloat(brushOpac.value);

            // Convert hex to RGBA for opacity support in free drawing
            const r = parseInt(color.slice(1, 3), 16);
            const g = parseInt(color.slice(3, 5), 16);
            const b = parseInt(color.slice(5, 7), 16);
            const rgba = `rgba(${r},${g},${b},${opacity})`;

            if (type === 'Pencil') {
                this.canvas.freeDrawingBrush = new fabric.PencilBrush(this.canvas);
            } else if (type === 'Spray') {
                this.canvas.freeDrawingBrush = new fabric.SprayBrush(this.canvas);
            } else if (type === 'Circle') {
                this.canvas.freeDrawingBrush = new fabric.CircleBrush(this.canvas);
            }

            this.canvas.freeDrawingBrush.color = rgba;
            this.canvas.freeDrawingBrush.width = size;
        };

        btnSelect.onclick = () => {
            this.endNodeEditMode();
            this.canvas.isDrawingMode = false;
            btnSelect.classList.add('pgfx-btn-primary');
            btnDraw.classList.remove('pgfx-btn-primary');
        };

        btnDraw.onclick = () => {
            this.endNodeEditMode();
            this.canvas.isDrawingMode = true;
            btnDraw.classList.add('pgfx-btn-primary');
            btnSelect.classList.remove('pgfx-btn-primary');
            document.getElementById('pgfx-tool-node').classList.remove('pgfx-btn-primary');
            updateBrush();
        };

        document.getElementById('pgfx-tool-node').onclick = () => {
            this.toggleNodeEditMode();
        };

        brushType.onchange = updateBrush;
        brushSize.oninput  = updateBrush;
        brushCol.oninput   = updateBrush;
        brushOpac.oninput  = updateBrush;

        document.getElementById('pgfx-clear-draw').onclick = () => {
            if (!this.canvas) return;
            // Only clear paths drawn using the drawing brush (tagged with 'pgfx_free_draw')
            const objects = this.canvas.getObjects().filter(o => o.name === 'pgfx_free_draw');
            if (objects.length > 0) {
                this.canvas.remove(...objects);
                commitCanvasChange();
                console.log("[PGFX Studio] Cleared " + objects.length + " sketch elements.");
            }
        };

        // --- CAMERA OVERLAY EVENTS ---
        const cameraToggle = document.getElementById('pgfx-camera-toggle');
        if (cameraToggle) {
            cameraToggle.onclick = () => this.toggleCamera();
        }
        const cameraCapture = document.getElementById('pgfx-camera-capture');
        if (cameraCapture) {
            cameraCapture.onclick = () => this.captureCameraFrame();
        }
        const cameraSelect = document.getElementById('pgfx-camera-select');
        if (cameraSelect) {
            cameraSelect.onchange = (e) => {
                if (this.cameraActive) {
                    this.startCameraStream(e.target.value);
                }
            };
        }
        const cameraOpacity = document.getElementById('pgfx-camera-opacity');
        if (cameraOpacity) {
            cameraOpacity.oninput = (e) => {
                const bgImage = this.canvas.backgroundImage;
                if (bgImage) {
                    bgImage.set('opacity', parseFloat(e.target.value));
                    this.canvas.requestRenderAll();
                }
            };
        }
    }

    initDOM() {
        let overlay = document.getElementById('pgfx-studio-overlay');
        if (!overlay) {
            overlay = document.createElement('div');
            overlay.id = 'pgfx-studio-overlay';
            overlay.innerHTML = `
                <div class="pgfx-studio-container">
                    <div class="pgfx-studio-header">
                        <div class="pgfx-studio-title">
                            <span style="font-size: 24px;">🎨</span> PGFX Logo Designer Studio
                        </div>
                        <div class="pgfx-row">
                            <button id="pgfx-cancel-btn" class="pgfx-btn">Cancel</button>
                            <div class="pgfx-toolbar-separator"></div>
                            <button id="pgfx-undo-btn" class="pgfx-btn" title="Undo (Ctrl+Z)">↶ Undo</button>
                            <button id="pgfx-redo-btn" class="pgfx-btn" title="Redo (Ctrl+Y)">↷ Redo</button>
                            <div class="pgfx-toolbar-separator"></div>
                            <button id="pgfx-fit-btn" class="pgfx-btn" title="Center and fit the canvas to the current window.">🔍 Fit View</button>
                            <button id="pgfx-export-svg-btn" class="pgfx-btn" title="Download the current design as a clean SVG file.">📋 Export SVG</button>
                            <button id="pgfx-save-btn" class="pgfx-btn pgfx-btn-primary" title="Apply the design to the node and close the window.">💾 Save State & Apply</button>
                        </div>
                    </div>
                    <div class="pgfx-studio-body">
                        <div class="pgfx-studio-sidebar">

                            <!-- CANVAS SETTINGS -->
                            <div class="pgfx-input-group">
                                <label class="pgfx-label">Canvas Properties</label>
                                <div class="pgfx-row">
                                    <span style="font-size: 11px; color:#aaa; width: 60px;">Preset</span>       
                                    <select id="pgfx-canvas-preset" class="pgfx-select" style="flex: 1;">
                                        <option value="1024x1024">Square (1:1)</option>
                                        <optgroup label="Landscape">
                                            <option value="1920x1080">16:9 Landscape</option>
                                            <option value="1536x1024">3:2 Landscape</option>
                                            <option value="2560x1080">21:9 Ultra-Wide</option>
                                            <option value="1280x1024">5:4 Classic</option>
                                        </optgroup>
                                        <optgroup label="Portrait">
                                            <option value="1080x1920">9:16 Story</option>
                                            <option value="1080x1350">4:5 Social</option>
                                            <option value="1024x1536">2:3 Portrait</option>
                                        </optgroup>
                                        <option value="custom">Custom...</option>
                                    </select>
                                </div>
                                <div class="pgfx-row">
                                    <span style="font-size: 11px; color:#aaa; width: 20px;">W</span>
                                    <input type="number" id="pgfx-canvas-width" value="1024" style="width: 65px; background: #000; border: 1px solid rgba(255,255,255,0.1); color: white; border-radius: 4px; padding: 4px;" disabled>
                                    <button id="pgfx-canvas-swap" class="pgfx-btn" style="padding: 2px 6px; min-width: unset; height: 26px; margin: 0 4px;" title="Swap Dimensions">⇄</button>
                                    <span style="font-size: 11px; color:#aaa; width: 20px; text-align: center;">H</span>
                                    <input type="number" id="pgfx-canvas-height" value="1024" style="width: 65px; background: #000; border: 1px solid rgba(255,255,255,0.1); color: white; border-radius: 4px; padding: 4px;" disabled>
                                </div>
                                <div class="pgfx-row" style="justify-content: space-between;">
                                    <span style="font-size: 11px; color:#aaa;">Canvas BG</span>
                                    <input type="color" id="pgfx-bg-picker" value="#000000" style="cursor: pointer; background: none; border: none;">
                                </div>
                            </div>

                             <!-- ASSETS & TEXT -->
                            <div class="pgfx-input-group">
                                <label class="pgfx-label">Creation Tools</label>
                                <button id="pgfx-add-text" class="pgfx-btn" style="justify-content: flex-start;" title="Add an editable text layer. Double-click the text on canvas to type.">📝 Add Text</button>
                                <div class="pgfx-row">
                                    <button id="pgfx-add-rect" class="pgfx-btn" style="flex: 1;" title="Add a filled rectangle shape to the canvas.">⬛ Rect</button>
                                    <button id="pgfx-add-circle" class="pgfx-btn" style="flex: 1;" title="Add a filled circle/ellipse shape to the canvas.">⚫ Circle</button>
                                </div>
                                <div class="pgfx-row">
                                    <button id="pgfx-add-triangle" class="pgfx-btn" style="flex: 1;" title="Add a triangle shape.">🔺 Tri</button>
                                    <button id="pgfx-add-star" class="pgfx-btn" style="flex: 1;" title="Add a star shape.">⭐ Star</button>
                                    <button id="pgfx-add-hexagon" class="pgfx-btn" style="flex: 1;" title="Add a hexagon shape.">⬢ Hex</button>
                                </div>
                                <button id="pgfx-import-btn" class="pgfx-btn" style="justify-content: flex-start;" title="Import a PNG, JPG, or SVG file onto the canvas. SVGs are imported as editable vector groups.">📥 Import SVG / Image</button>
                                <input type="file" id="pgfx-import-input" class="hidden-file-input" accept="image/*,.svg">
                            </div>

                            <!-- CAMERA OVERLAY MOCKUP -->
                            <div class="pgfx-input-group">
                                <label class="pgfx-label">Camera Overlay Mockup</label>
                                <div class="pgfx-row">
                                    <button id="pgfx-camera-toggle" class="pgfx-btn" style="flex: 1;" title="Enable or disable your live camera feed as a background overlay.">📹 Enable Camera</button>
                                </div>
                                <div id="pgfx-camera-controls" style="display: none; flex-direction: column; gap: 8px; margin-top: 8px; width: 100%;">
                                    <div class="pgfx-row">
                                        <span style="font-size: 11px; color:#aaa; width: 60px;">Source</span>   
                                        <select id="pgfx-camera-select" class="pgfx-select" style="flex: 1;">   
                                            <!-- Populated dynamically -->
                                        </select>
                                    </div>
                                    <button id="pgfx-camera-capture" class="pgfx-btn pgfx-btn-primary" title="Capture the current camera frame as a static background and stop the live camera feed.">📸 Capture Photo</button>
                                    <div class="pgfx-row">
                                        <span style="font-size: 11px; color:#aaa; width: 60px;">Opacity</span>  
                                        <input type="range" id="pgfx-camera-opacity" min="0.1" max="1" step="0.05" value="1" style="flex: 1;">
                                    </div>
                                </div>
                            </div>

                            <!-- TYPOGRAPHY -->
                            <div class="pgfx-input-group">
                                <label class="pgfx-label">Typography</label>
                                <div class="pgfx-row">
                                    <select id="pgfx-font-select" class="pgfx-select" style="flex: 1;">
                                        <!-- Populated via API -->
                                    </select>
                                    <button id="pgfx-upload-font-btn" class="pgfx-btn pgfx-btn-icon" title="Upload a custom font (.ttf, .otf, .woff). Custom fonts are saved for use in PGFX apps.">⬆️</button>
                                    <input type="file" id="pgfx-font-upload" class="hidden-file-input" accept=".ttf,.otf,.woff">
                                </div>
                                <div class="pgfx-row">
                                    <select id="pgfx-font-weight" class="pgfx-select" style="flex: 1;">
                                        <option value="normal">Normal</option>
                                        <option value="bold">Bold</option>
                                        <option value="100">100 (Thin)</option>
                                        <option value="200">200</option>
                                        <option value="300">300</option>
                                        <option value="400">400</option>
                                        <option value="500">500</option>
                                        <option value="600">600</option>
                                        <option value="700">700</option>
                                        <option value="800">800</option>
                                        <option value="900">900 (Black)</option>
                                    </select>
                                    <select id="pgfx-font-style" class="pgfx-select" style="flex: 1;">
                                        <option value="normal">Normal</option>
                                        <option value="italic">Italic</option>
                                    </select>
                                </div>
                                <div class="pgfx-row" style="width: 100%; justify-content: space-between;">     
                                    <button id="pgfx-align-left" class="pgfx-btn pgfx-btn-text" title="Left Align">LEFT</button>
                                    <button id="pgfx-align-center" class="pgfx-btn pgfx-btn-text" title="Center Align">CENT</button>
                                    <button id="pgfx-align-right" class="pgfx-btn pgfx-btn-text" title="Right Align">RIGHT</button>
                                    <button id="pgfx-align-justify" class="pgfx-btn pgfx-btn-text" title="Justify">JUST</button>
                                </div>
                                <div class="pgfx-row">
                                    <span style="font-size: 11px; color:#aaa; width: 60px;">Size</span>
                                    <input type="range" id="pgfx-font-size" min="10" max="600" value="100" style="flex: 1;">
                                </div>
                                <div class="pgfx-row">
                                    <span style="font-size: 11px; color:#aaa; width: 60px;">Letter</span>       
                                    <input type="range" id="pgfx-letter-spacing" min="-100" max="1000" value="0" style="flex: 1;">
                                </div>
                                <div class="pgfx-row">
                                    <span style="font-size: 11px; color:#aaa; width: 60px;">Line</span>
                                    <input type="range" id="pgfx-line-spacing" min="0.1" max="5" step="0.05" value="1.16" style="flex: 1;">
                                </div>
                            </div>

                            <!-- STYLING & STROKE -->
                            <div class="pgfx-input-group">
                                <label class="pgfx-label">Coloring & Stroke</label>
                                <div class="pgfx-row" style="justify-content: space-between;">
                                    <span style="font-size: 11px; color:#aaa;">Fill Color</span>
                                    <input type="color" id="pgfx-color-picker" value="#ffffff" style="cursor: pointer; background: none; border: none;">
                                </div>
                                <div class="pgfx-row" style="justify-content: space-between;">
                                    <span style="font-size: 11px; color:#aaa;">Stroke Color</span>
                                    <input type="color" id="pgfx-stroke-picker" value="#000000" style="cursor: pointer; background: none; border: none;">
                                </div>
                                <div class="pgfx-row">
                                    <span style="font-size: 11px; color:#aaa; width: 60px;">Stroke</span>       
                                    <input type="range" id="pgfx-stroke-width" min="0" max="100" value="0" style="flex: 1;">
                                </div>
                            </div>

                            <!-- TRANSFORMS -->
                            <div class="pgfx-input-group">
                                <label class="pgfx-label">Transforms</label>
                                <div class="pgfx-row">
                                    <span style="font-size: 11px; color:#aaa; width: 60px;">Rotate</span>       
                                    <input type="range" id="pgfx-rotation" min="-180" max="180" value="0" style="flex: 1;">
                                </div>
                                <div class="pgfx-row">
                                    <span style="font-size: 11px; color:#aaa; width: 60px;">Skew X</span>       
                                    <input type="range" id="pgfx-skew-x" min="-100" max="100" value="0" style="flex: 1;">
                                </div>
                                <div class="pgfx-row">
                                    <span style="font-size: 11px; color:#aaa; width: 60px;">Opacity</span>      
                                    <input type="range" id="pgfx-opacity" min="0" max="1" step="0.05" value="1" style="flex: 1;">
                                </div>
                            </div>

                            <!-- LAYER CONTROLS -->
                            <div class="pgfx-input-group">
                                <label class="pgfx-label">Layer Controls</label>
                                <div class="pgfx-row">
                                    <button id="pgfx-layer-front" class="pgfx-btn" style="flex:1;" title="Bring to Front: Move selection to the very top.">🔝 Front</button>
                                    <button id="pgfx-layer-up" class="pgfx-btn" style="flex:1;" title="Bring Forward: Move selected object one layer up.">🔼 Forward</button>
                                </div>
                                <div class="pgfx-row">
                                    <button id="pgfx-layer-down" class="pgfx-btn" style="flex:1;" title="Send Backward: Move selected object one layer down.">🔽 Back</button>
                                    <button id="pgfx-layer-bottom" class="pgfx-btn" style="flex:1;" title="Send to Bottom: Move selection to the very bottom.">⬇️ Bottom</button>
                                </div>
                            </div>

                            <!-- OBJECT ACTIONS -->
                            <div class="pgfx-input-group">
                                <label class="pgfx-label">Object Actions</label>
                                <div class="pgfx-row">
                                    <button id="pgfx-group-btn" class="pgfx-btn" style="flex:1;" title="Group Selected: Combine multiple objects into one movable group.">📦 Group</button>
                                    <button id="pgfx-ungroup-btn" class="pgfx-btn" style="flex:1;" title="Ungroup Selected: Break a group back into individual parts.">📂 Ungroup</button>
                                </div>
                                <div class="pgfx-row">
                                    <button id="pgfx-combine-btn" class="pgfx-btn" style="flex:1;" title="Combine Paths: Merge paths into one object (creates cutouts/holes).">➕ Combine</button>
                                    <button id="pgfx-break-btn" class="pgfx-btn" style="flex:1;" title="Break Apart: Split a complex path into its individual shapes.">✂️ Break</button>
                                </div>
                                <div class="pgfx-row">
                                    <button id="pgfx-align-h" class="pgfx-btn" style="flex:1;" title="Center Horizontally: Move selected object to the horizontal center of the canvas.">↔️ H-Center</button>
                                    <button id="pgfx-align-v" class="pgfx-btn" style="flex:1;" title="Center Vertically: Move selected object to the vertical center of the canvas.">↕️ V-Center</button>
                                </div>
                                <button id="pgfx-clone" class="pgfx-btn" style="justify-content: flex-start;" title="Duplicate the selected object, offset by 30px.">👯 Duplicate Selected</button>
                            </div>

                            <!-- STUDIO CONTROLS REFERENCE -->
                            <details style="background: rgba(6,182,212,0.05); border: 1px solid rgba(6,182,212,0.2); border-radius: 8px; padding: 12px; margin-bottom: 8px;">
                                <summary style="font-size: 11px; font-weight: 800; color: #06b6d4; cursor: pointer; text-transform: uppercase; letter-spacing: 1px;">🎮 Studio Controls</summary>
                                <div style="margin-top: 10px; font-size: 11px; color: #a1a1aa; line-height: 1.7;">
                                    <b style="color:#e4e4e7;">Drawing Tools</b><br>
                                    â€¢ <span style="color:#06b6d4;">D</span>: Free-draw Mode (Pencil/Spray/Circle)<br>
                                    â€¢ <span style="color:#06b6d4;">S</span>: Selection Mode (Move/Edit)<br>   
                                    â€¢ <span style="color:#06b6d4;">Brush Settings</span>: Set size, color, and opacity in the top bar.<br><br>

                                    <b style="color:#e4e4e7;">Navigation</b><br>
                                    â€¢ <span style="color:#06b6d4;">Mouse Wheel</span>: Zoom In/Out<br>        
                                    â€¢ <span style="color:#06b6d4;">Middle Mouse Click</span>: Pan/Grab Canvas<br><br>

                                    <b style="color:#e4e4e7;">Keyboard</b><br>
                                    â€¢ <span style="color:#06b6d4;">TAB / SHIFT+TAB</span>: Cycle Objects<br>  
                                    â€¢ <span style="color:#06b6d4;">DEL / BACKSPACE</span>: Delete Selected<br><br>

                                    <b style="color:#e4e4e7;">Shortcuts</b><br>
                                    â€¢ <span style="color:#06b6d4;">Double-Click</span>: Edit Text Layers<br>  
                                    â€¢ <span style="color:#06b6d4;">Drag Handles</span>: Scale / Rotate<br><br>

                                    <b style="color:#e4e4e7;">Sync Note</b><br>
                                    Editing the 'Primary Text' (the first one added) will auto-sync with the node's text input on Save.
                                </div>
                            </details>

                            <!-- NODE WIDGET REFERENCE PANEL -->
                            <details style="background: rgba(6,182,212,0.05); border: 1px solid rgba(6,182,212,0.2); border-radius: 8px; padding: 12px;">
                                <summary style="font-size: 11px; font-weight: 800; color: #06b6d4; cursor: pointer; text-transform: uppercase; letter-spacing: 1px;">📋 Node Widget Reference</summary>
                                <div style="margin-top: 10px; font-size: 11px; color: #a1a1aa; line-height: 1.7;">
                                    <p style="color:#06b6d4; font-weight:700; margin-bottom:4px;">This window = visual layout only.</p>
                                    <p>The following widgets on the node control the <b>AI prompt</b> sent to your model:</p>
                                    <hr style="border-color: rgba(255,255,255,0.05); margin: 8px 0;">
                                    <b style="color:#e4e4e7;">output_intent</b><br>
                                    VECTOR: Enforces strict flat 2-D. No lighting, no 3D. Best for vinyl/screen-print.<br>
                                    RASTER: Enables shading, depth, cinematic lighting for print/photo use.<br><br>
                                    <b style="color:#e4e4e7;">background_mode</b><br>
                                    simple: Solid background colour (use Canvas BG above).<br>
                                    preset: Use a named environment scene.<br>
                                    custom: Write your own background description.<br>
                                    none: No background instruction sent to model.<br><br>
                                    <b style="color:#e4e4e7;">background_preset</b><br>
                                    Active when background_mode = preset. Selects a scene environment (e.g. space nebula, city street).<br><br>
                                    <b style="color:#e4e4e7;">background_custom_prompt</b><br>
                                    Active when background_mode = custom. Describe any background you want.<br><br>
                                    <b style="color:#e4e4e7;">scene_interaction</b><br>
                                    Describes how the design physically interacts with its environment. E.g. "Letters sinking into sand."<br><br>
                                    <b style="color:#e4e4e7;">material</b><br>
                                    Changes the perceived surface of all design elements (e.g. gold, marble, neon).<br><br>
                                    <b style="color:#e4e4e7;">decoration</b><br>
                                    Adds surface ornamentation on top of the material (e.g. glowing_edges, ornate_engraving).<br><br>
                                    <b style="color:#e4e4e7;">action</b><br>
                                    Applies a dynamic physical process to the design (e.g. burning, dissolving, floating).<br><br>
                                    <b style="color:#e4e4e7;">environment_1/2/3</b><br>
                                    Three independent atmospheric effect slots. Adds particles, fog, lightning, etc. around the design.<br><br>
                                    <b style="color:#e4e4e7;">style_mode</b><br>
                                    flat_vector: Pure 2-D, no shading (best for vinyl).<br>
                                    creative: Cinematic lighting and artistic direction.<br>
                                    realistic: Photorealistic rendering.<br>
                                    3d_render: Full physically-based 3-D render look.<br><br>
                                    <b style="color:#e4e4e7;">intensity</b><br>
                                    0.2 = very subtle styling. 1.0 = normal. 2.0 = extreme detail.<br><br>      
                                    <b style="color:#e4e4e7;">extra_instruction</b><br>
                                    Free-form text appended verbatim to the final model prompt.
                                </div>
                            </details>

                        </div>
                        <div class="pgfx-studio-main">
                            <!-- TOP TOOLBAR -->
                            <div class="pgfx-studio-toolbar">
                                <div class="pgfx-row">
                                    <button id="pgfx-tool-select" class="pgfx-btn pgfx-btn-primary" title="Selection Mode (S)">🖱️ Select</button>
                                    <button id="pgfx-tool-node" class="pgfx-btn" title="Node Edit Mode (N) - Only works on Polygons">◉ Edit Nodes</button>
                                    <button id="pgfx-tool-draw" class="pgfx-btn" title="Free Drawing Mode (D)">✏️ Draw</button>
                                </div>
                                <div class="pgfx-toolbar-separator"></div>
                                <div class="pgfx-row">
                                    <span style="font-size: 10px; color:#71717a; font-weight:800;">BRUSH</span> 
                                    <select id="pgfx-brush-type" class="pgfx-select" style="width: 100px;">
                                        <option value="Pencil">Pencil</option>
                                        <option value="Spray">Spray</option>
                                        <option value="Circle">Circle</option>
                                    </select>
                                </div>
                                <div class="pgfx-row">
                                    <span style="font-size: 10px; color:#71717a; font-weight:800;">SIZE</span>  
                                    <input type="range" id="pgfx-brush-size" min="1" max="100" value="10" style="width: 80px;">
                                </div>
                                <div class="pgfx-row">
                                    <span style="font-size: 10px; color:#71717a; font-weight:800;">COLOR</span> 
                                    <input type="color" id="pgfx-brush-color" value="#ffffff" style="cursor: pointer; background: none; border: none; width: 30px;">
                                </div>
                                <div class="pgfx-row">
                                    <span style="font-size: 10px; color:#71717a; font-weight:800;">OPACITY</span>
                                    <input type="range" id="pgfx-brush-opacity" min="0" max="1" step="0.05" value="1" style="width: 60px;">
                                </div>
                                <div class="pgfx-toolbar-separator"></div>
                                <button id="pgfx-clear-draw" class="pgfx-btn pgfx-btn-danger" title="Clear all free-draw paths">🧹 Clear Sketch</button>
                            </div>

                            <div class="pgfx-studio-canvas-wrapper">
                                <canvas id="pgfx-design-canvas"></canvas>
                            </div>
                        </div>
                    </div>
                </div>
            `;
            document.body.appendChild(overlay);
        }
        this.overlay = overlay;
    }
}

app.registerExtension({
    name: "PGFX.LogoDesignerStudio",
    async nodeCreated(node) {
        if (node.comfyClass !== "PGFX_LogoDesignerStudio") return;

        // â”€â”€ Find the two hidden data widgets + the visible text_input widget â”€â”€â”€â”€â”€
        const base64Widget = node.widgets.find(w => w.name === "base64_image_data");
        const jsonWidget   = node.widgets.find(w => w.name === "canvas_json_data");
        const textWidget   = node.widgets.find(w => w.name === "text_input");

        // Completely suppress the internal data widgets:
        const hideWidget = (w) => {
            if (!w) return;
            w.type = "hidden";
            w.computeSize = () => [0, 0];
            w.draw = () => {};
        };
        hideWidget(base64Widget);
        hideWidget(jsonWidget);

        // â”€â”€ Preview drawing constants â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        const PREVIEW_H   = 260;
        const PREVIEW_PAD = 10;

        // â”€â”€ LiteGraph node preview via onDrawForeground â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        // We detect changes by comparing the current widget value src to what we last loaded.
        // The save button resets _pgfxLastSrc so the next draw picks up the new image.
        const origDrawFg = node.onDrawForeground?.bind(node);
        node.onDrawForeground = function(ctx) {
            if (origDrawFg) origDrawFg(ctx);

            const currentSrc = base64Widget?.value || "";
            if (!currentSrc.startsWith("data:image")) return;

            // If the src changed (or was reset by the save button), reload the image
            if (!this._pgfxPreviewImg || this._pgfxLastSrc !== currentSrc) {
                this._pgfxLastSrc    = currentSrc;
                this._pgfxPreviewImg = null;
                const img = new Image();
                img.onload  = () => { app.graph?.setDirtyCanvas(true, true); };
                img.onerror = () => { this._pgfxPreviewImg = null; };
                img.src = currentSrc;
                this._pgfxPreviewImg = img;
                return; // Render on next frame after image decodes
            }

            const img = this._pgfxPreviewImg;
            if (!img.complete || img.naturalWidth === 0) return;

            // Compute draw area: full node width, positioned dynamically below widgets
            let widgetsBottomY = 0;
            if (this.widgets) {
                for (const w of this.widgets) {
                    if (w.type !== "hidden" && w.y !== undefined) {
                        const h = w.computeSize ? w.computeSize()[1] : (LiteGraph.NODE_WIDGET_HEIGHT || 20);    
                        widgetsBottomY = Math.max(widgetsBottomY, w.y + h);
                    }
                }
            }
            if (widgetsBottomY === 0) {
                widgetsBottomY = 40; // Fallback
            }

            const drawW  = this.size[0] - PREVIEW_PAD * 2;
            const aspect = img.naturalHeight / img.naturalWidth;
            const drawH  = Math.min(drawW * aspect, PREVIEW_H);
            const drawX  = PREVIEW_PAD;
            const drawY  = widgetsBottomY + PREVIEW_PAD;

            // Dark bordered background panel
            ctx.save();
            ctx.fillStyle   = "#09090b";
            ctx.strokeStyle = "rgba(6,182,212,0.4)";
            ctx.lineWidth   = 1;
            ctx.beginPath();
            if (ctx.roundRect) {
                ctx.roundRect(drawX - 2, drawY - 2, drawW + 4, drawH + 4, 6);
            } else {
                ctx.rect(drawX - 2, drawY - 2, drawW + 4, drawH + 4);
            }
            ctx.fill();
            ctx.stroke();

            // Clip and draw the image
            ctx.beginPath();
            if (ctx.roundRect) {
                ctx.roundRect(drawX, drawY, drawW, drawH, 4);
            } else {
                ctx.rect(drawX, drawY, drawW, drawH);
            }
            ctx.clip();
            ctx.drawImage(img, drawX, drawY, drawW, drawH);
            ctx.restore();

            // "CANVAS PREVIEW" label
            ctx.fillStyle = "rgba(6,182,212,0.7)";
            ctx.font      = "bold 9px monospace";
            ctx.textAlign = "left";
            ctx.fillText("CANVAS PREVIEW", drawX, drawY - 4);
        };

        // â”€â”€ Auto-size: expand the node height to accommodate the preview â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€   
        const origComputeSize = node.computeSize?.bind(node);
        node.computeSize = function(out) {
            const s = origComputeSize ? origComputeSize(out) : [this.size[0], 400];
            const hasSrc = (base64Widget?.value || "").startsWith("data:image");
            if (hasSrc) {
                s[1] = s[1] + PREVIEW_H + PREVIEW_PAD * 2;
            }
            return s;
        };

        // â”€â”€ "Open Studio" button â€” this MUST be the last widget added â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        node.addWidget("button", "🎨  OPEN DESIGN STUDIO", "button", () => {
            if (!node.studioUI) {
                node.studioUI = new LogoStudioUI(node, base64Widget, jsonWidget, textWidget);
            }
            node.studioUI.open();
        });

        // Set initial size â€” auto-expands to include preview once a canvas is saved
        node.setSize([340, node.computeSize()[1]]);
    }
});

app.registerExtension({
    name: "PGFX.ImageVectorizer",
    async nodeCreated(node) {
        if (node.comfyClass !== "PGFX_ImageVectorizer") return;

        // Use a helper to find widgets by name to be 100% sure we don't mix up indices
        const getWidget = (name) => node.widgets?.find(w => w.name === name);

        if (getWidget("preset")) {
            const presetWidget = getWidget("preset");
            const origCallback = presetWidget.callback;

            presetWidget.callback = function (v) {
                if (origCallback) origCallback.call(this, v);

                let s = {}; // State object for new values

                if (v === "1-Color Silhouette (Ultra Fast)") {
                    s = { post: 2, noise: 32, path: 4, mode: "polygon", dither: false, layer: "cutout", color: 2 };
                } else if (v === "2-Color Minimalist") {
                    s = { post: 3, noise: 24, path: 4, mode: "spline", dither: false, layer: "cutout", color: 4 };
                } else if (v === "4-Color Vinyl / Tattoo Decal") {
                    s = { post: 4, noise: 20, path: 4, mode: "spline", dither: false, layer: "cutout", color: 5 };
                } else if (v === "Clean Vector Logo (8 Colors)") {
                    s = { post: 8, noise: 16, path: 3, mode: "spline", dither: false, layer: "stacked", color: 6 };
                } else if (v === "Graphic Art (16 Colors)") {
                    s = { post: 16, noise: 12, path: 3, mode: "polygon", dither: false, layer: "stacked", color: 7 };
                } else if (v === "Raster Optimization (32 Colors - Web Safe)") {
                    s = { post: 32, noise: 8, path: 4, mode: "polygon", dither: false, layer: "stacked", color: 8 };
                } else if (v === "High Fidelity Raster (64 Colors - Heavy)") {
                    s = { post: 64, noise: 2, path: 8, mode: "spline", dither: true, layer: "stacked", color: 8 };
                }

                if (s.post !== undefined) {
                    const w_post  = getWidget("posterize_levels");
                    const w_noise = getWidget("noise_suppression");
                    const w_path  = getWidget("path_precision");
                    const w_mode  = getWidget("mode");
                    const w_dith  = getWidget("dithering");
                    const w_layr  = getWidget("layering_mode");
                    const w_colr  = getWidget("color_matching");

                    if (w_post)  w_post.value  = s.post;
                    if (w_noise) w_noise.value = s.noise;
                    if (w_path)  w_path.value  = s.path;
                    if (w_mode)  w_mode.value  = s.mode;
                    if (w_dith)  w_dith.value  = s.dither;
                    if (w_layr)  w_layr.value  = s.layer;
                    if (w_colr)  w_colr.value  = s.color;

                    app.graph.setDirtyCanvas(true, true);
                }
            };
        }
    }
});