console.log("[PGFX] Fixed Logo Studio Loaded");
import { app } from "../../scripts/app.js";

// Load Fabric.js with local fallback and status reporting
const loadFabric = (statusEl) => {
    return new Promise((resolve, reject) => {
        if (window.fabric) {
            resolve(window.fabric);
            return;
        }

        const tryLoad = (src, isFallback = false) => {
            if (statusEl) statusEl.textContent = isFallback ? "📂 Attempting Local Engine Fallback..." : "📦 Downloading Designer Engine (Fabric.js)...";
            const script = document.createElement("script");
            script.src = src;
            script.onload = () => {
                if (statusEl) statusEl.textContent = "✅ Engine Ready. Starting Canvas...";
                resolve(window.fabric);
            };
            script.onerror = () => {
                if (!isFallback) {
                    // Try local fallback if CDN fails
                    tryLoad("/extensions/ComfyUI-PromptCrafter/js/fabric.min.js", true);
                } else {
                    if (statusEl) statusEl.textContent = "❌ Failed to load Designer Engine. Check your internet connection.";
                    reject(new Error("Failed to load Fabric.js."));
                }
            };
            document.head.appendChild(script);
        };

        tryLoad("https://cdnjs.cloudflare.com/ajax/libs/fabric.js/5.3.1/fabric.min.js");
    });
};

