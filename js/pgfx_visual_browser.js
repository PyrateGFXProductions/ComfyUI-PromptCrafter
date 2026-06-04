import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

// Helper to inject CSS
const injectStyles = () => {
    if (document.getElementById("pgfx-visual-browser-styles")) return;
    const style = document.createElement("style");
    style.id = "pgfx-visual-browser-styles";
    style.textContent = `
        .pgfx-browser-container {
            display: flex;
            flex-direction: row;
            gap: 12px;
            background: #111113;
            border: 1px solid rgba(255,255,255,0.1);
            border-radius: 8px;
            padding: 12px;
            color: white;
            font-family: 'Inter', system-ui, sans-serif;
            pointer-events: auto;
            min-height: 400px;
        }
        .pgfx-browser-main {
            display: flex;
            flex-direction: column;
            gap: 8px;
            flex: 1;
            min-width: 280px;
        }
        .pgfx-browser-details {
            width: 180px;
            background: #18181b;
            border-radius: 6px;
            padding: 10px;
            display: flex;
            flex-direction: column;
            gap: 10px;
            border-left: 1px solid #333;
            font-size: 11px;
        }
        .pgfx-details-title {
            font-family: 'Impact', 'Arial Black', sans-serif;
            text-transform: uppercase;
            color: #06b6d4;
            font-size: 14px;
            letter-spacing: 0.5px;
            border-bottom: 1px solid #333;
            padding-bottom: 4px;
            margin-bottom: 4px;
        }
        .pgfx-details-row {
            display: flex;
            flex-direction: column;
            gap: 2px;
        }
        .pgfx-details-label {
            font-family: 'Impact', 'Arial Black', sans-serif;
            font-size: 10px;
            text-transform: uppercase;
            color: #888;
            letter-spacing: 0.5px;
        }
        .pgfx-details-value {
            font-family: 'Inter', system-ui, sans-serif;
            color: #eee;
            word-break: break-all;
            background: #000;
            padding: 4px 6px;
            border-radius: 3px;
        }
        .pgfx-browser-search {
            background: #000;
            border: 1px solid #444;
            color: white;
            padding: 6px 10px;
            border-radius: 4px;
            font-size: 12px;
            outline: none;
        }
        .pgfx-browser-search:focus {
            border-color: #06b6d4;
        }
        .pgfx-browser-grid {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 8px;
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
        .pgfx-refresh-btn {
            background: #18181b;
            border: 1px solid #333;
            color: #aaa;
            padding: 2px 8px;
            border-radius: 4px;
            cursor: pointer;
            font-size: 10px;
            align-self: flex-end;
        }
        .pgfx-refresh-btn:hover {
            background: #222;
            color: white;
        }
    `;
    document.head.appendChild(style);
};

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

            // Hide the selected_image widget
            selectedImageWidget.type = "hidden";

            // Create Visual Browser Container
            const container = document.createElement("div");
            container.className = "pgfx-browser-container";

            // Left Side: Browser
            const mainContent = document.createElement("div");
            mainContent.className = "pgfx-browser-main";
            container.appendChild(mainContent);

            const headerRow = document.createElement("div");
            headerRow.style.display = "flex";
            headerRow.style.justifyContent = "space-between";
            headerRow.style.alignItems = "center";
            headerRow.style.marginBottom = "4px";

            const title = document.createElement("span");
            title.textContent = "Visual Browser";
            title.style.fontSize = "11px";
            title.style.fontWeight = "bold";
            title.style.color = "#06b6d4";

            const refreshBtn = document.createElement("button");
            refreshBtn.className = "pgfx-refresh-btn";
            refreshBtn.textContent = "Refresh Folders";
            refreshBtn.onclick = async (e) => {
                e.stopPropagation();
                await refreshFolders();
                await refreshImages();
            };

            headerRow.append(title, refreshBtn);
            mainContent.appendChild(headerRow);

            const searchInput = document.createElement("input");
            searchInput.className = "pgfx-browser-search";
            searchInput.placeholder = "🔍 Search images...";
            mainContent.appendChild(searchInput);

            const grid = document.createElement("div");
            grid.className = "pgfx-browser-grid";
            mainContent.appendChild(grid);

            // Pagination Controls
            const paginationRow = document.createElement("div");
            paginationRow.style.display = "flex";
            paginationRow.style.justifyContent = "space-between";
            paginationRow.style.alignItems = "center";
            paginationRow.style.marginTop = "8px";
            paginationRow.style.padding = "0 4px";

            const prevBtn = document.createElement("button");
            prevBtn.className = "pgfx-refresh-btn";
            prevBtn.textContent = "◀ Prev";
            prevBtn.style.padding = "4px 10px";

            const pageIndicator = document.createElement("span");
            pageIndicator.style.fontSize = "11px";
            pageIndicator.style.color = "#888";
            pageIndicator.textContent = "Pg 1 / 1";

            const nextBtn = document.createElement("button");
            nextBtn.className = "pgfx-refresh-btn";
            nextBtn.textContent = "Next ▶";
            nextBtn.style.padding = "4px 10px";

            paginationRow.append(prevBtn, pageIndicator, nextBtn);
            mainContent.appendChild(paginationRow);

            // Right Side: Details
            const detailsPanel = document.createElement("div");
            detailsPanel.className = "pgfx-browser-details";
            detailsPanel.innerHTML = '<div class="pgfx-details-title">Details</div><div style="color: #666; text-align: center; margin-top: 20px;">Select an image</div>';
            container.appendChild(detailsPanel);

            // Add DOM widget to the node
            const widget = node.addDOMWidget("VisualBrowser", "visual_browser", container, {
                serialize: false,
                getValue() { return selectedImageWidget.value; },
                setValue(v) { selectedImageWidget.value = v; }
            });

            // Adjust node size to fit browser
            node.size = [550, 480];

            let allImages = [];
            let currentPage = 0;
            const itemsPerPage = 9; // Reduced to 9 for 3x3 grid to make room for details

            const refreshFolders = async () => {
                try {
                    const response = await api.fetchApi("/pgfx/browser/folders");
                    const folders = await response.json();
                    if (folderWidget) {
                        folderWidget.options.values = folders;
                        if (!folders.includes(folderWidget.value)) {
                            folderWidget.value = folders[0] || ".";
                        }
                    }
                } catch (e) {
                    console.error("[PGFX] Error refreshing folders:", e);
                }
            };

            const refreshImages = async () => {
                const folder = folderWidget.value;
                grid.innerHTML = '<div style="grid-column: 1/-1; text-align: center; padding: 20px; color: #666;">Loading...</div>';
                
                try {
                    const response = await api.fetchApi(`/pgfx/browser/images?folder=${encodeURIComponent(folder)}`);
                    allImages = await response.json();
                    currentPage = 0;
                    renderImages();
                    
                    // If we have a selected image already, update its details
                    if (selectedImageWidget.value) {
                        updateDetails(selectedImageWidget.value);
                    }
                } catch (e) {
                    console.error("[PGFX] Error refreshing images:", e);
                    grid.innerHTML = '<div style="grid-column: 1/-1; text-align: center; padding: 20px; color: #f44;">Error loading images</div>';
                }
            };

            const updateDetails = async (filename) => {
                const folder = folderWidget.value;
                detailsPanel.innerHTML = '<div class="pgfx-details-title">Details</div><div style="color: #666; text-align: center; margin-top: 20px;">Loading...</div>';
                
                try {
                    const response = await api.fetchApi(`/pgfx/browser/details?folder=${encodeURIComponent(folder)}&filename=${encodeURIComponent(filename)}`);
                    const details = await response.json();
                    
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
                    detailsPanel.innerHTML = '<div class="pgfx-details-title">Details</div><div style="color: #f44;">Error loading details</div>';
                }
            };

            const renderImages = () => {
                grid.innerHTML = "";
                
                const query = searchInput.value.toLowerCase();
                const filtered = allImages.filter(img => img.filename.toLowerCase().includes(query));
                
                const totalPages = Math.ceil(filtered.length / itemsPerPage) || 1;
                if (currentPage >= totalPages) currentPage = Math.max(0, totalPages - 1);

                const start = currentPage * itemsPerPage;
                const end = start + itemsPerPage;
                const pageItems = filtered.slice(start, end);

                pageIndicator.textContent = `Pg ${currentPage + 1} / ${totalPages}`;
                prevBtn.disabled = currentPage === 0;
                nextBtn.disabled = (currentPage + 1) >= totalPages;

                if (pageItems.length === 0) {
                    grid.innerHTML = '<div style="grid-column: 1/-1; text-align: center; padding: 20px; color: #666;">No images found</div>';
                    return;
                }

                pageItems.forEach(imgData => {
                    const item = document.createElement("div");
                    item.className = "pgfx-browser-item";
                    if (selectedImageWidget.value === imgData.filename) {
                        item.classList.add("selected");
                    }

                    const img = document.createElement("img");
                    img.src = imgData.url + "&preview=true";
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

            searchInput.oninput = () => {
                currentPage = 0;
                renderImages();
            };

            prevBtn.onclick = (e) => {
                e.stopPropagation();
                if (currentPage > 0) {
                    currentPage--;
                    renderImages();
                }
            };

            nextBtn.onclick = (e) => {
                e.stopPropagation();
                const filtered = allImages.filter(img => img.filename.toLowerCase().includes(searchInput.value.toLowerCase()));
                if ((currentPage + 1) * itemsPerPage < filtered.length) {
                    currentPage++;
                    renderImages();
                }
            };

            // Intercept folder changes
            const origCallback = folderWidget.callback;
            folderWidget.callback = function(value, canvas, node) {
                refreshImages();
                if (this.triggerDraw) this.triggerDraw();
                else if (node && node.triggerDraw) node.triggerDraw();
                if (origCallback) return origCallback.apply(this, arguments);
            };

            // Initial load
            setTimeout(() => {
                refreshImages();
            }, 100);
        };

        // Ensure addDOMWidget helper exists on the node
        const onNodeCreatedBase = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function() {
            if (!this.addDOMWidget) {
                this.addDOMWidget = (name, type, element, options = {}) => {
                    const widget = {
                        type: type,
                        name: name,
                        get value() { return options.getValue ? options.getValue() : element.value; },
                        set value(v) { if (options.setValue) options.setValue(v); else element.value = v; },
                        draw(ctx, node, widget_width, y, widget_height) {
                            const margin = 10;
                            const elRect = element.getBoundingClientRect();
                            const top = node.pos[1] + y + margin;
                            const left = node.pos[0] + margin;
                            
                            // Align with LiteGraph zoom/pan
                            const transform = window.getComputedStyle(ctx.canvas).getPropertyValue('transform');
                            // This is a simplified approach, real ComfyUI might need more complex sync
                            // But usually append to document.body and positioning works for static zoom
                            // Better: use the built-in DOM widget support if available or shim it.
                        },
                        element: element,
                        options: options
                    };
                    
                    element.style.position = "absolute";
                    element.style.zIndex = 10;
                    
                    // ComfyUI standard: widgets are added to node.widgets
                    this.widgets.push(widget);
                    
                    // We need to attach the element to the actual DOM. 
                    // ComfyUI's internal handling of DOM widgets usually appends them to the parent of the canvas.
                    const canvasParent = app.canvas.el.parentElement;
                    canvasParent.appendChild(element);
                    
                    // Cleanup on node remove
                    const onRemoved = this.onRemoved;
                    this.onRemoved = function() {
                        element.remove();
                        onRemoved?.apply(this, arguments);
                    };
                    
                    // Positioning logic
                    const updatePosition = () => {
                        if (!this.graph || !element.parentElement) return;
                        
                        const scale = app.canvas.ds.scale;
                        const offset = app.canvas.ds.offset;
                        
                        // Find this widget's index to calculate Y
                        const widgetIndex = this.widgets.indexOf(widget);
                        let yOffset = 0;
                        for(let i=0; i<widgetIndex; i++) {
                            yOffset += this.widgets[i].computeSize ? this.widgets[i].computeSize()[1] : 20;
                        }
                        
                        // Roughly calculate position
                        const x = (this.pos[0] + offset[0]) * scale;
                        const y = (this.pos[1] + offset[1] + 60 + yOffset) * scale; // 60 for title bar + inputs
                        
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
                    
                    // Hook into graph draw
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
