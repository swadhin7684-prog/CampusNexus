@echo off
title ChronoSync - CIT Campus Scheduling System
echo ============================================================
echo   CHRONOSYNC - Chilika Institute of Technology
echo   Intelligent Campus Scheduling and Resource Optimization
echo ============================================================
echo.
echo Opening server on: http://localhost:8000
echo Press Ctrl+C in this window anytime to stop the server.
echo.
python -m uvicorn backend.app.main:app --host 0.0.0.0 --port 8000 --reload
pause

