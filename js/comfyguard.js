import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

app.registerExtension({
    name: "Comfy.ComfyGuard",
    async setup() {
        const response = await api.fetchApi("/comfyguard/status");
        const status = await response.json();

        // Create the button in the bottom menu
        const menu = document.querySelector(".comfy-menu");
        const btn = document.createElement("button");
        btn.style.color = status.cuda_broken ? "#ff4444" : "#44ff44";
        btn.textContent = status.cuda_broken ? "🛡️ GUARD: BORKED" : "🛡️ ComfyGuard";
        
        btn.onclick = () => {
            const modal = document.createElement("div");
            modal.style = "position:fixed; top:50%; left:50%; transform:translate(-50%,-50%); background:#222; padding:20px; border:2px solid #fff; z-index:1000;";

            const title = document.createElement("h2");
            title.textContent = "ComfyGuard Diagnostic";

            const statusMessage = document.createElement("p");
            statusMessage.textContent = status.status_msg || "";

            const suggestionList = document.createElement("ul");
            const suggestions = Array.isArray(status.suggestions) ? status.suggestions : [];
            suggestions.forEach((suggestion) => {
                const item = document.createElement("li");
                item.textContent = suggestion;
                suggestionList.appendChild(item);
            });

            const closeBtn = document.createElement("button");
            closeBtn.textContent = "Close";

            modal.append(title, statusMessage, suggestionList);

            let repairBtn = null;
            if (status.cuda_broken) {
                repairBtn = document.createElement("button");
                repairBtn.style = "background:red; color:white; padding:10px; cursor:pointer;";
                repairBtn.textContent = "FIX BROKEN CUDA NOW";
                modal.appendChild(repairBtn);
            } else {
                const healthyText = document.createElement("p");
                healthyText.textContent = "Environment is healthy.";
                modal.appendChild(healthyText);
            }

            modal.append(document.createElement("br"), closeBtn);
            document.body.appendChild(modal);

            closeBtn.onclick = () => modal.remove();
            if (repairBtn) {
                repairBtn.onclick = async () => {
                    await api.fetchApi("/comfyguard/repair", { method: "POST" });
                    alert("Repair Command Sent! Check your terminal window for progress.");
                    modal.remove();
                };
            }
        };
        menu.append(btn);
    }
});


function showRepairDialog(status) {
    const dialog = document.createElement("div");
    dialog.style = "position:fixed;top:20%;left:30%;width:40%;background:#222;color:white;padding:20px;border:2px solid #555;z-index:10001;font-family:sans-serif;box-shadow:0 0 20px black;";

    const title = document.createElement("h2");
    title.style.marginTop = "0";
    title.textContent = "🛡️ ComfyGuard Health Check";

    const messageBlock = document.createElement("div");
    messageBlock.style.fontSize = "1.1em";

    const statusLine = document.createElement("p");
    const statusPrefix = document.createTextNode(status.cuda_broken ? "🚨 " : "✅ ");
    const statusStrong = document.createElement("b");
    statusStrong.textContent = status.cuda_broken
        ? "Broken CUDA Detected!"
        : "Environment is Healthy.";
    statusLine.append(statusPrefix, statusStrong);
    messageBlock.appendChild(statusLine);

    if (status.cuda_broken) {
        const detailLine = document.createElement("p");
        detailLine.textContent = "Your Torch was downgraded to CPU mode by a recent install.";
        messageBlock.appendChild(detailLine);
    }

    const suggestions = Array.isArray(status.suggestions) ? status.suggestions : [];
    if (suggestions.length > 0) {
        const suggestionsHeader = document.createElement("b");
        suggestionsHeader.textContent = "Optimization Suggestions:";
        messageBlock.appendChild(suggestionsHeader);

        const suggestionList = document.createElement("ul");
        suggestions.forEach((suggestion) => {
            const item = document.createElement("li");
            item.textContent = suggestion;
            suggestionList.appendChild(item);
        });
        messageBlock.appendChild(suggestionList);
    }

    const controls = document.createElement("div");
    controls.style = "margin-top:20px;display:flex;justify-content:space-between;";

    const closeBtn = document.createElement("button");
    closeBtn.id = "cg-close";
    closeBtn.style.padding = "10px";
    closeBtn.textContent = "Close";
    controls.appendChild(closeBtn);

    let repairBtn = null;
    if (status.cuda_broken) {
        repairBtn = document.createElement("button");
        repairBtn.id = "cg-repair";
        repairBtn.style = "padding:10px;background:#d44;color:white;font-weight:bold;cursor:pointer;";
        repairBtn.textContent = "🛠️ ONE-CLICK REPAIR";
        controls.appendChild(repairBtn);
    }

    const utilityControls = document.createElement("div");
    utilityControls.style = "margin-top:10px; border-top:1px solid #444; padding-top:10px;";

    const generateBatBtn = document.createElement("button");
    generateBatBtn.id = "cg-gen-bat";
    generateBatBtn.style = "background:#4a4; color:white; margin-right:5px; cursor:pointer;";
    generateBatBtn.textContent = "🚀 Create Optimized .bat";

    const updateShieldBtn = document.createElement("button");
    updateShieldBtn.id = "cg-upd-shield";
    updateShieldBtn.style = "background:#44a; color:white; cursor:pointer;";
    updateShieldBtn.textContent = "🔒 Update Sticky Shield";

    utilityControls.append(generateBatBtn, updateShieldBtn);

    dialog.append(title, messageBlock, controls, utilityControls);
    document.body.appendChild(dialog);

    closeBtn.onclick = () => dialog.remove();
    
    if (repairBtn) {
        repairBtn.onclick = async () => {
            repairBtn.innerText = "Repairing... Check Terminal";
            const res = await api.fetchApi("/comfyguard/repair", { method: "POST" });
            const data = await res.json();
            alert(data.message);
            dialog.remove();
        };

        generateBatBtn.onclick = async () => {
            const res = await api.fetchApi("/comfyguard/generate_launcher", { method: "POST" });
            const data = await res.json();
            alert(data.message);
        };

        updateShieldBtn.onclick = async () => {
            await api.fetchApi("/comfyguard/update_shield", { method: "POST" });
            alert("Shield updated! All current versions are now 'Sticky'.");
        };
    }
}
