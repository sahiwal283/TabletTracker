# 🚀 TabletTracker Deployment Guide

## Quick PythonAnywhere Deployment

### 1. Pull Latest Version
```bash
cd ~/TabletTracker
git fetch origin
git reset --hard origin/main
git clean -fd
```

### 2. Create Sample Data (if Shipments page is empty)
```bash
python3 create_sample_shipments.py
```

### 3. Reload Web App
- Go to PythonAnywhere Web tab
- Click "Reload sahilk1.pythonanywhere.com"

---

## 🔧 Auto-Versioning System

### Usage Examples:
```bash
# Patch increment (1.9.4 → 1.9.5)
python3 auto_version.py "fix shipments bug"

# Minor increment (1.9.4 → 1.10.0)  
python3 auto_version.py minor "add new feature"

# Major increment (1.9.4 → 2.0.0)
python3 auto_version.py major "breaking changes"
```

### Safety Features:
- ✅ **Auto-increments version numbers**
- ✅ **Creates safety tags** with timestamps
- ✅ **Automatic git commit & push**
- ✅ **Rollback instructions provided**

### Safety Tags Format:
`v1.9.4-safe-20250826-142044`

### Emergency Rollback:
```bash
git checkout v1.9.4-safe-20250826-142044
git checkout -b emergency-rollback
git push origin emergency-rollback
```

---

## 🆘 Troubleshooting

### If Website Shows "Something went wrong"
1. Check error logs: `sahilk1.pythonanywhere.com.error.log`
2. Run diagnostic: `python3 debug_pythonanywhere.py`
3. Install dependencies: `pip install -r requirements.txt --upgrade`

### If Database Issues
```bash
python3 migrate_db.py
```

### If Shipments Page Empty
```bash
python3 create_sample_shipments.py
```

---

## 📋 Current Version: v1.9.4

### Latest Features:
- ✅ Sequential bag numbering fixed
- ✅ Pill count tracking working
- ✅ Delete with confirmation working
- ✅ **Shipments routes restored**
- ✅ **Auto-versioning system added**

### Safety Tags Available:
- `v1.9.3-perfect` - Original perfect version
- `v1.9.4-safe-20250826-142044` - Latest with shipments fix

**Always use auto-versioning for deployments to maintain safety!** 🛡️