@echo off
chcp 65001 >nul
title Dong Bo Nhom va Tu Khoa len VPS (skeyshome.io.vn)
echo Dang khoi dong tien trinh dong bo du lieu...
cd /d "%~dp0"
python sync_to_vps.py
