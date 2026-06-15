"""Scorciatoia auto-generata da Jarvis.

    Nome     : accendi la luce
    Slug     : accendi_la_luce
    Tipo     : run_file
    Creata il: 2026-06-09T22:54:21
"""
import os, sys, subprocess, webbrowser, urllib.parse, platform

def run():
    path = "C:/Users/windows/Desktop/alexa/!accendi.bat"
    if not os.path.exists(path):
        return f"File non trovato: {path}"
    ext = os.path.splitext(path)[1].lower()
    try:
        if platform.system() == "Windows":
            if ext in (".bat", ".cmd"):
                subprocess.Popen(["cmd", "/c", path],
                                 cwd=os.path.dirname(path) or None,
                                 creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0))
            elif ext == ".ps1":
                subprocess.Popen(["powershell", "-ExecutionPolicy", "Bypass",
                                  "-File", path])
            elif ext == ".py":
                subprocess.Popen([sys.executable, path])
            else:
                os.startfile(path)
        elif platform.system() == "Darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
        return f"Eseguo {path}."
    except Exception as e:
        return f"Errore avviando {path}: {e}"


if __name__ == "__main__":
    print(run())
