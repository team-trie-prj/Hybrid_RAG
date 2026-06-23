@echo off
set CONDA=C:\Users\user\anaconda3
set PATH=%CONDA%;%CONDA%\Library\bin;%CONDA%\Scripts;%PATH%
set PYTHONUTF8=1
python "%~dp0src\server.py" %1
