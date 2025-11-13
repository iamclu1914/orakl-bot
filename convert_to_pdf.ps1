# Bullseye Bot - Automated PDF Conversion Script (PowerShell)
# Requires Pandoc: https://pandoc.org/installing.html

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Bullseye Bot PDF Converter" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Check if Pandoc is installed
$pandocInstalled = Get-Command pandoc -ErrorAction SilentlyContinue
if (-not $pandocInstalled) {
    Write-Host "ERROR: Pandoc is not installed or not in PATH" -ForegroundColor Red
    Write-Host ""
    Write-Host "Please install Pandoc from: https://pandoc.org/installing.html" -ForegroundColor Yellow
    Write-Host "Or use VS Code with 'Markdown PDF' extension instead" -ForegroundColor Yellow
    Write-Host ""
    Read-Host "Press Enter to exit"
    exit 1
}

Write-Host "Pandoc found! Starting conversion..." -ForegroundColor Green
Write-Host ""

# Convert Part 1
Write-Host "[1/3] Converting Part 1 (Main Implementation)..." -ForegroundColor Yellow
try {
    pandoc BULLSEYE_BOT_COMPLETE_CODE.md -o BULLSEYE_BOT_PART1.pdf --pdf-engine=xelatex -V geometry:margin=0.75in -V fontsize=10pt --highlight-style=tango
    Write-Host "✓ Part 1 converted successfully: BULLSEYE_BOT_PART1.pdf" -ForegroundColor Green
} catch {
    Write-Host "✗ Part 1 conversion failed: $_" -ForegroundColor Red
}
Write-Host ""

# Convert Part 2
Write-Host "[2/3] Converting Part 2 (Data & Utilities)..." -ForegroundColor Yellow
try {
    pandoc BULLSEYE_BOT_PART2_DATA_UTILS.md -o BULLSEYE_BOT_PART2.pdf --pdf-engine=xelatex -V geometry:margin=0.75in -V fontsize=10pt --highlight-style=tango
    Write-Host "✓ Part 2 converted successfully: BULLSEYE_BOT_PART2.pdf" -ForegroundColor Green
} catch {
    Write-Host "✗ Part 2 conversion failed: $_" -ForegroundColor Red
}
Write-Host ""

# Create combined version
Write-Host "[3/3] Creating combined PDF..." -ForegroundColor Yellow
try {
    Get-Content BULLSEYE_BOT_COMPLETE_CODE.md, BULLSEYE_BOT_PART2_DATA_UTILS.md | Set-Content BULLSEYE_BOT_COMBINED.md
    pandoc BULLSEYE_BOT_COMBINED.md -o BULLSEYE_BOT_COMPLETE.pdf --pdf-engine=xelatex -V geometry:margin=0.75in -V fontsize=9pt --highlight-style=tango --toc --toc-depth=2
    Write-Host "✓ Combined PDF created: BULLSEYE_BOT_COMPLETE.pdf" -ForegroundColor Green
    Remove-Item BULLSEYE_BOT_COMBINED.md -ErrorAction SilentlyContinue
} catch {
    Write-Host "✗ Combined PDF conversion failed: $_" -ForegroundColor Red
}
Write-Host ""

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Conversion Complete!" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Generated files:" -ForegroundColor White
Write-Host "  • BULLSEYE_BOT_PART1.pdf (Main Implementation)" -ForegroundColor White
Write-Host "  • BULLSEYE_BOT_PART2.pdf (Data & Utilities)" -ForegroundColor White
Write-Host "  • BULLSEYE_BOT_COMPLETE.pdf (Combined)" -ForegroundColor White
Write-Host ""
Write-Host "Total: ~5,000 lines of documented code" -ForegroundColor Cyan
Write-Host ""

Read-Host "Press Enter to exit"


