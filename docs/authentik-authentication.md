# Authentik OIDC Authentication for DocsGPT

This document describes how to configure and use Authentik OIDC authentication with DocsGPT.

## Overview

The Authentik integration provides enterprise-grade authentication using OpenID Connect (OIDC) protocol. It supports:

- Single Sign-On (SSO) with Authentik
- Secure JWT token validation
- User information retrieval
- Group-based access control
- Token revocation on logout

## Prerequisites

- Authentik instance (self-hosted or cloud)
- DocsGPT instance with Authentik integration
- Network connectivity between DocsGPT and Authentik

## Authentik Configuration

### 1. Create OAuth2/OpenID Provider

1. Log into your Authentik admin interface
2. Navigate to **Applications** → **Providers**
3. Create a new **OAuth2/OpenID Provider** with:
   - **Name**: `docsgpt-oidc`
   - **Authorization flow**: `default-authorization-flow`
   - **Client type**: `Confidential`
   - **Client ID**: Generate or use a custom ID (save this)
   - **Client Secret**: Generate a secure secret (save this)
   - **Redirect URIs**: 
     - `http://localhost:5173/auth/callback` (development)
     - `https://your-docsgpt-domain.com/auth/callback` (production)
   - **Scopes**: `openid`, `profile`, `email`

### 2. Create Application

1. Navigate to **Applications** → **Applications**
2. Create a new application:
   - **Name**: `DocsGPT`
   - **Slug**: `docsgpt`
   - **Provider**: Select the provider created above
   - **Launch URL**: `http://localhost:5173` (or your DocsGPT URL)

### 3. Configure Groups (Optional)

To use group-based access control:

1. Navigate to **Directory** → **Groups**
2. Create groups as needed (e.g., `docsgpt-admins`, `docsgpt-users`)
3. Assign users to appropriate groups
4. Configure the provider to include groups in tokens:
   - Edit your OAuth2/OpenID Provider
   - Go to **Advanced Settings**
   - Add custom scopes or modify token mappings to include groups

## DocsGPT Configuration

### Environment Variables

Add the following variables to your `.env` file:

```env
# Authentication Configuration
AUTH_TYPE=authentik

# Authentik OIDC Settings
AUTHENTIK_BASE_URL=https://your-authentik-instance.com
AUTHENTIK_CLIENT_ID=your-client-id
AUTHENTIK_CLIENT_SECRET=your-client-secret
AUTHENTIK_REDIRECT_URI=http://localhost:5173/auth/callback
AUTHENTIK_SCOPES=openid profile email
AUTHENTIK_VERIFY_SSL=true
```

### Configuration Options

| Variable | Description | Default | Required |
|----------|-------------|---------|----------|
| `AUTH_TYPE` | Authentication type | `None` | ✅ |
| `AUTHENTIK_BASE_URL` | Authentik instance URL | `None` | ✅ |
| `AUTHENTIK_CLIENT_ID` | OAuth2 client ID | `None` | ✅ |
| `AUTHENTIK_CLIENT_SECRET` | OAuth2 client secret | `None` | ✅ |
| `AUTHENTIK_REDIRECT_URI` | OAuth2 redirect URI | `None` | ✅ |
| `AUTHENTIK_SCOPES` | OIDC scopes | `openid profile email` | ❌ |
| `AUTHENTIK_VERIFY_SSL` | Verify SSL certificates | `true` | ❌ |

## API Endpoints

The Authentik integration adds the following REST endpoints:

### Authentication Status
```http
GET /api/auth/status
```

Returns authentication configuration and status.

**Response:**
```json
{
  "auth_type": "authentik",
  "authentik_enabled": true,
  "requires_auth": true,
  "authentik_available": true,
  "authentik_issuer": "https://auth.example.com",
  "authentik_endpoints_available": true
}
```

### Initiate Login
```http
GET /api/auth/authentik/login
```

Starts the OIDC authentication flow.

**Response:**
```json
{
  "auth_url": "https://auth.example.com/auth?client_id=...",
  "state": "csrf-protection-state"
}
```

### Handle Callback
```http
GET /api/auth/authentik/callback?code=auth_code&state=csrf_state
```

Processes OAuth2 callback and exchanges code for tokens.

**Response:**
```json
{
  "id_token": "eyJ...",
  "access_token": "eyJ...",
  "user": {
    "sub": "user123",
    "email": "user@example.com",
    "name": "John Doe",
    "groups": ["docsgpt-users"]
  },
  "expires_in": 3600,
  "token_type": "Bearer"
}
```

