# 🔐 Auth0 Setup Guide for CognitoForge

## Prerequisites
- Auth0 account (free tier works)
- Domain for your application
- Basic understanding of OAuth 2.0

## 🚀 Quick Setup

### 1. Create Auth0 Application

1. **Login to Auth0 Dashboard**: https://auth0.com/
2. **Create New Application**:
   - Name: `CognitoForge`
   - Type: `Single Page Web Applications`
   - Technology: `React`

### 2. Configure Application Settings

In your Auth0 application settings:

**Allowed Callback URLs:**
```
http://localhost:3000,
https://your-domain.com,
https://your-vercel-deployment.vercel.app
```

**Allowed Logout URLs:**
```
http://localhost:3000,
https://your-domain.com,
https://your-vercel-deployment.vercel.app
```

**Allowed Web Origins:**
```
http://localhost:3000,
https://your-domain.com
```

**Allowed Origins (CORS):**
```
http://localhost:3000,
https://your-domain.com
```

### 3. Enable Advanced Settings

**Grant Types** (Advanced Settings → Grant Types):
- [x] Authorization Code
- [x] Refresh Token
- [x] Implicit (for fallback compatibility)

**Token Endpoint Authentication Method:**
- Select: `None` (for SPA)

### 4. Setup API (Optional for advanced features)

1. **Create API**:
   - Name: `CognitoForge API`
   - Identifier: `https://your-domain.auth0.com/api/v2/`
   - Signing Algorithm: `RS256`

2. **Scopes**:
   ```
   read:current_user
   update:current_user_metadata
   read:user_metadata
   create:user_metadata
   ```

### 5. Configure Environment Variables

In the `frontend/` directory create `.env.local`:
```bash
# Copy from frontend/.env.local.example and fill in your values
NEXT_PUBLIC_AUTH0_DOMAIN=your-domain.auth0.com
NEXT_PUBLIC_AUTH0_CLIENT_ID=your-client-id
NEXT_PUBLIC_AUTH0_AUDIENCE=https://your-domain.auth0.com/api/v2/
AUTH0_CLIENT_SECRET=your-client-secret
```

### 6. Setup User Roles (Optional)

**Create Roles** (User Management → Roles):
1. **Admin**: Full system access
2. **Security Analyst**: Can run scans and view reports
3. **Developer**: Basic scan access
4. **Viewer**: Read-only access

**Role Permissions:**
- Admin: All scopes
- Analyst: `read:scans`, `create:scans`, `read:reports`
- Developer: `read:scans`, `create:scans`
- Viewer: `read:reports`

## 🎯 Integration Points

### Frontend Integration

1. **Wrap your app** with `Auth0Provider`:
```jsx
import Auth0ProviderWithHistory from '../components/auth/Auth0Provider';

function MyApp({ Component, pageProps }) {
  return (
    <Auth0ProviderWithHistory>
      <Component {...pageProps} />
    </Auth0ProviderWithHistory>
  );
}
```

2. **Protect routes**:
```jsx
import ProtectedRoute from '../components/auth/ProtectedRoute';

function Dashboard() {
  return (
    <ProtectedRoute requiredRole="analyst">
      <DashboardContent />
    </ProtectedRoute>
  );
}
```

3. **Add login/logout**:
```jsx
import LoginButton from '../components/auth/LoginButton';
import LogoutButton from '../components/auth/LogoutButton';
import UserProfile from '../components/auth/UserProfile';
```

### Backend Integration (FastAPI)

**Install dependencies:**
```bash
pip install python-jose[cryptography] python-multipart
```

**JWT Verification middleware:**
```python
from jose import jwt
from fastapi import HTTPException, Depends
from fastapi.security import HTTPBearer

security = HTTPBearer()

def verify_token(token: str = Depends(security)):
    try:
        payload = jwt.decode(
            token.credentials,
            key=AUTH0_PUBLIC_KEY,
            algorithms=["RS256"],
            audience=AUTH0_AUDIENCE,
            issuer=f"https://{AUTH0_DOMAIN}/"
        )
        return payload
    except jwt.JWTError:
        raise HTTPException(401, "Invalid token")
```

## 🔒 Security Best Practices

1. **Never expose client secrets** in frontend code
2. **Use HTTPS** in production
3. **Implement CSRF protection**
4. **Set secure session cookies**
5. **Regular token rotation**
6. **Monitor authentication logs**

## 🐛 Troubleshooting

### Common Issues:

**1. "Callback URL mismatch"**
- Check Allowed Callback URLs in Auth0 dashboard
- Ensure exact URL match (including protocol)

**2. "Access denied"**
- Verify user has required role
- Check API permissions and scopes

**3. "Token expired"**
- Implement token refresh logic
- Check token expiration settings

**4. "CORS errors"**
- Add your domain to Allowed Origins (CORS)
- Ensure proper preflight handling

## 📊 Testing

### Test Users

Create test users with different roles:
```json
{
  "email": "admin@cognitoforge.com",
  "user_metadata": { "role": "admin" }
},
{
  "email": "analyst@cognitoforge.com", 
  "user_metadata": { "role": "analyst" }
}
```

### Test Flows

1. **Login Flow**: Test successful authentication
2. **Protected Routes**: Verify access control
3. **Token Refresh**: Test session persistence
4. **Logout**: Ensure clean session termination

## 🚀 Deployment

### Environment Variables for Production:
```bash
NEXT_PUBLIC_AUTH0_DOMAIN=production-domain.auth0.com
NEXT_PUBLIC_AUTH0_CLIENT_ID=production-client-id
AUTH0_CLIENT_SECRET=production-client-secret
NEXT_PUBLIC_BASE_URL=https://your-production-domain.com
```

### Vercel Deployment:
```bash
vercel env add NEXT_PUBLIC_AUTH0_DOMAIN
vercel env add NEXT_PUBLIC_AUTH0_CLIENT_ID
vercel env add AUTH0_CLIENT_SECRET
```

## 📈 Monitoring

**Auth0 Dashboard Metrics:**
- Login success/failure rates
- User registration trends
- Token usage patterns
- Security events

**Custom Analytics:**
- Track user engagement
- Monitor role usage
- Analyze scan patterns
- Security audit logs

---

## 🔗 Quick Links

- [Auth0 React SDK](https://auth0.com/docs/libraries/auth0-react)
- [Auth0 Dashboard](https://manage.auth0.com/)
- [JWT Debugger](https://jwt.io/)
- [Auth0 Community](https://community.auth0.com/)

---

**Need Help?** Check the Auth0 documentation or reach out to the team in our project Discord/Slack!