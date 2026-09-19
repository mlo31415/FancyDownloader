@echo off
rem Build FancyDownloader.exe.  If FancyDownloader.ico is present it becomes the exe's icon;
rem otherwise the build proceeds with the default icon.
rem
rem Deliberately NOT --windowed -- this is a console build.  --windowed would drop the console
rem (losing the taskbar entry that carries the icon during the long run) and can leave sys.stdout
rem as None.  FancyDownloader now also opens its own live log window, but the console build is kept
rem so there is a taskbar icon and a working stdout.
rem
rem --paths=..\HelpersPackage: Log.py / HelpersPackage.py are symlinked into this folder, but PyInstaller
rem does not follow those symlinks, so point it at the real directory or the modules won't be bundled
rem (the exe fails at startup with "No module named 'Log'").
rem --collect-all pywikibot: bundle pywikibot's submodules and data files (families, i18n, ...) that it
rem loads at runtime; --copy-metadata pywikibot: pywikibot reads its own version metadata, so the
rem dist-info must be included too.
if exist FancyDownloader.ico (
    .venv12\Scripts\pyinstaller.exe --onefile --log-level=DEBUG --paths=..\HelpersPackage --collect-all pywikibot --copy-metadata pywikibot --icon=FancyDownloader.ico FancyDownloader.py
) else (
    echo No FancyDownloader.ico found -- building with the default icon.
    .venv12\Scripts\pyinstaller.exe --onefile --log-level=DEBUG --paths=..\HelpersPackage --collect-all pywikibot --copy-metadata pywikibot FancyDownloader.py
)
