@echo off
for /f "delims=" %%i in ('py -c "import sys,os;print(os.path.join(os.path.dirname(sys.executable),'pythonw.exe'))"') do set PYTHONW=%%i
start "" "%PYTHONW%" "%~dp0main.py"
