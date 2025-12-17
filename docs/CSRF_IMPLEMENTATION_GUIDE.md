# CSRF Protection Implementation Guide

**Date**: December 17, 2025  
**Version**: 2.8.0+

## Overview

CSRF (Cross-Site Request Forgery) protection has been implemented across the entire TabletTracker application using Flask-WTF. This document explains how CSRF tokens work and how to use them in your code.

---

## ✅ What's Been Fixed

### 1. **Backend (Flask-WTF)**
- ✅ CSRF protection initialized in `app/__init__.py`
- ✅ CSRF tokens automatically validated on all POST/PUT/DELETE requests
- ✅ 400 Bad Request returned if CSRF token missing or invalid

### 2. **HTML Forms**
- ✅ Added CSRF tokens to all login forms:
  - `templates/unified_login.html`
  - `templates/employee_login.html`
  - `templates/admin_login.html`

### 3. **JavaScript/AJAX**
- ✅ Added global CSRF helper functions in `templates/base.html`
- ✅ CSRF token available via meta tag
- ✅ Helper functions for automatic CSRF inclusion

---

## 🔧 How to Use CSRF Tokens

### For HTML Forms

Add this line immediately after the opening `<form>` tag:

```html
<form method="POST" action="/your-endpoint">
    <input type="hidden" name="csrf_token" value="{{ csrf_token() }}"/>
    <!-- rest of form fields -->
</form>
```

**Example**:
```html
<form method="POST" action="/submit-data" class="space-y-4">
    <input type="hidden" name="csrf_token" value="{{ csrf_token() }}"/>
    
    <div>
        <label for="name">Name</label>
        <input type="text" id="name" name="name" required>
    </div>
    
    <button type="submit">Submit</button>
</form>
```

---

### For JavaScript Fetch Calls

#### ✅ Method 1: Use `csrfFetch()` Wrapper (Recommended)

The `csrfFetch()` function automatically adds CSRF tokens to POST/PUT/DELETE requests:

```javascript
// Simple POST request
async function submitData() {
    try {
        const response = await csrfFetch('/api/your-endpoint', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({key: 'value'})
        });
        
        const result = await response.json();
        console.log(result);
    } catch (error) {
        console.error('Error:', error);
    }
}
```

#### ✅ Method 2: Use `getCSRFHeaders()` Helper

For more control, manually add CSRF headers:

```javascript
async function updateResource() {
    const response = await fetch('/api/update', {
        method: 'PUT',
        headers: getCSRFHeaders({
            'Content-Type': 'application/json'
        }),
        body: JSON.stringify({data: 'value'})
    });
    
    return await response.json();
}
```

#### ✅ Method 3: Manual Token Retrieval

Get the CSRF token directly:

```javascript
const token = getCSRFToken();

fetch('/api/endpoint', {
    method: 'POST',
    headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': token
    },
    body: JSON.stringify({data: 'value'})
});
```

---

### For FormData Submissions

When submitting forms with `FormData`:

```javascript
async function uploadFile() {
    const formData = new FormData();
    formData.append('file', fileInput.files[0]);
    formData.append('description', 'My file');
    
    // Method 1: Use csrfFetch (recommended)
    const response = await csrfFetch('/api/upload', {
        method: 'POST',
        body: formData
    });
    
    // Method 2: Add headers manually
    const response2 = await fetch('/api/upload', {
        method: 'POST',
        headers: getCSRFHeaders(), // Don't set Content-Type for FormData!
        body: formData
    });
}
```

**Note**: When using `FormData`, do NOT set `Content-Type` header. The browser will set it automatically with the correct boundary.

---

## 📋 Migration Checklist

If you have existing code that makes HTTP requests, follow these steps:

### 1. **Identify All HTTP Requests**
Search your code for:
- `fetch(`
- `XMLHttpRequest`
- Any AJAX calls

### 2. **Check HTTP Method**
- **GET requests**: No CSRF token needed ✅
- **POST/PUT/DELETE/PATCH**: CSRF token required ⚠️

### 3. **Update Your Code**

**Before** (No CSRF protection):
```javascript
const response = await fetch('/api/endpoint', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(data)
});
```

**After** (With CSRF protection):
```javascript
// Option A: Use csrfFetch wrapper
const response = await csrfFetch('/api/endpoint', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(data)
});

// Option B: Add headers manually
const response = await fetch('/api/endpoint', {
    method: 'POST',
    headers: getCSRFHeaders({'Content-Type': 'application/json'}),
    body: JSON.stringify(data)
});
```

---

## 🧪 Testing CSRF Protection

### Test 1: Valid Request
```javascript
// Should succeed
await csrfFetch('/api/test', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({test: 'data'})
});
```

### Test 2: Missing Token
```javascript
// Should fail with 400 Bad Request
await fetch('/api/test', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({test: 'data'})
    // No CSRF token - will be rejected
});
```

### Test 3: Invalid Token
```javascript
// Should fail with 400 Bad Request
await fetch('/api/test', {
    method: 'POST',
    headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': 'invalid-token'
    },
    body: JSON.stringify({test: 'data'})
});
```

