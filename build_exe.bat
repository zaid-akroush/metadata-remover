@echo off
echo Installing dependencies...
python -m pip install -r requirements.txt pyinstaller

echo.
echo Building MetadataRemover.exe ...
python -m PyInstaller --onefile --windowed --name MetadataRemover app.py

echo.
echo Done. Your exe is at: dist\MetadataRemover.exe
echo You can move dist\MetadataRemover.exe anywhere you like, it's fully 