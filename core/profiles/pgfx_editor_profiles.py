NAMED_EDITOR_PROFILES = {
    "None (Manual Input)": {},
    "Default (Project/Style Folders)": {
        "subfolder_template": "{project_name}/{style}",
        "filename_template": "{index:04d}_{seed}"
    },
    "Simple Project Folder": {
        "subfolder_template": "{project_name}",
        "filename_template": "scene_{index:04d}"
    },
    "Flat Output (No Subfolders)": {
        "subfolder_template": "",
        "filename_template": "{project_name}_{index:04d}"
    },
    "Date-Based Sorting": {
        "subfolder_template": "{YYYY-MM-DD}/{project_name}",
        "filename_template": "{HHMMSS}_{index:04d}"
    }
}

def get_profile_options():
    return list(NAMED_EDITOR_PROFILES.keys())