---

## 🔍 Troubleshooting

### Error: "400 Bad Request: The CSRF token is missing."

**Cause**: POST/PUT/DELETE request without CSRF token.

**Fix**: 
1. Add CSRF token to HTML form: `<input type="hidden" name="csrf_token" value="{{ csrf_token() }}"/>`
2. Or use `csrfFetch()` for JavaScript requests
3. Or add CSRF headers with `getCSRFHeaders()`

### Error: "400 Bad Request: The CSRF token is invalid."

**Cause**: Token expired or doesn't match the session.

**Fix**:
1. Refresh the page to get a new token
2. Check if session expired (user needs to log in again)
3. Verify token is being extracted correctly with `getCSRFToken()`

### AJAX Request Returns 400

**Check**:
1. Is the request method POST/PUT/DELETE? (GET doesn't need CSRF)
2. Is the CSRF token included in headers?
3. Is the token value correct? (Check with `console.log(getCSRFToken())`)

### Form Submission Fails

**Check**:
1. Does the form have `<input type="hidden" name="csrf_token" value="{{ csrf_token() }}"/>`?
2. Is the input inside the `<form>` tag?
3. Is the form using `method="POST"`?

---

## 📚 Helper Functions Reference

### `getCSRFToken()`
**Returns**: `string|null` - The CSRF token or null if not found

**Description**: Retrieves the CSRF token from meta tag, hidden input, or cookie.

**Example**:
```javascript
const token = getCSRFToken();
console.log('CSRF Token:', token);
```

---

### `getCSRFHeaders(additionalHeaders)`
**Parameters**:
- `additionalHeaders` (object, optional): Additional headers to include

**Returns**: `object` - Headers object with CSRF token

**Description**: Creates a headers object with CSRF token included.

**Example**:
```javascript
const headers = getCSRFHeaders({
    'Content-Type': 'application/json',
    'Accept': 'application/json'
});
// Returns: {'X-CSRFToken': 'token...', 'X-CSRF-Token': 'token...', 'Content-Type': 'application/json', 'Accept': 'application/json'}
```

---

### `csrfFetch(url, options)`
**Parameters**:
- `url` (string): Request URL
- `options` (object, optional): Fetch options

**Returns**: `Promise<Response>` - Fetch response

**Description**: Wrapper around `fetch()` that automatically adds CSRF token for POST/PUT/DELETE/PATCH requests.

**Example**:
```javascript
const response = await csrfFetch('/api/data', {
    method: 'POST',
    body: JSON.stringify({key: 'value'})
});
```

---

## 🎯 Best Practices

### 1. **Always Use Helper Functions**
```javascript
// ✅ Good
await csrfFetch('/api/endpoint', {method: 'POST', body: data});

// ❌ Avoid
await fetch('/api/endpoint', {method: 'POST', body: data}); // Missing CSRF!
```

### 2. **Don't Hardcode Tokens**
```javascript
// ❌ Bad
const token = 'abc123xyz';

// ✅ Good
const token = getCSRFToken();
```

### 3. **Check Token Availability**
```javascript
// ✅ Good
const token = getCSRFToken();
if (!token) {
    console.error('CSRF token not found - user may need to log in');
    return;
}
```

### 4. **Use csrfFetch for All State-Changing Requests**
```javascript
// ✅ Good
await csrfFetch('/api/create', {method: 'POST', body: data});
await csrfFetch('/api/update', {method: 'PUT', body: data});
await csrfFetch('/api/delete', {method: 'DELETE'});

// GET requests don't need CSRF
await fetch('/api/data'); // ✅ OK without CSRF
```

---

## 🚨 Security Notes

1. **CSRF tokens are session-specific**: Each user session has its own token
2. **Tokens expire with session**: After logout/session timeout, new token needed
3. **Tokens are not secrets**: Safe to include in HTML/JavaScript
4. **Never disable CSRF protection**: Even for "internal" endpoints
5. **HTTPS recommended**: Always use HTTPS in production

---

## 📖 Additional Resources

- [Flask-WTF CSRF Documentation](https://flask-wtf.readthedocs.io/en/stable/csrf.html)
- [OWASP CSRF Prevention Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html)
- [MDN: Fetch API](https://developer.mozilla.org/en-US/docs/Web/API/Fetch_API)

---

## ✅ Quick Reference Card

```javascript
// HTML Form
<form method="POST">
    <input type="hidden" name="csrf_token" value="{{ csrf_token() }}"/>
    <!-- form fields -->
</form>

// JavaScript - Simple POST
await csrfFetch('/api/endpoint', {
    method: 'POST',
    body: JSON.stringify(data)
});

// JavaScript - With Headers
await csrfFetch('/api/endpoint', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(data)
});

// JavaScript - Manual Token
const token = getCSRFToken();
await fetch('/api/endpoint', {
    method: 'POST',
    headers: {
        'X-CSRFToken': token,
        'Content-Type': 'application/json'
    },
    body: JSON.stringify(data)
});
```

---

**Last Updated**: December 17, 2025  
**Applies To**: TabletTracker v2.8.0+
