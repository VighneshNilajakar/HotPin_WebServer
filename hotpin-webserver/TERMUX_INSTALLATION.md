# Termux Installation Guide

## ⚠️ CRITICAL: Use Python 3.11 (NOT 3.12)

**Problem:** Python 3.12 requires Pydantic v2, which needs Rust compilation (fails on Termux).

**Solution:** Use Python 3.11 with Pydantic v1 (no compilation needed).

## Step-by-Step Installation

### 1. Install Python 3.11
```bash
# Install Python 3.11 on Termux
pkg install python-3.11
```

### 2. Create Virtual Environment with Python 3.11
```bash
cd ~/HotPin_WebServer/hotpin-webserver

# Remove old venv if exists
rm -rf venv

# Create new venv with Python 3.11
python3.11 -m venv venv

# Activate it
source venv/bin/activate

# Verify Python version
python --version  # Should show Python 3.11.x
```

### 3. Install Requirements
```bash
# Upgrade pip
pip install --upgrade pip

# Install all requirements
pip install -r requirements-termux.txt
```

### 4. Run the Server
```bash
python -m hotpin.server
```

## Why Not Python 3.12?

| Python Version | Pydantic Version | Compilation Needed? | Works on Termux? |
|----------------|------------------|---------------------|------------------|
| 3.11 | v1.10.13 | ❌ No | ✅ Yes |
| 3.12 | v2.5.0 | ✅ Yes (Rust) | ❌ No |

**Python 3.12 Issue:**
- Changed `ForwardRef._evaluate()` API
- Pydantic v1 doesn't support it
- Pydantic v2 requires Rust (maturin)
- Rust compilation fails on Termux ARM

**Solution:** Use Python 3.11 with Pydantic v1 (no Rust needed).

## Troubleshooting

### "Command 'python3.11' not found"
```bash
pkg update
pkg install python-3.11
```

### Already have Python 3.12 venv?
```bash
# Deactivate if active
deactivate

# Remove old venv
rm -rf venv

# Create new with Python 3.11
python3.11 -m venv venv
source venv/bin/activate
```

### Verify Installation
```bash
python --version  # Must be 3.11.x
pip list | grep -E "fastapi|pydantic|pocketsphinx"
```

Should show:
- fastapi 0.68.2
- pydantic 1.10.13
- pocketsphinx 5.0.x

## Quick Commands

```bash
# Full clean install
cd ~/HotPin_WebServer/hotpin-webserver
rm -rf venv
python3.11 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements-termux.txt
python -m hotpin.server
```
