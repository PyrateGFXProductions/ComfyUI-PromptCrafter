import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

const injectStyles = () => {
    if (document.getElementById("pgfx-visual-browser-styles")) return;
    const style = document.createElement("style");
    style.id = "pgfx-visual-browser-styles";
    style.textContent = `
        .pgfx-browser-container {
            display: flex;
            flex-direction: column;
            gap: 6px;
            background: #111113;
            border: 1px solid rgba(255,255,255,0.1);
            border-radius: 8px;
            padding: 10px;
            color: white;
            font-family: 'Inter', system-ui, sans-serif;
            pointer-events: auto;
            box-sizing: border-box;
            will-change: transform;
        }
        .pgfx-pathbar {
            display: flex;
            align-items: center;
            gap: 2px;
            padding: 3px 6px;
            background: #000;
            border: 1px solid #333;
            border-radius: 4px;
            font-size: 11px;
            min-height: 26px;
            cursor: text;
            position: relative;
            flex: 1;
        }
        .pgfx-path-segment {
            cursor: pointer;
            color: #06b6d4;
            padding: 1px 3px;
            border-radius: 2px;
            white-space: nowrap;
        }
        .pgfx-path-segment:hover {
            background: #1a1a2e;
        }
        .pgfx-path-sep {
            color: #555;
            margin: 0 1px;
            user-select: none;
        }
        .pgfx-path-current {
            color: #aaa;
            white-space: nowrap;
        }
        .pgfx-path-input {
            flex: 1;
            background: #000;
            border: none;
            color: white;
            font-size: 11px;
            outline: none;
            font-family: inherit;
            min-width: 50px;
        }
        .pgfx-dropdown-btn {
            background: none;
            border: 1px solid #555;
            color: #aaa;
            padding: 0 6px;
            cursor: pointer;
            border-radius: 3px;
            font-size: 11px;
            line-height: 20px;
            flex-shrink: 0;
        }
        .pgfx-dropdown-btn:hover {
            background: #222;
            color: white;
        }
        .pgfx-folder-dropdown {
            display: none;
            position: absolute;
            top: 100%;
            right: 0;
            background: #1a1a1a;
            border: 1px solid #444;
            border-radius: 4px;
            max-height: 220px;
            overflow-y: auto;
            min-width: 200px;
            z-index: 1000;
            margin-top: 2px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.6);
        }
        .pgfx-folder-dropdown.active {
            display: block;
        }
        .pgfx-dropdown-item {
            padding: 5px 10px;
            font-size: 11px;
            cursor: pointer;
            color: #ccc;
            white-space: nowrap;
        }
        .pgfx-dropdown-item:hover {
            background: #06b6d4;
            color: black;
        }
        .pgfx-dropdown-item.parent-item {
            border-bottom: 1px solid #333;
        }
        .pgfx-top-row {
            display: flex;
            align-items: center;
            gap: 4px;
        }
        .pgfx-btn {
            background: #18181b;
            border: 1px solid #333;
            color: #aaa;
            padding: 2px 8px;
            border-radius: 4px;
            cursor: pointer;
            font-size: 10px;
            white-space: nowrap;
            line-height: 20px;
            flex-shrink: 0;
        }
        .pgfx-btn:hover {
            background: #222;
            color: white;
        }
        .pgfx-btn:disabled {
            opacity: 0.4;
            cursor: default;
        }
        .pgfx-refresh-btn {
            font-size: 13px;
            padding: 2px 6px;
            line-height: 20px;
        }
        .pgfx-search-row {
            display: flex;
            align-items: center;
            gap: 6px;
        }
        .pgfx-browser-search {
            background: #000;
            border: 1px solid #444;
            color: white;
            padding: 3px 8px;
            border-radius: 4px;
            font-size: 11px;
            outline: none;
            width: 160px;
            flex-shrink: 0;
        }
        .pgfx-browser-search:focus {
            border-color: #06b6d4;
        }
        .pgfx-filter-select {
            background: #000;
            border: 1px solid #444;
            color: white;
            padding: 3px 6px;
            border-radius: 4px;
            font-size: 11px;
            outline: none;
            flex-shrink: 0;
        }
        .pgfx-filter-select:focus {
            border-color: #06b6d4;
        }
        .pgfx-filter-custom {
            background: #000;
            border: 1px solid #444;
            color: white;
            padding: 3px 6px;
            border-radius: 4px;
            font-size: 11px;
            outline: none;
            width: 58px;
            flex-shrink: 0;
        }
        .pgfx-filter-custom:focus {
            border-color: #06b6d4;
        }
        .pgfx-file-icon {
            font-size: 20px;
            line-height: 1;
        }
        .pgfx-browser-item.file-item {
            flex-direction: column;
            gap: 3px;
            padding: 4px;
        }
        .pgfx-file-name {
            font-size: 8px;
            color: #aaa;
            max-width: 100%;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
            padding: 0 2px;
        }
        .pgfx-details-bar {
            display: flex;
            align-items: center;
            gap: 10px;
            padding: 3px 8px;
            background: #000;
            border: 1px solid #333;
            border-radius: 4px;
            font-size: 10px;
            min-height: 24px;
            color: #888;
            flex: 1;
            overflow-x: auto;
            white-space: nowrap;
        }
        .pgfx-details-item {
            display: flex;
            gap: 3px;
            align-items: center;
            flex-shrink: 0;
        }
        .pgfx-details-item + .pgfx-details-item::before {
            content: "|";
            color: #444;
            margin-right: 10px;
        }
        .pgfx-details-label {
            color: #555;
        }
        .pgfx-details-value {
            color: #ddd;
        }
        .pgfx-details-empty {
            color: #555;
            font-style: italic;
        }
        .pgfx-browser-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(70px, 1fr));
            gap: 5px;
            max-height: 260px;
            overflow-y: auto;
            padding-right: 4px;
        }
        .pgfx-browser-grid::-webkit-scrollbar {
            width: 5px;
        }
        .pgfx-browser-grid::-webkit-scrollbar-thumb {
            background: #333;
            border-radius: 3px;
        }
        .pgfx-browser-item {
            aspect-ratio: 1/1;
            background: #222;
            border-radius: 4px;
            overflow: hidden;
            cursor: pointer;
            border: 2px solid transparent;
            transition: all 0.2s ease;
            position: relative;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 10px;
            color: #888;
            text-align: center;
        }
        .pgfx-browser-item:hover {
            border-color: #06b6d4;
            transform: scale(1.05);
            z-index: 2;
        }
        .pgfx-browser-item.selected {
            border-color: #06b6d4;
            box-shadow: 0 0 10px rgba(6, 182, 212, 0.5);
        }
        .pgfx-browser-item.has-caption::after {
            content: "TXT";
            position: absolute;
            bottom: 4px;
            right: 4px;
            background: rgba(16, 185, 129, 0.85);
            color: white;
            font-size: 8px;
            font-weight: bold;
            padding: 1px 3px;
            border-radius: 2px;
            pointer-events: none;
            box-shadow: 0 1px 3px rgba(0,0,0,0.5);
        }
        .pgfx-browser-item img {
            width: 100%;
            height: 100%;
            object-fit: cover;
        }
        .pgfx-pagination {
            display: flex;
            justify-content: space-between;
            align-items: center;
            gap: 4px;
        }
        .pgfx-page-info {
            font-size: 10px;
            color: #888;
            white-space: nowrap;
        }

        /* --- Duplicate Scanner --- */
        .pgfx-scan-btn {
            background: #d97706;
            border: 1px solid #f59e0b;
            color: white;
            padding: 2px 8px;
            border-radius: 4px;
            cursor: pointer;
            font-size: 10px;
            white-space: nowrap;
            line-height: 20px;
            flex-shrink: 0;
        }
        .pgfx-scan-btn:hover {
            background: #f59e0b;
        }
        .pgfx-scan-btn:disabled {
            opacity: 0.4;
            cursor: default;
        }
        .pgfx-scan-btn.scanning {
            background: #2563eb;
            border-color: #3b82f6;
            animation: pgfx-pulse 1s infinite;
        }
        @keyframes pgfx-pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.5; }
        }

        /* --- Overlay Backdrop --- */
        .pgfx-overlay-backdrop {
            display: none;
            position: fixed;
            top: 0; left: 0; right: 0; bottom: 0;
            background: rgba(0,0,0,0.7);
            z-index: 9999;
            justify-content: center;
            align-items: center;
            backdrop-filter: blur(2px);
        }
        .pgfx-overlay-backdrop.active {
            display: flex;
        }
        .pgfx-overlay-panel {
            background: #1a1a2e;
            border: 1px solid #333;
            border-radius: 12px;
            padding: 20px;
            max-width: 90vw;
            max-height: 85vh;
            width: 800px;
            display: flex;
            flex-direction: column;
            box-shadow: 0 8px 32px rgba(0,0,0,0.5);
        }
        .pgfx-overlay-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 12px;
            flex-shrink: 0;
        }
        .pgfx-overlay-title {
            font-size: 14px;
            font-weight: 600;
            color: white;
        }
        .pgfx-overlay-close {
            background: none;
            border: none;
            color: #888;
            font-size: 18px;
            cursor: pointer;
            padding: 4px 8px;
            border-radius: 4px;
        }
        .pgfx-overlay-close:hover {
            background: #333;
            color: white;
        }
        .pgfx-overlay-body {
            flex: 1;
            overflow-y: auto;
            min-height: 200px;
        }
        .pgfx-overlay-body::-webkit-scrollbar {
            width: 6px;
        }
        .pgfx-overlay-body::-webkit-scrollbar-thumb {
            background: #444;
            border-radius: 3px;
        }
        .pgfx-overlay-footer {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-top: 12px;
            flex-shrink: 0;
            gap: 8px;
        }
        .pgfx-overlay-footer .pgfx-btn {
            font-size: 11px;
            padding: 4px 14px;
        }
        .pgfx-overlay-footer .pgfx-btn.danger {
            background: #dc2626;
            border-color: #ef4444;
            color: white;
        }
        .pgfx-overlay-footer .pgfx-btn.danger:hover {
            background: #ef4444;
        }
        .pgfx-overlay-footer .pgfx-btn.danger:disabled {
            opacity: 0.4;
            cursor: default;
        }
        .pgfx-overlay-footer .pgfx-btn.primary {
            background: #2563eb;
            border-color: #3b82f6;
            color: white;
        }
        .pgfx-overlay-footer .pgfx-btn.primary:hover {
            background: #3b82f6;
        }

        /* --- Duplicate Groups --- */
        .pgfx-dup-group {
            background: #111113;
            border: 1px solid #2a2a3e;
            border-radius: 8px;
            padding: 10px;
            margin-bottom: 10px;
        }
        .pgfx-dup-group:last-child {
            margin-bottom: 0;
        }
        .pgfx-dup-group-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 8px;
            font-size: 11px;
        }
        .pgfx-dup-group-label {
            color: #888;
        }
        .pgfx-dup-group-label strong {
            color: #ddd;
        }
        .pgfx-dup-group-files {
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
        }
        .pgfx-dup-item {
            width: 120px;
            background: #000;
            border-radius: 6px;
            overflow: hidden;
            border: 2px solid transparent;
            cursor: pointer;
            transition: all 0.15s ease;
            position: relative;
            user-select: none;
        }
        .pgfx-dup-item:hover {
            border-color: #06b6d4;
        }
        .pgfx-dup-item.selected {
            border-color: #ef4444;
            box-shadow: 0 0 8px rgba(239,68,68,0.4);
        }
        .pgfx-dup-item img {
            width: 100%;
            height: 80px;
            object-fit: cover;
            display: block;
        }
        .pgfx-dup-item-info {
            padding: 4px 6px;
            font-size: 9px;
            color: #aaa;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
            background: #0a0a0a;
        }
        .pgfx-dup-item-check {
            position: absolute;
            top: 4px;
            right: 4px;
            width: 18px;
            height: 18px;
            border-radius: 4px;
            background: rgba(0,0,0,0.7);
            border: 1px solid #555;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 12px;
            color: white;
            pointer-events: none;
        }
        .pgfx-dup-item.selected .pgfx-dup-item-check {
            background: #ef4444;
            border-color: #ef4444;
        }
        .pgfx-dup-empty {
            text-align: center;
            padding: 40px;
            color: #666;
            font-size: 13px;
        }
        .pgfx-scan-status {
            text-align: center;
            padding: 40px;
            color: #aaa;
            font-size: 13px;
        }
        .pgfx-scan-status .spinner {
            display: inline-block;
            width: 24px;
            height: 24px;
            border: 3px solid #333;
            border-top-color: #06b6d4;
            border-radius: 50%;
            animation: pgfx-spin 0.8s linear infinite;
            margin-bottom: 12px;
        }
        @keyframes pgfx-spin {
            to { transform: rotate(360deg); }
        }

        /* --- Caption Panel --- */
        .pgfx-caption-panel {
            display: none;
            flex-direction: column;
            gap: 6px;
            border-top: 1px solid #2a2a3e;
            padding-top: 8px;
            margin-top: 4px;
        }
        .pgfx-caption-panel.active {
            display: flex;
        }
        .pgfx-caption-label {
            font-size: 10px;
            color: #888;
            font-weight: 600;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .pgfx-caption-label .pgfx-caption-status {
            color: #555;
            font-weight: 400;
            font-size: 9px;
        }
        .pgfx-caption-textarea {
            background: #000;
            border: 1px solid #333;
            border-radius: 4px;
            color: white;
            font-size: 11px;
            padding: 6px 8px;
            outline: none;
            resize: vertical;
            font-family: inherit;
            min-height: 50px;
            max-height: 120px;
            line-height: 1.4;
            width: 100%;
            box-sizing: border-box;
        }
        .pgfx-caption-textarea:focus {
            border-color: #06b6d4;
        }
        .pgfx-caption-textarea::placeholder {
            color: #555;
        }
        .pgfx-caption-actions {
            display: flex;
            gap: 4px;
            flex-wrap: wrap;
        }
        .pgfx-caption-actions .pgfx-btn {
            font-size: 10px;
            padding: 2px 10px;
        }
        .pgfx-caption-actions .pgfx-btn.save {
            background: #059669;
            border-color: #10b981;
            color: white;
        }
        .pgfx-caption-actions .pgfx-btn.save:hover {
            background: #10b981;
        }
        .pgfx-caption-actions .pgfx-btn.save:disabled {
            opacity: 0.4;
            cursor: default;
        }
        .pgfx-caption-actions .pgfx-btn.generate {
            background: #7c3aed;
            border-color: #8b5cf6;
            color: white;
        }
        .pgfx-caption-actions .pgfx-btn.generate:hover {
            background: #8b5cf6;
        }
        .pgfx-caption-actions .pgfx-btn.generate:disabled {
            opacity: 0.4;
            cursor: default;
        }
        .pgfx-caption-actions .pgfx-btn.batch {
            background: #b45309;
            border-color: #d97706;
            color: white;
        }
        .pgfx-caption-actions .pgfx-btn.batch:hover {
            background: #d97706;
        }
        .pgfx-caption-actions .pgfx-btn.batch:disabled {
            opacity: 0.4;
            cursor: default;
        }
        .pgfx-caption-progress {
            font-size: 9px;
            color: #555;
            padding: 2px 0;
        }
        .pgfx-caption-progress.active {
            color: #06b6d4;
        }
        .pgfx-caption-progress.error {
            color: #ef4444;
        }
        .pgfx-caption-progress.success {
            color: #10b981;
        }
    `;
    document.head.appendChild(style);
};

