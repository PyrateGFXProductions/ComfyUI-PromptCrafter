import os
import sys
import subprocess
import json
from aiohttp import web
from server import PromptServer
import platform

# Ensure fonts directory exists in the custom node folder
FONTS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "fonts")
os.makedirs(FONTS_DIR, exist_ok=True)

def get_system_fonts():
    """Retrieve system fonts based on OS."""
    system_fonts = set()
    os_name = platform.system()
    
    try:
        if os_name == "Linux" or os_name == "Darwin": # macOS also has fc-list usually
            # Use fc-list to get font family names
            result = subprocess.run(["fc-list", "--format=%{family}\n"], capture_output=True, text=True, check=True)
            for line in result.stdout.split('\n'):
                if line.strip():
                    # Some fonts have multiple families comma-separated, take the first one
                    family = line.split(',')[0].strip()
                    if family:
                        system_fonts.add(family)
        elif os_name == "Windows":
            import winreg
            # Look up fonts in the registry
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts") as key:
                try:
                    for i in range(winreg.QueryInfoKey(key)[1]):
                        name, _, _ = winreg.EnumValue(key, i)
                        # Name usually looks like "Arial (TrueType)"
                        if name.endswith(" (TrueType)") or name.endswith(" (OpenType)"):
                            name = name[:name.rfind(" (")].strip()
                        if name:
                            system_fonts.add(name)
                except WindowsError:
                    pass
    except Exception as e:
        print(f"\033[93m[PGFX Font Manager] Failed to load system fonts: {e}\033[0m")
        
    return sorted(list(system_fonts))

def get_custom_fonts():
    """Retrieve list of custom uploaded fonts."""
    custom_fonts = []
    for f in os.listdir(FONTS_DIR):
        if f.lower().endswith(('.ttf', '.otf', '.woff', '.woff2')):
            # Store just the name without extension for the UI display, and the actual filename
            name = os.path.splitext(f)[0]
            custom_fonts.append({"name": name, "filename": f})
    return sorted(custom_fonts, key=lambda x: x["name"].lower())

def _route(method, path):
    instance = getattr(PromptServer, "instance", None)
    if instance is None:
        return lambda func: func
    return getattr(instance.routes, method)(path)


@_route("get", "/pgfx/fonts/list")
async def list_fonts(request):
    """Return both system and custom fonts."""
    system_fonts = get_system_fonts()
    custom_fonts = get_custom_fonts()
    return web.json_response({
        "system": system_fonts,
        "custom": custom_fonts
    })

@_route("post", "/pgfx/fonts/upload")
async def upload_font(request):
    """Save an uploaded font file to the custom fonts directory."""
    post = await request.post()
    font_file = post.get("font")
    
    if not font_file:
        return web.json_response({"error": "No font file provided"}, status=400)
        
    filename = font_file.filename
    # Sanitize filename somewhat
    filename = "".join(c for c in filename if c.isalnum() or c in " ._-")
    
    if not filename.lower().endswith(('.ttf', '.otf', '.woff', '.woff2')):
        return web.json_response({"error": "Invalid font format"}, status=400)
        
    file_path = os.path.join(FONTS_DIR, filename)
    
    # Save the file
    content = font_file.file.read()
    with open(file_path, "wb") as f:
        f.write(content)
        
    name = os.path.splitext(filename)[0]
    return web.json_response({"success": True, "name": name, "filename": filename})

@_route("get", "/pgfx/fonts/serve/{filename}")
async def serve_font(request):
    """Serve a custom font file for the browser FontFace API."""
    filename = request.match_info.get("filename", "")
    # Prevent directory traversal
    filename = os.path.basename(filename)
    
    file_path = os.path.join(FONTS_DIR, filename)
    if not os.path.exists(file_path):
        return web.Response(status=404, text="Font not found")
        
    return web.FileResponse(file_path)

print("\033[96m[PGFX Font Manager] API Routes registered.\033[0m")