### Get User Info
```http
GET /api/auth/authentik/userinfo
Authorization: Bearer <access_token>
```

Retrieves current user information.

### Logout
```http
POST /api/auth/authentik/logout
Content-Type: application/json

{
  "access_token": "token_to_revoke",
  "refresh_token": "refresh_token_to_revoke"
}
```

Revokes tokens and clears session.

## Frontend Integration

The frontend needs to handle the OIDC flow:

### 1. Check Authentication Status

```javascript
const response = await fetch('/api/auth/status');
const config = await response.json();

if (config.authentik_enabled) {
  // Show Authentik login button
}
```

### 2. Initiate Login

```javascript
const response = await fetch('/api/auth/authentik/login');
const { auth_url } = await response.json();

// Redirect to Authentik
window.location.href = auth_url;
```

### 3. Handle Callback

```javascript
// In your callback route handler
const urlParams = new URLSearchParams(window.location.search);
const code = urlParams.get('code');
const state = urlParams.get('state');

if (code && state) {
  const response = await fetch(`/api/auth/authentik/callback?code=${code}&state=${state}`);
  const tokens = await response.json();
  
  // Store tokens securely
  localStorage.setItem('id_token', tokens.id_token);
  localStorage.setItem('access_token', tokens.access_token);
  
  // Redirect to main application
  window.location.href = '/';
}
```

### 4. Use Tokens in API Calls

```javascript
const idToken = localStorage.getItem('id_token');

const response = await fetch('/api/some-endpoint', {
  headers: {
    'Authorization': `Bearer ${idToken}`,
    'Content-Type': 'application/json'
  }
});
```

## Security Considerations

### Token Storage
- Store ID tokens securely (consider httpOnly cookies)
- Implement proper token refresh mechanisms
- Clear tokens on logout

### CSRF Protection
- State parameter is automatically generated and validated
- Session-based state storage prevents CSRF attacks

### SSL/TLS
- Always use HTTPS in production
- Set `AUTHENTIK_VERIFY_SSL=true` for production
- Only disable SSL verification for development/testing

### Error Handling
- All authentication errors are logged
- User-friendly error messages returned to clients
- Sensitive information not exposed in error responses

## Troubleshooting

### Common Issues

**1. "Missing required Authentik configuration"**
- Verify all required environment variables are set
- Check for typos in variable names

**2. "Failed to fetch OIDC discovery document"**
- Verify `AUTHENTIK_BASE_URL` is correct and accessible
- Check network connectivity between DocsGPT and Authentik
- Verify SSL/TLS configuration

**3. "Invalid state parameter"**
- Ensure sessions are properly configured in Flask
- Check that `app.secret_key` is set
- Verify CSRF protection is not interfering

**4. "Token validation failed"**
- Verify client ID matches Authentik configuration
- Check that Authentik issuer URL is correct
- Ensure JWKS endpoint is accessible

### Debug Mode

Enable debug logging to troubleshoot issues:

```python
import logging
logging.getLogger('application.auth.authentik').setLevel(logging.DEBUG)
logging.getLogger('application.api.auth.routes').setLevel(logging.DEBUG)
```

### Testing Configuration

Test your configuration:

```bash
# Check authentication status
curl http://localhost:7091/api/auth/status

# Initiate login (will return authorization URL)
curl http://localhost:7091/api/auth/authentik/login
```

## Migration from Other Auth Types

To migrate from existing authentication:

1. **Backup current configuration**
2. **Update environment variables** to use Authentik
3. **Test thoroughly** in development environment
4. **Deploy changes** during maintenance window
5. **Verify all users can authenticate**

### Backward Compatibility

The Authentik integration maintains full backward compatibility:
- Existing `simple_jwt` and `session_jwt` modes continue to work
- Configuration is purely additive
- No breaking changes to existing APIs

## Performance Considerations

- OIDC discovery and JWKS responses are cached
- Token validation is performed locally after initial key retrieval
- Network requests include retry logic and timeouts
- Consider implementing token refresh for long-running sessions

## Support

For issues related to:
- **Authentik configuration**: Check Authentik documentation
- **DocsGPT integration**: Create an issue in the DocsGPT repository
- **OIDC protocol**: Refer to OpenID Connect specification
