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
            gap: 8px;
            background: #111113;
            border: 1px solid rgba(255,255,255,0.1);
            border-radius: 8px;
            padding: 12px;
            color: white;
            font-family: 'Inter', system-ui, sans-serif;
            pointer-events: auto;
            min-height: 400px;
        }
        .pgfx-browser-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            gap: 8px;
        }
        .pgfx-browser-title {
            font-size: 11px;
            font-weight: bold;
            color: #06b6d4;
            white-space: nowrap;
        }
        .pgfx-breadcrumbs {
            display: flex;
            flex-wrap: wrap;
            align-items: center;
            gap: 2px;
            padding: 4px 8px;
            background: #000;
            border: 1px solid #333;
            border-radius: 4px;
            font-size: 11px;
            min-height: 28px;
        }
        .pgfx-breadcrumb-segment {
            cursor: pointer;
            color: #06b6d4;
            padding: 1px 4px;
            border-radius: 2px;
            white-space: nowrap;
        }
        .pgfx-breadcrumb-segment:hover {
            background: #1a1a2e;
        }
        .pgfx-breadcrumb-sep {
            color: #555;
            margin: 0 2px;
        }
        .pgfx-breadcrumb-current {
            color: #aaa;
            white-space: nowrap;
        }
        .pgfx-toolbar {
            display: flex;
            gap: 6px;
            align-items: center;
        }
        .pgfx-btn {
            background: #18181b;
            border: 1px solid #333;
            color: #aaa;
            padding: 4px 10px;
            border-radius: 4px;
            cursor: pointer;
            font-size: 10px;
            white-space: nowrap;
        }
        .pgfx-btn:hover {
            background: #222;
            color: white;
        }
        .pgfx-btn:disabled {
            opacity: 0.4;
            cursor: default;
        }
        .pgfx-browser-search {
            background: #000;
            border: 1px solid #444;
            color: white;
            padding: 4px 8px;
            border-radius: 4px;
            font-size: 11px;
            outline: none;
            flex: 1;
            min-width: 80px;
        }
        .pgfx-browser-search:focus {
            border-color: #06b6d4;
        }
        .pgfx-browser-main {
            display: flex;
            gap: 8px;
            flex: 1;
            min-height: 0;
        }
        .pgfx-folder-list {
            width: 160px;
            min-width: 120px;
            background: #000;
            border: 1px solid #333;
            border-radius: 4px;
            overflow-y: auto;
            padding: 4px;
            display: flex;
            flex-direction: column;
            gap: 1px;
            max-height: 280px;
        }
        .pgfx-folder-item {
            padding: 4px 6px;
            font-size: 11px;
            cursor: pointer;
            border-radius: 3px;
            color: #ccc;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }
        .pgfx-folder-item:hover {
            background: #1a1a2e;
            color: white;
        }
        .pgfx-folder-item.active-folder {
            background: #06b6d4;
            color: black;
        }
        .pgfx-grid-area {
            flex: 1;
            min-width: 0;
            display: flex;
            flex-direction: column;
            gap: 4px;
        }
        .pgfx-browser-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(70px, 1fr));
            gap: 6px;
            max-height: 280px;
            overflow-y: auto;
            padding-right: 4px;
        }
        .pgfx-browser-grid::-webkit-scrollbar {
            width: 6px;
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
        .pgfx-browser-item img {
            width: 100%;
            height: 100%;
            object-fit: cover;
        }
        .pgfx-folder-thumb {
            font-size: 24px;
            opacity: 0.5;
        }
        .pgfx-pagination {
            display: flex;
            justify-content: space-between;
            align-items: center;
            gap: 4px;
            margin-top: 4px;
        }
        .pgfx-page-info {
            font-size: 10px;
            color: #888;
            white-space: nowrap;
        }
        .pgfx-browser-details {
            width: 160px;
            min-width: 120px;
            background: #000;
            border: 1px solid #333;
            border-radius: 4px;
            padding: 8px;
            display: flex;
            flex-direction: column;
            gap: 6px;
            font-size: 10px;
            max-height: 280px;
            overflow-y: auto;
        }
        .pgfx-details-title {
            font-weight: bold;
            text-transform: uppercase;
            color: #06b6d4;
            font-size: 11px;
            letter-spacing: 0.5px;
            border-bottom: 1px solid #333;
            padding-bottom: 4px;
        }
        .pgfx-details-row {
            display: flex;
            flex-direction: column;
            gap: 1px;
        }
        .pgfx-details-label {
            font-size: 9px;
            text-transform: uppercase;
            color: #888;
            letter-spacing: 0.5px;
        }
        .pgfx-details-value {
            color: #eee;
            word-break: break-all;
            background: #111;
            padding: 3px 5px;
            border-radius: 2px;
        }
    `;
    document.head.appendChild(style);
};

const thumbCache = new Map();

app.registerExtension({
    name: "PromptCrafter.VisualFolderLoader",
    async beforeRegisterNodeDef(nodeType, nodeData, app) {
        if (nodeData.name !== "PGFX_VisualFolderLoader") return;

        injectStyles();

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            onNodeCreated?.apply(this, arguments);
            const node = this;

            const folderWidget = node.widgets.find(w => w.name === "folder");
            const selectedImageWidget = node.widgets.find(w => w.name === "selected_image");

            selectedImageWidget.type = "hidden";

            let currentFolder = folderWidget.value || ".";
            let allSubfolders = [];

            // --- State ---
            let imageData = { images: [], total: 0, page: 0, total_pages: 1 };
            let currentPage = 0;
            const perPage = 18;

            // --- Thumbnail cache ---
            const getCachedThumb = (url) => {
                if (thumbCache.has(url)) return thumbCache.get(url);
                const img = new Image();
                img.src = url;
                thumbCache.set(url, img);
                return img;
            };

            const clearImageCache = () => {
                // Only clear image data cache, not rendered Image objects
            };

            // --- Container ---
            const container = document.createElement("div");
            container.className = "pgfx-browser-container";

            // --- Header row ---
            const headerRow = document.createElement("div");
            headerRow.className = "pgfx-browser-header";

            const title = document.createElement("span");
            title.className = "pgfx-browser-title";
            title.textContent = "PGFX Visual Browser";

            const headerToolbar = document.createElement("div");
            headerToolbar.className = "pgfx-toolbar";

            const refreshBtn = document.createElement("button");
            refreshBtn.className = "pgfx-btn";
            refreshBtn.textContent = "↻ Refresh";
            refreshBtn.onclick = async (e) => {
                e.stopPropagation();
                await loadSubfolders();
                await loadImages(0);
            };

            headerToolbar.appendChild(refreshBtn);
            headerRow.append(title, headerToolbar);
            container.appendChild(headerRow);

            // --- Breadcrumbs ---
            const breadcrumbs = document.createElement("div");
            breadcrumbs.className = "pgfx-breadcrumbs";
            container.appendChild(breadcrumbs);

            // --- Search row ---
            const searchRow = document.createElement("div");
            searchRow.style.display = "flex";
            searchRow.style.gap = "6px";
            searchRow.style.alignItems = "center";

            const searchInput = document.createElement("input");
            searchInput.className = "pgfx-browser-search";
            searchInput.placeholder = "Search images...";
            searchRow.appendChild(searchInput);
            container.appendChild(searchRow);

            // --- Main area (folder sidebar + grid + details) ---
            const mainArea = document.createElement("div");
            mainArea.className = "pgfx-browser-main";

            // Folder list sidebar
            const folderList = document.createElement("div");
            folderList.className = "pgfx-folder-list";
            mainArea.appendChild(folderList);

            // Grid area
            const gridArea = document.createElement("div");
            gridArea.className = "pgfx-grid-area";

            const grid = document.createElement("div");
            grid.className = "pgfx-browser-grid";
            gridArea.appendChild(grid);

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
            gridArea.appendChild(paginationRow);
            mainArea.appendChild(gridArea);

            // Details panel
            const detailsPanel = document.createElement("div");
            detailsPanel.className = "pgfx-browser-details";
            detailsPanel.innerHTML = '<div class="pgfx-details-title">Details</div><div style="color: #666; text-align: center; margin-top: 10px;">Select an image</div>';
            mainArea.appendChild(detailsPanel);

            container.appendChild(mainArea);

            // --- DOM Widget ---
            const widget = node.addDOMWidget("VisualBrowser", "visual_browser", container, {
                serialize: false,
                getValue() { return selectedImageWidget.value; },
                setValue(v) { selectedImageWidget.value = v; }
            });
            node.size = [680, 480];

            // --- Breadcrumb rendering ---
            const renderBreadcrumbs = () => {
                breadcrumbs.innerHTML = "";
                const segments = currentFolder === "." ? [] : currentFolder.split("/");
                const allParts = [".", ...segments];

                allParts.forEach((part, idx) => {
                    if (idx > 0) {
                        const sep = document.createElement("span");
                        sep.className = "pgfx-breadcrumb-sep";
                        sep.textContent = "/";
                        breadcrumbs.appendChild(sep);
                    }

                    const isLast = idx === allParts.length - 1;
                    if (isLast) {
                        const span = document.createElement("span");
                        span.className = "pgfx-breadcrumb-current";
                        const label = part === "." ? "Output" : part;
                        span.textContent = label;
                        breadcrumbs.appendChild(span);
                    } else {
                        const span = document.createElement("span");
                        span.className = "pgfx-breadcrumb-segment";
                        const label = part === "." ? "Output" : part;
                        span.textContent = label;
                        const path = allParts.slice(0, idx + 1).join("/");
                        span.onclick = () => navigateTo(path);
                        breadcrumbs.appendChild(span);
                    }
                });
            };

            // --- Navigation ---
            const navigateTo = async (folder) => {
                currentFolder = folder;
                folderWidget.value = folder;
                renderBreadcrumbs();
                await loadSubfolders();
                await loadImages(0);
            };

            // --- Load subfolders ---
            const loadSubfolders = async () => {
                try {
                    const resp = await api.fetchApi(`/pgfx/browser/subfolders?folder=${encodeURIComponent(currentFolder)}`);
                    const data = await resp.json();
                    allSubfolders = data.subfolders || [];

                    folderList.innerHTML = "";

                    // Parent folder item
                    if (data.parent) {
                        const parentItem = document.createElement("div");
                        parentItem.className = "pgfx-folder-item";
                        parentItem.textContent = "📁 .. (Up)";
                        parentItem.onclick = () => navigateTo(data.parent);
                        folderList.appendChild(parentItem);
                    }

                    // Subfolder items
                    allSubfolders.forEach(sf => {
                        const item = document.createElement("div");
                        item.className = "pgfx-folder-item";
                        item.textContent = "📁 " + sf;
                        item.onclick = () => {
                            const target = currentFolder === "." ? sf : currentFolder + "/" + sf;
                            navigateTo(target);
                        };
                        folderList.appendChild(item);
                    });

                    if (allSubfolders.length === 0 && !data.parent) {
                        folderList.innerHTML = '<div style="padding: 8px; font-size: 10px; color: #555; text-align: center;">No subfolders</div>';
                    }
                } catch (e) {
                    console.error("[PGFX] Error loading subfolders:", e);
                }
            };

            // --- Load images with server pagination ---
            let searchTimer = null;

            const loadImages = async (page) => {
                const folder = currentFolder;
                grid.innerHTML = '<div style="grid-column: 1/-1; text-align: center; padding: 20px; color: #666;">Loading...</div>';

                try {
                    const query = searchInput.value.trim();
                    let url = `/pgfx/browser/images?folder=${encodeURIComponent(folder)}&page=${page}&per_page=${perPage}`;
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
                    grid.innerHTML = '<div style="grid-column: 1/-1; text-align: center; padding: 20px; color: #666;">No images found</div>';
                    return;
                }

                images.forEach(imgData => {
                    const item = document.createElement("div");
                    item.className = "pgfx-browser-item";
                    if (selectedImageWidget.value === imgData.filename) {
                        item.classList.add("selected");
                    }

                    const img = document.createElement("img");
                    const thumbUrl = imgData.url + "&preview=true";
                    const cached = getCachedThumb(thumbUrl);
                    if (cached.complete && cached.naturalWidth > 0) {
                        img.src = thumbUrl;
                    } else {
                        img.src = thumbUrl;
                    }
                    img.loading = "lazy";

                    item.append(img);

                    item.onclick = () => {
                        const prevSelected = grid.querySelector(".selected");
                        if (prevSelected) prevSelected.classList.remove("selected");
                        item.classList.add("selected");
                        selectedImageWidget.value = imgData.filename;
                        updateDetails(imgData.filename);
                        node.setDirtyCanvas(true, true);
                    };

                    grid.appendChild(item);
                });
            };

            // --- Pagination controls ---
            const updatePagination = () => {
                const tp = imageData.total_pages || 1;
                pageInfo.textContent = `Page ${currentPage + 1} / ${tp} (${imageData.total} images)`;
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

            // --- Search with debounce ---
            searchInput.oninput = () => {
                if (searchTimer) clearTimeout(searchTimer);
                searchTimer = setTimeout(() => loadImages(0), 250);
            };

            // --- Details ---
            const updateDetails = async (filename) => {
                const folder = currentFolder;
                detailsPanel.innerHTML = '<div class="pgfx-details-title">Details</div><div style="color: #666; text-align: center; margin-top: 10px;">Loading...</div>';

                try {
                    const resp = await api.fetchApi(`/pgfx/browser/details?folder=${encodeURIComponent(folder)}&filename=${encodeURIComponent(filename)}`);
                    const details = await resp.json();

                    detailsPanel.innerHTML = `
                        <div class="pgfx-details-title">Details</div>
                        <div class="pgfx-details-row">
                            <span class="pgfx-details-label">Filename</span>
                            <span class="pgfx-details-value">${details.filename}</span>
                        </div>
                        <div class="pgfx-details-row">
                            <span class="pgfx-details-label">Resolution</span>
                            <span class="pgfx-details-value">${details.resolution}</span>
                        </div>
                        <div class="pgfx-details-row">
                            <span class="pgfx-details-label">File Size</span>
                            <span class="pgfx-details-value">${details.size}</span>
                        </div>
                        <div class="pgfx-details-row">
                            <span class="pgfx-details-label">Date Modified</span>
                            <span class="pgfx-details-value">${details.date}</span>
                        </div>
                        <div class="pgfx-details-row">
                            <span class="pgfx-details-label">Format</span>
                            <span class="pgfx-details-value">${details.format}</span>
                        </div>
                    `;
                } catch (e) {
                    console.error("[PGFX] Error fetching details:", e);
                    detailsPanel.innerHTML = '<div class="pgfx-details-title">Details</div><div style="color: #f44; margin-top: 10px;">Error loading details</div>';
                }
            };

            // --- Initialization ---
            const init = async () => {
                renderBreadcrumbs();
                await loadSubfolders();
                await loadImages(0);
            };

            setTimeout(init, 100);
        };

        // --- addDOMWidget shim ---
        const onNodeCreatedBase = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function() {
            if (!this.addDOMWidget) {
                this.addDOMWidget = (name, type, element, options = {}) => {
                    const widget = {
                        type: type,
                        name: name,
                        get value() { return options.getValue ? options.getValue() : element.value; },
                        set value(v) { if (options.setValue) options.setValue(v); else element.value = v; },
                        draw() {},
                        element: element,
                        options: options,
                    };

                    element.style.position = "absolute";
                    element.style.zIndex = 10;
                    this.widgets.push(widget);

                    const canvasParent = app.canvas.el.parentElement;
                    canvasParent.appendChild(element);

                    const onRemoved = this.onRemoved;
                    this.onRemoved = function() {
                        element.remove();
                        onRemoved?.apply(this, arguments);
                    };

                    const updatePosition = () => {
                        if (!this.graph || !element.parentElement) return;
                        const scale = app.canvas.ds.scale;
                        const offset = app.canvas.ds.offset;
                        const widgetIndex = this.widgets.indexOf(widget);
                        let yOffset = 0;
                        for (let i = 0; i < widgetIndex; i++) {
                            yOffset += this.widgets[i].computeSize ? this.widgets[i].computeSize()[1] : 20;
                        }
                        const x = (this.pos[0] + offset[0]) * scale;
                        const y = (this.pos[1] + offset[1] + 60 + yOffset) * scale;
                        element.style.left = `${x}px`;
                        element.style.top = `${y}px`;
                        element.style.width = `${(this.size[0] - 20) * scale}px`;
                        element.style.transformOrigin = "top left";
                        element.style.transform = `scale(${scale})`;
                        if (this.flags?.collapsed) {
                            element.style.display = "none";
                        } else {
                            element.style.display = "flex";
                        }
                    };

                    const origDraw = this.onDrawForeground;
                    this.onDrawForeground = function() {
                        updatePosition();
                        return origDraw?.apply(this, arguments);
                    };

                    return widget;
                };
            }
            onNodeCreatedBase?.apply(this, arguments);
        };
    }
});