const thumbCache = new Map();

app.registerExtension({
    name: "PromptCrafter.VisualFolderLoader",
    async beforeRegisterNodeDef(nodeType, nodeData, app) {
        if (nodeData.name !== "PGFX_VisualFolderLoader" && nodeData.name !== "PGFX_VisualFolderLoaderV3") return;

        injectStyles();

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            onNodeCreated?.apply(this, arguments);
            const node = this;

            const folderWidget = node.widgets.find(w => w.name === "folder");
            const selectedImageWidget = node.widgets.find(w => w.name === "selected_image");
            const captionModelWidget = node.widgets.find(w => w.name === "caption_model");
            const captionPromptWidget = node.widgets.find(w => w.name === "caption_prompt");
            const captionOutputWidget = node.widgets.find(w => w.name === "caption_output");

            selectedImageWidget.type = "hidden";

            let captionsEnabled = captionModelWidget && captionModelWidget.value && captionModelWidget.value.trim().length > 0;

            let currentFolder = folderWidget.value || ".";

            let imageData = { images: [], total: 0, page: 0, total_pages: 1 };
            let currentPage = 0;
            const perPage = 18;
            let currentFilter = "all";
            let customMode = false;

            const container = document.createElement("div");
            container.className = "pgfx-browser-container";

            // --- Top row: path bar + refresh ---
            const topRow = document.createElement("div");
            topRow.className = "pgfx-top-row";

            const pathBar = document.createElement("div");
            pathBar.className = "pgfx-pathbar";

            const dropdownBtn = document.createElement("button");
            dropdownBtn.className = "pgfx-dropdown-btn";
            dropdownBtn.textContent = "📂 ▼";
            dropdownBtn.title = "Browse subfolders";

            const folderDropdown = document.createElement("div");
            folderDropdown.className = "pgfx-folder-dropdown";

            pathBar.appendChild(dropdownBtn);
            pathBar.appendChild(folderDropdown);

            const refreshBtn = document.createElement("button");
            refreshBtn.className = "pgfx-btn pgfx-refresh-btn";
            refreshBtn.textContent = "↻";
            refreshBtn.title = "Refresh";
            refreshBtn.onclick = async (e) => {
                e.stopPropagation();
                await refreshAll();
            };

            const scanBtn = document.createElement("button");
            scanBtn.className = "pgfx-scan-btn";
            scanBtn.textContent = "🔍 Duplicates";
            scanBtn.title = "Scan for duplicate images in this folder";
            scanBtn.onclick = async (e) => {
                e.stopPropagation();
                await startDuplicateScan();
            };

            topRow.appendChild(pathBar);
            topRow.appendChild(scanBtn);
            topRow.appendChild(refreshBtn);
            container.appendChild(topRow);

            // --- Search row + details bar ---
            const searchRow = document.createElement("div");
            searchRow.className = "pgfx-search-row";

            const searchInput = document.createElement("input");
            searchInput.className = "pgfx-browser-search";
            searchInput.placeholder = "Search...";

            const filterSelect = document.createElement("select");
            filterSelect.className = "pgfx-filter-select";
            filterSelect.title = "Filter files by type";
            const filterOptions = [
                ["all", "All Files"],
                ["images", "🖼️ Images"],
                ["videos", "🎬 Videos"],
                ["audio", "🎵 Audio"],
                ["text", "📄 Text / Data"],
                ["models", "🧠 Models"],
                ["__custom__", "⌨️ Custom extension"],
            ];
            filterOptions.forEach(([val, label]) => {
                const opt = document.createElement("option");
                opt.value = val;
                opt.textContent = label;
                filterSelect.appendChild(opt);
            });

            const customFilterInput = document.createElement("input");
            customFilterInput.className = "pgfx-filter-custom";
            customFilterInput.placeholder = ".ext";
            customFilterInput.title = "Type any file extension to show only those files";
            customFilterInput.style.display = "none";

            const detailsBar = document.createElement("div");
            detailsBar.className = "pgfx-details-bar";
            detailsBar.innerHTML = '<span class="pgfx-details-empty">Select a file</span>';

            searchRow.appendChild(searchInput);
            searchRow.appendChild(filterSelect);
            searchRow.appendChild(customFilterInput);
            searchRow.appendChild(detailsBar);
            container.appendChild(searchRow);

            // --- Grid ---
            const grid = document.createElement("div");
            grid.className = "pgfx-browser-grid";
            container.appendChild(grid);

            // --- Pagination ---
            const paginationRow = document.createElement("div");
            paginationRow.className = "pgfx-pagination";

            const prevBtn = document.createElement("button");
            prevBtn.className = "pgfx-btn";
            prevBtn.textContent = "◀ Prev";

            const pageInfo = document.createElement("span");
            pageInfo.className = "pgfx-page-info";
            pageInfo.textContent = "Page 0 / 0";

            const nextBtn = document.createElement("button");
            nextBtn.className = "pgfx-btn";
            nextBtn.textContent = "Next ▶";

            paginationRow.append(prevBtn, pageInfo, nextBtn);
            container.appendChild(paginationRow);

            // --- Caption Panel ---
            const captionPanel = document.createElement("div");
            captionPanel.className = "pgfx-caption-panel";

            const captionHelp = document.createElement("div");
            captionHelp.className = "pgfx-caption-help";
            captionHelp.style.cssText = "font-size: 9px; color: #888; background: #1a1a2e; border: 1px solid rgba(6, 182, 212, 0.2); border-radius: 4px; padding: 6px; margin-bottom: 6px; line-height: 1.3;";
            captionHelp.innerHTML = `<strong>💡 Dataset Captioning:</strong> This panel manages <code>.txt</code> sidecar files containing tags/prompts next to your images. Set a <strong>caption_model</strong> and prompt above to use AI vision. Use <strong>✨ Generate</strong> for individual images or <strong>📝 Caption All</strong> to queue the entire folder.<br><br><strong>⚠️ Time Warning:</strong> Captioning can take <strong>5–30+ seconds per image</strong> depending on model/hardware. A batch of 100 images could take <strong>several minutes to an hour</strong>. Plan accordingly.`;
            captionPanel.append(captionHelp);

            const captionLabel = document.createElement("div");
            captionLabel.className = "pgfx-caption-label";
            const captionLabelText = document.createElement("span");
            captionLabelText.textContent = "Caption";
            const captionStatus = document.createElement("span");
            captionStatus.className = "pgfx-caption-status";
            captionStatus.textContent = "";
            captionLabel.append(captionLabelText, captionStatus);

            const captionTextarea = document.createElement("textarea");
            captionTextarea.className = "pgfx-caption-textarea";
            captionTextarea.placeholder = captionsEnabled ? "Select an image to view/edit its caption..." : "Set a caption_model in node inputs to enable captioning.";
            captionTextarea.disabled = !captionsEnabled;

            const captionActions = document.createElement("div");
            captionActions.className = "pgfx-caption-actions";

            const saveCaptionBtn = document.createElement("button");
            saveCaptionBtn.className = "pgfx-btn save";
            saveCaptionBtn.textContent = "💾 Save";
            saveCaptionBtn.disabled = true;
            saveCaptionBtn.title = "Save caption to file (format: caption_output)";

            const genCaptionBtn = document.createElement("button");
            genCaptionBtn.className = "pgfx-btn generate";
            genCaptionBtn.textContent = "✨ Generate";
            genCaptionBtn.disabled = true;
            genCaptionBtn.title = "Generate caption using vision model";

            const batchCaptionBtn = document.createElement("button");
            batchCaptionBtn.className = "pgfx-btn batch";
            batchCaptionBtn.textContent = "📝 Caption All";
            batchCaptionBtn.disabled = true;
            batchCaptionBtn.title = "Caption all uncaptioned images in folder";

            const captionProgress = document.createElement("div");
            captionProgress.className = "pgfx-caption-progress";
            captionProgress.textContent = "";

            captionActions.append(saveCaptionBtn, genCaptionBtn, batchCaptionBtn);
            captionPanel.append(captionLabel, captionTextarea, captionActions, captionProgress);
            container.appendChild(captionPanel);

            if (captionsEnabled) {
                captionPanel.classList.add("active");
            }

            // --- Duplicate Scan Overlay ---
            const overlayBackdrop = document.createElement("div");
            overlayBackdrop.className = "pgfx-overlay-backdrop";

            const overlayPanel = document.createElement("div");
            overlayPanel.className = "pgfx-overlay-panel";

            const overlayHeader = document.createElement("div");
            overlayHeader.className = "pgfx-overlay-header";
            const overlayTitle = document.createElement("span");
            overlayTitle.className = "pgfx-overlay-title";
            overlayTitle.textContent = "Scanning for Duplicates...";
            const overlayClose = document.createElement("button");
            overlayClose.className = "pgfx-overlay-close";
            overlayClose.textContent = "✕";
            overlayHeader.append(overlayTitle, overlayClose);

            const overlayBody = document.createElement("div");
            overlayBody.className = "pgfx-overlay-body";
            overlayBody.innerHTML = '<div class="pgfx-scan-status"><div class="spinner"></div><div>Scanning images...</div></div>';

            const overlayFooter = document.createElement("div");
            overlayFooter.className = "pgfx-overlay-footer";
            const footerLeft = document.createElement("div");
            const selectAllBtn = document.createElement("button");
            selectAllBtn.className = "pgfx-btn primary";
            selectAllBtn.textContent = "Select All";
            const deselectAllBtn = document.createElement("button");
            deselectAllBtn.className = "pgfx-btn";
            deselectAllBtn.textContent = "Deselect All";
            footerLeft.append(selectAllBtn, deselectAllBtn);
            const footerRight = document.createElement("div");
            const cancelBtn = document.createElement("button");
            cancelBtn.className = "pgfx-btn";
            cancelBtn.textContent = "Cancel";
            const deleteBtn = document.createElement("button");
            deleteBtn.className = "pgfx-btn danger";
            deleteBtn.textContent = "Delete Selected (0)";
            deleteBtn.disabled = true;
            footerRight.append(cancelBtn, deleteBtn);
            overlayFooter.append(footerLeft, footerRight);

            overlayPanel.append(overlayHeader, overlayBody, overlayFooter);
            overlayBackdrop.appendChild(overlayPanel);
            document.body.appendChild(overlayBackdrop);

            // --- Duplicate scan state ---
            let dupGroups = [];
            let dupSelectedFiles = new Set();
            let isScanning = false;

            // --- DOM Widget ---
            const widget = node.addDOMWidget("VisualBrowser", "visual_browser", container, {
                serialize: false,
                getValue() { return selectedImageWidget.value; },
                setValue(v) { selectedImageWidget.value = v; }
            });
            widget.computeSize = function(width) {
                return [width, 440];
            };
            if (node.setSize) node.setSize([680, 480]);

            // --- Dropdown ---
            const closeDropdown = () => {
                folderDropdown.classList.remove("active");
            };

            const openDropdown = async () => {
                await populateDropdown();
                folderDropdown.classList.add("active");
            };

            const toggleDropdown = async (e) => {
                e.stopPropagation();
                if (folderDropdown.classList.contains("active")) {
                    closeDropdown();
                } else {
                    await openDropdown();
                }
            };

            dropdownBtn.onclick = toggleDropdown;

            document.addEventListener("click", (e) => {
                if (!pathBar.contains(e.target)) {
                    closeDropdown();
                }
            });

            const populateDropdown = async () => {
                folderDropdown.innerHTML = '<div style="padding: 8px; font-size: 10px; color: #555;">Loading...</div>';
                try {
                    const resp = await api.fetchApi(`/pgfx/browser/subfolders?folder=${encodeURIComponent(currentFolder)}`);
                    const data = await resp.json();
                    folderDropdown.innerHTML = "";

                    if (data.parent) {
                        const parentItem = document.createElement("div");
                        parentItem.className = "pgfx-dropdown-item parent-item";
                        parentItem.textContent = "📁 .. (Up)";
                        parentItem.onclick = (e) => {
                            e.stopPropagation();
                            closeDropdown();
                            navigateTo(data.parent);
                        };
                        folderDropdown.appendChild(parentItem);
                    }

                    const sfs = data.subfolders || [];
                    if (sfs.length === 0 && !data.parent) {
                        folderDropdown.innerHTML = '<div style="padding: 8px; font-size: 10px; color: #555;">No subfolders</div>';
                        return;
                    }

                    sfs.forEach(sf => {
                        const item = document.createElement("div");
                        item.className = "pgfx-dropdown-item";
                        item.textContent = "📁 " + sf;
                        item.onclick = (e) => {
                            e.stopPropagation();
                            closeDropdown();
                            const target = joinPath(currentFolder, sf);
                            navigateTo(target);
                        };
                        folderDropdown.appendChild(item);
                    });

                    const pathInfo = document.createElement("div");
                    pathInfo.style.cssText = "padding: 5px 10px; font-size: 9px; color: #555; border-top: 1px solid #333; margin-top: 4px; word-break: break-all;";
                    pathInfo.textContent = data.current;
                    folderDropdown.appendChild(pathInfo);
                } catch (e) {
                    console.error("[PGFX] Dropdown error:", e);
                    folderDropdown.innerHTML = '<div style="padding: 8px; font-size: 10px; color: #f44;">Error</div>';
                }
            };

            // --- Path utilities ---
            const normalizePath = (p) => {
                if (!p || p === ".") return p;
                return p.replace(/\\/g, "/");
            };

            const joinPath = (base, name) => {
                if (!base || base === ".") return name;
                return base.replace(/\\/g, "/").replace(/\/+$/, "") + "/" + name;
            };

            const getPathSegments = (p) => {
                if (!p || p === ".") return [];
                const norm = normalizePath(p);
                if (norm === "/") return ["/"];
                return norm.split("/").filter(s => s !== "");
            };

            const buildPathUpTo = (segments, idx) => {
                if (segments.length === 0) return ".";
                const norm = normalizePath(currentFolder);
                let parts = segments.slice(0, idx + 1);
                if (parts[0] === "/") {
                    return parts.length === 1 ? "/" : "/" + parts.slice(1).join("/");
                }
                let built = parts.join("/");
                if (/^[A-Za-z]:$/.test(parts[0]) && parts.length === 1) {
                    built = parts[0] + "/";
                }
                if (norm.startsWith("/") && !built.startsWith("/")) {
                    built = "/" + built;
                }
                return built;
            };

            // --- Render path bar ---
            const renderPathBar = () => {
                const toRemove = [];
                for (const child of pathBar.children) {
                    if (child !== dropdownBtn && child !== folderDropdown) {
                        toRemove.push(child);
                    }
                }
                toRemove.forEach(el => el.remove());

                const segments = getPathSegments(currentFolder);
                
                // Truncate logic for individual segment display names
                const formatSeg = (s) => {
                    if (s.length <= 14 || s.endsWith(":")) return s;
                    return s.substring(0, 7) + ".." + s.substring(s.length - 4);
                };

                let displaySegments = segments.map((s, i) => ({
                    original: s,
                    display: formatSeg(s),
                    index: i
                }));

                // Collapse logic for deep paths
                if (displaySegments.length > 4) {
                    const first = displaySegments[0];
                    const lastTwo = displaySegments.slice(-2);
                    displaySegments = [first, { display: "...", isEllipsis: true }, ...lastTwo];
                }

                if (segments.length === 0 || currentFolder === ".") {
                    const span = document.createElement("span");
                    span.className = "pgfx-path-current";
                    span.textContent = "(Output)";
                    pathBar.insertBefore(span, dropdownBtn);
                } else {
                    displaySegments.forEach((seg, idx) => {
                        if (idx > 0) {
                            const sep = document.createElement("span");
                            sep.className = "pgfx-path-sep";
                            sep.textContent = "/";
                            pathBar.insertBefore(sep, dropdownBtn);
                        }
                        
                        if (seg.isEllipsis) {
                            const span = document.createElement("span");
                            span.className = "pgfx-path-sep";
                            span.textContent = "...";
                            span.title = "Middle folders hidden";
                            pathBar.insertBefore(span, dropdownBtn);
                            return;
                        }

                        const isLast = idx === displaySegments.length - 1;
                        if (isLast) {
                            const span = document.createElement("span");
                            span.className = "pgfx-path-current";
                            span.textContent = seg.display;
                            span.title = seg.original;
                            pathBar.insertBefore(span, dropdownBtn);
                        } else {
                            const span = document.createElement("span");
                            span.className = "pgfx-path-segment";
                            span.textContent = seg.display;
                            span.title = seg.original;
                            const targetPath = buildPathUpTo(segments, seg.index);
                            span.onclick = () => navigateTo(targetPath);
                            pathBar.insertBefore(span, dropdownBtn);
                        }
                    });
                }

                pathBar.appendChild(dropdownBtn);
                pathBar.appendChild(folderDropdown);
            };

            // --- Editable path ---
            let editInput = null;

            const startPathEdit = () => {
                const toRemove = [];
                for (const child of pathBar.children) {
                    if (child !== dropdownBtn && child !== folderDropdown) {
                        toRemove.push(child);
                    }
                }
                toRemove.forEach(el => el.remove());

                editInput = document.createElement("input");
                editInput.className = "pgfx-path-input";
                editInput.value = currentFolder;
                pathBar.insertBefore(editInput, dropdownBtn);

                editInput.focus();
                editInput.select();

                const finishEdit = () => {
                    const val = editInput.value.trim();
                    if (val) {
                        closeDropdown();
                        navigateTo(val);
                    }
                    editInput = null;
                    renderPathBar();
                };

                editInput.addEventListener("keydown", (e) => {
                    e.stopPropagation();
                    if (e.key === "Enter") {
                        finishEdit();
                    } else if (e.key === "Escape") {
                        editInput = null;
                        renderPathBar();
                    }
                });
                editInput.addEventListener("blur", () => {
                    setTimeout(() => {
                        if (editInput) finishEdit();
                    }, 200);
                });
            };

            pathBar.addEventListener("dblclick", (e) => {
                if (!editInput) {
                    e.stopPropagation();
                    startPathEdit();
                }
            });

            // --- Navigation ---
            const navigateTo = async (folder) => {
                currentFolder = folder.replace(/\\/g, "/");
                folderWidget.value = currentFolder;
                renderPathBar();
                await loadImages(0);
            };

            const refreshAll = async () => {
                renderPathBar();
                await loadImages(currentPage);
            };

            // --- Load images ---
            let searchTimer = null;
            let filterTimer = null;

            const normalizeExt = (v) => {
                const s = String(v || "").trim().toLowerCase();
                if (!s) return "all";
                return s.startsWith(".") ? s : "." + s;
            };

            const fileIconFor = (ext, isImage) => {
                if (isImage) return "🖼️";
                const e = (ext || "").toLowerCase();
                if ([".mp4", ".webm", ".mov", ".avi", ".mkv", ".flv", ".wmv", ".m4v", ".mpeg", ".mpg", ".3gp"].includes(e)) return "🎬";
                if ([".mp3", ".wav", ".flac", ".ogg", ".m4a", ".aac", ".opus", ".wma"].includes(e)) return "🎵";
                if ([".srt", ".vtt"].includes(e)) return "💬";
                if ([".json"].includes(e)) return "🧾";
                if ([".safetensors", ".ckpt", ".sft", ".pt", ".pth", ".gguf", ".onnx"].includes(e)) return "🧠";
                if ([".txt", ".md", ".csv", ".tsv"].includes(e)) return "📄";
                if ([".zip", ".7z", ".rar", ".tar", ".gz"].includes(e)) return "🗜️";
                if ([".html", ".xml", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".log"].includes(e)) return "⚙️";
                if ([".psd", ".xcf", ".ai", ".svg"].includes(e)) return "🎨";
                return "📁";
            };

            const showFilterUI = () => {
                customFilterInput.style.display = customMode ? "" : "none";
                filterSelect.value = customMode ? "__custom__" : currentFilter;
            };

            const setFilter = (value) => {
                if (value === "__custom__") {
                    customMode = true;
                    currentFilter = normalizeExt(customFilterInput.value);
                    showFilterUI();
                    customFilterInput.focus();
                } else {
                    customMode = false;
                    currentFilter = String(value || "all");
                    showFilterUI();
                }
                loadImages(0);
            };

            filterSelect.onchange = (e) => {
                e.stopPropagation();
                setFilter(filterSelect.value);
            };

            customFilterInput.oninput = () => {
                if (!customMode) return;
                if (filterTimer) clearTimeout(filterTimer);
                filterTimer = setTimeout(() => {
                    currentFilter = normalizeExt(customFilterInput.value);
                    loadImages(0);
                }, 250);
            };

            customFilterInput.onkeydown = (e) => e.stopPropagation();

            const loadImages = async (page) => {
                const folder = currentFolder;
                grid.innerHTML = '<div style="grid-column: 1/-1; text-align: center; padding: 20px; color: #666;">Loading...</div>';

                try {
                    const query = searchInput.value.trim();
                    let url = `/pgfx/browser/images?folder=${encodeURIComponent(folder)}&page=${page}&per_page=${perPage}&filter=${encodeURIComponent(currentFilter)}`;
                    if (query) url += `&search=${encodeURIComponent(query)}`;
                    const resp = await api.fetchApi(url);
                    const data = await resp.json();

                    imageData = data;
                    currentPage = data.page;
                    renderGrid();
                    updatePagination();
                } catch (e) {
                    console.error("[PGFX] Error loading images:", e);
                    grid.innerHTML = '<div style="grid-column: 1/-1; text-align: center; padding: 20px; color: #f44;">Error loading images</div>';
                }
            };

            // --- Render grid ---
            const renderGrid = () => {
                grid.innerHTML = "";
                const images = imageData.images || [];

                if (images.length === 0) {
                    const msg = currentFilter === "all" ? "No files found" : "No files match filter";
                    grid.innerHTML = `<div style="grid-column: 1/-1; text-align: center; padding: 20px; color: #666;">${msg}</div>`;
                    return;
                }

                images.forEach(imgData => {
                    const item = document.createElement("div");
                    item.className = "pgfx-browser-item";
                    if (!imgData.is_image) {
                        item.classList.add("file-item");
                    }
                    if (selectedImageWidget.value === imgData.filename) {
                        item.classList.add("selected");
                    }
                    if (imgData.has_caption) {
                        item.classList.add("has-caption");
                    }
                    item.title = imgData.filename;

                    if (imgData.is_image) {
                        const img = document.createElement("img");
                        const thumbUrl = imgData.url + "&preview=true";
                        const cached = thumbCache.get(thumbUrl);
                        if (cached && cached.complete && cached.naturalWidth > 0) {
                            img.src = thumbUrl;
                        } else {
                            img.src = thumbUrl;
                            if (!cached) {
                                const cacheImg = new Image();
                                cacheImg.src = thumbUrl;
                                thumbCache.set(thumbUrl, cacheImg);
                            }
                        }
                        img.loading = "lazy";
                        item.append(img);
                    } else {
                        const icon = document.createElement("div");
                        icon.className = "pgfx-file-icon";
                        icon.textContent = fileIconFor(imgData.ext, false);
                        const label = document.createElement("div");
                        label.className = "pgfx-file-name";
                        label.textContent = imgData.filename;
                        label.title = imgData.filename;
                        item.append(icon, label);
                    }

                    item.onclick = () => {
                        const prevSelected = grid.querySelector(".selected");
                        if (prevSelected) prevSelected.classList.remove("selected");
                        item.classList.add("selected");
                        selectedImageWidget.value = imgData.filename;
                        updateDetails(imgData.filename);
                        if (captionsEnabled) {
                            if (imgData.is_image) {
                                loadCaption(imgData.filename);
                            } else {
                                currentCaptionFile = imgData.filename;
                                captionTextarea.value = "";
                                captionStatus.textContent = "Not an image (no caption)";
                                saveCaptionBtn.disabled = true;
                                genCaptionBtn.disabled = true;
                            }
                        }
                        node.setDirtyCanvas(true, true);
                    };

                    grid.appendChild(item);
                });
            };

            // --- Pagination ---
            const updatePagination = () => {
                const tp = imageData.total_pages || 1;
                pageInfo.textContent = `Page ${currentPage + 1} / ${tp} (${imageData.total})`;
                prevBtn.disabled = currentPage <= 0;
                nextBtn.disabled = currentPage >= tp - 1;
            };

            prevBtn.onclick = (e) => {
                e.stopPropagation();
                if (currentPage > 0) loadImages(currentPage - 1);
            };

            nextBtn.onclick = (e) => {
                e.stopPropagation();
                if (currentPage < imageData.total_pages - 1) loadImages(currentPage + 1);
            };

            // --- Search ---
            searchInput.oninput = () => {
                if (searchTimer) clearTimeout(searchTimer);
                searchTimer = setTimeout(() => loadImages(0), 250);
            };

            // --- Details bar ---
            const updateDetails = async (filename) => {
                detailsBar.innerHTML = '<span class="pgfx-details-empty">Loading...</span>';

                try {
                    const resp = await api.fetchApi(`/pgfx/browser/details?folder=${encodeURIComponent(currentFolder)}&filename=${encodeURIComponent(filename)}`);
                    const d = await resp.json();

                    const parts = [
                        { label: "Type", value: d.kind || d.format },
                        { label: "Size", value: d.size },
                        { label: "Date", value: d.date },
                        { label: "Res", value: d.resolution },
                    ];

                    detailsBar.innerHTML = parts.map(p =>
                        `<span class="pgfx-details-item">` +
                        (p.label ? `<span class="pgfx-details-label">${p.label}:</span>` : ``) +
                        `<span class="pgfx-details-value">${p.value}</span></span>`
                    ).join("");
                } catch (e) {
                    console.error("[PGFX] Details error:", e);
                    detailsBar.innerHTML = '<span class="pgfx-details-empty">Error loading details</span>';
                }
            };

            // --- Caption functions ---
            let currentCaptionFile = "";

            const loadCaption = async (filename) => {
                currentCaptionFile = filename;
                captionStatus.textContent = "Loading...";
                saveCaptionBtn.disabled = true;
                genCaptionBtn.disabled = true;

                if (!filename) {
                    captionTextarea.value = "";
                    captionStatus.textContent = "No image selected";
                    return;
                }

                try {
                    const resp = await api.fetchApi(`/pgfx/browser/caption?folder=${encodeURIComponent(currentFolder)}&filename=${encodeURIComponent(filename)}`);
                    const data = await resp.json();
                    if (data.error) {
                        captionTextarea.value = "";
                        captionStatus.textContent = `Error: ${data.error}`;
                        return;
                    }
                    captionTextarea.value = data.caption || "";
                    captionStatus.textContent = data.caption ? "📄 Caption loaded" : "No caption found";
                    saveCaptionBtn.disabled = false;
                    genCaptionBtn.disabled = false;
                } catch (e) {
                    console.error("[PGFX] Caption load error:", e);
                    captionTextarea.value = "";
                    captionStatus.textContent = "Error loading caption";
                }
            };

            const getCaptionOutput = () => captionOutputWidget?.value || "Sidecar .txt";

            const saveCaption = async () => {
                const text = captionTextarea.value.trim();
                if (!currentCaptionFile) return;

                captionStatus.textContent = "Saving...";
                saveCaptionBtn.disabled = true;

                try {
                    const resp = await api.fetchApi("/pgfx/browser/save-caption", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({
                            folder: currentFolder,
                            filename: currentCaptionFile,
                            caption: text,
                            caption_output: getCaptionOutput(),
                        }),
                    });
                    const data = await resp.json();
                    if (data.success) {
                        captionStatus.textContent = "✅ Saved";
                    } else {
                        captionStatus.textContent = `⚠️ Error: ${data.error || "Unknown"}`;
                    }
                } catch (e) {
                    console.error("[PGFX] Caption save error:", e);
                    captionStatus.textContent = "❌ Save failed";
                } finally {
                    saveCaptionBtn.disabled = false;
                }
            };

            const generateCaption = async () => {
                if (!currentCaptionFile) return;

                const model = captionModelWidget?.value?.trim();
                const userPrompt = captionPromptWidget?.value?.trim();
                const prompt = userPrompt
                    ? `Describe this image in detail. Use the following as ground truth context for what is depicted: ${userPrompt}`
                    : "Describe this image in detail, focusing on the subject, setting, composition, lighting, and style. Include the subject's appearance, pose, background, mood, and any notable visual elements.";

                if (!model) {
                    captionStatus.textContent = "⚠️ No caption_model configured";
                    return;
                }

                genCaptionBtn.disabled = true;
                saveCaptionBtn.disabled = true;
                captionStatus.textContent = "⏳ Generating...";
                captionTextarea.value = "";

                // Capture file reference to avoid race if user clicks another image
                const targetFile = currentCaptionFile;
                const targetFolder = currentFolder;

                try {
                    const resp = await api.fetchApi("/pgfx/browser/generate-caption", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({
                            folder: targetFolder,
                            filename: targetFile,
                            model: model,
                            prompt: prompt,
                            temperature: 0.2,
                        }),
                    });
                    const data = await resp.json();
                    if (data.error) {
                        captionStatus.textContent = `❌ ${data.error}`;
                        return;
                    }
                    const captionText = data.caption || "";

                    // Only update UI if still on the same image
                    if (currentCaptionFile === targetFile) {
                        captionTextarea.value = captionText;
                        captionStatus.textContent = "✨ Generated";
                        saveCaptionBtn.disabled = false;
                    }

                    // Auto-save — show combined status
                    let saveResult = "ok";
                    try {
                        const saveResp = await api.fetchApi("/pgfx/browser/save-caption", {
                            method: "POST",
                            headers: { "Content-Type": "application/json" },
                            body: JSON.stringify({
                                folder: targetFolder,
                                filename: targetFile,
                                caption: captionText,
                                caption_output: getCaptionOutput(),
                            }),
                        });
                        const saveData = await saveResp.json();
                        if (!saveData.success) {
                            saveResult = `Save: ${saveData.error || "Unknown"}`;
                        }
                    } catch (saveErr) {
                        console.error("[PGFX] Auto-save error:", saveErr);
                        saveResult = "Auto-save failed";
                    }

                    if (currentCaptionFile === targetFile) {
                        captionStatus.textContent = saveResult === "ok" ? "✨ Generated ✅ Saved" : `✨ Generated ⚠️ ${saveResult}`;
                        saveCaptionBtn.disabled = false;
                    }

                    // Refresh grid to update TXT badges
                    loadImages(currentPage).catch(err => console.error("[PGFX] Grid refresh error:", err));

                } catch (e) {
                    console.error("[PGFX] Caption generate error:", e);
                    captionStatus.textContent = "❌ Generation failed";
                } finally {
                    genCaptionBtn.disabled = false;
                    if (currentCaptionFile === targetFile) {
                        saveCaptionBtn.disabled = false;
                    }
                }
            };

            let batchCancelled = false;

            const batchCaption = async () => {
                const model = captionModelWidget?.value?.trim();
                const userPrompt = captionPromptWidget?.value?.trim();
                const prompt = userPrompt
                    ? `Describe this image in detail. Use the following as ground truth context for what is depicted: ${userPrompt}`
                    : "";

                if (!model) {
                    captionStatus.textContent = "⚠️ No caption_model configured";
                    return;
                }

                const overwrite = confirm("Do you want to overwrite existing captions?\n\n- Click OK to overwrite existing captions.\n- Click Cancel to only caption images that don't have captions yet.");

                captionProgress.textContent = "⏳ Scanning folder...";
                captionProgress.className = "pgfx-caption-progress active";
                batchCaptionBtn.textContent = "🛑 Stop Batch";
                batchCaptionBtn.onclick = () => {
                    batchCancelled = true;
                    batchCaptionBtn.textContent = "Stopping...";
                    batchCaptionBtn.disabled = true;
                };

                try {
                    const resp = await api.fetchApi(`/pgfx/browser/images?folder=${encodeURIComponent(currentFolder)}&per_page=999999`);
                    const data = await resp.json();
                    const files = data.images || [];
                    const images = files.filter(f => f.is_image);

                    let toProcess = [];
                    if (overwrite) {
                        toProcess = images;
                    } else {
                        toProcess = images.filter(img => !img.has_caption);
                    }

                    const total = toProcess.length;
                    if (total === 0) {
                        captionProgress.textContent = "ℹ️ No images need captioning.";
                        captionProgress.className = "pgfx-caption-progress success";
                        resetBatchBtn();
                        return;
                    }

                    const estSeconds = total * 15;
                    const timeStr = estSeconds < 60
                        ? `~${estSeconds} seconds`
                        : `~${Math.round(estSeconds / 60)} minutes (${estSeconds} seconds)`;
                    if (!confirm(`⚠️  TIME WARNING\n\nFound ${total} images to caption using model: ${model}.\nEstimated time: ${timeStr} (at ~15s per image).\n\nProceed?`)) {
                        captionProgress.textContent = "Batch cancelled.";
                        captionProgress.className = "pgfx-caption-progress";
                        resetBatchBtn();
                        return;
                    }

                    batchCancelled = false;
                    let successCount = 0;
                    let failCount = 0;

                    for (let i = 0; i < total; i++) {
                        if (batchCancelled) {
                            captionProgress.textContent = `🛑 Stopped. Processed ${successCount}, failed ${failCount}.`;
                            captionProgress.className = "pgfx-caption-progress error";
                            break;
                        }

                        const img = toProcess[i];
                        captionProgress.textContent = `⏳ Captioning ${i + 1}/${total} (${Math.round((i/total)*100)}%): ${img.filename}...`;

                        try {
                            const genResp = await api.fetchApi("/pgfx/browser/generate-caption", {
                                method: "POST",
                                headers: { "Content-Type": "application/json" },
                                body: JSON.stringify({
                                    folder: currentFolder,
                                    filename: img.filename,
                                    model: model,
                                    prompt: prompt,
                                    temperature: 0.2,
                                }),
                            });
                            const genData = await genResp.json();
                            if (genData.error) {
                                failCount++;
                                console.error(`Failed to caption ${img.filename}:`, genData.error);
                            } else {
                                // Save the caption file
                                let saved = false;
                                try {
                                    const saveResp = await api.fetchApi("/pgfx/browser/save-caption", {
                                        method: "POST",
                                        headers: { "Content-Type": "application/json" },
                                        body: JSON.stringify({
                                            folder: currentFolder,
                                            filename: img.filename,
                                            caption: genData.caption || "",
                                            caption_output: getCaptionOutput(),
                                        }),
                                    });
                                    const saveData = await saveResp.json();
                                    saved = saveData.success;
                                } catch (saveErr) {
                                    console.error(`Failed to save caption for ${img.filename}:`, saveErr);
                                }

                                if (saved) {
                                    successCount++;
                                } else {
                                    failCount++;
                                }

                                if (currentCaptionFile === img.filename) {
                                    captionTextarea.value = genData.caption || "";
                                    captionStatus.textContent = saved ? "✨ Generated ✅ Saved" : "✨ Generated ⚠️ Save failed";
                                    saveCaptionBtn.disabled = false;
                                }
                            }
                        } catch (err) {
                            failCount++;
                            console.error(`Error captioning ${img.filename}:`, err);
                        }
                    }

                    if (!batchCancelled) {
                        captionProgress.textContent = `✅ Completed! Processed ${successCount}, failed ${failCount}.`;
                        captionProgress.className = failCount > 0 ? "pgfx-caption-progress error" : "pgfx-caption-progress success";
                    }

                    await loadImages(currentPage);

                } catch (e) {
                    console.error("[PGFX] Batch caption error:", e);
                    captionProgress.textContent = "❌ Batch captioning failed";
                    captionProgress.className = "pgfx-caption-progress error";
                } finally {
                    resetBatchBtn();
                    setTimeout(() => {
                        captionProgress.className = "pgfx-caption-progress";
                        captionProgress.textContent = "";
                    }, 5000);
                }
            };

            const resetBatchBtn = () => {
                batchCaptionBtn.textContent = "📝 Caption All";
                batchCaptionBtn.disabled = false;
                batchCaptionBtn.onclick = batchCaption;
            };

            // --- Caption button handlers ---
            saveCaptionBtn.onclick = saveCaption;
            genCaptionBtn.onclick = generateCaption;
            batchCaptionBtn.onclick = batchCaption;

            // Watch for caption_model changes to enable/disable caption panel
            if (captionModelWidget) {
                const origCallback = captionModelWidget.callback;
                captionModelWidget.callback = function(...args) {
                    origCallback?.apply(this, args);
                    const hasModel = this.value && this.value.trim().length > 0;
                    captionsEnabled = hasModel;
                    captionPanel.classList.toggle("active", hasModel);
                    captionTextarea.disabled = !hasModel;
                    captionTextarea.placeholder = hasModel
                        ? "Select an image to view/edit its caption..."
                        : "Set a caption_model in node inputs to enable captioning.";
                    if (!hasModel) {
                        captionTextarea.value = "";
                        captionStatus.textContent = "";
                        saveCaptionBtn.disabled = true;
                        genCaptionBtn.disabled = true;
                        batchCaptionBtn.disabled = true;
                    } else {
                        batchCaptionBtn.disabled = false;
                        if (currentCaptionFile) {
                            loadCaption(currentCaptionFile);
                        }
                    }
                    node.setDirtyCanvas(true, true);
                };
            }

            // Update compute size when caption panel visibility changes
            const origComputeSize = widget.computeSize;
            widget.computeSize = function(width) {
                const base = origComputeSize ? origComputeSize.call(this, width) : [width, 440];
                if (captionsEnabled && captionPanel.classList.contains("active")) {
                    base[1] = Math.max(base[1], 530);
                }
                return base;
            };

            // --- Duplicate scan overlay functions ---
            const showOverlay = () => {
                overlayBackdrop.classList.add("active");
            };

            const hideOverlay = () => {
                overlayBackdrop.classList.remove("active");
                dupGroups = [];
                dupSelectedFiles.clear();
            };

            const renderDuplicateGroups = () => {
                overlayBody.innerHTML = "";
                if (dupGroups.length === 0) {
                    overlayBody.innerHTML = '<div class="pgfx-dup-empty">🎉 No duplicate images found!</div>';
                    return;
                }

                dupGroups.forEach((group, gi) => {
                    const groupDiv = document.createElement("div");
                    groupDiv.className = "pgfx-dup-group";

                    const header = document.createElement("div");
                    header.className = "pgfx-dup-group-header";
                    header.innerHTML = `<span class="pgfx-dup-group-label"><strong>Group ${gi + 1}</strong> — ${group.type === "exact" ? "Exact duplicate" : "Near duplicate"} (${group.similarity * 100}% similar)</span>`;

                    const filesDiv = document.createElement("div");
                    filesDiv.className = "pgfx-dup-group-files";

                    group.files.forEach((file) => {
                        const item = document.createElement("div");
                        item.className = "pgfx-dup-item";
                        item.dataset.path = file.path;
                        if (dupSelectedFiles.has(file.path)) {
                            item.classList.add("selected");
                        }

                        const img = document.createElement("img");
                        img.src = file.url + "&preview=true";
                        img.loading = "lazy";
                        img.alt = file.filename;

                        const check = document.createElement("div");
                        check.className = "pgfx-dup-item-check";
                        check.textContent = dupSelectedFiles.has(file.path) ? "✕" : "";

                        const info = document.createElement("div");
                        info.className = "pgfx-dup-item-info";
                        info.textContent = `${file.filename} (${file.size})`;

                        item.append(img, check, info);

                        item.onclick = (e) => {
                            e.stopPropagation();
                            const path = item.dataset.path;
                            if (dupSelectedFiles.has(path)) {
                                dupSelectedFiles.delete(path);
                                item.classList.remove("selected");
                                check.textContent = "";
                            } else {
                                dupSelectedFiles.add(path);
                                item.classList.add("selected");
                                check.textContent = "✕";
                            }
                            updateDeleteButton();
                        };

                        filesDiv.appendChild(item);
                    });

                    groupDiv.append(header, filesDiv);
                    overlayBody.appendChild(groupDiv);
                });

                // Auto-select all files from first group onward (skip one per group to keep)
                if (dupSelectedFiles.size === 0) {
                    dupGroups.forEach((group) => {
                        // Keep the first file, mark rest for deletion
                        for (let i = 1; i < group.files.length; i++) {
                            dupSelectedFiles.add(group.files[i].path);
                        }
                    });
                }
                updateDeleteButton();
                // Re-render to show checkmarks
                renderDuplicateGroupsChecks();
            };

            const renderDuplicateGroupsChecks = () => {
                const items = overlayBody.querySelectorAll(".pgfx-dup-item");
                items.forEach((item) => {
                    const path = item.dataset.path;
                    const check = item.querySelector(".pgfx-dup-item-check");
                    if (dupSelectedFiles.has(path)) {
                        item.classList.add("selected");
                        if (check) check.textContent = "✕";
                    } else {
                        item.classList.remove("selected");
                        if (check) check.textContent = "";
                    }
                });
            };

            const updateDeleteButton = () => {
                const count = dupSelectedFiles.size;
                deleteBtn.textContent = `Delete Selected (${count})`;
                deleteBtn.disabled = count === 0;
            };

            const startDuplicateScan = async () => {
                if (isScanning) return;
                isScanning = true;
                scanBtn.disabled = true;
                scanBtn.classList.add("scanning");
                scanBtn.textContent = "⏳ Scanning...";

                overlayTitle.textContent = "Scanning for Duplicates...";
                overlayBody.innerHTML = '<div class="pgfx-scan-status"><div class="spinner"></div><div>Scanning images...</div></div>';
                overlayClose.style.display = "none";
                deleteBtn.style.display = "none";
                cancelBtn.textContent = "Cancel";
                selectAllBtn.style.display = "none";
                deselectAllBtn.style.display = "none";
                showOverlay();

                try {
                    const resp = await api.fetchApi("/pgfx/browser/scan-duplicates", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ folder: currentFolder, threshold: 10 }),
                    });
                    const data = await resp.json();

                    if (data.error) {
                        overlayBody.innerHTML = `<div class="pgfx-dup-empty">Error: ${data.error}</div>`;
                        return;
                    }

                    dupGroups = data.groups || [];
                    const totalDups = data.total_duplicates || 0;
                    const totalFiles = data.total_files || 0;

                    overlayTitle.textContent = `Duplicate Images Found (${dupGroups.length} groups, ${totalDups} files out of ${totalFiles})`;

                    if (dupGroups.length === 0) {
                        overlayBody.innerHTML = '<div class="pgfx-dup-empty">🎉 No duplicate images found!</div>';
                        return;
                    }

                    overlayClose.style.display = "";
                    deleteBtn.style.display = "";
                    selectAllBtn.style.display = "";
                    deselectAllBtn.style.display = "";
                    cancelBtn.textContent = "Close";

                    dupSelectedFiles.clear();
                    renderDuplicateGroups();

                } catch (e) {
                    console.error("[PGFX] Duplicate scan error:", e);
                    overlayBody.innerHTML = `<div class="pgfx-dup-empty">Error: ${e.message}</div>`;
                } finally {
                    isScanning = false;
                    scanBtn.disabled = false;
                    scanBtn.classList.remove("scanning");
                    scanBtn.textContent = "🔍 Duplicates";
                }
            };

            const executeDelete = async () => {
                const paths = Array.from(dupSelectedFiles);
                if (paths.length === 0) return;

                if (!confirm(`Are you sure you want to delete ${paths.length} file(s)?\n\nThis action cannot be undone.`)) {
                    return;
                }

                deleteBtn.disabled = true;
                deleteBtn.textContent = "⏳ Deleting...";

                try {
                    const resp = await api.fetchApi("/pgfx/browser/delete-files", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ files: paths }),
                    });
                    const data = await resp.json();

                    const deleted = data.deleted || [];
                    const failed = data.failed || [];

                    overlayTitle.textContent = `Deleted ${deleted.length} file(s)`;

                    if (failed.length > 0) {
                        overlayBody.innerHTML = `<div class="pgfx-dup-empty">⚠️ Deleted ${deleted.length}, but ${failed.length} failed:<br>${failed.map(f => `${f.path}: ${f.reason}`).join("<br>")}</div>`;
                    } else {
                        overlayBody.innerHTML = `<div class="pgfx-dup-empty">✅ Successfully deleted ${deleted.length} file(s)!</div>`;
                    }

                    deleteBtn.style.display = "none";
                    selectAllBtn.style.display = "none";
                    deselectAllBtn.style.display = "none";
                    cancelBtn.textContent = "Close";
                    dupSelectedFiles.clear();

                    // Refresh the image grid
                    setTimeout(() => refreshAll(), 500);

                } catch (e) {
                    console.error("[PGFX] Delete error:", e);
                    overlayBody.innerHTML = `<div class="pgfx-dup-empty">Error: ${e.message}</div>`;
                    deleteBtn.disabled = false;
                    deleteBtn.textContent = `Delete Selected (${dupSelectedFiles.size})`;
                }
            };

            // --- Overlay event handlers ---
            overlayClose.onclick = hideOverlay;
            cancelBtn.onclick = hideOverlay;

            overlayBackdrop.addEventListener("click", (e) => {
                if (e.target === overlayBackdrop) {
                    hideOverlay();
                }
            });

            selectAllBtn.onclick = () => {
                const items = overlayBody.querySelectorAll(".pgfx-dup-item");
                items.forEach((item) => {
                    dupSelectedFiles.add(item.dataset.path);
                });
                renderDuplicateGroupsChecks();
                updateDeleteButton();
            };

            deselectAllBtn.onclick = () => {
                dupSelectedFiles.clear();
                renderDuplicateGroupsChecks();
                updateDeleteButton();
            };

            deleteBtn.onclick = executeDelete;

            // --- Keyboard shortcuts ---
            document.addEventListener("keydown", (e) => {
                if (!overlayBackdrop.classList.contains("active")) return;

                if (e.key === "Escape") {
                    e.preventDefault();
                    hideOverlay();
                } else if (e.key === "Delete" || e.key === "Backspace") {
                    if (dupSelectedFiles.size > 0 && !isScanning) {
                        e.preventDefault();
                        executeDelete();
                    }
                }
            });

            // --- Init ---
            const init = async () => {
                if (currentFolder === ".") {
                    try {
                        const resp = await api.fetchApi(`/pgfx/browser/subfolders?folder=.`);
                        const data = await resp.json();
                        if (data.current) {
                            currentFolder = data.current;
                            folderWidget.value = currentFolder;
                        }
                    } catch (e) {
                        console.error("[PGFX] Init resolve error:", e);
                    }
                }
                renderPathBar();
                showFilterUI();
                await loadImages(0);
                if (captionsEnabled) {
                    batchCaptionBtn.disabled = false;
                    if (selectedImageWidget.value) {
                        const selFile = selectedImageWidget.value;
                        setTimeout(() => loadCaption(selFile), 200);
                    }
                }
            };

            setTimeout(init, 100);
        };

        // --- addDOMWidget shim ---
        const onNodeCreatedBase = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function() {
            if (!this.addDOMWidget) {
                this.addDOMWidget = (name, type, element, options = {}) => {
                    if (element._pgfx_widget) return element._pgfx_widget;

                    const widget = {
                        type: type,
                        name: name,
                        get value() { return options.getValue ? options.getValue() : element.value; },
                        set value(v) { if (options.setValue) options.setValue(v); else element.value = v; },
                        draw() {},
                        element: element,
                        options: options,
                        computeSize(width) { return [width, 440]; },
                        height: 440,
                    };
                    element._pgfx_widget = widget;

                    element.style.position = "absolute";
                    element.style.zIndex = 10;
                    element.style.boxSizing = "border-box";
                    element.style.left = "0px";
                    element.style.top = "0px";
                    this.widgets.push(widget);

                    const canvasParent = app.canvas.el.parentElement;
                    if (element.parentElement !== canvasParent) {
                        canvasParent.appendChild(element);
                    }

                    const onRemoved = this.onRemoved;
                    this.onRemoved = function() {
                        element.remove();
                        onRemoved?.apply(this, arguments);
                    };

                    let lastX, lastY, lastW, lastScale, lastCollapsed, lastYOffset;

                    const updatePosition = () => {
                        if (!this.graph || !element.parentElement || !app.canvas?.ds) return;
                        
                        const scale = app.canvas.ds.scale;
                        const offset = app.canvas.ds.offset;
                        const collapsed = !!this.flags?.collapsed;
                        
                        if (collapsed) {
                            if (lastCollapsed !== true) {
                                element.style.display = "none";
                                lastCollapsed = true;
                            }
                            return;
                        }

                        const widgetIndex = this.widgets.indexOf(widget);
                        let yOffset = 0;
                        if (widgetIndex > 0) {
                            for (let i = 0; i < widgetIndex; i++) {
                                const w = this.widgets[i];
                                if (w.computeSize) {
                                    const sz = w.computeSize(this.size[0]);
                                    yOffset += (sz && sz[1]) ? sz[1] : 20;
                                } else if (w.height) {
                                    yOffset += w.height;
                                } else {
                                    yOffset += 20;
                                }
                            }
                        }

                        const x = (this.pos[0] + offset[0]) * scale;
                        const y = (this.pos[1] + offset[1] + 60 + yOffset) * scale;
                        const w = (this.size[0] - 20) * scale;

                        if (x === lastX && y === lastY && w === lastW && scale === lastScale && yOffset === lastYOffset && lastCollapsed === false) {
                            return;
                        }

                        lastX = x; lastY = y; lastW = w; lastScale = scale; lastYOffset = yOffset; lastCollapsed = false;

                        element.style.display = "flex";
                        element.style.width = `${w}px`;
                        element.style.transformOrigin = "top left";
                        element.style.transform = `translate(${x}px, ${y}px) scale(${scale})`;
                    };

                    const origDraw = this.onDrawForeground;
                    if (!origDraw || !origDraw._pgfx_wrapped) {
                        this.onDrawForeground = function() {
                            updatePosition();
                            return origDraw?.apply(this, arguments);
                        };
                        this.onDrawForeground._pgfx_wrapped = true;
                    }

                    return widget;
                };
            }
            onNodeCreatedBase?.apply(this, arguments);
        };
    }
});
