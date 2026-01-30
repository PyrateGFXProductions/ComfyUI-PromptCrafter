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
        btn.innerHTML = status.cuda_broken ? "🛡️ GUARD: BORKED" : "🛡️ ComfyGuard";
        
        btn.onclick = () => {
            const repairText = status.cuda_broken ? 
                `<button id="repair-btn" style="background:red; color:white; padding:10px; cursor:pointer;">FIX BROKEN CUDA NOW</button>` : 
                `<p>Environment is healthy.</p>`;

            const modal = document.createElement("div");
            modal.style = "position:fixed; top:50%; left:50%; transform:translate(-50%,-50%); background:#222; padding:20px; border:2px solid #fff; z-index:1000;";
            modal.innerHTML = `
                <h2>ComfyGuard Diagnostic</h2>
                <p>${status.status_msg}</p>
                <ul>${status.suggestions.map(s => `<li>${s}</li>`).join("")}</ul>
                ${repairText}
                <br><button id="close-guard">Close</button>
            `;
            document.body.appendChild(modal);

            document.getElementById("close-guard").onclick = () => modal.remove();
            if(status.cuda_broken) {
                document.getElementById("repair-btn").onclick = async () => {
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
    let message = status.cuda_broken 
        ? "🚨 <b>Broken CUDA Detected!</b><br>Your Torch was downgraded to CPU mode by a recent install."
        : "✅ <b>Environment is Healthy.</b>";
    
    if (status.suggestions.length > 0) {
        message += "<br><br><b>Optimization Suggestions:</b><ul>" + 
                   status.suggestions.map(s => `<li>${s}</li>`).join("") + "</ul>";
    }

    const dialog = document.createElement("div");
    dialog.style = "position:fixed;top:20%;left:30%;width:40%;background:#222;color:white;padding:20px;border:2px solid #555;z-index:10001;font-family:sans-serif;box-shadow:0 0 20px black;";
    dialog.innerHTML = `
        <h2 style="margin-top:0">🛡️ ComfyGuard Health Check</h2>
        <p style="font-size:1.1em">${message}</p>
        <div style="margin-top:20px;display:flex;justify-content:space-between;">
            <button id="cg-close" style="padding:10px">Close</button>
            ${status.cuda_broken ? '<button id="cg-repair" style="padding:10px;background:#d44;color:white;font-weight:bold;cursor:pointer;">🛠️ ONE-CLICK REPAIR</button>' : ''}
        </div>
        <div style="margin-top:10px; border-top:1px solid #444; padding-top:10px;">
            <button id="cg-gen-bat" style="background:#4a4; color:white; margin-right:5px; cursor:pointer;">🚀 Create Optimized .bat</button>
            <button id="cg-upd-shield" style="background:#44a; color:white; cursor:pointer;">🔒 Update Sticky Shield</button>
        </div>
    `;
    document.body.appendChild(dialog);

    document.getElementById("cg-close").onclick = () => dialog.remove();
    
    if (status.cuda_broken) {
        document.getElementById("cg-repair").onclick = async () => {
            document.getElementById("cg-repair").innerText = "Repairing... Check Terminal";
            const res = await api.fetchApi("/comfyguard/repair", { method: "POST" });
            const data = await res.json();
            alert(data.message);
            dialog.remove();
        };

        document.getElementById("cg-gen-bat").onclick = async () => {
            const res = await api.fetchApi("/comfyguard/generate_launcher", { method: "POST" });
            const data = await res.json();
            alert(data.message);
        };

        document.getElementById("cg-upd-shield").onclick = async () => {
            await api.fetchApi("/comfyguard/update_shield", { method: "POST" });
            alert("Shield updated! All current versions are now 'Sticky'.");
        };
    }
}