// Load Three.js, OrbitControls, SVGLoader, and TransformControls with status reporting
const loadThreeJS = (statusEl) => {
    return new Promise(async (resolve, reject) => {
        if (window.THREE && window.THREE.OrbitControls && window.THREE.SVGLoader && window.THREE.TransformControls && window.THREE.GLTFLoader && window.THREE.OBJLoader && window.THREE.STLLoader) {
            resolve(window.THREE);
            return;
        }

        const loadScript = (src) => {
            return new Promise((res, rej) => {
                const script = document.createElement("script");
                script.src = src;
                script.onload = () => res();
                script.onerror = () => rej(new Error("Failed to load script: " + src));
                document.head.appendChild(script);
            });
        };

        try {
            if (statusEl) statusEl.textContent = "📦 Downloading 3D Graphics Engine (Three.js)...";
            if (!window.THREE) {
                await loadScript("https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js");
            }
            if (statusEl) statusEl.textContent = "📦 Downloading 3D Camera Controls (OrbitControls)...";
            if (!window.THREE.OrbitControls) {
                await loadScript("https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/controls/OrbitControls.js");
            }
            if (statusEl) statusEl.textContent = "📦 Downloading Vector Extruder (SVGLoader)...";
            if (!window.THREE.SVGLoader) {
                await loadScript("https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/loaders/SVGLoader.js");
            }
            if (statusEl) statusEl.textContent = "📦 Downloading Transform Controls...";
            if (!window.THREE.TransformControls) {
                await loadScript("https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/controls/TransformControls.js");
            }
            if (statusEl) statusEl.textContent = "📦 Downloading 3D Model Loaders (GLTF/OBJ/STL)...";
            if (!window.THREE.GLTFLoader) {
                await loadScript("https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/loaders/GLTFLoader.js");
            }
            if (!window.THREE.OBJLoader) {
                await loadScript("https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/loaders/OBJLoader.js");
            }
            if (!window.THREE.STLLoader) {
                await loadScript("https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/loaders/STLLoader.js");
            }
            if (statusEl) statusEl.textContent = "📦 Downloading 3D Exporter...";
            if (!window.THREE.GLTFExporter) {
                await loadScript("https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/exporters/GLTFExporter.js");
            }
            if (statusEl) statusEl.textContent = "✅ 3D Engine Ready!";
            resolve(window.THREE);
        } catch (err) {
            if (statusEl) statusEl.textContent = "❌ Failed to load 3D graphics engine: " + err.message;
            reject(err);
        }
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
            width: 300px;
            background: #18181b;
            border-right: 1px solid rgba(255,255,255,0.05);
            padding: 16px;
            display: flex;
            flex-direction: column;
            gap: 12px;
            overflow-y: auto;
        }
        .pgfx-studio-right-sidebar {
            flex-shrink: 0;
            width: 260px;
            background: #18181b;
            border-left: 1px solid rgba(255,255,255,0.05);
            padding: 16px;
            display: flex;
            flex-direction: column;
            gap: 12px;
            overflow-y: auto;
        }
        .pgfx-layers-list {
            display: flex;
            flex-direction: column;
            gap: 4px;
        }
        .pgfx-layer-item {
            background: rgba(255,255,255,0.02);
            border: 1px solid rgba(255,255,255,0.05);
            border-radius: 6px;
            padding: 8px 10px;
            display: flex;
            align-items: center;
            gap: 10px;
            cursor: pointer;
            transition: all 0.2s;
        }
        .pgfx-layer-item:hover {
            background: rgba(255,255,255,0.05);
            border-color: rgba(255,255,255,0.1);
        }
        .pgfx-layer-item.active {
            background: rgba(6, 182, 212, 0.1);
            border-color: rgba(6, 182, 212, 0.4);
        }
        .pgfx-layer-name {
            font-size: 11px;
            font-weight: 600;
            flex: 1;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
            color: #d4d4d8;
        }
        .pgfx-layer-icon {
            font-size: 12px;
            opacity: 0.5;
            transition: opacity 0.2s;
            cursor: pointer;
            width: 18px;
            text-align: center;
        }
        .pgfx-layer-icon:hover {
            opacity: 1;
            color: #06b6d4;
        }
        .pgfx-layer-icon.disabled {
            opacity: 0.2;
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
        #pgfx-studio-loading {
            position: absolute;
            top: 0; left: 0; width: 100%; height: 100%;
            background: #111113;
            z-index: 1000;
            display: none;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            gap: 20px;
            color: #06b6d4;
            font-weight: bold;
        }
        .pgfx-spinner {
            width: 40px;
            height: 40px;
            border: 4px solid rgba(6, 182, 212, 0.1);
            border-top: 4px solid #06b6d4;
            border-radius: 50%;
            animation: pgfx-spin 1s linear infinite;
        }
        #pgfx-context-menu {
            position: fixed;
            z-index: 20000;
            background: #18181b;
            border: 1px solid rgba(255,255,255,0.1);
            border-radius: 8px;
            box-shadow: 0 10px 25px rgba(0,0,0,0.5);
            padding: 4px;
            display: none;
            flex-direction: column;
            min-width: 160px;
        }
        .pgfx-menu-item {
            padding: 8px 12px;
            font-size: 12px;
            color: #d4d4d8;
            cursor: pointer;
            border-radius: 4px;
            display: flex;
            align-items: center;
            gap: 10px;
            transition: all 0.2s;
        }
        .pgfx-menu-item:hover {
            background: #06b6d4;
            color: black;
        }
        .pgfx-menu-separator {
            height: 1px;
            background: rgba(255,255,255,0.05);
            margin: 4px 0;
        }
        @keyframes pgfx-spin {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
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

        // 3D Selection & Transform
        this.selectedMesh3d = null;
        this.transformControls3d = null;
        this.raycaster3d = null;
        this.mouse3d = null;
        this.transformMode = 'translate'; // translate | rotate | scale
        this._saved3DTransforms = {}; // keyed by name+type — persists 3D transforms across sync

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
        if (this.isProcessingHistory || this.historyIdx <= 0) return;
        console.log("[PGFX Studio] Undo", this.historyIdx - 1);
        this.historyIdx--;
        this._loadFromHistory();
    }

    redo() {
        if (this.isProcessingHistory || this.historyIdx >= this.history.length - 1) return;
        console.log("[PGFX Studio] Redo", this.historyIdx + 1);
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
            this._updateSelectionUI();
            this.scheduleNodeStateSync();
            
            // Sync to 3D if active so Undo/Redo works in 3D Viewport
            if (this.mode3D) {
                this.sync2DTo3D();
            }
        });
    }

    commitCanvasChange() {
        if (!this.canvas) return;
        this.canvas.renderAll();
        this.refreshLayersPanel();
        this._saveToHistory();
        this.scheduleNodeStateSync();
        
        // Ensure 3D viewport stays in sync with 2D changes
        if (this.mode3D) {
            this.sync2DTo3D();
        }
    }

    async open() {
        injectStyles();
        this.overlay.classList.add('active');
        
        // Show loading state
        const loadingOverlay = document.getElementById('pgfx-studio-loading');
        const loadingStatus = document.getElementById('pgfx-loading-status');
        if (loadingOverlay) loadingOverlay.style.display = 'flex';

        try {
            await loadFabric(loadingStatus);
            if (loadingStatus) loadingStatus.textContent = "📂 Loading Design Data...";
            
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

                // --- RESTORE FROM SAVED DATA ---
                if (this.jsonWidget.value && this.jsonWidget.value.startsWith('{')) {
                    try {
                        const projectState = JSON.parse(this.jsonWidget.value);
                        const fabricData = projectState.fabric_canvas || projectState; 
                        
                        if (projectState.customFonts) {
                            for (const font of projectState.customFonts) {
                                await this.loadFontIntoBrowser(font.name, font.url);
                            }
                        }

                        this.isProcessingHistory = true;
                        this.canvas.loadFromJSON(fabricData, () => {
                            this.isProcessingHistory = false;
                            
                            // Restore Dimensions and Background
                            this.targetWidth = projectState.pgfx_canvas_width || 1024;
                            this.targetHeight = projectState.pgfx_canvas_height || 1024;
                            const restoredBg = projectState.pgfx_editor_background || projectState.backgroundColor || '#000000';
                            this.pageBackgroundColor = restoredBg === 'transparent' ? '#000000' : restoredBg;
                            this.canvas.backgroundColor = 'transparent';

                            // Restore 3D settings
                            if (projectState.pgfx_3d_settings) {
                                this._apply3DSettings(projectState.pgfx_3d_settings);
                            }

                            // Sync UI Inputs
                            const wIn = document.getElementById('pgfx-canvas-width');
                            const hIn = document.getElementById('pgfx-canvas-height');
                            if (wIn && hIn) {
                                wIn.value = this.targetWidth;
                                hIn.value = this.targetHeight;
                            }

                            this.canvas.renderAll();
                            this._syncBackgroundPicker();
                            this.updateUIForSelection();
                            this.refreshLayersPanel();
                            this.fitCanvasToView();
                            this.lastCanvasText = this._extractCanvasText();
                            
                            this.history = [];
                            this.historyIdx = -1;
                            this._saveToHistory();
                            this.scheduleNodeStateSync();

                            // Force 3D Restoration if active
                            if (this._shouldRestore3D) {
                                console.log("[PGFX Studio] Restoring 3D Viewport...");
                                setTimeout(() => {
                                    this.toggleViewportTab('3D');
                                    // Safety: Force a second sync once the UI has definitely reflowed
                                    setTimeout(() => this.sync2DTo3D(), 300);
                                }, 150);
                            }

                            if (loadingOverlay) loadingOverlay.style.display = 'none';
                        });
                    } catch (e) {
                        console.error("[PGFX Studio] Critical Restore Error:", e);
                        if (loadingOverlay) loadingOverlay.style.display = 'none';
                    }
                } else {
                    // ── No saved state: seed canvas from text_input if it has content ─
                    this._addDefaultText();
                    this._syncBackgroundPicker();
                    this.refreshLayersPanel();
                    this.setupEventHandlers();
                    this.fitCanvasToView();
                    // Multi-pass fit to handle dynamic layout shifts
                    setTimeout(() => this.fitCanvasToView(), 100);
                    setTimeout(() => this.fitCanvasToView(), 300);
                    this.history = [];
                    this.historyIdx = -1;
                    this._saveToHistory();
                    this.scheduleNodeStateSync();
                    if (loadingOverlay) loadingOverlay.style.display = 'none';
                }

                this.setupEventHandlers();
            } else {
                // Canvas already exists — if text_input changed since last open, update the primary text layer   
                this._syncTextInputToCanvas();
                this._syncBackgroundPicker();
                this.refreshLayersPanel();
                this.fitCanvasToView();
                setTimeout(() => this.fitCanvasToView(), 100);
                this.scheduleNodeStateSync();
                if (loadingOverlay) loadingOverlay.style.display = 'none';
            }
        } catch (err) {
            console.error("[PGFX Studio] Critical startup error:", err);
            if (loadingStatus) loadingStatus.innerHTML = `<span style="color: #ef4444;">❌ Studio Failed to Start: ${err.message}</span><br><br><button onclick="window.location.reload()" class="pgfx-btn">Reload Page</button>`;
        }
    }

    // Populate the canvas with the text_input value (or a placeholder if empty)
    _addDefaultText() {
        const rawText = (this.textWidget?.value || "").trim();
        const displayText = rawText || "YOUR TEXT\nHERE";
        const text = new fabric.IText(displayText, {
            left: this.targetWidth / 2, top: this.targetHeight / 2,
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

        // --- HIGH-RESOLUTION ASPECT-CORRECT 3D CAPTURE ---
        if (this.mode3D && this.renderer3d && this.scene3d && this.camera3d) {
            const prevSize = new THREE.Vector2();
            this.renderer3d.getSize(prevSize);
            const prevAspect = this.camera3d.aspect;
            const prevFov = this.camera3d.fov;
            
            if (this.transformControls3d) this.transformControls3d.visible = false;
            this.isExporting = true;

            const targetW = this.targetWidth || 1024;
            const targetH = this.targetHeight || 1024;
            const targetAspect = targetW / targetH;

            // FOV COMPENSATION: Preserve framing regardless of aspect ratio shift
            if (prevAspect > targetAspect) {
                const vFovRad = THREE.MathUtils.degToRad(prevFov);
                const hFovRad = 2 * Math.atan(Math.tan(vFovRad / 2) * prevAspect);
                this.camera3d.fov = THREE.MathUtils.radToDeg(2 * Math.atan(Math.tan(hFovRad / 2) / targetAspect));
            }

            this.renderer3d.setSize(targetW, targetH, false);
            this.camera3d.aspect = targetAspect;
            this.camera3d.updateProjectionMatrix();

            // Render high-res frame
            this.renderer3d.render(this.scene3d, this.camera3d);
            const dataUrl = this.renderer3d.domElement.toDataURL("image/png");

            // RESTORE
            this.renderer3d.setSize(prevSize.x, prevSize.y, false);
            this.camera3d.aspect = prevAspect;
            this.camera3d.fov = prevFov;
            this.camera3d.updateProjectionMatrix();
            
            this.isExporting = false;
            if (this.transformControls3d) this.transformControls3d.visible = true;

            const advSettings = {};
            const primary = this.canvas.getObjects().find(o => o.name === 'pgfx_primary_text');
            if (primary) {
                advSettings.font_family = primary.fontFamily;
                advSettings.text_align = primary.textAlign;
            }

            const jsonState = this.canvas.toJSON(['name', 'userData']);
            jsonState.background = 'transparent';
            jsonState.backgroundColor = 'transparent';
            jsonState.pgfx_editor_background = editorBackground;
            jsonState.pgfx_canvas_width = this.targetWidth;
            jsonState.pgfx_canvas_height = this.targetHeight;
            jsonState.customFonts = this.customFonts;
            jsonState.pgfx_adv_settings = advSettings;
            jsonState.pgfx_3d_settings = this._collect3DSettings();

            return {
                dataUrl,
                jsonText: JSON.stringify(jsonState),
                canvasText: this._extractCanvasText(),
            };
        }

        // Silently hide active object controls without triggering selection events or destroying ActiveSelection groups
        const prevActive = this.canvas._activeObject;
        this.canvas._activeObject = null;

        // Hide overlay items (like the page border) from export
        this.isExporting = true;

        const exportZoom = this.canvas.getWidth() / this.targetWidth;
        this.canvas.setViewportTransform([exportZoom, 0, 0, exportZoom, 0, 0]);
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

    async applyCanvasStateToNode({ bumpSeed = false, closeAfter = false } = {}) {
        const snapshot = this._captureCanvasState();
        if (!snapshot) return;

        // Upload image to server and set widget value to the filename path
        try {
            const blob = await (await fetch(snapshot.dataUrl)).blob();
            const nodeId = this.node?.id || "temp";
            const body = new FormData();
            body.append("image", blob, `pgfx_logo_${nodeId}.png`);
            body.append("overwrite", "true");
            body.append("subfolder", "pgfx_logo");

            const resp = await fetch("/upload/image", {
                method: "POST",
                body
            });
            if (resp.ok) {
                const data = await resp.json();
                const filenamePath = (data.subfolder ? data.subfolder + "/" : "") + data.name;
                if (this.base64Widget) this.base64Widget.value = filenamePath;
            } else {
                console.error("[PGFX Studio] Upload failed, falling back to base64 widget value");
                if (this.base64Widget) this.base64Widget.value = snapshot.dataUrl;
            }
        } catch (err) {
            console.error("[PGFX Studio] Upload exception, falling back to base64 widget value", err);
            if (this.base64Widget) this.base64Widget.value = snapshot.dataUrl;
        }

        if (this.jsonWidget) this.jsonWidget.value = snapshot.jsonText;
        if (this.textWidget && snapshot.canvasText) this.textWidget.value = snapshot.canvasText;
        this.lastCanvasText = snapshot.canvasText;

        this.node._pgfxPreviewImg = null;
        this.node._pgfxLastSrc = null;

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

        // Stop 3D render loop and clean up WebGL without switching the UI mode
        if (this.mode3D) {
            this.cleanUp3D();
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

            fabricVideo.scaleX = this.targetWidth / videoEl.videoWidth;
            fabricVideo.scaleY = this.targetHeight / videoEl.videoHeight;

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

            img.scaleX = this.targetWidth / img.width;
            img.scaleY = this.targetHeight / img.height;

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
        // 3D mode: show mesh properties in the 2D controls
        if (this.mode3D && this.selectedMesh3d) {
            const mesh = this.selectedMesh3d;
            const mat = Array.isArray(mesh.material) ? mesh.material[0] : mesh.material;

            // Check if this is an imported model group (not an extruded Fabric object)
            const isImportedModel = mesh.parent === this.modelsGroup || !!mesh.userData._importedModelId;

            // For extruded objects (not imported models), sync per-object 3D settings
            if (!isImportedModel) {
                const activeObj = this.canvas.getActiveObject();
                if (activeObj) {
                    const s3d = this._getObj3DSettings(activeObj);
                    const setVal = (id, val) => { const el = document.getElementById(id); if (el) el.value = val; };
                    setVal('pgfx-3d-depth', s3d.depth);
                    const dv = document.getElementById('pgfx-3d-depth-val');
                    if (dv) dv.textContent = s3d.depth;
                    document.getElementById('pgfx-3d-bevel-enabled').checked = s3d.bevelEnabled;
                    document.getElementById('pgfx-3d-bevel-settings').style.display = s3d.bevelEnabled ? 'flex' : 'none';
                    setVal('pgfx-3d-bevel-size', s3d.bevelSize);
                    const bsv = document.getElementById('pgfx-3d-bevel-size-val');
                    if (bsv) bsv.textContent = s3d.bevelSize;
                    setVal('pgfx-3d-bevel-segments', s3d.bevelSegments);
                    const bsgv = document.getElementById('pgfx-3d-bevel-segments-val');
                    if (bsgv) bsgv.textContent = s3d.bevelSegments;
                }
            }

            // Update color picker
            const colorEl = document.getElementById('pgfx-color-picker');
            if (mat && mat.color && colorEl) {
                colorEl.value = '#' + mat.color.getHexString();
            }

            // Update opacity
            const opacityVal = mat ? (mat.opacity ?? 1) : 1;
            document.getElementById('pgfx-opacity').value = opacityVal;
            const valEl = document.getElementById('pgfx-opacity-val');
            if (valEl) valEl.textContent = Math.round(opacityVal * 100) + '%';

            // Rotation
            const rotDeg = THREE.MathUtils.radToDeg(mesh.rotation.z);
            document.getElementById('pgfx-rotation').value = Math.round(rotDeg);
            const rotValEl = document.getElementById('pgfx-rotation-val');
            if (rotValEl) rotValEl.textContent = Math.round(rotDeg) + '\u00b0';

            // Stroke and shadow only apply to single extruded meshes, not imported model groups
            if (!isImportedModel) {
                this._update3DStroke(mesh);
                this._update3DShadow(mesh);
            }

            return;
        }

        const active = this.canvas.getActiveObject();
        if (!active) return;

        // Helper to safely update a readout span
        const _valEl = (id, text) => { const el = document.getElementById(id); if (el) el.textContent = text; };

        // Common
        const opacityVal = active.opacity != null ? active.opacity : 1;
        const rotationVal = Math.round(active.angle || 0);
        const skewVal = Math.round(active.skewX || 0);
        const strokeVal = active.strokeWidth || 0;

        document.getElementById('pgfx-opacity').value = opacityVal;
        document.getElementById('pgfx-rotation').value = rotationVal;
        document.getElementById('pgfx-skew-x').value = skewVal;

        _valEl('pgfx-opacity-val', Math.round(opacityVal * 100) + '%');
        _valEl('pgfx-rotation-val', rotationVal + '\u00b0');
        _valEl('pgfx-skew-x-val', String(skewVal));

        // Colors & Fill Type
        const fillTypeSelect = document.getElementById('pgfx-fill-type');
        const gradientControls = document.getElementById('pgfx-fill-gradient-controls');
        const solidRow = document.getElementById('pgfx-fill-solid-row');

        if (active.fill && typeof active.fill === 'object' && active.fill.type) {
            // Gradient
            fillTypeSelect.value = active.fill.type;
            gradientControls.style.display = 'flex';
            solidRow.style.display = 'none';

            if (active.fill.colorStops && active.fill.colorStops.length >= 2) {
                document.getElementById('pgfx-gradient-start').value = active.fill.colorStops[0].color;
                document.getElementById('pgfx-gradient-end').value = active.fill.colorStops[active.fill.colorStops.length - 1].color;
            }
            const angle = active.fill.pgfx_angle || 0;
            document.getElementById('pgfx-gradient-angle').value = angle;
            _valEl('pgfx-gradient-angle-val', angle + '°');
        } else {
            // Solid
            fillTypeSelect.value = 'solid';
            gradientControls.style.display = 'none';
            solidRow.style.display = 'flex';
            if (active.fill && typeof active.fill === 'string') {
                document.getElementById('pgfx-color-picker').value = active.fill;
            }
        }

        if (active.stroke) document.getElementById('pgfx-stroke-picker').value = typeof active.stroke === 'string' ? active.stroke : '#000000';
        document.getElementById('pgfx-stroke-width').value = strokeVal;
        _valEl('pgfx-stroke-width-val', String(strokeVal));

        // Shadows
        const shadowEnabled = document.getElementById('pgfx-shadow-enabled');
        const shadowControls = document.getElementById('pgfx-shadow-controls');
        if (active.shadow && active.shadow instanceof fabric.Shadow) {
            shadowEnabled.checked = true;
            shadowControls.style.display = 'flex';
            document.getElementById('pgfx-shadow-color').value = active.shadow.color;
            document.getElementById('pgfx-shadow-blur').value = active.shadow.blur;
            document.getElementById('pgfx-shadow-offset-x').value = active.shadow.offsetX;
            document.getElementById('pgfx-shadow-offset-y').value = active.shadow.offsetY;
            _valEl('pgfx-shadow-blur-val', String(active.shadow.blur));
            _valEl('pgfx-shadow-offset-x-val', String(active.shadow.offsetX));
            _valEl('pgfx-shadow-offset-y-val', String(active.shadow.offsetY));
        } else {
            shadowEnabled.checked = false;
            shadowControls.style.display = 'none';
        }

        // Text specific
        if (active.type === 'i-text' || active.type === 'text') {
            const sizeVal = active.fontSize || 100;
            const letterVal = active.charSpacing || 0;
            const lineVal = active.lineHeight || 1.16;

            document.getElementById('pgfx-font-select').value = active.fontFamily || 'Arial';
            document.getElementById('pgfx-font-size').value = sizeVal;
            document.getElementById('pgfx-font-weight').value = active.fontWeight || 'normal';
            document.getElementById('pgfx-font-style').value = active.fontStyle || 'normal';
            document.getElementById('pgfx-line-spacing').value = lineVal;
            document.getElementById('pgfx-letter-spacing').value = letterVal;

            _valEl('pgfx-font-size-val', String(Math.round(sizeVal)));
            _valEl('pgfx-letter-spacing-val', String(Math.round(letterVal)));
            _valEl('pgfx-line-spacing-val', parseFloat(lineVal).toFixed(2));
        }
    }

    updateGradient() {
        const active = this.canvas.getActiveObject();
        if (!active) return;

        const type = document.getElementById('pgfx-fill-type').value;
        if (type === 'solid') {
            active.set('fill', document.getElementById('pgfx-color-picker').value);
        } else {
            const start = document.getElementById('pgfx-gradient-start').value;
            const end = document.getElementById('pgfx-gradient-end').value;
            const angle = parseInt(document.getElementById('pgfx-gradient-angle').value);
            
            // Convert angle to coords for Fabric
            const angleRad = (angle * Math.PI) / 180;
            const coords = {
                x1: 0,
                y1: 0,
                x2: Math.cos(angleRad),
                y2: Math.sin(angleRad)
            };

            const grad = new fabric.Gradient({
                type: type,
                coords: type === 'linear' ? {
                    x1: 0, y1: 0,
                    x2: active.width * Math.cos(angleRad),
                    y2: active.height * Math.sin(angleRad)
                } : {
                    r1: 0, r2: active.width / 2,
                    x1: active.width / 2, y1: active.height / 2,
                    x2: active.width / 2, y2: active.height / 2
                },
                colorStops: [
                    { offset: 0, color: start },
                    { offset: 1, color: end }
                ]
            });
            grad.pgfx_angle = angle; // Store for UI sync
            active.set('fill', grad);
        }
        this.canvas.requestRenderAll();
        this._saveToHistory();
        this.scheduleNodeStateSync();
    }

    updateShadow() {
        if (this.mode3D && this.selectedMesh3d) {
            this._update3DShadow(this.selectedMesh3d);
            return;
        }
        const active = this.canvas.getActiveObject();
        if (!active) return;

        const enabled = document.getElementById('pgfx-shadow-enabled').checked;
        if (!enabled) {
            active.set('shadow', null);
        } else {
            const color = document.getElementById('pgfx-shadow-color').value;
            const blur = parseInt(document.getElementById('pgfx-shadow-blur').value);
            const offsetX = parseInt(document.getElementById('pgfx-shadow-offset-x').value);
            const offsetY = parseInt(document.getElementById('pgfx-shadow-offset-y').value);

            active.set('shadow', new fabric.Shadow({
                color: color,
                blur: blur,
                offsetX: offsetX,
                offsetY: offsetY
            }));
        }
        this.canvas.requestRenderAll();
        this._saveToHistory();
        this.scheduleNodeStateSync();
    }

    refreshLayersPanel() {
        const list = document.getElementById('pgfx-layers-list');
        const count = document.getElementById('pgfx-layer-count');
        if (!list) return;

        list.innerHTML = '';

        let objects;
        let is3D = this.mode3D && this.extrudedGroup;

        if (is3D) {
            objects = this.extrudedGroup.children;
            // Also include imported models
            if (this.modelsGroup && this.modelsGroup.children.length > 0) {
                objects = [...objects, ...this.modelsGroup.children];
            }
        } else if (this.canvas) {
            objects = this.canvas.getObjects().filter(o => o.name !== 'node_control');
        } else {
            if (count) count.textContent = '0';
            return;
        }

        if (count) count.textContent = objects.length;

        // Render from top to bottom (reverse order of stack)
        [...objects].reverse().forEach((obj) => {
            const item = document.createElement('div');
            item.className = 'pgfx-layer-item';

            // Determine if selected
            let isActive = false;
            if (is3D) {
                isActive = this.selectedMesh3d === obj;
            } else if (this.canvas) {
                isActive = this.canvas.getActiveObject() === obj || 
                    (obj.type === 'activeSelection' && obj.getObjects().includes(obj));
            }

            if (isActive) item.classList.add('active');

            if (is3D) {
                // 3D layer item - simpler, no visibility/lock for now
                const icon = document.createElement('span');
                icon.className = 'pgfx-layer-icon';
                const isImported = obj.userData && obj.userData._importedModelId;
                const typeLabel = isImported ? '3D Model' : (obj.geometry && obj.geometry.type ? obj.geometry.type : 'Mesh');
                icon.innerHTML = isImported ? '🎲' : '🧊';
                icon.title = isImported ? 'Imported 3D Model' : '3D Object';

                const name = document.createElement('span');
                name.className = 'pgfx-layer-name';
                name.textContent = obj.userData?.name || `${typeLabel} ${objects.indexOf(obj) + 1}`;

                item.appendChild(icon);
                item.appendChild(name);
                item.onclick = () => {
                    if (this.selectedMesh3d === obj) {
                        this.deselectMesh3d();
                    } else {
                        this.selectMesh3d(obj);
                    }
                    this.refreshLayersPanel();
                };
            } else {
                // 2D Fabric layer item
                const visibleIcon = document.createElement('span');
                visibleIcon.className = 'pgfx-layer-icon';
                visibleIcon.innerHTML = obj.visible ? '👁️' : '🕶️';
                visibleIcon.title = obj.visible ? 'Hide Layer' : 'Show Layer';
                visibleIcon.onclick = (e) => {
                    e.stopPropagation();
                    obj.set('visible', !obj.visible);
                    this.canvas.requestRenderAll();
                    this.refreshLayersPanel();
                    this._saveToHistory();
                    this.scheduleNodeStateSync();
                };

                const lockIcon = document.createElement('span');
                lockIcon.className = 'pgfx-layer-icon';
                lockIcon.innerHTML = obj.selectable ? '🔓' : '🔒';
                lockIcon.title = obj.selectable ? 'Lock Layer' : 'Unlock Layer';
                lockIcon.onclick = (e) => {
                    e.stopPropagation();
                    const isLocked = !obj.selectable;
                    obj.set({
                        selectable: isLocked,
                        evented: isLocked,
                        hasControls: isLocked,
                        hasBorders: isLocked
                    });
                    this.canvas.requestRenderAll();
                    this.refreshLayersPanel();
                    this._saveToHistory();
                    this.scheduleNodeStateSync();
                };

                const name = document.createElement('span');
                name.className = 'pgfx-layer-name';
                const typeLabel = obj.type.charAt(0).toUpperCase() + obj.type.slice(1);
                name.textContent = obj.name || `${typeLabel} Layer`;
                
                name.ondblclick = (e) => {
                    e.stopPropagation();
                    const newName = prompt("Rename Layer:", name.textContent);
                    if (newName !== null) {
                        obj.set('name', newName);
                        this.refreshLayersPanel();
                        this._saveToHistory();
                        this.scheduleNodeStateSync();
                    }
                };

                const upBtn = document.createElement('span');
                upBtn.className = 'pgfx-layer-icon';
                upBtn.innerHTML = '▲';
                upBtn.title = 'Move Up';
                upBtn.onclick = (e) => {
                    e.stopPropagation();
                    obj.bringForward();
                    this.refreshLayersPanel();
                    this._saveToHistory();
                    this.scheduleNodeStateSync();
                };

                const downBtn = document.createElement('span');
                downBtn.className = 'pgfx-layer-icon';
                downBtn.innerHTML = '▼';
                downBtn.title = 'Move Down';
                downBtn.onclick = (e) => {
                    e.stopPropagation();
                    obj.sendBackwards();
                    this.refreshLayersPanel();
                    this._saveToHistory();
                    this.scheduleNodeStateSync();
                };

                item.appendChild(visibleIcon);
                item.appendChild(lockIcon);
                item.appendChild(name);
                item.appendChild(upBtn);
                item.appendChild(downBtn);
                item.onclick = () => {
                    if (obj.type === 'activeSelection') return;
                    this.canvas.setActiveObject(obj);
                    this.canvas.requestRenderAll();
                    this.refreshLayersPanel();
                    this._updateSelectionUI();
                };
            }
            list.appendChild(item);
        });
    }

    // ── Agent Log ──────────────────────────────────────────────
    _addAgentLog(msg) {
        this._agentLog = this._agentLog || [];
        this._agentLog.unshift(msg);
        if (this._agentLog.length > 5) this._agentLog.length = 5;
        const el = document.getElementById('pgfx-agent-log');
        if (!el) return;
        el.innerHTML = this._agentLog.map(m =>
            `<div style="border-bottom: 1px solid rgba(255,255,255,0.04); padding: 2px 0;">${m}</div>`
        ).join('');
    }

    async sendToAgent() {
        const active = this.canvas.getActiveObject();
        if (!active) {
            alert("Please select a design element to describe to the AI Agent.");
            return;
        }

        const btn = document.getElementById('pgfx-send-agent-btn');
        const originalText = btn.innerHTML;
        btn.innerHTML = "🤖 Injecting...";
        btn.disabled = true;

        try {
            const getFillInfo = (fill) => {
                if (!fill) return "none";
                if (typeof fill === 'string') return fill;
                if (fill.type) {
                    const stops = fill.colorStops.map(s => s.color).join(' to ');
                    return `${fill.type} gradient (${stops})`;
                }
                return "complex";
            };

            const type = active.type.charAt(0).toUpperCase() + active.type.slice(1);
            const name = active.name || `${type} Layer`;
            const fill = getFillInfo(active.fill);
            const stroke = active.stroke ? `${active.strokeWidth}px ${active.stroke}` : "none";
            const opacity = Math.round((active.opacity || 1) * 100) + "%";

            let injection = `[Agent Focus: "${name}"] `;
            injection += `Type: ${type}, Fill: ${fill}, Opacity: ${opacity}`;
            if (active.stroke && active.strokeWidth > 0) injection += `, Stroke: ${stroke}`;
            if (active.type.includes('text')) {
                injection += `, Text: "${active.text}", Font: ${active.fontFamily}`;
            }

            const userRefinement = prompt(`What should the AI do with "${name}"?`, "enhance detail and visual quality");
            if (userRefinement) {
                injection += `. ${userRefinement}`;
            }

            // Find the extra_instruction widget on the node
            const extraWidget = this.node.widgets?.find(w => w.name === 'extra_instruction');
            if (extraWidget) {
                const existing = (extraWidget.value || '').trim();
                extraWidget.value = existing
                    ? existing + '\n' + injection
                    : injection;
                // Force the widget callback so ComfyUI sees the change
                if (extraWidget.callback) extraWidget.callback(extraWidget.value);
            }

            this._addAgentLog(`📝 "${name}" → extra_instruction`);

            btn.innerHTML = "✅ Injected";
            setTimeout(() => {
                btn.innerHTML = originalText;
                btn.disabled = false;
            }, 2000);

            this.scheduleNodeStateSync();

        } catch (err) {
            console.error("[PGFX Studio] Error sending to agent:", err);
            btn.innerHTML = "❌ Error";
            btn.disabled = false;
        }
    }

    // ── Save / Load Project ────────────────────────────────────
    collectProjectState() {
        const state = {
            pgfx_version: '1.1',
            pgfx_type: 'project',
            saved_at: new Date().toISOString(),
            canvas_json: this.canvas ? this.canvas.toJSON(['name']) : null,
            canvas_text: this.lastCanvasText || '',
            editor: {
                target_width: this.targetWidth,
                target_height: this.targetHeight,
                page_background_color: this.pageBackgroundColor || '#000000',
                custom_fonts: this.customFonts || [],
                show_grid: document.getElementById('pgfx-show-grid')?.checked ?? true,
                grid_size: parseFloat(document.getElementById('pgfx-grid-size')?.value) || 50,
            },
            settings_3d: this._collect3DSettings(),
            imported_models: this.importedModels ? this.importedModels.map(m => ({
                id: m.id,
                name: m.name,
                format: m.format,
                data: m.data,
            })) : [],
            brush: {
                type: document.getElementById('pgfx-brush-type')?.value || 'Pencil',
                size: parseFloat(document.getElementById('pgfx-brush-size')?.value) || 10,
                color: document.getElementById('pgfx-brush-color')?.value || '#ffffff',
                opacity: parseFloat(document.getElementById('pgfx-brush-opacity')?.value) || 1,
            },
        };

        // Collect public node widget values
        const widgetNames = [
            'output_intent', 'background_mode', 'background_preset',
            'background_custom_prompt', 'scene_interaction', 'material',
            'decoration', 'action', 'environment_1', 'environment_2',
            'environment_3', 'environment_1_intensity', 'environment_2_intensity',
            'environment_3_intensity', 'style_mode', 'intensity', 'extra_instruction',
            'text_input'
        ];
        if (this.node?.widgets) {
            state.node_widgets = {};
            for (const w of this.node.widgets) {
                if (widgetNames.includes(w.name)) {
                    state.node_widgets[w.name] = w.value;
                }
            }
        }

        return state;
    }

    async saveProject() {
        try {
            const state = this.collectProjectState();
            const blob = new Blob([JSON.stringify(state, null, 2)], { type: 'application/json' });
            const suggestedName = `pgfx_project_${Date.now()}.pgfx`;

            // Try File System Access API (shows native save dialog)
            if ('showSaveFilePicker' in window) {
                try {
                    const handle = await window.showSaveFilePicker({
                        suggestedName: suggestedName,
                        types: [{
                            description: 'PGFX Project',
                            accept: { 'application/json': ['.pgfx'] }
                        }]
                    });
                    const writable = await handle.createWritable();
                    await writable.write(blob);
                    await writable.close();
                    this._addAgentLog('💾 Project saved to ' + handle.name);
                    return;
                } catch (err) {
                    // User cancelled or API failed — fall through
                    if (err.name === 'AbortError' || err.name === 'SecurityError') return;
                }
            }

            // Fallback: anchor download
            this._saveBlob(blob, suggestedName);
            this._addAgentLog('💾 Project saved');
        } catch (err) {
            console.error('[PGFX] Save error:', err);
            alert('Failed to save project: ' + err.message);
        }
    }

    _saveBlob(blob, filename) {
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    }

    export3D() {
        if (!window.THREE || !window.THREE.GLTFExporter || !this.scene3d) {
            alert("3D Engine or Exporter not ready. Please open the 3D Viewport first.");
            return;
        }

        const exporter = new THREE.GLTFExporter();
        
        // We only want to export the design elements, not the helper grid/axes/plane
        const exportGroup = new THREE.Group();
        
        // Clone design groups into the export group
        if (this.extrudedGroup) exportGroup.add(this.extrudedGroup.clone());
        if (this.modelsGroup) exportGroup.add(this.modelsGroup.clone());
        
        const options = {
            binary: true, // Export as compact .glb
            trs: false,
            onlyVisible: true,
            truncateDrawRange: true,
            embedImages: true,
            forceIndices: true
        };

        exporter.parse(exportGroup, (result) => {
            if (result instanceof ArrayBuffer) {
                this._saveBlob(new Blob([result], { type: 'application/octet-stream' }), `PGFX_3D_Export_${+new Date()}.glb`);
                this._addAgentLog('🧊 3D Scene exported (.glb)');
            } else {
                // Fallback to text JSON if binary failed
                const output = JSON.stringify(result, null, 2);
                this._saveBlob(new Blob([output], { type: 'text/plain' }), `PGFX_3D_Export_${+new Date()}.gltf`);
                this._addAgentLog('🧊 3D Scene exported (.gltf)');
            }
        }, options);
    }

    async loadProject() {
        const input = document.createElement('input');
        input.type = 'file';
        input.accept = '.pgfx,.json';
        input.onchange = async () => {
            const file = input.files[0];
            if (!file) return;
            try {
                const text = await file.text();
                const state = JSON.parse(text);
                if (!state.pgfx_version) {
                    alert('Invalid project file (missing pgfx_version).');
                    return;
                }
                this._restoreProjectState(state);
            } catch (err) {
                console.error('[PGFX] Load error:', err);
                alert('Failed to load project: ' + err.message);
            }
        };
        input.click();
    }

    _restoreProjectState(state) {
        // 1. Restore editor settings
        if (state.editor) {
            if (state.editor.target_width) this.targetWidth = state.editor.target_width;
            if (state.editor.target_height) this.targetHeight = state.editor.target_height;
            if (state.editor.page_background_color) {
                this.pageBackgroundColor = state.editor.page_background_color;
                const el = document.getElementById('pgfx-page-bg-color');
                if (el) el.value = state.editor.page_background_color;
            }
            if (state.editor.custom_fonts) {
                this.customFonts = state.editor.custom_fonts;
            }
            if (state.editor.show_grid !== undefined) {
                const el = document.getElementById('pgfx-show-grid');
                if (el) el.checked = state.editor.show_grid;
            }
            if (state.editor.grid_size !== undefined) {
                const el = document.getElementById('pgfx-grid-size');
                if (el) el.value = state.editor.grid_size;
                const valEl = document.getElementById('pgfx-grid-size-val');
                if (valEl) valEl.textContent = String(state.editor.grid_size);
            }
        }

        // 2. Restore canvas objects
        if (state.canvas_json && this.canvas) {
            this.isProcessingHistory = true;
            this.canvas.loadFromJSON(state.canvas_json, () => {
                this.isProcessingHistory = false;
                this.canvas.requestRenderAll();
                this.refreshLayersPanel();
            });
        }

        // 3. Restore canvas text
        if (state.canvas_text != null) {
            this.lastCanvasText = state.canvas_text;
            if (this.textWidget) this.textWidget.value = state.canvas_text;
        }

        // 4. Restore node widgets
        if (state.node_widgets && this.node?.widgets) {
            for (const w of this.node.widgets) {
                if (state.node_widgets[w.name] !== undefined) {
                    w.value = state.node_widgets[w.name];
                    if (w.callback) w.callback(w.value);
                }
            }
        }

        // 5. Restore 3D settings
        if (state.settings_3d) {
            const s = state.settings_3d;
            const setVal = (id, val) => {
                const el = document.getElementById(id);
                if (el) el.value = val;
            };
            setVal('pgfx-3d-depth', s.depth ?? 20);
            setVal('pgfx-3d-bevel-enabled', s.bevel_enabled ?? false);
            setVal('pgfx-3d-bevel-size', s.bevel_size ?? 1.5);
            setVal('pgfx-3d-bevel-segments', s.bevel_segments ?? 3);
            setVal('pgfx-3d-material', s.material || 'matte_plastic');
            const setChecked = (id, val) => {
                const el = document.getElementById(id);
                if (el) el.checked = !!val;
            };
            setChecked('pgfx-3d-show-grid', s.show_grid_3d ?? true);
            const bevSettings = document.getElementById('pgfx-3d-bevel-settings');
            if (bevSettings) {
                bevSettings.style.display = (s.bevel_enabled ?? false) ? 'flex' : 'none';
            }
        }

        // 6. Restore brush settings
        if (state.brush) {
            const set = (id, val) => {
                const el = document.getElementById(id);
                if (el) el.value = val;
            };
            set('pgfx-brush-type', state.brush.type || 'Pencil');
            set('pgfx-brush-size', state.brush.size ?? 10);
            set('pgfx-brush-color', state.brush.color || '#ffffff');
            set('pgfx-brush-opacity', state.brush.opacity ?? 1);
        }

        // 7. Restore imported 3D models
        this.importedModels = [];
        if (state.imported_models && Array.isArray(state.imported_models)) {
            for (const m of state.imported_models) {
                if (m.data) {
                    const entry = { id: m.id, name: m.name, format: m.format, data: m.data };
                    this.importedModels.push(entry);
                }
            }
        }

        // If in 3D mode, rebuild extruded meshes and restore imported models
        if (this.mode3D && this.extrudedGroup) {
            const grid3DCheck = document.getElementById('pgfx-3d-show-grid');
            if (grid3DCheck && this.gridHelper) this.gridHelper.visible = grid3DCheck.checked;
            if (grid3DCheck && this.axesHelper) this.axesHelper.visible = grid3DCheck.checked;
            this.sync2DTo3D().then(() => {
                if (this.modelsGroup) {
                    for (const entry of this.importedModels) {
                        if (entry.data && !entry.group) {
                            this._loadModelIntoScene(entry).catch(err => {
                                console.error('[PGFX] Failed to restore model:', entry.name, err);
                            });
                        }
                    }
                }
                this.fit3DView();
            });
        }

        this._addAgentLog('📂 Project loaded');
        this.scheduleNodeStateSync();
    }

    setupEventHandlers() {
        const commitCanvasChange = () => {
            this.commitCanvasChange();
        };

        // --- CONTEXT MENU ---
        const ctxMenu = document.getElementById('pgfx-context-menu');
        this.canvas.on('mouse:down', (opt) => {
            if (opt.e.button === 2) { // Right click
                const active = this.canvas.getActiveObject();
                if (active) {
                    ctxMenu.style.display = 'flex';
                    ctxMenu.style.left = opt.e.clientX + 'px';
                    ctxMenu.style.top = opt.e.clientY + 'px';
                }
            } else {
                ctxMenu.style.display = 'none';
            }
        });

        document.getElementById('pgfx-ctx-clone').onclick = () => {
            document.getElementById('pgfx-clone').click();
            ctxMenu.style.display = 'none';
        };
        document.getElementById('pgfx-ctx-group').onclick = () => {
            document.getElementById('pgfx-group-btn').click();
            ctxMenu.style.display = 'none';
        };
        document.getElementById('pgfx-ctx-ungroup').onclick = () => {
            document.getElementById('pgfx-ungroup-btn').click();
            ctxMenu.style.display = 'none';
        };
        document.getElementById('pgfx-ctx-lock').onclick = () => {
            const active = this.canvas.getActiveObject();
            if (active) {
                const isLocked = !active.selectable;
                active.set({
                    selectable: isLocked,
                    evented: isLocked,
                    hasControls: isLocked,
                    hasBorders: isLocked
                });
                commitCanvasChange();
            }
            ctxMenu.style.display = 'none';
        };
        document.getElementById('pgfx-ctx-hide').onclick = () => {
            const active = this.canvas.getActiveObject();
            if (active) {
                active.set('visible', !active.visible);
                commitCanvasChange();
            }
            ctxMenu.style.display = 'none';
        };
        document.getElementById('pgfx-ctx-delete').onclick = () => {
            const active = this.canvas.getActiveObject();
            if (active) {
                this.canvas.remove(active);
                commitCanvasChange();
            }
            ctxMenu.style.display = 'none';
        };
        document.getElementById('pgfx-ctx-agent').onclick = () => {
            this.sendToAgent();
            ctxMenu.style.display = 'none';
        };

        // Hide context menu on scroll or resize
        window.addEventListener('scroll', () => ctxMenu.style.display = 'none');
        window.addEventListener('resize', () => ctxMenu.style.display = 'none');
        this.overlay.onclick = (e) => {
            if (!ctxMenu.contains(e.target)) ctxMenu.style.display = 'none';
        };

        // Disable native context menu on canvas
        this.canvas.upperCanvasEl.oncontextmenu = (e) => e.preventDefault();

        // Elite Bridge
        document.getElementById('pgfx-send-agent-btn').onclick = () => this.sendToAgent();

        // Save / Load Project
        document.getElementById('pgfx-save-project').onclick = () => this.saveProject();
        document.getElementById('pgfx-load-project').onclick = () => this.loadProject();

        // --- ADD ELEMENTS ---
        document.getElementById('pgfx-add-text').onclick = () => {
            const font = document.getElementById('pgfx-font-select').value;
            const text = new fabric.IText("NEW TEXT", {
                left: this.targetWidth / 2, top: this.targetHeight / 2,
                fontFamily: font, fontSize: 100, fill: '#ffffff', originX: 'center', originY: 'center'
            });
            this.canvas.add(text);
            this.canvas.setActiveObject(text);
            commitCanvasChange();
        };

        document.getElementById('pgfx-add-rect').onclick = () => {
            const rect = new fabric.Rect({
                left: this.targetWidth / 2, top: this.targetHeight / 2,
                width: 200, height: 200, fill: '#ffffff', originX: 'center', originY: 'center'
            });
            this.canvas.add(rect);
            this.canvas.setActiveObject(rect);
            commitCanvasChange();
        };

        document.getElementById('pgfx-add-circle').onclick = () => {
            const circle = new fabric.Circle({
                left: this.targetWidth / 2, top: this.targetHeight / 2,
                radius: 100, fill: '#ffffff', originX: 'center', originY: 'center'
            });
            this.canvas.add(circle);
            this.canvas.setActiveObject(circle);
            commitCanvasChange();
        };

        document.getElementById('pgfx-add-triangle').onclick = () => {
            const tri = new fabric.Triangle({
                left: this.targetWidth / 2, top: this.targetHeight / 2,
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
                left: this.targetWidth / 2, top: this.targetHeight / 2,
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
                left: this.targetWidth / 2, top: this.targetHeight / 2,
                fill: '#ffffff', originX: 'center', originY: 'center'
            });
            this.canvas.add(hex);
            this.canvas.setActiveObject(hex);
            commitCanvasChange();
        };

        // --- INTERACTION (ZOOM & PAN & SNAPPING) ---
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

        const _snapGrid = () => parseFloat(document.getElementById('pgfx-grid-size')?.value) || 10;

        this.canvas.on('object:moving', (options) => {
            if (document.getElementById('pgfx-snap-grid').checked) {
                const gs = _snapGrid();
                options.target.set({
                    left: Math.round(options.target.left / gs) * gs,
                    top: Math.round(options.target.top / gs) * gs
                });
            }
        });

        this.canvas.on('object:scaling', (options) => {
            if (document.getElementById('pgfx-snap-grid').checked) {
                const gs = _snapGrid();
                const target = options.target;
                const w = target.width * target.scaleX;
                const h = target.height * target.scaleY;
                const snapW = Math.round(w / gs) * gs;
                const snapH = Math.round(h / gs) * gs;
                target.set({
                    scaleX: snapW / target.width,
                    scaleY: snapH / target.height
                });
            }
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
        fileInput.onchange = async (e) => {
            const file = e.target.files[0];
            if(!file) return;

            const isSVG = file.type === "image/svg+xml" || file.name.endsWith('.svg');

            // Generate clean unique filename to avoid conflicts and cache collisions
            const cleanName = file.name.replace(/[^a-zA-Z0-9._-]/g, '_');
            const uniqueName = `pgfx_${Date.now()}_${cleanName}`;

            let url = URL.createObjectURL(file);
            let persistentUrl = null;

            try {
                const body = new FormData();
                body.append("image", file, uniqueName);
                body.append("overwrite", "true");
                body.append("subfolder", "pgfx_assets");

                const resp = await fetch("/upload/image", {
                    method: "POST",
                    body
                });
                if (resp.ok) {
                    const data = await resp.json();
                    persistentUrl = `/view?filename=${encodeURIComponent(data.name)}&type=input&subfolder=${encodeURIComponent(data.subfolder || '')}`;
                    console.log("[PGFX Studio] Persistent asset uploaded:", persistentUrl);
                } else {
                    console.warn("[PGFX Studio] Asset upload failed, falling back to local Blob URL");
                }
            } catch (err) {
                console.error("[PGFX Studio] Asset upload exception:", err);
            }

            const targetUrl = persistentUrl || url;
            if (persistentUrl) {
                URL.revokeObjectURL(url); // Not using the blob URL, revoke it now
            }

            if (isSVG) {
                fabric.loadSVGFromURL(targetUrl, (objects, options) => {
                    const obj = fabric.util.groupSVGElements(objects, options);
                    if (!obj) return;
                    obj.set({ left: this.targetWidth / 2, top: this.targetHeight / 2, originX: 'center', originY: 'center' });
                    if (obj.width < 10 || obj.height < 10) obj.scaleToWidth(200);
                    if (obj.width > 800) obj.scaleToWidth(800);
                    this.canvas.add(obj);
                    this.canvas.setActiveObject(obj);
                    commitCanvasChange();
                    if (!persistentUrl) URL.revokeObjectURL(url); // Revoke fallback blob URL after load
                });
            } else {
                fabric.Image.fromURL(targetUrl, (img) => {
                    img.set({ left: this.targetWidth / 2, top: this.targetHeight / 2, originX: 'center', originY: 'center' });
                    if (img.width > 800) img.scaleToWidth(800);
                    this.canvas.add(img);
                    this.canvas.setActiveObject(img);
                    commitCanvasChange();
                    if (!persistentUrl) URL.revokeObjectURL(url); // Revoke fallback blob URL after load
                });
            }
            fileInput.value = '';
        };

        // --- 3D MODEL IMPORTER ---
        this.importedModels = [];
        const modelInput = document.getElementById('pgfx-import-3d-input');
        const importBtn = document.getElementById('pgfx-import-3d-btn');
        const clearBtn = document.getElementById('pgfx-clear-3d-models-btn');
        if (importBtn && modelInput) {
            importBtn.onclick = () => modelInput.click();
            modelInput.onchange = async (e) => {
                const file = e.target.files[0];
                if (!file) return;
                try {
                    const buffer = await file.arrayBuffer();
                    const ext = file.name.split('.').pop().toLowerCase();
                    const base64 = this._bufferToBase64(buffer);
                    const modelEntry = {
                        id: 'model_' + Date.now(),
                        name: file.name,
                        format: ext,
                        data: base64,
                    };
                    this.importedModels.push(modelEntry);
                    await this._loadModelIntoScene(modelEntry);
                    this.fit3DView();
                    this.scheduleNodeStateSync();
                } catch (err) {
                    console.error('[PGFX] 3D model import error:', err);
                    alert('Failed to import 3D model: ' + err.message);
                }
                modelInput.value = '';
            };
        }
        if (clearBtn) {
            clearBtn.onclick = () => {
                for (const m of this.importedModels) {
                    if (m.group) {
                        this.modelsGroup.remove(m.group);
                        this._disposeModelGroup(m.group);
                    }
                }
                this.importedModels = [];
                this.scheduleNodeStateSync();
            };
        }

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
        document.getElementById('pgfx-fill-type').onchange = (e) => {
            const type = e.target.value;
            document.getElementById('pgfx-fill-solid-row').style.display = type === 'solid' ? 'flex' : 'none';
            document.getElementById('pgfx-fill-gradient-controls').style.display = type === 'solid' ? 'none' : 'flex';
            this.updateGradient();
        };

        document.getElementById('pgfx-color-picker').oninput = (e) => {
            // 3D mode: update selected mesh material color
            if (this.mode3D && this.selectedMesh3d) {
                const color = new THREE.Color(e.target.value);
                const mat = this.selectedMesh3d.material;
                if (mat) {
                    if (Array.isArray(mat)) {
                        mat.forEach(m => { m.color = color; m.needsUpdate = true; });
                    } else {
                        mat.color = color;
                        mat.needsUpdate = true;
                    }
                } else {
                    // Possibly an imported model group — update all child meshes
                    this.selectedMesh3d.traverse((child) => {
                        if (child.isMesh && child.material) {
                            if (Array.isArray(child.material)) {
                                child.material.forEach(m => { m.color = color; m.needsUpdate = true; });
                            } else {
                                child.material.color = color;
                                child.material.needsUpdate = true;
                            }
                        }
                    });
                }
                return;
            }
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

        ['pgfx-gradient-start', 'pgfx-gradient-end', 'pgfx-gradient-angle'].forEach(id => {
            document.getElementById(id).oninput = () => {
                if (id === 'pgfx-gradient-angle') {
                    document.getElementById('pgfx-gradient-angle-val').textContent = document.getElementById(id).value + '°';
                }
                this.updateGradient();
            };
        });

        document.getElementById('pgfx-stroke-picker').oninput = (e) => {
            if (this.mode3D && this.selectedMesh3d) {
                this._update3DStroke(this.selectedMesh3d);
                return;
            }
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
            const valEl = document.getElementById('pgfx-stroke-width-val');
            if (valEl) valEl.textContent = e.target.value;
            if (this.mode3D && this.selectedMesh3d) {
                this._update3DStroke(this.selectedMesh3d);
                return;
            }
            const active = this.canvas.getActiveObject();
            if (active) {
                active.set('strokeWidth', parseInt(e.target.value));
                commitCanvasChange();
            }
        };

        // Shadows
        document.getElementById('pgfx-shadow-enabled').onchange = (e) => {
            document.getElementById('pgfx-shadow-controls').style.display = e.target.checked ? 'flex' : 'none';
            this.updateShadow();
        };

        ['pgfx-shadow-color', 'pgfx-shadow-blur', 'pgfx-shadow-offset-x', 'pgfx-shadow-offset-y'].forEach(id => {
            document.getElementById(id).oninput = () => {
                const val = document.getElementById(id).value;
                const readout = document.getElementById(id + '-val');
                if (readout) readout.textContent = val;
                this.updateShadow();
            };
        });

        document.getElementById('pgfx-show-grid').onchange = () => {
            if (this.canvas) this.canvas.requestRenderAll();
        };
        document.getElementById('pgfx-grid-size').oninput = (e) => {
            const valEl = document.getElementById('pgfx-grid-size-val');
            if (valEl) valEl.textContent = e.target.value;
            if (this.canvas) this.canvas.requestRenderAll();
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
            const valEl = document.getElementById('pgfx-font-size-val');
            if (valEl) valEl.textContent = e.target.value;
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
            const valEl = document.getElementById('pgfx-letter-spacing-val');
            if (valEl) valEl.textContent = e.target.value;
            if (active && active.type.includes('text')) {
                active.set('charSpacing', parseInt(e.target.value));
                commitCanvasChange();
            }
        };

        document.getElementById('pgfx-line-spacing').oninput = (e) => {
            const active = this.canvas.getActiveObject();
            const valEl = document.getElementById('pgfx-line-spacing-val');
            if (valEl) valEl.textContent = parseFloat(e.target.value).toFixed(2);
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
            const valEl = document.getElementById('pgfx-rotation-val');
            if (valEl) valEl.textContent = e.target.value + '°';
            if (active) {
                active.rotate(parseInt(e.target.value));
                commitCanvasChange();
            }
        };

        document.getElementById('pgfx-skew-x').oninput = (e) => {
            const active = this.canvas.getActiveObject();
            const valEl = document.getElementById('pgfx-skew-x-val');
            if (valEl) valEl.textContent = e.target.value;
            if (active) {
                active.set('skewX', parseInt(e.target.value));
                commitCanvasChange();
            }
        };

        document.getElementById('pgfx-opacity').oninput = (e) => {
            const val = parseFloat(e.target.value);
            const valEl = document.getElementById('pgfx-opacity-val');
            if (valEl) valEl.textContent = Math.round(val * 100) + '%';
            // 3D mode: update mesh material opacity
            if (this.mode3D && this.selectedMesh3d) {
                const mat = this.selectedMesh3d.material;
                if (mat) {
                    if (Array.isArray(mat)) {
                        mat.forEach(m => { m.opacity = val; m.transparent = val < 1; m.needsUpdate = true; });
                    } else {
                        mat.opacity = val;
                        mat.transparent = val < 1;
                        mat.needsUpdate = true;
                    }
                } else {
                    // Possibly an imported model group — update all child meshes
                    this.selectedMesh3d.traverse((child) => {
                        if (child.isMesh && child.material) {
                            if (Array.isArray(child.material)) {
                                child.material.forEach(m => { m.opacity = val; m.transparent = val < 1; m.needsUpdate = true; });
                            } else {
                                child.material.opacity = val;
                                child.material.transparent = val < 1;
                                child.material.needsUpdate = true;
                            }
                        }
                    });
                }
                return;
            }
            const active = this.canvas.getActiveObject();
            if (active) {
                active.set('opacity', val);
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
            if (active) {
                if (active.type === 'activeSelection') {
                    // Relative alignment within selection
                    const objects = active.getObjects();
                    const center = active.getCenterPoint();
                    objects.forEach(obj => {
                        obj.set({ left: 0 }); // Local center within group
                    });
                } else {
                    // Align to canvas center
                    const centerPoint = active.getCenterPoint();
                    const offset = (this.targetWidth / 2) - centerPoint.x;
                    active.set({ left: active.left + offset });
                }
                active.setCoords();
                commitCanvasChange();
            }
        };
        document.getElementById('pgfx-align-v').onclick = () => {
            const active = this.canvas.getActiveObject();
            if (active) {
                if (active.type === 'activeSelection') {
                    // Relative alignment within selection
                    const objects = active.getObjects();
                    objects.forEach(obj => {
                        obj.set({ top: 0 }); // Local center within group
                    });
                } else {
                    // Align to canvas center
                    const centerPoint = active.getCenterPoint();
                    const offset = (this.targetHeight / 2) - centerPoint.y;
                    active.set({ top: active.top + offset });
                }
                active.setCoords();
                commitCanvasChange();
            }
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
        this.canvas.on('selection:created', () => {
            this.updateUIForSelection();
            this.refreshLayersPanel();
        });
        this.canvas.on('selection:updated', () => {
            this.updateUIForSelection();
            this.refreshLayersPanel();
        });
        this.canvas.on('selection:cleared', () => {
            this.refreshLayersPanel();
        });
        this.canvas.on('object:added', () => {
            this.refreshLayersPanel();
            // Don't save to history during initial load or undo/redo restore
            if (!this.isProcessingHistory) this._saveToHistory();
        });
        this.canvas.on('object:modified', () => {
            this.refreshLayersPanel();
            this._updateSelectionUI();
            this._saveToHistory();
            this.scheduleNodeStateSync();
        });
        this.canvas.on('object:removed', () => {
            this.refreshLayersPanel();
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
            ctx.fillRect(0, 0, this.targetWidth, this.targetHeight);

            ctx.restore();
        });

        // Locked page boundary dashed outline (Bug 4)
        this.canvas.on('after:render', () => {
            if (this.isExporting) return;
            const ctx = this.canvas.getContext();
            const vpt = this.canvas.viewportTransform;
            const zoom = this.canvas.getZoom();

            // 2D Canvas Grid
            const showGrid = document.getElementById('pgfx-show-grid')?.checked;
            if (showGrid) {
                const gridSize = parseFloat(document.getElementById('pgfx-grid-size')?.value) || 50;
                ctx.save();
                ctx.transform(vpt[0], vpt[1], vpt[2], vpt[3], vpt[4], vpt[5]);

                const startX = -Math.ceil(this.targetWidth / gridSize) * gridSize;
                const startY = -Math.ceil(this.targetHeight / gridSize) * gridSize;
                const endX = this.targetWidth * 2;
                const endY = this.targetHeight * 2;

                ctx.strokeStyle = 'rgba(255,255,255,0.05)';
                ctx.lineWidth = 1 / zoom;

                // Major grid every 5th line
                for (let x = startX; x <= endX; x += gridSize) {
                    ctx.beginPath();
                    ctx.moveTo(x, startY);
                    ctx.lineTo(x, endY);
                    if (x % (gridSize * 5) === 0) ctx.strokeStyle = 'rgba(255,255,255,0.1)';
                    else ctx.strokeStyle = 'rgba(255,255,255,0.04)';
                    ctx.stroke();
                }
                for (let y = startY; y <= endY; y += gridSize) {
                    ctx.beginPath();
                    ctx.moveTo(startX, y);
                    ctx.lineTo(endX, y);
                    if (y % (gridSize * 5) === 0) ctx.strokeStyle = 'rgba(255,255,255,0.1)';
                    else ctx.strokeStyle = 'rgba(255,255,255,0.04)';
                    ctx.stroke();
                }

                ctx.restore();
            }

            ctx.save();
            ctx.transform(vpt[0], vpt[1], vpt[2], vpt[3], vpt[4], vpt[5]);

            ctx.strokeStyle = 'rgba(6, 182, 212, 0.8)';
            ctx.lineWidth = 2 / zoom;
            ctx.setLineDash([4 / zoom, 4 / zoom]);
            ctx.strokeRect(0, 0, this.targetWidth, this.targetHeight);

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

            // ARROW KEYS: Nudge active object (1px standard, 10px with Shift)
            if (['ArrowLeft', 'ArrowUp', 'ArrowRight', 'ArrowDown'].includes(e.key)) {
                if (activeObject) {
                    e.preventDefault();
                    const moveAmount = e.shiftKey ? 10 : 1;
                    let deltaX = 0;
                    let deltaY = 0;

                    if (e.key === 'ArrowLeft') deltaX = -moveAmount;
                    else if (e.key === 'ArrowRight') deltaX = moveAmount;
                    else if (e.key === 'ArrowUp') deltaY = -moveAmount;
                    else if (e.key === 'ArrowDown') deltaY = moveAmount;

                    activeObject.set({
                        left: activeObject.left + deltaX,
                        top: activeObject.top + deltaY
                    });
                    activeObject.setCoords();
                    this.canvas.fire('object:modified', { target: activeObject });
                    this.canvas.requestRenderAll();
                }
            }

            // DELETE / BACKSPACE: Remove object (2D), selected 3D mesh, or imported model
            if (e.key === 'Delete' || e.key === 'Backspace') {
                if (this.mode3D && this.selectedMesh3d) {
                    const mesh = this.selectedMesh3d;
                    this.deselectMesh3d();
                    // Check if it's an imported model
                    if (mesh.parent === this.modelsGroup || mesh.userData._importedModelId) {
                        const modelId = mesh.userData._importedModelId;
                        const idx = this.importedModels.findIndex(m => m.id === modelId);
                        if (idx !== -1) {
                            const entry = this.importedModels[idx];
                            this.modelsGroup.remove(entry.group);
                            this._disposeModelGroup(entry.group);
                            this.importedModels.splice(idx, 1);
                        } else {
                            this.modelsGroup.remove(mesh);
                            this._disposeModelGroup(mesh);
                        }
                    } else {
                        this.extrudedGroup.remove(mesh);
                        if (mesh.geometry) mesh.geometry.dispose();
                        if (mesh.material) {
                            if (Array.isArray(mesh.material)) {
                                mesh.material.forEach(m => m.dispose());
                            } else {
                                mesh.material.dispose();
                            }
                        }
                    }
                    return;
                }
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

            // 3D TRANSFORM MODE SHORTCUTS (only in 3D mode)
            if (this.mode3D) {
                if (e.key.toLowerCase() === 'w') {
                    e.preventDefault();
                    this.setTransformMode('translate');
                } else if (e.key.toLowerCase() === 'e') {
                    e.preventDefault();
                    this.setTransformMode('rotate');
                } else if (e.key.toLowerCase() === 'r') {
                    e.preventDefault();
                    this.fit3DView();
                }
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

        // Add window resize event listener to automatically keep the view fitted
        window.addEventListener('resize', () => {
            if (this.overlay && this.overlay.classList.contains('active')) {
                this.fitCanvasToView();
            }
        });

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

        const saveBtn = document.getElementById('pgfx-save-btn');
        if (saveBtn) {
            saveBtn.onclick = async () => {
                saveBtn.disabled = true;
                const originalText = saveBtn.innerHTML;
                saveBtn.innerHTML = "Saving...";
                try {
                    await this.applyCanvasStateToNode({ bumpSeed: true, closeAfter: true });
                } catch (err) {
                    console.error("[PGFX Studio] Failed to save canvas state:", err);
                    alert("Failed to save: " + err.message);
                } finally {
                    saveBtn.disabled = false;
                    saveBtn.innerHTML = originalText;
                }
            };
        }

        document.getElementById('pgfx-cancel-btn').onclick = () => this.close();

        // --- EXPORT ACTIONS ---
        document.getElementById('pgfx-export-svg-btn').onclick = () => {
            if (!this.canvas) return;
            const svgData = this.canvas.toSVG();
            const blob = new Blob([svgData], { type: 'image/svg+xml;charset=utf-8' });
            this._saveBlob(blob, `PGFX_Design_${+new Date()}.svg`);
        };

        document.getElementById('pgfx-export-3d-btn').onclick = () => {
            this.export3D();
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
            // Clear all paths drawn with the brush or tagged as free draw
            const objects = this.canvas.getObjects().filter(o => 
                o.name === 'pgfx_free_draw' || 
                (o.type === 'path' && !o.name)
            );
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

        // --- 3D TRANSFORM MODE BUTTONS ---
        const btnTrans = document.getElementById('pgfx-3d-mode-translate');
        const btnRot = document.getElementById('pgfx-3d-mode-rotate');
        const btnScale = document.getElementById('pgfx-3d-mode-scale');
        if (btnTrans) btnTrans.onclick = () => this.setTransformMode('translate');
        if (btnRot) btnRot.onclick = () => this.setTransformMode('rotate');
        if (btnScale) btnScale.onclick = () => this.setTransformMode('scale');

        // --- OBJECT PROPERTIES INPUT HANDLERS ---
        ['pgfx-prop-x','pgfx-prop-y','pgfx-prop-z','pgfx-prop-rotation','pgfx-prop-scale'].forEach(id => {
            const el = document.getElementById(id);
            if (el) {
                el.onchange = () => {
                    if (this.mode3D) {
                        this._applyPropertyTo3D();
                    } else {
                        this._applyPropertyTo2D();
                    }
                };
            }
        });

        // --- 3D VIEWPORT TAB & CONTROL EVENTS ---
        const tab2D = document.getElementById('pgfx-tab-2d');
        const tab3D = document.getElementById('pgfx-tab-3d');
        if (tab2D && tab3D) {
            tab2D.onclick = () => this.toggleViewportTab('2D');
            tab3D.onclick = () => this.toggleViewportTab('3D');
        }

        const depthInput = document.getElementById('pgfx-3d-depth');
        if (depthInput) {
            depthInput.oninput = (e) => {
                document.getElementById('pgfx-3d-depth-val').textContent = e.target.value;
                if (this.mode3D) {
                    this._applyObj3DSettings();
                } else {
                    this.sync2DTo3D();
                }
            };
        }

        const bevelEnabledInput = document.getElementById('pgfx-3d-bevel-enabled');
        if (bevelEnabledInput) {
            bevelEnabledInput.onchange = (e) => {
                document.getElementById('pgfx-3d-bevel-settings').style.display = e.target.checked ? 'flex' : 'none';
                if (this.mode3D) {
                    this._applyObj3DSettings();
                } else {
                    this.sync2DTo3D();
                }
            };
        }

        const bevelSizeInput = document.getElementById('pgfx-3d-bevel-size');
        if (bevelSizeInput) {
            bevelSizeInput.oninput = (e) => {
                document.getElementById('pgfx-3d-bevel-size-val').textContent = e.target.value;
                if (this.mode3D) {
                    this._applyObj3DSettings();
                } else {
                    this.sync2DTo3D();
                }
            };
        }

        const bevelSegsInput = document.getElementById('pgfx-3d-bevel-segments');
        if (bevelSegsInput) {
            bevelSegsInput.oninput = (e) => {
                document.getElementById('pgfx-3d-bevel-segments-val').textContent = e.target.value;
                if (this.mode3D) {
                    this._applyObj3DSettings();
                } else {
                    this.sync2DTo3D();
                }
            };
        }

        const matSelect = document.getElementById('pgfx-3d-material');
        if (matSelect) {
            matSelect.onchange = () => this.sync2DTo3D();
        }

        const lightRotInput = document.getElementById('pgfx-3d-light-rot');
        if (lightRotInput) {
            lightRotInput.oninput = (e) => {
                const rotVal = parseFloat(e.target.value);
                document.getElementById('pgfx-3d-light-rot-val').textContent = rotVal + '°';
                if (this.dirLight) {
                    const rad = THREE.MathUtils.degToRad(rotVal);
                    // Orbit the light around the scene center
                    const dist = 800;
                    this.dirLight.position.set(
                        Math.cos(rad) * dist,
                        Math.sin(rad) * dist,
                        600
                    );
                }
            };
        }

        const shadowCheck = document.getElementById('pgfx-3d-shadows');
        if (shadowCheck) {
            shadowCheck.onchange = (e) => {
                if (this.dirLight) {
                    this.dirLight.castShadow = e.target.checked;
                }
                // Refresh scene to apply shadow changes to all materials if needed
                this.sync2DTo3D();
            };
        }

        const resetCamBtn = document.getElementById('pgfx-3d-reset-cam');
        if (resetCamBtn) {
            resetCamBtn.onclick = () => this.fit3DView();
        }

        // 3D Grid toggle
        const grid3DCheck = document.getElementById('pgfx-3d-show-grid');
        if (grid3DCheck) {
            grid3DCheck.onchange = (e) => {
                if (this.gridHelper) this.gridHelper.visible = e.target.checked;
                if (this.axesHelper) this.axesHelper.visible = e.target.checked;
            };
        }
    }

    async toggleViewportTab(mode) {
        const tab2D = document.getElementById('pgfx-tab-2d');
        const tab3D = document.getElementById('pgfx-tab-3d');
        const container2D = document.getElementById('pgfx-2d-canvas-container');
        const container3D = document.getElementById('pgfx-3d-canvas-container');
        const rightSidebar = document.querySelector('.pgfx-studio-right-sidebar');
        const tools3D = document.getElementById('pgfx-3d-tools-group');
        const zRow = document.getElementById('pgfx-prop-z-row');
        const sidebar3D = document.getElementById('pgfx-3d-sidebar-controls');

        if (mode === '3D') {
            this.mode3D = true;
            tab2D.classList.remove('pgfx-btn-primary');
            tab3D.classList.add('pgfx-btn-primary');
            container2D.style.display = 'none';
            container3D.style.display = 'block';
            if (rightSidebar) rightSidebar.style.display = 'flex';
            if (tools3D) tools3D.style.display = 'block';
            if (zRow) zRow.style.display = 'flex';
            if (sidebar3D) sidebar3D.style.display = 'flex';

            // Wake up renderer with a hard resize to fix the "black void"
            if (this.renderer3d) {
                const w = container3D.clientWidth || 800;
                const h = container3D.clientHeight || 600;
                this.camera3d.aspect = w / h;
                this.camera3d.updateProjectionMatrix();
                this.renderer3d.setSize(w, h);
            }

            try {
                // Asynchronously load Three.js libraries
                const loadingOverlay = document.getElementById('pgfx-studio-loading');
                const loadingStatus = document.getElementById('pgfx-loading-status');
                await loadThreeJS(loadingStatus || null);
                if (!this.scene3d) {
                    this.init3DScene();
                }
                
                // Rebuild scene
                await this.sync2DTo3D();
                
                // Restore imported models
                if (this.importedModels && this.importedModels.length > 0) {
                    for (const m of this.importedModels) {
                        if (m.data && !m.group) {
                            await this._loadModelIntoScene(m).catch(e => console.error('[PGFX] Restore model failed', e));
                        }
                    }
                }
                
                // Ensure camera is framing correctly
                setTimeout(() => this.fit3DView(), 100);
                
            } catch (err) {
                console.error("[PGFX Studio] 3D Activation Error:", err);
                container3D.innerHTML = `<div style="display: flex; align-items: center; justify-content: center; width: 100%; height: 100%; color: #ef4444; font-size: 14px; font-weight: bold; text-align: center; flex-direction: column;">Error activating 3D:<br>${err.message}</div>`;
            }
        } else {
            this.mode3D = false;
            tab2D.classList.add('pgfx-btn-primary');
            tab3D.classList.remove('pgfx-btn-primary');
            container2D.style.display = 'block';
            container3D.style.display = 'none';
            if (rightSidebar) rightSidebar.style.display = 'flex';
            if (tools3D) tools3D.style.display = 'none';
            if (zRow) zRow.style.display = 'none';
            if (sidebar3D) sidebar3D.style.display = 'none';

            // Clean up 3D to release WebGL context and graphics memory
            this.cleanUp3D();

            // Force redraw of 2D canvas
            if (this.canvas) {
                this.canvas.requestRenderAll();
                this.fitCanvasToView();
            }

            // Refresh layers & properties for 2D
            this.refreshLayersPanel();
            this._updateSelectionUI();
            this.updateUIForSelection();
        }
    }

    init3DScene() {
        const container = document.getElementById('pgfx-3d-canvas-container');
        if (!container) return;

        // Clear container
        container.innerHTML = '';

        // Safety: Ensure we have valid dimensions
        const width = Math.max(container.clientWidth, 800);
        const height = Math.max(container.clientHeight, 600);

        // Create Scene
        this.scene3d = new THREE.Scene();
        this.scene3d.background = new THREE.Color(0x2a2a2a); // Professional gray

        // Create Camera
        this.camera3d = new THREE.PerspectiveCamera(45, width / height, 1, 10000);
        this.camera3d.position.set(0, 0, 1000);

        // Create Renderer
        this.renderer3d = new THREE.WebGLRenderer({ antialias: true, alpha: false, preserveDrawingBuffer: true });
        this.renderer3d.setSize(width, height);
        this.renderer3d.setPixelRatio(Math.min(window.devicePixelRatio, 2));
        this.renderer3d.shadowMap.enabled = true;
        this.renderer3d.shadowMap.type = THREE.PCFSoftShadowMap;
        container.appendChild(this.renderer3d.domElement);

        // OrbitControls
        this.controls3d = new THREE.OrbitControls(this.camera3d, this.renderer3d.domElement);
        this.controls3d.enableDamping = true;
        this.controls3d.dampingFactor = 0.05;
        this.controls3d.screenSpacePanning = true;

        // TransformControls
        if (window.THREE.TransformControls) {
            this.transformControls3d = new THREE.TransformControls(this.camera3d, this.renderer3d.domElement);
            this.transformControls3d.setMode(this.transformMode);
            this.scene3d.add(this.transformControls3d);
            this.transformControls3d.addEventListener('dragging-changed', (e) => this.controls3d.enabled = !e.value);
            this.transformControls3d.addEventListener('change', () => this._updateSelectionUI());
        }

        this.raycaster3d = new THREE.Raycaster();
        this.mouse3d = new THREE.Vector2();

        // Click-to-select
        this.renderer3d.domElement.addEventListener('click', (event) => {
            if (this.transformControls3d && this.transformControls3d.dragging) return;
            const rect = this.renderer3d.domElement.getBoundingClientRect();
            this.mouse3d.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
            this.mouse3d.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
            if (this.raycaster3d && this.extrudedGroup) {
                this.raycaster3d.setFromCamera(this.mouse3d, this.camera3d);
                const allTargets = [...this.extrudedGroup.children];
                if (this.modelsGroup) allTargets.push(...this.modelsGroup.children);
                const intersects = this.raycaster3d.intersectObjects(allTargets, true);
                if (intersects.length > 0) {
                    let hit = intersects[0].object;
                    while (hit.parent && hit.parent !== this.modelsGroup && hit.parent !== this.extrudedGroup && hit.parent !== this.scene3d) hit = hit.parent;
                    this.selectMesh3d(hit.parent === this.modelsGroup ? hit : intersects[0].object);
                } else this.deselectMesh3d();
            }
        });

        // Lights
        this.scene3d.add(new THREE.AmbientLight(0xffffff, 0.5));
        this.dirLight = new THREE.DirectionalLight(0xffffff, 1.0);
        this.dirLight.position.set(500, 500, 1000);
        this.dirLight.castShadow = true;
        this.dirLight.shadow.mapSize.set(2048, 2048);
        this.scene3d.add(this.dirLight);

        // Environment Helpers
        this.gridHelper = new THREE.GridHelper(5000, 50, 0x444444, 0x333333);
        this.gridHelper.position.z = -100;
        this.gridHelper.rotation.x = Math.PI / 2;
        this.scene3d.add(this.gridHelper);
        this.axesHelper = new THREE.AxesHelper(500);
        this.axesHelper.position.z = -90;
        this.scene3d.add(this.axesHelper);

        // --- CANVAS SAFE AREA (The Plane) ---
        const planeW = Math.max(this.targetWidth, 1);
        const planeH = Math.max(this.targetHeight, 1);
        const canvasPlaneGeom = new THREE.PlaneGeometry(planeW, planeH);
        const canvasPlaneMat = new THREE.MeshBasicMaterial({ 
            color: new THREE.Color(this.pageBackgroundColor || '#000000'),
            side: THREE.DoubleSide, transparent: true, opacity: 0.85
        });
        this.canvasPlane3d = new THREE.Mesh(canvasPlaneGeom, canvasPlaneMat);
        this.canvasPlane3d.position.set(0, 0, -10);
        this.canvasPlane3d.receiveShadow = true; // Essential for seeing shadows!
        this.scene3d.add(this.canvasPlane3d);

        const borderGeom = new THREE.EdgesGeometry(canvasPlaneGeom);
        this.canvasPlane3d.add(new THREE.LineSegments(borderGeom, new THREE.LineBasicMaterial({ color: 0x00ffff, linewidth: 2 })));

        // HUD Controls
        this._add3DViewControls(container);

        this.extrudedGroup = new THREE.Group();
        this.scene3d.add(this.extrudedGroup);
        this.modelsGroup = new THREE.Group();
        this.scene3d.add(this.modelsGroup);

        this.resizeObserver3d = new ResizeObserver(() => {
            if (!this.renderer3d) return;
            const w = Math.max(container.clientWidth, 100);
            const h = Math.max(container.clientHeight, 100);
            this.camera3d.aspect = w / h;
            this.camera3d.updateProjectionMatrix();
            this.renderer3d.setSize(w, h);
        });
        this.resizeObserver3d.observe(container);

        const animate = () => {
            if (!this.renderer3d) return;
            requestAnimationFrame(animate);
            if (this.controls3d) this.controls3d.update();
            this.renderer3d.render(this.scene3d, this.camera3d);
        };
        requestAnimationFrame(animate);
    }

    _add3DViewControls(container) {
        const hud = document.createElement('div');
        hud.style.cssText = `
            position: absolute; bottom: 20px; right: 20px;
            display: flex; gap: 10px; z-index: 100;
        `;
        
        const btnReset = document.createElement('button');
        btnReset.className = 'pgfx-btn';
        btnReset.innerHTML = '🎯 Center View';
        btnReset.onclick = () => {
            if (this.controls3d && this.camera3d) {
                this.controls3d.reset();
                this.camera3d.position.set(0, 0, 1000);
                this.controls3d.target.set(0, 0, 0);
                this.controls3d.update();
            }
        };
        
        const btnSync = document.createElement('button');
        btnSync.className = 'pgfx-btn pgfx-btn-primary';
        btnSync.innerHTML = '🔄 Sync 3D';
        btnSync.title = "Force a re-sync of design assets to the 3D scene.";
        btnSync.onclick = () => this.sync2DTo3D();

        hud.appendChild(btnSync);
        hud.appendChild(btnReset);
        container.appendChild(hud);
    }

    _keyForObj(obj, index) {
        return (obj.name || obj.type || 'obj') + '_' + index;
    }

    async sync2DTo3D() {
        if (!window.THREE || !this.extrudedGroup) return;

        // 1. Save selection state to recover it after sync
        const selectedKey = this.selectedMesh3d ? this.selectedMesh3d.userData._key : null;

        // 2. Update Canvas Safe Area Plane
        if (this.canvasPlane3d) {
            this.canvasPlane3d.material.color.set(this.pageBackgroundColor || '#000000');
            const currentGeom = this.canvasPlane3d.geometry.parameters;
            if (currentGeom.width !== this.targetWidth || currentGeom.height !== this.targetHeight) {
                this.canvasPlane3d.geometry.dispose();
                this.canvasPlane3d.geometry = new THREE.PlaneGeometry(this.targetWidth, this.targetHeight);
                if (this.canvasPlane3d.children.length > 0) {
                    const line = this.canvasPlane3d.children[0];
                    line.geometry.dispose();
                    line.geometry = new THREE.EdgesGeometry(this.canvasPlane3d.geometry);
                }
            }
        }

        // 3. Save 3D transforms before clearing
        const saved = {};
        for (let i = 0; i < this.extrudedGroup.children.length; i++) {
            const child = this.extrudedGroup.children[i];
            if (child.userData && child.userData._key) {
                saved[child.userData._key] = {
                    position: child.position.clone(),
                    rotation: child.rotation.clone(),
                    scale: child.scale.clone(),
                };
            }
        }
        Object.assign(this._saved3DTransforms, saved);

        // 4. Clear previous meshes
        while (this.extrudedGroup.children.length > 0) { 
            const childObj = this.extrudedGroup.children[0];
            this.extrudedGroup.remove(childObj);
            if (childObj.geometry) childObj.geometry.dispose();
            if (childObj.material) {
                if (Array.isArray(childObj.material)) childObj.material.forEach(m => { if (m) m.dispose(); });
                else childObj.material.dispose();
            }
        }

        const objects = this.canvas.getObjects();
        for (let index = 0; index < objects.length; index++) {
            const obj = objects[index];
            if (!obj.visible || obj.name === 'node_control') continue;
            const zOffset = index * 2; 

            if (obj.type === 'image' || obj.type === 'video') {
                const imgEl = obj.getElement();
                if (!imgEl) continue;
                const texture = new THREE.Texture(imgEl);
                texture.needsUpdate = true;
                const width = obj.width * obj.scaleX;
                const height = obj.height * obj.scaleY;
                const s3d = this._getObj3DSettings(obj);
                
                // Use a neutral base color
                const baseColor = '#888888';
                const material = this.createMaterialPreset(baseColor);
                
                let mesh;
                if (s3d.depth > 0) {
                    const geometry = new THREE.BoxGeometry(width, height, s3d.depth);
                    
                    // CRITICAL: Ensure side materials have NO map to prevent image repetition
                    const sideMat = material.clone();
                    sideMat.map = null;
                    sideMat.transparent = false; // Sides should be solid
                    
                    const frontMat = material.clone();
                    frontMat.map = texture;
                    frontMat.transparent = true;
                    
                    // BoxGeometry materials order: 0:right, 1:left, 2:top, 3:bottom, 4:front, 5:back
                    const materials = [sideMat, sideMat, sideMat, sideMat, frontMat, sideMat];
                    mesh = new THREE.Mesh(geometry, materials);
                } else {
                    const geometry = new THREE.PlaneGeometry(width, height);
                    const frontMat = material.clone();
                    frontMat.map = texture;
                    frontMat.transparent = true;
                    frontMat.side = THREE.DoubleSide;
                    mesh = new THREE.Mesh(geometry, frontMat);
                }
                
                mesh.userData.name = obj.name || 'Image';
                mesh.userData._key = this._keyForObj(obj, index);
                const center = obj.getCenterPoint();
                mesh.position.set(center.x - this.targetWidth / 2, -(center.y - this.targetHeight / 2), zOffset);
                mesh.rotation.z = THREE.MathUtils.degToRad(-obj.angle);
                mesh.castShadow = true; mesh.receiveShadow = true;
                this.extrudedGroup.add(mesh);
            } else if (obj.type === 'i-text' || obj.type === 'text' || obj.type === 'textbox') {
                // TRUE SILHOUETTE VECTOR EXTRUSION (V2)
                const textContent = obj.text || '';
                if (!textContent.trim()) continue;

                const s3d = this._getObj3DSettings(obj);
                const fillColor = typeof obj.fill === 'string' && obj.fill !== 'transparent' ? obj.fill : '#ffffff';
                const material = this.createMaterialPreset(fillColor);

                let pathData = "";
                try {
                    pathData = (typeof obj.toPathData === "function") ? obj.toPathData() : "";
                } catch(e) {}

                if (pathData) {
                    const svgPathMarkup = `<path d="${pathData}" />`;
                    const wrapper = `<svg xmlns="http://www.w3.org/2000/svg">${svgPathMarkup}</svg>`;
                    const svgLoader = new THREE.SVGLoader();
                    const parsed = svgLoader.parse(wrapper);

                    if (parsed && parsed.paths && parsed.paths.length > 0) {
                        const allShapes = [];
                        parsed.paths.forEach(p => allShapes.push(...THREE.SVGLoader.createShapes(p)));
                        
                        if (allShapes.length > 0) {
                            const extrudeGeom = new THREE.ExtrudeGeometry(allShapes, {
                                depth: s3d.depth,
                                bevelEnabled: s3d.bevelEnabled,
                                bevelSegments: s3d.bevelSegments,
                                steps: 1,
                                bevelSize: s3d.bevelSize,
                                bevelThickness: s3d.bevelSize
                            });

                            // Center the geometry so the origin is the middle of the text
                            extrudeGeom.center();

                            const mesh = new THREE.Mesh(extrudeGeom, material);
                            mesh.userData.name = obj.name || 'Text';
                            mesh.userData._key = this._keyForObj(obj, index);
                            
                            const center = obj.getCenterPoint();
                            mesh.position.set(center.x - this.targetWidth / 2, -(center.y - this.targetHeight / 2), zOffset);
                            mesh.rotation.z = THREE.MathUtils.degToRad(-obj.angle);
                            
                            // Fabric path data is already scaled, but Three.js Y is inverted
                            mesh.scale.set(1, -1, 1);
                            
                            mesh.castShadow = true;
                            mesh.receiveShadow = true;
                            this.extrudedGroup.add(mesh);
                            continue;
                        }
                    }
                }

                // FALLBACK: Sharp block if vectorization fails
                const padding = 24;
                const scale = 2; 
                const textWidth = Math.ceil(obj.width * obj.scaleX) + padding * 2;
                const textHeight = Math.ceil(obj.height * obj.scaleY) + padding * 2;
                const textCanvas = document.createElement('canvas');
                textCanvas.width = textWidth * scale; textCanvas.height = textHeight * scale;
                const tCtx = textCanvas.getContext('2d');
                tCtx.scale(scale, scale);
                const fontSize = Math.round(obj.fontSize * obj.scaleY);
                tCtx.font = `${obj.fontStyle || 'normal'} ${obj.fontWeight || 'normal'} ${fontSize}px "${obj.fontFamily || 'Arial'}"`;
                tCtx.textAlign = 'center'; tCtx.textBaseline = 'middle';
                tCtx.save();
                const hStretch = obj.scaleX / obj.scaleY;
                tCtx.setTransform(scale * hStretch, 0, 0, scale, (textWidth / 2) * scale, (textHeight / 2) * scale);
                tCtx.fillStyle = fillColor;
                tCtx.fillText(textContent, 0, 0);
                tCtx.restore();

                const textTex = new THREE.CanvasTexture(textCanvas);
                const frontMat = material.clone(); frontMat.map = textTex; frontMat.transparent = true; frontMat.alphaTest = 0.5;
                const invMat = new THREE.MeshBasicMaterial({ transparent: true, opacity: 0, depthWrite: false });
                const geometry = new THREE.BoxGeometry(textWidth, textHeight, s3d.depth);
                const mesh = new THREE.Mesh(geometry, [invMat, invMat, invMat, invMat, frontMat, invMat]);
                mesh.userData._key = this._keyForObj(obj, index);
                const center = obj.getCenterPoint();
                mesh.position.set(center.x - this.targetWidth / 2, -(center.y - this.targetHeight / 2), zOffset);
                mesh.rotation.z = THREE.MathUtils.degToRad(-obj.angle);
                this.extrudedGroup.add(mesh);
            } else {
                // ... (SVG logic)
                const svgMarkup = obj.toSVG();
                const wrapper = `<svg xmlns="http://www.w3.org/2000/svg" width="${this.targetWidth}" height="${this.targetHeight}" viewBox="0 0 ${this.targetWidth} ${this.targetHeight}">${svgMarkup}</svg>`;
                const svgLoader = new THREE.SVGLoader();
                let parsed;
                try { parsed = svgLoader.parse(wrapper); } catch (err) { continue; }
                const paths = parsed.paths;
                for (let p = 0; p < paths.length; p++) {
                    const path = paths[p];
                    const shapes = THREE.SVGLoader.createShapes(path);
                    const fillColor = path.color || new THREE.Color(0xffffff);
                    const material = this.createMaterialPreset(fillColor);
                    for (let s = 0; s < shapes.length; s++) {
                        const shape = shapes[s];
                        const s3d = this._getObj3DSettings(obj);
                        const extrudeGeom = new THREE.ExtrudeGeometry(shape, {
                            depth: s3d.depth, bevelEnabled: s3d.bevelEnabled,
                            bevelSegments: s3d.bevelSegments, steps: 1,
                            bevelSize: s3d.bevelSize, bevelThickness: s3d.bevelSize
                        });
                        const mesh = new THREE.Mesh(extrudeGeom, material);
                        mesh.userData.name = obj.name || 'Shape';
                        mesh.userData._key = this._keyForObj(obj, index) + '_' + p + '_' + s;
                        mesh.scale.set(1, -1, 1);
                        mesh.position.set(-this.targetWidth / 2, this.targetHeight / 2, zOffset);
                        mesh.castShadow = true; mesh.receiveShadow = true;
                        this.extrudedGroup.add(mesh);
                    }
                }
            }
        }

        // 5. Restore saved 3D transforms
        for (const child of this.extrudedGroup.children) {
            if (child.userData && child.userData._key) {
                const savedTr = this._saved3DTransforms[child.userData._key];
                if (savedTr) {
                    child.position.copy(savedTr.position);
                    child.rotation.copy(savedTr.rotation);
                    child.scale.copy(savedTr.scale);
                }
            }
        }

        // 6. RECOVER SELECTION: find the new mesh that matches the old key and re-select it
        if (selectedKey) {
            const newSelection = this.extrudedGroup.children.find(c => c.userData?._key === selectedKey);
            if (newSelection) {
                this.selectMesh3d(newSelection);
            }
        }
    }

    createMaterialPreset(color) {
        const presetSelect = document.getElementById('pgfx-3d-material');
        const preset = presetSelect ? presetSelect.value : 'polished_gold';
        
        switch (preset) {
            case 'polished_gold':
                return new THREE.MeshStandardMaterial({
                    color: new THREE.Color(0xd4af37), // gold hue
                    roughness: 0.15,
                    metalness: 0.9,
                    clearcoat: 1.0,
                    clearcoatRoughness: 0.05
                });
            case 'brushed_steel':
                return new THREE.MeshStandardMaterial({
                    color: new THREE.Color(0x8a95a5),
                    roughness: 0.35,
                    metalness: 0.85
                });
            case 'frosted_glass':
                return new THREE.MeshPhysicalMaterial({
                    color: color,
                    transparent: true,
                    opacity: 0.5,
                    roughness: 0.25,
                    metalness: 0.05,
                    transmission: 0.9,
                    ior: 1.45,
                    thickness: 8,
                    depthWrite: false
                });
            case 'obsidian':
                return new THREE.MeshStandardMaterial({
                    color: new THREE.Color(0x111116),
                    roughness: 0.08,
                    metalness: 0.1,
                    clearcoat: 1.0,
                    clearcoatRoughness: 0.05
                });
            case 'marble_white':
                return new THREE.MeshStandardMaterial({
                    color: new THREE.Color(0xf5f5fa),
                    roughness: 0.4,
                    metalness: 0.05
                });
            case 'glowing_neon':
                return new THREE.MeshStandardMaterial({
                    color: color,
                    emissive: color,
                    emissiveIntensity: 2.0,
                    roughness: 0.2,
                    metalness: 0.1
                });
            case 'matte_plastic':
                return new THREE.MeshStandardMaterial({
                    color: color,
                    roughness: 0.75,
                    metalness: 0.0
                });
            case 'default_color':
            default:
                return new THREE.MeshStandardMaterial({
                    color: color,
                    roughness: 0.4,
                    metalness: 0.2
                });
        }
    }

    selectMesh3d(mesh) {
        if (!mesh) return;
        if (this.selectedMesh3d === mesh) return;

        // Restore previous selection highlight
        this.deselectMesh3d();

        this.selectedMesh3d = mesh;

        // Save original emissive for restoration on deselect
        if (mesh.material && !mesh._origEmissive) {
            mesh._origEmissive = mesh.material.emissive ? mesh.material.emissive.clone() : new THREE.Color(0x000000);
        }
        // Highlight selected
        if (mesh.material) {
            mesh.material.emissive = new THREE.Color(0x06b6d4);
            mesh.material.emissiveIntensity = 0.25;
        } else {
            // Imported model group — highlight all child meshes
            mesh.traverse((child) => {
                if (child.isMesh && child.material) {
                    if (!child._origEmissive) {
                        child._origEmissive = child.material.emissive ? child.material.emissive.clone() : new THREE.Color(0x000000);
                    }
                    child.material.emissive = new THREE.Color(0x06b6d4);
                    child.material.emissiveIntensity = 0.25;
                }
            });
        }

        // Attach transform gizmo
        if (this.transformControls3d) {
            this.transformControls3d.attach(mesh);
        }

        this._updateSelectionUI();
        this.updateUIForSelection();
        this._update3DTransformButtons();
        this.refreshLayersPanel();
    }

    deselectMesh3d() {
        if (this.selectedMesh3d) {
            if (this.selectedMesh3d.material) {
                if (this.selectedMesh3d.material.emissive) {
                    this.selectedMesh3d.material.emissive.copy(this.selectedMesh3d._origEmissive || new THREE.Color(0x000000));
                }
                this.selectedMesh3d.material.emissiveIntensity = 0;
            } else {
                this.selectedMesh3d.traverse((child) => {
                    if (child.isMesh && child.material) {
                        if (child.material.emissive) {
                            child.material.emissive.copy(child._origEmissive || new THREE.Color(0x000000));
                        }
                        child.material.emissiveIntensity = 0;
                    }
                });
            }
            this.selectedMesh3d = null;
        }
        if (this.transformControls3d) this.transformControls3d.detach();
        this._updateSelectionUI();
        this.updateUIForSelection();
        this.refreshLayersPanel();
    }

    setTransformMode(mode) {
        this.transformMode = mode;
        if (this.transformControls3d) {
            this.transformControls3d.setMode(mode);
        }
        this._update3DTransformButtons();
    }

    _update3DTransformButtons() {
        const btnT = document.getElementById('pgfx-3d-mode-translate');
        const btnR = document.getElementById('pgfx-3d-mode-rotate');
        const btnS = document.getElementById('pgfx-3d-mode-scale');
        if (btnT) btnT.classList.toggle('pgfx-btn-primary', this.transformMode === 'translate');
        if (btnR) btnR.classList.toggle('pgfx-btn-primary', this.transformMode === 'rotate');
        if (btnS) btnS.classList.toggle('pgfx-btn-primary', this.transformMode === 'scale');
    }

    _updateSelectionUI() {
        const panel = document.getElementById('pgfx-properties-panel');
        if (!panel) return;
        const zRow = document.getElementById('pgfx-prop-z-row');

        if (this.mode3D && this.selectedMesh3d) {
            // 3D object selected
            panel.style.display = 'block';
            if (zRow) zRow.style.display = 'flex';
            const p = this.selectedMesh3d.position;
            const r = this.selectedMesh3d.rotation;
            const s = this.selectedMesh3d.scale;
            this._setPropInput('pgfx-prop-x', p.x);
            this._setPropInput('pgfx-prop-y', p.y);
            this._setPropInput('pgfx-prop-z', p.z);
            this._setPropInput('pgfx-prop-rotation', THREE.MathUtils.radToDeg(r.z).toFixed(1));
            this._setPropInput('pgfx-prop-scale', s.x.toFixed(2));
        } else if (!this.mode3D) {
            const active = this.canvas ? this.canvas.getActiveObject() : null;
            if (active) {
                panel.style.display = 'block';
                if (zRow) zRow.style.display = 'none';
                const bounds = active.getBoundingRect();
                this._setPropInput('pgfx-prop-x', Math.round(bounds.left));
                this._setPropInput('pgfx-prop-y', Math.round(bounds.top));
                this._setPropInput('pgfx-prop-rotation', Math.round(active.angle || 0));
                this._setPropInput('pgfx-prop-scale', parseFloat(active.scaleX || 1).toFixed(2));
            } else {
                panel.style.display = 'none';
            }
        } else {
            panel.style.display = 'none';
        }
    }

    _setPropInput(id, value) {
        const el = document.getElementById(id);
        if (el) el.value = value;
    }

    _applyPropertyTo3D() {
        if (!this.selectedMesh3d) return;
        const x = parseFloat(document.getElementById('pgfx-prop-x')?.value) || 0;
        const y = parseFloat(document.getElementById('pgfx-prop-y')?.value) || 0;
        const z = parseFloat(document.getElementById('pgfx-prop-z')?.value) || 0;
        const rot = parseFloat(document.getElementById('pgfx-prop-rotation')?.value) || 0;
        const scale = parseFloat(document.getElementById('pgfx-prop-scale')?.value) || 1;
        this.selectedMesh3d.position.set(x, y, z);
        this.selectedMesh3d.rotation.set(0, 0, THREE.MathUtils.degToRad(rot));
        this.selectedMesh3d.scale.set(scale, scale, scale);
        this._updateSelectionUI();
    }

    _applyPropertyTo2D() {
        if (!this.canvas) return;
        const active = this.canvas.getActiveObject();
        if (!active) return;
        const x = parseFloat(document.getElementById('pgfx-prop-x')?.value) || 0;
        const y = parseFloat(document.getElementById('pgfx-prop-y')?.value) || 0;
        const rot = parseFloat(document.getElementById('pgfx-prop-rotation')?.value) || 0;
        const scale = parseFloat(document.getElementById('pgfx-prop-scale')?.value) || 1;
        active.set({
            left: x,
            top: y,
            angle: rot,
            scaleX: scale,
            scaleY: scale,
        });
        active.setCoords();
        this.canvas.requestRenderAll();
        this._updateSelectionUI();
    }

    _getObj3DSettings(obj) {
        if (!obj) return { depth: 20, bevelEnabled: true, bevelSize: 1.5, bevelSegments: 3 };
        if (!obj.userData) obj.userData = {};
        if (!obj.userData.pgfx_3d) {
            obj.userData.pgfx_3d = {
                depth: parseFloat(document.getElementById('pgfx-3d-depth')?.value) || 20,
                bevelEnabled: document.getElementById('pgfx-3d-bevel-enabled')?.checked ?? true,
                bevelSize: parseFloat(document.getElementById('pgfx-3d-bevel-size')?.value) || 1.5,
                bevelSegments: parseInt(document.getElementById('pgfx-3d-bevel-segments')?.value) || 3,
            };
        }
        return obj.userData.pgfx_3d;
    }

    _applyObj3DSettings() {
        let target = null;
        if (this.canvas) target = this.canvas.getActiveObject();
        if (!target) return;
        
        if (!target.userData) target.userData = {};
        target.userData.pgfx_3d = {
            depth: parseFloat(document.getElementById('pgfx-3d-depth')?.value) || 20,
            bevelEnabled: document.getElementById('pgfx-3d-bevel-enabled')?.checked ?? true,
            bevelSize: parseFloat(document.getElementById('pgfx-3d-bevel-size')?.value) || 1.5,
            bevelSegments: parseInt(document.getElementById('pgfx-3d-bevel-segments')?.value) || 3,
        };
        
        if (this._syncTimeout) clearTimeout(this._syncTimeout);
        this._syncTimeout = setTimeout(() => { this.sync2DTo3D(); }, 16);
    }

    _update3DStroke(mesh) {
        if (!mesh || !window.THREE) return;
        // Remove old stroke overlay
        if (mesh.userData._strokeLines) {
            mesh.remove(mesh.userData._strokeLines);
            if (mesh.userData._strokeLines.geometry) mesh.userData._strokeLines.geometry.dispose();
            if (mesh.userData._strokeLines.material) mesh.userData._strokeLines.material.dispose();
            mesh.userData._strokeLines = null;
        }
        const strokeWidth = parseInt(document.getElementById('pgfx-stroke-width')?.value) || 0;
        const strokeColor = document.getElementById('pgfx-stroke-picker')?.value;
        if (strokeWidth > 0 && strokeColor) {
            const edges = new THREE.EdgesGeometry(mesh.geometry, 30);
            const lineMat = new THREE.LineBasicMaterial({ color: strokeColor });
            const lines = new THREE.LineSegments(edges, lineMat);
            lines.position.z = 0.5;
            mesh.add(lines);
            mesh.userData._strokeLines = lines;
        }
    }

    _update3DShadow(mesh) {
        if (!mesh || !window.THREE) return;
        // Remove old shadow clone
        if (mesh.userData._shadowClone) {
            mesh.remove(mesh.userData._shadowClone);
            if (mesh.userData._shadowClone.geometry) mesh.userData._shadowClone.geometry.dispose();
            if (mesh.userData._shadowClone.material) mesh.userData._shadowClone.material.dispose();
            mesh.userData._shadowClone = null;
        }
        const enabled = document.getElementById('pgfx-shadow-enabled')?.checked;
        if (!enabled) return;
        const color = document.getElementById('pgfx-shadow-color')?.value || '#000000';
        const offsetX = parseInt(document.getElementById('pgfx-shadow-offset-x')?.value) || 5;
        const offsetY = parseInt(document.getElementById('pgfx-shadow-offset-y')?.value) || 5;
        const blur = parseInt(document.getElementById('pgfx-shadow-blur')?.value) || 10;
        const shadowMat = new THREE.MeshBasicMaterial({
            color: color,
            transparent: true,
            opacity: Math.max(0.1, Math.min(0.5, blur / 100)),
            depthWrite: false,
        });
        const shadowClone = new THREE.Mesh(mesh.geometry.clone(), shadowMat);
        shadowClone.position.set(offsetX * 0.5, -offsetY * 0.5, -5);
        mesh.add(shadowClone);
        mesh.userData._shadowClone = shadowClone;
    }

    fit3DView() {
        if (!this.camera3d || !this.extrudedGroup || !this.controls3d) return;

        const box = new THREE.Box3();

        // Include the extruded objects
        if (this.extrudedGroup.children.length > 0) {
            box.expandByObject(this.extrudedGroup);
        }

        // Include the canvas safe area plane (the "Page")
        if (this.canvasPlane3d) {
            box.expandByObject(this.canvasPlane3d);
        }

        if (box.isEmpty()) return;

        const size = new THREE.Vector3();
        box.getSize(size);
        const center = new THREE.Vector3();
        box.getCenter(center);

        this.controls3d.target.copy(center);

        const maxDim = Math.max(size.x, size.y, size.z);
        const fov = this.camera3d.fov * (Math.PI / 180);
        let cameraZ = Math.abs(maxDim / 2 / Math.tan(fov / 2));

        cameraZ *= 1.35; // margin
        cameraZ = Math.max(cameraZ, 200); // slightly more generous lower bound

        this.camera3d.position.set(center.x, center.y, center.z + cameraZ);
        this.camera3d.lookAt(center);
        this.controls3d.update();
    }

    cleanUp3D() {
        this.deselectMesh3d();
        if (this.transformControls3d) {
            this.transformControls3d.dispose();
            this.transformControls3d = null;
        }
        if (this.resizeObserver3d && this.renderer3d) {
            const container = document.getElementById('pgfx-3d-canvas-container');
            if (container) this.resizeObserver3d.unobserve(container);
            this.resizeObserver3d = null;
        }
        if (this.renderer3d) {
            this.renderer3d.dispose();
            this.renderer3d.forceContextLoss();
            const canvasEl = this.renderer3d.domElement;
            if (canvasEl) canvasEl.remove();
            this.renderer3d = null;
        }
        if (this.scene3d) {
            this.scene3d.traverse((object) => {
                if (object.geometry) object.geometry.dispose();
                if (object.material) {
                    if (Array.isArray(object.material)) {
                        object.material.forEach(m => m.dispose());
                    } else {
                        object.material.dispose();
                    }
                }
            });
            this.scene3d = null;
        }
        this.camera3d = null;
        this.controls3d = null;
        this.extrudedGroup = null;
        this.modelsGroup = null;
        this.scene3d = null;
    }

    _bufferToBase64(buffer) {
        const bytes = new Uint8Array(buffer);
        let binary = '';
        for (let i = 0; i < bytes.length; i++) {
            binary += String.fromCharCode(bytes[i]);
        }
        return btoa(binary);
    }

    _base64ToBuffer(base64) {
        const binary = atob(base64);
        const bytes = new Uint8Array(binary.length);
        for (let i = 0; i < binary.length; i++) {
            bytes[i] = binary.charCodeAt(i);
        }
        return bytes.buffer;
    }

    async _loadModelIntoScene(entry) {
        if (!window.THREE || !this.modelsGroup) return;
        const buffer = this._base64ToBuffer(entry.data);
        const blob = new Blob([buffer]);
        const url = URL.createObjectURL(blob);

        try {
            let modelGroup = new THREE.Group();
            const ext = entry.format || 'glb';

            if (ext === 'glb' || ext === 'gltf') {
                const loader = new THREE.GLTFLoader();
                const gltf = await new Promise((resolve, reject) => {
                    loader.load(url, resolve, undefined, reject);
                });
                const scene = gltf.scene || gltf;
                scene.traverse((child) => {
                    if (child.isMesh) {
                        child.castShadow = true;
                        child.receiveShadow = true;
                        if (!child.geometry.attributes.normal) {
                            child.geometry.computeVertexNormals();
                        }
                    }
                });
                modelGroup = scene;
            } else if (ext === 'obj') {
                const loader = new THREE.OBJLoader();
                const obj = await new Promise((resolve, reject) => {
                    loader.load(url, resolve, undefined, reject);
                });
                obj.traverse((child) => {
                    if (child.isMesh) {
                        child.castShadow = true;
                        child.receiveShadow = true;
                        child.geometry.computeVertexNormals();
                    }
                });
                modelGroup = obj;
            } else if (ext === 'stl') {
                const loader = new THREE.STLLoader();
                const geometry = await new Promise((resolve, reject) => {
                    loader.load(url, resolve, undefined, reject);
                });
                const material = new THREE.MeshStandardMaterial({
                    color: new THREE.Color(0x888888),
                    roughness: 0.5,
                    metalness: 0.3,
                });
                const mesh = new THREE.Mesh(geometry, material);
                mesh.castShadow = true;
                mesh.receiveShadow = true;
                mesh.geometry.computeVertexNormals();
                modelGroup.add(mesh);
            }

            modelGroup.userData._importedModelId = entry.id;
            entry.group = modelGroup;
            this.modelsGroup.add(modelGroup);

            // Center and scale to fit
            const box = new THREE.Box3().setFromObject(modelGroup);
            if (!box.isEmpty()) {
                const size = new THREE.Vector3();
                box.getSize(size);
                const center = new THREE.Vector3();
                box.getCenter(center);
                const maxDim = Math.max(size.x, size.y, size.z);
                const targetSize = 200;
                if (maxDim > 0) {
                    const scale = targetSize / maxDim;
                    modelGroup.scale.set(scale, scale, scale);
                }
                modelGroup.position.sub(center.clone().multiply(modelGroup.scale));
                modelGroup.position.z = -50;
            }

            URL.revokeObjectURL(url);
        } catch (err) {
            URL.revokeObjectURL(url);
            console.error('[PGFX] Failed to load model:', entry.name, err);
            throw err;
        }
    }

    _disposeModelGroup(group) {
        if (!group) return;
        group.traverse((child) => {
            if (child.geometry) child.geometry.dispose();
            if (child.material) {
                if (Array.isArray(child.material)) {
                    child.material.forEach(m => m.dispose());
                } else {
                    child.material.dispose();
                }
            }
        });
    }

    _collect3DSettings() {
        return {
            mode3D: !!this.mode3D,
            transforms: this._saved3DTransforms || {},
            depth: parseFloat(document.getElementById('pgfx-3d-depth').value) || 20,
            bevel_enabled: document.getElementById('pgfx-3d-bevel-enabled').checked,
            bevel_size: parseFloat(document.getElementById('pgfx-3d-bevel-size').value) || 1.5,
            bevel_segments: parseInt(document.getElementById('pgfx-3d-bevel-segments').value) || 3,
            material: document.getElementById('pgfx-3d-material').value || 'matte_plastic',
            light_rotation: parseFloat(document.getElementById('pgfx-3d-light-rot').value) || 45,
            cast_shadows: document.getElementById('pgfx-3d-shadows').checked,
            show_grid_3d: document.getElementById('pgfx-3d-show-grid')?.checked ?? true,
        };
    }

    _apply3DSettings(settings) {
        if (!settings) return;
        
        // Restore transforms into the temporary persistence map
        if (settings.transforms) {
            this._saved3DTransforms = Object.assign({}, settings.transforms);
        }

        const setVal = (id, val) => {
            const el = document.getElementById(id);
            if (el) el.value = val;
        };
        const setChecked = (id, val) => {
            const el = document.getElementById(id);
            if (el) el.checked = !!val;
        };
        
        // Store mode for open() to use
        this._shouldRestore3D = !!settings.mode3D;

        setVal('pgfx-3d-depth', settings.depth ?? 20);
        const dv = document.getElementById('pgfx-3d-depth-val');
        if (dv) dv.textContent = settings.depth ?? 20;
        setChecked('pgfx-3d-bevel-enabled', settings.bevel_enabled ?? true);
        const bevSettings = document.getElementById('pgfx-3d-bevel-settings');
        if (bevSettings) {
            bevSettings.style.display = (settings.bevel_enabled !== false) ? 'flex' : 'none';
        }
        setVal('pgfx-3d-bevel-size', settings.bevel_size ?? 1.5);
        const bsv = document.getElementById('pgfx-3d-bevel-size-val');
        if (bsv) bsv.textContent = settings.bevel_size ?? 1.5;
        setVal('pgfx-3d-bevel-segments', settings.bevel_segments ?? 3);
        const bsgv = document.getElementById('pgfx-3d-bevel-segments-val');
        if (bsgv) bsgv.textContent = settings.bevel_segments ?? 3;
        setVal('pgfx-3d-material', settings.material || 'matte_plastic');
        setVal('pgfx-3d-light-rot', settings.light_rotation ?? 45);
        const lrv = document.getElementById('pgfx-3d-light-rot-val');
        if (lrv) lrv.textContent = (settings.light_rotation ?? 45) + '°';
        setChecked('pgfx-3d-shadows', settings.cast_shadows ?? true);
        setChecked('pgfx-3d-show-grid', settings.show_grid_3d ?? true);
    }

    initDOM() {
        let overlay = document.getElementById('pgfx-studio-overlay');
        if (!overlay) {
            overlay = document.createElement('div');
            overlay.id = 'pgfx-studio-overlay';
            overlay.innerHTML = `
                <div class="pgfx-studio-container">
                    <div id="pgfx-studio-loading">
                        <div class="pgfx-spinner"></div>
                        <div id="pgfx-loading-status" style="font-size: 14px; letter-spacing: 1px; text-transform: uppercase; text-align: center;">Initializing Studio...</div>
                    </div>
                    <div class="pgfx-studio-header">
                        <div class="pgfx-studio-title">
                            <span style="font-size: 24px;">🎨</span> PGFX Logo Designer Studio
                            <div class="pgfx-studio-tabs" style="margin-left: 24px; display: inline-flex; gap: 8px;">
                                <button id="pgfx-tab-2d" class="pgfx-btn pgfx-btn-primary" style="height: 28px; padding: 2px 10px; font-size: 11px; text-transform: uppercase;">🎨 2D Design</button>
                                <button id="pgfx-tab-3d" class="pgfx-btn" style="height: 28px; padding: 2px 10px; font-size: 11px; text-transform: uppercase;">🧊 3D Viewport</button>
                            </div>
                        </div>
                        <div class="pgfx-row">
                            <button id="pgfx-cancel-btn" class="pgfx-btn">Cancel</button>
                            <div class="pgfx-toolbar-separator"></div>
                            <button id="pgfx-undo-btn" class="pgfx-btn" title="Undo (Ctrl+Z)">↶ Undo</button>
                            <button id="pgfx-redo-btn" class="pgfx-btn" title="Redo (Ctrl+Y)">↷ Redo</button>
                            <div class="pgfx-toolbar-separator"></div>
                            <button id="pgfx-fit-btn" class="pgfx-btn" title="Center and fit the canvas to the current window.">🔍 Fit View</button>
                            <button id="pgfx-export-svg-btn" class="pgfx-btn" title="Download the current design as a clean SVG file.">📋 SVG</button>
                            <button id="pgfx-export-3d-btn" class="pgfx-btn" title="Export the 3D scene as a standard .glb file for Blender, Unity, etc.">🧊 3D (.glb)</button>
                            <button id="pgfx-save-btn" class="pgfx-btn pgfx-btn-primary" title="Apply the design to the node and close the window.">💾 Save State & Apply</button>
                        </div>
                    </div>
                    <div class="pgfx-studio-body">
                        <div class="pgfx-studio-sidebar">

                            <!-- CANVAS SETTINGS -->
                            <div class="pgfx-input-group">
                                <label class="pgfx-label">Canvas Properties</label>
                                <div class="pgfx-row" style="justify-content: space-between;">
                                    <span style="font-size: 11px; color:#aaa;">Show Grid</span>
                                    <input type="checkbox" id="pgfx-show-grid" checked style="cursor: pointer;">
                                </div>
                                <div class="pgfx-row">
                                    <span style="font-size: 11px; color:#aaa; width: 60px;">Grid Size</span>
                                    <input type="range" id="pgfx-grid-size" min="10" max="200" value="50" style="flex: 1;">
                                    <span id="pgfx-grid-size-val" style="font-size: 10px; color:#71717a; font-family: monospace; width: 25px; text-align: right;">50</span>
                                </div>
                                <div class="pgfx-row" style="justify-content: space-between;">
                                    <span style="font-size: 11px; color:#aaa;">Snap to Grid</span>
                                    <input type="checkbox" id="pgfx-snap-grid" style="cursor: pointer;">
                                </div>
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

                            <!-- 3D SIDEBAR CONTROLS (Only visible in 3D mode) -->
                            <div id="pgfx-3d-sidebar-controls" style="display: none; flex-direction: column; gap: 12px; width: 100%;">
                                <div class="pgfx-input-group" style="border-color: rgba(6, 182, 212, 0.3);">
                                    <label class="pgfx-label" style="color: #06b6d4;">3D Extrusion & Bevel</label>
                                    <div class="pgfx-row">
                                        <span style="font-size: 11px; color:#aaa; width: 60px;">Depth</span>
                                        <input type="range" id="pgfx-3d-depth" min="1" max="150" value="20" style="flex: 1;">
                                        <span id="pgfx-3d-depth-val" style="font-size: 10px; color:#71717a; font-family: monospace; width: 25px; text-align: right;">20</span>
                                    </div>
                                    <div class="pgfx-row" style="justify-content: space-between;">
                                        <span style="font-size: 11px; color:#aaa;">Bevel Enabled</span>
                                        <input type="checkbox" id="pgfx-3d-bevel-enabled" checked style="cursor: pointer;">
                                    </div>
                                    <div id="pgfx-3d-bevel-settings" style="display: flex; flex-direction: column; gap: 8px;">
                                        <div class="pgfx-row">
                                            <span style="font-size: 11px; color:#aaa; width: 60px;">B-Size</span>
                                            <input type="range" id="pgfx-3d-bevel-size" min="0" max="15" step="0.5" value="1.5" style="flex: 1;">
                                            <span id="pgfx-3d-bevel-size-val" style="font-size: 10px; color:#71717a; font-family: monospace; width: 25px; text-align: right;">1.5</span>
                                        </div>
                                        <div class="pgfx-row">
                                            <span style="font-size: 11px; color:#aaa; width: 60px;">B-Segs</span>
                                            <input type="range" id="pgfx-3d-bevel-segments" min="1" max="8" value="3" style="flex: 1;">
                                            <span id="pgfx-3d-bevel-segments-val" style="font-size: 10px; color:#71717a; font-family: monospace; width: 25px; text-align: right;">3</span>
                                        </div>
                                    </div>
                                    <div class="pgfx-row">
                                        <span style="font-size: 11px; color:#aaa; width: 60px;">Material</span>
                                        <select id="pgfx-3d-material" class="pgfx-select" style="flex: 1;">
                                            <option value="polished_gold">Polished Gold</option>
                                            <option value="brushed_steel">Brushed Steel</option>
                                            <option value="frosted_glass">Frosted Glass</option>
                                            <option value="obsidian">Obsidian Black</option>
                                            <option value="marble_white">White Marble</option>
                                            <option value="glowing_neon">Glowing Neon</option>
                                            <option value="matte_plastic">Matte Plastic</option>
                                            <option value="default_color">Default Color</option>
                                        </select>
                                    </div>
                                    <div class="pgfx-row">
                                        <span style="font-size: 11px; color:#aaa; width: 60px;">Light Rot</span>
                                        <input type="range" id="pgfx-3d-light-rot" min="0" max="360" value="45" style="flex: 1;">
                                        <span id="pgfx-3d-light-rot-val" style="font-size: 10px; color:#71717a; font-family: monospace; width: 25px; text-align: right;">45°</span>
                                    </div>
                                    <div class="pgfx-row" style="justify-content: space-between;">
                                        <span style="font-size: 11px; color:#aaa;">Cast Shadows</span>
                                        <input type="checkbox" id="pgfx-3d-shadows" checked style="cursor: pointer;">
                                    </div>
                                    <div class="pgfx-row" style="justify-content: space-between;">
                                        <span style="font-size: 11px; color:#aaa;">Show Grid</span>
                                        <input type="checkbox" id="pgfx-3d-show-grid" checked style="cursor: pointer;">
                                    </div>
                                    <div class="pgfx-row" style="margin-top: 4px;">
                                        <button id="pgfx-3d-reset-cam" class="pgfx-btn pgfx-btn-primary" style="flex: 1; font-size: 10px;" title="Reset 3D camera orientation and center the model (Shortcut: R)">Reset Camera (R)</button>
                                    </div>
                                    <div class="pgfx-row" style="margin-top: 4px;">
                                        <button id="pgfx-import-3d-btn" class="pgfx-btn" style="flex: 1; font-size: 10px;" title="Import a 3D model file (.glb, .gltf, .obj, .stl) into the 3D viewport">🎲 Import 3D Model</button>
                                        <button id="pgfx-clear-3d-models-btn" class="pgfx-btn" style="font-size: 10px; padding: 4px 8px;" title="Remove all imported 3D models from the scene">🗑️</button>
                                    </div>
                                    <input type="file" id="pgfx-import-3d-input" class="hidden-file-input" accept=".glb,.gltf,.obj,.stl">
                                </div>


                            </div>

                            <div id="pgfx-2d-sidebar-controls" style="display: flex; flex-direction: column; gap: 12px; width: 100%;">
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
                                    <span id="pgfx-font-size-val" style="font-size: 10px; color:#71717a; font-family: monospace; width: 38px; text-align: right;">100</span>
                                </div>
                                <div class="pgfx-row">
                                    <span style="font-size: 11px; color:#aaa; width: 60px;">Letter</span>       
                                    <input type="range" id="pgfx-letter-spacing" min="-100" max="1000" value="0" style="flex: 1;">
                                    <span id="pgfx-letter-spacing-val" style="font-size: 10px; color:#71717a; font-family: monospace; width: 38px; text-align: right;">0</span>
                                </div>
                                <div class="pgfx-row">
                                    <span style="font-size: 11px; color:#aaa; width: 60px;">Line</span>
                                    <input type="range" id="pgfx-line-spacing" min="0.1" max="5" step="0.05" value="1.16" style="flex: 1;">
                                    <span id="pgfx-line-spacing-val" style="font-size: 10px; color:#71717a; font-family: monospace; width: 38px; text-align: right;">1.16</span>
                                </div>
                            </div>

                            <!-- STYLING & STROKE -->
                            <div class="pgfx-input-group">
                                <label class="pgfx-label">Fill & Stroke</label>
                                <div class="pgfx-row">
                                    <span style="font-size: 11px; color:#aaa; width: 60px;">Fill Type</span>
                                    <select id="pgfx-fill-type" class="pgfx-select" style="flex: 1;">
                                        <option value="solid">Solid Color</option>
                                        <option value="linear">Linear Gradient</option>
                                        <option value="radial">Radial Gradient</option>
                                    </select>
                                </div>
                                
                                <!-- SOLID FILL -->
                                <div id="pgfx-fill-solid-row" class="pgfx-row" style="justify-content: space-between;">
                                    <span style="font-size: 11px; color:#aaa;">Fill Color</span>
                                    <input type="color" id="pgfx-color-picker" value="#ffffff" style="cursor: pointer; background: none; border: none;">
                                </div>

                                <!-- GRADIENT FILL (Hidden by default) -->
                                <div id="pgfx-fill-gradient-controls" style="display: none; flex-direction: column; gap: 8px;">
                                    <div class="pgfx-row" style="justify-content: space-between;">
                                        <span style="font-size: 11px; color:#aaa;">Start Color</span>
                                        <input type="color" id="pgfx-gradient-start" value="#ffffff" style="cursor: pointer; background: none; border: none;">
                                    </div>
                                    <div class="pgfx-row" style="justify-content: space-between;">
                                        <span style="font-size: 11px; color:#aaa;">End Color</span>
                                        <input type="color" id="pgfx-gradient-end" value="#06b6d4" style="cursor: pointer; background: none; border: none;">
                                    </div>
                                    <div class="pgfx-row">
                                        <span style="font-size: 11px; color:#aaa; width: 60px;">Angle</span>
                                        <input type="range" id="pgfx-gradient-angle" min="0" max="360" value="0" style="flex: 1;">
                                        <span id="pgfx-gradient-angle-val" style="font-size: 10px; color:#71717a; font-family: monospace; width: 38px; text-align: right;">0°</span>
                                    </div>
                                </div>

                                <div class="pgfx-row" style="justify-content: space-between;">
                                    <span style="font-size: 11px; color:#aaa;">Stroke Color</span>
                                    <input type="color" id="pgfx-stroke-picker" value="#000000" style="cursor: pointer; background: none; border: none;">
                                </div>
                                <div class="pgfx-row">
                                    <span style="font-size: 11px; color:#aaa; width: 60px;">Stroke</span>       
                                    <input type="range" id="pgfx-stroke-width" min="0" max="100" value="0" style="flex: 1;">
                                    <span id="pgfx-stroke-width-val" style="font-size: 10px; color:#71717a; font-family: monospace; width: 38px; text-align: right;">0</span>
                                </div>
                            </div>

                            <!-- EFFECTS & DEPTH -->
                            <div class="pgfx-input-group">
                                <label class="pgfx-label">Effects & Depth</label>
                                <div class="pgfx-row" style="justify-content: space-between;">
                                    <span style="font-size: 11px; color:#aaa;">Drop Shadow</span>
                                    <input type="checkbox" id="pgfx-shadow-enabled" style="cursor: pointer;">
                                </div>
                                <div id="pgfx-shadow-controls" style="display: none; flex-direction: column; gap: 8px;">
                                    <div class="pgfx-row" style="justify-content: space-between;">
                                        <span style="font-size: 11px; color:#aaa;">Color</span>
                                        <input type="color" id="pgfx-shadow-color" value="#000000" style="cursor: pointer; background: none; border: none;">
                                    </div>
                                    <div class="pgfx-row">
                                        <span style="font-size: 11px; color:#aaa; width: 60px;">Blur</span>
                                        <input type="range" id="pgfx-shadow-blur" min="0" max="100" value="10" style="flex: 1;">
                                        <span id="pgfx-shadow-blur-val" style="font-size: 10px; color:#71717a; font-family: monospace; width: 38px; text-align: right;">10</span>
                                    </div>
                                    <div class="pgfx-row">
                                        <span style="font-size: 11px; color:#aaa; width: 60px;">Offset X</span>
                                        <input type="range" id="pgfx-shadow-offset-x" min="-100" max="100" value="5" style="flex: 1;">
                                        <span id="pgfx-shadow-offset-x-val" style="font-size: 10px; color:#71717a; font-family: monospace; width: 38px; text-align: right;">5</span>
                                    </div>
                                    <div class="pgfx-row">
                                        <span style="font-size: 11px; color:#aaa; width: 60px;">Offset Y</span>
                                        <input type="range" id="pgfx-shadow-offset-y" min="-100" max="100" value="5" style="flex: 1;">
                                        <span id="pgfx-shadow-offset-y-val" style="font-size: 10px; color:#71717a; font-family: monospace; width: 38px; text-align: right;">5</span>
                                    </div>
                                </div>
                            </div>

                            <!-- TRANSFORMS -->
                            <div class="pgfx-input-group">
                                <label class="pgfx-label">Transforms</label>
                                <div class="pgfx-row">
                                    <span style="font-size: 11px; color:#aaa; width: 60px;">Rotate</span>       
                                    <input type="range" id="pgfx-rotation" min="-180" max="180" value="0" style="flex: 1;">
                                    <span id="pgfx-rotation-val" style="font-size: 10px; color:#71717a; font-family: monospace; width: 38px; text-align: right;">0°</span>
                                </div>
                                <div class="pgfx-row">
                                    <span style="font-size: 11px; color:#aaa; width: 60px;">Skew X</span>       
                                    <input type="range" id="pgfx-skew-x" min="-100" max="100" value="0" style="flex: 1;">
                                    <span id="pgfx-skew-x-val" style="font-size: 10px; color:#71717a; font-family: monospace; width: 38px; text-align: right;">0</span>
                                </div>
                                <div class="pgfx-row">
                                    <span style="font-size: 11px; color:#aaa; width: 60px;">Opacity</span>      
                                    <input type="range" id="pgfx-opacity" min="0" max="1" step="0.05" value="1" style="flex: 1;">
                                    <span id="pgfx-opacity-val" style="font-size: 10px; color:#71717a; font-family: monospace; width: 38px; text-align: right;">100%</span>
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
                                    â€¢ <span style="color:#06b6d4;">DEL / BACKSPACE</span>: Delete Selected<br>
                                    â€¢ <span style="color:#06b6d4;">Arrow Keys</span>: Nudge Object (1px)<br>
                                    â€¢ <span style="color:#06b6d4;">SHIFT + Arrow Keys</span>: Nudge Object (10px)<br><br>

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
                                    <b style="color:#e4e4e7;">environment_1_intensity / environment_2_intensity / environment_3_intensity</b><br>
                                    Per-slot intensity for each environment effect. 0.0 = disabled. 0.5 = subtle/sparse. 1.0 = normal. 1.5 = heavy. 2.0 = dramatic/intense.<br><br>
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
                                <div id="pgfx-2d-canvas-container" style="display: block; width: 100%; height: 100%; position: relative;">
                                    <canvas id="pgfx-design-canvas"></canvas>
                                </div>
                                <div id="pgfx-3d-canvas-container" style="display: none; width: 100%; height: 100%; position: relative; overflow: hidden; background: #0a0a0b;">
                                </div>
                            </div>
                        </div>
                        <div class="pgfx-studio-right-sidebar" style="margin-top: 45px;">
                            <!-- LAYERS PANEL (works for both 2D and 3D) -->
                            <div class="pgfx-input-group" style="flex: 1; display: flex; flex-direction: column;">
                                <label class="pgfx-label">
                                    Layers
                                    <span id="pgfx-layer-count" style="font-weight: normal; opacity: 0.6;">0</span>
                                </label>
                                <div id="pgfx-layers-list" class="pgfx-layers-list" style="flex: 1; overflow-y: auto; margin-top: 8px;">
                                    <!-- Populated dynamically -->
                                </div>
                            </div>

                            <!-- 3D TRANSFORM TOOLS (shown only in 3D mode) -->
                            <div id="pgfx-3d-tools-group" class="pgfx-input-group" style="display: none; border-color: rgba(6, 182, 212, 0.3); padding: 10px 8px;">
                                <label class="pgfx-label" style="color: #06b6d4; font-size: 9px;">3D Transform</label>
                                <div style="display: flex; flex-direction: column; gap: 4px;">
                                    <button id="pgfx-3d-mode-translate" class="pgfx-btn pgfx-btn-primary" style="width: 100%; font-size: 10px; padding: 6px 2px;" title="Move mode (W)">↕ Translate</button>
                                    <button id="pgfx-3d-mode-rotate" class="pgfx-btn" style="width: 100%; font-size: 10px; padding: 6px 2px;" title="Rotate mode (E)">↻ Rotate</button>
                                    <button id="pgfx-3d-mode-scale" class="pgfx-btn" style="width: 100%; font-size: 10px; padding: 6px 2px;" title="Scale mode">⇔ Scale</button>
                                </div>
                                <div style="font-size: 8px; color: #71717a; margin-top: 4px; text-align: center; line-height: 1.2;">Click object to select.<br>W / E to switch modes.</div>
                            </div>

                            <!-- OBJECT PROPERTIES (editable for both 2D and 3D) -->
                            <div id="pgfx-properties-panel" class="pgfx-input-group" style="display: none; padding: 10px 8px;">
                                <label class="pgfx-label" style="font-size: 9px;">Object Properties</label>
                                <div class="pgfx-row" style="justify-content: space-between; align-items: center; gap: 4px;">
                                    <span style="font-size: 9px; color:#aaa;">X</span>
                                    <input id="pgfx-prop-x" type="number" step="1" style="width: 50px; font-size: 9px; background: #1a1a2e; color: #d4d4d8; border: 1px solid #333; border-radius: 4px; padding: 2px 3px;">
                                </div>
                                <div class="pgfx-row" style="justify-content: space-between; align-items: center; gap: 4px;">
                                    <span style="font-size: 9px; color:#aaa;">Y</span>
                                    <input id="pgfx-prop-y" type="number" step="1" style="width: 50px; font-size: 9px; background: #1a1a2e; color: #d4d4d8; border: 1px solid #333; border-radius: 4px; padding: 2px 3px;">
                                </div>
                                <div id="pgfx-prop-z-row" class="pgfx-row" style="justify-content: space-between; align-items: center; gap: 4px; display: none;">
                                    <span style="font-size: 9px; color:#06b6d4;">Z</span>
                                    <input id="pgfx-prop-z" type="number" step="1" style="width: 50px; font-size: 9px; background: #1a1a2e; color: #d4d4d8; border: 1px solid #333; border-radius: 4px; padding: 2px 3px;">
                                </div>
                                <div class="pgfx-row" style="justify-content: space-between; align-items: center; gap: 4px;">
                                    <span style="font-size: 9px; color:#aaa;">Rotation</span>
                                    <input id="pgfx-prop-rotation" type="number" step="1" style="width: 50px; font-size: 9px; background: #1a1a2e; color: #d4d4d8; border: 1px solid #333; border-radius: 4px; padding: 2px 3px;">
                                </div>
                                <div class="pgfx-row" style="justify-content: space-between; align-items: center; gap: 4px;">
                                    <span style="font-size: 9px; color:#aaa;">Scale</span>
                                    <input id="pgfx-prop-scale" type="number" step="0.01" style="width: 50px; font-size: 9px; background: #1a1a2e; color: #d4d4d8; border: 1px solid #333; border-radius: 4px; padding: 2px 3px;">
                                </div>
                            </div>

                            <!-- ELITE BRIDGE -->
                            <div class="pgfx-input-group" style="padding: 10px 8px;">
                                <label class="pgfx-label" style="font-size: 9px;">
                                    Elite Bridge
                                </label>
                                <button id="pgfx-send-agent-btn" class="pgfx-btn pgfx-btn-primary" style="font-size: 10px; padding: 8px 4px;" title="Describe the selected element">🤖 Describe Selection</button>
                                <div id="pgfx-agent-log" style="margin-top: 4px; max-height: 60px; overflow-y: auto; font-size: 8px; line-height: 1.4; color: #71717a;"></div>
                            </div>

                            <!-- SAVE / LOAD PROJECT -->
                            <div class="pgfx-input-group" style="padding: 10px 8px;">
                                <label class="pgfx-label" style="font-size: 9px;">
                                    Project
                                    <span style="font-weight: normal; opacity: 0.6; font-size: 8px;">.pgfx file</span>
                                </label>
                                <div style="display: flex; flex-direction: column; gap: 4px;">
                                    <button id="pgfx-save-project" class="pgfx-btn" style="width: 100%; font-size: 10px; padding: 6px 2px;" title="Save project file">💾 Save</button>
                                    <button id="pgfx-load-project" class="pgfx-btn" style="width: 100%; font-size: 10px; padding: 6px 2px;" title="Load project file">📂 Load</button>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
                <div id="pgfx-context-menu">
                    <div class="pgfx-menu-item" id="pgfx-ctx-clone">👯 Duplicate</div>
                    <div class="pgfx-menu-item" id="pgfx-ctx-group">📦 Group</div>
                    <div class="pgfx-menu-item" id="pgfx-ctx-ungroup">📂 Ungroup</div>
                    <div class="pgfx-menu-separator"></div>
                    <div class="pgfx-menu-item" id="pgfx-ctx-lock">🔒 Lock / Unlock</div>
                    <div class="pgfx-menu-item" id="pgfx-ctx-hide">👁️ Hide / Show</div>
                    <div class="pgfx-menu-separator"></div>
                    <div class="pgfx-menu-item" id="pgfx-ctx-agent" style="color: #06b6d4;">🤖 Send to Agent</div>
                    <div class="pgfx-menu-separator"></div>
                    <div class="pgfx-menu-item" id="pgfx-ctx-delete" style="color: #ef4444;">🗑️ Delete</div>
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
            if (!currentSrc) return;

            // If the src changed (or was reset by the save button), reload the image
            if (!this._pgfxPreviewImg || this._pgfxLastSrc !== currentSrc) {
                this._pgfxLastSrc    = currentSrc;
                this._pgfxPreviewImg = null;
                const img = new Image();
                img.onload  = () => { app.graph?.setDirtyCanvas(true, true); };
                img.onerror = () => { this._pgfxPreviewImg = null; };

                let realSrc = currentSrc;
                if (!realSrc.startsWith("data:image")) {
                    const parts = currentSrc.split("/");
                    const filename = parts.pop();
                    const subfolder = parts.join("/");
                    realSrc = `/view?filename=${encodeURIComponent(filename)}&type=input&subfolder=${encodeURIComponent(subfolder)}&t=${Date.now()}`;
                }
                img.src = realSrc;
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
            const hasSrc = (base64Widget?.value || "").trim().length > 0;
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

            presetWidget.callback = function (v, canvas, node) {
                if (origCallback) origCallback.call(this, v, canvas, node);

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