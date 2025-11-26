@echo off
echo Starting Brave with remote debugging...
echo.
echo This will open Brave in a way that allows automation without detection.
echo.

start "" "C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe" --remote-debugging-port=9222 --user-data-dir="%~dp0brave-profile"

echo.
echo Brave should now be open with remote debugging enabled!
echo.
echo Next steps:
echo   1. In that Brave window, go to pathofexile.com/trade
echo   2. Login if needed
echo   3. Navigate to your live search
echo   4. Run: node poe_trade_connect_existing.js
echo.
pause

